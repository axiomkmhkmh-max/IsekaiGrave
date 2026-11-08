"""🏟 میدانِ نبرد — لایه‌ی تلگرام و دیتابیسِ «بازی‌های ریپلایی» (قوانینِ خالص تو clash.py ـه).

چی داره:
• ⚔️ حمله‌ی ژستی (کلش): مهاجم یکی از ۳ ژست رو مخفی می‌زنه، مدافع ۴۵ ثانیه وقت داره دفاعش رو انتخاب کنه؛
  مثلثِ ژست‌ها برتری می‌ده، بعدش نبردِ رشته‌ی سرنوشت تموم می‌کنه. مدافعِ موفق هم پاداش می‌گیره (غارت، XP، RP).
• 🥋 تمرین: همون کلش ولی بدونِ ضرر و غارت (از سطح ۱؛ مخصوص تازه‌کارها و دوستانه).
• 😏 تحقیر: طعنه‌ی بامزه؛ به طرف ۱ ساعت حقِ انتقام (بدونِ محدودیتِ جفت) می‌ده.
• ✊✋✌️ شرط‌بندی: سنگ‌کاغذ‌قیچی با GS؛ پات تو «امانت» می‌مونه و پرداخت‌ها idempotent ـن.
• 🏅 رتبه‌ی نام‌آوری (RP)، 🔥 زنجیره‌ی پیروزی، 📜 نبردنامه و 🔥 انتقامِ یک‌کلیکی تو پنلِ «میدان».
• v3.6 «ذهن‌بازی»: 🩸 حمله‌ی ریسکی، 🎼/🏰 کامبو (سه ژستِ متفاوت)، 🔮 حدسِ تماشاچی‌ها، ⏰ منشنِ ثانیه‌های آخر،
  🆚 رقابت (رقیب/دشمنِ خونی)، 💢 جان‌سخت، 🧠 لقب‌های تسلط، 🔥 روزهای پشت‌سرهم، 🎯 چالش‌های روز + 🎁 صندوق، 🥋 ریمچِ یک‌کلیکی.

امنیت (همه ثابت و سقف‌دار):
• هر برخورد با یک «claim» اتمیک روی وضعیت (wait → resolving → done) حل میشه؛ پس جایزه/تاوان دقیقاً یک‌بار.
• شارژ/کولداونِ مهاجم موقعِ ثبتِ ژست خرج میشه؛ خرابی وسطِ راه فقط برخورد رو منقضی می‌کنه، پولی گم نمیشه.
• GS انتقالی با debit شرطی، سقفِ غارت، کفِ ۵۰ GS برای قربانی و دفترِ تراکنش؛ بقا هیچ‌وقت زیر ۵٪ نمیره.
• شرط‌بندی: امانتِ هر دو طرف با مارکرِ تک‌سندی (sk_pay) کم/پس داده میشه؛ ریکاوریِ استارت دوباره‌پرداختی نداره.
"""

import asyncio
import random
import time
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatType
from bson import ObjectId
from pymongo import ReturnDocument

from battle import _Shim
from battle_engine import MAX_SOUL, pct, run_ai
from clash import (
    ATT, ATT_BASE, DEF, DEF_BASE, FOCUS_COST, FOCUS_MAX, RANK_REWARD,
    RANK_UP_LINES, RPS, SPECIAL_EDGE_SOULS, SPECIAL_HELP, SUPPORT_MARGIN, TAUNTS, TRIANGLE_HELP, apply_edge, attack_rp,
    PRIEST_DEF_HEAL, SBET_DAILY, SBET_MAX, SBET_STAKE, auto_defense, class_edge, clash_result, defend_rp, edict_bonus,
    edict_text, habit_line, rank_index, rank_label, rank_name, rank_progress, repeat_edge, rps_payouts, rps_result,
    run_next, sbet_payouts, streak_banner, streak_break_reward, streak_loot_mult,
    # v3.6
    COMBO_ATT_NAME, COMBO_DEF_NAME, COMBO_RP, COMBO_SOULS, COMEBACK_LOSSES, COMEBACK_SOULS, DAY_STREAK_REWARDS,
    DEF_FLOURISH, GUESS_DAILY, GUESS_MAX, GUESS_RP, RISK_DEF_LOOT_MULT, RISK_DEF_RP, RISK_DMG_MULT, RISK_HELP, RISK_LOOT_MULT,
    RISK_LOSE_RP, RISK_LOSE_SURV, RISK_MIN_SURV, RISK_WIN_RP, RIVAL_RP, STREAK_BREAK_MIN, WIN_FLOURISH, ach_due, chest_roll,
    combo_fresh, combo_need, combo_step, combo_text, rival_banner, rival_level, rival_line, scene_line, trial_text,
    trials_done,
)
from config import GS, IR_OFFSET, log
from database import store
from economy import burn, credit, debit, log_tx
from players import adjust_survival, grant, refresh_titles
from quests import quest_progress
from render import display
from skirmish import (
    CHARGE_SECS, GOLD_FLOOR, MAX_CHARGES, MIN_LEVEL, PAIR_COOLDOWN, REVENGE_SECS, SHIELD_SECS, SURV_FLOOR, LEVEL_GAP,
    _Locks, _claim_bounties, _dur, _eligible, _expire_bounties, _fighter, _loot_amount, _regen,
)
from ui import CbMsg, btn, hp_bar, kb, panel, say, show
from utils import day_key, esc, is_group, spawn, utcnow, week_key
from weekly import add_guild_pts

CLASH_WINDOW = 45                # ثانیه‌ی دفاعِ مدافع
PICK_TTL_MIN = 3                 # عمرِ پنلِ انتخابِ ژست (دقیقه)
STALE_SECS = 15 * 60             # برخوردِ باز/نیمه‌کاره بعد از این مدت منقضی میشه
SPAR_PAIR_COOLDOWN = 45             # ثانیه؛ ریمچِ تمرینی سریع (سقفِ پاداشِ روزانه جلوی فارم رو می‌گیره)
NUDGE_AT = 16                    # ⏰ چند ثانیه مونده به پایانِ دفاع، مدافع منشن میشه
SPAR_DAILY_REWARDS = 5           # تمرین‌هایی که تو روز XP/RP می‌دن
SPAR_XP_WIN, SPAR_XP_LOSE = 8, 5
TAUNT_COOLDOWN, TAUNT_DAILY, TAUNT_REV_SECS = 10 * 60, 6, 3600
DEF_LOOT_CAP, DEF_LOOT_PCT = 15, 0.05     # پاداشِ مدافعِ موفق (از GS مهاجم)
LOOT_CEIL = 90                   # سقفِ مطلقِ غارتِ یک حمله (حتی با زنجیره و بحرانی)
BET_MIN, BET_MAX, BET_DAILY, BET_WINDOW = 10, 200, 600, 90
LOG_KEEP = 12
TRAP_COST, TRAP_SECS, TRAP_DMG, TRAP_LOOT = 15, 3600, 5, 10     # 🪤 تله
SUP_DAILY, SUP_MAX = 10, 12                                       # 🔔 سقفِ RPِ حمایتِ روزانه / حامیِ مؤثر در هر برخورد
FIRST_WIN_XP, FIRST_WIN_RP = 15, 3                                 # 🌅 اولین بردِ روز (حمله یا دفاع)
SEASON_MIN_RP, SEASON_REWARDS, SEASON_TITLE = 15, (150, 90, 50), "🏆 قهرمانِ میدانِ هفته"   # 🏆 جایزه‌ی هفتگیِ ۳ نفرِ اولِ RP
H2H_MAX = 40                                                      # سقفِ تعدادِ حریف‌هایی که سابقه‌شون نگه‌داری میشه

_KIND_CODE = {"attack": "a", "spar": "s"}
_CODE_KIND = {v: k for k, v in _KIND_CODE.items()}
_ATT_SHORT = {"h": "سنگین", "q": "سریع", "f": "فریب", "x": "ویژه ⚡"}
_DEF_SHORT = {"g": "سپر", "e": "جاخالی", "c": "ضدحمله", "v": "ویژه ⚡"}
_ATT_COLOR = {"h": "red", "q": "green", "f": "blue", "x": "red"}
_DEF_COLOR = {"g": "blue", "e": "green", "c": "red", "v": "green"}


def _nm(doc: Optional[dict]) -> str:
    return esc((doc or {}).get("first_name") or "ناشناس")


def _tsmin() -> int:
    return int(time.time() // 60)


def _ago(t: float) -> str:
    s = max(0, int(time.time() - float(t)))
    if s < 90:
        return "همین الان"
    if s < 3600:
        return f"{s // 60} دقیقه پیش"
    if s < 86400:
        return f"{s // 3600} ساعت پیش"
    return f"{s // 86400} روز پیش"


# ───────────────────────────── 🏅 RP و لاگ ─────────────────────────────
async def _add_rp(uid: int, delta: int) -> dict:
    """RP (کلی + هفتگی) رو اتمیک عوض می‌کنه (هیچ‌وقت منفی نمیشه). رتبه‌ی جدید برای بار اول جایزه‌ی GS داره."""
    wk = week_key()
    before = await store.users.find_one_and_update(
        {"user_id": uid},
        [{"$set": {
            "sk_rp": {"$max": [0, {"$add": [{"$ifNull": ["$sk_rp", 0]}, delta]}]},
            "sk_rp_w": {"$cond": [{"$eq": ["$sk_rp_wk", wk]},
                                  {"$max": [0, {"$add": [{"$ifNull": ["$sk_rp_w", 0]}, delta]}]}, {"$max": [0, delta]}]},
            "sk_rp_prev": {"$cond": [{"$eq": ["$sk_rp_wk", wk]}, "$sk_rp_prev",
                                     {"wk": "$sk_rp_wk", "rp": {"$ifNull": ["$sk_rp_w", 0]}}]},   # 📸 اسنپ‌شاتِ هفته‌ی قبل برای جایزه‌ی فصل
            "sk_rp_wk": wk,
        }}],
        return_document=ReturnDocument.BEFORE)
    old = int((before or {}).get("sk_rp", 0))
    new = max(0, old + delta)
    info = {"rp": new, "delta": new - old, "up": None}
    oi, ni = rank_index(old), rank_index(new)
    if before and ni > oi:
        first = await store.users.find_one_and_update(
            {"user_id": uid, "sk_rank_max": {"$not": {"$gte": ni}}}, {"$set": {"sk_rank_max": ni}})
        reward = RANK_REWARD[ni] if first is not None else 0
        if reward:
            await grant(uid, gold=reward)
        info["up"] = (ni, reward)
    return info


def _rankup(name: str, info: dict) -> list:
    if not info.get("up"):
        return []
    ni, reward = info["up"]
    return [f"🎖 <b>{name}</b> به رتبه‌ی {rank_name(ni)} رسید!" + (f" 🪙 +{reward} {GS}" if reward else "")]


async def _first_win(uid: int) -> bool:
    """🌅 اولین بردِ امروز؟ (ادعای اتمیک؛ فقط یک‌بار در روز)"""
    return await store.users.find_one_and_update({"user_id": uid, "sk_fw_day": {"$ne": day_key()}}, {"$set": {"sk_fw_day": day_key()}}) is not None


async def season_payout(old_key: Optional[str], bot: Optional[Bot] = None):
    """🏆 جایزه‌ی هفتگی: ۳ نفرِ اولِ RPِ هفته‌ی قبل (از weekly._weekly_rollover صدا زده میشه؛ علامتِ «پرداخت‌شده» تو meta)."""
    if not old_key:
        return
    meta = await store.meta.find_one({"_id": "arena_season"})
    if meta and meta.get("paid") == old_key:
        return
    await store.meta.update_one({"_id": "arena_season"}, {"$set": {"paid": old_key}}, upsert=True)
    rows = {}
    async for d in store.users.find({"sk_rp_wk": old_key, "sk_rp_w": {"$gt": 0}}):
        rows[d["user_id"]] = (int(d["sk_rp_w"]), d)
    async for d in store.users.find({"sk_rp_prev.wk": old_key, "sk_rp_prev.rp": {"$gt": 0}}):
        rows.setdefault(d["user_id"], (int(d["sk_rp_prev"]["rp"]), d))
    ranked = sorted(((rp, uid) for uid, (rp, d) in rows.items() if rp >= SEASON_MIN_RP and not d.get("opted_out")), reverse=True)[:len(SEASON_REWARDS)]
    for i, (rp, uid) in enumerate(ranked):
        gold = SEASON_REWARDS[i]
        upd = {"$inc": {"gold": gold}}
        if i == 0:
            upd["$addToSet"] = {"titles": SEASON_TITLE}
        await store.users.update_one({"user_id": uid}, upd)
        await log_tx(uid, gold, "arena_season", old_key)
        await _push_log(uid, f"🏆 جایزه‌ی هفته: رتبه‌ی {i + 1} با {rp} RP → +{gold} {GS}")
        if bot is not None:
            try:
                await bot.send_message(uid, panel("yellow", "🏆", "جایزه‌ی هفتگیِ میدان", [
                    f"{['🥇', '🥈', '🥉'][i]} رتبه‌ی {i + 1} با {rp} RP", f"🪙 +{gold} {GS}" + (f" · لقب «{SEASON_TITLE}»" if i == 0 else "")]))
            except Exception as e:
                log.debug("season dm skipped for %s: %s", uid, e)


async def _push_log(uid: int, text: str):
    await store.users.update_one({"user_id": uid}, {"$push": {"sk_log": {"$each": [{"t": int(time.time()), "x": text}], "$slice": -LOG_KEEP}}})


# ───────────────────────────── 🔎 پیش‌شرط‌ها ─────────────────────────────
async def _busy_fight(*uids) -> bool:
    return bool(await store.clashes.count_documents({
        "kind": {"$in": ["attack", "spar"]}, "status": {"$in": ["wait", "resolving"]}, "uids": {"$in": list(uids)},
        "created_at": {"$gt": utcnow() - timedelta(seconds=STALE_SECS)}}))


async def _busy_bet(*uids) -> bool:
    return bool(await store.clashes.count_documents({
        "kind": "rps", "status": {"$in": ["hold", "wait", "matching", "settling"]}, "uids": {"$in": list(uids)},
        "created_at": {"$gt": utcnow() - timedelta(seconds=STALE_SECS)}}))


def _checks(kind: str, adoc: dict, tdoc: dict, now: float) -> tuple:
    """(خطا یا None، انتقام؟، شارژ، مبنای زمانیِ شارژ)."""
    tid = tdoc["user_id"]
    if adoc.get("opted_out"):
        return "خودت «محافظت» رو فعال کردی؛ اول بنویس «برگردم به بازی». 🛡", False, 0, now
    if tdoc.get("opted_out"):
        return f"{display(tdoc)} «محافظت» فعال کرده؛ بهش نمیشه دست زد. 🛡", False, 0, now
    if kind == "spar":
        if tdoc.get("registered") is False or adoc.get("registered") is False:
            return "حریف هنوز ثبت‌نام نکرده. 📜", False, 0, now
        last = float((adoc.get("sk_spar") or {}).get(str(tid), 0))
        if now - last < SPAR_PAIR_COOLDOWN:
            return f"تازه با همین نفر تمرین کردی؛ {_dur(SPAR_PAIR_COOLDOWN - (now - last))} دیگه. ⏳", False, 0, now
        return None, False, 0, now
    for who, d in (("تو", adoc), (None, tdoc)):
        why = _eligible(d)
        if why:
            return (f"{who}: " if who else "") + why, False, 0, now
    revenge = float((adoc.get("sk_rev") or {}).get(str(tid), 0)) > now
    if not revenge and int(tdoc.get("level", 1)) < int(adoc.get("level", 1)) - LEVEL_GAP:
        return "این بازیکن خیلی از تو ضعیف‌تره؛ زورگویی تو ایسکا هم مد نیست. 😒", False, 0, now
    if float(tdoc.get("sk_shield", 0)) > now:
        return f"{display(tdoc)} تازه ضربه خورده و داره نفس می‌گیره؛ {_dur(tdoc['sk_shield'] - now)} دیگه. 🛡", False, 0, now
    last = float((adoc.get("sk_pair") or {}).get(str(tid), 0))
    if not revenge and now - last < PAIR_COOLDOWN:
        return f"به همین نفر تازه حمله کردی؛ {_dur(PAIR_COOLDOWN - (now - last))} دیگه. ⏳", False, 0, now
    charges, base_t = _regen(adoc, now)
    if charges <= 0:
        return f"شارژِ حمله نداری؛ بعدی تا {_dur(base_t + CHARGE_SECS - now)} دیگه. 🔋", False, 0, base_t
    return None, revenge, charges, base_t


def _bet_counts(c: dict) -> tuple:
    bets = c.get("bets") or []
    return sum(1 for b in bets if b["side"] == "a"), sum(1 for b in bets if b["side"] == "d")


def _kb_from(c: dict):
    """کیبوردِ پنلِ دفاع از رویِ سندِ برخورد: دفاع‌ها + 🔔 حمایت + 🎲 شرط + 🔮 حدسِ تماشاچی‌ها (فقط حمله‌ی واقعی)."""
    oid, tid = c["_id"], c["t"]
    codes = list(DEF_BASE) + (["v"] if c.get("dspec") else [])
    rows = [[btn(f"{DEF[x][0]} {_DEF_SHORT[x]}", f"sk:df:{x}:{oid}:{tid}", _DEF_COLOR[x]) for x in codes]]
    if c.get("kind") == "attack":
        sa, sd = len(c.get("sup_a", [])), len(c.get("sup_d", []))
        ba, bd = _bet_counts(c)
        rows.append([btn(f"🔔 مهاجم ({sa})", f"sk:su:a:{oid}:0", "blue"), btn(f"🔔 مدافع ({sd})", f"sk:su:d:{oid}:0", "blue")])
        rows.append([btn(f"🎲 {SBET_STAKE} روی مهاجم ({ba})", f"sk:sb:a:{oid}:0", "red"), btn(f"🎲 {SBET_STAKE} روی مدافع ({bd})", f"sk:sb:d:{oid}:0", "green")])
        rows.append([btn(f"🔮{ATT[x][0]}", f"sk:gs:{x}:{oid}:0", _ATT_COLOR[x]) for x in ATT_BASE]
                    + [btn(f"👁 {len(c.get('guesses', []))}", f"sk:gs:i:{oid}:0", "blue")])
    return kb(*rows)


def _pick_kb(kind: str, aid: int, tid: int, special: bool = False, risky_ok: bool = False):
    ts = _tsmin()
    codes = list(ATT_BASE) + (["x"] if special else [])
    rows = [[btn(f"{ATT[c][0]} {_ATT_SHORT[c]}", f"sk:ap:{_KIND_CODE[kind]}:{c}:{tid}:{ts}:{aid}", _ATT_COLOR[c]) for c in codes]]
    if risky_ok and kind == "attack":      # 🩸 همون ژست‌ها ولی همه‌یا‌هیچ (آخرِ callback: r)
        rows.append([btn(f"🩸{ATT[c][0]} ریسکی", f"sk:ap:a:{c}:{tid}:{ts}:{aid}:r", "red") for c in ATT_BASE])
    return kb(*rows)


def _h2h_rec(doc: dict, opp: int) -> dict:
    return (doc.get("sk_h2h") or {}).get(str(opp)) or {}


def _h2h_line(adoc: dict, tdoc: dict) -> Optional[str]:
    r = _h2h_rec(adoc, tdoc["user_id"])
    if not r:
        return None
    return rival_line(_nm(tdoc), int(r.get("w", 0)), int(r.get("l", 0)))


async def _h2h(uid: int, opp: int, won: bool):
    """سابقه‌ی رودررو از دیدِ uid (برد/باخت)."""
    doc = await store.get(uid) or {}
    h = doc.get("sk_h2h") or {}
    if str(opp) not in h and len(h) >= H2H_MAX:
        return
    await store.users.update_one({"user_id": uid}, {"$inc": {f"sk_h2h.{opp}.{'w' if won else 'l'}": 1}})


async def _add_focus(uid: int, n: int) -> int:
    """⚡ تمرکز (سقف ۳)؛ خروجی = مقدارِ جدید."""
    if n <= 0:
        d = await store.get(uid)
        return int((d or {}).get("sk_focus", 0))
    d = await store.users.find_one_and_update(
        {"user_id": uid},
        [{"$set": {"sk_focus": {"$min": [FOCUS_MAX, {"$add": [{"$ifNull": ["$sk_focus", 0]}, n]}]}}}],
        return_document=ReturnDocument.AFTER)
    return int((d or {}).get("sk_focus", 0))


def _dnum() -> int:
    """شماره‌ی روز (به وقتِ ایران) برای شمارشِ روزهای پشت‌سرهم."""
    return (utcnow() + IR_OFFSET).toordinal()


async def _bump(uid: int, field: str, n: int = 1):
    await store.users.update_one({"user_id": uid}, {"$inc": {field: n}})


async def _award_titles(uid: int, name: str) -> list:
    """🏷 لقب‌های تازه‌رسیده (اتمیک؛ هر لقب فقط یک‌بار)."""
    doc = await store.get(uid)
    out = []
    for t in (ach_due(doc) if doc else []):
        if await store.users.find_one_and_update({"user_id": uid, "titles": {"$ne": t}}, {"$addToSet": {"titles": t}}):
            out.append(f"🏷 لقبِ تازه برای <b>{name}</b>: {t}")
    return out


async def _trial(uid: int, key: str, name: str) -> list:
    """🎯 پیشرفتِ چالش‌های روز؛ وقتی هر سه کامل شد یه صندوقِ متغیر (یک‌بار در روز، اتمیک)."""
    today = day_key()
    d = await store.users.find_one_and_update(
        {"user_id": uid},
        [{"$set": {"sk_dq": {"$cond": [
            {"$eq": [{"$ifNull": ["$sk_dq.day", ""]}, today]},
            {"$mergeObjects": ["$sk_dq", {key: {"$add": [{"$ifNull": [f"$sk_dq.{key}", 0]}, 1]}}]},
            {"day": today, key: 1}]}}}],
        return_document=ReturnDocument.AFTER)
    if not trials_done((d or {}).get("sk_dq"), today):
        return []
    got = await store.users.find_one_and_update({"user_id": uid, "sk_dq.day": today, "sk_dq.done": {"$ne": True}}, {"$set": {"sk_dq.done": True}})
    if not got:
        return []
    cname, gs, foc = chest_roll(random)
    await grant(uid, gold=gs)
    if foc:
        await _add_focus(uid, foc)
    return [f"🎯 چالش‌های روزِ <b>{name}</b> کامل شد! {cname}: 🪙 +{gs} {GS}" + (f" · ⚡ +{foc} تمرکز" if foc else "")]


async def _day_streak(uid: int, name: str) -> list:
    """🔥 روزهای پشت‌سرهمِ حضور تو میدان (فقط اولین برخوردِ روز حساب میشه؛ ادعای اتمیک)."""
    ordn = _dnum()
    before = await store.users.find_one_and_update({"user_id": uid, "sk_ds_ord": {"$ne": ordn}}, {"$set": {"sk_ds_ord": ordn}},
                                                   return_document=ReturnDocument.BEFORE)
    if before is None:
        return []
    n = int(before.get("sk_ds_n", 0)) + 1 if int(before.get("sk_ds_ord", 0) or 0) == ordn - 1 else 1
    await store.users.update_one({"user_id": uid}, {"$set": {"sk_ds_n": n}, "$max": {"sk_ds_best": n}})
    lines = []
    if n >= 2:
        lines.append(f"🔥 <b>{name}</b>: روزِ {n}ُم پشت‌سرهم تو میدان")
    rw = DAY_STREAK_REWARDS.get(n)
    if rw:
        xp, gs, foc = rw
        kw = {k: v for k, v in (("xp", xp), ("gold", gs)) if v}
        if kw:
            await grant(uid, **kw)
        if foc:
            await _add_focus(uid, foc)
        lines.append("🎁 جایزه‌ی وفاداری: " + " · ".join(x for x in (f"⭐ +{xp} XP" if xp else "", f"🪙 +{gs} {GS}" if gs else "", f"⚡ +{foc} تمرکز" if foc else "") if x))
    return lines


async def _lstreak(winner: int, loser: int):
    """💢 شمارنده‌ی باختِ پشت‌سرهم (برای «جان‌سخت»)."""
    await store.users.update_one({"user_id": winner}, {"$set": {"sk_lstreak": 0}})
    await store.users.update_one({"user_id": loser}, {"$inc": {"sk_lstreak": 1}})


# ───────────────────────────── ⚔️ حمله / 🥋 تمرین: پنلِ انتخابِ ژست ─────────────────────────────
async def attack_open(m, adoc: dict, tdoc: dict, kind: str = "attack"):
    """مرحله‌ی ۱: چک‌های سریع + پنلِ انتخابِ ژستِ مهاجم (استیت‌لس؛ شارژ تا انتخاب خرج نمیشه)."""
    aid, tid = adoc["user_id"], tdoc["user_id"]
    now = time.time()
    icon, title = ("⚔️", "حمله") if kind == "attack" else ("🥋", "تمرین")
    err, revenge, charges, _ = _checks(kind, adoc, tdoc, now)
    if err:
        return await say(m, err, icon, title, "orange")
    if await _busy_fight(aid, tid):
        return await say(m, "یکی از شما هنوز تو یه برخوردِ دیگه‌ست؛ چند لحظه صبر کنین. ⏳", icon, title, "blue")
    high = bool(tdoc.get("sk_war")) or revenge
    focus = int(adoc.get("sk_focus", 0))
    special = kind == "attack" and focus >= FOCUS_COST
    lines = [f"{display(adoc, link=True)} ⚔️ {display(tdoc, link=True)}" + ("  🔥 انتقام!" if revenge else ""),
             TRIANGLE_HELP + (f"\n{SPECIAL_HELP}" if special else "")]
    hl = habit_line(tdoc.get("sk_df"), DEF, _nm(tdoc))
    if hl:
        lines.append(hl)
    h2 = _h2h_line(adoc, tdoc) if kind == "attack" else None
    if h2:
        lines.append(h2)
    risky_ok = kind == "attack" and int(adoc.get("survival_rate", 100)) >= RISK_MIN_SURV
    if kind == "attack":
        lines.append(f"🔋 شارژ: {charges}/{MAX_CHARGES} · ⚡ تمرکز: {focus}/{FOCUS_MAX}" + (" — ✨ ژستِ ویژه آماده‌ست!" if special else "")
                     + (" · 💰 غارتِ بیشتر (جنگ/انتقام)" if high else ""))
        lines.append(edict_text(day_key()))
        lines.append(combo_text(adoc.get("sk_cb"), adoc.get("sk_cb_t"), ATT, ATT_BASE, now))
        dtxt = combo_need(tdoc.get("sk_cbd"), tdoc.get("sk_cbd_t"), DEF_BASE, now)
        if dtxt:
            lines.append(f"🏰 {_nm(tdoc)} تو دیوارِ سه‌لایه‌ست؛ دفاعِ بعدی متفاوت = +۱🕯 برای مدافع (حدسِ ژستش با تو!)")
        if int(tdoc.get("sk_streak", 0)) >= STREAK_BREAK_MIN:
            bg, bx = streak_break_reward(int(tdoc.get("sk_streak", 0)))
            lines.append(f"⛓ {_nm(tdoc)} زنجیره‌ی {int(tdoc.get('sk_streak', 0))}تایی داره؛ شکستنش = 🪙 +{bg} {GS} · ⭐ +{bx} XP")
        if int(adoc.get("sk_lstreak", 0)) >= COMEBACK_LOSSES:
            lines.append(f"💢 جان‌سخت فعاله! برخوردِ بعدیت +{COMEBACK_SOULS}🕯 با شروع میشه.")
        if risky_ok:
            lines.append(RISK_HELP)
    else:
        lines.append("🥋 دوستانه: بدونِ ضرر و غارت؛ فقط XP و RP")
    await m.reply(panel("orange" if kind == "attack" else "green", icon, f"{title} — ژستت رو انتخاب کن", lines,
                        "🎯 ژستِ تو مخفی می‌مونه تا حریف دفاعش رو بزنه.\n⏳ این پنل ۳ دقیقه اعتبار داره."),
                  reply_markup=_pick_kb(kind, aid, tid, special, risky_ok))


async def _end_panel(cq, text: str, color: str = "orange", icon: str = "⚔️", title: str = "حمله"):
    try:
        await cq.message.edit_text(panel(color, icon, title, [text]))
    except Exception as e:
        log.debug("arena panel edit failed: %s", e)


async def _commit(cq, bot: Bot, kind: str, st: str, aid: int, tid: int, risky: bool = False):
    """مرحله‌ی ۲: ثبتِ ژست، خرجِ شارژ و ساختِ برخورد؛ پنل برای دفاعِ مدافع تعویض میشه."""
    now = time.time()
    icon, title = ("⚔️", "حمله") if kind == "attack" else ("🥋", "تمرین")
    async with _Locks(aid, tid):
        adoc, tdoc = await store.get(aid), await store.get(tid)
        if not adoc or not tdoc:
            await cq.answer("بازیکن پیدا نشد.", show_alert=True)
            return
        if kind == "attack":
            await _expire_bounties()
        err, revenge, charges, base_t = _checks(kind, adoc, tdoc, now)
        if not err and await _busy_fight(aid, tid):
            err = "یکی از شما هنوز تو یه برخوردِ دیگه‌ست. ⏳"
        if not err and st == "x":
            if kind != "attack":
                err = "ژستِ ویژه فقط تو حمله‌ی واقعیه. ✨"
            elif int(adoc.get("sk_focus", 0)) < FOCUS_COST:
                err = "تمرکزت برای ژستِ ویژه کافی نیست. ⚡"
        if not err and risky:
            if kind != "attack" or st not in ATT_BASE:
                err = "حمله‌ی ریسکی فقط با ژست‌های عادیِ حمله‌ی واقعیه. 🩸"
            elif int(adoc.get("survival_rate", 100)) < RISK_MIN_SURV:
                err = f"برای حمله‌ی ریسکی بقات باید حداقل {RISK_MIN_SURV}٪ باشه. 🩸"
        if err:
            await cq.answer()
            await _end_panel(cq, err, "blue", icon, title)
            return
        upd: dict = {"$inc": {f"sk_st.{st}": 1}}
        if st == "x":
            upd["$inc"]["sk_focus"] = -FOCUS_COST
        cb_prev = combo_fresh(adoc.get("sk_cb"), adoc.get("sk_cb_t"), ATT_BASE, now) if kind == "attack" else []
        cb_new, combo_done = combo_step(adoc.get("sk_cb"), adoc.get("sk_cb_t"), st, ATT_BASE, now) if kind == "attack" else ([], False)
        if kind == "attack":
            upd["$set"] = {"sk_charges": charges - 1, "sk_charge_t": (now if charges >= MAX_CHARGES else base_t), f"sk_pair.{tid}": now}
            if st in ATT_BASE:                      # 🎼 ژستِ ویژه کامبو رو دست نمی‌زنه
                upd["$set"].update({"sk_cb": cb_new, "sk_cb_t": now})
            if revenge:
                upd["$unset"] = {f"sk_rev.{tid}": ""}
        else:
            upd["$set"] = {f"sk_spar.{tid}": now}
        await store.users.update_one({"user_id": aid}, upd)
        res = await store.clashes.insert_one({
            "kind": kind, "chat_id": cq.message.chat.id, "msg_id": cq.message.message_id, "a": aid, "t": tid, "uids": [aid, tid],
            "st": st, "revenge": revenge, "status": "wait", "created_at": utcnow(), "risky": bool(risky), "combo": bool(combo_done),
            "deadline": utcnow() + timedelta(seconds=CLASH_WINDOW)})
    oid = res.inserted_id
    dspecial = kind == "attack" and int(tdoc.get("sk_focus", 0)) >= FOCUS_COST
    lines = [f"⚠️ {display(adoc, link=True)} داره به {display(tdoc, link=True)} " + ("حمله می‌کنه!" if kind == "attack" else "تمرین پیشنهاد می‌ده!"),
             "🤫 ژستِ مهاجم مخفیه؛ حدس بزن و دفاعت رو انتخاب کن:", TRIANGLE_HELP]
    if dspecial:
        lines.append("⚡ تمرکزت پره! ⛓ «دفاعِ ویژه» (۳⚡) هر سه ضربه‌ی عادی رو می‌خونه؛ فقط ✨ ویژه باهاش مساویه.")
    hl = habit_line(adoc.get("sk_st"), ATT, _nm(adoc))
    if hl:
        lines.append(hl)
    if kind == "attack":
        if risky:
            lines.append(f"🩸 <b>حمله‌ی ریسکی!</b> مهاجم همه‌چیز رو روی این ضربه گذاشته؛ اگه بشکنیش +{RISK_DEF_RP} RP و غارتِ ×{RISK_DEF_LOOT_MULT:g} داری.")
        if len(cb_prev) == 2 and cb_prev[0] != cb_prev[1]:
            lines.append(f"🎼 مهاجم تو کامبوئه ({' → '.join(ATT[c][0] for c in cb_prev)} → ؟)؛ ژستِ سومِ متفاوت = +{COMBO_SOULS}🕯 برای مهاجم. جدیه یا بلوف؟ 🤔")
        lines.append(combo_text(tdoc.get("sk_cbd"), tdoc.get("sk_cbd_t"), DEF, DEF_BASE, now, "🏰 دیوارِ سه‌لایه"))
    await store.clashes.update_one({"_id": oid}, {"$set": {"dspec": dspecial}})
    try:
        await cq.message.edit_text(
            panel("red" if kind == "attack" else "green", icon, f"{title} — نوبتِ دفاع", lines,
                  f"⏳ {CLASH_WINDOW} ثانیه وقت داری. جواب ندی، دفاعِ خودکار (کلاس‌محور) اجرا میشه و پاداشِ دفاع رو از دست میدی."),
            reply_markup=_kb_from({"_id": oid, "t": tid, "kind": kind, "dspec": dspecial}))
    except Exception as e:
        log.debug("clash panel edit failed: %s", e)
    await cq.answer("ژستت ثبت شد! حالا نوبتِ دفاعِ حریفه. 🎯")
    spawn(_watch_clash(bot, oid, CLASH_WINDOW + 1))


async def _defend(cq, bot: Bot, code: str, oid, uid: int):
    if code not in DEF:
        await cq.answer()
        return
    if code == "v":          # ⛓ دفاعِ ویژه: اول تمرکز خرج میشه، اگه برخورد دیگه نبود پس داده میشه
        spent = await store.users.update_one({"user_id": uid, "sk_focus": {"$gte": FOCUS_COST}}, {"$inc": {"sk_focus": -FOCUS_COST}})
        if not spent.modified_count:
            await cq.answer("تمرکزت برای دفاعِ ویژه کافی نیست. ⚡", show_alert=True)
            return
    clash = await store.clashes.find_one_and_update(
        {"_id": oid, "status": "wait", "t": uid, "kind": {"$in": ["attack"] if code == "v" else ["attack", "spar"]}},
        {"$set": {"status": "resolving", "dfn": code, "auto": False}}, return_document=ReturnDocument.AFTER)
    if not clash:
        if code == "v":
            await store.users.update_one({"user_id": uid}, {"$inc": {"sk_focus": FOCUS_COST}})
        await cq.answer("این برخورد تموم شده یا مال تو نیست. ⏳")
        return
    await cq.answer(f"{DEF[code][0]} {DEF[code][1]}!")
    await store.users.update_one({"user_id": uid}, {"$inc": {f"sk_df.{code}": 1}})
    if clash.get("kind") == "attack" and code in DEF_BASE:       # 🏰 کامبوی دفاع (سه دفاعِ متفاوت پشت‌سرهم)
        d = await store.get(uid) or {}
        new, done = combo_step(d.get("sk_cbd"), d.get("sk_cbd_t"), code, DEF_BASE, time.time())
        await store.users.update_one({"user_id": uid}, {"$set": {"sk_cbd": new, "sk_cbd_t": time.time()}})
        if done:
            clash["dcombo"] = True
            await store.clashes.update_one({"_id": oid}, {"$set": {"dcombo": True}})
    await _resolve(bot, clash)


async def _support(cq, bot: Bot, side: str, oid, uid: int):
    """🔔 تماشاچی‌ها (غیر از دو طرف) یه رأی می‌دن؛ اختلافِ ≥۲ حامی = +۱ روح؛ حامیانِ برنده +۱ RP (سقفِ روزانه)."""
    if side not in ("a", "d"):
        await cq.answer()
        return
    doc = await store.get(uid)
    if not doc or doc.get("registered") is False:
        await cq.answer("اول ثبت‌نام کن. 🙂", show_alert=True)
        return
    c = await store.clashes.find_one({"_id": oid, "status": "wait", "kind": "attack"})
    if not c:
        await cq.answer("این برخورد تموم شده. ⏳")
        return
    if uid in c.get("uids", []):
        await cq.answer("خودت وسطِ ماجرایی! 😄", show_alert=True)
        return
    c = await store.clashes.find_one_and_update(
        {"_id": oid, "status": "wait", "sup_users": {"$ne": uid}},
        {"$addToSet": {"sup_users": uid, f"sup_{side}": uid}}, return_document=ReturnDocument.AFTER)
    if not c:
        await cq.answer("قبلاً رأی دادی یا برخورد تموم شد. ⏳")
        return
    await cq.answer("🔔 حمایتت ثبت شد!")
    try:
        await cq.message.edit_reply_markup(reply_markup=_kb_from(c))
    except Exception as e:
        log.debug("support markup edit failed: %s", e)


async def _support_rewards(uids: list) -> list:
    got, today = 0, day_key()
    for u in list(uids)[:SUP_MAX]:
        d = await store.get(u)
        if not d:
            continue
        n = int(d.get("sk_sup_n", 0)) if d.get("sk_sup_day") == today else 0
        if n >= SUP_DAILY:
            continue
        await store.users.update_one({"user_id": u}, {"$set": {"sk_sup_day": today, "sk_sup_n": n + 1}})
        await _add_rp(u, 1)
        got += 1
    return [f"🔔 حامیانِ برنده: {got} نفر · +۱ RP"] if got else []


async def _guess(cq, bot: Bot, g: str, oid, uid: int):
    """🔮 تماشاچی‌ها ژستِ مخفیِ مهاجم رو حدس می‌زنن؛ حدسِ درست +۱ RP (سقفِ روزانه) و شمارنده‌ی «غیب‌گو»."""
    if g == "i":
        c = await store.clashes.find_one({"_id": oid})
        await cq.answer(f"🔮 {len((c or {}).get('guesses', []))} نفر حدس زدن. تو هم ژستِ مخفیِ مهاجم رو حدس بزن!")
        return
    if g not in ATT_BASE:
        await cq.answer()
        return
    doc = await store.get(uid)
    if not doc or doc.get("registered") is False:
        await cq.answer("اول ثبت‌نام کن. 🙂", show_alert=True)
        return
    c = await store.clashes.find_one({"_id": oid, "status": "wait", "kind": "attack"})
    if not c:
        await cq.answer("این برخورد تموم شده. ⏳")
        return
    if uid in c.get("uids", []):
        await cq.answer("خودت وسطِ ماجرایی! 😄", show_alert=True)
        return
    c = await store.clashes.find_one_and_update(
        {"_id": oid, "status": "wait", "guesses.u": {"$ne": uid}, f"guesses.{GUESS_MAX - 1}": {"$exists": False}},
        {"$push": {"guesses": {"u": uid, "g": g}}}, return_document=ReturnDocument.AFTER)
    if not c:
        await cq.answer("قبلاً حدس زدی یا ظرفیتِ حدس پر شد. 🔮")
        return
    await cq.answer(f"🔮 حدست ثبت شد: {ATT[g][0]} {_ATT_SHORT[g]}")
    try:
        await cq.message.edit_reply_markup(reply_markup=_kb_from(c))
    except Exception as e:
        log.debug("guess markup edit failed: %s", e)


async def _guess_rewards(c: dict, st: str) -> list:
    gs = list(c.get("guesses") or [])
    if not gs:
        return []
    right = [int(x["u"]) for x in gs if x["g"] == st]
    today, got, names, extra = day_key(), 0, [], []
    for u in right[:GUESS_MAX]:
        d = await store.get(u)
        if not d:
            continue
        n = int(d.get("sk_gs_n", 0)) if d.get("sk_gs_day") == today else 0
        if n >= GUESS_DAILY:
            continue
        await store.users.update_one({"user_id": u}, {"$set": {"sk_gs_day": today, "sk_gs_n": n + 1}, "$inc": {"sk_guess_ok": 1}})
        await _add_rp(u, GUESS_RP)
        got += 1
        if len(names) < 3:
            names.append(_nm(d))
        extra += await _award_titles(u, _nm(d))
    if st == "x":
        return [f"🔮 {len(gs)} نفر حدس زده بودن ولی ژستِ ویژه تو هیچ‌کدوم نبود! ✨"]
    head = f"🔮 حدسِ تماشاچی‌ها: {len(right)} از {len(gs)} نفر درست زدن" + (f" ({'، '.join(names)}) · +{GUESS_RP} RP" if got else "")
    return [head] + extra


async def _sbet(cq, bot: Bot, side: str, oid, uid: int):
    """🎲 شرطِ ثابت (۱۰ GS) روی یکی از دو طرفِ حمله؛ پات بینِ برنده‌ها تقسیم میشه (۵٪ و باقیمانده می‌سوزه)."""
    if side not in ("a", "d"):
        await cq.answer()
        return
    doc = await store.get(uid)
    if not doc or doc.get("registered") is False or int(doc.get("level", 1)) < MIN_LEVEL:
        await cq.answer(f"شرط‌بندی از سطح {MIN_LEVEL} و فقط برای ثبت‌نام‌شده‌هاست. 🐣", show_alert=True)
        return
    c = await store.clashes.find_one({"_id": oid, "status": "wait", "kind": "attack"})
    if not c:
        await cq.answer("این برخورد تموم شده. ⏳")
        return
    if uid in c.get("uids", []):
        await cq.answer("خودت وسطِ ماجرایی! 😄", show_alert=True)
        return
    today = day_key()
    spent = int(doc.get("sk_sbet_amt", 0)) if doc.get("sk_sbet_day") == today else 0
    if spent + SBET_STAKE > SBET_DAILY:
        await cq.answer(f"سقفِ شرطِ تماشاچیِ روزانه {SBET_DAILY} {GS}ه. 🌙", show_alert=True)
        return
    if any(b["u"] == uid for b in c.get("bets", [])):
        await cq.answer("تو قبلاً شرط بستی. 🎲")
        return
    if not await _hold(uid, SBET_STAKE, oid, f"s{uid}"):
        await cq.answer(f"موجودیت برای شرط ({SBET_STAKE} {GS}) کافی نیست. 🪙", show_alert=True)
        return
    c = await store.clashes.find_one_and_update(
        {"_id": oid, "status": "wait", "bets.u": {"$ne": uid}, f"bets.{SBET_MAX - 1}": {"$exists": False}},
        {"$push": {"bets": {"u": uid, "side": side, "amt": SBET_STAKE}}}, return_document=ReturnDocument.AFTER)
    if not c:                                   # برخورد تموم شد/ظرفیت پر شد → امانت برمی‌گرده
        await _refund(uid, SBET_STAKE, oid, f"s{uid}", f"x{uid}")
        await cq.answer("شرط جا نشد (برخورد تموم شد یا ظرفیت پره)؛ پولت برگشت. ⏳")
        return
    await store.users.update_one({"user_id": uid}, {"$set": {"sk_sbet_day": today, "sk_sbet_amt": spent + SBET_STAKE}})
    await cq.answer(f"🎲 {SBET_STAKE} {GS} روی {'مهاجم' if side == 'a' else 'مدافع'} شرط بستی!")
    try:
        await cq.message.edit_reply_markup(reply_markup=_kb_from(c))
    except Exception as e:
        log.debug("sbet markup edit failed: %s", e)


async def _pay_sbets(c: dict):
    """پرداختِ idempotent (مارکرِ تک‌سندی برای هر نفر)؛ ریکاوری هم امن دوباره صداش می‌زنه."""
    oid = c["_id"]
    pays, burned, _mode = sbet_payouts(c.get("bets") or [], c.get("sb_winner"))
    for u, amt in pays:
        await _pay(int(u), int(amt), oid, f"sb{u}", "sbet_win")
    if burned > 0 and await store.clashes.find_one_and_update({"_id": oid, "sb_burned": {"$ne": True}}, {"$set": {"sb_burned": True}}):
        await burn(burned, "sbet_fee")
    await store.clashes.update_one({"_id": oid}, {"$set": {"sb_state": "done"}})


async def _settle_sbets(oid, winner: Optional[str]):
    if await store.clashes.find_one_and_update({"_id": oid, "bets.0": {"$exists": True}, "sb_state": {"$exists": False}},
                                               {"$set": {"sb_state": "paying", "sb_winner": winner}}):
        await _pay_sbets(await store.clashes.find_one({"_id": oid}))


async def _refund_sbets(c: dict):
    """برخوردِ منقضی/خراب: امانتِ همه‌ی شرط‌بندها برمی‌گرده."""
    if await store.clashes.find_one_and_update({"_id": c["_id"], "bets.0": {"$exists": True}, "sb_state": {"$exists": False}},
                                               {"$set": {"sb_state": "refunded"}}):
        for b in c.get("bets") or []:
            await _refund(int(b["u"]), int(b["amt"]), c["_id"], f"s{b['u']}", f"x{b['u']}")


async def do_trap(m):
    """🪤 «تله بذار»: ۱ ساعت؛ اولین مهاجمی که ازت شکست بخوره بقا و GS (سقف‌دار) از دست میده."""
    uid = m.from_user.id
    async with _Locks(uid):
        doc = await store.get(uid)
        if not doc or doc.get("registered") is False:
            return await say(m, "اول ثبت‌نام کن. 📜", "🪤", "تله", "orange")
        if doc.get("opted_out"):
            return await say(m, "تو «محافظت» هستی؛ تله لازم نداری. 🛡", "🪤", "تله", "blue")
        now = time.time()
        if float(doc.get("sk_trap", 0)) > now:
            return await say(m, f"تله‌ات از قبل فعاله ({_dur(doc['sk_trap'] - now)} دیگه). 🪤", "🪤", "تله", "blue")
        if not await debit(uid, TRAP_COST, "sk_trap"):
            return await say(m, f"تله {TRAP_COST} {GS} خرج داره و نداری. 🪙", "🪤", "تله", "orange")
        await store.users.update_one({"user_id": uid}, {"$set": {"sk_trap": now + TRAP_SECS}})
    await m.reply(panel("orange", "🪤", "تله کار گذاشته شد", [
        f"{display(doc, link=True)} یه تله‌ی مخفی ۱ ساعته کار گذاشت.",
        f"اولین مهاجمی که ازت شکست بخوره: −{TRAP_DMG}٪ بقا و حدود −{TRAP_LOOT} {GS} (سقف‌دار) می‌ده.",
        f"🪙 هزینه: {TRAP_COST} {GS}"], "فقط وقتی فعال میشه که تو دفاع پیروز بشی. 😉"))


async def _watch_clash(bot: Bot, oid, delay: float):
    try:
        if delay > NUDGE_AT + 4:             # ⏰ ثانیه‌های آخر: مدافع منشن میشه (فشارِ اجتماعی تو گروه)
            await asyncio.sleep(delay - NUDGE_AT)
            c0 = await store.clashes.find_one_and_update({"_id": oid, "status": "wait", "kind": "attack", "nudged": {"$ne": True}}, {"$set": {"nudged": True}})
            if c0:
                try:
                    td = await store.get(c0["t"])
                    await bot.send_message(c0["chat_id"], f"⏰ {display(td, link=True)} فقط {NUDGE_AT} ثانیه مونده! دفاعت رو بزن وگرنه دفاعِ خودکار اجرا میشه. 🛡")
                except Exception as e:
                    log.debug("clash nudge skipped: %s", e)
            await asyncio.sleep(NUDGE_AT)
        else:
            await asyncio.sleep(delay)
        c = await store.clashes.find_one({"_id": oid, "status": "wait"})
        if not c:
            return
        tdoc = await store.get(c["t"])
        code = auto_defense((tdoc or {}).get("cls"))
        c = await store.clashes.find_one_and_update(
            {"_id": oid, "status": "wait"}, {"$set": {"status": "resolving", "dfn": code, "auto": True}},
            return_document=ReturnDocument.AFTER)
        if c:
            await _resolve(bot, c)
    except Exception:
        log.exception("clash watch failed")


# ───────────────────────────── 🧮 حلِ برخورد ─────────────────────────────
def _loot_amt(tdoc: dict, high: bool, mult: float) -> int:
    g = int(tdoc.get("gold", 0))
    return max(0, min(int(_loot_amount(tdoc, high) * mult), LOOT_CEIL, g - GOLD_FLOOR))


async def _show(bot: Bot, clash: dict, text: str, markup):
    try:
        await bot.edit_message_text(text, chat_id=clash["chat_id"], message_id=clash["msg_id"], reply_markup=markup)
    except Exception as e:
        log.debug("clash result edit failed: %s", e)
        try:
            await bot.send_message(clash["chat_id"], text, reply_markup=markup)
        except Exception:
            log.exception("clash result send failed")


async def _resolve(bot: Bot, clash: dict):
    """فقط کسی صدا می‌زنه که وضعیت رو اتمیک به resolving برده؛ پس هر برخورد دقیقاً یک‌بار حل میشه."""
    oid = clash["_id"]
    try:
        text, markup, after, winner = await _resolve_inner(clash)
    except Exception:
        log.exception("clash resolve failed")
        await store.clashes.update_one({"_id": oid}, {"$set": {"status": "failed", "closed_at": utcnow()}})
        try:
            await _refund_sbets(clash)
        except Exception:
            log.exception("sbet refund failed")
        return
    await store.clashes.update_one({"_id": oid}, {"$set": {"status": "done", "closed_at": utcnow(), "winner": winner}})
    await _show(bot, clash, text, markup)
    try:
        await _settle_sbets(oid, winner)
    except Exception:
        log.exception("sbet settle failed")
    for kind, uid in after:
        try:
            await quest_progress(_Shim(bot, clash["chat_id"], uid), kind, uid=uid)
        except Exception:
            log.exception("clash quest hook failed")
    for uid in clash.get("uids", []):
        try:
            gd = await store.get(uid)
            if gd:
                await refresh_titles(gd)
        except Exception:
            log.exception("clash titles failed")


async def _resolve_inner(clash: dict) -> tuple:
    kind, aid, tid, st, dfn = clash["kind"], clash["a"], clash["t"], clash["st"], clash["dfn"]
    auto = bool(clash.get("auto"))
    revenge = bool(clash.get("revenge"))
    risky = bool(clash.get("risky")) and kind == "attack"
    now = time.time()
    async with _Locks(aid, tid):
        adoc, tdoc = await store.get(aid), await store.get(tid)
        an, dn = _nm(adoc), _nm(tdoc)
        res = clash_result(st, dfn)
        mod_notes = []
        res, note = class_edge(res, adoc.get("cls"), tdoc.get("cls"), st, dfn)      # 🎭 تخصصِ کلاس (فقط تساوی‌ها)
        if note:
            mod_notes.append(note)
        if kind == "attack":                                                       # 🔁 حرکتِ تکراری (فقط تساوی‌ها)
            a_run, a_rep = run_next(adoc.get("sk_run_a"), st)
            d_run, d_rep = run_next(tdoc.get("sk_run_d"), dfn)
            res, note = repeat_edge(res, a_rep, d_rep and not auto)
            if note:
                mod_notes.append(note)
            await store.users.update_one({"user_id": aid}, {"$set": {"sk_run_a": a_run}})
            if not auto:
                await store.users.update_one({"user_id": tid}, {"$set": {"sk_run_d": d_run}})
        crit = res > 0 and not auto
        read = res < 0 and not auto
        fa, fb = await _fighter(adoc), await _fighter(tdoc)
        special = st == "x" or dfn == "v"
        souls = SPECIAL_EDGE_SOULS if special else 2
        first = apply_edge(fa, fb, res, MAX_SOUL, souls)
        sup_a, sup_d = list(clash.get("sup_a", [])), list(clash.get("sup_d", []))
        if len(sup_a) - len(sup_d) >= SUPPORT_MARGIN:          # 🔔 تماشاچی‌ها پشتِ یه طرف وایستادن
            fa["soul"] = min(MAX_SOUL, fa["soul"] + 1)
        elif len(sup_d) - len(sup_a) >= SUPPORT_MARGIN:
            fb["soul"] = min(MAX_SOUL, fb["soul"] + 1)
        a_combo = kind == "attack" and bool(clash.get("combo"))
        d_combo = kind == "attack" and bool(clash.get("dcombo")) and not auto
        if a_combo:                                            # 🎼 کامبوی مهاجم
            fa["soul"] = min(MAX_SOUL, fa["soul"] + COMBO_SOULS)
            mod_notes.append(f"{COMBO_ATT_NAME}! <b>{an}</b> +{COMBO_SOULS}🕯")
        if d_combo:                                            # 🏰 کامبوی مدافع
            fb["soul"] = min(MAX_SOUL, fb["soul"] + COMBO_SOULS)
            mod_notes.append(f"{COMBO_DEF_NAME}! <b>{dn}</b> +{COMBO_SOULS}🕯")
        if kind == "attack":                                   # 💢 جان‌سخت (بعد از ۳ باختِ پشت‌سرهم)
            if int(adoc.get("sk_lstreak", 0)) >= COMEBACK_LOSSES:
                fa["soul"] = min(MAX_SOUL, fa["soul"] + COMEBACK_SOULS)
                mod_notes.append(f"💢 جان‌سخت: <b>{an}</b> +{COMEBACK_SOULS}🕯")
            if int(tdoc.get("sk_lstreak", 0)) >= COMEBACK_LOSSES:
                fb["soul"] = min(MAX_SOUL, fb["soul"] + COMEBACK_SOULS)
                mod_notes.append(f"💢 جان‌سخت: <b>{dn}</b> +{COMEBACK_SOULS}🕯")
        win = run_ai(fa, fb, first=first) == 0
        ai, att_name = ATT[st]
        di, def_name = DEF[dfn]
        if res > 0:
            edge = f"🎯 خوندش! +{souls}🕯 و شروعِ اول" + (" · 💥 ضربه‌ی بحرانی" if crit else " (دفاعِ خودکار: بدونِ بحرانی)")
        elif res < 0:
            edge = f"🧠 {dn} خوندش! +{souls}🕯 برای مدافع و ضربه‌های مهاجم ۱۵٪ ضعیف‌تر"
        else:
            edge = "⚖️ مساوی؛ نبردِ عادی"
        head = [f"{display(adoc, link=True)} ⚔️ {display(tdoc, link=True)}" + ("  🔥 انتقام!" if revenge else "") + ("  🩸 ریسکی!" if risky else ""),
                f"{ai} {an}: {att_name}   ⟷   {di} {dn}: {def_name}" + (" 🤖" if auto else ""),
                scene_line(st, dfn, random).format(a=f"<b>{an}</b>", d=f"<b>{dn}</b>"), edge,
                f"💥 ضربه‌ها: {an} {fa['dealt']} · {dn} {fb['dealt']}" + (" · 🔁 بازتولد" if fa["used_echo"] or fb["used_echo"] else ""),
                "┈┈┈┈┈┈┈┈┈┈"]
        for i, nt in enumerate(mod_notes):
            head.insert(4 + i, nt)
        bets = list(clash.get("bets") or [])
        if bets:
            pays, burned, mode = sbet_payouts(bets, "a" if win else "d")
            head.insert(4 + len(mod_notes), f"🎲 شرطِ تماشاچی‌ها: {len(bets)} نفر · پات {sum(int(b['amt']) for b in bets)} {GS}"
                        + (f" · برنده‌ها +{max(p for _u, p in pays)} {GS}" if mode == "pay" else " · یه طرف خالی بود؛ پول‌ها برگشت"))
        if sup_a or sup_d:
            head.insert(3, f"🔔 حامیان: مهاجم {len(sup_a)} · مدافع {len(sup_d)}" + (" (+۱🕯)" if abs(len(sup_a) - len(sup_d)) >= SUPPORT_MARGIN else ""))
        if kind == "spar":
            return await _spar_effects(clash, adoc, tdoc, win, head)

        arp, drp = int(adoc.get("sk_rp", 0)), int(tdoc.get("sk_rp", 0))
        a_streak0, d_streak0 = int(adoc.get("sk_streak", 0)), int(tdoc.get("sk_streak", 0))
        high = bool(tdoc.get("sk_war")) or revenge
        lines, after, rank_lines = list(head), [("attack", aid)], []
        # 🆚 رقابت: از دیدِ سابقه‌ی قبل از این برخورد (دو طرف یکسانه)
        rec = _h2h_rec(adoc, tid)
        n_before = int(rec.get("w", 0)) + int(rec.get("l", 0))
        riv_lvl, riv_label = rival_level(n_before)
        riv_rp = RIVAL_RP[riv_lvl]
        extra: list = []                                         # خطوطِ تازه (کامبو/ریسک/رقابت/چالش/لقب)
        if win:
            streak = a_streak0 + 1
            mult = streak_loot_mult(streak) * (1.25 if crit else 1.0) * (RISK_LOOT_MULT if risky else 1.0)
            dmg = 5 + int(10 * pct(fa))
            if not high:
                dmg = max(3, dmg // 2)
            if crit:
                dmg = int(dmg * 1.5)
            if risky:
                dmg = int(dmg * RISK_DMG_MULT)
            dmg = min(dmg, max(0, int(tdoc.get("survival_rate", 100)) - SURV_FLOOR))
            if dmg:
                tdoc = await adjust_survival(tid, -dmg, "sk_hits_taken")
            loot, amt = 0, _loot_amt(tdoc, high, mult)
            if amt and await debit(tid, amt, "skirmish_lost", burn_it=False):
                await credit(aid, amt, "skirmish_loot")
                loot = amt
            bounty = await _claim_bounties(tid, aid)
            brk_gs, brk_xp = streak_break_reward(d_streak0)
            if brk_gs:
                await grant(aid, gold=brk_gs, xp=brk_xp)
            await store.users.update_one({"user_id": tid}, {
                "$set": {"sk_shield": now + SHIELD_SECS, f"sk_rev.{aid}": now + REVENGE_SECS, "sk_streak": 0},
                "$inc": {"sk_lost": loot, "sk_def_losses": 1}})
            await store.users.update_one({"user_id": aid}, {
                "$set": {"sk_streak": streak}, "$max": {"sk_best": streak}, "$inc": {"sk_wins": 1, "sk_loot": loot + bounty}})
            await grant(aid, xp=random.randint(10, 20) + (5 if crit else 0))
            ed = edict_bonus(day_key(), True, st, dfn)
            bonus = (RISK_WIN_RP if risky else 0) + (COMBO_RP if a_combo else 0) + riv_rp
            ia = await _add_rp(aid, attack_rp(True, arp, drp, crit, streak) + ed + bonus)
            it = await _add_rp(tid, defend_rp(False, drp, arp))
            await _h2h(aid, tid, True)
            await _h2h(tid, aid, False)
            await _lstreak(aid, tid)
            await add_guild_pts(adoc.get("guild"), 3)
            after.append(("atk_win", aid))
            lines += [f"🏆 <b>{an} پیروز شد!</b>", random.choice(WIN_FLOURISH).format(a=f"<b>{an}</b>"),
                      f"💀 {display(tdoc)} −{dmg}٪ بقا {hp_bar(int(tdoc.get('survival_rate', 0)))}"]
            if loot:
                lines.append(f"🪙 غارت: +{loot} {GS}" + (f" · زنجیره ×{streak_loot_mult(streak):.1f}" if streak > 1 else "")
                             + (" · حالت جنگ/انتقام" if high else "") + (f" · 🩸 ریسکی ×{RISK_LOOT_MULT:g}" if risky else ""))
            if bounty:
                lines.append(f"🎯 جایزه‌ی سر: +{bounty} {GS}")
            if brk_gs:
                lines.append(f"⛓ زنجیره‌ی {d_streak0}تاییِ {dn} رو شکستی! 🪙 +{brk_gs} {GS} · ⭐ +{brk_xp} XP")
            ban = streak_banner(streak)
            lines.append(f"🔥 زنجیره‌ی {an}: <b>{streak}</b>" + (f"  {ban}" if ban else ""))
            lines.append(f"🏅 RP: {an} {ia['delta']:+d} · {dn} {it['delta']:+d}")
            if ed:
                lines.append(f"📜 فرمانِ امروز: +{ed} RP برای {an}")
            if risky:
                extra.append(f"🩸 قمارِ <b>{an}</b> جواب داد! +{RISK_WIN_RP} RP")
                await _bump(aid, "sk_risk_w")
            if a_combo:
                extra.append(f"{COMBO_ATT_NAME}: +{COMBO_RP} RP")
            if riv_rp:
                extra.append(f"{riv_label}: برنده +{riv_rp} RP")
            lines.append(f"🛡 {dn} ۲۰ دقیقه سپر گرفت؛ ولی ۲۴ ساعت حق انتقام داره!")
            rank_lines = _rankup(an, ia) + _rankup(dn, it)
            if await _first_win(aid):
                await grant(aid, xp=FIRST_WIN_XP)
                rank_lines += _rankup(an, await _add_rp(aid, FIRST_WIN_RP))
                lines.append(f"🌅 اولین بردِ امروزِ {an}: +{FIRST_WIN_XP} XP · +{FIRST_WIN_RP} RP")
            extra += await _trial(aid, "a", an)
            await _push_log(tid, f"⚔️ {an} بهت زد: −{dmg}٪ بقا" + (f"، −{loot} {GS}" if loot else "") + (" (بحرانی!)" if crit else "") + (" (ریسکی)" if risky else ""))
            await _push_log(aid, f"🏆 به {dn} حمله کردی و بردی" + (f": +{loot} {GS}" if loot else ""))
            markup = kb([btn("🔥 انتقام", f"sk:rv:{aid}:{tid}", "red"), btn("🥋 ریمچِ تمرینی", f"sk:rm:{aid}:{tid}", "green")],
                        [btn("🏟 میدان", "sk:ar:0", "blue")])
            color = "red"
        else:
            dmg = min(random.randint(3, 8) + (RISK_LOSE_SURV if risky else 0), max(0, int(adoc.get("survival_rate", 100)) - SURV_FLOOR))
            if dmg:
                await adjust_survival(aid, -dmg, "sk_hits_taken")
            streak = d_streak0 + 1
            brk_gs, brk_xp = streak_break_reward(a_streak0)
            if brk_gs:
                await grant(tid, gold=brk_gs, xp=brk_xp)
            dloot = 0
            if not auto:
                g = int(adoc.get("gold", 0))
                amt = max(0, min(int(DEF_LOOT_CAP * (1.5 if read else 1.0) * (RISK_DEF_LOOT_MULT if risky else 1.0)), int(g * DEF_LOOT_PCT), g - GOLD_FLOOR))
                if amt and await debit(aid, amt, "skirmish_def_lost", burn_it=False):
                    await credit(tid, amt, "skirmish_def_loot")
                    dloot = amt
            trap_line = None
            if float(tdoc.get("sk_trap", 0)) > now:           # 🪤 تله‌ی مدافع
                await store.users.update_one({"user_id": tid}, {"$unset": {"sk_trap": ""}})
                a_now = await store.get(aid) or adoc
                tdmg = min(TRAP_DMG, max(0, int(a_now.get("survival_rate", 100)) - SURV_FLOOR))
                if tdmg:
                    await adjust_survival(aid, -tdmg, "sk_hits_taken")
                g2 = int(a_now.get("gold", 0))
                tl = max(0, min(TRAP_LOOT, int(g2 * DEF_LOOT_PCT), g2 - GOLD_FLOOR))
                if tl and await debit(aid, tl, "skirmish_trap_lost", burn_it=False):
                    await credit(tid, tl, "skirmish_trap_loot")
                else:
                    tl = 0
                trap_line = f"🪤 تله‌ی {dn} فعال شد! {an} −{tdmg}٪ بقا" + (f" و −{tl} {GS}" if tl else "")
            await store.users.update_one({"user_id": aid}, {"$set": {"sk_streak": 0}, "$inc": {"sk_losses": 1}})
            await store.users.update_one({"user_id": tid}, {
                "$set": {"sk_streak": streak}, "$max": {"sk_best": streak}, "$inc": {"sk_def_wins": 1, "sk_loot": dloot}})
            await grant(tid, xp=(4 if auto else 8 + (5 if read else 0)))
            ed = edict_bonus(day_key(), False, st, dfn)
            bonus = (RISK_DEF_RP if risky else 0) + (COMBO_RP if d_combo else 0) + riv_rp
            ia = await _add_rp(aid, attack_rp(False, arp, drp) - (RISK_LOSE_RP if risky else 0))
            it = await _add_rp(tid, defend_rp(True, drp, arp, read) + ed + bonus)
            await _h2h(aid, tid, False)
            await _h2h(tid, aid, True)
            await _lstreak(tid, aid)
            await add_guild_pts(tdoc.get("guild"), 2)
            after.append(("defend", tid))
            priest = tdoc.get("cls") == "priest"
            if priest:                                          # ✨ کشیشِ پیروز زخمش رو ترمیم می‌کنه
                await adjust_survival(tid, PRIEST_DEF_HEAL, "blessings_received")
            lines += [f"🛡 <b>{dn} دفاع کرد!</b> حمله‌ی {an} شکست خورد.", random.choice(DEF_FLOURISH).format(d=f"<b>{dn}</b>"),
                      f"🩸 {an} −{dmg}٪ بقا بابت حمله‌ی ناموفق."]
            if priest:
                lines.append(f"✨ کشیش: {dn} +{PRIEST_DEF_HEAL}٪ بقا برگردوند.")
            if dloot:
                lines.append(f"🪙 پاداشِ دفاع: {dn} +{dloot} {GS}" + (" (خوندنِ کاملِ حرکت ×۱٫۵)" if read else "")
                             + (f" · 🩸 ریسکِ مهاجم ×{RISK_DEF_LOOT_MULT:g}" if risky else ""))
            if brk_gs:
                lines.append(f"⛓ زنجیره‌ی {a_streak0}تاییِ {an} شکست! {dn}: 🪙 +{brk_gs} {GS} · ⭐ +{brk_xp} XP")
            if auto:
                lines.append("🤖 دفاعِ خودکار بود؛ پاداشِ کاملِ دفاع ندارد.")
            ban = streak_banner(streak)
            if streak > 1:
                lines.append(f"🔥 زنجیره‌ی {dn}: <b>{streak}</b>" + (f"  {ban}" if ban else ""))
            lines.append(f"🏅 RP: {an} {ia['delta']:+d} · {dn} {it['delta']:+d}")
            if trap_line:
                lines.append(trap_line)
            if ed:
                lines.append(f"📜 فرمانِ امروز: +{ed} RP برای {dn}")
            if risky:
                extra.append(f"🩸 قمارِ <b>{an}</b> باخت: −{RISK_LOSE_SURV}٪ بقای اضافه و −{RISK_LOSE_RP} RP · {dn} +{RISK_DEF_RP} RP")
            if d_combo:
                extra.append(f"{COMBO_DEF_NAME}: +{COMBO_RP} RP")
            if riv_rp:
                extra.append(f"{riv_label}: برنده +{riv_rp} RP")
            rank_lines = _rankup(an, ia) + _rankup(dn, it)
            if await _first_win(tid):
                await grant(tid, xp=FIRST_WIN_XP)
                rank_lines += _rankup(dn, await _add_rp(tid, FIRST_WIN_RP))
                lines.append(f"🌅 اولین بردِ امروزِ {dn}: +{FIRST_WIN_XP} XP · +{FIRST_WIN_RP} RP")
            extra += await _trial(tid, "d", dn)
            await _push_log(aid, f"🛡 {dn} حمله‌ات رو دفع کرد: −{dmg}٪ بقا" + (f"، −{dloot} {GS}" if dloot else ""))
            await _push_log(tid, f"🏆 حمله‌ی {an} رو دفع کردی" + (f": +{dloot} {GS}" if dloot else ""))
            markup = kb([btn("🥋 ریمچِ تمرینی", f"sk:rm:{aid}:{tid}", "green"), btn("🏟 میدان", "sk:ar:0", "blue")])
            color = "blue"
        # ── 🧠 خوندنِ حرکت، 🎼 کامبو، 🆚 رقابت، 🔥 روزهای پشت‌سرهم، 🏷 لقب‌ها
        if res > 0 and not auto:
            await _bump(aid, "sk_reads")
            extra += await _trial(aid, "r", an)
        elif res < 0 and not auto:
            await _bump(tid, "sk_reads")
            extra += await _trial(tid, "r", dn)
        if a_combo:
            await _bump(aid, "sk_combos")
        if d_combo:
            await _bump(tid, "sk_combos")
        n_after = n_before + 1
        rb = rival_banner(an, dn, n_after)
        if rb:
            extra.append(rb)
        if n_after >= 10:
            await store.users.update_many({"user_id": {"$in": [aid, tid]}}, {"$max": {"sk_riv10": 1}})
        extra += await _day_streak(aid, an) + await _day_streak(tid, dn)
        extra += await _award_titles(aid, an) + await _award_titles(tid, dn)
        a_f = (1 if res < 0 else 0) + (0 if win else 1)            # ⚡ بازنده و «خونده‌شده» تمرکز جمع می‌کنن
        d_f = (1 if res > 0 else 0) + (1 if win else 0)
        fa_n, fd_n = await _add_focus(aid, a_f), await _add_focus(tid, d_f)
        lines.append(f"⚡ تمرکز: {an} {fa_n}/{FOCUS_MAX} · {dn} {fd_n}/{FOCUS_MAX}" + ("  ← ژستِ ویژه آماده!" if FOCUS_COST <= max(fa_n, fd_n) else ""))
        lines += extra
        lines += await _guess_rewards(clash, st)
        lines += await _support_rewards(sup_a if win else sup_d)
        if rank_lines:
            lines += rank_lines + [random.choice(RANK_UP_LINES)]
        lines.append(f"🔋 شارژ حمله‌ی {an}: {max(0, _regen(await store.get(aid), now)[0])}/{MAX_CHARGES}")
        return panel(color, "⚔️", "حمله!" if win else "دفاعِ موفق", lines), markup, after, ("a" if win else "d")


async def _spar_effects(clash: dict, adoc: dict, tdoc: dict, win: bool, head: list) -> tuple:
    aid, tid = adoc["user_id"], tdoc["user_id"]
    today = day_key()
    an, dn = _nm(adoc), _nm(tdoc)
    lines, after = list(head), [("spar", aid), ("spar", tid)]
    winner, loser = (adoc, tdoc) if win else (tdoc, adoc)
    lines.append(f"🏆 <b>{_nm(winner)}</b> تمرین رو برد! (دوستانه؛ هیچ ضرری نداره)")
    for d, is_win in ((winner, True), (loser, False)):
        n = int(d.get("sk_spar_n", 0)) if d.get("sk_spar_day") == today else 0
        if n < SPAR_DAILY_REWARDS:
            await store.users.update_one({"user_id": d["user_id"]}, {"$set": {"sk_spar_day": today, "sk_spar_n": n + 1}})
            await grant(d["user_id"], xp=SPAR_XP_WIN if is_win else SPAR_XP_LOSE)
            if is_win:
                info = await _add_rp(d["user_id"], 1)
                lines.append(f"⭐ {_nm(d)}: +{SPAR_XP_WIN} XP · 🏅 +1 RP")
                lines += _rankup(_nm(d), info)
            else:
                lines.append(f"⭐ {_nm(d)}: +{SPAR_XP_LOSE} XP")
        else:
            lines.append(f"😴 {_nm(d)}: سقفِ پاداشِ تمرینِ امروز پر شده ({SPAR_DAILY_REWARDS} بار)")
    await _push_log(aid, f"🥋 با {dn} تمرین کردی: " + ("بردی" if win else "باختی"))
    await _push_log(tid, f"🥋 با {an} تمرین کردی: " + ("باختی" if win else "بردی"))
    return panel("green", "🥋", "تمرین تموم شد", lines), kb([btn("🔁 ریمچ", f"sk:rm:{aid}:{tid}", "green"), btn("🏟 میدان", "sk:ar:0", "blue")]), after, None


# ───────────────────────────── 😏 تحقیر ─────────────────────────────
async def do_taunt(m, adoc: dict, tdoc: dict):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    now, today = time.time(), day_key()
    if tdoc.get("opted_out"):
        return await say(m, f"{display(tdoc)} «محافظت» فعال کرده؛ طعنه‌ات به دیوار خورد. 🛡", "😏", "تحقیر", "blue")
    if adoc.get("opted_out"):
        return await say(m, "خودت «محافظت» رو فعال کردی؛ اول بنویس «برگردم به بازی». 🛡", "😏", "تحقیر", "blue")
    if tdoc.get("registered") is False:
        return await say(m, "این بازیکن هنوز ثبت‌نام نکرده. 📜", "😏", "تحقیر", "orange")
    async with _Locks(aid):
        adoc = await store.get(aid)
        if now - float(adoc.get("sk_taunt_t", 0)) < TAUNT_COOLDOWN:
            return await say(m, f"زبونت هنوز داغه؛ {_dur(TAUNT_COOLDOWN - (now - adoc['sk_taunt_t']))} دیگه. 😏", "😏", "تحقیر", "blue")
        n = int(adoc.get("sk_taunt_n", 0)) if adoc.get("sk_taunt_day") == today else 0
        if n >= TAUNT_DAILY:
            return await say(m, f"امروز {TAUNT_DAILY} بار طعنه زدی؛ بقیه هم نفس بکشن. 🌙", "😏", "تحقیر", "blue")
        await store.users.update_one({"user_id": aid}, {"$set": {"sk_taunt_t": now, "sk_taunt_day": today, "sk_taunt_n": n + 1}})
    await store.users.update_one({"user_id": tid}, {"$max": {f"sk_rev.{aid}": now + TAUNT_REV_SECS}})
    await _push_log(tid, f"😏 {_nm(adoc)} تحقیرت کرد؛ ۱ ساعت حقِ انتقام داری")
    line = random.choice(TAUNTS).format(a=f"<b>{_nm(adoc)}</b>", d=display(tdoc, link=True))
    await m.reply(panel("orange", "😏", "تحقیر!", [line, f"🔥 {display(tdoc)} یه ساعت حقِ انتقام داره (بدونِ محدودیتِ سطح و کولداونِ جفت و با غارتِ بیشتر)."]),
                  reply_markup=kb([btn("🔥 انتقام", f"sk:rv:{aid}:{tid}", "red")]))


# ───────────────────────────── ✊✋✌️ شرط‌بندی ─────────────────────────────
_PAY_ALL = ("hold", "wait", "matching", "settling", "expiring")


async def _hold(uid: int, amount: int, cid, tag: str) -> bool:
    """امانتِ اتمیک و idempotent (مارکرِ تک‌سندی)."""
    res = await store.users.update_one(
        {"user_id": uid, "gold": {"$gte": amount}, "sk_pay": {"$ne": f"{cid}:{tag}"}},
        {"$inc": {"gold": -amount}, "$push": {"sk_pay": {"$each": [f"{cid}:{tag}"], "$slice": -40}}})
    if res.modified_count:
        await log_tx(uid, -amount, "rps_stake", str(cid))
        return True
    return False


async def _pay(uid: int, amount: int, cid, tag: str, reason: str) -> bool:
    if amount <= 0:
        return False
    res = await store.users.update_one(
        {"user_id": uid, "sk_pay": {"$ne": f"{cid}:{tag}"}},
        {"$inc": {"gold": amount}, "$push": {"sk_pay": {"$each": [f"{cid}:{tag}"], "$slice": -40}}})
    if res.modified_count:
        await log_tx(uid, amount, reason, str(cid))
        return True
    return False


async def _refund(uid: int, amount: int, cid, hold_tag: str, ref_tag: str) -> bool:
    """فقط اگه امانت واقعاً گرفته شده و هنوز پس داده نشده."""
    res = await store.users.update_one(
        {"user_id": uid, "sk_pay": {"$all": [f"{cid}:{hold_tag}"], "$ne": f"{cid}:{ref_tag}"}},
        {"$inc": {"gold": amount}, "$push": {"sk_pay": {"$each": [f"{cid}:{ref_tag}"], "$slice": -40}}})
    if res.modified_count:
        await log_tx(uid, amount, "rps_refund", str(cid))
        return True
    return False


def _bet_checks(adoc: dict, tdoc: dict, amount: int) -> Optional[str]:
    if not BET_MIN <= amount <= BET_MAX:
        return f"مبلغِ شرط بین {BET_MIN} تا {BET_MAX} {GS} باشه. 🎲"
    if adoc.get("opted_out") or tdoc.get("opted_out"):
        return "یکی از شما «محافظت» فعال کرده؛ شرط‌بندی نمیشه. 🛡"
    for d in (adoc, tdoc):
        if int(d.get("level", 1)) < MIN_LEVEL or d.get("registered") is False:
            return f"شرط‌بندی از سطح {MIN_LEVEL} و فقط بینِ ثبت‌نام‌شده‌هاست. 🐣"
    return None


def _bet_today(doc: dict) -> int:
    return int(doc.get("sk_bet_amt", 0)) if doc.get("sk_bet_day") == day_key() else 0


async def _bump_bet(uid: int, amount: int):
    today = day_key()
    doc = await store.get(uid)
    n = _bet_today(doc or {})
    await store.users.update_one({"user_id": uid}, {"$set": {"sk_bet_day": today, "sk_bet_amt": n + amount}})


async def bet_open(m, adoc: dict, tdoc: dict, amount: int):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    err = _bet_checks(adoc, tdoc, amount)
    if not err and _bet_today(adoc) + amount > BET_DAILY:
        err = f"سقفِ شرط‌بندیِ روزانه {BET_DAILY} {GS}ه (امروز {_bet_today(adoc)} شرط بستی). 🌙"
    if not err and int(adoc.get("gold", 0)) < amount:
        err = "موجودیت برای این شرط کافی نیست. 🪙"
    if not err and await _busy_bet(aid, tid):
        err = "یکی از شما تو یه شرطِ بازه؛ صبر کنین. ⏳"
    if err:
        return await say(m, err, "🎲", "شرط‌بندی", "orange")
    ts = _tsmin()
    row = [btn(f"{RPS[x][0]} {RPS[x][1]}", f"sk:rp:{x}:{tid}:{amount}:{ts}:{aid}", "blue") for x in RPS]
    await m.reply(panel("yellow", "🎲", "شرط‌بندی: سنگ‌کاغذ‌قیچی", [
        f"{display(adoc, link=True)} 🆚 {display(tdoc, link=True)}",
        f"🪙 هر کدوم {amount} {GS} · برنده {amount * 2 - max(1, amount * 2 * 5 // 100)} {GS} می‌بره (۵٪ کارمزدِ سوخته)",
        "⚖️ مساوی = پول‌ها برمی‌گرده."], "✊ حرکتت رو انتخاب کن؛ مخفی می‌مونه. (۳ دقیقه اعتبار)"), reply_markup=kb(row))


async def _bet_commit(cq, bot: Bot, x: str, aid: int, tid: int, amount: int):
    async with _Locks(aid):
        adoc, tdoc = await store.get(aid), await store.get(tid)
        err = _bet_checks(adoc, tdoc, amount) if adoc and tdoc else "بازیکن پیدا نشد."
        if not err and _bet_today(adoc) + amount > BET_DAILY:
            err = f"سقفِ شرط‌بندیِ روزانه {BET_DAILY} {GS}ه. 🌙"
        if not err and await _busy_bet(aid, tid):
            err = "یکی از شما تو یه شرطِ بازه. ⏳"
        if err:
            await cq.answer()
            await _end_panel(cq, err, "blue", "🎲", "شرط‌بندی")
            return
        oid = ObjectId()
        await store.clashes.insert_one({
            "_id": oid, "kind": "rps", "chat_id": cq.message.chat.id, "msg_id": cq.message.message_id, "a": aid, "t": tid,
            "uids": [aid, tid], "amount": amount, "pick_a": x, "status": "hold", "created_at": utcnow(),
            "deadline": utcnow() + timedelta(seconds=BET_WINDOW)})
        if not await _hold(aid, amount, oid, "ha"):
            await store.clashes.update_one({"_id": oid}, {"$set": {"status": "void"}})
            await cq.answer()
            await _end_panel(cq, "موجودیت برای این شرط کافی نیست. 🪙", "orange", "🎲", "شرط‌بندی")
            return
        await store.clashes.update_one({"_id": oid, "status": "hold"}, {"$set": {"status": "wait"}})
        await _bump_bet(aid, amount)
    row = [btn(f"{RPS[c][0]} {RPS[c][1]}", f"sk:rr:{c}:{oid}:{tid}", "blue") for c in RPS]
    try:
        await cq.message.edit_text(panel("yellow", "🎲", "چالشِ شرط‌بندی!", [
            f"{display(adoc, link=True)} روی {amount} {GS} با {display(tdoc, link=True)} شرط بست!",
            "حرکتش مخفیه؛ حرکتت رو بزن تا شرط قبول بشه (هر دو امانتِ مساوی می‌ذارین)."],
            f"⏳ {BET_WINDOW} ثانیه وقت داری؛ وگرنه شرط لغو و پولِ حریف برمی‌گرده."),
            reply_markup=kb(row, [btn("❌ رد می‌کنم", f"sk:rn:{oid}:{tid}", "red")]))
    except Exception as e:
        log.debug("bet panel edit failed: %s", e)
    await cq.answer("حرکتت ثبت شد و امانت گرفته شد. 🎲")
    spawn(_watch_bet(bot, oid, BET_WINDOW + 1))


async def _bet_edit(bot: Bot, c: dict, text: str, markup=None):
    await _show(bot, c, text, markup)


async def _refund_all(c: dict, why: str):
    cid, amt = c["_id"], int(c["amount"])
    await _refund(c["a"], amt, cid, "ha", "xa")
    await _refund(c["t"], amt, cid, "ht", "xt")
    await store.clashes.update_one({"_id": cid}, {"$set": {"status": why, "closed_at": utcnow()}})


async def _watch_bet(bot: Bot, oid, delay: float):
    try:
        await asyncio.sleep(delay)
        c = await store.clashes.find_one_and_update({"_id": oid, "kind": "rps", "status": "wait"}, {"$set": {"status": "expiring"}},
                                                    return_document=ReturnDocument.AFTER)
        if c:
            await _refund_all(c, "expired")
            await _bet_edit(bot, c, panel("blue", "⌛", "شرط منقضی شد", ["حریف جواب نداد؛ پولِ امانت برگشت."]))
    except Exception:
        log.exception("bet watch failed")


async def _bet_decline(cq, bot: Bot, oid, uid: int):
    c = await store.clashes.find_one_and_update({"_id": oid, "kind": "rps", "status": "wait", "t": uid}, {"$set": {"status": "expiring"}},
                                                return_document=ReturnDocument.AFTER)
    if not c:
        await cq.answer("این شرط تموم شده یا مال تو نیست. ⏳")
        return
    await _refund_all(c, "declined")
    await cq.answer("شرط رد شد.")
    await _bet_edit(bot, c, panel("blue", "🚫", "شرط رد شد", ["حریف قبول نکرد؛ پولِ امانت برگشت."]))


async def _bet_answer(cq, bot: Bot, x: str, oid, uid: int):
    if x not in RPS:
        await cq.answer()
        return
    c = await store.clashes.find_one_and_update(
        {"_id": oid, "kind": "rps", "status": "wait", "t": uid, "deadline": {"$gt": utcnow()}},
        {"$set": {"status": "matching", "pick_t": x}}, return_document=ReturnDocument.AFTER)
    if not c:
        await cq.answer("این شرط تموم شده یا مال تو نیست. ⏳")
        return
    aid, tid, amt = c["a"], c["t"], int(c["amount"])
    tdoc = await store.get(tid)
    err = None
    if not tdoc or int(tdoc.get("level", 1)) < MIN_LEVEL or tdoc.get("opted_out"):
        err = "نمی‌تونی وارد این شرط بشی."
    elif _bet_today(tdoc) + amt > BET_DAILY:
        err = f"سقفِ شرط‌بندیِ روزانه {BET_DAILY} {GS}ه."
    elif not await _hold(tid, amt, oid, "ht"):
        err = "موجودیت کافی نیست. 🪙"
    if err:
        await store.clashes.update_one({"_id": oid, "status": "matching"}, {"$set": {"status": "wait"}, "$unset": {"pick_t": ""}})
        left = (c["deadline"] - utcnow()).total_seconds()
        if left > 1:
            spawn(_watch_bet(bot, oid, left + 1))
        await cq.answer(err, show_alert=True)
        return
    await _bump_bet(tid, amt)
    res = rps_result(c["pick_a"], x)
    win_amt, fee = rps_payouts(amt, res)
    if res == 0:
        pays = [[aid, amt, "ra"], [tid, amt, "rt"]]
    else:
        pays = [[aid if res > 0 else tid, win_amt, "w"]]
    await store.clashes.update_one({"_id": oid, "status": "matching"}, {"$set": {"status": "settling", "payouts": pays, "fee": fee, "res": res}})
    await cq.answer(f"{RPS[x][0]} {RPS[x][1]}!")
    await _settle(bot, oid)


async def _settle(bot: Optional[Bot], oid):
    """پرداختِ idempotent: هر پرداخت با مارکرِ تک‌سندی؛ ریکاوری هم می‌تونه امن دوباره صداش بزنه."""
    c = await store.clashes.find_one({"_id": oid, "kind": "rps", "status": "settling"})
    if not c:
        return
    for uid, amt, tag in c.get("payouts", []):
        await _pay(int(uid), int(amt), oid, tag, "rps_win" if tag == "w" else "rps_refund")
    if int(c.get("fee", 0)) > 0 and await store.clashes.find_one_and_update({"_id": oid, "fee_burned": {"$ne": True}}, {"$set": {"fee_burned": True}}):
        await burn(int(c["fee"]), "rps_fee")
    done = await store.clashes.find_one_and_update({"_id": oid, "status": "settling"}, {"$set": {"status": "done", "closed_at": utcnow()}},
                                                   return_document=ReturnDocument.AFTER)
    if not done or bot is None:
        return
    adoc, tdoc = await store.get(c["a"]), await store.get(c["t"])
    ai, an = RPS[c["pick_a"]][0], _nm(adoc)
    ti, tn = RPS[c["pick_t"]][0], _nm(tdoc)
    amt, res = int(c["amount"]), int(c["res"])
    lines = [f"{ai} {an}  🆚  {ti} {tn}"]
    if res == 0:
        lines.append("⚖️ مساوی! پولِ هر دو برگشت.")
    else:
        w = adoc if res > 0 else tdoc
        lines.append(f"🏆 <b>{_nm(w)}</b> برد! 🪙 +{int(c['payouts'][0][1])} {GS} (کارمزدِ سوخته: {int(c['fee'])})")
    await _show(bot, c, panel("yellow", "🎲", "نتیجه‌ی شرط‌بندی", lines), kb([btn("🏟 میدان", "sk:ar:0", "blue")]))


async def _recover_bets(bot: Bot):
    async for c in store.clashes.find({"kind": "rps", "status": {"$in": list(_PAY_ALL)}}):
        try:
            if c["status"] == "settling":
                await _settle(bot, c["_id"])
            elif c["status"] == "wait" and (c["deadline"] - utcnow()).total_seconds() > 1:
                spawn(_watch_bet(bot, c["_id"], (c["deadline"] - utcnow()).total_seconds() + 1))
            else:
                await _refund_all(c, "expired")
        except Exception:
            log.exception("bet recovery failed")


async def recover_arena(bot: Bot):
    """بعد از ری‌استارت: برخوردهای در انتظار ادامه پیدا می‌کنن، نیمه‌کاره‌ها منقضی و شرط‌ها پس داده/پرداخت میشن."""
    try:
        now = utcnow()
        async for c in store.clashes.find({"kind": {"$in": ["attack", "spar"]}, "status": {"$in": ["wait", "resolving"]}}):
            if c["status"] == "resolving" or (now - c["created_at"]).total_seconds() > STALE_SECS:
                await store.clashes.update_one({"_id": c["_id"], "status": c["status"]}, {"$set": {"status": "expired", "closed_at": now}})
                await _refund_sbets(c)
                continue
            spawn(_watch_clash(bot, c["_id"], max(1.0, (c["deadline"] - now).total_seconds())))
        async for c in store.clashes.find({"kind": "attack", "bets.0": {"$exists": True}, "$or": [
                {"status": {"$in": ["failed", "expired"]}, "sb_state": {"$exists": False}},
                {"status": "done", "sb_state": {"$exists": False}}, {"sb_state": "paying"}]}):
            if c.get("sb_state") == "paying":
                await _pay_sbets(c)
            elif c["status"] == "done":
                await _settle_sbets(c["_id"], c.get("winner"))
            else:
                await _refund_sbets(c)
        await _recover_bets(bot)
    except Exception:
        log.exception("recover_arena failed")


# ───────────────────────────── 🏟 پنلِ میدان و برترین‌ها ─────────────────────────────
async def do_arena(m):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc or doc.get("registered") is False:
        return await say(m, "اول ثبت‌نام کن تا وارد میدان بشی. 📜", "🏟", "میدان", "orange")
    await _expire_bounties()
    now = time.time()
    rp, streak = int(doc.get("sk_rp", 0)), int(doc.get("sk_streak", 0))
    ch, base_t = _regen(doc, now)
    wk = int(doc.get("sk_rp_w", 0)) if doc.get("sk_rp_wk") == week_key() else 0
    bounty = 0
    async for b in store.bounties.find({"target": uid, "status": "open"}):
        bounty += int(b["amount"])
    lines = [f"{display(doc, link=True)} — {rank_label(rp)}", rank_progress(rp),
             f"🔥 زنجیره: <b>{streak}</b> · رکورد {int(doc.get('sk_best', 0))} · 🏅 این هفته {wk} RP",
             f"🔋 شارژ حمله: {ch}/{MAX_CHARGES}" + (f" · بعدی {_dur(base_t + CHARGE_SECS - now)} دیگه" if ch < MAX_CHARGES else ""),
             f"⚔️ حمله: {int(doc.get('sk_wins', 0))} برد · {int(doc.get('sk_losses', 0))} باخت   🛡 دفاع: {int(doc.get('sk_def_wins', 0))} برد · {int(doc.get('sk_def_losses', 0))} باخت",
             f"🪙 غارتِ کل: {int(doc.get('sk_loot', 0))} {GS}"]
    flags = []
    if doc.get("sk_war"):
        flags.append("🔥 حالت جنگ")
    if float(doc.get("sk_shield", 0)) > now:
        flags.append(f"🛡 سپر ({_dur(doc['sk_shield'] - now)})")
    if bounty:
        flags.append(f"🎯 جایزه روی سرت: {bounty} {GS}")
    foc = int(doc.get("sk_focus", 0))
    lines.append(f"⚡ تمرکز: {foc}/{FOCUS_MAX}" + (" — ✨/⛓ ژستِ ویژه آماده!" if foc >= FOCUS_COST else ""))
    lines.append(edict_text(day_key()))
    lines.append(trial_text(doc.get("sk_dq"), day_key()))
    ds = int(doc.get("sk_ds_n", 0))
    if ds >= 1 and int(doc.get("sk_ds_ord", 0) or 0) >= _dnum() - 1:
        lines.append(f"🔥 روزِ {ds}ُم پشت‌سرهم تو میدان (رکورد {int(doc.get('sk_ds_best', 0))})")
    lines.append(combo_text(doc.get("sk_cb"), doc.get("sk_cb_t"), ATT, ATT_BASE, now))
    lines.append(combo_text(doc.get("sk_cbd"), doc.get("sk_cbd_t"), DEF, DEF_BASE, now, "🏰 دیوارِ سه‌لایه"))
    lines.append(f"🧠 خوندنِ حریف: {int(doc.get('sk_reads', 0))} · 🔮 حدسِ درست: {int(doc.get('sk_guess_ok', 0))} · 🎼 کامبو: {int(doc.get('sk_combos', 0))}")
    h2h = doc.get("sk_h2h") or {}
    if h2h:                                                       # 🆚 رقیبِ اصلی: بیشترین برخورد
        k, rec = max(h2h.items(), key=lambda kv: int(kv[1].get("w", 0)) + int(kv[1].get("l", 0)))
        rd = await store.get(int(k))
        rl = rival_line(_nm(rd), int(rec.get("w", 0)), int(rec.get("l", 0))) if rd else None
        if rl:
            lines.append(rl.replace("سابقه با", "رقیبِ اصلی:", 1))
    if int(doc.get("sk_lstreak", 0)) >= COMEBACK_LOSSES:
        lines.append(f"💢 جان‌سخت فعاله: برخوردِ بعدی +{COMEBACK_SOULS}🕯")
    if float(doc.get("sk_trap", 0)) > now:
        flags.append(f"🪤 تله ({_dur(doc['sk_trap'] - now)})")
    if flags:
        lines.append(" · ".join(flags))
    rev = sorted(((float(e), k) for k, e in (doc.get("sk_rev") or {}).items() if float(e) > now))[:3]
    rows = []
    if rev:
        lines += ["┈┈┈┈┈┈┈┈┈┈", "🔥 <b>حقِ انتقام</b>:"]
        for exp, k in rev:
            td = await store.get(int(k))
            if td:
                lines.append(f"• {display(td)} — {_dur(exp - now)} دیگه")
                if is_group(m):
                    rows.append([btn(f"🔥 انتقام از {(td.get('first_name') or '؟')[:14]}", f"sk:rv:{k}:{uid}", "red")])
    logs = (doc.get("sk_log") or [])[-4:]
    if logs:
        lines += ["┈┈┈┈┈┈┈┈┈┈", "📜 <b>نبردنامه</b>:"] + [f"• {_ago(e['t'])}: {e['x']}" for e in reversed(logs)]
    await show(m, panel("red", "🏟", "میدانِ نبرد", lines,
                        "⚔️ ریپلای + «حمله» (🩸 ریسکی هم داره) · 🥋 «تمرین» · 😏 «تحقیرش کن» · 🎲 «شرط ۵۰» · 🔮 تو حمله‌ی بقیه حدس بزن"),
               kb(*rows, [btn("🏆 برترین‌ها", f"sk:lb:{uid}", "green"), btn("🔄 تازه‌سازی", f"sk:ar:{uid}", "blue")],
                  [btn("🌙 منو", f"m:main:{uid}", "blue")]))


async def do_arena_board(m):
    uid = m.from_user.id
    base = {"opted_out": {"$ne": True}}
    weekly = await store.users.find({**base, "sk_rp_wk": week_key(), "sk_rp_w": {"$gt": 0}}).sort("sk_rp_w", -1).limit(5).to_list(5)
    allt = await store.users.find({**base, "sk_rp": {"$gt": 0}}).sort("sk_rp", -1).limit(5).to_list(5)
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    lines = ["📅 <b>این هفته</b>"] + ([f"{medals[i]} {display(d)} — {int(d['sk_rp_w'])} RP" for i, d in enumerate(weekly)] or ["هنوز کسی امتیاز نگرفته. 🕊"])
    lines += ["┈┈┈┈┈┈┈┈┈┈", "👑 <b>همیشه</b>"] + ([f"{medals[i]} {display(d)} — {rank_label(int(d['sk_rp']))} · {int(d['sk_rp'])} RP" for i, d in enumerate(allt)] or ["—"])
    await show(m, panel("yellow", "🏆", "برترین‌های میدان", lines, f"🏆 جایزه‌ی هفته: {SEASON_REWARDS[0]}/{SEASON_REWARDS[1]}/{SEASON_REWARDS[2]} {GS} برای ۳ نفرِ اولِ RP (حداقل {SEASON_MIN_RP} RP) + لقبِ قهرمان"),
               kb([btn("🏟 میدانِ من", f"sk:ar:{uid}", "blue")]))


# ───────────────────────────── 🎛 کال‌بک‌ها ─────────────────────────────
async def arena_cb(cq, bot: Bot, parts: list):
    """sk:ap:<k>:<st>:<tid>:<ts>:<aid> · sk:df:<c>:<oid>:<tid> · sk:rv:<aid>:<me> · sk:ar:<n> · sk:lb:<n>
       sk:rp:<x>:<tid>:<amt>:<ts>:<aid> · sk:rr:<x>:<oid>:<tid> · sk:rn:<oid>:<tid>
       sk:ap:…:<aid>[:r] (ریسکی) · sk:gs:<h|q|f|i>:<oid>:0 (حدس) · sk:rm:<aid>:<tid> (ریمچ)"""
    uid = cq.from_user.id
    try:
        act = parts[1]
        if act == "ap" and len(parts) >= 7:
            kind, st, tid, ts = _CODE_KIND.get(parts[2]), parts[3], int(parts[4]), int(parts[5])
            if not kind or st not in ATT:
                await cq.answer()
            elif int(parts[6]) != uid:
                await cq.answer("این پنل مالِ تو نیست؛ خودت «حمله» رو بزن. 😉", show_alert=True)
            elif _tsmin() - ts > PICK_TTL_MIN:
                await cq.answer("این پنل قدیمی شده؛ دوباره «حمله» رو بزن. ⏳", show_alert=True)
            else:
                await _commit(cq, bot, kind, st, uid, tid, risky=(len(parts) >= 8 and parts[7] == "r"))
        elif act == "df" and len(parts) >= 5:
            await _defend(cq, bot, parts[2], ObjectId(parts[3]), uid)
        elif act == "rv" and len(parts) >= 4:
            await _revenge(cq, bot, int(parts[2]), uid)
        elif act == "sb" and len(parts) >= 5:
            await _sbet(cq, bot, parts[2], ObjectId(parts[3]), uid)
        elif act == "su" and len(parts) >= 5:
            await _support(cq, bot, parts[2], ObjectId(parts[3]), uid)
        elif act == "gs" and len(parts) >= 5:
            await _guess(cq, bot, parts[2], ObjectId(parts[3]), uid)
        elif act == "rm" and len(parts) >= 4:
            await _rematch(cq, bot, int(parts[2]), int(parts[3]), uid)
        elif act == "ar":
            await cq.answer()
            await do_arena(CbMsg(cq, bot))
        elif act == "lb":
            await cq.answer()
            await do_arena_board(CbMsg(cq, bot))
        elif act == "rp" and len(parts) >= 7:
            x, tid, amt, ts = parts[2], int(parts[3]), int(parts[4]), int(parts[5])
            if x not in RPS:
                await cq.answer()
            elif int(parts[6]) != uid:
                await cq.answer("این پنل مالِ تو نیست. 😉", show_alert=True)
            elif _tsmin() - ts > PICK_TTL_MIN:
                await cq.answer("این پنل قدیمی شده؛ دوباره «شرط» رو بزن. ⏳", show_alert=True)
            else:
                await _bet_commit(cq, bot, x, uid, tid, amt)
        elif act == "rr" and len(parts) >= 5:
            await _bet_answer(cq, bot, parts[2], ObjectId(parts[3]), uid)
        elif act == "rn" and len(parts) >= 4:
            await _bet_decline(cq, bot, ObjectId(parts[2]), uid)
        else:
            await cq.answer()
    except Exception:
        log.exception("arena callback failed")
        try:
            await cq.answer("یه مشکل کوچیک پیش اومد. دوباره امتحان کن. 🛠", show_alert=True)
        except Exception:
            pass


async def _revenge(cq, bot: Bot, target_id: int, uid: int):
    if cq.message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await cq.answer("انتقام فقط تو گروه ممکنه. 👥", show_alert=True)
        return
    adoc, tdoc = await store.get(uid), await store.get(target_id)
    if not adoc or not tdoc or float((adoc.get("sk_rev") or {}).get(str(target_id), 0)) <= time.time():
        await cq.answer("حقِ انتقامت تموم شده. ⌛", show_alert=True)
        return
    await cq.answer()
    await attack_open(CbMsg(cq, bot), adoc, tdoc, "attack")


async def _rematch(cq, bot: Bot, a_id: int, t_id: int, uid: int):
    """🥋 ریمچِ تمرینیِ یک‌کلیکی؛ فقط خودِ دو طرف می‌تونن بزنن (بدونِ ضرر؛ پاداشِ روزانه سقف داره)."""
    if uid not in (a_id, t_id):
        await cq.answer("این ریمچ مالِ تو نیست. 😉", show_alert=True)
        return
    if cq.message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await cq.answer("ریمچ فقط تو گروه ممکنه. 👥", show_alert=True)
        return
    opp = t_id if uid == a_id else a_id
    adoc, tdoc = await store.get(uid), await store.get(opp)
    if not adoc or not tdoc:
        await cq.answer("بازیکن پیدا نشد.", show_alert=True)
        return
    await cq.answer()
    await attack_open(CbMsg(cq, bot), adoc, tdoc, "spar")


# ───────────────────────────── 🪝 هوک‌ها (از skirmish.py) ─────────────────────────────
async def quest(m, kind: str, uid: Optional[int] = None):
    await quest_progress(m, kind, uid=uid)


async def renown(uid: int, delta: int):
    info = await _add_rp(uid, delta)
    return info
