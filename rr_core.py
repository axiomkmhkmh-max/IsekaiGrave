"""🎭 Reply-RPG — قوانینِ خالص (بدونِ تلگرام/دیتابیس) + ریجکس‌ها؛ قابل‌تست و بدونِ اثر جانبی.

همه‌ی کنش‌های Reply-RPG با «ریپلای» انجام میشن؛ این فایل فقط تشخیصِ کلمه‌ها و فرمول‌هاست.
"""

import random
import re
from typing import Optional

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_VS = re.compile(r"[\ufe0f\u200d]")


def tok(raw: str) -> str:
    """متنِ کوتاهِ پیام → توکنِ نرمال‌شده (ارقام انگلیسی، بدونِ variation-selector ایموجی، بدونِ علائم)."""
    from utils import clean, norm
    t = _VS.sub("", (raw or "").translate(_DIGITS))
    return clean(norm(t))


# ───────────────────────────── 🔤 کلمه‌های کنش ─────────────────────────────
HIT_RE = re.compile(r"(?:حمله|بزن|ضربه|حمله میکنم|حمله کن|⚔|🗡|💥)")
COVER_RE = re.compile(r"(?:پوشش|پوشش میدم|دفاع|سپر|سپر میشم|🛡)")
COUNTER_RE = re.compile(r"(?:پاتک|ضد ?حمله|جاخالی|🔄|⚡)")
OPEN_RE = re.compile(r"(?:باز کردن|باز|باز کن|بازش کن|🗝|📦|🎁)")
PRAY_RE = re.compile(r"(?:دعا|دعا میکنم|🙏)")
DISPEL_RE = re.compile(r"(?:رفع طلسم|دفع طلسم|طلسم شکن|طلسمشکن|🕯)")
BUYOUT_RE = re.compile(r"(?:بازخرید|بازخرید طلسم)")
CAST_RE = re.compile(r"(?:طلسم|طلسمش کن|طلسمش میکنم)(?: (\S+))?")
DUEL_START_RE = re.compile(r"(?:دوئل|دوعل|دوئل با|دوعل با|دوئل خیابانی|دوئل خیابونی|کری|کری میخونم|کری بخون)")
ACCEPT_RE = re.compile(r"(?:قبول|قبول میکنم|بیا|بزن بریم|بریم|قبول دوئل|دوئل قبول)")
DECLINE_RE = re.compile(r"(?:رد|نه|نمیخوام|رد میکنم|ترسیدم)")
REMATCH_RE = re.compile(r"(?:ریمچ|دوباره|انتقام|یه دست دیگه)")
SUMMON_RE = re.compile(r"(?:احضار هیولا|هیولا بیار|هیولا بخون)")
DUNGEON_RE = re.compile(r"(?:سیاه ?چال|سیاه ?چاله|دانجن|راه دو شاخه|ماجرای کوتاه)(?: کوچک| کوچیک)?")
STREAK_RE = re.compile(r"(?:پشتکار|پشتکار من|استریک ریپلای)")
HELP_RE = re.compile(r"(?:راهنمای ریپلای|راهنمای ریپلای ها|ریپلای رپگ)")
CHOICE_RE = re.compile(r"[12]")

MOVES = {"sword": "⚔️ شمشیر", "magic": "🔮 جادو", "shield": "🛡 سپر"}
_MOVE_ALIASES = {
    "sword": ("شمشیر", "تیغ", "⚔", "🗡"),
    "magic": ("جادو", "سحر", "🔮", "✨"),
    "shield": ("سپر", "دفاع", "🛡"),
}
BEATS = {"sword": "magic", "magic": "shield", "shield": "sword"}   # شمشیر جادوگر رو می‌بُره · جادو سپر رو سوراخ می‌کنه · سپر شمشیر رو می‌گیره

CURSE_ALIASES = {
    "frog": ("قورباغه", "قورباغه ای", "قورباغه‌ای", "غوک", "🐸"),
    "fire": ("آتش", "اتش", "سوزان", "🔥"),
    "pocket": ("جیب", "جیب سوراخ", "جیبسوراخ", "سوراخ", "🪙"),
    "clown": ("دلقک", "مسخره", "🤡"),
}


_NORM_CACHE: dict = {}


def _norm_map(name: str, table: dict) -> dict:
    """نام‌های مستعار رو یک‌بار با همون نرمال‌سازیِ پیام (حذف نیم‌فاصله و …) آماده می‌کنه."""
    m = _NORM_CACHE.get(name)
    if m is None:
        m = _NORM_CACHE[name] = {tok(a): k for k, al in table.items() for a in al}
    return m


def parse_move(t: str) -> Optional[str]:
    return _norm_map("moves", _MOVE_ALIASES).get(t)


def parse_curse_type(arg: Optional[str]) -> Optional[str]:
    """None = نوعِ تصادفی؛ '' = اسمِ ناشناخته."""
    if not arg:
        return None
    return _norm_map("curses", CURSE_ALIASES).get(tok(arg), "")


def parse_choice(t: str) -> Optional[int]:
    return int(t) if CHOICE_RE.fullmatch(t) else None


def matches(raw: str, has_reply: bool, to_bot: bool = False) -> bool:
    """آیا متن یه کنشِ Reply-RPG به نظر میاد؟ (فقط برای گیتِ ثبت‌نام).
    کلمه‌های روی پیامِ ربات (۱/۲، حمله، پاتک، باز کردن…) فقط وقتی ریپلای به ربات باشه؛ «دوئل/طلسم/رفع طلسم» روی هر ریپلای."""
    t = tok(raw)
    if not t:
        return False
    if to_bot and (CHOICE_RE.fullmatch(t) or HIT_RE.fullmatch(t) or COVER_RE.fullmatch(t) or COUNTER_RE.fullmatch(t)
                   or OPEN_RE.fullmatch(t) or PRAY_RE.fullmatch(t) or ACCEPT_RE.fullmatch(t) or REMATCH_RE.fullmatch(t)
                   or parse_move(t)):
        return True
    if has_reply and (DUEL_START_RE.fullmatch(t) or CAST_RE.fullmatch(t) or DISPEL_RE.fullmatch(t) or BUYOUT_RE.fullmatch(t)):
        return True
    return bool(SUMMON_RE.fullmatch(t) or DUNGEON_RE.fullmatch(t) or HELP_RE.fullmatch(t) or STREAK_RE.fullmatch(t))


# ───────────────────────────── ⚔️ زنجیره‌ی حمله ─────────────────────────────
HIT_CD = 3.5            # ثانیه؛ ضدِ اسپم
CHAIN_WINDOW = 12.0     # فاصله‌ی مجازِ دو ضربه‌ی «دو نفرِ متفاوت» برای ادامه‌ی زنجیره
STRIKE_WINDOW = 14      # مهلتِ واکنش به پاتکِ هیولا (ثانیه)
CHAIN_MAX_MULT = 2.0


def chain_mult(chain: int) -> float:
    """هر حلقه‌ی زنجیره +۱۰٪؛ سقف ×۲."""
    return min(CHAIN_MAX_MULT, 1.0 + 0.1 * max(0, chain - 1))


def hit_damage(level: int, cls: Optional[str], chain: int, rng=random) -> tuple:
    """(دمیج، کریتیکال؟) — کلاس جنگجو کمی بیشتر؛ ضربه‌ی تصادفی ±۲۰٪."""
    base = 28 + 3 * max(1, min(int(level), 40))
    if cls == "warrior":
        base = int(base * 1.15)
    base = base * rng.uniform(0.8, 1.2)
    crit = rng.random() < 0.1
    if crit:
        base *= 1.8
    return max(5, int(base * chain_mult(chain))), crit


def parry_damage(level: int, react_s: float, window: float = STRIKE_WINDOW) -> int:
    """پاتکِ سرعتی: هرچه سریع‌تر، دمیجِ بیشتر (۱٫۵× تا ۴×)."""
    frac = max(0.0, min(1.0, 1.0 - react_s / max(1.0, window)))
    base = 28 + 3 * max(1, min(int(level), 40))
    return int(base * (1.5 + 2.5 * frac))


def strike_after_cover(dmg: int, n_cover: int) -> int:
    """هر پوشش‌دهنده ۳۰٪ از ضربه رو می‌گیره؛ حداقل ۱۰٪ می‌مونه."""
    return max(1, int(round(dmg * max(0.1, 1.0 - 0.3 * n_cover))))


def split_loot(pool: int, scores: dict, last_hitter=None, last_bonus: float = 0.15, floor: int = 4) -> dict:
    """تقسیمِ پات بینِ مشارکت‌کننده‌ها بر اساسِ امتیاز؛ مجموعِ خروجی دقیقاً ≤ pool.
    ضربه‌ی آخر ۱۵٪ پاتِ جدا می‌گیره؛ هر نفرِ فعال حداقل «floor» (اگه پات بکشه)."""
    pool = max(0, int(pool))
    scores = {k: max(0, v) for k, v in scores.items() if v > 0}
    if not scores or pool <= 0:
        return {}
    out = {k: 0 for k in scores}
    bonus = 0
    if last_hitter in out:
        bonus = int(pool * last_bonus)
        out[last_hitter] += bonus
    rest = pool - bonus
    mins = min(floor, rest // len(scores))
    for k in out:
        out[k] += mins
    rest -= mins * len(scores)
    tot = sum(scores.values())
    used = 0
    for k, v in sorted(scores.items(), key=lambda kv: -kv[1]):
        share = int(rest * v / tot)
        out[k] += share
        used += share
    if used < rest:                       # باقی‌مانده‌ی گردکردن به نفرِ اول
        top = max(scores, key=scores.get)
        out[top] += rest - used
    return out


# ───────────────────────────── 🥊 دوئلِ خیابانی ─────────────────────────────
def duel_odds(ma: Optional[str], mb: Optional[str], la: int, lb: int, ta: float = 0.0, tb: float = 0.0) -> tuple:
    """(احتمالِ بردِ A به درصد، برنده‌ی مثلث: 'a'|'b'|None). مثلث ±۲۲، اختلافِ سطح ±۱۰، تساوی→سرعت ±۶."""
    p = 50 + max(-10, min(10, (int(la) - int(lb)) * 2))
    tri = None
    if ma and mb:
        if BEATS[ma] == mb:
            tri, p = "a", p + 22
        elif BEATS[mb] == ma:
            tri, p = "b", p - 22
        else:
            p += 6 if ta < tb else (-6 if tb < ta else 0)
    return max(12, min(88, p)), tri


def duel_roll(ma, mb, la, lb, ta=0.0, tb=0.0, rng=random) -> dict:
    p, tri = duel_odds(ma, mb, la, lb, ta, tb)
    win = "a" if rng.random() * 100 < p else "b"
    return {"p": p, "tri": tri, "winner": win, "upset": bool(tri and tri != win), "crit": rng.random() < 0.12}


def duel_stake(loser_gold: int, winner_level: int) -> int:
    """GS که از بازنده به برنده میره: ۸٪ موجودیِ بازنده، سقف ۲۰+۴×سطحِ برنده (حداکثر ۶۰)، حداقل ۵؛ زیرِ ۵ GS = صفر."""
    g = int(loser_gold)
    if g < 5:
        return 0
    cap = min(60, 20 + 4 * max(1, int(winner_level)))
    return max(5, min(cap, int(g * 0.08), g))


# ───────────────────────────── 🎁 کمین ─────────────────────────────
RANK_SHARE = {1: 1.0, 2: 0.5, 3: 0.25}


def rank_share(rank: int) -> float:
    return RANK_SHARE.get(rank, 0.0)


# ───────────────────────────── 🧭 سیاه‌چالِ کوچک ─────────────────────────────
def tally(votes: dict, rng=random) -> int:
    """votes: {uid: 1|2} → گزینه‌ی برنده (تساوی/بدونِ رأی: تصادفی)."""
    c1 = sum(1 for v in votes.values() if v == 1)
    c2 = sum(1 for v in votes.values() if v == 2)
    if c1 == c2:
        return rng.choice((1, 2))
    return 1 if c1 > c2 else 2


def bar(v: float, mx: float, w: int = 10) -> str:
    n = max(0, min(w, round(w * max(v, 0) / mx))) if mx else 0
    return "▰" * n + "▱" * (w - n)
