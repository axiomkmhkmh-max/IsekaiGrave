"""باس گروهی (سیاه‌چاله‌ی چندنفره)."""

import asyncio
import random
import time
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from pymongo import ReturnDocument

from battle_engine import BOSS_COUNTER, FATE_COST, MAX_SOUL, RAGE_MAX, raid_base_damage, raid_fate
from config import GS, log, RAID_COOLDOWN, RAID_HIT_COOLDOWN, RAID_TTL
from content import BOSS_HITS, BOSSES
from database import store
from economy import terr_perks
from players import adjust_survival, grant, heal_bonus
from rules import gear_bonus
from quests import quest_progress
from render import display
from ui import btn, kb, panel, say
from utils import esc, is_group, spawn, utcnow


_last_raid_hit: dict = {}


# ───────────────────────────── 🐉 باس گروهی (سیاه‌چاله‌ی چندنفره) ─────────────────────────────
def boss_bar(hp: int, mx: int) -> str:
    n = max(0, min(10, round(10 * max(hp, 0) / mx))) if mx else 0
    return "▰" * n + "▱" * (10 - n)


async def active_raid(chat_id: int) -> Optional[dict]:
    return await store.raids.find_one({"chat_id": chat_id, "status": "active", "expires_at": {"$gt": utcnow()}})


def raid_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn("⚔️ ضربه (+۱🕯)", "raid:hit:0", "red"), btn("🛡 سپر (+۱🕯)", "raid:ward:0", "blue")],
        [btn("🌀 رشته‌ی سرنوشت (۳🕯)", "raid:fate:0", "green"), btn("📊 وضعیت", "raid:st:0", "blue")],
    )


def _soul(n: int) -> str:
    return "●" * n + "○" * (MAX_SOUL - n)


def rage_line(r: dict) -> str:
    rage = int(r.get("rage", 0))
    bar = "🔥" * rage + "▫️" * (RAGE_MAX - rage)
    warn = ""
    if rage >= RAGE_MAX - 1:
        warn = f"\n⚠️ <b>باس شارژ شده!</b> ضربه‌ی بعدی → پاسخِ سنگین (−{BOSS_COUNTER}٪ بقا) به همه‌ی ضربه‌زننده‌های این دور؛ «🛡 سپر» دفعش می‌کنه!"
    return f"😡 خشمِ باس: {bar}{warn}"


async def spawn_raid(bot: Bot, chat_id: int, caller: Optional[str] = None) -> str:
    """'ok' | 'active' | 'cool'"""
    if await active_raid(chat_id):
        return "active"
    last = await store.raids.find({"chat_id": chat_id}).sort("created_at", -1).limit(1).to_list(1)
    if last and (utcnow() - last[0]["created_at"]).total_seconds() < RAID_COOLDOWN:
        return "cool"
    members = await store.users.count_documents({"chats": chat_id})
    mx = 300 + 90 * max(1, min(members, 12))
    name, icon = random.choice(BOSSES)
    res = await store.raids.insert_one({
        "chat_id": chat_id, "name": name, "icon": icon, "hp": mx, "max_hp": mx, "dmg": {}, "names": {}, "soul": {}, "ward": {}, "rage": 0, "window": [],
        "status": "active", "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=RAID_TTL),
    })
    who = f"{esc(caller)} با یه ورد مشکوک" if caller else "از شکاف دروازه‌ی آخر"
    await bot.send_message(chat_id, panel("red", icon, f"باس ظاهر شد: {name}", [
        f"💥 {who} <b>{esc(name)}</b> رو احضار کرد!",
        f"❤️ HP: <b>{mx}</b> {boss_bar(mx, mx)}",
        "👥 همه با هم حمله کنید! «<b>حمله به باس</b>» یا دکمه‌ها: ⚔️ ضربه · 🛡 سپر · 🌀 رشته‌ی سرنوشت (با ۳🕯).",
        f"🧿 باس هر {RAGE_MAX} ضربه خشمگین میشه و به همه‌ی ضربه‌زننده‌ها جواب میده؛ سپر بزنین!",
        f"⏳ {RAID_TTL // 60} دقیقه وقت دارید. غنیمت بین همه‌ی حمله‌کننده‌ها تقسیم میشه؛ هر کی بیشتر ضربه بزنه، جایزه‌ی ویژه می‌گیره! 🎁",
    ], "💅 <i>«من فقط تماشا می‌کنم. هر کی ترسید و فرار کرد، اسمش رو تو دفترم می‌نویسم.»</i>"), reply_markup=raid_kb())
    spawn(raid_timer(bot, chat_id, res.inserted_id, RAID_TTL))
    return "ok"


async def raid_timer(bot: Bot, chat_id: int, rid, ttl: int):
    try:
        await asyncio.sleep(ttl)
        r = await store.raids.find_one_and_update({"_id": rid, "status": "active"}, {"$set": {"status": "lost"}})
        if r:
            await bot.send_message(chat_id, panel("black", r["icon"], "باس فرار کرد!", [
                f"{esc(r['name'])} با بقایای HP خودش ({max(int(r['hp']), 0)}) توی مه ناپدید شد.",
                "این بار غنیمتی نیست. دفعه‌ی بعد با هماهنگی بیشتر امتحان کنید! 💪",
            ], "💅 <i>«گروه شما فقط یه استعداد داره: فرار. احمق‌ها.»</i>"))
    except Exception:
        log.exception("raid_timer failed")


async def do_boss_call(m, bot: Bot) -> bool:
    if not is_group(m):
        await say(m, "باس مخصوص گروه‌هاست؛ تنهایی نمی‌شه باهاش جنگید. ربات رو ببر تو یه گروه! 🐉", "🐉", "باس", "red")
        return True
    st = await spawn_raid(bot, m.chat.id, m.from_user.full_name)
    if st == "active":
        await say(m, "یه باس همین الان زنده‌ست! بنویس «حمله به باس» یا دکمه‌ی پایین رو بزن. 🐉", "🐉", "باس", "red", raid_kb())
    elif st == "cool":
        await say(m, "این گروه تازه یه باس رو شکست داده. هر ۲ ساعت فقط یه باس میاد؛ بعداً دوباره امتحان کنین. ⏳", "🐉", "باس", "red")
    return True


async def do_boss_status(m):
    if not is_group(m):
        await say(m, "باس تو گروه‌ها ظاهر میشه. ربات رو به گروهت اضافه کن! 🐉", "🐉", "باس", "red")
        return
    r = await active_raid(m.chat.id)
    if not r:
        await m.reply(panel("red", "🐉", "باس گروه", [
            "الان هیچ باسی زنده نیست.",
            "با «<b>احضار باس</b>» یکی رو صدا بزنید (هر ۲ ساعت). گاهی هم خودش بی‌دعوت میاد!",
        ]), reply_markup=kb([btn("🐉 احضار باس", f"raid:call:0", "red")]))
        return
    left = max(1, int((r["expires_at"] - utcnow()).total_seconds()) // 60)
    top = sorted(r["dmg"].items(), key=lambda x: -x[1])[:5]
    lines = [f"❤️ HP: <b>{max(int(r['hp']), 0)}/{r['max_hp']}</b> {boss_bar(int(r['hp']), r['max_hp'])}",
             rage_line(r), f"⏳ ~{left} دقیقه مونده", "┈┈┈┈┈┈┈┈┈┈"]
    if top:
        lines.append("🏅 <b>بیشترین ضربه:</b>")
        lines += [f"{i}. {esc(r['names'].get(u, '؟'))} — {d} 💥" for i, (u, d) in enumerate(top, 1)]
    else:
        lines.append("هنوز کسی بهش ضربه نزده. شجاع‌ها کجان؟")
    await m.reply(panel("red", r["icon"], r["name"], lines), reply_markup=raid_kb())


async def do_raid_hit(m, move: str = "strike") -> bool:
    """move: strike | ward | fate — تاکتیکِ باس: روح جمع کن، سپر بزن، رشته‌ی سرنوشت رو سرِ وقت آزاد کن."""
    if not is_group(m):
        return False
    r = await active_raid(m.chat.id)
    if not r:
        return False
    uid = m.from_user.id
    now = time.time()
    if now - _last_raid_hit.get(uid, 0) < RAID_HIT_COOLDOWN:
        await say(m, f"دستت هنوز می‌لرزه! {RAID_HIT_COOLDOWN} ثانیه صبر کن. 💪", "🐉", "باس", "red")
        return True
    doc = await store.get(uid)
    name = m.from_user.full_name
    key = str(uid)
    soul = int((r.get("soul") or {}).get(key, 0))
    has_ward = bool((r.get("ward") or {}).get(key))

    if move == "ward":
        if has_ward:
            await say(m, "سپرت همین الان بالاست! 🛡", "🛡", "باس", "red")
            return True
        _last_raid_hit[uid] = now
        r2 = await store.raids.find_one_and_update(
            {"_id": r["_id"], "status": "active"},
            {"$set": {f"ward.{key}": True, f"soul.{key}": min(MAX_SOUL, soul + 1), f"names.{key}": name}},
            return_document=ReturnDocument.AFTER)
        if not r2:
            return False
        await m.reply(panel("blue", "🛡", r["name"], [
            f"{display(doc, link=True)} سپرِ روح بالا برد — اولین پاسخِ باس رو دفع می‌کنه.",
            f"🕯 روحِ تو: {_soul(min(MAX_SOUL, soul + 1))}", rage_line(r2),
        ]), reply_markup=raid_kb())
        return True

    fate = None
    if move == "fate":
        if soul < FATE_COST:
            await say(m, f"رشته‌ی سرنوشت {FATE_COST} روح می‌خواد و تو {soul} تا داری. با ضربه یا سپر روح جمع کن! 🕯", "🌀", "باس", "red")
            return True
        fate = raid_fate(doc.get("cls"))
    _last_raid_hit[uid] = now

    perks = await terr_perks(doc)
    gear = gear_bonus((doc.get("equip") or {}).get("item"))
    base = raid_base_damage(doc, gear, perks)
    dmg = int(base * (fate["mult"] if fate else 1))
    new_soul = min(MAX_SOUL, soul - FATE_COST + fate["refund"]) if fate else min(MAX_SOUL, soul + 1)
    rage_inc = fate["rage"] if fate else 1
    r2 = await store.raids.find_one_and_update(
        {"_id": r["_id"], "status": "active"},
        {"$inc": {"hp": -dmg, f"dmg.{uid}": dmg, "rage": rage_inc},
         "$set": {f"names.{key}": name, f"soul.{key}": new_soul}, "$addToSet": {"window": uid}},
        return_document=ReturnDocument.AFTER,
    )
    if not r2:
        return False
    icon = "🌀" if fate else random.choice(["⚔️", "🗡", "🔥", "⚡"])
    lines = [f"{icon} {display(doc, link=True)} {random.choice(BOSS_HITS)}: <b>{dmg}</b>" + (" 🌀 <b>رشته‌ی سرنوشت!</b>" if fate else "")]
    if fate and fate["heal"]:
        h = heal_bonus(doc, fate["heal"])
        await adjust_survival(uid, h)
        lines.append(f"💚 نفَسِ بازتولد: +{h}٪ بقا")
    hp = max(int(r2["hp"]), 0)
    won = False
    if r2["hp"] <= 0:
        won = bool(await store.raids.find_one_and_update({"_id": r["_id"], "status": "active"}, {"$set": {"status": "won"}}))
    elif int(r2.get("rage", 0)) >= RAGE_MAX:
        # 🔥 باس خشمگین میشه: فقط یک نفر (برندهی این آپدیت) پاسخ رو اعمال می‌کنه
        claim = await store.raids.find_one_and_update(
            {"_id": r["_id"], "status": "active", "rage": {"$gte": RAGE_MAX}},
            {"$set": {"rage": 0, "window": [], "ward": {}}}, return_document=ReturnDocument.BEFORE)
        if claim:
            lines.append(f"😡 <b>{esc(r['name'])} خشمگین شد!</b>")
            wards = claim.get("ward") or {}
            for u in (claim.get("window") or [])[:12]:
                nm = esc(claim.get("names", {}).get(str(u), "؟"))
                if wards.get(str(u)):
                    lines.append(f"🛡 {nm}: سپر دفعش کرد!")
                else:
                    await adjust_survival(u, -BOSS_COUNTER)
                    lines.append(f"🩸 {nm}: −{BOSS_COUNTER}٪ بقا")
            r2["rage"] = 0
    lines.append(f"❤️ {r2['icon']} {hp}/{r2['max_hp']} {boss_bar(hp, r2['max_hp'])}")
    lines.append(f"🕯 روحِ تو: {_soul(new_soul)}" + ("  — رشته‌ی سرنوشت آماده‌ست!" if new_soul >= FATE_COST else ""))
    if not won:
        lines.append(rage_line(r2))
    await m.reply(panel("red", r2["icon"], r2["name"], lines), reply_markup=None if won else raid_kb())
    await quest_progress(m, "boss")
    if won:
        await raid_victory(m, r2)
    return True


async def raid_victory(m, r: dict):
    dmg = {int(u): int(d) for u, d in r["dmg"].items()}
    total = max(1, sum(dmg.values()))
    pool = 200 + 30 * len(dmg)
    top_uid = max(dmg, key=dmg.get)
    lines = [f"🏆 <b>{esc(r['name'])} شکست خورد!</b> 🎉", "┈┈┈┈┈┈┈┈┈┈"]
    for u, d in sorted(dmg.items(), key=lambda x: -x[1]):
        gold = int(pool * d / total) + 30   # (بعد از سقف روزانه‌ی GS تعدیل میشه)
        item = None
        if u == top_uid:
            item = f"👑 {random.choice(['پوستِ', 'دندانِ', 'تاجِ', 'قلبِ'])} {r['name']} ‹غنیمت باس›"
        await grant(u, gold=gold, xp=60, item=item)
        lines.append(f"{'🥇' if u == top_uid else '•'} {esc(r['names'].get(str(u), '؟'))} — 💥{d}  🪙+{gold} {GS}" + (" 🎁 غنیمتِ ویژه" if item else ""))
    await m.reply(panel("green", "🏆", "غنایمِ باس", lines,
                        "💅 <i>«…بد نبود. ولی غنیمت رو خرج کن، قبل از این‌که برگردم و پسش بگیرم.»</i>"))
