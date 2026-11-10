"""🎭 Reply-RPG — پنج سیستمِ گروهیِ «بدونِ دکمه»؛ همه‌چیز با ریپلایِ متن/ایموجی روی پیامِ ربات یا بازیکن.

۱) ⚔️ هیولای زنجیره‌ای  — «حمله» روی پیامِ هیولا؛ دو نفرِ متفاوت پشت‌سرهم = زنجیره؛ پاتکِ هیولا با «پاتک»/«پوشش»؛ لوت بر اساسِ مشارکت.
۲) 🥊 دوئلِ خیابانی     — ریپلای «دوئل» (/duel) روی یه نفر؛ «قبول»؛ حرکتِ مخفیِ شمشیر/جادو/سپر؛ GS از بازنده به برنده.
۳) 🎁 کمین             — گوبلین/صندوقچه/تله/چشمه وسطِ چت؛ سریع‌ترین‌ها با ریپلای پاداش می‌گیرن.
۴) 🪄 طلسم             — ریپلای «طلسم [نوع]»؛ افکتِ ماندگار روی پیام‌های بعدیِ قربانی؛ رفع با ریپلای چند نفر؛ ابتلای زنجیره‌ای.
۵) 🧭 سیاه‌چالِ کوچک     — «سیاه چال»؛ گروه با ریپلای 1 یا 2 رأی می‌ده.

داده: یک کالکشنِ چندمنظوره‌ی `rrpg` (فیلدِ kind = chain|duel|ambush|curse|dungeon). هر پیامِ ربات که قابلِ ریپلاست تو `anchors` ثبت میشه.
امنیت: هر گذار (wait→picking→resolving→done، open→claimed، active→won/lifted) با find_one_and_update اتمیک claim میشه ⇒ پاداش دقیقاً یک‌بار.
انتقالِ GS فقط تو دوئل (debit از بازنده + credit به برنده، ۵٪ کارمزدِ سوخته) و بقیه‌ی جایزه‌ها از players.grant رد میشن (سقفِ روزانه).
"""

import asyncio
import os
import random
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import ReactionTypeEmoji, ReplyParameters
from bson import ObjectId
from pymongo import ReturnDocument

import rr_content as C
from config import GS, log
from content import BLACK_MARKET_ITEMS, roll_item
from database import store
from economy import burn, credit, debit
from players import adjust_survival, gold_bonus, grant, heal_bonus, loss_cut
from rr_core import (
    ACCEPT_RE, BUYOUT_RE, CAST_RE, CHAIN_WINDOW, COUNTER_RE, COVER_RE, DECLINE_RE, DISPEL_RE, DUEL_START_RE,
    DUNGEON_RE, HELP_RE, HIT_CD, HIT_RE, MOVES, OPEN_RE, PRAY_RE, REMATCH_RE, STRIKE_WINDOW, SUMMON_RE,
    bar, duel_roll, duel_stake, hit_damage, parry_damage, parse_choice, parse_curse_type, parse_move,
    rank_share, split_loot, strike_after_cover, tally, tok,
)
from ui import panel
from utils import day_key, esc, is_group, spawn, utcnow

AFTER = ReturnDocument.AFTER
BEFORE = ReturnDocument.BEFORE

ENABLED = os.getenv("RR_ENABLED", "1") == "1"
SPAWN_CHANCE = float(os.getenv("RR_SPAWN_CHANCE", "0.035"))     # شانسِ هر پیامِ گروه برای کمین/سیاه‌چال/هیولا
SPAWN_GAP = int(os.getenv("RR_SPAWN_GAP", "420"))               # حداقل فاصله‌ی دو رویدادِ خودکار تو یه گروه (ثانیه)

CHAIN_TTL = 8 * 60
SUMMON_COST = 30
SUMMON_GAP = 20 * 60
DUEL_WAIT = 75
DUEL_PICK = 30
DUEL_PAIR_DAILY = 4             # حداکثر دوئلِ «همراه با انتقالِ GS» بینِ یه جفت تو روز
DUEL_GAIN_DAILY = 150           # سقفِ سودِ روزانه‌ی هر نفر از دوئل‌ها
DUEL_FEE_PCT = 5
DUEL_CD = 45
CURSE_CD = 90
CURSE_MAX_CHAT = 3
CURSE_TICK_GAP = 25
CURSE_SPREAD_P = 0.2
CURSE_MIN_LEVEL = 2
DG_DAILY = 8
DG_GAP = 240

_elocks: dict = {}
_activity: dict = defaultdict(lambda: deque(maxlen=60))     # chat → [(ts, uid)]
_last_spawn: dict = {}
_cd: dict = {}                                              # (کلید، id) → ts؛ کولداون‌های سبک (حافظه‌ای)
_cursed: dict = {}                                          # (chat, uid) → curse _id (کَشِ سریع برای هر پیام)
_del_cache: dict = {}
_react_last: dict = {}
TRAP_SET = {tok(w) for w in C.TRAP_WORDS}


# ───────────────────────────── 🔧 ابزارها ─────────────────────────────
def _lk(uid, name) -> str:
    return f'<a href="tg://user?id={uid}">{esc(name or "ناشناس")}</a>'


def _now() -> float:
    return time.time()


def _elock(eid) -> asyncio.Lock:
    lk = _elocks.get(eid)
    if lk is None:
        if len(_elocks) > 3000:
            _elocks.clear()
        lk = _elocks[eid] = asyncio.Lock()
    return lk


def _cool(key: tuple, secs: float) -> bool:
    """True = هنوز تو کولداونه؛ وگرنه کولداون رو شروع می‌کنه و False برمی‌گردونه."""
    now = _now()
    if now - _cd.get(key, 0) < secs:
        return True
    if len(_cd) > 5000:
        _cd.clear()
    _cd[key] = now
    return False


async def _send(bot: Bot, chat_id: int, text: str, reply_to: Optional[int] = None) -> Optional[int]:
    try:
        if reply_to:
            msg = await bot.send_message(chat_id, text, reply_parameters=ReplyParameters(
                message_id=reply_to, allow_sending_without_reply=True))
        else:
            msg = await bot.send_message(chat_id, text)
        return msg.message_id
    except Exception:
        log.exception("rrpg send failed")
        return None


async def _anchor(eid, mid: Optional[int]):
    if mid:
        await store.rrpg.update_one({"_id": eid}, {"$push": {"anchors": {"$each": [mid], "$slice": -40}}})


async def _post(bot: Bot, chat_id: int, eid, text: str, reply_to: Optional[int] = None) -> Optional[int]:
    """ارسال + ثبتِ پیام به‌عنوانِ «لنگرِ ریپلای» برای این رویداد."""
    mid = await _send(bot, chat_id, text, reply_to)
    await _anchor(eid, mid)
    return mid


async def _react(bot: Bot, chat_id: int, mid: int, emoji: str):
    now = _now()
    if now - _react_last.get(chat_id, 0) < 0.5:        # ضدِ فلودِ API
        return
    _react_last[chat_id] = now
    try:
        await bot.set_message_reaction(chat_id, mid, reaction=[ReactionTypeEmoji(emoji=emoji)])
    except Exception:
        pass


def _soft(bot: Bot, chat_id: int, mid: int, emoji: str):
    spawn(_react(bot, chat_id, mid, emoji))


def _active_users(chat_id: int, secs: int = 600) -> set:
    lim = _now() - secs
    return {u for ts, u in _activity[chat_id] if ts >= lim}


def _lvl(doc: Optional[dict]) -> int:
    return int((doc or {}).get("level", 1) or 1)


async def _wild_active(chat_id: int) -> bool:
    return bool(await store.rrpg.count_documents({
        "chat_id": chat_id, "kind": {"$in": ["chain", "ambush", "dungeon"]},
        "status": {"$in": ["active", "open"]}, "expires_at": {"$gt": utcnow()}}))


async def _daily_slot(uid: int, day_f: str, n_f: str, limit: int) -> bool:
    """یک «اسلاتِ روزانه» برمی‌داره؛ False = سقفِ امروز پره."""
    today = day_key()
    await store.users.update_one({"user_id": uid, day_f: {"$ne": today}}, {"$set": {day_f: today, n_f: 0}})
    res = await store.users.update_one({"user_id": uid, day_f: today, n_f: {"$lt": limit}}, {"$inc": {n_f: 1}})
    return res.modified_count > 0


async def _safe_edit(bot: Bot, chat_id: int, mid: Optional[int], text: str):
    if not mid:
        return
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=mid)
    except Exception as e:
        log.debug("rrpg edit failed: %s", e)


# ═════════════════════════════ ⚔️ ۱) هیولای زنجیره‌ای ═════════════════════════════
def _chain_text(ev: dict, headline: str, rules: bool = False, extra: Optional[list] = None) -> str:
    hp = max(0, int(ev["hp"]))
    lines = [headline, f"{ev['emoji']} <b>{esc(ev['name'])}</b>", f"❤️ {bar(hp, ev['max_hp'])} <b>{hp}</b>/{ev['max_hp']}"]
    ch = int(ev.get("chain", 0))
    if ch >= 2 and _now() - float(ev.get("last_hit_ts", 0)) <= CHAIN_WINDOW:
        lines.append(f"🔗 زنجیره: <b>{ch}</b> حلقه · ×{min(2.0, 1.0 + 0.1 * (ch - 1)):.1f} دمیج")
    top = sorted(ev.get("contrib", {}).items(), key=lambda kv: -int(kv[1].get("dmg", 0)))[:3]
    if top:
        lines.append("🏅 " + " · ".join(f"{esc(ev['names'].get(k, '؟'))} {int(v.get('dmg', 0))}" for k, v in top))
    lines += extra or []
    if rules:
        lines += ["┈┈┈┈┈┈┈┈┈┈", C.CHAIN_RULES.format(w=int(CHAIN_WINDOW))]
    return panel("red", "⚔️", "هیولای زنجیره‌ای", lines, f"💰 غنیمت: <b>{int(ev.get('pot', 0))} GS</b> · ⏳ {CHAIN_TTL // 60} دقیقه")


async def _spawn_chain(bot: Bot, chat_id: int, summoner: Optional[int] = None) -> bool:
    n = max(2, min(8, len(_active_users(chat_id))))
    emoji, name, mult = random.choice(C.MONSTERS)
    max_hp = int((520 + 150 * n) * mult)
    ev = {"kind": "chain", "chat_id": chat_id, "status": "active", "emoji": emoji, "name": name, "hp": max_hp,
          "max_hp": max_hp, "chain": 0, "best_chain": 0, "last_hit_ts": 0.0, "last_hit_uid": None, "contrib": {},
          "cd": {}, "names": {}, "strikes": {}, "pot": min(360, 60 + 25 * n), "anchors": [], "summoner": summoner,
          "last_status_ts": _now(), "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=CHAIN_TTL)}
    res = await store.rrpg.insert_one(ev)
    ev["_id"] = res.inserted_id
    head = random.choice(C.CHAIN_SPAWN).format(e=emoji, n=esc(name))
    await _post(bot, chat_id, ev["_id"], _chain_text(ev, head, rules=True))
    spawn(_chain_loop(bot, ev["_id"]))
    return True


async def _summon(m, bot: Bot) -> bool:
    if not (is_group(m)):
        return False
    uid = m.from_user.id
    me = await store.get(uid)
    if not me or not me.get("registered"):
        return False
    cid = m.chat.id
    if _lvl(me) < 2:
        await m.reply(panel("purple", "🐲", "احضار", ["از سطح ۲ می‌تونی هیولا احضار کنی."]))
        return True
    if len(_active_users(cid)) < 2:
        await m.reply(panel("purple", "🐲", "احضار", ["گروه خیلی ساکته؛ یه نفر دیگه هم بیاد وسط تا هیولا حال کنه. 🦗"]))
        return True
    if _now() - _last_spawn.get(("summon", cid), 0) < SUMMON_GAP:
        await m.reply(panel("purple", "🐲", "احضار", ["هیولای قبلی هنوز تو حال‌وهواشه؛ بعداً."]))
        return True
    if await _wild_active(cid):
        await m.reply(panel("purple", "🐲", "احضار", ["یه رویدادِ دیگه الان فعاله؛ اول اون تموم بشه."]))
        return True
    if not await debit(uid, SUMMON_COST, "rr_summon"):
        await m.reply(panel("red", "🐲", "احضار", [f"احضار {SUMMON_COST} {GS} خرج داره و نداری."]))
        return True
    _last_spawn[("summon", cid)] = _last_spawn[cid] = _now()
    await _spawn_chain(bot, cid, summoner=uid)
    return True


async def _chain_loop(bot: Bot, eid):
    """هر ۲۲–۳۶ ثانیه هیولا یه پاتک می‌زنه؛ تایم‌اوت = فرار."""
    try:
        while True:
            await asyncio.sleep(random.uniform(22, 36))
            ev = await store.rrpg.find_one({"_id": eid})
            if not ev or ev["status"] != "active":
                return
            if ev["expires_at"] <= utcnow():
                await _chain_flee(bot, ev)
                return
            await _chain_strike(bot, ev)
    except Exception:
        log.exception("chain loop failed")


async def _chain_flee(bot: Bot, ev: dict):
    got = await store.rrpg.find_one_and_update({"_id": ev["_id"], "status": "active"}, {"$set": {"status": "fled"}}, return_document=AFTER)
    if not got:
        return
    for k in got.get("contrib", {}):
        try:
            await grant(int(k), xp=6)
        except Exception:
            log.exception("chain flee xp failed")
    await _send(bot, got["chat_id"], panel("black", "🌫", "فرار", [random.choice(C.CHAIN_FLEE).format(e=got["emoji"], n=esc(got["name"]))],
                                          "همه‌ی شرکت‌کننده‌ها +۶ XP برای تلاش گرفتن."))


async def _chain_strike(bot: Bot, ev: dict):
    now = _now()
    live = [k for k, t in ev.get("cd", {}).items() if now - float(t) < 90]
    if not live:
        return
    tid = int(random.choice(live))
    tname = ev["names"].get(str(tid), "؟")
    d = random.randint(5, 9)
    steal = random.choice((0, 8, 12, 16))
    line = random.choice(C.STRIKE_LINES).format(e=ev["emoji"], n=esc(ev["name"]), t=_lk(tid, tname))
    text = panel("orange", "💢", "پاتکِ هیولا!", [line, f"🩸 ضربه: <b>−{d}٪ بقا</b>"], C.STRIKE_FOOT.format(w=STRIKE_WINDOW))
    mid = await _send(bot, ev["chat_id"], text)
    if not mid:
        return
    await store.rrpg.update_one({"_id": ev["_id"], "status": "active"}, {
        "$set": {f"strikes.{mid}": {"target": tid, "tname": tname, "d": d, "steal": steal, "t": now, "state": "open", "cover": [], "parry": None}},
        "$push": {"anchors": {"$each": [mid], "$slice": -40}}})
    spawn(_resolve_strike(bot, ev["_id"], mid))


async def _resolve_strike(bot: Bot, eid, mid: int):
    try:
        await asyncio.sleep(STRIKE_WINDOW)
        async with _elock(eid):
            ev = await store.rrpg.find_one_and_update(
                {"_id": eid, "status": "active", f"strikes.{mid}.state": "open"},
                {"$set": {f"strikes.{mid}.state": "done"}}, return_document=AFTER)
            if not ev:
                return
            s = ev["strikes"][str(mid)]
            cid, t = ev["chat_id"], _lk(s["target"], s["tname"])
            if s.get("parry"):
                return                                          # پاتک قبلاً اعلام شده
            cov = s.get("cover", [])
            if cov:
                d = strike_after_cover(s["d"], len(cov))
                names = "، ".join(_lk(u, ev["names"].get(str(u), "؟")) for u in cov)
                lines = [random.choice(C.STRIKE_COVER_LINES).format(c=names, d0=s["d"], d=d, t=t)]
                for u in cov:
                    await adjust_survival(u, -1)
            else:
                d = s["d"]
                lines = [random.choice(C.STRIKE_HIT_LINES).format(t=t, d=d)]
                if s.get("steal"):
                    tdoc = await store.get(s["target"])
                    amt = min(int(s["steal"]), int((tdoc or {}).get("gold", 0)))
                    if amt >= 1 and await debit(s["target"], amt, "rr_chain_steal", burn_it=False):
                        await store.rrpg.update_one({"_id": eid}, {"$inc": {"pot": amt}})
                        lines.append(C.STEAL_LINE.format(s=amt))
            tdoc = await store.get(s["target"])
            await adjust_survival(s["target"], -loss_cut(tdoc, d))
            await _send(bot, cid, panel("red" if not cov else "green", "💥" if not cov else "🛡", "نتیجه‌ی پاتک", lines), reply_to=mid)
    except Exception:
        log.exception("resolve strike failed")


async def _chain_route(m, bot: Bot, ev: dict, t: str, me: dict) -> bool:
    uid, mid = m.from_user.id, m.reply_to_message.message_id
    name = m.from_user.full_name
    if HIT_RE.fullmatch(t):
        return await _chain_hit(m, bot, ev, me)
    if ev["status"] != "active":
        return False
    s = ev.get("strikes", {}).get(str(mid))
    if COVER_RE.fullmatch(t):
        if not s or s["state"] != "open":
            return False
        if uid == s["target"]:
            await m.reply(panel("purple", "🛡", "پوشش", ["خودت رو نمی‌تونی پوشش بدی؛ از بقیه کمک بخواه!"]))
            return True
        got = await store.rrpg.find_one_and_update(
            {"_id": ev["_id"], "status": "active", f"strikes.{mid}.state": "open", f"strikes.{mid}.cover": {"$ne": uid}},
            {"$push": {f"strikes.{mid}.cover": uid}, "$inc": {f"contrib.{uid}.cover": 1}, "$set": {f"names.{uid}": name}},
            return_document=AFTER)
        if got:
            _soft(bot, m.chat.id, m.message_id, "🫡")
        return True
    if COUNTER_RE.fullmatch(t):
        if not s or s["state"] != "open":
            return False
        now = _now()
        react = max(0.0, now - float(s["t"]))
        dmg = parry_damage(_lvl(me), react)
        got = await store.rrpg.find_one_and_update(
            {"_id": ev["_id"], "status": "active", f"strikes.{mid}.state": "open", f"strikes.{mid}.parry": None},
            {"$set": {f"strikes.{mid}.parry": {"uid": uid, "t": now}, f"names.{uid}": name},
             "$inc": {"hp": -dmg, f"contrib.{uid}.parry": 1, f"contrib.{uid}.dmg": dmg}}, return_document=AFTER)
        if not got:
            _soft(bot, m.chat.id, m.message_id, "😴")        # یکی زودتر رسید
            return True
        _soft(bot, m.chat.id, m.message_id, "🏆")
        await m.reply(panel("yellow", "⚡", "پاتکِ سرعتی!", [random.choice(C.PARRY_LINES).format(
            a=_lk(uid, name), s=f"{react:.1f}", d=dmg, e=got["emoji"])]))
        if got["hp"] <= 0:
            await _chain_finish(bot, got, uid)
        return True
    return False


async def _chain_hit(m, bot: Bot, ev: dict, me: dict) -> bool:
    uid, name, eid = m.from_user.id, m.from_user.full_name, ev["_id"]
    async with _elock(eid):
        ev = await store.rrpg.find_one({"_id": eid})
        if not ev or ev["status"] != "active":
            _soft(bot, m.chat.id, m.message_id, "🥱")
            return True
        now = _now()
        if now - float(ev["cd"].get(str(uid), 0)) < HIT_CD:
            return True
        gap = now - float(ev.get("last_hit_ts", 0))
        prev, luid = int(ev.get("chain", 0)), ev.get("last_hit_uid")
        broke = 0
        if luid is not None and gap <= CHAIN_WINDOW:
            chain = prev + 1 if luid != uid else max(1, prev)
        else:
            broke = prev if prev >= 4 else 0
            chain = 1
        dmg, crit = hit_damage(_lvl(me), me.get("cls"), chain)
        old_pct = max(0, ev["hp"]) * 100 // ev["max_hp"]
        new = await store.rrpg.find_one_and_update(
            {"_id": eid, "status": "active"},
            {"$inc": {"hp": -dmg, f"contrib.{uid}.dmg": dmg, f"contrib.{uid}.hits": 1},
             "$set": {"chain": chain, "last_hit_ts": now, "last_hit_uid": uid, f"cd.{uid}": now, f"names.{uid}": name},
             "$max": {"best_chain": chain}}, return_document=AFTER)
        if not new:
            return True
        _soft(bot, m.chat.id, m.message_id, "💯" if crit else ("🔥" if chain >= 3 else "⚡"))
        if new["hp"] <= 0:
            await _chain_finish(bot, new, uid)
            return True
        new_pct = max(0, new["hp"]) * 100 // new["max_hp"]
        crossed = any(old_pct > x >= new_pct for x in (75, 50, 25))
        mile = chain in (3, 5, 8, 12) and luid != uid
        if broke or crossed or mile or now - float(new.get("last_status_ts", 0)) >= 25:
            await store.rrpg.update_one({"_id": eid}, {"$set": {"last_status_ts": now}})
            extra = []
            if broke:
                extra.append(C.CHAIN_BREAK.format(n=broke))
            if crit:
                extra.append(f"💥 ضربه‌ی بحرانی از {_lk(uid, name)}!")
            head = f"🔗 <b>زنجیره‌ی {chain}تایی!</b> ادامه بدید!" if mile else "⚔️ نبرد ادامه داره…"
            await _post(bot, m.chat.id, eid, _chain_text(new, head, extra=extra), reply_to=m.message_id)
    return True


async def _chain_finish(bot: Bot, ev: dict, last_uid: int):
    got = await store.rrpg.find_one_and_update({"_id": ev["_id"], "status": "active"},
                                               {"$set": {"status": "won", "finished_at": utcnow()}}, return_document=AFTER)
    if not got:
        return
    ev = got
    scores = {int(k): int(v.get("dmg", 0)) + 40 * int(v.get("cover", 0)) + 120 * int(v.get("parry", 0))
              for k, v in ev.get("contrib", {}).items()}
    pool = int(ev.get("pot", 0)) + min(200, 10 * len(scores))
    split = split_loot(pool, scores, last_uid)
    order = sorted(scores, key=lambda u: -scores[u])
    mvp = order[0] if order else None
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines = [C.CHAIN_WIN.format(n=esc(ev["name"]), a=_lk(last_uid, ev["names"].get(str(last_uid), "؟"))),
             f"🔗 بهترین زنجیره: <b>{int(ev.get('best_chain', 0))}</b> · 👥 {len(scores)} نفر", "┈┈┈┈┈┈┈┈┈┈"]
    for i, u in enumerate(order):
        c = ev["contrib"].get(str(u), {})
        xp = 15 + min(40, scores[u] // 25)
        try:
            await grant(u, gold=split.get(u, 0), xp=xp)
        except Exception:
            log.exception("chain payout failed")
        if i < 5:
            extra = (f" · 🛡{int(c.get('cover', 0))}" if c.get("cover") else "") + (f" · ⚡{int(c.get('parry', 0))}" if c.get("parry") else "")
            lines.append(f"{medals[i]} {_lk(u, ev['names'].get(str(u), '؟'))} — 💥{int(c.get('dmg', 0))}{extra} → +{split.get(u, 0)} {GS}")
    foot = None
    if mvp:
        item, _, _ = roll_item(BLACK_MARKET_ITEMS)
        try:
            await grant(mvp, item=item)
            foot = f"🎁 جایزه‌ی MVP برای {_lk(mvp, ev['names'].get(str(mvp), '؟'))}: {esc(item)}"
        except Exception:
            log.exception("chain mvp failed")
    await _send(bot, ev["chat_id"], panel("yellow", "🏆", "هیولا شکست خورد!", lines, foot))


# ═════════════════════════════ 🥊 ۲) دوئلِ خیابانی ═════════════════════════════
async def _can_delete(bot: Bot, chat_id: int) -> bool:
    c = _del_cache.get(chat_id)
    if c and _now() - c[0] < 600:
        return c[1]
    ok = False
    try:
        cm = await bot.get_chat_member(chat_id, bot.id)
        ok = bool(getattr(cm, "can_delete_messages", False))
    except Exception:
        ok = False
    _del_cache[chat_id] = (_now(), ok)
    return ok


def _duel_arena(ev: dict) -> str:
    p = ev.get("picks", {})
    def st(side: str) -> str:
        return "🔒 قفل شد" if side in p else "⏳ منتظر…"

    lines = [f"{_lk(ev['a'], ev['a_name'])}: {st('a')}", f"{_lk(ev['b'], ev['b_name'])}: {st('b')}", "┈┈┈┈┈┈┈┈┈┈",
             C.DUEL_ARENA_GROUP if ev.get("mode") == "group" else C.DUEL_ARENA_DM, C.DUEL_TRIANGLE]
    return panel("orange", "🥊", "دوئلِ خیابانی", lines, f"⏱ {DUEL_PICK} ثانیه وقت دارید")


async def _duel_open(bot: Bot, chat_id: int, a: int, an: str, b: int, bn: str, reply_to: Optional[int] = None):
    pair = ":".join(str(x) for x in sorted((a, b)))
    ev = {"kind": "duel", "chat_id": chat_id, "status": "wait", "a": a, "a_name": an, "b": b, "b_name": bn, "uids": [a, b],
          "pair": pair, "day": day_key(), "picks": {}, "anchors": [], "created_at": utcnow(),
          "expires_at": utcnow() + timedelta(seconds=DUEL_WAIT)}
    res = await store.rrpg.insert_one(ev)
    ev["_id"] = res.inserted_id
    line = random.choice(C.DUEL_CHALLENGE).format(a=_lk(a, an), b=_lk(b, bn))
    await _post(bot, chat_id, ev["_id"], panel("orange", "🥊", "چالشِ کری‌خوانی!", [line],
                f"{_lk(b, bn)} ← ریپلای «<b>قبول</b>» یا «<b>رد</b>» روی همین پیام · ⏳ {DUEL_WAIT} ثانیه"), reply_to=reply_to)
    spawn(_duel_wait_timer(bot, ev["_id"]))


async def _duel_challenge(m, bot: Bot, me: dict, ru) -> bool:
    uid, cid = m.from_user.id, m.chat.id
    if ru.id == uid:
        await m.reply(panel("orange", "🥊", "دوئل", ["با خودت؟ برو جلوی آینه کری بخون. 🪞"]))
        return True
    if _cool(("duel", uid), DUEL_CD):
        return True
    tdoc = await store.get(ru.id)
    if not tdoc or not tdoc.get("registered"):
        await m.reply(panel("orange", "🥊", "دوئل", ["این بازیکن هنوز ثبت‌نام نکرده."]))
        return True
    if tdoc.get("opted_out") or me.get("opted_out"):
        await m.reply(panel("blue", "🛡", "دوئل", ["یکی از شما «محافظت» رو روشن کرده؛ دوئل نمیشه."]))
        return True
    if await store.rrpg.count_documents({"kind": "duel", "uids": {"$in": [uid, ru.id]},
                                          "status": {"$in": ["wait", "picking"]}, "expires_at": {"$gt": utcnow()}}):
        await m.reply(panel("orange", "🥊", "دوئل", ["یکی از شما همین الان تو یه دوئل درگیره."]))
        return True
    await _duel_open(bot, cid, uid, m.from_user.full_name, ru.id, ru.full_name, reply_to=m.reply_to_message.message_id)
    return True


async def _duel_wait_timer(bot: Bot, eid):
    try:
        await asyncio.sleep(DUEL_WAIT + 1)
        got = await store.rrpg.find_one_and_update({"_id": eid, "status": "wait"}, {"$set": {"status": "expired"}}, return_document=AFTER)
        if got:
            await _send(bot, got["chat_id"], panel("black", "🐔", "کری بی‌جواب", [
                f"{_lk(got['b'], got['b_name'])} جواب نداد؛ کریِ {_lk(got['a'], got['a_name'])} تو هوا موند. 🦗"]))
    except Exception:
        log.exception("duel wait timer failed")


async def _duel_accept(m, bot: Bot, ev: dict) -> bool:
    uid = m.from_user.id
    if ev["status"] != "wait" or uid != ev["b"]:
        return False
    mode = "group" if await _can_delete(bot, m.chat.id) else "dm"
    got = await store.rrpg.find_one_and_update(
        {"_id": ev["_id"], "status": "wait", "b": uid, "expires_at": {"$gt": utcnow()}},
        {"$set": {"status": "picking", "mode": mode, "picks": {}, "pick_start": _now(),
                  "expires_at": utcnow() + timedelta(seconds=DUEL_PICK + 20)}}, return_document=AFTER)
    if not got:
        return True
    mid = await _post(bot, m.chat.id, got["_id"], _duel_arena(got))
    await store.rrpg.update_one({"_id": got["_id"]}, {"$set": {"arena_mid": mid}})
    spawn(_duel_pick_timer(bot, got["_id"]))
    return True


async def _duel_decline(m, ev: dict) -> bool:
    if ev["status"] != "wait" or m.from_user.id != ev["b"]:
        return False
    got = await store.rrpg.find_one_and_update({"_id": ev["_id"], "status": "wait"}, {"$set": {"status": "expired"}}, return_document=AFTER)
    if got:
        await m.reply(panel("black", "🐔", "رد شد", [f"{_lk(got['b'], got['b_name'])} جا زد! {_lk(got['a'], got['a_name'])} با افتخار رفت. 😎"]))
    return True


async def _duel_accept_plain(m, bot: Bot) -> bool:
    """«قبول» بدونِ ریپلای، اگه دوئلِ منتظرِ این نفر تو همین گروه باشه."""
    ev = await store.rrpg.find_one({"kind": "duel", "chat_id": m.chat.id, "b": m.from_user.id, "status": "wait",
                                    "expires_at": {"$gt": utcnow()}})
    return await _duel_accept(m, bot, ev) if ev else False


async def _duel_pick_timer(bot: Bot, eid):
    try:
        await asyncio.sleep(DUEL_PICK)
        await _duel_resolve(bot, eid)
    except Exception:
        log.exception("duel pick timer failed")


async def _duel_pick(m, bot: Bot, ev: dict, move: str, dm: bool) -> bool:
    uid = m.from_user.id
    side = "a" if uid == ev["a"] else ("b" if uid == ev["b"] else None)
    if not side or ev["status"] != "picking":
        return False
    if not dm and ev.get("mode") == "dm":
        await m.reply(panel("purple", "🔒", "حرکتِ مخفی", ["این دوئل مخفیه ولی ربات اینجا ادمین نیست؛ حرکتت رو <b>تو پیوی ربات</b> بنویس."]))
        return True
    if not dm:
        try:
            await m.delete()                                    # حرکت مخفی بمونه
        except Exception:
            log.debug("rrpg: delete failed in %s", m.chat.id)
    got = await store.rrpg.find_one_and_update(
        {"_id": ev["_id"], "status": "picking", f"picks.{side}": {"$exists": False}},
        {"$set": {f"picks.{side}": {"m": move, "t": _now()}}}, return_document=AFTER)
    if dm:
        await m.reply("🔒 حرکتت قفل شد!" if got else "قبلاً حرکتت رو فرستادی یا دوئل تموم شده.")
    if not got:
        return True
    await _safe_edit(bot, got["chat_id"], got.get("arena_mid"), _duel_arena(got))
    if "a" in got["picks"] and "b" in got["picks"]:
        await _duel_resolve(bot, got["_id"])
    return True


async def _duel_resolve(bot: Bot, eid):
    async with _elock(eid):
        ev = await store.rrpg.find_one_and_update({"_id": eid, "status": "picking"}, {"$set": {"status": "resolving"}}, return_document=AFTER)
        if not ev:
            return
        cid, a, b = ev["chat_id"], ev["a"], ev["b"]
        al, bl = _lk(a, ev["a_name"]), _lk(b, ev["b_name"])
        pa, pb = ev["picks"].get("a"), ev["picks"].get("b")
        if not pa and not pb:
            await store.rrpg.update_one({"_id": eid}, {"$set": {"status": "expired"}})
            await _send(bot, cid, panel("black", "🦗", "دوئلِ سایلنت", [random.choice(C.DUEL_GHOST)]))
            return
        ad, bd = await store.get(a), await store.get(b)
        ma, mb = (pa or {}).get("m"), (pb or {}).get("m")
        info = {"tri": None, "upset": False, "crit": False}
        if pa and pb:
            info = duel_roll(ma, mb, _lvl(ad), _lvl(bd), pa["t"], pb["t"])
            win = info["winner"]
        else:
            win = "a" if pa else "b"
        lose = "b" if win == "a" else "a"
        wu, lu = (a, b) if win == "a" else (b, a)
        wl, ll = (al, bl) if win == "a" else (bl, al)
        wdoc, ldoc = (ad, bd) if win == "a" else (bd, ad)
        lines = []
        if pa and pb:
            lines.append(f"{al}  <b>{MOVES[ma]}</b>   ⚔   <b>{MOVES[mb]}</b>  {bl}")
            wm, lm = (ma, mb) if win == "a" else (mb, ma)
            if info["tri"] == win:
                lines.append(random.choice(C.DUEL_WIN_LINES[(wm, lm)]).format(w=wl, l=ll))
            elif info["tri"] is None:
                lines.append(C.DUEL_DRAW_LINES[ma].format(f=wl))
            else:
                lines.append(random.choice(C.DUEL_UPSET).format(w=wl, l=ll))
        else:
            lines.append(random.choice(C.DUEL_FORFEIT).format(w=wl, l=ll))
        if info["crit"]:
            lines.append(random.choice(C.DUEL_CRIT).format(w=wl))
        # 🪙 انتقالِ GS (با سقف‌های ضدِ فارم)
        stake, note = 0, None
        paid_today = await store.rrpg.count_documents({"kind": "duel", "pair": ev["pair"], "day": day_key(), "paid": True})
        gain_ok = bool(wdoc) and not (wdoc.get("rr_duel_day") == day_key() and int(wdoc.get("rr_duel_gain", 0)) >= DUEL_GAIN_DAILY)
        if paid_today >= DUEL_PAIR_DAILY:
            note = "🔁 سقفِ جابه‌جاییِ GS بینِ این دو نفر برای امروز پر شده؛ فقط افتخار!"
        elif not gain_ok:
            note = "🔁 سقفِ سودِ روزانه‌ی برنده پر شده؛ فقط افتخار!"
        else:
            stake = duel_stake(int((ldoc or {}).get("gold", 0)), _lvl(wdoc))
        got_amt = 0
        if stake and await debit(lu, stake, "rr_duel_loss", burn_it=False):
            fee = stake * DUEL_FEE_PCT // 100
            got_amt = stake - fee
            await credit(wu, got_amt, "rr_duel_win")
            await burn(fee, "rr_duel_fee")
            today = day_key()
            await store.users.update_one({"user_id": wu, "rr_duel_day": {"$ne": today}}, {"$set": {"rr_duel_day": today, "rr_duel_gain": 0}})
            await store.users.update_one({"user_id": wu}, {"$inc": {"rr_duel_gain": got_amt}})
            lines.append(C.DUEL_LOOT.format(w=wl, l=ll, g=got_amt))
        else:
            lines.append(C.DUEL_NOLOOT.format(l=ll) if not note else note)
        await grant(wu, xp=12 + (8 if info["upset"] else 0))
        await grant(lu, xp=4)
        await adjust_survival(lu, -loss_cut(ldoc, 3))
        await store.users.update_one({"user_id": wu}, {"$inc": {"rr_duel_w": 1}})
        await store.users.update_one({"user_id": lu}, {"$inc": {"rr_duel_l": 1}})
        lines.append(f"✨ {wl}: +{12 + (8 if info['upset'] else 0)} XP · {ll}: +4 XP و −3٪ بقا")
        mid = await _send(bot, cid, panel("orange", "🥊", "نتیجه‌ی دوئلِ خیابانی", lines, C.DUEL_ENDER.format(w=wl)), reply_to=ev.get("arena_mid"))
        await store.rrpg.update_one({"_id": eid}, {"$set": {"status": "done", "winner": wu, "loser": lu, "paid": bool(got_amt),
                                                              "result_mid": mid},
                                                    "$push": {"anchors": {"$each": [mid] if mid else [], "$slice": -40}}})


async def _duel_route(m, bot: Bot, ev: dict, t: str) -> bool:
    uid = m.from_user.id
    st = ev["status"]
    if st == "wait":
        if ACCEPT_RE.fullmatch(t):
            return await _duel_accept(m, bot, ev)
        if DECLINE_RE.fullmatch(t):
            return await _duel_decline(m, ev)
        return False
    if st == "picking":
        mv = parse_move(t)
        return await _duel_pick(m, bot, ev, mv, dm=False) if mv else False
    if st == "done" and ev.get("winner"):
        wu, lu = ev["winner"], ev.get("loser")
        wname = ev["a_name"] if wu == ev["a"] else ev["b_name"]
        # بازنده: «ریمچ» · تماشاچی‌ها (و بازنده): «دوئل» روی نتیجه = چالش با برنده
        if (REMATCH_RE.fullmatch(t) and uid == lu) or (DUEL_START_RE.fullmatch(t) and uid != wu):
            if _cool(("duel", uid), DUEL_CD):
                return True
            if await store.rrpg.count_documents({"kind": "duel", "uids": {"$in": [uid, wu]}, "status": {"$in": ["wait", "picking"]},
                                                  "expires_at": {"$gt": utcnow()}}):
                return True
            await _duel_open(bot, m.chat.id, uid, m.from_user.full_name, wu, wname, reply_to=m.message_id)
            return True
    return False


async def _dm(m, bot: Bot, t: str) -> bool:
    mv = parse_move(t)
    if not mv:
        return False
    ev = await store.rrpg.find_one({"kind": "duel", "uids": m.from_user.id, "status": "picking", "expires_at": {"$gt": utcnow()}},
                                    sort=[("created_at", -1)])
    return await _duel_pick(m, bot, ev, mv, dm=True) if ev else False


# ═════════════════════════════ 🎁 ۳) کمین و رویدادهای تصادفی ═════════════════════════════
AMBUSH_MAX = {"goblin": 3, "chest": 1, "trap": 3, "shrine": 5}
AMBUSH_COLOR = {"goblin": "red", "chest": "yellow", "trap": "orange", "shrine": "blue"}


async def _spawn_ambush(bot: Bot, chat_id: int, atype: Optional[str] = None) -> bool:
    atype = atype or random.choices(["goblin", "chest", "trap", "shrine"], weights=[45, 25, 20, 10])[0]
    icon, title, texts, rules = C.AMBUSH_SPAWN[atype]
    word = random.choice(C.TRAP_WORDS) if atype == "trap" else None
    name = random.choice(C.GOBLIN_NAMES) if atype == "goblin" else None
    ev = {"kind": "ambush", "chat_id": chat_id, "atype": atype, "status": "open", "word": word, "gname": name,
          "claim_count": 0, "claimed": [], "wrong": [], "max_claims": AMBUSH_MAX[atype], "anchors": [], "posted_at": _now(),
          "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=C.AMBUSH_TTL)}
    res = await store.rrpg.insert_one(ev)
    ev["_id"] = res.inserted_id
    body = random.choice(texts).format(n=esc(name or ""), w=esc(word or ""))
    mid = await _post(bot, chat_id, ev["_id"], panel(AMBUSH_COLOR[atype], icon, title, [body, "┈┈┈┈┈┈┈┈┈┈", rules.format(w=esc(word or ""))]))
    ev["msg"] = mid
    if mid:
        await store.rrpg.update_one({"_id": ev["_id"]}, {"$set": {"posted_at": _now()}})
    spawn(_ambush_timer(bot, ev["_id"]))
    return True


async def _ambush_timer(bot: Bot, eid):
    try:
        await asyncio.sleep(C.AMBUSH_TTL + 1)
        got = await store.rrpg.find_one_and_update({"_id": eid, "status": "open"}, {"$set": {"status": "closed"}}, return_document=AFTER)
        if got and got["claim_count"] == 0:
            await _send(bot, got["chat_id"], panel("black", "💨", "رفت…", [C.AMBUSH_FLEE[got["atype"]]]))
    except Exception:
        log.exception("ambush timer failed")


async def _ambush_route(m, bot: Bot, ev: dict, t: str, me: dict) -> bool:
    atype, uid, name = ev["atype"], m.from_user.id, m.from_user.full_name
    ok = {"goblin": bool(HIT_RE.fullmatch(t)), "chest": bool(OPEN_RE.fullmatch(t)), "shrine": bool(PRAY_RE.fullmatch(t)),
          "trap": t == tok(ev.get("word") or "")}[atype]
    if atype == "trap" and not ok and t in TRAP_SET:
        got = await store.rrpg.find_one_and_update({"_id": ev["_id"], "status": "open", "wrong": {"$ne": uid}}, {"$addToSet": {"wrong": uid}}, return_document=AFTER)
        if got:
            await adjust_survival(uid, -loss_cut(me, 2))
            await m.reply(C.AMBUSH_WRONG.format(a=_lk(uid, name)))
        return True
    if not ok:
        return False
    got = await store.rrpg.find_one_and_update(
        {"_id": ev["_id"], "status": "open", "claimed": {"$ne": uid}, "claim_count": {"$lt": ev["max_claims"]},
         "expires_at": {"$gt": utcnow()}},
        {"$inc": {"claim_count": 1}, "$addToSet": {"claimed": uid}}, return_document=AFTER)
    if not got:
        _soft(bot, m.chat.id, m.message_id, "😴")
        return True
    rank = got["claim_count"]
    if rank >= got["max_claims"]:
        await store.rrpg.update_one({"_id": ev["_id"], "status": "open"}, {"$set": {"status": "closed"}})
    ms = int((_now() - float(ev["posted_at"])) * 1000)
    share = rank_share(rank) if atype in ("goblin", "trap") else 1.0
    a = _lk(uid, name)
    lines = [random.choice(C.AMBUSH_WIN[atype]).format(a=a, n=esc(ev.get("gname") or ""))]
    foot = f"⏱ {ms / 1000:.2f} ثانیه · رتبه‌ی {rank}"
    if atype == "goblin":
        g = gold_bonus(me, int(random.randint(40, 90) * share))
        item = roll_item(BLACK_MARKET_ITEMS)[0] if random.random() < 0.3 * share else None
        await grant(uid, gold=g, xp=int(20 * share) + 5, item=item)
        lines.append(f"🪙 +{g} {GS} · ✨ +{int(20 * share) + 5} XP" + (f" · 🎁 {esc(item)}" if item else ""))
    elif atype == "trap":
        g = gold_bonus(me, int(random.randint(25, 60) * share))
        await grant(uid, gold=g, xp=int(15 * share) + 4)
        lines.append(f"🪙 +{g} {GS} · ✨ +{int(15 * share) + 4} XP")
    elif atype == "shrine":
        h = heal_bonus(me, random.randint(6, 12))
        await adjust_survival(uid, h)
        await grant(uid, xp=8)
        lines.append(f"💚 +{h}٪ بقا · ✨ +8 XP")
    else:                                                       # chest
        if random.random() < 0.2:
            d = loss_cut(me, random.randint(8, 14))
            await adjust_survival(uid, -d)
            await debit(uid, 20, "rr_mimic")
            lines = [C.AMBUSH_MIMIC.format(a=a, d=d, g=20)]
        else:
            g = gold_bonus(me, random.randint(40, 120))
            item = roll_item(BLACK_MARKET_ITEMS)[0]
            await grant(uid, gold=g, xp=random.randint(15, 30), item=item)
            lines.append(f"🪙 +{g} {GS} · 🎁 {esc(item)}")
    _soft(bot, m.chat.id, m.message_id, "🏆" if rank == 1 else "🎉")
    await m.reply(panel(AMBUSH_COLOR[atype], C.AMBUSH_SPAWN[atype][0], "سریع بودی!" if rank == 1 else "نزدیک بود!", lines, foot))
    return True


# ═════════════════════════════ 🪄 ۴) طلسم‌ها ═════════════════════════════
async def _curse_create(bot: Bot, chat_id: int, caster: int, cname: str, target: int, tname: str, ctype: str,
                        depth: int = 0, ticks: Optional[int] = None, ttl: int = C.CURSE_TTL,
                        spread_from: Optional[str] = None) -> Optional[dict]:
    info = C.CURSES[ctype]
    ev = {"kind": "curse", "chat_id": chat_id, "status": "active", "ctype": ctype, "caster": caster, "caster_name": cname,
          "target": target, "target_name": tname, "need": C.CURSE_NEED, "helpers": [], "hn": {}, "depth": depth,
          "ticks_left": ticks or info["ticks"], "last_tick": 0.0, "anchors": [], "created_at": utcnow(),
          "expires_at": utcnow() + timedelta(seconds=ttl)}
    res = await store.rrpg.insert_one(ev)
    ev["_id"] = res.inserted_id
    _cursed[(chat_id, target)] = ev["_id"]
    t = _lk(target, tname)
    if spread_from:
        head = C.CURSE_SPREAD.format(t=t, s=spread_from, i=info["icon"], c=info["name"])
    else:
        head = random.choice(C.CURSE_CAST).format(a=_lk(caster, cname), t=t, c=info["name"], i=info["icon"])
    foot = C.CURSE_CAST_FOOT.format(n=C.CURSE_NEED, t=t, b=C.CURSE_BUYOUT, m=ttl // 60)
    await _post(bot, chat_id, ev["_id"], panel("purple", info["icon"], info["name"], [head, f"📜 {info['desc']}"], foot))
    spawn(_curse_timer(bot, ev["_id"], ttl))
    return ev


async def _curse_cast(m, bot: Bot, me: dict, ru, t: str) -> bool:
    uid, cid = m.from_user.id, m.chat.id
    arg = CAST_RE.fullmatch(t).group(1)
    ctype = parse_curse_type(arg)
    if ctype == "":
        await m.reply(panel("purple", "🪄", "طلسم", ["نوعِ طلسم؟ «طلسم قورباغه» · «طلسم آتش» · «طلسم جیب» · «طلسم دلقک» (یا فقط «طلسم» برای شانسی)"]))
        return True
    if ru.id == uid:
        return False
    if _lvl(me) < CURSE_MIN_LEVEL:
        await m.reply(panel("purple", "🪄", "طلسم", [f"طلسم از سطح {CURSE_MIN_LEVEL} باز میشه."]))
        return True
    if _cool(("curse", uid), CURSE_CD):
        await m.reply(panel("purple", "🪄", "طلسم", ["ورد خوندن خستگی داره؛ چند لحظه صبر کن."]))
        return True
    tdoc = await store.get(ru.id)
    if not tdoc or not tdoc.get("registered") or tdoc.get("opted_out") or me.get("opted_out"):
        await m.reply(panel("blue", "🛡", "طلسم", ["این بازیکن ثبت‌نام نکرده یا «محافظت» روشنه؛ طلسمت برگشت و دودش رفت تو چشمت. 🪞"]))
        return True
    if float(tdoc.get("rr_immune_until", 0)) > _now():
        await m.reply(panel("blue", "✨", "طلسم", ["این بازیکن تازه رفع طلسم شده و مصونه؛ بعداً بیا."]))
        return True
    if (cid, ru.id) in _cursed:
        await m.reply(panel("purple", "🪄", "طلسم", ["این بدبخت از قبل طلسم داره! 🕯"]))
        return True
    if await store.rrpg.count_documents({"kind": "curse", "chat_id": cid, "status": "active"}) >= CURSE_MAX_CHAT:
        await m.reply(panel("purple", "🪄", "طلسم", ["تو این گروه همین الان کلی طلسمِ فعاله؛ بذار بعضی‌هاشون تموم بشن."]))
        return True
    if not await debit(uid, C.CURSE_COST, "rr_curse"):
        await m.reply(panel("red", "🪄", "طلسم", [f"طلسم {C.CURSE_COST} {GS} می‌خواد (خاکِ قبرستون گرونه!)."]))
        return True
    await _curse_create(bot, cid, uid, m.from_user.full_name, ru.id, ru.full_name, ctype or random.choice(list(C.CURSES)))
    return True


async def _curse_timer(bot: Bot, cid_: ObjectId, ttl: int):
    try:
        await asyncio.sleep(ttl + 1)
        got = await store.rrpg.find_one_and_update({"_id": cid_, "status": "active"}, {"$set": {"status": "expired"}}, return_document=AFTER)
        if got:
            _cursed.pop((got["chat_id"], got["target"]), None)
            await _send(bot, got["chat_id"], panel("black", "⌛", "پایانِ طلسم", [
                C.CURSE_EXPIRED.format(t=_lk(got["target"], got["target_name"]), a=_lk(got["caster"], got["caster_name"]))]))
    except Exception:
        log.exception("curse timer failed")


async def _curse_tick(m, bot: Bot):
    """هر پیامِ گروهِ نفرین‌شده: افکتِ ماندگار (با فاصله‌ی ۲۵ ثانیه‌ای تا چت پر نشه)."""
    key = (m.chat.id, m.from_user.id)
    cid_ = _cursed.get(key)
    if not cid_:
        return
    now = _now()
    got = await store.rrpg.find_one_and_update(
        {"_id": cid_, "status": "active", "ticks_left": {"$gt": 0}, "last_tick": {"$lte": now - CURSE_TICK_GAP}, "expires_at": {"$gt": utcnow()}},
        {"$set": {"last_tick": now}, "$inc": {"ticks_left": -1}}, return_document=AFTER)
    if not got:
        doc = await store.rrpg.find_one({"_id": cid_}, {"status": 1})
        if not doc or doc["status"] != "active":
            _cursed.pop(key, None)
        return
    uid, name = m.from_user.id, m.from_user.full_name
    t = _lk(uid, name)
    me = await store.get(uid)
    ct = got["ctype"]
    if ct == "frog":
        words = (m.text or "").split()[:8] or ["…"]
        out = " ".join(random.choice(C.FROG_WORDS) for _ in words)
        await adjust_survival(uid, -loss_cut(me, 1))
        txt = C.FROG_LINE.format(x=esc(out)) + "  🐸 −1٪"
    elif ct == "fire":
        await adjust_survival(uid, -loss_cut(me, 2))
        txt = random.choice(C.FIRE_LINES).format(t=t)
    elif ct == "pocket":
        g = random.randint(2, 6)
        if int((me or {}).get("gold", 0)) >= g and await debit(uid, g, "rr_pocket"):
            txt = random.choice(C.POCKET_LINES).format(t=t, g=g)
        else:
            await adjust_survival(uid, -loss_cut(me, 1))
            txt = C.POCKET_EMPTY.format(t=t)
    else:
        await adjust_survival(uid, -loss_cut(me, 1))
        txt = random.choice(C.CLOWN_LINES).format(t=t)
    if got["ticks_left"] <= 0:
        await store.rrpg.update_one({"_id": cid_, "status": "active"}, {"$set": {"status": "expired"}})
        _cursed.pop(key, None)
        txt += "\n" + C.CURSE_LAST.format(t=t)
    try:
        await m.reply(f"{C.CURSES[ct]['icon']} {txt}")
    except Exception:
        log.exception("curse tick reply failed")


async def _curse_lift(bot: Bot, cur: dict, how: str, name_by: str = "") -> bool:
    got = await store.rrpg.find_one_and_update({"_id": cur["_id"], "status": "active"}, {"$set": {"status": "lifted", "how": how}}, return_document=AFTER)
    if not got:
        return False
    _cursed.pop((got["chat_id"], got["target"]), None)
    return True


async def _curse_dispel(m, bot: Bot, cur: dict) -> bool:
    uid, name = m.from_user.id, m.from_user.full_name
    if cur["status"] != "active":
        return False
    if uid == cur["target"]:
        await m.reply(panel("purple", "🕯", "رفع طلسم", ["خودت نمی‌تونی رفعش کنی؛ از بقیه بخواه یا «بازخرید» بزن."]))
        return True
    if uid == cur["caster"]:
        await m.reply(panel("purple", "🕯", "رفع طلسم", ["طلسم‌کننده خودش نمی‌تونه رفعش کنه! 😏"]))
        return True
    got = await store.rrpg.find_one_and_update(
        {"_id": cur["_id"], "status": "active", "helpers": {"$ne": uid}},
        {"$addToSet": {"helpers": uid}, "$set": {f"hn.{uid}": name}}, return_document=AFTER)
    if not got:
        return True
    _soft(bot, m.chat.id, m.message_id, "🙏")
    n = len(got["helpers"])
    if n < got["need"]:
        await m.reply(C.CURSE_PROGRESS.format(h=_lk(uid, name), n=n, need=got["need"]))
        return True
    if not await _curse_lift(bot, got, "helpers"):
        return True
    hs = got["helpers"]
    for h in hs:
        try:
            await grant(h, gold=6, xp=10)
        except Exception:
            log.exception("curse helper reward failed")
    await adjust_survival(got["target"], 2)
    await store.users.update_one({"user_id": got["target"]}, {"$set": {"rr_immune_until": _now() + 1800}})
    names = "، ".join(_lk(h, got["hn"].get(str(h), "؟")) for h in hs)
    await _send(bot, got["chat_id"], panel("green", "🌟", "طلسم شکست!", [
        random.choice(C.CURSE_LIFTED).format(h=names, t=_lk(got["target"], got["target_name"])),
        "🎁 هر کمک‌کننده: +6 GS و +10 XP"]))
    return True


async def _curse_buyout(m, bot: Bot) -> bool:
    uid = m.from_user.id
    cid_ = _cursed.get((m.chat.id, uid))
    if not cid_:
        return False
    cur = await store.rrpg.find_one({"_id": cid_, "status": "active"})
    if not cur:
        _cursed.pop((m.chat.id, uid), None)
        return False
    if not await debit(uid, C.CURSE_BUYOUT, "rr_buyout"):
        await m.reply(panel("red", "💸", "بازخرید", [f"بازخریدِ طلسم {C.CURSE_BUYOUT} {GS} می‌خواد."]))
        return True
    if await _curse_lift(bot, cur, "buyout"):
        await store.users.update_one({"user_id": uid}, {"$set": {"rr_immune_until": _now() + 600}})
        await m.reply(panel("green", "💸", "بازخرید", [C.CURSE_BOUGHT.format(t=_lk(uid, m.from_user.full_name), b=C.CURSE_BUYOUT)]))
    else:
        await credit(uid, C.CURSE_BUYOUT, "rr_buyout_refund")
    return True


async def _dispel_on_user(m, bot: Bot, ru) -> bool:
    cid_ = _cursed.get((m.chat.id, ru.id))
    if not cid_:
        return False
    cur = await store.rrpg.find_one({"_id": cid_, "status": "active"})
    if not cur:
        _cursed.pop((m.chat.id, ru.id), None)
        return False
    return await _curse_dispel(m, bot, cur)


async def _maybe_spread(m, bot: Bot, me: dict, ru):
    """🦠 هر کی به نفرین‌شده ریپلای بزنه، ریسکِ ابتلا داره (حداکثر دو جهش)."""
    cid_ = _cursed.get((m.chat.id, ru.id))
    uid = m.from_user.id
    if not cid_ or (m.chat.id, uid) in _cursed or me.get("opted_out") or random.random() > CURSE_SPREAD_P:
        return
    if float(me.get("rr_immune_until", 0)) > _now():
        return
    cur = await store.rrpg.find_one({"_id": cid_, "status": "active"})
    if not cur or cur.get("depth", 0) >= 2:
        return
    if await store.rrpg.count_documents({"kind": "curse", "chat_id": m.chat.id, "status": "active"}) >= CURSE_MAX_CHAT:
        return
    await _curse_create(bot, m.chat.id, cur["caster"], cur["caster_name"], uid, m.from_user.full_name, cur["ctype"],
                        depth=cur.get("depth", 0) + 1, ticks=max(2, cur["ticks_left"] // 2 + 1), ttl=12 * 60,
                        spread_from=_lk(ru.id, ru.full_name))


async def _curse_route(m, bot: Bot, cur: dict, t: str) -> bool:
    if DISPEL_RE.fullmatch(t):
        return await _curse_dispel(m, bot, cur)
    if BUYOUT_RE.fullmatch(t) and m.from_user.id == cur["target"]:
        return await _curse_buyout(m, bot)
    return False


# ═════════════════════════════ 🧭 ۵) سیاه‌چالِ کوچک ═════════════════════════════
def _dg_node(sc: dict, path: str) -> dict:
    return sc["start"] if not path else sc["n"][path]


def _dg_text(sc: dict, node: dict, step: int) -> str:
    lines = [node["t"], "┈┈┈┈┈┈┈┈┈┈"] + [f"<b>{k}</b> ‹ {v}" for k, v in node["c"].items()]
    return panel("purple", sc["icon"], f"{sc['title']} · مرحله {step + 1}/2", lines,
                 C.DG_VOTE_HINT.format(s=C.DG_TTL, q=C.DG_QUORUM))


async def _dg_start(bot: Bot, chat_id: int, starter: Optional[int] = None) -> bool:
    sc = random.choice(C.DUNGEONS)
    ev = {"kind": "dungeon", "chat_id": chat_id, "status": "active", "sid": sc["id"], "step": 0, "path": "", "votes": {},
          "party": {}, "step0": [], "cur_msg": None, "anchors": [], "starter": starter, "created_at": utcnow(),
          "expires_at": utcnow() + timedelta(seconds=C.DG_TTL * 3 + 20)}
    res = await store.rrpg.insert_one(ev)
    ev["_id"] = res.inserted_id
    mid = await _post(bot, chat_id, ev["_id"], _dg_text(sc, sc["start"], 0))
    await store.rrpg.update_one({"_id": ev["_id"]}, {"$set": {"cur_msg": mid}})
    spawn(_dg_timer(bot, ev["_id"], 0))
    return True


async def _dungeon_cmd(m, bot: Bot) -> bool:
    if not is_group(m):
        return False
    me = await store.get(m.from_user.id)
    if not me or not me.get("registered"):
        return False
    cid = m.chat.id
    if _now() - _last_spawn.get(("dg", cid), 0) < DG_GAP:
        await m.reply(panel("purple", "🧭", "سیاه‌چال", ["هنوز کسی از سیاه‌چالِ قبلی برنگشته؛ چند دقیقه صبر کن."]))
        return True
    if await _wild_active(cid):
        await m.reply(panel("purple", "🧭", "سیاه‌چال", ["یه رویدادِ دیگه الان فعاله؛ اول اون تموم بشه."]))
        return True
    _last_spawn[("dg", cid)] = _last_spawn[cid] = _now()
    return await _dg_start(bot, cid, starter=m.from_user.id)


async def _dg_timer(bot: Bot, eid, step: int):
    try:
        await asyncio.sleep(C.DG_TTL)
        await _dg_advance(bot, eid, step)
    except Exception:
        log.exception("dg timer failed")


async def _dg_route(m, bot: Bot, ev: dict, t: str) -> bool:
    ch = parse_choice(t)
    if not ch or ev["status"] != "active":
        return False
    uid, mid = m.from_user.id, m.reply_to_message.message_id
    if ev.get("cur_msg") != mid:
        _soft(bot, m.chat.id, m.message_id, "🥱")          # پیامِ مرحله‌ی قبل
        return True
    got = await store.rrpg.find_one_and_update(
        {"_id": ev["_id"], "status": "active", "step": ev["step"], f"votes.{uid}": {"$exists": False}},
        {"$set": {f"votes.{uid}": ch, f"party.{uid}": m.from_user.full_name}}, return_document=AFTER)
    if not got:
        return True
    _soft(bot, m.chat.id, m.message_id, "👌")
    if len(got["votes"]) >= C.DG_QUORUM:
        spawn(_dg_advance(bot, ev["_id"], ev["step"]))
    return True


async def _dg_advance(bot: Bot, eid, step: int):
    old = await store.rrpg.find_one_and_update({"_id": eid, "status": "active", "step": step},
                                               {"$set": {"step": step + 1, "votes": {}}}, return_document=BEFORE)
    if not old:
        return
    cid = old["chat_id"]
    sc = next(s for s in C.DUNGEONS if s["id"] == old["sid"])
    votes = {int(k): v for k, v in old["votes"].items()}
    if not votes and step == 0:
        await store.rrpg.update_one({"_id": eid}, {"$set": {"status": "expired"}})
        await _send(bot, cid, panel("black", sc["icon"], sc["title"], ["هیشکی جرأتِ وارد شدن نداشت؛ ورودی تو مه ناپدید شد. 🌫"]))
        return
    choice = tally(votes)
    path = old["path"] + str(choice)
    if step == 0:
        node = sc["n"][path]
        mid = await _send(bot, cid, _dg_text(sc, node, 1))
        await store.rrpg.update_one({"_id": eid}, {"$set": {"path": path, "cur_msg": mid, "step0": list(votes)},
                                                   "$push": {"anchors": {"$each": [mid] if mid else [], "$slice": -40}}})
        spawn(_dg_timer(bot, eid, 1))
        return
    await _dg_finish(bot, old, sc, path, votes, choice)


async def _dg_finish(bot: Bot, ev: dict, sc: dict, path: str, votes: dict, choice: int):
    text, kind = sc["end"][path]
    icon, (g_lo, g_hi), xp, item_p, loss = C.DG_END_KINDS[kind]
    party = {int(k): v for k, v in ev.get("party", {}).items()}
    final = set(votes)
    major = [u for u, v in votes.items() if v == choice]
    lucky = random.choice(major) if major and random.random() < item_p else None
    lines = [text, "┈┈┈┈┈┈┈┈┈┈", f"{icon} پایان: <b>{C.DG_KIND_NAME[kind]}</b> · 👥 {len(party)} نفر"]
    shown = 0
    for u, nm in party.items():
        mult = 1.0 if u in major else (0.5 if u in final else 0.6)
        if not await _daily_slot(u, "rr_dg_day", "rr_dg_n", DG_DAILY):
            mult = 0.0
        g = int(random.randint(g_lo, g_hi) * mult) if g_hi else 0
        doc = await store.get(u)
        if g:
            g = gold_bonus(doc, g)
        x = int(xp * mult)
        item = roll_item(BLACK_MARKET_ITEMS)[0] if u == lucky else None
        try:
            if g or x or item:
                await grant(u, gold=g, xp=x, item=item)
            if loss and u in final:
                await adjust_survival(u, -loss_cut(doc, random.randint(*loss)))
        except Exception:
            log.exception("dungeon payout failed")
        if shown < 6:
            shown += 1
            bits = []
            if g:
                bits.append(f"+{g} {GS}")
            if x:
                bits.append(f"+{x} XP")
            if item:
                bits.append(f"🎁 {esc(item)}")
            if loss and u in final:
                bits.append("🩸 زخمی")
            lines.append(f"• {_lk(u, nm)} {'· ' + ' · '.join(bits) if bits else '· (سقفِ امروز پره)'}")
    if len(party) > 6:
        lines.append(f"… و {len(party) - 6} نفرِ دیگه")
    await store.rrpg.update_one({"_id": ev["_id"]}, {"$set": {"status": "done", "ending": path}})
    await _send(bot, ev["chat_id"], panel("yellow" if kind in ("jackpot", "win") else "red", sc["icon"], sc["title"], lines,
                                         "🧭 دوباره؟ بنویس «سیاه چال»"))


# ═════════════════════════════ 🔀 مسیریابی، هوک‌ها، ریکاوری ═════════════════════════════
async def _route(m, bot: Bot, ev: dict, t: str, me: dict) -> bool:
    k = ev.get("kind")
    if k == "chain":
        return await _chain_route(m, bot, ev, t, me)
    if k == "duel":
        return await _duel_route(m, bot, ev, t)
    if k == "ambush":
        return await _ambush_route(m, bot, ev, t, me)
    if k == "curse":
        return await _curse_route(m, bot, ev, t)
    if k == "dungeon":
        return await _dg_route(m, bot, ev, t)
    return False


async def handle(m, bot: Bot) -> bool:
    """ورودیِ اصلی از game_text.handle_text؛ True = پیام مصرف شد."""
    if not ENABLED or not m.from_user or m.from_user.is_bot or not m.text:
        return False
    t = tok(m.text)
    if not t or len(t) > 40:
        return False
    try:
        if not is_group(m):
            return await _dm(m, bot, t)
        rt = m.reply_to_message
        if rt is None:
            if SUMMON_RE.fullmatch(t):
                return await _summon(m, bot)
            if DUNGEON_RE.fullmatch(t):
                return await _dungeon_cmd(m, bot)
            if HELP_RE.fullmatch(t):
                await m.reply(panel("purple", "🎭", "راهنمای ریپلای‌ها", C.HELP_TEXT))
                return True
            if ACCEPT_RE.fullmatch(t):
                return await _duel_accept_plain(m, bot)
            if BUYOUT_RE.fullmatch(t):
                return await _curse_buyout(m, bot)
            return False
        me = await store.get(m.from_user.id)
        if not me or not me.get("registered"):
            return False
        ru = rt.from_user
        if ru is None:
            return False
        if ru.id == bot.id:
            ev = await store.rrpg.find_one({"chat_id": m.chat.id, "anchors": rt.message_id})
            return await _route(m, bot, ev, t, me) if ev else False
        if ru.is_bot:
            return False
        if DUEL_START_RE.fullmatch(t):
            return await _duel_challenge(m, bot, me, ru)
        if DISPEL_RE.fullmatch(t):                      # قبل از CAST: «طلسم شکن» نباید «طلسم + آرگومان» حساب بشه
            return await _dispel_on_user(m, bot, ru)
        if CAST_RE.fullmatch(t):
            return await _curse_cast(m, bot, me, ru, t)
        if BUYOUT_RE.fullmatch(t):
            return await _curse_buyout(m, bot)
        await _maybe_spread(m, bot, me, ru)
        return False
    except Exception:
        log.exception("reply_rpg.handle failed")
        return False


async def _spawn_random(bot: Bot, chat_id: int):
    users = len(_active_users(chat_id))
    kinds, weights = ["ambush", "dungeon"], [75, 25]
    if users >= 4:
        kinds.append("chain")
        weights.append(10)
    kind = random.choices(kinds, weights=weights)[0]
    if kind == "ambush":
        await _spawn_ambush(bot, chat_id)
    elif kind == "dungeon":
        await _dg_start(bot, chat_id)
    else:
        await _spawn_chain(bot, chat_id)


async def on_message(m, bot: Bot):
    """هوکِ هر پیامِ گروه: ثبتِ فعالیت، افکتِ طلسم برای نفرین‌شده‌ها، و شانسِ ظهورِ رویدادِ تصادفی."""
    if not ENABLED or not m.from_user or m.from_user.is_bot or not is_group(m):
        return
    try:
        cid, uid, now = m.chat.id, m.from_user.id, _now()
        _activity[cid].append((now, uid))
        if (cid, uid) in _cursed:
            await _curse_tick(m, bot)
        if random.random() < SPAWN_CHANCE and now - _last_spawn.get(cid, 0) > SPAWN_GAP and len(_active_users(cid)) >= 3:
            _last_spawn[cid] = now
            if not await _wild_active(cid):
                await _spawn_random(bot, cid)
    except Exception:
        log.exception("reply_rpg.on_message failed")


async def recover_rrpg(bot: Bot):
    """استارت: رویدادهای نیمه‌کاره بسته میشن (پولی تو امانت نیست)؛ طلسم‌های فعال دوباره بارگذاری میشن."""
    try:
        await store.rrpg.update_many({"kind": {"$in": ["chain", "ambush", "dungeon", "duel"]}, "status": {"$in": ["active", "open", "wait", "picking", "resolving"]}},
                                     {"$set": {"status": "expired"}})
        now = utcnow()
        await store.rrpg.update_many({"kind": "curse", "status": "active", "expires_at": {"$lte": now}}, {"$set": {"status": "expired"}})
        async for c in store.rrpg.find({"kind": "curse", "status": "active", "expires_at": {"$gt": now}}):
            _cursed[(c["chat_id"], c["target"])] = c["_id"]
            spawn(_curse_timer(bot, c["_id"], max(1, int((c["expires_at"] - now).total_seconds()))))
    except Exception:
        log.exception("recover_rrpg failed")
