"""قلمروهای نقشه، مزایای قلمرو و «جنگ قلمروها» (محاصره با شرکتِ اعضا).

قوانینِ ساده:
1) یکی از اعضای گیلد (تو گروه) «محاصره [قلمرو]» رو اعلام می‌کنه؛ ۸۰ GS از «خزانه‌ی گیلد» خرج میشه.
2) تا ۱۰ دقیقه، اعضای گیلدِ مهاجم و (اگه قلمرو مالک داره) گیلدِ مدافع با دکمه می‌پیوندن؛
   قدرتِ هر نفر = سطح + بقا + تجهیز. «تمام‌عیار» = ۴۰٪ قدرتِ بیشتر در ازای ۸٪ بقا.
3) آخرش مجموع‌ها مقایسه میشه (بدون رندوم). برنده‌ی «شرکت‌کننده‌ها» از صندوقِ جنگ سهم می‌گیرن؛
   عضوِ غایب هیچی نمی‌گیره. هر نفر در هر محاصره فقط یک‌بار می‌پیوندد، سقفِ GS برای هر نفر هست و
   حل‌وفصلِ محاصره اتمیکه (جایزه دوبار پرداخت نمیشه).
4) قلمروِ فتح‌شده مدتی محافظت میشه و برای گیلدِ مالک «مزیتِ ویژه» (TERR_PERKS) + خراجِ هفتگی به خزانه داره."""

import asyncio
import re
from datetime import timedelta
from typing import Optional

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from battle_engine import war_power
from config import (
    GS, SIEGE_COOLDOWN, SIEGE_COST, SIEGE_MIN_JOIN, SIEGE_MIN_SURVIVAL, SIEGE_PROTECT, SIEGE_WINDOW, TERR_TRIBUTE,
    WAR_ALLIN_BONUS, WAR_ALLIN_COST, WAR_CHEST_PLAYER_CAP, log,
)
from content import TERR_INCOME, TERR_PERKS, TERRITORIES
from database import store
from economy import burn, fmt
from guilds import effective_fort, guild_power
from players import adjust_survival, grant
from quests import quest_progress
from rules import gear_bonus
from ui import back_kb, btn, kb, panel, say, show
from utils import esc, is_group, spawn, utcnow
from weekly import add_guild_pts, ensure_week


# ───────────────────────────── 👑 قلمروها و پادشاه هفته ─────────────────────────────
TERR_ALIAS = {
    "capital": r"(پایتخت|شهر|درخشان)",
    "castle": r"(قلعه|تاریک)",
    "forest": r"(جنگل)",
    "port": r"(بندر|طوفان|دریا)",
    "ruins": r"(خرابه|ویرانه|معبد)",
}


def find_terr(text: str) -> Optional[str]:
    for k, rx in TERR_ALIAS.items():
        if re.search(rx, text):
            return k
    return None


async def do_terr(m):
    uid = m.from_user.id
    await resolve_due(getattr(m, "bot", None))
    meta = await ensure_week()
    owners = {t["key"]: t.get("owner") async for t in store.territories.find({})}
    sieged = {s["key"] async for s in store.sieges.find({"status": "open"}, {"key": 1})}
    lines = []
    king = meta.get("king")
    if king:
        lines.append(f"👑 <b>پادشاه هفته‌ی قبل:</b> {esc(king['leader_name'])} — گیلد «{esc(king['guild'])}» ({king['pts']} امتیاز)")
    else:
        lines.append("👑 هنوز پادشاهی نداریم؛ تاج روی میز خاک می‌خوره.")
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    for k, (name, icon, power) in TERRITORIES.items():
        own = owners.get(k)
        perk = TERR_PERKS[k]
        tag = " 🔥<b>تحت محاصره</b>" if k in sieged else ""
        lines.append(f"{icon} <b>{name}</b> — " + (f"🛡 {esc(own)}" if own else f"🏴 آزاد (نگهبان ⚡{power})") + tag
                     + f"\\n      🎖 {perk[0]}: {perk[1]}")
    top = await store.guilds.find({"week_pts": {"$gt": 0}}).sort("week_pts", -1).limit(5).to_list(5)
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    if top:
        lines.append("🏁 <b>رده‌بندی این هفته:</b>")
        lines += [f"{i}. {esc(g['name'])} — {g.get('week_pts', 0)} امتیاز" for i, g in enumerate(top, 1)]
    else:
        lines.append("🏁 هنوز هیچ گیلدی امتیازی نگرفته. وقتشه!")
    rows = []
    ks = list(TERRITORIES.items())
    for i in range(0, len(ks), 2):
        rows.append([btn(f"⚔️ {v[1]} {v[0]}", f"sg:{k}:{uid}", "red") for k, v in ks[i:i + 2]])
    await show(m, panel("yellow", "🗺", "نقشه‌ی جهان و جنگ قلمروها", lines,
                        f"هر قلمرو برای اعضای گیلدِ مالک 🪙+{TERR_INCOME} {GS} به‌ازای هر سفر + مزیتِ بالا + خراجِ {TERR_TRIBUTE} {GS} هفتگی به خزانه‌ی گیلد می‌ده.\n"
                        f"محاصره: {SIEGE_COST} {GS} از خزانه‌ی گیلد؛ اعضا با دکمه می‌پیوندن."),
               kb(*rows, back_kb(uid)))


# ───────────────────────────── 🏰 اعلامِ محاصره ─────────────────────────────
def _totals(s: dict) -> tuple:
    a = sum(int(v) for v in (s.get("att") or {}).values())
    d_members = sum(int(v) for v in (s.get("de") or {}).values())
    d = int((int(s.get("base_def", 0)) + d_members) * (1 + 0.1 * int(s.get("fort", 0))))
    return a, d


def siege_text(s: dict, foot: Optional[str] = None) -> str:
    name, icon, _ = TERRITORIES[s["key"]]
    a, d = _totals(s)
    left = max(0, int((s["ends_at"] - utcnow()).total_seconds()))
    defender = esc(s["defender"]["name"]) if s.get("defender") else f"نگهبانانِ {name}"
    lines = [
        f"🛡 مهاجم: <b>{esc(s['attacker']['name'])}</b> — 👥 {len(s.get('att') or {})} نفر | ⚡ <b>{a}</b>",
        f"🗡 مدافع: <b>{defender}</b> — 👥 {len(s.get('de') or {})} نفر | ⚡ <b>{d}</b>" + (f" (دژ سطح {s['fort']})" if s.get("fort") else ""),
        f"⏳ {left // 60}:{left % 60:02d} تا نتیجه",
    ]
    return panel("red", icon, f"محاصره‌ی {name}", lines,
                 foot or "برای حضور، دکمه‌ی گیلدت رو بزن. غایب‌ها از غنیمت سهم ندارن! مجموعِ قدرت برنده رو مشخص می‌کنه (بدون رندوم).")


def siege_kb(sid):
    return kb(
        [btn("⚔️ حمله", f"war:atk:{sid}:0", "red"), btn("🔥 حمله‌ی تمام‌عیار (−۸٪ بقا)", f"war:atkx:{sid}:0", "red")],
        [btn("🛡 دفاع", f"war:def:{sid}:0", "blue"), btn("🔥 دفاعِ تمام‌عیار (−۸٪ بقا)", f"war:defx:{sid}:0", "blue")],
        [btn("📊 وضعیت", f"war:st:{sid}:0", "green")],
    )


async def do_siege(m, key: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await say(m, "برای محاصره باید عضو یه گیلد باشی. یه گیلد بساز یا به یکی بپیوند. 🛡", "🛡", "محاصره", "red")
        return
    if not is_group(m):
        await say(m, "محاصره باید تو گروه اعلام بشه تا هم‌گیلدی‌هات بتونن بپیوندن. 🏰", "🏰", "محاصره", "red")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        return
    if len(g["members"]) < SIEGE_MIN_JOIN:
        await say(m, f"گیلد برای لشکرکشی حداقل {SIEGE_MIN_JOIN} عضو می‌خواد. 👥", "🛡", "محاصره", "red")
        return
    name, icon, garrison = TERRITORIES[key]
    now = utcnow()
    t = await store.territories.find_one({"key": key})
    holder = await store.guilds.find_one({"name": t["owner"]}) if t and t.get("owner") else None
    if holder and holder["_id"] == g["_id"]:
        await say(m, f"{icon} «{name}» همین الان مال گیلد خودته! یه قلمرو دیگه رو انتخاب کن. 👑", "👑", "محاصره", "yellow")
        return
    if holder and t.get("since") and (now - t["since"]).total_seconds() < SIEGE_PROTECT:
        left = int(SIEGE_PROTECT - (now - t["since"]).total_seconds()) // 60 + 1
        await say(m, f"«{name}» تازه فتح شده و ~{left} دقیقه تحت محافظته. 🕊", "🕊", "محاصره", "yellow")
        return
    if await store.sieges.find_one({"key": key, "status": {"$in": ["open", "resolving"]}}):
        await say(m, f"«{name}» همین الان تحت محاصره‌ست. 🔥", "🔥", "محاصره", "red")
        return
    # هزینه (از خزانه) و کولداون در یک آپدیتِ اتمیک
    cutoff = now - timedelta(seconds=SIEGE_COOLDOWN)
    claim = await store.guilds.update_one(
        {"_id": g["_id"], "treasury": {"$gte": SIEGE_COST}, "$or": [{"last_siege_at": None}, {"last_siege_at": {"$lt": cutoff}}]},
        {"$inc": {"treasury": -SIEGE_COST}, "$set": {"last_siege_at": now}})
    if not claim.modified_count:
        last = g.get("last_siege_at")
        if last and (now - last).total_seconds() < SIEGE_COOLDOWN:
            left = int(SIEGE_COOLDOWN - (now - last).total_seconds()) // 60 + 1
            await say(m, f"گیلدت هنوز خسته‌ست. حدود {left} دقیقه‌ی دیگه می‌تونین دوباره حمله کنین. 🩹", "🩹", "محاصره", "red")
        else:
            await say(m, f"خزانه‌ی گیلد کمه (لازم: {fmt(SIEGE_COST)}، موجود: {fmt(g.get('treasury', 0))}). اعضا با «اهدا [مبلغ]» پرش کنن. 💰", "💰", "محاصره", "yellow")
        return
    base_def = 60 if holder else int(garrison * 2.2)
    s = {
        "key": key, "chat_id": m.chat.id, "attacker": {"id": g["_id"], "name": g["name"]},
        "defender": {"id": holder["_id"], "name": holder["name"]} if holder else None,
        "base_def": base_def, "fort": effective_fort(holder) if holder else 0, "att": {}, "de": {}, "names": {},
        "status": "open", "created_at": now, "ends_at": now + timedelta(seconds=SIEGE_WINDOW), "cost": SIEGE_COST,
        "notify_chat": holder.get("home_chat") if holder and holder.get("home_chat") != m.chat.id else None,
    }
    try:
        res = await store.sieges.insert_one(s)
    except DuplicateKeyError:
        await store.guilds.update_one({"_id": g["_id"]}, {"$inc": {"treasury": SIEGE_COST}, "$set": {"last_siege_at": g.get("last_siege_at")}})
        await say(m, f"«{name}» همین الان تحت محاصره‌ست. 🔥", "🔥", "محاصره", "red")
        return
    s["_id"] = res.inserted_id
    await burn(SIEGE_COST, "siege")
    msg = await m.reply(siege_text(s), reply_markup=siege_kb(s["_id"]))
    upd = {"msg_id": getattr(msg, "message_id", None)}
    bot = getattr(m, "bot", None)
    if s.get("notify_chat") and bot:
        try:
            n = await bot.send_message(s["notify_chat"], siege_text(s, f"🚨 گیلدِ <b>{esc(g['name'])}</b> به قلمروتون حمله کرده! مدافع‌ها بپیوندین!"), reply_markup=siege_kb(s["_id"]))
            upd["notify_msg_id"] = n.message_id
        except Exception:
            pass
    await store.sieges.update_one({"_id": s["_id"]}, {"$set": upd})
    spawn(siege_timer(bot, s["_id"], SIEGE_WINDOW))


# ───────────────────────────── ⚔️ پیوستن ─────────────────────────────
async def siege_join(m, sid, side: str, allin: bool):
    uid = m.from_user.id
    doc = await store.get(uid)
    s = await store.sieges.find_one({"_id": sid, "status": "open"})
    if not s or s["ends_at"] <= utcnow():
        await say(m, "این محاصره تموم شده. 🏁", "🏰", "محاصره", "red")
        return
    gname = (s["attacker"] if side == "att" else (s.get("defender") or {})).get("name")
    if not gname:
        await say(m, "این قلمرو فقط نگهبانِ NPC داره؛ مدافعِ انسانی نداره. 🗿", "🏰", "محاصره", "red")
        return
    if doc.get("guild") != gname:
        await say(m, f"این دکمه مخصوص اعضای گیلدِ «{esc(gname)}»ـه. 🛡", "🏰", "محاصره", "red")
        return
    if int(doc.get("survival_rate", 0)) < SIEGE_MIN_SURVIVAL + (WAR_ALLIN_COST if allin else 0):
        await say(m, "زخمیِ‌تر از اون هستی که بجنگی؛ اول بقات رو ترمیم کن (کافه/جادوگر). 🩹", "🩹", "محاصره", "red")
        return
    wp = war_power(doc, gear_bonus((doc.get("equip") or {}).get("item")))
    if allin:
        wp = int(wp * WAR_ALLIN_BONUS)
    field = "att" if side == "att" else "de"
    res = await store.sieges.update_one(
        {"_id": sid, "status": "open", f"{field}.{uid}": {"$exists": False}},
        {"$set": {f"{field}.{uid}": wp, f"names.{uid}": doc.get("first_name") or "؟"}})
    if not res.modified_count:
        await say(m, "قبلاً پیوستی (یا محاصره تموم شد). هر نفر یک‌بار شرکت می‌کنه. ✅", "🏰", "محاصره", "yellow")
        return
    if allin:
        await adjust_survival(uid, -WAR_ALLIN_COST)
    s = await store.sieges.find_one({"_id": sid})
    await m.reply(panel("red", "⚔️" if side == "att" else "🛡", "پیوستی!", [
        f"{esc(doc.get('first_name'))} با قدرتِ <b>{wp}</b>{' 🔥 (تمام‌عیار)' if allin else ''} به {'حمله' if side == 'att' else 'دفاع'} پیوست.",
        *siege_text(s).split("\n")[1:2],
    ]), reply_markup=siege_kb(sid))
    await quest_progress(m, "war")


async def siege_status(m, sid):
    s = await store.sieges.find_one({"_id": sid})
    if not s:
        await say(m, "این محاصره پیدا نشد. 🪦", "🏰", "محاصره", "red")
        return
    if s["status"] != "open":
        await say(m, "این محاصره تموم شده. 🏁", "🏰", "محاصره", "red")
        return
    await m.reply(siege_text(s), reply_markup=siege_kb(sid))


async def siege_cb(m, parts: list):
    """war:<act>:<siege>:0"""
    try:
        sid = ObjectId(parts[2])
    except Exception:
        return
    act = parts[1]
    if act in ("atk", "atkx"):
        await siege_join(m, sid, "att", act == "atkx")
    elif act in ("def", "defx"):
        await siege_join(m, sid, "de", act == "defx")
    else:
        await siege_status(m, sid)


# ───────────────────────────── 🏁 نتیجه ─────────────────────────────
async def siege_timer(bot, sid, delay: float):
    try:
        await asyncio.sleep(max(0.0, delay) + 1)
        await resolve_siege(bot, sid)
    except Exception:
        log.exception("siege_timer failed")


def _shares(parts: dict, chest: int) -> dict:
    tot = sum(parts.values()) or 1
    return {u: min(WAR_CHEST_PLAYER_CAP, int(chest * wp / tot)) for u, wp in parts.items()}


async def resolve_siege(bot, sid):
    """اتمیک: فقط یک‌بار اجرا میشه (open→resolving)."""
    s = await store.sieges.find_one_and_update({"_id": sid, "status": "open"}, {"$set": {"status": "resolving"}}, return_document=ReturnDocument.AFTER)
    if not s:
        return
    att = {int(u): int(v) for u, v in (s.get("att") or {}).items()}
    de = {int(u): int(v) for u, v in (s.get("de") or {}).items()}
    a_tot, d_tot = _totals(s)
    name, icon, garrison = TERRITORIES[s["key"]]
    an, dn = s["attacker"]["name"], (s.get("defender") or {}).get("name")
    lines = [f"🛡 <b>{esc(an)}</b>  ⚡{a_tot}  ({len(att)} نفر)", "      ⚔️ محاصره ⚔️",
             f"🗡 <b>{esc(dn) if dn else 'نگهبانان'}</b>  ⚡{d_tot}  ({len(de)} نفر)", "┈┈┈┈┈┈┈┈┈┈"]
    names = s.get("names") or {}

    async def pay(parts: dict, chest: int, xp: int):
        out = []
        for u, share in _shares(parts, chest).items():
            await grant(u, gold=share, xp=xp)
            out.append(f"• {esc(names.get(str(u), '؟'))} — 🪙+{share} {GS}")
        return out

    color, foot = "red", "💅 <i>«شکست خوردین. تو دفتر من، بازنده‌ها حتی اسم هم ندارن.»</i>"
    result = "hold"
    if len(att) < SIEGE_MIN_JOIN:
        result = "fizzle"
        await store.guilds.update_one({"_id": s["attacker"]["id"]}, {"$inc": {"treasury": SIEGE_COST // 2}})
        lines.append(f"🌫 کسی نیومد! (حداقل {SIEGE_MIN_JOIN} نفر لازمه). نصفِ هزینه ({SIEGE_COST // 2} {GS}) به خزانه برگشت.")
    elif a_tot > d_tot:
        result = "win"
        await store.territories.update_one({"key": s["key"]}, {"$set": {"owner": an, "since": utcnow()}}, upsert=True)
        lines.append(f"🏆 <b>{icon} {name} فتح شد!</b> مزیتِ «{TERR_PERKS[s['key']][0]}» حالا مالِ {esc(an)}ـه. 🎖")
        lines.append(f"💰 غنیمتِ شرکت‌کننده‌ها (سقف {WAR_CHEST_PLAYER_CAP} {GS} برای هر نفر):")
        lines += await pay(att, 100 + garrison // 2, 20)
        for u in de:
            await grant(u, xp=5)
        await add_guild_pts(an, 25)
        color, foot = "green", "💅 <i>«پرچم جدید، ارباب جدید. ولی آخرش همه‌شون زیر پای منن.»</i>"
    else:
        lines.append("🪦 محاصره شکست خورد. قلمرو سر جاشه!")
        for u in att:
            await grant(u, xp=8)
        await add_guild_pts(an, 5)
        if dn and de:
            lines.append("🛡 غنیمتِ مدافع‌ها:")
            lines += await pay(de, 80, 15)
            await add_guild_pts(dn, 10)
        elif dn:
            lines.append("🛡 مدافعی نیومد، ولی قلمرو دووم آورد!")
    await store.sieges.update_one({"_id": s["_id"]}, {"$set": {"status": "done", "result": result, "a_tot": a_tot, "d_tot": d_tot, "closed_at": utcnow()}})
    text = panel(color, icon, f"محاصره‌ی {name} — نتیجه", lines, foot)
    for cid, mid in ((s["chat_id"], s.get("msg_id")), (s.get("notify_chat"), s.get("notify_msg_id"))):
        if not cid or not bot:
            continue
        try:
            if mid:
                try:
                    await bot.edit_message_text(text, chat_id=cid, message_id=mid, reply_markup=None)
                    continue
                except Exception:
                    pass
            await bot.send_message(cid, text)
        except Exception:
            log.debug("siege result send failed for %s", cid)


async def resolve_due(bot):
    """محاصره‌هایی که زمانشون گذشته (مثلاً تایمر با ری‌استارت از بین رفته) رو نتیجه می‌ده."""
    try:
        async for s in store.sieges.find({"status": "open", "ends_at": {"$lte": utcnow()}}, {"_id": 1}):
            await resolve_siege(bot, s["_id"])
    except Exception:
        log.exception("resolve_due failed")


async def recover_sieges(bot):
    try:
        await resolve_due(bot)
        async for s in store.sieges.find({"status": "open"}):
            spawn(siege_timer(bot, s["_id"], (s["ends_at"] - utcnow()).total_seconds()))
        # نتیجه‌ای که وسطش کرش کرده، قلمرو رو برای همیشه قفل نکنه
        await store.sieges.update_many(
            {"status": "resolving", "ends_at": {"$lt": utcnow() - timedelta(minutes=10)}},
            {"$set": {"status": "done", "result": "interrupted"}})
    except Exception:
        log.exception("recover_sieges failed")


async def terr_income(doc: dict) -> int:
    if not doc.get("guild"):
        return 0
    n = await store.territories.count_documents({"owner": doc["guild"]})
    return n * TERR_INCOME
