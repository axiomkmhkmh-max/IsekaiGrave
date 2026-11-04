"""قوانین خالصِ بازی (بدون وابستگی به تلگرام/دیتابیس): آیتم‌ها، سقف درآمد GS، کارمزد، ارتقا.
همه‌ی توابع اینجا خالص‌ان تا راحت تست بشن."""

import re
import zlib
from typing import Optional

# ───────────────────────────── 💎 کمیابی آیتم‌ها ─────────────────────────────
# (نام، ایموجی رنگی، وزن دراپ، ارزش پایه به GS)
RARITIES = [
    ("معمولی", "🪵", 50, 5),
    ("غیرمعمول", "🍀", 25, 12),
    ("نادر", "💎", 14, 30),
    ("حماسی", "🔮", 7, 70),
    ("افسانه‌ای", "👑", 3, 150),
    ("نفرین‌شده", "💀", 1, 0),
]
CURSED_IDX = 5
RARITY_NAMES = [r[0] for r in RARITIES]

# برچسب‌های ویژه که مثل یه کمیابی رفتار می‌کنن (برای تجهیز/ادغام/ارزش)
TAG_ALIAS = {"غنیمت باس": 4, "پیمان‌دار": 4}
# برچسب‌هایی که آیتم رو «روح‌پیوند» می‌کنن: غیرقابل فروش و معامله
SOULBOUND_TAGS = {"نفرین‌شده", "پیمان‌دار"}
SOULBOUND_MARK = "🔗"
UNKNOWN_TAG_VALUE = 10     # آیتم‌های مشکوکِ NPC و …
NO_TAG_VALUE = 8

_TAG_RE = re.compile(r"‹([^›]+)›")
_STAR_RE = re.compile(r"\s*★(\d+)\s*$")

STAR = "★"
MAX_STARS = 4
GEAR_BASE = [1, 2, 4, 6, 8]     # بونوس حمله‌ی تجهیز به‌ازای کمیابی (۰..۴)
GEAR_PER_STAR = 1
GEAR_CAP = 12                    # سقفِ بونوس تجهیز؛ پول نمی‌تونه از اینجا بیشتر قدرت بخره


def item_tag(item: str) -> Optional[str]:
    found = _TAG_RE.findall(item or "")
    return found[-1] if found else None


def item_stars(item: str) -> int:
    m = _STAR_RE.search(item or "")
    return int(m.group(1)) if m else 0


def strip_stars(item: str) -> str:
    return _STAR_RE.sub("", item or "")


def with_stars(item: str, n: int) -> str:
    base = strip_stars(item)
    return f"{base} {STAR}{n}" if n > 0 else base


def rarity_idx(item: str) -> Optional[int]:
    tag = item_tag(item)
    if tag is None:
        return None
    if tag in TAG_ALIAS:
        return TAG_ALIAS[tag]
    return RARITY_NAMES.index(tag) if tag in RARITY_NAMES else None


def is_soulbound(item: str) -> bool:
    if (item or "").lstrip().startswith(SOULBOUND_MARK):
        return True
    return item_tag(item) in SOULBOUND_TAGS


def is_tradable(item: str) -> bool:
    return bool(item) and not is_soulbound(item) and rarity_idx(item) != CURSED_IDX


def can_equip(item: str) -> bool:
    idx = rarity_idx(item)
    return idx is not None and idx != CURSED_IDX


def base_value(item: str) -> int:
    idx = rarity_idx(item)
    if idx == CURSED_IDX:
        return 0
    if idx is None:
        return UNKNOWN_TAG_VALUE if item_tag(item) else NO_TAG_VALUE
    val = RARITIES[idx][3]
    # هر ستاره‌ی ارتقا ارزش آیتم رو بالا می‌بره (بازارِ بازیکن‌ها قیمت واقعی رو تعیین می‌کنه)
    return int(val * (1 + 0.35 * item_stars(item)))


def gear_bonus(item: Optional[str]) -> int:
    if not item or not can_equip(item):
        return 0
    return min(GEAR_CAP, GEAR_BASE[rarity_idx(item)] + GEAR_PER_STAR * min(MAX_STARS, item_stars(item)))


def item_hash(item: str) -> str:
    return format(zlib.crc32((item or "").encode("utf-8")) & 0xFFFFFFFF, "08x")


def item_label(item: str) -> str:
    """نشانگر وضعیتِ آیتم برای نمایش در لیست‌ها."""
    if is_soulbound(item):
        return "🔗"
    return ""


# ───────────────────────────── 🪙 اقتصادِ GS ─────────────────────────────
def capped_amount(earned: int, amount: int, soft: int, hard: int, soft_rate: float) -> int:
    """بخشی از «amount» که امروز واقعاً به بازیکن می‌رسه.
    تا soft: کامل | بین soft و hard: soft_rate | بعد از hard: صفر. earned = مجموعِ درآمدِ خامِ امروز."""
    if amount <= 0:
        return amount
    out, cur, rem = 0.0, max(0, earned), amount
    if cur < soft:
        take = min(rem, soft - cur)
        out += take
        cur += take
        rem -= take
    if rem > 0 and cur < hard:
        take = min(rem, hard - cur)
        out += take * soft_rate
    return int(out)


def exchange_fee(price: int, pct: int) -> int:
    return max(1, price * pct // 100)


def upgrade_cost(item: str) -> Optional[int]:
    """هزینه‌ی ارتقای ستاره‌ی بعدیِ آیتم؛ None یعنی به سقف رسیده یا قابل ارتقا نیست."""
    stars = item_stars(item)
    idx = rarity_idx(item)
    if idx is None or idx == CURSED_IDX or stars >= MAX_STARS:
        return None
    return 30 * (stars + 1) ** 2 + 15 * idx


FUSE_COUNT = 3
FUSE_COST = [20, 45, 90, 180]      # ادغام معمولی→غیرمعمول، …، حماسی→افسانه‌ای

FORGE_NAMES = [
    "شمشیرِ سرنوشت‌دوز", "سپرِ پژواک", "عصای مه‌ی دروازه", "خنجرِ دوباره‌تولد",
    "کلاهِ ایزدبانو‌پسند", "زره‌ی خاکستر", "تبرِ خاموش", "کمانِ آخرین‌نفس",
]


def forged_item(idx: int, name: str) -> str:
    return f"{RARITIES[idx][1]} {name} ‹{RARITIES[idx][0]}›"


# ───────────────────────────── 🔁 پژواکِ مرگ (بازتولد) ─────────────────────────────
def echo_charges(deaths: int) -> int:
    """هرچه بیشتر مرده باشی، پژواکِ بازتولد بیشتری داری (مرگ پیشرفت رو نمی‌کُشه؛ قدرت می‌ده)."""
    if deaths >= 15:
        return 3
    if deaths >= 5:
        return 2
    if deaths >= 1:
        return 1
    return 0
