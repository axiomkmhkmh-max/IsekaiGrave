"""پنل و دستورهای ادمین."""

import asyncio
import time
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message

from config import ADMIN_IDS, BOT_STARTED
from database import store
from intents import (
    ADMIN_BAN_RE, ADMIN_BROADCAST_RE, ADMIN_CLEAN_RE, ADMIN_HEALTH_RE, ADMIN_KILL_RE,
    ADMIN_PANEL_RE, ADMIN_STATS_RE, ADMIN_UNBAN_RE,
)
from players import reincarnate
from render import render_rebirth
from ui import btn, kb, panel
from utils import esc, spawn, utcnow, _bg_tasks


# ───────────────────────────── 🛠 پنل ادمین ─────────────────────────────
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def admin_kb(uid: int) -> InlineKeyboardMarkup:
    return kb(
        [btn("📊 آمار ربات", f"adm:stats:{uid}", "blue"), btn("🩺 سلامت سرور", f"adm:health:{uid}", "green")],
        [btn("🧹 پاکسازی دیتابیس", f"adm:clean:{uid}", "red"), btn("📖 دستورها", f"adm:help:{uid}", "blue")],
    )


ADMIN_HELP = [
    "فرمان‌های ادمین (متنی):",
    "• <b>آمار ربات</b> ← آمار کلی",
    "• <b>سلامت سرور</b> ← وضعیت MongoDB و آپتایم",
    "• <b>پاکسازی</b> ← حذف رکوردهای منقضی",
    "• <b>بن [user_id]</b> / <b>آنبن [user_id]</b> (یا ریپلای + «بن»)",
    "• <b>کشتن [user_id]</b> ← ارسال اجباری به ایسکا",
    "• <b>سراسری [متن]</b> ← پیام همگانی به همه‌ی کاربران و گروه‌ها",
]


async def admin_stats() -> str:
    day_ago = utcnow() - timedelta(hours=24)
    u_count = await store.users.count_documents({})
    reg = await store.users.count_documents({"registered": True})
    banned = await store.users.count_documents({"banned": True})
    active = await store.users.count_documents({"last_seen": {"$gt": day_ago}})
    married = await store.users.count_documents({"spouse": {"$ne": None}})
    g_count = await store.guilds.count_documents({})
    gr_count = await store.groups.count_documents({})
    raids_won = await store.raids.count_documents({"status": "won"})
    d_res = await store.users.aggregate([{"$group": {"_id": None, "t": {"$sum": "$death_count"}}}]).to_list(1)
    deaths = d_res[0]["t"] if d_res else 0
    gs_res = await store.users.aggregate([{"$group": {"_id": None, "t": {"$sum": "$gold"}}}]).to_list(1)
    eco = await store.meta.find_one({"_id": "economy"}) or {}
    active_l = await store.listings.count_documents({"status": "active"})
    sold_l = await store.listings.count_documents({"status": "sold"})
    return panel("blue", "📊", "آمار حیاتی ربات", [
        f"🪙 GS در گردش: <b>{(gs_res[0]['t'] if gs_res else 0):,}</b>  |  🔥 سوخته‌شده: <b>{int(eco.get('burned', 0)):,}</b>",
        f"🪦 آگهی فعال: <b>{active_l}</b>  |  معامله‌ی انجام‌شده: <b>{sold_l}</b>",
        f"👤 کل کاربران: <b>{u_count}</b>  (ثبت‌نام‌شده: {reg})",
        f"🔥 فعال در ۲۴ ساعت: <b>{active}</b>",
        f"🚫 بن‌شده: <b>{banned}</b>",
        f"☠️ مجموع مرگ‌ومیرها: <b>{deaths}</b>",
        f"🛡 گیلدها: <b>{g_count}</b>  |  👥 گروه‌ها: <b>{gr_count}</b>",
        f"💍 متأهل‌ها: <b>{married}</b>  |  🐉 باس‌های کشته‌شده: <b>{raids_won}</b>",
    ])


async def admin_health() -> str:
    t0 = time.time()
    try:
        await store.users.database.command("ping")
        ping = f"✅ MongoDB پاسخ داد ({int((time.time() - t0) * 1000)}ms)"
    except Exception as e:
        ping = f"❌ MongoDB: {esc(str(e)[:80])}"
    up = int(time.time() - BOT_STARTED)
    return panel("green", "🩺", "سلامت سیستم", [
        ping,
        f"⏱ آپتایم: {up // 3600} ساعت و {(up % 3600) // 60} دقیقه",
        f"🧵 تسک‌های پس‌زمینه: {len(_bg_tasks)}",
        f"🔑 ادمین‌ها: {len(ADMIN_IDS)}",
    ])


async def admin_clean() -> str:
    cut = utcnow() - timedelta(days=1)
    r1 = await store.offers.delete_many({"status": {"$ne": "open"}, "created_at": {"$lt": cut}})
    r2 = await store.duels.delete_many({"status": {"$ne": "pending"}, "created_at": {"$lt": cut}})
    r3 = await store.drops.delete_many({"status": {"$ne": "open"}, "created_at": {"$lt": cut}})
    r4 = await store.proposals.delete_many({"expires_at": {"$lt": cut}})
    r5 = await store.raids.delete_many({"status": {"$ne": "active"}, "created_at": {"$lt": utcnow() - timedelta(days=3)}})
    return panel("red", "🧹", "پاکسازی انجام شد", [
        f"🕶 پیشنهادهای بازار سیاه: {r1.deleted_count}",
        f"⚔️ دوئل‌ها: {r2.deleted_count}",
        f"🎁 صندوق/بمب: {r3.deleted_count}",
        f"💍 خواستگاری‌ها: {r4.deleted_count}",
        f"🐉 باس‌ها: {r5.deleted_count}",
    ])


async def broadcast(bot: Bot, admin_chat: int, text: str):
    ok = fail = 0
    targets = [u["user_id"] async for u in store.users.find({"banned": {"$ne": True}}, {"user_id": 1})]
    targets += [g["chat_id"] async for g in store.groups.find({}, {"chat_id": 1})]
    body = panel("purple", "📢", f"پیام همگانی ایزدبانو", [text])
    for cid in targets:
        try:
            await bot.send_message(cid, body)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.06)  # جلوگیری از Flood
    try:
        await bot.send_message(admin_chat, f"✅ پیام همگانی تموم شد.\nموفق: {ok}\nناموفق: {fail}")
    except Exception:
        pass


def admin_target(m, g: Optional[str]) -> Optional[int]:
    if g and g.strip().isdigit():
        return int(g.strip())
    if m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user.id
    return None


async def handle_admin_commands(m: Message, bot: Bot, c: str) -> bool:
    uid = m.from_user.id
    if not is_admin(uid):
        return False
    if ADMIN_PANEL_RE.fullmatch(c):
        await m.reply(panel("red", "🛠", "پنل مدیریت ادمین", ADMIN_HELP), reply_markup=admin_kb(uid))
        return True
    if ADMIN_STATS_RE.fullmatch(c):
        await m.reply(await admin_stats())
        return True
    if ADMIN_HEALTH_RE.fullmatch(c):
        await m.reply(await admin_health())
        return True
    if ADMIN_CLEAN_RE.fullmatch(c):
        await m.reply(await admin_clean())
        return True
    if bm := ADMIN_BAN_RE.fullmatch(c):
        tid = admin_target(m, bm.group(2))
        if not tid:
            return False
        await store.users.update_one({"user_id": tid}, {"$set": {"banned": True, "opted_out": True}})
        await m.reply(f"🚫 کاربر <code>{tid}</code> بن شد.")
        return True
    if ubm := ADMIN_UNBAN_RE.fullmatch(c):
        tid = admin_target(m, ubm.group(2))
        if not tid:
            return False
        await store.users.update_one({"user_id": tid}, {"$set": {"banned": False, "opted_out": False}})
        await m.reply(f"✅ کاربر <code>{tid}</code> آنبن شد.")
        return True
    if km := ADMIN_KILL_RE.fullmatch(c):
        tid = int(km.group(1))
        if not await store.get(tid):
            await m.reply("❌ کاربر پیدا نشد.")
            return True
        rdoc, new = await reincarnate(tid, forced=True)
        await m.reply(f"⚡ ادمین حکم مرگ کاربر <code>{tid}</code> رو صادر کرد!\n\n{render_rebirth(rdoc, new)}")
        return True
    raw = (m.text or "").strip()
    if bcm := ADMIN_BROADCAST_RE.match(raw):
        await m.reply("⏳ پیام همگانی تو صف ارسال قرار گرفت…")
        spawn(broadcast(bot, m.chat.id, bcm.group(1)))
        return True
    return False
