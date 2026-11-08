"""ابزارهای گسترده‌ی ادمین: پروندهٔ بازیکن، اقتصاد، گیلد/قلمرو، جهان/باس، ارتباطات و سیستم.

همه‌ی دستورها هم متنی‌ان (فارسی) و هم اسلش (/user، /givegs، …)؛ اسلش‌ها تو commands.py به همین عبارت‌ها تبدیل میشن.
گزارش‌های بدون آرگومان (REPORTS) هم از دکمه‌های پنل اجرا میشن و هم از متن، پس منطق فقط یک‌جاست.
تغییرهای حساس (GS، سطح، حذف گیلد، بارش همگانی) تو لاگ‌چنل «ممیزی» میشن و GS تو دفتر تراکنش ثبت میشه."""

import csv
import io
import re
import time
from datetime import timedelta
from typing import Awaitable, Callable, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup
from pymongo import ReturnDocument

from config import ADMIN_IDS, BOT_STARTED, GS, log
from database import store
from economy import credit, debit, log_tx
from ui import btn, kb, panel, safe_edit
from utils import esc, utcnow

MAX_GS = 10_000_000
CONFIRM = "تایید"
_LIMIT = 3800          # سقفِ امنِ طولِ پیام تلگرام (۴۰۹۶)


# ───────────────────────────── 🧰 ابزارهای کوچک ─────────────────────────────
def n(x) -> str:
    try:
        return f"{int(x or 0):,}"
    except (TypeError, ValueError):
        return "0"


def ago(dt) -> str:
    if not dt:
        return "—"
    try:
        s = int((utcnow() - dt).total_seconds())
    except Exception:
        return "—"
    if s < 60:
        return "همین الان"
    if s < 3600:
        return f"{s // 60} دقیقه پیش"
    if s < 86400:
        return f"{s // 3600} ساعت پیش"
    return f"{s // 86400} روز پیش"


def ptxt(color: str, icon: str, title: str, lines: list, foot: Optional[str] = None) -> str:
    """پنل با برشِ ایمن (اگه خیلی بلند شد، ته‌شو می‌بره)."""
    out = panel(color, icon, title, lines, foot)
    if len(out) > _LIMIT:
        keep, size = [], 0
        for ln in lines:
            size += len(ln) + 1
            if size > _LIMIT - 400:
                keep.append("…")
                break
            keep.append(ln)
        out = panel(color, icon, title, keep, foot)
    return out


def uname(d: dict) -> str:
    u = d.get("username")
    return f"{esc(d.get('first_name') or 'ناشناس')}" + (f" @{esc(u)}" if u else "")


def audit(m, text: str):
    """ثبتِ اقدامِ ادمین تو لاگ‌چنل (هیچ‌وقت خطا نمیده)."""
    try:
        import logchannel
        logchannel.event(f"🛠 <b>ادمین</b> {esc(m.from_user.full_name)} <code>{m.from_user.id}</code>\n{text}")
    except Exception:
        log.exception("admin audit failed")


async def dm(bot: Bot, uid: int, text: str):
    try:
        await bot.send_message(uid, text)
    except Exception:
        pass


async def find_user(tok: Optional[str]) -> Optional[dict]:
    tok = (tok or "").strip()
    if tok.startswith("@"):
        return await store.users.find_one({"username_lower": tok[1:].lower()})
    if tok.isdigit():
        return await store.get(int(tok))
    return None


def split_target(m, args: Optional[str]) -> tuple:
    """(توکنِ هدف یا None، باقی توکن‌ها). هدف = آیدی عددی (≥۶ رقم) یا @یوزرنیم یا ریپلای."""
    toks = (args or "").split()
    if toks and (toks[0].startswith("@") or (toks[0].isdigit() and len(toks[0]) >= 6)):
        return toks[0], toks[1:]
    rp = getattr(m, "reply_to_message", None)
    if rp and rp.from_user:
        return str(rp.from_user.id), toks
    return None, toks


async def target_doc(m, args: Optional[str]) -> tuple:
    """(doc, rest) یا (None, rest) با پیامِ خطا به ادمین."""
    tok, rest = split_target(m, args)
    if not tok:
        await m.reply("❌ هدف مشخص نیست. آیدی عددی، @یوزرنیم یا ریپلای بده.")
        return None, rest
    doc = await find_user(tok)
    if not doc:
        await m.reply("❌ این کاربر تو دیتابیس نیست.")
        return None, rest
    return doc, rest


def amount_of(rest: list, lo: int = 1, hi: int = MAX_GS) -> Optional[int]:
    if rest and rest[0].isdigit():
        v = int(rest[0])
        if lo <= v <= hi:
            return v
    return None


async def find_guild(name: str) -> Optional[dict]:
    name = (name or "").strip()
    if not name:
        return None
    g = await store.guilds.find_one({"name_lower": name.lower()})
    if g:
        return g
    from utils import clean, norm
    want = clean(norm(name))
    async for x in store.guilds.find({}).limit(300):
        if clean(norm(x.get("name", ""))) == want:
            return x
    return None


def terr_key(tok: str) -> Optional[str]:
    from content import TERRITORIES
    from territories import find_terr
    tok = (tok or "").lower()
    return tok if tok in TERRITORIES else find_terr(tok)


# ───────────────────────────── 📊 گزارش‌های بدون آرگومان ─────────────────────────────
# هر گزارش: async fn(bot, chat_id) → متنِ HTML (یا None اگه خودش فرستاده)
async def rep_economy(bot, chat_id):
    since = utcnow() - timedelta(hours=24)
    agg = await store.users.aggregate([
        {"$match": {"registered": True, "banned": {"$ne": True}}},
        {"$group": {"_id": None, "t": {"$sum": "$gold"}, "mx": {"$max": "$gold"}, "c": {"$sum": 1}}},
    ]).to_list(1)
    total, mx, cnt = (agg[0]["t"], agg[0]["mx"], agg[0]["c"]) if agg else (0, 0, 0)
    top10 = await store.users.find({"registered": True, "banned": {"$ne": True}}, {"gold": 1}).sort("gold", -1).limit(10).to_list(10)
    share = int(sum(int(x.get("gold", 0)) for x in top10) * 100 / total) if total else 0
    eco = await store.meta.find_one({"_id": "economy"}) or {}
    flow = {r["_id"]: r async for r in store.ledger.aggregate([
        {"$match": {"at": {"$gte": since}}},
        {"$group": {"_id": {"$cond": [{"$gt": ["$delta", 0]}, "in", "out"]}, "s": {"$sum": "$delta"}, "c": {"$sum": 1}}},
    ])}
    by = sorted((eco.get("burned_by") or {}).items(), key=lambda kv: -int(kv[1]))[:6]
    lines = [
        f"🪙 {GS} در گردش: <b>{n(total)}</b>  |  میانگین: <b>{n(total / cnt) if cnt else 0}</b>",
        f"👑 ثروتمندترین: <b>{n(mx)}</b>  |  سهمِ ۱۰ نفرِ اول: <b>{share}٪</b>",
        f"🔥 کلِ سوخته‌شده: <b>{n(eco.get('burned', 0))}</b>",
        "┈┈┈┈┈┈┈┈┈┈",
        f"📥 ورودیِ ۲۴ ساعت (دفتر): <b>{n(flow.get('in', {}).get('s', 0))}</b> در {n(flow.get('in', {}).get('c', 0))} تراکنش",
        f"📤 خروجیِ ۲۴ ساعت (دفتر): <b>{n(abs(flow.get('out', {}).get('s', 0)))}</b> در {n(flow.get('out', {}).get('c', 0))} تراکنش",
        f"🪦 آگهی فعالِ بازار روح: <b>{await store.listings.count_documents({'status': 'active'})}</b>",
    ]
    if by:
        lines += ["┈┈┈┈┈┈┈┈┈┈", "🔥 بیشترین سوخت از:"] + [f"• {esc(k)}: {n(v)}" for k, v in by]
    return ptxt("yellow", "💰", "گزارش اقتصاد", lines)


async def rep_ledger(bot, chat_id):
    rows = await store.ledger.find({}).sort("at", -1).limit(15).to_list(15)
    if not rows:
        return "📒 دفتر خالیه."
    return ptxt("yellow", "📒", "آخرین تراکنش‌های دفتر کل", [
        f"<code>{r['uid']}</code> · {'+' if r['delta'] > 0 else ''}{n(r['delta'])} · {esc(r.get('reason') or '-')} · {ago(r.get('at'))}"
        for r in rows])


async def rep_rich(bot, chat_id):
    rows = await store.users.find({"registered": True}).sort("gold", -1).limit(10).to_list(10)
    return ptxt("yellow", "🪙", f"۱۰ ثروتمندِ برتر ({GS})", [
        f"{i}. {uname(d)} <code>{d['user_id']}</code> — <b>{n(d.get('gold'))}</b>" for i, d in enumerate(rows, 1)])


async def rep_toplvl(bot, chat_id):
    rows = await store.users.find({"registered": True}).sort("xp", -1).limit(10).to_list(10)
    return ptxt("blue", "🏅", "۱۰ بازیکنِ برتر (سطح)", [
        f"{i}. {uname(d)} <code>{d['user_id']}</code> — سطح <b>{d.get('level', 1)}</b> ({n(d.get('xp'))} XP)"
        for i, d in enumerate(rows, 1)])


async def rep_banlist(bot, chat_id):
    rows = await store.users.find({"banned": True}).limit(30).to_list(30)
    if not rows:
        return "✅ هیچ‌کس بن نیست."
    return ptxt("red", "🚫", f"لیست بن ({len(rows)})", [f"• {uname(d)} <code>{d['user_id']}</code>" for d in rows])


async def rep_active(bot, chat_id):
    now = utcnow()
    h1 = await store.users.count_documents({"last_seen": {"$gt": now - timedelta(hours=1)}})
    d1 = await store.users.count_documents({"last_seen": {"$gt": now - timedelta(days=1)}})
    d7 = await store.users.count_documents({"last_seen": {"$gt": now - timedelta(days=7)}})
    rows = await store.users.find({"last_seen": {"$gt": now - timedelta(days=1)}}).sort("last_seen", -1).limit(15).to_list(15)
    return ptxt("green", "🔥", "بازیکنانِ فعال", [
        f"⏱ ۱ ساعت: <b>{h1}</b>  |  ۲۴ ساعت: <b>{d1}</b>  |  ۷ روز: <b>{d7}</b>", "┈┈┈┈┈┈┈┈┈┈",
        *[f"• {uname(d)} <code>{d['user_id']}</code> · {ago(d.get('last_seen'))}" for d in rows]])


async def rep_growth(bot, chat_id):
    since = utcnow() - timedelta(days=7)
    days = [r async for r in store.users.aggregate([
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}, "n": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ])]
    total = await store.users.count_documents({})
    reg = await store.users.count_documents({"registered": True})
    mx = max([d["n"] for d in days] or [1])
    bars = [f"<code>{d['_id']}</code> {'▰' * max(1, round(d['n'] * 10 / mx))} {d['n']}" for d in days] or ["— هیچ عضوِ جدیدی نبود —"]
    return ptxt("green", "📈", "رشدِ ۷ روز اخیر (عضوِ جدید)", [
        f"👤 کل: <b>{n(total)}</b>  |  ثبت‌نام‌شده: <b>{n(reg)}</b>  ({int(reg * 100 / total) if total else 0}٪)", "┈┈┈┈┈┈┈┈┈┈", *bars])


async def rep_guilds(bot, chat_id):
    rows = await store.guilds.find({}).sort("week_pts", -1).limit(20).to_list(20)
    if not rows:
        return "🏰 هنوز گیلدی ساخته نشده."
    return ptxt("purple", "🏰", f"گیلدها ({len(rows)})", [
        f"• <b>{esc(g['name'])}</b> — 👥 {len(g.get('members') or [])} · 💰 {n(g.get('treasury'))} · 🏆 {g.get('wins', 0)}/{g.get('losses', 0)}"
        for g in rows])


async def rep_sieges(bot, chat_id):
    from content import TERRITORIES
    rows = await store.sieges.find({"status": "open"}).to_list(20)
    if not rows:
        return "🏴 محاصره‌ی بازی نداریم."
    out = []
    for s in rows:
        t = TERRITORIES.get(s["key"])
        left = int((s["ends_at"] - utcnow()).total_seconds()) if s.get("ends_at") else 0
        out.append(f"• {t[1] if t else ''} <b>{esc(t[0] if t else s['key'])}</b> — مهاجم: {esc((s.get('attacker') or {}).get('name'))} · "
                   f"مدافع: {esc((s.get('defender') or {}).get('name') or 'بی‌صاحب')} · ⏳ {max(left, 0) // 60}د")
    return ptxt("red", "🏴", "محاصره‌های بازِ", out)


async def rep_world(bot, chat_id):
    from worlddata import REGION_FA
    w = await store.meta.find_one({"_id": "world"})
    if not w:
        return "🌍 دنیا هنوز ساخته نشده."
    regs = [f"• {esc(REGION_FA.get(r, r))}: خطر <b>{int(v.get('danger', 0))}</b> · رونق <b>{int(v.get('prosperity', 0))}</b>"
            for r, v in (w.get("regions") or {}).items()]
    lt = w.get("last_tick") or 0
    return ptxt("blue", "🌍", "وضعیت جهانِ زنده", [
        f"🔁 تیک: <b>{n(w.get('tick_n'))}</b>  |  آخرین تیک: {int(time.time() - lt) // 60 if lt else '—'} دقیقه پیش",
        f"🧙 NPC زنده: <b>{await store.wnpcs.count_documents({})}</b>  |  ⚡️ رویداد فعال: <b>{await store.wevents.count_documents({'status': 'active'})}</b>",
        "┈┈┈┈┈┈┈┈┈┈", *regs, "┈┈┈┈┈┈┈┈┈┈",
        f"📰 اخبار: {len(w.get('news') or [])}  |  🗣 شایعه: {len(w.get('rumors') or [])}"])


async def rep_events(bot, chat_id):
    rows = await store.wevents.find({"status": "active"}).to_list(20)
    if not rows:
        return "⚡️ رویدادِ فعالی نیست."
    now = time.time()
    return ptxt("orange", "⚡️", f"رویدادهای فعال ({len(rows)})", [
        f"{e.get('icon', '•')} <b>{esc(e.get('title'))}</b> <code>{e['id']}</code> — {e.get('progress', 0)}/{e.get('target', 0)} · ⏳ {max(int(e['ends_at'] - now), 0) // 60}د"
        for e in rows], "برای پایان‌دادن: «پایان رویداد [id]»")


async def rep_bosses(bot, chat_id):
    rows = await store.raids.find({"status": "active"}).to_list(20)
    if not rows:
        return "🐉 باسِ فعالی نیست."
    return ptxt("red", "🐉", f"باس‌های فعال ({len(rows)})", [
        f"{r.get('icon', '')} <b>{esc(r['name'])}</b> — ❤️ {max(int(r['hp']), 0)}/{r['max_hp']} · چت <code>{r['chat_id']}</code>" for r in rows])


async def rep_groups(bot, chat_id):
    rows = await store.groups.find({}).sort("activity", -1).limit(15).to_list(15)
    return ptxt("blue", "👥", f"گروه‌های برتر (از {await store.groups.count_documents({})})", [
        f"• {esc(g.get('title') or '?')} <code>{g['chat_id']}</code> — فعالیت {n(g.get('activity'))} · ☠️ {n(g.get('deaths'))}" for g in rows])


_COLLS = ["users", "ledger", "listings", "offers", "guilds", "groups", "duels", "battles", "clashes", "raids", "sieges",
          "territories", "wnpcs", "wevents", "bounties", "drops", "proposals", "meta"]


async def rep_dbstats(bot, chat_id):
    lines = []
    for c in _COLLS:
        try:
            lines.append(f"• {c}: <b>{n(await getattr(store, c).estimated_document_count())}</b>")
        except Exception:
            pass
    try:
        st = await store.users.database.command("dbStats")
        lines += ["┈┈┈┈┈┈┈┈┈┈", f"💾 داده: <b>{st.get('dataSize', 0) / 1e6:.1f}MB</b>  |  ایندکس: <b>{st.get('indexSize', 0) / 1e6:.1f}MB</b>"]
    except Exception:
        pass
    return ptxt("green", "🗄", "آمار دیتابیس", lines)


async def rep_admins(bot, chat_id):
    out = []
    for a in ADMIN_IDS:
        d = await store.get(a)
        out.append(f"• {uname(d) if d else 'هنوز /start نزده'} <code>{a}</code>")
    return ptxt("red", "🔑", f"ادمین‌ها ({len(ADMIN_IDS)})", out or ["—"])


async def rep_export(bot, chat_id):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "name", "username", "registered", "banned", "class", "level", "xp", "gs", "deaths", "wins",
                "losses", "guild", "last_seen", "created_at"])
    cnt = 0
    async for d in store.users.find({}).limit(50000):
        w.writerow([d["user_id"], d.get("first_name"), d.get("username"), d.get("registered"), d.get("banned"), d.get("cls"),
                    d.get("level"), d.get("xp"), d.get("gold"), d.get("death_count"), d.get("wins"), d.get("losses"),
                    d.get("guild"), d.get("last_seen"), d.get("created_at")])
        cnt += 1
    await bot.send_document(chat_id, BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename=f"users_{utcnow():%Y%m%d_%H%M}.csv"),
                            caption=f"📤 خروجیِ {cnt} کاربر")
    return None


async def rep_logtest(bot, chat_id):
    import logchannel
    logchannel.event("🧪 <b>تستِ لاگ‌چنل</b> — اگه این رو می‌بینی لاگ سالمه.")
    return "🧪 پیام تست به لاگ‌چنل رفت (اگه LOG_CHANNEL تنظیم باشه)."


REPORTS: dict = {
    "economy": ("💰 اقتصاد", rep_economy), "ledger": ("📒 دفتر کل", rep_ledger), "rich": ("🪙 ثروتمندان", rep_rich),
    "toplvl": ("🏅 برترین سطح", rep_toplvl), "banlist": ("🚫 لیست بن", rep_banlist), "active": ("🔥 فعالان", rep_active),
    "growth": ("📈 رشد", rep_growth), "guilds": ("🏰 گیلدها", rep_guilds), "sieges": ("🏴 محاصره‌ها", rep_sieges),
    "world": ("🌍 جهان", rep_world), "events": ("⚡️ رویدادها", rep_events), "bosses": ("🐉 باس‌ها", rep_bosses),
    "groups": ("👥 گروه‌ها", rep_groups), "dbstats": ("🗄 دیتابیس", rep_dbstats), "admins": ("🔑 ادمین‌ها", rep_admins),
    "export": ("📤 خروجی CSV", rep_export), "logtest": ("🧪 تست لاگ", rep_logtest),
}


# ───────────────────────────── 📋 ثبتِ دستورهای متنی ─────────────────────────────
_CMDS: list = []


def cmd(pattern: str):
    rx = re.compile(pattern, re.DOTALL)

    def deco(fn):
        _CMDS.append((rx, fn))
        return fn
    return deco


def _report_cmd(pattern: str, key: str):
    async def h(m, bot, g):
        text = await REPORTS[key][1](bot, m.chat.id)
        if text:
            await m.reply(text)
    _CMDS.append((re.compile(pattern), h))


for _p, _k in [
    (r"^اقتصاد$", "economy"), (r"^دفتر کل$", "ledger"), (r"^ثروتمندان$", "rich"), (r"^سطح بالاها$", "toplvl"),
    (r"^لیست بن$", "banlist"), (r"^فعالان$", "active"), (r"^گزارش رشد$", "growth"), (r"^لیست گیلد ?ها$", "guilds"),
    (r"^محاصره ?های باز$", "sieges"), (r"^ادمین جهان$", "world"), (r"^ادمین رویدادها$", "events"),
    (r"^لیست باس ?ها$", "bosses"), (r"^لیست گروه ?ها$", "groups"), (r"^آمار دیتابیس$", "dbstats"),
    (r"^لیست ادمین ?ها$", "admins"), (r"^خروجی کاربران$", "export"), (r"^تست لاگ$", "logtest"),
]:
    _report_cmd(_p, _k)


# ── 👤 بازیکن ──
@cmd(r"^بازیکن(?:\s+(.+))?$")
async def c_user(m, bot, g):
    doc, _ = await target_doc(m, g.group(1))
    if not doc:
        return
    inv = doc.get("inventory") or []
    st = "🚫 بن" if doc.get("banned") else ("✅ ثبت‌نام‌شده" if doc.get("registered") else "⏳ بدون قرارداد")
    await m.reply(ptxt("blue", "🪪", f"پرونده‌ی {doc.get('first_name') or 'ناشناس'}", [
        f"🆔 <code>{doc['user_id']}</code>" + (f" · @{esc(doc['username'])}" if doc.get("username") else ""),
        f"📌 وضعیت: {st}" + (" · 🛡 محافظت" if doc.get("opted_out") and not doc.get("banned") else ""),
        f"🎭 کلاس: {esc(doc.get('cls') or '—')}  |  سطح <b>{doc.get('level', 1)}</b> ({n(doc.get('xp'))} XP)",
        f"🪙 {GS}: <b>{n(doc.get('gold'))}</b>  |  ❤️ بقا: <b>{doc.get('survival_rate', 100)}</b>",
        f"☠️ مرگ: {doc.get('death_count', 0)}  |  🏆 برد/باخت: {doc.get('wins', 0)}/{doc.get('losses', 0)}",
        f"🛡 گیلد: {esc(doc.get('guild') or 'بی‌گیلد')}  |  💍 {esc(doc.get('spouse_name') or 'مجرد')}",
        f"🎒 آیتم: {len(inv)}  |  🔥 استریک: {doc.get('streak', 0)}  |  🔗 معرفی: {doc.get('referrals_total', 0)}",
        f"👥 گروه‌ها: {len(doc.get('chats') or [])}  |  🕐 آخرین فعالیت: {ago(doc.get('last_seen'))}",
        f"📅 عضویت: {ago(doc.get('created_at'))}",
    ]))


@cmd(r"^جستجو\s+(.+)$")
async def c_find(m, bot, g):
    q = g.group(1).strip().lstrip("@")
    rx = {"$regex": re.escape(q), "$options": "i"}
    rows = await store.users.find({"$or": [{"first_name": rx}, {"username_lower": rx}]}).limit(10).to_list(10)
    if not rows:
        await m.reply("🔍 چیزی پیدا نشد.")
        return
    await m.reply(ptxt("blue", "🔍", f"نتیجه‌ی جستجوی «{esc(q)}»", [
        f"• {uname(d)} <code>{d['user_id']}</code> · سطح {d.get('level', 1)} · {n(d.get('gold'))} {GS}" for d in rows]))


@cmd(r"^شارژ\s+(.+)$")
async def c_givegs(m, bot, g):
    doc, rest = await target_doc(m, g.group(1))
    if not doc:
        return
    amt = amount_of(rest)
    if not amt:
        await m.reply(f"❌ مبلغ نامعتبر (۱ تا {n(MAX_GS)}). مثال: <code>شارژ 123456789 500</code>")
        return
    await credit(doc["user_id"], amt, "admin:give")
    audit(m, f"🪙 +{n(amt)} {GS} برای {uname(doc)} <code>{doc['user_id']}</code>")
    await m.reply(f"✅ <b>{n(amt)}</b> {GS} به {uname(doc)} واریز شد.")
    await dm(bot, doc["user_id"], f"🎁 ایزدبانو <b>{n(amt)}</b> {GS} برات فرستاد! 💅")


@cmd(r"^کسر\s+(.+)$")
async def c_takegs(m, bot, g):
    doc, rest = await target_doc(m, g.group(1))
    if not doc:
        return
    amt = amount_of(rest)
    if not amt:
        await m.reply("❌ مبلغ نامعتبر. مثال: <code>کسر 123456789 200</code>")
        return
    take = min(amt, int(doc.get("gold", 0)))
    if take <= 0 or not await debit(doc["user_id"], take, "admin:take", burn_it=False):
        await m.reply("❌ موجودیِ کاربر صفره (یا همزمان تغییر کرد).")
        return
    audit(m, f"🪙 −{n(take)} {GS} از {uname(doc)} <code>{doc['user_id']}</code>")
    await m.reply(f"✅ <b>{n(take)}</b> {GS} از {uname(doc)} کم شد." + (" (بیشتر از موجودی نداشت)" if take < amt else ""))


@cmd(r"^تنظیم جی اس\s+(.+)$")
async def c_setgs(m, bot, g):
    doc, rest = await target_doc(m, g.group(1))
    if not doc:
        return
    amt = amount_of(rest, 0)
    if amt is None:
        await m.reply("❌ مقدار نامعتبر. مثال: <code>تنظیم جی اس 123456789 1000</code>")
        return
    old = int(doc.get("gold", 0))
    await store.users.update_one({"user_id": doc["user_id"]}, {"$set": {"gold": amt}})
    await log_tx(doc["user_id"], amt - old, "admin:set")
    audit(m, f"🪙 موجودیِ {uname(doc)} <code>{doc['user_id']}</code>: {n(old)} ← {n(amt)}")
    await m.reply(f"✅ موجودیِ {uname(doc)}: {n(old)} ← <b>{n(amt)}</b> {GS}")


@cmd(r"^(?:اکس ?پی|xp)\s+(.+)$")
async def c_givexp(m, bot, g):
    doc, rest = await target_doc(m, g.group(1))
    if not doc:
        return
    amt = amount_of(rest, 1, 1_000_000)
    if not amt:
        await m.reply("❌ مقدار نامعتبر. مثال: <code>اکس پی 123456789 300</code>")
        return
    nd = await store.users.find_one_and_update({"user_id": doc["user_id"]}, {"$inc": {"xp": amt}}, return_document=ReturnDocument.AFTER)
    lvl = 1 + int(nd.get("xp", 0)) // 100
    if lvl != nd.get("level"):
        await store.users.update_one({"user_id": doc["user_id"]}, {"$set": {"level": lvl}})
    audit(m, f"✨ +{n(amt)} XP برای {uname(doc)} <code>{doc['user_id']}</code> (سطح {lvl})")
    await m.reply(f"✅ {n(amt)} XP به {uname(doc)} داده شد → سطح <b>{lvl}</b>")


@cmd(r"^تنظیم سطح\s+(.+)$")
async def c_setlevel(m, bot, g):
    doc, rest = await target_doc(m, g.group(1))
    if not doc:
        return
    lvl = amount_of(rest, 1, 500)
    if not lvl:
        await m.reply("❌ سطح باید ۱ تا ۵۰۰ باشه. مثال: <code>تنظیم سطح 123456789 10</code>")
        return
    await store.users.update_one({"user_id": doc["user_id"]}, {"$set": {"level": lvl, "xp": (lvl - 1) * 100}})
    audit(m, f"⭐️ سطحِ {uname(doc)} <code>{doc['user_id']}</code> ← {lvl}")
    await m.reply(f"✅ سطحِ {uname(doc)} روی <b>{lvl}</b> تنظیم شد.")


@cmd(r"^آیتم\s+(.+)$")
async def c_giveitem(m, bot, g):
    doc, rest = await target_doc(m, g.group(1))
    if not doc:
        return
    item = " ".join(rest).strip()
    if not item or len(item) > 60:
        await m.reply("❌ اسمِ آیتم رو بنویس (حداکثر ۶۰ حرف). مثال: <code>آیتم 123456789 شمشیر مقدس</code>")
        return
    await store.users.update_one({"user_id": doc["user_id"]}, {"$push": {"inventory": {"$each": [item], "$slice": -15}}})
    audit(m, f"🎒 آیتم «{esc(item)}» برای {uname(doc)} <code>{doc['user_id']}</code>")
    await m.reply(f"✅ آیتمِ «{esc(item)}» به کوله‌ی {uname(doc)} اضافه شد.")


@cmd(r"^شفا(?:\s+(.+))?$")
async def c_heal(m, bot, g):
    doc, _ = await target_doc(m, g.group(1))
    if not doc:
        return
    await store.users.update_one({"user_id": doc["user_id"]}, {"$set": {"survival_rate": 100}})
    audit(m, f"❤️ شفای کامل برای {uname(doc)} <code>{doc['user_id']}</code>")
    await m.reply(f"✅ بقای {uname(doc)} روی ۱۰۰ رفت.")


@cmd(r"^تراکنش(?:\s+(.+))?$")
async def c_txlog(m, bot, g):
    doc, _ = await target_doc(m, g.group(1))
    if not doc:
        return
    rows = await store.ledger.find({"uid": doc["user_id"]}).sort("at", -1).limit(12).to_list(12)
    if not rows:
        await m.reply("📒 این کاربر تراکنشی نداره.")
        return
    await m.reply(ptxt("yellow", "📒", f"تراکنش‌های {doc.get('first_name') or doc['user_id']}", [
        f"{'+' if r['delta'] > 0 else ''}{n(r['delta'])} · {esc(r.get('reason') or '-')} · {ago(r.get('at'))}" for r in rows]))


@cmd(r"^بارش\s+(.+)$")
async def c_airdrop(m, bot, g):
    toks = g.group(1).split()
    amt = amount_of(toks, 1, 5000)
    if not amt:
        await m.reply("❌ مبلغِ هر نفر ۱ تا ۵۰۰۰. مثال: <code>بارش 100</code>")
        return
    flt = {"registered": True, "banned": {"$ne": True}, "last_seen": {"$gt": utcnow() - timedelta(hours=24)}}
    ids = [d["user_id"] async for d in store.users.find(flt, {"user_id": 1})]
    if CONFIRM not in toks[1:]:
        await m.reply(f"⚠️ این کار به <b>{len(ids)}</b> بازیکنِ فعالِ ۲۴ ساعت اخیر، هرکدوم {n(amt)} {GS} می‌ده "
                      f"(جمعاً {n(amt * len(ids))}).\nبرای اجرا: <code>بارش {amt} {CONFIRM}</code>")
        return
    if not ids:
        await m.reply("❌ بازیکنِ فعالی نیست.")
        return
    await store.users.update_many({"user_id": {"$in": ids}}, {"$inc": {"gold": amt}})
    now = utcnow()
    await store.ledger.insert_many([{"uid": u, "delta": amt, "reason": "admin:airdrop", "ref": None, "at": now} for u in ids])
    audit(m, f"🌧 بارشِ {n(amt)} {GS} برای {len(ids)} نفر")
    await m.reply(f"✅ بارشِ {n(amt)} {GS} برای <b>{len(ids)}</b> نفر انجام شد. 🌧")


# ── 🏰 گیلد و قلمرو ──
@cmd(r"^اطلاعات گیلد\s+(.+)$")
async def c_ginfo(m, bot, g):
    from content import TERRITORIES
    from guilds import effective_fort
    gd = await find_guild(g.group(1))
    if not gd:
        await m.reply("❌ گیلد پیدا نشد.")
        return
    ids = gd.get("members") or []
    mem = await store.users.find({"user_id": {"$in": ids}}).sort("xp", -1).limit(12).to_list(12)
    terrs = [f"{TERRITORIES[t['key']][1]} {TERRITORIES[t['key']][0]}" async for t in store.territories.find({"owner": gd["name"]}) if t["key"] in TERRITORIES]
    await m.reply(ptxt("purple", "🏰", f"گیلد {gd['name']}", [
        f"👑 رهبر: <code>{gd.get('owner_id')}</code>  |  👥 اعضا: <b>{len(ids)}</b>",
        f"💰 خزانه: <b>{n(gd.get('treasury'))}</b>  |  🏯 دژ: {effective_fort(gd)}  |  🏆 {gd.get('wins', 0)}/{gd.get('losses', 0)}",
        f"🗺 قلمرو: {'، '.join(terrs) if terrs else 'ندارد'}",
        "┈┈┈┈┈┈┈┈┈┈", *[f"• {uname(d)} · سطح {d.get('level', 1)}" for d in mem]]))


async def _treasury(m, g, sign: int):
    toks = g.group(1).split()
    if len(toks) < 2 or not toks[-1].isdigit():
        await m.reply("❌ فرمت: <code>افزایش خزانه [نام گیلد] [مبلغ]</code>")
        return
    amt = int(toks[-1])
    if not 1 <= amt <= MAX_GS:
        await m.reply("❌ مبلغ نامعتبر.")
        return
    gd = await find_guild(" ".join(toks[:-1]))
    if not gd:
        await m.reply("❌ گیلد پیدا نشد.")
        return
    flt = {"_id": gd["_id"]}
    if sign < 0:
        flt["treasury"] = {"$gte": amt}
    res = await store.guilds.update_one(flt, {"$inc": {"treasury": sign * amt}})
    if not res.modified_count:
        await m.reply("❌ خزانه کمتر از این مقداره.")
        return
    audit(m, f"💰 خزانه‌ی «{esc(gd['name'])}» {'+' if sign > 0 else '−'}{n(amt)}")
    await m.reply(f"✅ خزانه‌ی «{esc(gd['name'])}» {'+' if sign > 0 else '−'}{n(amt)} {GS} شد.")


@cmd(r"^افزایش خزانه\s+(.+)$")
async def c_gadd(m, bot, g):
    await _treasury(m, g, 1)


@cmd(r"^کاهش خزانه\s+(.+)$")
async def c_gsub(m, bot, g):
    await _treasury(m, g, -1)


@cmd(r"^حذف گیلد\s+(.+)$")
async def c_gdel(m, bot, g):
    toks = g.group(1).split()
    confirmed = bool(toks) and toks[-1] == CONFIRM
    gd = await find_guild(" ".join(toks[:-1] if confirmed else toks))
    if not gd:
        await m.reply("❌ گیلد پیدا نشد.")
        return
    if not confirmed:
        await m.reply(f"⚠️ گیلدِ «{esc(gd['name'])}» ({len(gd.get('members') or [])} عضو) برگشت‌ناپذیر حذف میشه و قلمروهاش آزاد میشن.\n"
                      f"برای اجرا: <code>حذف گیلد {esc(gd['name'])} {CONFIRM}</code>")
        return
    await store.users.update_many({"guild": gd["name"]}, {"$set": {"guild": None}})
    await store.territories.update_many({"owner": gd["name"]}, {"$set": {"owner": None}})
    await store.guilds.delete_one({"_id": gd["_id"]})
    audit(m, f"🗑 گیلد «{esc(gd['name'])}» حذف شد")
    await m.reply(f"✅ گیلدِ «{esc(gd['name'])}» حذف شد.")


@cmd(r"^تصاحب قلمرو\s+(.+)$")
async def c_tset(m, bot, g):
    from content import TERRITORIES
    toks = g.group(1).split()
    key = terr_key(toks[0]) if toks else None
    gd = await find_guild(" ".join(toks[1:])) if key else None
    if not key or not gd:
        await m.reply("❌ فرمت: <code>تصاحب قلمرو [قلعه|جنگل|بندر|خرابه|پایتخت] [نام گیلد]</code>")
        return
    await store.territories.update_one({"key": key}, {"$set": {"owner": gd["name"], "since": utcnow()}}, upsert=True)
    audit(m, f"👑 قلمروِ {TERRITORIES[key][0]} ← «{esc(gd['name'])}»")
    await m.reply(f"✅ {TERRITORIES[key][1]} <b>{TERRITORIES[key][0]}</b> به «{esc(gd['name'])}» رسید.")


@cmd(r"^آزادسازی قلمرو\s+(.+)$")
async def c_tfree(m, bot, g):
    from content import TERRITORIES
    key = terr_key(g.group(1).split()[0])
    if not key:
        await m.reply("❌ قلمرو پیدا نشد (قلعه، جنگل، بندر، خرابه، پایتخت).")
        return
    await store.territories.update_one({"key": key}, {"$set": {"owner": None}}, upsert=True)
    audit(m, f"🏳️ قلمروِ {TERRITORIES[key][0]} آزاد شد")
    await m.reply(f"✅ {TERRITORIES[key][1]} <b>{TERRITORIES[key][0]}</b> بی‌صاحب شد.")


# ── 🌍 جهان و باس ──
@cmd(r"^پایان رویداد\s+(\w+)$")
async def c_endevent(m, bot, g):
    res = await store.wevents.update_one({"id": g.group(1), "status": "active"}, {"$set": {"ends_at": time.time()}})
    if not res.matched_count:
        await m.reply("❌ رویدادِ فعالی با این شناسه نیست.")
        return
    audit(m, f"⚡️ رویداد <code>{esc(g.group(1))}</code> برای پایان علامت خورد")
    await m.reply("✅ رویداد تو تیکِ بعدیِ جهان جمع‌بندی میشه.")


@cmd(r"^باس ادمین$")
async def c_spawnboss(m, bot, g):
    from utils import is_group
    if not is_group(m):
        await m.reply("❌ این دستور فقط تو گروه کار می‌کنه.")
        return
    from raid import spawn_raid
    res = await spawn_raid(bot, m.chat.id, "ادمین")
    if res != "ok":
        await m.reply("⏳ همین الان یه باس فعاله." if res == "active" else "⏳ کولدانِ باس هنوز تموم نشده.")
    else:
        audit(m, f"🐉 باس تو چتِ <code>{m.chat.id}</code> احضار شد")


@cmd(r"^پایان باس$")
async def c_killboss(m, bot, g):
    res = await store.raids.update_many({"chat_id": m.chat.id, "status": "active"}, {"$set": {"status": "lost"}})
    await m.reply("✅ باسِ این چت بسته شد." if res.modified_count else "❌ باسِ فعالی تو این چت نیست.")


# ── ✉️ ارتباطات (از متنِ خام، چون «-» تو c پاک میشه) ──
_PM_RE = re.compile(r"^\s*پیام خصوصی\s+(\d+)\s+(.+)$", re.DOTALL)
_SAY_RE = re.compile(r"^\s*ارسال به گروه\s+(-?\d+)\s+(.+)$", re.DOTALL)


async def _raw_cmds(m, bot, raw: str) -> bool:
    if pm := _PM_RE.match(raw):
        try:
            await bot.send_message(int(pm.group(1)), panel("purple", "📩", "پیام از مدیریت", [esc(pm.group(2))]))
            audit(m, f"📩 پیام خصوصی به <code>{pm.group(1)}</code>")
            await m.reply("✅ فرستاده شد.")
        except Exception as e:
            await m.reply(f"❌ ارسال نشد: {esc(str(e)[:100])}")
        return True
    if sy := _SAY_RE.match(raw):
        try:
            await bot.send_message(int(sy.group(1)), panel("purple", "📢", "اعلام ایزدبانو", [esc(sy.group(2))]))
            audit(m, f"📢 پیام به چت <code>{sy.group(1)}</code>")
            await m.reply("✅ فرستاده شد.")
        except Exception as e:
            await m.reply(f"❌ ارسال نشد: {esc(str(e)[:100])}")
        return True
    return False


# ───────────────────────────── 🎛 راهنما و پنلِ لایه‌ایِ دکمه‌ها ─────────────────────────────
CATS: dict = {
    "players": ("👤", "مدیریت بازیکنان", [
        "• <b>بازیکن [id/@user]</b> ← پرونده‌ی کامل  <i>/user</i>",
        "• <b>جستجو [نام]</b> ← پیدا کردن بازیکن  <i>/find</i>",
        "• <b>شارژ [id] [مبلغ]</b> / <b>کسر</b> / <b>تنظیم جی اس</b>  <i>/givegs /takegs /setgs</i>",
        "• <b>اکس پی [id] [مقدار]</b> · <b>تنظیم سطح [id] [سطح]</b>  <i>/givexp /setlevel</i>",
        "• <b>آیتم [id] [نام]</b> · <b>شفا [id]</b> · <b>تراکنش [id]</b>  <i>/giveitem /heal /txlog</i>",
        "• بن / آنبن / کشتن  <i>/ban /unban /kill</i>   (آیدی را می‌شود با ریپلای هم داد)",
    ], ["rich", "toplvl", "active", "banlist", "growth"]),
    "economy": ("💰", "اقتصاد", [
        "• <b>اقتصاد</b> ← گردش، سوخت، تمرکز ثروت  <i>/economy</i>",
        "• <b>دفتر کل</b> ← آخرین تراکنش‌ها  <i>/ledger</i>",
        "• <b>بارش [مبلغ]</b> ← GS برای فعال‌های ۲۴ ساعت (با «تایید»)  <i>/airdrop</i>",
    ], ["economy", "ledger", "rich"]),
    "guild": ("🏰", "گیلد و قلمرو", [
        "• <b>لیست گیلدها</b> · <b>اطلاعات گیلد [نام]</b>  <i>/guilds /ginfo</i>",
        "• <b>افزایش خزانه [نام] [مبلغ]</b> · <b>کاهش خزانه</b>  <i>/gadd /gsub</i>",
        "• <b>حذف گیلد [نام] تایید</b>  <i>/gdel</i>",
        "• <b>تصاحب قلمرو [قلمرو] [گیلد]</b> · <b>آزادسازی قلمرو [قلمرو]</b>  <i>/tset /tfree</i>",
        "• <b>محاصره های باز</b>  <i>/sieges</i>",
    ], ["guilds", "sieges"]),
    "world": ("🌍", "جهان و باس", [
        "• <b>ادمین جهان</b> ← خطر/رونق مناطق  <i>/aworld</i>",
        "• <b>ادمین رویدادها</b> · <b>پایان رویداد [id]</b>  <i>/aevents /endevent</i>",
        "• <b>لیست باس ها</b> · <b>باس ادمین</b> (تو گروه) · <b>پایان باس</b>  <i>/bosses /spawnboss /killboss</i>",
    ], ["world", "events", "bosses"]),
    "comms": ("📢", "ارتباطات", [
        "• <b>سراسری [متن]</b> ← پیام همگانی  <i>/broadcast</i>",
        "• <b>پیام خصوصی [id] [متن]</b>  <i>/pm</i>",
        "• <b>ارسال به گروه [chat_id] [متن]</b>  <i>/say</i>",
        "• <b>لیست گروه ها</b>  <i>/groups</i>",
    ], ["groups", "logtest"]),
    "system": ("⚙️", "سیستم", [
        "• <b>آمار ربات</b> · <b>سلامت سرور</b> · <b>پاکسازی</b>",
        "• <b>آمار دیتابیس</b> ← حجم و تعداد رکوردها  <i>/dbstats</i>",
        "• <b>خروجی کاربران</b> ← فایل CSV  <i>/export</i>",
        "• <b>لیست ادمین ها</b> · <b>تست لاگ</b>  <i>/admins /logtest</i>",
    ], ["dbstats", "export", "admins", "logtest"]),
}


def _all_help() -> list:
    out = ["پنل چندلایه است؛ از دکمه‌ها وارد دسته‌ها شو یا مستقیم بنویس «<b>ادمین کمک</b>»."]
    for icon, title, lines, _ in CATS.values():
        out += ["", f"{icon} <b>{title}</b>", *lines]
    return out


HELP_LINES = _all_help()


def admin_kb(uid: int) -> InlineKeyboardMarkup:
    cats = [btn(f"{v[0]} {v[1]}", f"adm:cat:{k}:{uid}", "blue") for k, v in CATS.items()]
    return kb(
        cats[0:2], cats[2:4], cats[4:6],
        [btn("📊 آمار ربات", f"adm:stats:{uid}", "green"), btn("🩺 سلامت سرور", f"adm:health:{uid}", "green")],
        [btn("🧹 پاکسازی دیتابیس", f"adm:clean:{uid}", "red"), btn("📖 همه‌ی دستورها", f"adm:help:{uid}", "blue")],
    )


def cat_kb(key: str, uid: int) -> InlineKeyboardMarkup:
    reps = [btn(REPORTS[r][0], f"adm:run:{r}:{uid}", "green") for r in CATS[key][3]]
    rows = [reps[i:i + 2] for i in range(0, len(reps), 2)]
    return kb(*rows, [btn("🔙 پنل ادمین", f"adm:home:{uid}", "blue")])


def home_text() -> str:
    return panel("red", "🛠", "پنل مدیریت ادمین",
                 ["یه دسته رو انتخاب کن. هر دسته گزارش‌های زنده و فرمان‌هاش رو داره.",
                  *[f"{v[0]} <b>{v[1]}</b> — {len(v[2])} فرمان" for v in CATS.values()]],
                 "💡 همه‌ی فرمان‌ها اسلش هم دارن (منوی / برای ادمین‌ها).")


async def admin_cb(cq, m, parts: list, bot: Bot):
    """هندلرِ دکمه‌های adm:*  (احرازِ ادمین بودن و cq.answer() قبلاً تو callbacks.py انجام شده)."""
    import admin as A        # import تنبل (admin خودش admin_tools رو import می‌کنه)
    uid = cq.from_user.id
    act = parts[1] if len(parts) > 1 else ""
    if act == "home":
        await safe_edit(cq.message, home_text(), admin_kb(uid))
    elif act == "cat" and len(parts) > 2 and parts[2] in CATS:
        icon, title, lines, _ = CATS[parts[2]]
        await safe_edit(cq.message, panel("red", icon, title, lines), cat_kb(parts[2], uid))
    elif act == "run" and len(parts) > 2 and parts[2] in REPORTS:
        try:
            text = await REPORTS[parts[2]][1](bot, cq.message.chat.id)
        except Exception as e:
            log.exception("admin report failed")
            text = f"❌ خطا: {esc(str(e)[:120])}"
        if text:
            await m.reply(text)
    elif act == "stats":
        await m.reply(await A.admin_stats())
    elif act == "health":
        await m.reply(await A.admin_health())
    elif act == "clean":
        await m.reply(await A.admin_clean())
    elif act == "help":
        await m.reply(panel("red", "🛠", "فرمان‌های ادمین", A.ADMIN_HELP))


async def handle_ext(m, bot: Bot, c: str) -> bool:
    """دستورهای گسترده‌ی ادمین. (دسترسی قبلاً تو handle_admin_commands چک شده.) True = مصرف شد."""
    raw = (m.text or "").strip()
    try:
        if await _raw_cmds(m, bot, raw):
            return True
        if c == "ادمین کمک":
            await m.reply(panel("red", "🛠", "راهنمای کاملِ ادمین", HELP_LINES), reply_markup=admin_kb(m.from_user.id))
            return True
        for rx, fn in _CMDS:
            g = rx.match(c)
            if g:
                await fn(m, bot, g)
                return True
    except Exception as e:
        log.exception("admin ext command failed")
        await m.reply(f"❌ خطا تو اجرای دستور: <code>{esc(str(e)[:150])}</code>")
        return True
    return False
