"""🎭 باشگاهِ ریپلای — بازی‌های سریعِ ریپلایی تو گپ + لایه‌ی عمقِ حمله (تب، زخم، تسلطِ ژست، صندوقِ روزانه).

بازی‌ها (همه با «ریپلای» روی پیامِ یه بازیکن تو گروه؛ شرطِ GS اختیاریه و بدونش «دوستانه» حساب میشه):
• 🎲 تاس   — «تاس [مبلغ]»: ربات تاس/دارت/بسکتبال/فوتبال/بولینگِ واقعیِ تلگرام می‌ندازه؛ مساوی = ریرول.
• 🔫 هفت‌تیر — «هفت تیر [مبلغ]»: «آماده…» → (۲ تا ۶ ثانیه‌ی تصادفی) → «شلیک!». زودتر بزنی = فالت. سریع‌ترین دست برنده‌ست
              و زمانِ واکنش (ms) ثبت میشه؛ جدولِ «سریع ترین ها» داره.
• 🎭 بلوف  — «بازی بلوف [مبلغ]»: یه عددِ مخفی انتخاب می‌کنی و یه عدد «می‌گی»؛ حریف باید تصمیم بگیره باور کنه یا نه.
              نقش‌ها هر راند عوض میشن، اولین نفرِ ۲ امتیازی برنده‌ست.

لایه‌ی عمق (به حمله/تمرینِ arena.py وصله):
• 🌡 تب: هر برخوردِ ریپلایی تب رو بالا می‌بره و با زمان خنک میشه؛ ۳ پله (گرم/داغ/شعله‌ور) = XPِ بیشتر و تو شعله‌ور +۱🕯.
• 🩸 زخم: ضربه‌ی سنگین/خوانده‌شدن زخمی‌ت می‌کنه (برخوردِ بعدی −۱🕯)؛ «ترمیمِ» یه دوست زخم رو پاک می‌کنه.
• 🎖 تسلطِ ژست: هر برد با یه ژست پیشرفتش رو بالا می‌بره؛ سطح ۲ = +۱ RP، سطح ۳ = +۱🕯 با اون ژست، سطح ۴ = لقب.
• 🎁 صندوقِ باشگاه: ۳/۷/۱۲ برخوردِ ریپلایی در روز (حمله، تمرین و بازی‌ها) = صندوقِ شانسی + روزهای پشت‌سرهم.

v3.8 (بازی‌های جدید + اعتیادِ چت):
• 💣 بمب      — «بمب بازی [مبلغ]»: بمبِ فیتیله‌مخفی دست‌به‌دست میشه؛ «پاس بده» یا «✂️ خنثی کن» (ریسکی). تو دستِ هر کی بترکه می‌بازه.
• 🃏 بیست‌ویک — «بیست و یک [مبلغ]»: نوبتی «کارت» یا «بس»؛ نزدیک‌تر به ۲۱ برنده‌ست، رد شدن = سوختن.
• 🌍 چالشِ باز — «تاس باز»، «بمب بازی باز 30»، …: بدونِ ریپلای؛ هر کی تو گپ قبول کنه حریفه (نفر‌به‌نفر، بدونِ گیلد).
• 💰 دو برابر یا هیچ + 📊 سریِ امروز + 🎁 «فقط ۱ برخورد تا صندوق» + ⛓ شکستنِ زنجیره‌ی بردِ باشگاه (XP).
• 🎯 نشانِ شکار (عمقِ حمله): هر بار حرکتِ حریف رو بخونی یه نشان روش می‌زنی؛ ۳ نشانِ تازه = برخوردِ بعدی +۱🕯.

امنیت: انتقالِ GS با «امانتِ تک‌سندی» روی خودِ کاربر (کم‌کردن + مارکر، پرداخت + حذفِ مارکر تو یک آپدیت)؛ پس پرداخت دقیقاً
یک‌بار انجام میشه و بعد از ری‌استارت هر بازیِ نیمه‌کاره با بازگشتِ کاملِ پول بسته میشه. سقفِ شرط، سقفِ سودِ روزانه و سقفِ
تعدادِ شرط با یه جفت ثابتن؛ ۵٪ از پات می‌سوزه. محافظت (opted_out) مطلقه.
"""

import asyncio
import random
import re
import time
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from bson import ObjectId
from pymongo import ReturnDocument

from battle_engine import MAX_SOUL
from config import GS, log
from database import store
from economy import burn, log_tx
from npcreply import norm
from players import grant
from render import display
from ui import btn, kb, panel, say
from utils import day_key, esc, ir_now, is_group, spawn, utcnow

# ───────────────────────────── ⚙️ ثابت‌ها ─────────────────────────────
MAX_STAKE = 100
STAKE_MIN_LEVEL = 2
FEE_PCT = 5
DAILY_PROFIT_CAP = 300          # سقفِ سودِ خالصِ روزانه از شرط‌ها
PAIR_STAKE_DAILY = 8            # حداکثر بازیِ شرطی با یه حریف تو روز
WAIT_SECS = 90                  # مهلتِ قبولِ چالش
BLUFF_IDLE = 70                 # بیکاریِ بلوف = باخت
DRAW_MIN_DELAY, DRAW_MAX_DELAY, DRAW_WINDOW = 2.2, 5.8, 12
BLUFF_WIN, BLUFF_MAX_ROUNDS = 2, 6
DICE_SET = [("🎲", 6), ("🎯", 6), ("🎳", 6), ("🏀", 5), ("⚽", 5)]
DICE_REROLLS = 2
OPEN_WAIT = 120                 # مهلتِ چالشِ باز (هر کی قبول کنه حریفه)
BOMB_MIN, BOMB_MAX, BOMB_IDLE = 4, 9, 16
BJ_TARGET, BJ_IDLE = 21, 40
MARK_NEED, MARK_TTL, MARK_FRESH = 3, 3 * 3600, 3 * 3600      # 🎯 نشانِ شکار: ۳ نشانِ تازه (تا ۳ ساعت)
STREAK_BREAK_MIN, STREAK_BREAK_XP = 3, 8                      # ⛓ شکستنِ زنجیره‌ی بردِ باشگاه (XP هر بُردِ زنجیره، سقفِ ۴۰)

HYPE_DECAY = 300                # هر ۳۰۰ ثانیه ۱ واحد خنک میشه
HYPE_TIERS = [(75, 3, "☄️", "شعله‌ور"), (45, 2, "🔥", "داغ"), (20, 1, "🌡", "گرم")]
HYPE_XP = (0, 2, 4, 6)

WOUND_SECS = 30 * 60
MAST_LEVELS = (6, 18, 40, 80)   # تعدادِ بردِ لازم برای سطح ۱..۴
MAST_NAMES = {
    "h": ("💥", "کوبنده"), "q": ("🗡", "تیغ"), "f": ("🌀", "فریب"),
    "g": ("🛡", "سپر"), "e": ("💨", "سایه"), "c": ("🔄", "تلافی"),
}
MAST_TITLE = {
    "h": "استادِ کوبش", "q": "تیغِ بی‌امان", "f": "ملکه‌ی فریب",
    "g": "دیوارِ آهنین", "e": "سایه‌ی لغزان", "c": "تلافی‌گرِ بی‌رحم",
}
CHEST = {3: ((10, 30), 15), 7: ((20, 60), 30), 12: ((35, 100), 50)}      # آستانه → ((بازه‌ی GS)، XP)
JACKPOT_P = 0.05

KINDS = {"d": ("🎲", "تاس"), "q": ("🔫", "هفت‌تیر"), "b": ("🎭", "بلوف"), "m": ("💣", "بمب"), "j": ("🃏", "بیست‌ویک")}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_AMT = r"(?: (\d{1,3}))?(?: gs| جی اس)?"
DICE_RE = re.compile(r"(?:تاس|تاس بریزیم|تاس بندازیم)" + _AMT)
DRAW_RE = re.compile(r"(?:هفت ?تیر|تیراندازی|دوئل سریع)" + _AMT)
BLUFF_RE = re.compile(r"(?:بازی بلوف|بلوف بازی|بازی دروغگو)" + _AMT)
BOMB_RE = re.compile(r"(?:بمب بازی|بازی بمب|بمب دست ?به ?دست|سیب ?زمینی داغ)" + _AMT)
BJ_RE = re.compile(r"(?:بیست ?و ?یک|بازی بیست ?و ?یک|بلک ?جک)" + _AMT)
OPEN_RE = re.compile(r"(تاس|هفت ?تیر|بازی بلوف|بمب بازی|بازی بمب|بیست ?و ?یک|بلک ?جک) (?:باز|همگانی|آزاد)" + _AMT)
CLUB_RE = re.compile(r"(?:باشگاه|باشگاه ریپلای|باشگاه ریپلایی|کلاب)")
FAST_RE = re.compile(r"(?:سریع ?ترین ها|سریع ?ترین دست ها|رکورد واکنش)")
_NEEDS_REPLY = (DICE_RE, DRAW_RE, BLUFF_RE, BOMB_RE, BJ_RE)
_BY_KIND = (("d", DICE_RE), ("q", DRAW_RE), ("b", BLUFF_RE), ("m", BOMB_RE), ("j", BJ_RE))
_HOW = {
    "d": "ربات یه تاس/دارت/توپِ واقعی برای هر دو می‌ندازه؛ بالاتر برنده‌ست.",
    "q": "«آماده…» میاد؛ تا «شلیک!» دستت رو نگه دار! زودتر بزنی فالت میشی. سریع‌ترین برنده‌ست.",
    "b": "یه عدد مخفی انتخاب می‌کنی و یه عدد «می‌گی»؛ حریف باید باور کنه یا بگه دروغگو. اولین ۲ امتیاز می‌بره.",
    "m": "یه بمبِ فیتیله‌مخفی دست‌به‌دست میشه؛ هر نوبت «پاس بده» یا «✂️ خنثی کن» (ریسکی). تو دستِ هر کی بترکه می‌بازه!",
    "j": "هر نفر دو کارت داره؛ نوبتی «کارت» بکش یا «بس» بگو. نزدیک‌تر به ۲۱ برنده‌ست و رد شدن از ۲۱ = سوختن!",
}


def _open_kind(name: str) -> Optional[str]:
    return next((k for k, rx in _BY_KIND if rx.fullmatch(name)), None)


def _n(raw: str) -> str:
    return norm((raw or "").translate(_DIGITS))


def matches(raw: str, has_reply: bool = True) -> bool:
    t = _n(raw)
    if CLUB_RE.fullmatch(t) or FAST_RE.fullmatch(t) or OPEN_RE.fullmatch(t):
        return True
    return has_reply and any(r.fullmatch(t) for r in _NEEDS_REPLY)


def _nm(d: Optional[dict]) -> str:
    return esc((d or {}).get("first_name") or (d or {}).get("username") or "ناشناس")


def _bar(v: float, mx: int, w: int = 10) -> str:
    k = max(0, min(w, round(w * v / mx))) if mx else 0
    return "▰" * k + "▱" * (w - k)


# ───────────────────────────── 🌡 تب ─────────────────────────────
def hype_now(doc: Optional[dict], now: Optional[float] = None) -> float:
    d = doc or {}
    now = now or time.time()
    h, t = float(d.get("rg_hype", 0) or 0), d.get("rg_hype_t")
    if not h or not t:
        return 0.0
    return max(0.0, min(100.0, h - (now - float(t)) / HYPE_DECAY))


def hype_tier(h: float) -> tuple:
    """(پله 0..3، آیکون، اسم)."""
    for th, tier, ic, nm in HYPE_TIERS:
        if h >= th:
            return tier, ic, nm
    return 0, "❄️", "سرد"


async def hype_add(uid: int, n: int):
    now = time.time()
    cur = {"$ifNull": ["$rg_hype", 0]}
    age = {"$divide": [{"$subtract": [now, {"$ifNull": ["$rg_hype_t", now]}]}, HYPE_DECAY]}
    try:
        await store.users.update_one({"user_id": uid}, [{"$set": {
            "rg_hype": {"$min": [100, {"$add": [{"$max": [0, {"$subtract": [cur, age]}]}, n]}]}, "rg_hype_t": now}}])
    except Exception:
        log.exception("hype_add failed")


def hype_line(doc: dict) -> str:
    h = hype_now(doc)
    tier, ic, nm = hype_tier(h)
    perk = ("" if tier == 0 else f" · +{HYPE_XP[tier]} XP هر برخورد" + (" · +۱🕯 تو حمله" if tier == 3 else ""))
    return f"{ic} تب: {_bar(h, 100)} {int(h)}/100 — {nm}{perk}"


# ───────────────────────────── 🎖 تسلطِ ژست ─────────────────────────────
def mast_level(count: int) -> int:
    return sum(1 for t in MAST_LEVELS if count >= t)


def mast_count(doc: Optional[dict], code: str) -> int:
    return int(((doc or {}).get("rg_mast") or {}).get(code, 0) or 0)


def mast_level_of(doc: Optional[dict], code: str) -> int:
    return mast_level(mast_count(doc, code)) if code in MAST_NAMES else 0


# ───────────────────────────── 🩸 زخم ─────────────────────────────
def wounded(doc: Optional[dict], now: Optional[float] = None) -> bool:
    return float((doc or {}).get("rg_wound_until", 0) or 0) > (now or time.time())


# ───────────────────────────── 🎯 نشانِ شکار ─────────────────────────────
def marks_of(doc: Optional[dict], opp, now: Optional[float] = None) -> int:
    """تعدادِ نشانِ «تازه»ای که صاحبِ doc روی حریفِ opp داره (۰..MARK_NEED)."""
    v = ((doc or {}).get("rg_marks") or {}).get(str(opp))
    try:
        if not v or len(v) < 2 or (now or time.time()) - float(v[1]) > MARK_TTL:
            return 0
        return max(0, min(MARK_NEED, int(v[0])))
    except (TypeError, ValueError):
        return 0


async def mark_add(uid: int, opp: int) -> int:
    """یه نشان روی حریف می‌زنه (نشانِ کهنه‌ها پاک میشن)؛ تعدادِ جدید رو برمی‌گردونه."""
    try:
        now = time.time()
        doc = await store.users.find_one({"user_id": uid}, {"rg_marks": 1}) or {}
        mk = doc.get("rg_marks") or {}
        n = min(MARK_NEED, marks_of(doc, opp, now) + 1)
        upd: dict = {"$set": {f"rg_marks.{opp}": [n, now]}}
        stale = {f"rg_marks.{k}": "" for k, v in mk.items() if k != str(opp) and marks_of(doc, k, now) == 0}
        if stale:
            upd["$unset"] = stale
        await store.users.update_one({"user_id": uid}, upd)
        return n
    except Exception:
        log.exception("mark_add failed")
        return 0


async def mark_clear(uid: int, opp: int):
    try:
        await store.users.update_one({"user_id": uid}, {"$unset": {f"rg_marks.{opp}": ""}})
    except Exception:
        log.exception("mark_clear failed")


def _mark_bar(n: int) -> str:
    return "🎯" * n + "▫️" * (MARK_NEED - n)


def attack_panel_lines(adoc: dict, tdoc: dict, now: Optional[float] = None) -> list:
    """خط‌هایی که پنلِ انتخابِ ژستِ حمله اضافه می‌کنه (تب، زخم‌ها، نشان‌های شکار)."""
    now = now or time.time()
    out = [hype_line(adoc)]
    mk = marks_of(adoc, tdoc.get("user_id"), now)
    if mk:
        out.append(f"🎯 نشانِ شکار روی {_nm(tdoc)}: {_mark_bar(mk)}" + (" — پُره! این برخورد +۱🕯 داری" if mk >= MARK_NEED else f" ({mk}/{MARK_NEED}؛ یه خوندنِ دیگه…)"))
    mk2 = marks_of(tdoc, adoc.get("user_id"), now)
    if mk2:
        out.append(f"⚠️ {_nm(tdoc)} روی تو {mk2}/{MARK_NEED} نشان داره" + (" — پُره؛ این برخورد +۱🕯 برای اونه!" if mk2 >= MARK_NEED else "؛ ژست‌هات رو عوض کن!"))
    if wounded(adoc, now):
        out.append("🩸 تو زخمی‌ای: تو این برخورد −۱🕯 داری. یه دوست «ترمیم» کنه پاک میشه!")
    if wounded(tdoc, now):
        out.append(f"🩸 {_nm(tdoc)} زخمیه: −۱🕯 برای اون؛ فرصتِ خوبیه! 😈")
    return out


def defense_panel_lines(adoc: dict, tdoc: dict, now: Optional[float] = None) -> list:
    """خط‌های اضافه‌ی پنلِ دفاع (از دیدِ مدافع tdoc)."""
    now = now or time.time()
    out = []
    mk = marks_of(tdoc, adoc.get("user_id"), now)
    if mk:
        out.append(f"🎯 تو روی {_nm(adoc)} {_mark_bar(mk)}" + (" داری — پُره: +۱🕯 تو این برخورد!" if mk >= MARK_NEED else f" نشان داری ({mk}/{MARK_NEED})."))
    mk2 = marks_of(adoc, tdoc.get("user_id"), now)
    if mk2:
        out.append(f"⚠️ {_nm(adoc)} روی تو {mk2}/{MARK_NEED} نشان داره" + (" — پُره؛ +۱🕯 برای اونه!" if mk2 >= MARK_NEED else "."))
    if wounded(tdoc, now):
        out.append("🩸 تو زخمی‌ای: تو این برخورد −۱🕯 داری.")
    return out


async def pre_fight(adoc: dict, tdoc: dict, st: str, dfn: str, auto: bool, fa: dict, fb: dict, kind: str) -> list:
    """قبل از نبردِ رشته‌ی سرنوشت: روحِ شروعِ دو طرف رو با تب/تسلط/زخم تنظیم می‌کنه. خطاش حمله رو خراب نمی‌کنه."""
    notes: list = []
    if kind != "attack":
        return notes
    try:
        now = time.time()
        for d, f, pose, is_def, opp in ((adoc, fa, st, False, tdoc["user_id"]), (tdoc, fb, dfn, True, adoc["user_id"])):
            up, down, nm = 0, 0, _nm(d)
            if marks_of(d, opp, now) >= MARK_NEED:
                up += 1
                notes.append(f"🎯 نشانِ شکارِ <b>{nm}</b> پُر بود: +۱🕯")
                await mark_clear(d["user_id"], opp)
            if hype_tier(hype_now(d, now))[0] >= 3:
                up += 1
                notes.append(f"☄️ تبِ <b>{nm}</b> شعله‌ور: +۱🕯")
            if pose in MAST_NAMES and not (is_def and auto) and mast_level_of(d, pose) >= 3:
                up += 1
                notes.append(f"🎖 تسلطِ {MAST_NAMES[pose][0]}: <b>{nm}</b> +۱🕯")
            if wounded(d, now):
                down = 1
                f["_wounded"] = True
                notes.append(f"🩸 زخمِ <b>{nm}</b>: −۱🕯")
            f["soul"] = max(0, min(MAX_SOUL, int(f.get("soul", 0)) + up - down))
    except Exception:
        log.exception("rg pre_fight failed")
    return notes


async def post_fight(adoc: dict, tdoc: dict, st: str, dfn: str, win: bool, res: int, auto: bool, an: str, dn: str) -> list:
    """بعد از نتیجه‌ی حمله: زخمِ تازه/پاک‌شدنِ زخمِ قبلی، تسلطِ ژست و XPِ تب. خط‌های اضافه‌ی پنل رو برمی‌گردونه."""
    lines: list = []
    try:
        now = time.time()
        aid, tid = adoc["user_id"], tdoc["user_id"]
        loser = tid if win else aid
        lname = dn if win else an
        hard = (win and (st in ("h", "x") or res > 0)) or (not win and res < 0 and not auto)
        for d, uid in ((adoc, aid), (tdoc, tid)):
            if uid == loser and hard:
                await store.users.update_one({"user_id": uid}, {"$set": {"rg_wound_until": now + WOUND_SECS}})
                lines.append(f"🩸 <b>{lname}</b> زخمی شد؛ برخوردِ بعدیش −۱🕯 شروع میشه ({WOUND_SECS // 60} دقیقه). یه دوست می‌تونه «ترمیم» کنه!")
            elif wounded(d, now):
                await store.users.update_one({"user_id": uid}, {"$unset": {"rg_wound_until": ""}})
        # 🎖 تسلط: برنده با ژستِ پیروزش پیشرفت می‌گیره
        wid, code, wname = (aid, st, an) if win else (tid, dfn, dn)
        if code in MAST_NAMES and not (not win and auto):
            nd = await store.users.find_one_and_update({"user_id": wid}, {"$inc": {f"rg_mast.{code}": 1}}, return_document=ReturnDocument.AFTER)
            cnt = mast_count(nd, code)
            lv, ic = mast_level(cnt), MAST_NAMES[code][0]
            if lv > mast_level(cnt - 1):
                lines.append(f"🎖 <b>{wname}</b>: تسلطِ {ic} {MAST_NAMES[code][1]} → سطح <b>{lv}</b>!"
                             + (" (+۱ RP با هر بردِ این ژست)" if lv == 2 else " (+۱🕯 با این ژست)" if lv == 3 else ""))
                if lv >= 4:
                    await store.users.update_one({"user_id": wid}, {"$addToSet": {"titles": MAST_TITLE[code]}})
                    lines.append(f"🏷 لقبِ تازه: «{MAST_TITLE[code]}»")
            if lv >= 2:
                try:
                    import arena
                    await arena.renown(wid, 1)
                except Exception:
                    log.exception("rg mastery rp failed")
        # 🎯 نشانِ شکار: کسی که حرکتِ حریف رو «خونده» (و دفاعِ خودکار نبوده) یه نشان می‌زنه
        if not auto and res != 0:
            reader, victim, rname = (aid, tid, an) if res > 0 else (tid, aid, dn)
            n = await mark_add(reader, victim)
            if n:
                lines.append(f"🎯 <b>{rname}</b> حرکتِ حریف رو خوند و نشان زد {_mark_bar(n)}"
                             + (" — پُر شد! برخوردِ بعدیشون +۱🕯 برای اونه." if n >= MARK_NEED else ""))
        # 🌡 XPِ تب (هر دو طرف)
        bonus = []
        for d, nm in ((adoc, an), (tdoc, dn)):
            xp = HYPE_XP[hype_tier(hype_now(d, now))[0]]
            if xp:
                await grant(d["user_id"], xp=xp)
                bonus.append(f"{nm} +{xp}")
        if bonus:
            lines.append("🌡 XPِ تب: " + " · ".join(bonus))
    except Exception:
        log.exception("rg post_fight failed")
    return lines


async def on_heal(healer: int, target: int):
    """ترمیمِ یه دوست زخم رو پاک می‌کنه؛ هر دو طرف کمی تب می‌گیرن."""
    try:
        res = await store.users.update_one({"user_id": target, "rg_wound_until": {"$gt": time.time()}}, {"$unset": {"rg_wound_until": ""}})
        await hype_add(healer, 6)
        if res.modified_count:
            await store.users.update_one({"user_id": healer}, {"$inc": {"rg_cures": 1}})
            await hype_add(target, 4)
    except Exception:
        log.exception("rg on_heal failed")


# ───────────────────────────── 🎁 باشگاه: شمارنده‌ی روز و صندوق ─────────────────────────────
async def club_bump(bot: Bot, chat_id: int, uid: int) -> int:
    """یک برخوردِ ریپلایی به حسابِ امروز اضافه می‌کنه؛ اگه به آستانه برسه صندوق باز میشه. تعدادِ امروز رو برمی‌گردونه."""
    n = 0
    try:
        today = day_key()
        yday = (ir_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        same = {"$eq": ["$rg_day", today]}
        doc = await store.users.find_one_and_update({"user_id": uid}, [{"$set": {
            "rg_n": {"$cond": [same, {"$add": [{"$ifNull": ["$rg_n", 0]}, 1]}, 1]},
            "rg_dstreak": {"$cond": [same, {"$ifNull": ["$rg_dstreak", 1]},
                                     {"$cond": [{"$eq": ["$rg_day", yday]}, {"$add": [{"$ifNull": ["$rg_dstreak", 0]}, 1]}, 1]}]},
            "rg_claim": {"$cond": [same, {"$ifNull": ["$rg_claim", []]}, []]},
            "rg_day": today}}], return_document=ReturnDocument.AFTER)
        if not doc:
            return 0
        n = int(doc.get("rg_n", 0))
        for th in sorted(CHEST):
            if n < th:
                continue
            got = await store.users.update_one({"user_id": uid, "rg_claim": {"$ne": th}}, {"$push": {"rg_claim": th}})
            if not got.modified_count:
                continue
            (lo, hi), xp = CHEST[th]
            gs = random.randint(lo, hi)
            jackpot = random.random() < JACKPOT_P
            if jackpot:
                gs *= 3
            ds = int(doc.get("rg_dstreak", 1))
            if th == min(CHEST):
                gs += 3 * min(ds, 7)
            await grant(uid, gold=gs, xp=xp)
            await bot.send_message(chat_id, panel("yellow", "🎁", "صندوقِ باشگاهِ ریپلای باز شد!" if not jackpot else "🎰 جکپات! صندوقِ باشگاه", [
                f"{display(doc, link=True)} امروز <b>{n}</b> برخوردِ ریپلایی داشته (آستانه‌ی {th}).",
                f"🪙 +{gs} {GS} · ⭐ +{xp} XP" + (" · 🎰 ×۳ جکپات!" if jackpot else ""),
                f"📆 روزهای پشت‌سرهم: <b>{ds}</b>" + (f" (پاداشِ استریک +{3 * min(ds, 7)})" if th == min(CHEST) and ds > 1 else ""),
                f"⏭ صندوقِ بعدی: " + (f"{next(x for x in sorted(CHEST) if x > th)} برخورد" if th < max(CHEST) else "فردا دوباره!"),
            ]))
    except Exception:
        log.exception("club_bump failed")
    return n


async def _stat(uid: int, kind: str, res: str) -> tuple:
    """res: w/l/d؛ زنجیره‌ی بردِ باشگاه رو هم نگه می‌داره. خروجی = (زنجیره‌ی فعلی بعد از برد، زنجیره‌ای که با این باخت شکست)."""
    upd: dict = {"$inc": {f"rg_st.{kind}.{res}": 1}}
    if res == "w":
        upd["$inc"]["rg_ws"] = 1
    elif res == "l":
        upd["$set"] = {"rg_ws": 0}
    doc = await store.users.find_one_and_update({"user_id": uid}, upd, return_document=ReturnDocument.BEFORE)
    prev = int((doc or {}).get("rg_ws", 0) or 0)
    if res == "w" and doc:
        ws = prev + 1
        await store.users.update_one({"user_id": uid, "rg_ws_best": {"$not": {"$gte": ws}}}, {"$set": {"rg_ws_best": ws}})
        return ws, 0
    return 0, (prev if res == "l" else 0)


_WS_BANNER = {3: "🔥 سه بردِ پشت‌سرهم!", 5: "💀 پنج‌تایی! کسی جلوداره نیست!", 8: "👑 هشت‌تایی؛ افسانه‌ی باشگاه!"}


# ───────────────────────────── 💰 امانتِ تک‌سندی ─────────────────────────────
async def _hold(uid: int, gid, amount: int) -> bool:
    """کم‌کردنِ شرط + مارکر تو یک آپدیتِ اتمیک (دوباره‌کم‌شدن/ازدست‌رفتن ممکن نیست)."""
    if amount <= 0:
        return True
    res = await store.users.update_one(
        {"user_id": uid, "gold": {"$gte": amount}, f"rg_hold.{gid}": {"$exists": False}},
        {"$inc": {"gold": -amount}, "$set": {f"rg_hold.{gid}": amount}})
    if res.modified_count:
        await log_tx(uid, -amount, "rg_stake", str(gid))
    return bool(res.modified_count)


async def _release(uid: int, gid, amount: int) -> bool:
    """برگرداندنِ امانت (amount=۰ یعنی فقط مارکر پاک بشه). idempotent: بدونِ مارکر هیچ اتفاقی نمیفته."""
    upd: dict = {"$unset": {f"rg_hold.{gid}": ""}}
    if amount > 0:
        upd["$inc"] = {"gold": amount}
    res = await store.users.update_one({"user_id": uid, f"rg_hold.{gid}": {"$exists": True}}, upd)
    if res.modified_count and amount > 0:
        await log_tx(uid, amount, "rg_payout", str(gid))
    return bool(res.modified_count)


async def _payout(g: dict):
    """پرداختِ idempotent بر اساسِ برنده‌ی ثبت‌شده؛ بعدش بازی «done» میشه."""
    gid, stake, a, t, w = g["_id"], int(g.get("stake", 0)), g["a"], g["t"], g.get("winner")
    if stake > 0:
        if w in (a, t):
            l = t if w == a else a
            pot = stake * 2
            fee = max(1, pot * FEE_PCT // 100)
            if await _release(w, gid, pot - fee):
                await burn(fee, "rg_fee")
                await _profit(w, pot - fee - stake)
            await _release(l, gid, 0)
        else:
            await _release(a, gid, stake)
            await _release(t, gid, stake)
    await store.rgames.update_one({"_id": gid}, {"$set": {"status": "done"}})


async def _profit(uid: int, net: int):
    today = day_key()
    await store.users.update_one({"user_id": uid, "rg_prof_day": {"$ne": today}}, {"$set": {"rg_prof_day": today, "rg_prof": 0}})
    await store.users.update_one({"user_id": uid}, {"$inc": {"rg_prof": net}})


async def _refund_all(g: dict):
    for uid in (g["a"], g["t"]):
        await _release(uid, g["_id"], int(g.get("stake", 0)))


# ───────────────────────────── 🧩 ابزارهای مشترکِ بازی ─────────────────────────────
async def _edit(bot: Bot, g: dict, text: str, markup=None):
    try:
        await bot.edit_message_text(text, chat_id=g["chat_id"], message_id=g["msg_id"], reply_markup=markup)
    except Exception as e:
        log.debug("rg edit failed: %s", e)


async def _claim(gid, frm, to: str, **extra) -> Optional[dict]:
    """گذارِ اتمیکِ وضعیت؛ فقط یک نفر موفق میشه."""
    flt = {"_id": gid, "status": frm} if isinstance(frm, str) else {"_id": gid, **frm}
    return await store.rgames.find_one_and_update(flt, {"$set": {"status": to, **extra}}, return_document=ReturnDocument.AFTER)


async def _end(bot: Bot, gid, flt: dict, winner: Optional[int], **extra) -> Optional[dict]:
    """پایانِ بازیِ زنده: «settling» با برنده‌ی ثبت‌شده؛ بعد پرداخت و پنلِ نتیجه."""
    g = await store.rgames.find_one_and_update(
        {"_id": gid, "status": "live", **flt}, {"$set": {"status": "settling", "winner": winner, "ended": time.time(), **extra}},
        return_document=ReturnDocument.AFTER)
    if not g:
        return None
    try:
        await _payout(g)
        await _post(bot, g)
    except Exception:
        log.exception("rg end failed")
    return g


def _pair_kb(g: dict):
    return kb([btn("✅ قبول", f"rg:ac:{g['_id']}", "green"), btn("🙅 رد", f"rg:no:{g['_id']}", "red")])


def _rematch_kb(g: dict):
    # دکمه‌ی ریمچ: هر کی بزنه، چالش‌دهنده‌ی جدیده و طرفِ مقابل رو صدا می‌زنه. «دو برابر یا هیچ» / «شرطی» هم کنارشه.
    k, a, t, stake = g["kind"], g["a"], g["t"], int(g.get("stake", 0))
    row = [btn("🔁 ریمچ", f"rg:rm:{k}:{a}:{t}:{stake}", "green")]
    if stake > 0 and stake * 2 <= MAX_STAKE:
        row.append(btn(f"💰 دو برابر ({stake * 2})", f"rg:rm:{k}:{a}:{t}:{stake * 2}", "red"))
    elif stake == 0:
        row.append(btn("🪙 شرطی (۱۰)", f"rg:rm:{k}:{a}:{t}:10", "red"))
    return kb(row, [btn("🎭 باشگاه", "rg:ci", "blue")])


def _stake_line(stake: int) -> str:
    if stake <= 0:
        return "🤝 دوستانه (بدونِ شرط)"
    return f"🪙 شرط: <b>{stake}</b> {GS} از هر نفر · برنده {stake * 2 - max(1, stake * 2 * FEE_PCT // 100)} {GS} می‌گیره (کارمزد {FEE_PCT}٪ می‌سوزه)"


_TAUNTS = [
    "💅 «{w} بُرد. {l} هم مثلِ همیشه…»",
    "😈 {l}، فکر کردی راحته؟ {w} فقط گرم شد!",
    "🪦 ایزدبانو یه خطِ دیگه تو دفترِ شکستِ {l} نوشت.",
    "🥱 {w} حتی عرق هم نکرد؛ {l} ریمچ می‌خوای؟",
    "👑 امروز نوبتِ {w} بود. فردا؟ شاید نوبتِ {l}… شاید.",
    "🍿 تماشاچی‌ها: «{l} رو دیدی؟!» · «آره، دیدم… و حیف شد!»",
]


async def _series_line(g: dict, ad: dict, td: dict) -> Optional[str]:
    """📊 سریِ امروزِ دو نفر (همه‌ی بازی‌های باشگاه)؛ رقابتِ دوطرفه رو داغ نگه می‌داره."""
    try:
        a, t = g["a"], g["t"]
        flt = {"uids": {"$all": [a, t]}, "day": g.get("day"), "status": "done"}
        wa = await store.rgames.count_documents({**flt, "winner": a})
        wt = await store.rgames.count_documents({**flt, "winner": t})
        if wa + wt < 2:
            return None
        line = f"📊 امروز بینتون: {_nm(ad)} <b>{wa}</b> – <b>{wt}</b> {_nm(td)}"
        if abs(wa - wt) >= 2:
            line += f"\n😤 {_nm(ad if wa < wt else td)} عقبه؛ ریمچ بزن و جبران کن!"
        elif wa + wt >= 4:
            line += " · 🔥 رقابتِ داغ!"
        return line
    except Exception:
        log.exception("rg series failed")
        return None


async def _post(bot: Bot, g: dict):
    """بعد از پرداخت: آمار، تب، صندوق، سریِ امروز و پنلِ نتیجه."""
    kind, a, t, w = g["kind"], g["a"], g["t"], g.get("winner")
    ad, td = await store.get(a), await store.get(t)
    banners, near = [], []
    for uid, d in ((a, ad), (t, td)):
        res = "d" if w is None else "w" if uid == w else "l"
        ws, lost_ws = await _stat(uid, kind, res)
        if res == "w" and ws in _WS_BANNER:
            banners.append(f"{_WS_BANNER[ws]} — {display(d)}")
        if res == "l" and lost_ws >= STREAK_BREAK_MIN and w is not None:      # ⛓ زنجیره‌ی بردِ بازنده شکست
            xp = min(40, STREAK_BREAK_XP * lost_ws)
            await grant(w, xp=xp)
            banners.append(f"⛓ {display(ad if w == a else td)} زنجیره‌ی {lost_ws}تاییِ {display(d)} رو شکست! ⭐ +{xp} XP")
        await hype_add(uid, 14 if res == "w" else 9 if res == "l" else 5)
        n_today = await club_bump(bot, g["chat_id"], uid)
        if 0 < n_today <= max(CHEST):                       # XPِ بازی فقط برای ۱۲ بازیِ اولِ روز (ضدِ فارم)
            await grant(uid, xp=8 if res == "w" else 4)
        nxt = next((th for th in sorted(CHEST) if th > n_today), None)
        if nxt and nxt - n_today == 1:
            near.append(f"🎁 {_nm(d)}: فقط ۱ برخورد تا صندوقِ {nxt}تایی!")
    lines = list(g.get("res_lines") or [])
    stake = int(g.get("stake", 0))
    if w is not None:
        wd, ld = (ad, td) if w == a else (td, ad)
        lines.append(f"🏆 برنده: {display(wd, link=True)}")
        if stake > 0:
            win_amt = stake * 2 - max(1, stake * 2 * FEE_PCT // 100)
            lines.append(f"🪙 +{win_amt} {GS} (سودِ خالص {win_amt - stake})")
        lines.append(random.choice(_TAUNTS).format(w=_nm(wd), l=_nm(ld)))
    else:
        lines.append("🤝 مساوی/لغو — شرط‌ها برگشت.")
    sl = await _series_line(g, ad, td)
    if sl:
        lines.append(sl)
    lines += banners + near
    ic, nm = KINDS[kind]
    await _edit(bot, g, panel("purple", ic, f"{nm} — نتیجه", lines), _rematch_kb(g))


# ───────────────────────────── 🚪 شروعِ چالش ─────────────────────────────
async def _busy(*uids, ignore=None) -> bool:
    flt: dict = {"uids": {"$in": list(uids)}, "status": {"$in": ["wait", "live", "settling"]}}
    if ignore is not None:
        flt["_id"] = {"$ne": ignore}
    return bool(await store.rgames.find_one(flt))


async def _precheck(adoc: dict, tdoc: dict, stake: int, ignore=None) -> Optional[str]:
    if adoc.get("opted_out"):
        return "خودت «محافظت» رو فعال کردی؛ اول بنویس «برگردم به بازی». 🛡"
    if tdoc.get("opted_out"):
        return f"{display(tdoc)} «محافظت» فعال کرده؛ بهش نمیشه چالش داد. 🛡"
    if tdoc.get("registered") is False:
        return f"{display(tdoc)} هنوز قرارداد امضا نکرده. 📜"
    if await _busy(adoc["user_id"], tdoc["user_id"], ignore=ignore):
        return "یکی از شما هنوز تو یه بازیِ باشگاهه؛ اول اون تموم بشه. ⏳"
    if stake > 0:
        if stake > MAX_STAKE:
            return f"سقفِ شرط {MAX_STAKE} {GS} ـه. 🪙"
        if min(int(adoc.get("level", 1)), int(tdoc.get("level", 1))) < STAKE_MIN_LEVEL:
            return f"شرطی بازی کردن از سطح {STAKE_MIN_LEVEL} باز میشه؛ فعلاً دوستانه بازی کنین. 🐣"
        if int(adoc.get("gold", 0)) < stake:
            return f"موجودیت واسه شرطِ {stake} {GS} کافی نیست. 🪙"
        if int(tdoc.get("gold", 0)) < stake:
            return f"{display(tdoc)} موجودیِ کافی واسه این شرط نداره. 🪙"
        today = day_key()
        for d in (adoc, tdoc):
            if d.get("rg_prof_day") == today and int(d.get("rg_prof", 0)) >= DAILY_PROFIT_CAP:
                return f"{display(d)} امروز به سقفِ سودِ باشگاه ({DAILY_PROFIT_CAP} {GS}) رسیده؛ دوستانه بازی کنین. 🌙"
        n = await store.rgames.count_documents({"uids": {"$all": [adoc["user_id"], tdoc["user_id"]]}, "day": today,
                                                 "stake": {"$gt": 0}, "status": {"$in": ["live", "settling", "done"]}})
        if n >= PAIR_STAKE_DAILY:
            return "امروز زیادی با همین حریف شرطی بازی کردین؛ دوستانه ادامه بدین. 🔁"
    return None


async def _open(m, bot: Bot, kind: str, adoc: dict, tdoc: dict, stake: int):
    err = await _precheck(adoc, tdoc, stake)
    if err:
        return await say(m, err, KINDS[kind][0], KINDS[kind][1], "orange")
    ic, nm = KINDS[kind]
    aid, tid = adoc["user_id"], tdoc["user_id"]
    how = _HOW[kind]
    g = {"kind": kind, "chat_id": m.chat.id, "a": aid, "t": tid, "uids": [aid, tid], "stake": stake, "status": "wait",
         "created_at": utcnow(), "day": day_key(), "upd": time.time()}
    res = await store.rgames.insert_one(g)
    g["_id"] = res.inserted_id
    msg = await m.reply(panel("purple", ic, f"چالشِ {nm}", [
        f"{display(adoc, link=True)} {ic} {display(tdoc, link=True)} رو به <b>{nm}</b> دعوت کرد!",
        how, _stake_line(stake),
        f"👀 فقط {_nm(tdoc)} می‌تونه قبول کنه. ⏳ {WAIT_SECS} ثانیه وقت داره.",
    ]), reply_markup=_pair_kb(g))
    await store.rgames.update_one({"_id": g["_id"]}, {"$set": {"msg_id": msg.message_id}})
    spawn(_expire_wait(bot, g["_id"], WAIT_SECS))


async def _precheck_open(adoc: dict, stake: int) -> Optional[str]:
    """چکِ سازنده‌ی چالشِ باز (حریف هنوز مشخص نیست؛ چکِ کاملِ جفت موقعِ قبول انجام میشه)."""
    if adoc.get("opted_out"):
        return "خودت «محافظت» رو فعال کردی؛ اول بنویس «برگردم به بازی». 🛡"
    if await _busy(adoc["user_id"]):
        return "تو هنوز تو یه بازیِ باشگاهی؛ اول اون تموم بشه. ⏳"
    if stake > 0:
        if stake > MAX_STAKE:
            return f"سقفِ شرط {MAX_STAKE} {GS} ـه. 🪙"
        if int(adoc.get("level", 1)) < STAKE_MIN_LEVEL:
            return f"شرطی بازی کردن از سطح {STAKE_MIN_LEVEL} باز میشه؛ فعلاً دوستانه بازی کن. 🐣"
        if int(adoc.get("gold", 0)) < stake:
            return f"موجودیت واسه شرطِ {stake} {GS} کافی نیست. 🪙"
        if adoc.get("rg_prof_day") == day_key() and int(adoc.get("rg_prof", 0)) >= DAILY_PROFIT_CAP:
            return f"امروز به سقفِ سودِ باشگاه ({DAILY_PROFIT_CAP} {GS}) رسیدی؛ دوستانه بازی کن. 🌙"
    return None


async def _open_public(m, bot: Bot, kind: str, adoc: dict, stake: int):
    """🌍 چالشِ باز: بدونِ ریپلای؛ اولین نفری که قبول کنه (غیر از خودت) حریفه. نفر‌به‌نفره‌ست، گروهی نیست."""
    ic, nm = KINDS[kind]
    err = await _precheck_open(adoc, stake)
    if err:
        return await say(m, err, ic, nm, "orange")
    aid = adoc["user_id"]
    g = {"kind": kind, "chat_id": m.chat.id, "a": aid, "t": None, "uids": [aid], "stake": stake, "status": "wait", "open": True,
         "created_at": utcnow(), "day": day_key(), "upd": time.time()}
    res = await store.rgames.insert_one(g)
    g["_id"] = res.inserted_id
    msg = await m.reply(panel("purple", ic, f"🌍 چالشِ باز — {nm}", [
        f"{display(adoc, link=True)} یه چالشِ <b>{nm}</b> باز گذاشت! کی جرئتِ روبه‌رو شدن داره؟ 😏",
        _HOW[kind], _stake_line(stake),
        f"⏳ {OPEN_WAIT} ثانیه وقت هست؛ اولین نفرِ قبول‌کننده حریفه.",
    ]), reply_markup=kb([btn("⚔️ قبول می‌کنم", f"rg:ac:{g['_id']}", "green"), btn("🙅 پس‌گرفتن", f"rg:no:{g['_id']}", "red")]))
    await store.rgames.update_one({"_id": g["_id"]}, {"$set": {"msg_id": msg.message_id}})
    spawn(_expire_wait(bot, g["_id"], OPEN_WAIT))


async def _expire_wait(bot: Bot, gid, delay: float):
    try:
        await asyncio.sleep(delay)
        g = await _claim(gid, "wait", "expired")
        if g:
            who = await store.get(g["t"]) if g.get("t") else None
            await _edit(bot, g, panel("black", KINDS[g["kind"]][0], "چالش منقضی شد",
                                      [f"{_nm(who)} جواب نداد. 💤" if who else "هیچ‌کس جرئتِ قبول کردن نداشت! 🐔"]))
    except Exception:
        log.exception("rg expire_wait failed")


# ───────────────────────────── ✅ قبول / رد ─────────────────────────────
async def _accept(cq, bot: Bot, gid: ObjectId, uid: int):
    g = await store.rgames.find_one({"_id": gid})
    if not g or g["status"] != "wait":
        return await cq.answer("این چالش دیگه فعال نیست. ⌛", show_alert=True)
    if g.get("t") is None:                                   # 🌍 چالشِ باز
        return await _accept_open(cq, bot, g, uid)
    if uid != g["t"]:
        return await cq.answer("این چالش مالِ تو نیست؛ خودت یکی بساز! 😉", show_alert=True)
    g = await _claim(gid, "wait", "holding")
    if not g:
        return await cq.answer("دیر شد! ⌛", show_alert=True)
    await _go_live(cq, bot, g)


async def _accept_open(cq, bot: Bot, g: dict, uid: int):
    gid = g["_id"]
    if uid == g["a"]:
        return await cq.answer("چالشِ خودته! صبر کن یه حریف پیدا بشه. 😄", show_alert=True)
    adoc, tdoc = await store.get(g["a"]), await store.get(uid)
    if not adoc or not tdoc:
        return await cq.answer("بازیکن پیدا نشد؛ اول ثبت‌نام کن. 📜", show_alert=True)
    err = await _precheck(adoc, tdoc, int(g.get("stake", 0)), ignore=gid)
    if err:
        return await cq.answer(re.sub(r"<[^>]+>", "", err)[:190], show_alert=True)
    claimed = await store.rgames.find_one_and_update(
        {"_id": gid, "status": "wait", "t": None}, {"$set": {"status": "holding", "t": uid, "uids": [g["a"], uid]}},
        return_document=ReturnDocument.AFTER)
    if not claimed:
        return await cq.answer("یکی زودتر قبول کرد! ⌛", show_alert=True)
    await _go_live(cq, bot, claimed)


async def _go_live(cq, bot: Bot, g: dict):
    """بعد از قبولِ چالش: امانتِ شرط، شروعِ بازی."""
    gid = g["_id"]
    stake = int(g.get("stake", 0))
    if stake > 0:
        ok_a = await _hold(g["a"], gid, stake)
        ok_t = ok_a and await _hold(g["t"], gid, stake)
        if not (ok_a and ok_t):
            await _refund_all(g)
            await _claim(gid, "holding", "cancelled")
            await cq.answer("موجودیِ یکی از شما کم شده؛ بازی لغو شد. 🪙", show_alert=True)
            return await _edit(bot, g, panel("black", KINDS[g["kind"]][0], "لغو شد", ["موجودیِ کافی نبود؛ هیچ پولی کم نشد. 🪙"]))
    g = await _claim(gid, "holding", "live", upd=time.time(), started=time.time())
    await cq.answer("بازی شروع شد! 🎬")
    kind = g["kind"]
    spawn({"d": _run_dice, "q": _run_draw, "b": _run_bluff, "m": _run_bomb, "j": _run_21}[kind](bot, gid))


async def _decline(cq, bot: Bot, gid: ObjectId, uid: int):
    g = await store.rgames.find_one({"_id": gid})
    if not g or g["status"] != "wait":
        return await cq.answer("این چالش دیگه فعال نیست. ⌛", show_alert=True)
    if uid not in (g["a"], g["t"]):
        return await cq.answer("این چالش مالِ تو نیست. 😉", show_alert=True)
    g = await _claim(gid, "wait", "declined")
    if g:
        who = await store.get(uid)
        await cq.answer()
        await _edit(bot, g, panel("black", KINDS[g["kind"]][0], "چالش رد شد" if uid == g["t"] else "چالش پس گرفته شد",
                                  [f"{display(who)} " + ("جا زد! 🐔" if uid == g["t"] else "منصرف شد.")]))


# ───────────────────────────── 🎲 تاس ─────────────────────────────
async def _run_dice(bot: Bot, gid):
    g = await store.rgames.find_one({"_id": gid})
    try:
        ad, td = await store.get(g["a"]), await store.get(g["t"])
        emoji, mx = random.choice(DICE_SET)
        trail = []
        for rnd in range(DICE_REROLLS + 1):
            await _edit(bot, g, panel("orange", emoji, "تاس — بریز!", [
                f"{display(ad)} ⟷ {display(td)}", f"اولین {emoji} مالِ <b>{_nm(ad)}</b>، دومی مالِ <b>{_nm(td)}</b> 🎬"] + trail))
            ma = await bot.send_dice(g["chat_id"], emoji=emoji)
            mb = await bot.send_dice(g["chat_id"], emoji=emoji)
            va, vb = int(ma.dice.value), int(mb.dice.value)
            await asyncio.sleep(3.8)
            trail.append(f"{'🔁 ' if rnd else ''}{emoji} {_nm(ad)} <b>{va}</b> ⟷ <b>{vb}</b> {_nm(td)}")
            if va != vb:
                w = g["a"] if va > vb else g["t"]
                await _end(bot, gid, {}, w, res_lines=trail)
                return
            trail.append("⚖️ مساوی! دوباره می‌ریزیم…")
        await _end(bot, gid, {}, None, res_lines=trail[:-1] + ["⚖️ سه بار مساوی؛ سرنوشت نمی‌خواد کسی ببره!"])
    except Exception:
        log.exception("rg dice failed")
        await _abort(bot, gid)


# ───────────────────────────── 🔫 هفت‌تیر ─────────────────────────────
def _draw_kb(g_id, fire: bool):
    return kb([btn("🔫 شلیک!!", f"rg:sh:{g_id}", "red")] if fire else [btn("⏳ صبر کن…", f"rg:fs:{g_id}", "blue")])


async def _run_draw(bot: Bot, gid):
    try:
        g = await store.rgames.find_one({"_id": gid})
        ad, td = await store.get(g["a"]), await store.get(g["t"])
        await store.rgames.update_one({"_id": gid}, {"$set": {"phase": "ready"}})
        await _edit(bot, g, panel("orange", "🔫", "هفت‌تیر — آماده…", [
            f"{display(ad)} 🔫 {display(td)}", "🤠 دستتون روی دکمه‌ست… <b>تا «شلیک!» نیومده نزنین!</b>", "زودتر بزنی = فالت و باخت. 😈"]),
            _draw_kb(gid, False))
        await asyncio.sleep(random.uniform(DRAW_MIN_DELAY, DRAW_MAX_DELAY))
        fired = await store.rgames.find_one_and_update({"_id": gid, "status": "live", "phase": "ready"},
                                                        {"$set": {"phase": "fire", "fire_ts": time.time()}}, return_document=ReturnDocument.AFTER)
        if not fired:
            return                                        # فالت شده یا لغو
        await _edit(bot, g, panel("red", "💥", "شلیک!!!", [f"{display(ad)} 🔫 {display(td)}", "<b>همین الان بزن!</b> 🔥"]), _draw_kb(gid, True))
        await store.rgames.update_one({"_id": gid, "status": "live", "phase": "fire"}, {"$set": {"fire_ts": time.time()}})   # ساعتِ واکنش از لحظه‌ی دیده‌شدنِ دکمه
        await asyncio.sleep(DRAW_WINDOW)
        await _end(bot, gid, {"phase": "fire"}, None, res_lines=["😴 هیچ‌کس شلیک نکرد؛ هر دو خوابیدن!"])
    except Exception:
        log.exception("rg draw failed")
        await _abort(bot, gid)


async def _draw_press(cq, bot: Bot, gid: ObjectId, uid: int, early: bool):
    g = await store.rgames.find_one({"_id": gid})
    if not g or g["status"] != "live" or g["kind"] != "q":
        return await cq.answer("تموم شد. ⌛", show_alert=True)
    if uid not in (g["a"], g["t"]):
        return await cq.answer("تماشاچی‌ها دست نزنن! 👀", show_alert=True)
    other = g["t"] if uid == g["a"] else g["a"]
    if early:
        done = await _end(bot, gid, {"phase": "ready"}, other, res_lines=[
            f"🚨 <b>{_nm(await store.get(uid))}</b> قبل از «شلیک» دستش لرزید و فالت شد!", random.choice(
                ["دستِ لرزون، دلِ لرزون. 🫨", "اینجا صبر هم جزوِ مهارته! 🧘", "قبل از شلیک شلیک کرد؛ تیرِ خلاص به خودش! 🤦"])])
        return await cq.answer("فالت! زود زدی. 🚨" if done else "تموم شد. ⌛", show_alert=bool(done))
    fts = float(g.get("fire_ts") or 0)
    ms = max(1, int((time.time() - fts) * 1000)) if fts else 0
    lines = [f"⚡ <b>{_nm(await store.get(uid))}</b> تو <b>{ms}ms</b> شلیک کرد!"]
    if ms >= 100:
        rec = await store.users.find_one_and_update({"user_id": uid, "$or": [{"rg_best_ms": {"$exists": False}}, {"rg_best_ms": {"$gt": ms}}]},
                                                    {"$set": {"rg_best_ms": ms}})
        if rec is not None:
            lines.append(f"🏅 رکوردِ شخصیِ جدید: <b>{ms}ms</b>!")
    done = await _end(bot, gid, {"phase": "fire"}, uid, res_lines=lines, ms=ms)
    await cq.answer("🔥 زدی!" if done else "یکی زودتر زد. ⌛", show_alert=not done)


# ───────────────────────────── 🎭 بلوف ─────────────────────────────
def _bluff_roles(g: dict) -> tuple:
    """(کسی که می‌گه، کسی که قضاوت می‌کنه)"""
    return (g["a"], g["t"]) if int(g.get("r", 1)) % 2 == 1 else (g["t"], g["a"])


def _bluff_panel(g: dict, ad: dict, td: dict) -> tuple:
    claimer, judge = _bluff_roles(g)
    cn, jn = _nm(ad if claimer == g["a"] else td), _nm(ad if judge == g["a"] else td)
    sc = g.get("sc") or {}
    head = [f"{display(ad)} 🎭 {display(td)}", f"🏁 امتیاز: {_nm(ad)} <b>{int(sc.get(str(g['a']), 0))}</b> – <b>{int(sc.get(str(g['t']), 0))}</b> {_nm(td)}  (تا {BLUFF_WIN})  ·  راند {g.get('r', 1)}"]
    if g.get("hist"):
        head += ["┈┈┈┈┈┈┈┈┈┈"] + list(g["hist"])[-3:] + ["┈┈┈┈┈┈┈┈┈┈"]
    ph = g.get("phase")
    nums = lambda pre: [btn(str(i), f"rg:{pre}:{g['_id']}:{i}", "blue") for i in range(1, 7)]
    if ph == "pick":
        head.append(f"🤫 <b>{cn}</b>: یه عددِ مخفی انتخاب کن (فقط خودت می‌بینی).")
        return head, kb(nums("bp")[:3], nums("bp")[3:])
    if ph == "claim":
        head.append(f"🗣 <b>{cn}</b>: حالا بگو عددت چنده! (راست یا دروغ؟)")
        return head, kb(nums("bc")[:3], nums("bc")[3:])
    head.append(f"🗣 <b>{cn}</b> می‌گه عددش <b>{g.get('claim')}</b> ـه.\n🕵️ <b>{jn}</b>، باور می‌کنی؟")
    return head, kb([btn("✅ باور می‌کنم", f"rg:bj:{g['_id']}:y", "green"), btn("🕵️ دروغگو!", f"rg:bj:{g['_id']}:n", "red")])


async def _bluff_show(bot: Bot, g: dict):
    ad, td = await store.get(g["a"]), await store.get(g["t"])
    lines, markup = _bluff_panel(g, ad, td)
    await _edit(bot, g, panel("purple", "🎭", "بلوف", lines, _stake_line(int(g.get("stake", 0)))), markup)


async def _run_bluff(bot: Bot, gid):
    try:
        g = await store.rgames.find_one_and_update({"_id": gid}, {"$set": {
            "phase": "pick", "r": 1, "sc": {}, "hist": [], "upd": time.time()}}, return_document=ReturnDocument.AFTER)
        await _bluff_show(bot, g)
        while True:                                                 # نگهبانِ بیکاری
            await asyncio.sleep(12)
            g = await store.rgames.find_one({"_id": gid})
            if not g or g["status"] != "live":
                return
            if time.time() - float(g.get("upd", 0)) > BLUFF_IDLE:
                claimer, judge = _bluff_roles(g)
                idle = judge if g.get("phase") == "judge" else claimer
                other = g["t"] if idle == g["a"] else g["a"]
                await _end(bot, gid, {}, other, res_lines=[f"⌛ <b>{_nm(await store.get(idle))}</b> وقتی جواب نداد؛ باخت."])
                return
    except Exception:
        log.exception("rg bluff failed")
        await _abort(bot, gid)


async def _bluff_cb(cq, bot: Bot, act: str, gid: ObjectId, arg: str, uid: int):
    g = await store.rgames.find_one({"_id": gid})
    if not g or g["status"] != "live" or g["kind"] != "b":
        return await cq.answer("تموم شد. ⌛", show_alert=True)
    if uid not in (g["a"], g["t"]):
        return await cq.answer("تماشاچی‌ها ساکت! 🤫", show_alert=True)
    claimer, judge = _bluff_roles(g)
    now = time.time()
    if act == "bp":
        if uid != claimer or not arg.isdigit() or not 1 <= int(arg) <= 6:
            return await cq.answer("الان نوبتِ تو نیست. ⏳", show_alert=True)
        n = await store.rgames.find_one_and_update({"_id": gid, "status": "live", "phase": "pick"}, {"$set": {"secret": int(arg), "phase": "claim", "upd": now}},
                                                   return_document=ReturnDocument.AFTER)
        if not n:
            return await cq.answer("قبلاً انتخاب کردی. ✅", show_alert=True)
        await cq.answer(f"🤫 عددِ مخفیت {arg} ثبت شد؛ حالا بگو چی می‌گی.", show_alert=True)
        return await _bluff_show(bot, n)
    if act == "bc":
        if uid != claimer or not arg.isdigit() or not 1 <= int(arg) <= 6:
            return await cq.answer("الان نوبتِ تو نیست. ⏳", show_alert=True)
        n = await store.rgames.find_one_and_update({"_id": gid, "status": "live", "phase": "claim"}, {"$set": {"claim": int(arg), "phase": "judge", "upd": now}},
                                                   return_document=ReturnDocument.AFTER)
        if not n:
            return await cq.answer("قبلاً گفتی. ✅", show_alert=True)
        await cq.answer("گفتی! حالا حریف قضاوت می‌کنه. 🎭")
        return await _bluff_show(bot, n)
    if act == "bj":
        if uid != judge or arg not in ("y", "n"):
            return await cq.answer("الان نوبتِ تو نیست. ⏳", show_alert=True)
        g = await store.rgames.find_one_and_update({"_id": gid, "status": "live", "phase": "judge"}, {"$set": {"phase": "resolving"}}, return_document=ReturnDocument.AFTER)
        if not g:
            return await cq.answer("قبلاً قضاوت کردی. ✅", show_alert=True)
        truth = int(g["claim"]) == int(g["secret"])
        liar_call = arg == "n"
        pt = None                                                    # امتیازِ این راند
        if liar_call:
            pt, verdict = (claimer, "🕵️ اتهامِ ناحق! راست می‌گفت.") if truth else (judge, "🕵️ دروغگو گیر افتاد!")
        else:
            pt, verdict = (None, "🤝 راست می‌گفت و باور شد؛ امتیازی نیست.") if truth else (claimer, "🎭 خوب بلوف زد! گول خورد.")
        sc = dict(g.get("sc") or {})
        if pt:
            sc[str(pt)] = int(sc.get(str(pt), 0)) + 1
        cn, jn = _nm(await store.get(claimer)), _nm(await store.get(judge))
        hist = list(g.get("hist") or []) + [f"راند {g['r']}: {cn} گفت {g['claim']} (واقعی {g['secret']}) · {jn} {'گفت دروغگو' if liar_call else 'باور کرد'} → {verdict}"]
        winner = next((int(k) for k, v in sc.items() if int(v) >= BLUFF_WIN), None)
        r = int(g["r"])
        if winner or r >= BLUFF_MAX_ROUNDS:
            if not winner:
                a_s, t_s = int(sc.get(str(g["a"]), 0)), int(sc.get(str(g["t"]), 0))
                winner = g["a"] if a_s > t_s else g["t"] if t_s > a_s else None
            await store.rgames.update_one({"_id": gid}, {"$set": {"phase": "over", "sc": sc, "hist": hist}})
            await cq.answer(verdict, show_alert=True)
            return await _end(bot, gid, {"phase": "over"}, winner, res_lines=hist[-3:] + [f"🏁 {_nm(await store.get(g['a']))} {sc.get(str(g['a']), 0)} – {sc.get(str(g['t']), 0)} {_nm(await store.get(g['t']))}"])
        n = await store.rgames.find_one_and_update({"_id": gid}, {"$set": {"phase": "pick", "r": r + 1, "sc": sc, "hist": hist, "upd": now},
                                                                  "$unset": {"secret": "", "claim": ""}}, return_document=ReturnDocument.AFTER)
        await cq.answer(f"{verdict}  (عددِ واقعی {g['secret']})", show_alert=True)
        await _bluff_show(bot, n)
        return
    await cq.answer()


# ───────────────────────────── 💣 بمب ─────────────────────────────
def _bomb_kb(gid):
    return kb([btn("💣 پاس بده", f"rg:bm:{gid}:p", "blue"), btn("✂️ خنثی کن", f"rg:bm:{gid}:d", "red")])


def _defuse_p(c: int, f: int) -> float:
    """شانسِ خنثی‌سازی: هر چی فیتیله داغ‌تر (نزدیک‌تر به انفجار) بیشتر؛ بازیکن فقط «داغی» رو می‌بینه نه عددِ فیتیله رو."""
    return 0.15 + 0.7 * min(1.0, c / f if f else 0.0)


async def _bomb_show(bot: Bot, g: dict):
    ad, td = await store.get(g["a"]), await store.get(g["t"])
    holder = ad if g["holder"] == g["a"] else td
    c, f = int(g.get("c", 0)), int(g.get("f", BOMB_MAX))
    heat = c / f if f else 0
    ic = "🧊" if heat < .25 else "🌡" if heat < .5 else "🔥" if heat < .75 else "☄️"
    lines = [f"{display(ad)} 💣 {display(td)}"]
    if g.get("last"):
        lines.append(g["last"])
    lines += [f"{ic} داغیِ فیتیله: {_bar(c, f, 8)}  ·  پاس‌ها: <b>{c}</b>",
              f"💣 بمب دستِ <b>{_nm(holder)}</b> ـه! ⏳ {BOMB_IDLE} ثانیه وقت داره.", "┈┈┈┈┈┈┈┈┈┈",
              "💣 <b>پاس بده</b>: بمب میره سمتِ حریف (اگه فیتیله تموم شده باشه، تو دستِ خودت می‌ترکه!)",
              "✂️ <b>خنثی کن</b>: همه‌چی یا هیچی؛ هر چی فیتیله داغ‌تر، شانسِ موفقیتش بیشتر."]
    await _edit(bot, g, panel("red", "💣", "بمب — دست‌به‌دست", lines, _stake_line(int(g.get("stake", 0)))), _bomb_kb(g["_id"]))


async def _run_bomb(bot: Bot, gid):
    try:
        g = await store.rgames.find_one({"_id": gid})
        holder = random.choice([g["a"], g["t"]])
        g = await store.rgames.find_one_and_update({"_id": gid}, {"$set": {
            "f": random.randint(BOMB_MIN, BOMB_MAX), "c": 0, "holder": holder, "upd": time.time(),
            "last": f"🎲 قرعه افتاد: بمب اول دستِ <b>{_nm(await store.get(holder))}</b> ـه!"}}, return_document=ReturnDocument.AFTER)
        await _bomb_show(bot, g)
        while True:                                                 # نگهبانِ بیکاری
            await asyncio.sleep(2)
            g = await store.rgames.find_one({"_id": gid})
            if not g or g["status"] != "live":
                return
            if time.time() - float(g.get("upd", 0)) > BOMB_IDLE:
                idle = g["holder"]
                other = g["t"] if idle == g["a"] else g["a"]
                await _end(bot, gid, {"holder": idle, "c": int(g.get("c", 0))}, other, res_lines=[
                    f"💤 <b>{_nm(await store.get(idle))}</b> خشکش زد و بمب تو دستش ترکید! 💥"])
                return
    except Exception:
        log.exception("rg bomb failed")
        await _abort(bot, gid)


async def _bomb_cb(cq, bot: Bot, gid: ObjectId, arg: str, uid: int):
    g = await store.rgames.find_one({"_id": gid})
    if not g or g["status"] != "live" or g["kind"] != "m":
        return await cq.answer("تموم شد. ⌛", show_alert=True)
    if uid not in (g["a"], g["t"]):
        return await cq.answer("تماشاچی‌ها دور بایستن! 💣", show_alert=True)
    if g.get("holder") != uid:
        return await cq.answer("بمب دستِ تو نیست! ⏳", show_alert=True)
    other = g["t"] if uid == g["a"] else g["a"]
    c, f = int(g.get("c", 0)), int(g.get("f", BOMB_MAX))
    me = _nm(await store.get(uid))
    if arg == "p":
        if c + 1 >= f:
            done = await _end(bot, gid, {"holder": uid, "c": c}, other, res_lines=[
                f"💥 فیتیله تموم بود! بمب تو دستِ <b>{me}</b> ترکید (فیتیله {f} پاسی بود)."])
            return await cq.answer("💥 ترکید!" if done else "تموم شد. ⌛", show_alert=bool(done))
        n = await store.rgames.find_one_and_update(
            {"_id": gid, "status": "live", "holder": uid, "c": c},
            {"$set": {"c": c + 1, "holder": other, "upd": time.time(), "last": f"💨 <b>{me}</b> بمب رو پاس داد!"}}, return_document=ReturnDocument.AFTER)
        if not n:
            return await cq.answer("تموم شد. ⌛", show_alert=True)
        await cq.answer("پاس دادی! 💨")
        return await _bomb_show(bot, n)
    if arg == "d":
        ok = random.random() < _defuse_p(c, f)
        win = uid if ok else other
        done = await _end(bot, gid, {"holder": uid, "c": c}, win, res_lines=[
            f"✂️ <b>{me}</b> سیمِ درست رو برید و بمب رو خنثی کرد! 😎" if ok
            else f"💥 <b>{me}</b> سیمِ اشتباه رو برید و بمب منفجر شد! (فیتیله {f} پاسی بود)"])
        return await cq.answer(("✂️ خنثی شد! 😎" if ok else "💥 سیمِ اشتباه!") if done else "تموم شد. ⌛", show_alert=bool(done))
    await cq.answer()


# ───────────────────────────── 🃏 بیست‌ویک ─────────────────────────────
def _bj_kb(gid):
    return kb([btn("🃏 کارت", f"rg:cd:{gid}:h", "green"), btn("✋ بس", f"rg:cd:{gid}:s", "red")])


async def _bj_show(bot: Bot, g: dict):
    ad, td = await store.get(g["a"]), await store.get(g["t"])
    tot, std = g["tot"], g["std"]
    row = lambda d: f"{_nm(d)}: <b>{tot[str(d['user_id'])]}</b>" + (" ✋" if std[str(d['user_id'])] else "")
    turn_d, opp_d = (ad, td) if g["turn"] == g["a"] else (td, ad)
    lines = [f"{display(ad)} 🃏 {display(td)}", f"{row(ad)}   ⟷   {row(td)}"]
    if g.get("last"):
        lines.append(g["last"])
    if std[str(opp_d["user_id"])]:
        lines.append(f"⚠️ {_nm(opp_d)} روی <b>{tot[str(opp_d['user_id'])]}</b> ایستاده؛ باید ازش بالاتر بری (و از {BJ_TARGET} رد نشی)!")
    lines.append(f"🎯 نوبتِ <b>{_nm(turn_d)}</b> · ⏳ {BJ_IDLE} ثانیه")
    await _edit(bot, g, panel("green", "🃏", f"بیست‌ویک — نزدیک‌تر به {BJ_TARGET}", lines, _stake_line(int(g.get("stake", 0)))), _bj_kb(g["_id"]))


async def _run_21(bot: Bot, gid):
    try:
        g = await store.rgames.find_one({"_id": gid})
        a, t = g["a"], g["t"]
        card = lambda: random.randint(1, 10)
        g = await store.rgames.find_one_and_update({"_id": gid}, {"$set": {
            "tot": {str(a): card() + card(), str(t): card() + card()}, "std": {str(a): False, str(t): False},
            "turn": random.choice([a, t]), "mv": 0, "upd": time.time(), "last": "🃏 هر کس دو کارت گرفت!"}}, return_document=ReturnDocument.AFTER)
        await _bj_show(bot, g)
        while True:                                                 # نگهبانِ بیکاری
            await asyncio.sleep(3)
            g = await store.rgames.find_one({"_id": gid})
            if not g or g["status"] != "live":
                return
            if time.time() - float(g.get("upd", 0)) > BJ_IDLE:
                idle = g["turn"]
                other = g["t"] if idle == g["a"] else g["a"]
                await _end(bot, gid, {"turn": idle, "mv": int(g.get("mv", 0))}, other, res_lines=[
                    f"⌛ <b>{_nm(await store.get(idle))}</b> وقتی جواب نداد؛ باخت."])
                return
    except Exception:
        log.exception("rg 21 failed")
        await _abort(bot, gid)


async def _21_cb(cq, bot: Bot, gid: ObjectId, arg: str, uid: int):
    g = await store.rgames.find_one({"_id": gid})
    if not g or g["status"] != "live" or g["kind"] != "j" or not g.get("tot"):
        return await cq.answer("تموم شد. ⌛", show_alert=True)
    if uid not in (g["a"], g["t"]):
        return await cq.answer("تماشاچی‌ها کارت نمی‌کشن! 🃏", show_alert=True)
    if g.get("turn") != uid:
        return await cq.answer("الان نوبتِ تو نیست. ⏳", show_alert=True)
    if arg not in ("h", "s"):
        return await cq.answer()
    a, t = g["a"], g["t"]
    other = t if uid == a else a
    mv = int(g.get("mv", 0))
    tot, std = dict(g["tot"]), dict(g["std"])
    me = _nm(await store.get(uid))
    flt = {"turn": uid, "mv": mv}
    if arg == "h":
        card = random.randint(1, 10)
        tot[str(uid)] = int(tot[str(uid)]) + card
        if tot[str(uid)] > BJ_TARGET:
            done = await _end(bot, gid, flt, other, tot=tot, res_lines=[f"🃏 <b>{me}</b> کارتِ {card} کشید و شد <b>{tot[str(uid)]}</b> — سوخت! 💥"])
            return await cq.answer("💥 سوختی!" if done else "تموم شد. ⌛", show_alert=bool(done))
        last = f"🃏 <b>{me}</b> کارتِ <b>{card}</b> کشید."
        if tot[str(uid)] == BJ_TARGET:
            std[str(uid)] = True
            last += f" {BJ_TARGET}! خودکار «بس» شد. 🎯"
    else:
        std[str(uid)] = True
        last = f"✋ <b>{me}</b> «بس» گفت."
    if std[str(uid)] and std[str(other)]:
        ta, tt = int(tot[str(a)]), int(tot[str(t)])
        w = a if ta > tt else t if tt > ta else None
        done = await _end(bot, gid, flt, w, tot=tot, res_lines=[last, f"🃏 {_nm(await store.get(a))} <b>{ta}</b> ⟷ <b>{tt}</b> {_nm(await store.get(t))}"])
        return await cq.answer("تموم شد! 🎬" if done else "تموم شد. ⌛", show_alert=not done)
    nxt = other if not std[str(other)] else uid
    n = await store.rgames.find_one_and_update(
        {"_id": gid, "status": "live", **flt},
        {"$set": {"tot": tot, "std": std, "turn": nxt, "mv": mv + 1, "upd": time.time(), "last": last}}, return_document=ReturnDocument.AFTER)
    if not n:
        return await cq.answer("تموم شد. ⌛", show_alert=True)
    await cq.answer(f"{tot[str(uid)]} 🃏" if arg == "h" else "✋ بس!")
    await _bj_show(bot, n)


# ───────────────────────────── 🧯 لغو/ریکاوری ─────────────────────────────
async def _abort(bot: Bot, gid):
    """خطای غیرمنتظره: بازی بسته میشه و همه‌ی پول‌ها برمی‌گردن."""
    try:
        g = await store.rgames.find_one_and_update({"_id": gid, "status": {"$in": ["live", "holding"]}},
                                                    {"$set": {"status": "settling", "winner": None}}, return_document=ReturnDocument.AFTER)
        if g:
            await _payout(g)
            await _edit(bot, g, panel("black", KINDS[g["kind"]][0], "بازی لغو شد", ["یه مشکلِ فنی پیش اومد؛ شرط‌ها کامل برگشت. 🛠"]))
    except Exception:
        log.exception("rg abort failed")


async def recover_rg(bot: Bot):
    """بعد از ری‌استارت: بازی‌های نیمه‌کاره (تسک‌هاشون مُردن) با بازگشتِ کاملِ پول بسته میشن؛ پرداخت‌های نیمه‌تموم کامل میشن."""
    try:
        async for g in store.rgames.find({"status": "settling"}):
            await _payout(g)
        async for g in store.rgames.find({"status": {"$in": ["wait", "holding", "live"]}}):
            g2 = await store.rgames.find_one_and_update({"_id": g["_id"], "status": g["status"]}, {"$set": {"status": "settling", "winner": None}},
                                                         return_document=ReturnDocument.AFTER)
            if g2:
                await _payout(g2)
                await _edit(bot, g2, panel("black", KINDS[g2["kind"]][0], "بازی لغو شد", ["ربات ری‌استارت شد؛ بازی بسته و شرط‌ها کامل برگشت. 🔄"]))
        async for u in store.users.find({"rg_hold": {"$exists": True, "$ne": {}}}, {"user_id": 1, "rg_hold": 1}):    # مارکرِ یتیم
            for gid_s, amt in (u.get("rg_hold") or {}).items():
                try:
                    gg = await store.rgames.find_one({"_id": ObjectId(gid_s)})
                except Exception:
                    gg = None
                if gg and gg.get("status") == "done":
                    await _release(u["user_id"], gid_s, 0)
                elif not gg or gg.get("status") in ("expired", "cancelled", "declined"):
                    await _release(u["user_id"], gid_s, int(amt))
    except Exception:
        log.exception("recover_rg failed")


# ───────────────────────────── 🎭 پنلِ باشگاه و جدولِ سرعت ─────────────────────────────
async def do_club(m):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc:
        return
    now = time.time()
    n = int(doc.get("rg_n", 0)) if doc.get("rg_day") == day_key() else 0
    claimed = set(doc.get("rg_claim") or []) if doc.get("rg_day") == day_key() else set()
    nxt = next((th for th in sorted(CHEST) if th not in claimed), None)
    chest = "  ".join(f"{'✅' if th in claimed else '🎁'}{th}" for th in sorted(CHEST))
    st = doc.get("rg_st") or {}
    games = []
    for k, (ic, nm) in KINDS.items():
        s = st.get(k) or {}
        games.append(f"{ic} {nm}: {int(s.get('w', 0))}–{int(s.get('l', 0))}")
    mast = []
    for code, (ic, nm) in MAST_NAMES.items():
        c = mast_count(doc, code)
        lv = mast_level(c)
        mast.append(f"{ic} {_bar(min(lv, 4), 4, 4)} {lv}" + (f" ({c}/{MAST_LEVELS[lv]})" if lv < 4 else " ⭐"))
    lines = [
        hype_line(doc),
        f"🎯 امروز: <b>{n}</b> برخوردِ ریپلایی · صندوق‌ها: {chest}" + (f"  (بعدی: {nxt - n} برخورد دیگه)" if nxt and nxt > n else ""),
        f"📆 روزهای پشت‌سرهم: <b>{int(doc.get('rg_dstreak', 0)) if doc.get('rg_day') in (day_key(), (ir_now() - timedelta(days=1)).strftime('%Y-%m-%d')) else 0}</b>"
        f"  ·  🔥 زنجیره‌ی بردِ باشگاه: <b>{int(doc.get('rg_ws', 0))}</b> (رکورد {int(doc.get('rg_ws_best', 0))})",
        "┈┈┈┈┈┈┈┈┈┈", "  |  ".join(games),
        f"⚡ سریع‌ترین شلیک: <b>{int(doc['rg_best_ms'])}ms</b>" if doc.get("rg_best_ms") else "⚡ هنوز شلیکی نزدی؛ «هفت تیر» رو امتحان کن!",
        "┈┈┈┈┈┈┈┈┈┈", "🎖 تسلطِ ژست‌ها:", "   ".join(mast[:3]), "   ".join(mast[3:]),
    ]
    if wounded(doc, now):
        lines += ["┈┈┈┈┈┈┈┈┈┈", f"🩸 زخمی‌ای! ({int(float(doc['rg_wound_until']) - now) // 60 + 1} دقیقه‌ی دیگه) — یه دوست «ترمیم» کنه پاک میشه."]
    helps = ["┈┈┈┈┈┈┈┈┈┈", "با «ریپلای» روی یه بازیکن:", "🎲 <b>تاس</b> · 🔫 <b>هفت تیر</b> · 🎭 <b>بازی بلوف</b> · 💣 <b>بمب بازی</b> · 🃏 <b>بیست و یک</b>  (+ مبلغِ اختیاری)",
             "🌍 بدونِ ریپلای، چالشِ باز: <b>تاس باز</b> · <b>بمب بازی باز 30</b> …",
             "⚔️ <b>حمله</b> · 🥋 <b>تمرین</b> · 🩹 <b>ترمیم</b> · «سریع ترین ها»"]
    await m.reply(panel("purple", "🎭", "باشگاهِ ریپلای", lines + helps, "💅 <i>«هر چی بیشتر بازی کنی، بیشتر بهت می‌چسبم.»</i>"),
                  reply_markup=kb([btn("🏟 میدان", "sk:ar:0", "blue"), btn("⚡ سریع‌ترین‌ها", "rg:lb", "green")]))


async def do_fastest(m):
    rows = await store.users.find({"rg_best_ms": {"$gt": 0}}).sort("rg_best_ms", 1).limit(10).to_list(10)
    if not rows:
        return await say(m, "هنوز کسی شلیک نزده! «هفت تیر» رو با ریپلای شروع کنین. 🔫", "⚡", "سریع‌ترین‌ها", "blue")
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    await m.reply(panel("orange", "⚡", "سریع‌ترین دست‌های ایسکا", [
        f"{medals[i]} {display(d)} — <b>{int(d['rg_best_ms'])}ms</b>" for i, d in enumerate(rows)], "رکوردت رو بشکن: «هفت تیر» + ریپلای 🔫"))


# ───────────────────────────── 🚪 ورودیِ متن و دکمه ─────────────────────────────
async def handle(m, bot: Bot) -> bool:
    """True = پیام مالِ باشگاه بود. (بازی‌ها فقط تو گروه و با ریپلای.)"""
    t = _n(m.text or "")
    if CLUB_RE.fullmatch(t):
        await do_club(m)
        return True
    if FAST_RE.fullmatch(t):
        await do_fastest(m)
        return True
    mo = OPEN_RE.fullmatch(t)
    if mo:                                                  # 🌍 چالشِ باز (بدونِ ریپلای)
        kind = _open_kind(mo.group(1))
        if not kind:
            return False
        if not is_group(m):
            await say(m, "چالشِ باز فقط تو گروه کار می‌کنه؛ اونجا یه حریف پیدا میشه. 👥", "🎭", "باشگاه", "orange")
            return True
        adoc = await store.get(m.from_user.id)
        if adoc:
            await _open_public(m, bot, kind, adoc, int(mo.group(2) or 0))
        return True
    kind, rx = next(((k, r) for k, r in _BY_KIND if r.fullmatch(t)), (None, None))
    if not kind or not m.reply_to_message:
        return False
    if not is_group(m):
        await say(m, "بازی‌های باشگاه فقط تو گروه و با ریپلای روی پیامِ یه بازیکنه. 👥", "🎭", "باشگاه", "orange")
        return True
    from skirmish import _target
    tdoc, err = await _target(m)
    if err or not tdoc:
        await say(m, err or "هدف پیدا نشد.", "🎭", "باشگاه", "orange")
        return True
    adoc = await store.get(m.from_user.id)
    if not adoc:
        return True
    stake = int(rx.fullmatch(t).group(1) or 0)
    await _open(m, bot, kind, adoc, tdoc, stake)
    return True


async def rg_cb(cq, bot: Bot, parts: list):
    """rg:ac:<id> · rg:no:<id> · rg:fs|sh:<id> · rg:bp|bc:<id>:<n> · rg:bj:<id>:<y|n> · rg:bm:<id>:<p|d> · rg:cd:<id>:<h|s> · rg:rm:<k>:<a>:<t>:<stake> · rg:ci · rg:lb"""
    uid = cq.from_user.id
    try:
        act = parts[1]
        if act == "ac" and len(parts) >= 3:
            await _accept(cq, bot, ObjectId(parts[2]), uid)
        elif act == "no" and len(parts) >= 3:
            await _decline(cq, bot, ObjectId(parts[2]), uid)
        elif act in ("fs", "sh") and len(parts) >= 3:
            await _draw_press(cq, bot, ObjectId(parts[2]), uid, early=(act == "fs"))
        elif act in ("bp", "bc", "bj") and len(parts) >= 4:
            await _bluff_cb(cq, bot, act, ObjectId(parts[2]), parts[3], uid)
        elif act == "bm" and len(parts) >= 4:
            await _bomb_cb(cq, bot, ObjectId(parts[2]), parts[3], uid)
        elif act == "cd" and len(parts) >= 4:
            await _21_cb(cq, bot, ObjectId(parts[2]), parts[3], uid)
        elif act == "rm" and len(parts) >= 6:
            await _rematch(cq, bot, parts[2], int(parts[3]), int(parts[4]), int(parts[5]), uid)
        elif act == "ci":
            from ui import CbMsg
            await cq.answer()
            await do_club(CbMsg(cq, bot))
        elif act == "lb":
            from ui import CbMsg
            await cq.answer()
            await do_fastest(CbMsg(cq, bot))
        else:
            await cq.answer()
    except Exception:
        log.exception("rg callback failed")
        try:
            await cq.answer("یه مشکل کوچیک پیش اومد. دوباره امتحان کن. 🛠", show_alert=True)
        except Exception:
            pass


async def _rematch(cq, bot: Bot, kind: str, a: int, t: int, stake: int, uid: int):
    """ریمچ: کسی که دکمه رو می‌زنه چالش‌دهنده‌ی جدیده و طرفِ مقابل همون حریفِ قبلیه."""
    if kind not in KINDS or uid not in (a, t):
        return await cq.answer("این بازی مالِ تو نبود. 😉", show_alert=True)
    opp = t if uid == a else a
    adoc, tdoc = await store.get(uid), await store.get(opp)
    if not adoc or not tdoc:
        return await cq.answer("بازیکن پیدا نشد.", show_alert=True)
    err = await _precheck(adoc, tdoc, stake)
    if err:
        return await cq.answer(re.sub(r"<[^>]+>", "", err)[:190], show_alert=True)
    await cq.answer("ریمچ! 🔁")
    from ui import CbMsg
    await _open(CbMsg(cq, bot), bot, kind, adoc, tdoc, stake)


async def after_clash(bot: Bot, clash: dict, winner: Optional[str]):
    """بعد از هر حمله/تمرین: تب بالا میره و به حسابِ صندوقِ روزانه اضافه میشه."""
    try:
        if clash.get("kind") not in ("attack", "spar"):
            return
        for uid in clash.get("uids", []):
            won = (winner == "a" and uid == clash["a"]) or (winner == "d" and uid == clash["t"])
            await hype_add(uid, 14 if won else 9)
            await club_bump(bot, clash["chat_id"], uid)
    except Exception:
        log.exception("rg after_clash failed")
