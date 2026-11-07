"""⚔️ موتورِ «کلش» — برخوردِ ژست‌ها، رتبه‌ی نام‌آوری، زنجیره‌ی پیروزی و سنگ‌کاغذ‌قیچی.

کاملاً خالص: بدونِ تلگرام، بدونِ دیتابیس و بدونِ رندوم؛ هر چی اینجاست با ورودیِ یکسان خروجیِ یکسان می‌ده.

🧠 مثلثِ ژست (مهاجم × مدافع) — هر ژست یکی رو می‌بره، از یکی می‌بازه و با یکی مساویه:
    💥 سنگین  → 🛡 سپر رو می‌شکنه    | 💨 جاخالی ازش در می‌ره | 🔄 ضدحمله: مساوی
    🗡 سریع   → 💨 جاخالی رو می‌گیره | 🔄 ضدحمله جوابش رو می‌ده | 🛡 سپر: مساوی
    🌀 فریب   → 🔄 ضدحمله رو گول می‌زنه | 🛡 سپر فریب رو می‌خونه | 💨 جاخالی: مساوی
برنده‌ی کلش تو نبرد برتری می‌گیره (روحِ اضافه + شروعِ اول)، بازنده ضعیف‌تر شروع می‌کنه؛
بعدش خودِ نبردِ رشته‌ی سرنوشت (battle_engine) بقیه‌ی ماجرا رو تموم می‌کنه.
"""

from typing import Optional

# ───────────────────────────── 🧠 مثلثِ ژست ─────────────────────────────
ATT = {
    "h": ("💥", "ضربه‌ی سنگین"),
    "q": ("🗡", "ضربه‌ی سریع"),
    "f": ("🌀", "فریب"),
}
DEF = {
    "g": ("🛡", "سپر"),
    "e": ("💨", "جاخالی"),
    "c": ("🔄", "ضدحمله"),
}
# ژستِ مهاجم → (دفاعی که می‌بره، دفاعی که ازش می‌بازه)
_TRI = {"h": ("g", "e"), "q": ("e", "c"), "f": ("c", "g")}

TRIANGLE_HELP = (
    "💥 سنگین: سپر رو می‌شکنه · از جاخالی می‌بازه\n"
    "🗡 سریع: جاخالی رو می‌گیره · از ضدحمله می‌بازه\n"
    "🌀 فریب: ضدحمله رو گول می‌زنه · از سپر می‌بازه"
)

EDGE_SOULS = 2          # روحِ اضافه‌ی برنده‌ی کلش
EDGE_ATK_PENALTY = 0.85  # مهاجمِ خوانده‌شده: ضربه‌هاش ۱۵٪ ضعیف‌تر


def clash_result(att: str, dfn: str) -> int:
    """+۱ = مهاجم خوندش (برتری)، ۰ = مساوی، −۱ = مدافع خوند."""
    win_vs, lose_vs = _TRI[att]
    return 1 if dfn == win_vs else -1 if dfn == lose_vs else 0


def auto_defense(cls: Optional[str]) -> str:
    """ژستِ دفاعیِ خودکار (وقتی مدافع جواب نده): ثابت و قابل‌حدس بر اساسِ کلاس."""
    return {"warrior": "g", "rogue": "e", "mage": "c", "priest": "g"}.get(cls or "", "g")


def apply_edge(fa: dict, fb: dict, res: int, max_soul: int = 5) -> int:
    """نتیجه‌ی کلش رو روی دو جنگنده (در جا) اعمال می‌کنه؛ خروجی = اندیسِ اولین بازیکن (0=مهاجم)."""
    if res > 0:
        fa["soul"] = min(max_soul, fa["soul"] + EDGE_SOULS)
        return 0
    if res < 0:
        fb["soul"] = min(max_soul, fb["soul"] + EDGE_SOULS)
        fa["atk"] = int(fa["atk"] * EDGE_ATK_PENALTY)
        return 1
    return 0


def habit_line(counts: Optional[dict], table: dict, who: str) -> Optional[str]:
    """«عادتِ» یه بازیکن تو انتخابِ ژست (فقط وقتی ≥ ۵ نمونه هست) — برای خوندنِ حریف."""
    c = {k: int((counts or {}).get(k, 0)) for k in table}
    tot = sum(c.values())
    if tot < 5:
        return None
    parts = [f"{table[k][0]}{round(100 * v / tot)}٪" for k, v in sorted(c.items(), key=lambda kv: -kv[1]) if v]
    return f"📈 عادتِ {who}: " + " · ".join(parts)


# متنِ صحنه برای هر ترکیب (مهاجم، مدافع) — {a} مهاجم، {d} مدافع
CLASH_LINES = {
    ("h", "g"): "💥 سپرِ {d} زیرِ ضربه‌ی سنگینِ {a} خرد شد!",
    ("h", "e"): "💨 {d} از ضربه‌ی کُندِ {a} جاخالی داد و ضربه تو هوا موند!",
    ("h", "c"): "⚖️ ضربه‌ی سنگینِ {a} و ضدحمله‌ی {d} تو هم گره خورد!",
    ("q", "e"): "🗡 {d} جاخالی داد ولی ضربه‌ی سریعِ {a} زودتر رسید!",
    ("q", "c"): "🔄 {d} ضربه‌ی سریعِ {a} رو خوند و با ضدحمله جوابش رو داد!",
    ("q", "g"): "⚖️ ضربه‌ی سریعِ {a} به سپرِ {d} خورد و برگشت!",
    ("f", "c"): "🌀 {d} گولِ فریبِ {a} رو خورد و ضدحمله‌اش تو هوا موند!",
    ("f", "g"): "🛡 {d} فریبِ {a} رو نخرید و سپرش رو نگه داشت!",
    ("f", "e"): "⚖️ فریبِ {a} و جاخالیِ {d}؛ هر دو دور هم می‌چرخن!",
}

TAUNTS = [
    "{a} با یه پوزخندِ تمام‌عیار به {d} نگاه کرد: «اون شمشیر رو از کجا قرض گرفتی؟» 😏",
    "{a} بلند گفت: «{d}؟ آها، همونی که ایزدبانو بهش می‌خنده!» 🤭",
    "{a} برای {d} دست زد: «شجاعتت قابل تحسینه؛ احمقانه‌ست ولی قابل تحسینه.» 👏",
    "{a} ادای {d} رو درآورد و تمام گروه ترکید. 😂",
    "{a} به {d} گفت: «تو رو تو لیستِ ‹بعداً‌ها› نوشتم. خیلی هم پایین.» 📝",
    "{a} فوتِ بلندی به شمشیرِ {d} کرد: «زنگ زده؛ بعد از دعوا بفرست پاکش کنن.» 🗡",
]

RANK_UP_LINES = [
    "ایزدبانو با بی‌حوصلگی سرش رو بلند کرد و یه چشمک زد: «…بد نبود.» 💅",
    "گورستان لحظه‌ای ساکت شد؛ بعد همه‌ی ارواح براش دست زدن. 👻",
    "اسمش تو دفترِ ایزدبانو با خط درشت‌تر نوشته شد. 📖",
]

# ───────────────────────────── 🏅 رتبه‌ی نام‌آوری ─────────────────────────────
# (حدِ پایین RP، ایموجی، نام)
RANKS = [
    (0, "🪨", "خاک‌نشینِ گورستان"),
    (30, "🗡", "تازه‌شمشیر"),
    (100, "⚔️", "جنگجوی گور"),
    (250, "🩸", "شکارچیِ ارواح"),
    (500, "🔥", "فرمانده‌ی تاریکی"),
    (900, "👑", "سردارِ خونین"),
    (1500, "🌟", "افسانه‌ی ایسکا"),
    (2500, "💀", "رقیبِ ایزدبانو"),
]
RANK_REWARD = [0, 20, 40, 70, 110, 160, 240, 400]     # GS یک‌باره برای رسیدن به هر رتبه (با سقفِ روزانه‌ی درآمد)
assert len(RANKS) == len(RANK_REWARD)


def rank_index(rp: int) -> int:
    idx = 0
    for i, (need, _ic, _nm) in enumerate(RANKS):
        if rp >= need:
            idx = i
    return idx


def rank_label(rp: int) -> str:
    _n, ic, nm = RANKS[rank_index(rp)]
    return f"{ic} {nm}"


def rank_name(idx: int) -> str:
    _n, ic, nm = RANKS[max(0, min(idx, len(RANKS) - 1))]
    return f"{ic} {nm}"


def rank_progress(rp: int, width: int = 10) -> str:
    """نوارِ پیشرفت تا رتبه‌ی بعدی + عددها."""
    i = rank_index(rp)
    if i >= len(RANKS) - 1:
        return "▰" * width + f" {rp} RP (رتبه‌ی نهایی)"
    lo, hi = RANKS[i][0], RANKS[i + 1][0]
    n = max(0, min(width, int(width * (rp - lo) / (hi - lo))))
    return "▰" * n + "▱" * (width - n) + f" {rp}/{hi} RP → {rank_name(i + 1)}"


def _gap(my_rp: int, opp_rp: int) -> float:
    """−۱..+۱؛ مثبت = حریف قوی‌تره."""
    return max(-1.0, min(1.0, (opp_rp - my_rp) / 300.0))


def attack_rp(win: bool, my_rp: int, opp_rp: int, crit: bool = False, streak: int = 0) -> int:
    """تغییرِ RP مهاجم. بردِ حریفِ قوی‌تر بیشتر می‌ده، باختِ حریفِ ضعیف‌تر بیشتر کم می‌کنه."""
    g = _gap(my_rp, opp_rp)
    if win:
        return max(3, round(8 + 4 * g + (2 if crit else 0) + min(max(streak - 1, 0), 4)))
    return -max(1, round(3 - 2 * g))


def defend_rp(win: bool, my_rp: int, opp_rp: int, read: bool = False) -> int:
    """تغییرِ RP مدافع (read = حرکتِ مهاجم رو خونده)."""
    g = _gap(my_rp, opp_rp)
    if win:
        return max(2, round(5 + 3 * g + (2 if read else 0)))
    return -max(1, round(2 - g))


# ───────────────────────────── 🔥 زنجیره‌ی پیروزی ─────────────────────────────
STREAK_BANNERS = {3: "🔥 زنجیره‌ی سه‌تایی!", 5: "💀 قتل‌عام!", 7: "👑 بی‌رحمِ ایسکا!", 10: "🌋 افسانه‌ی خون!"}
STREAK_BREAK_MIN = 3


def streak_loot_mult(streak: int) -> float:
    """ضریبِ غارت: برد #۱ → ×۱٫۰ … برد #۶+ → ×۱٫۵."""
    return 1.0 + 0.1 * min(max(streak - 1, 0), 5)


def streak_banner(streak: int) -> Optional[str]:
    """فقط وقتی دقیقاً به یه آستانه می‌رسه یه بنر داره."""
    return STREAK_BANNERS.get(streak)


def streak_break_reward(broken: int) -> tuple:
    """(GS، XP) برای کسی که زنجیره‌ی ≥ ۳ تایی رو می‌شکنه."""
    if broken < STREAK_BREAK_MIN:
        return 0, 0
    return min(60, 10 * broken), min(40, 5 * broken)


# ───────────────────────────── ✊✋✌️ سنگ‌کاغذ‌قیچی ─────────────────────────────
RPS = {"r": ("✊", "سنگ"), "p": ("✋", "کاغذ"), "s": ("✌️", "قیچی")}
_RPS_BEATS = {"r": "s", "p": "r", "s": "p"}
RPS_FEE_PCT = 5


def rps_result(x: str, y: str) -> int:
    """+۱ = x می‌بره، −۱ = y می‌بره، ۰ = مساوی."""
    if x == y:
        return 0
    return 1 if _RPS_BEATS[x] == y else -1


def rps_payouts(amount: int, res: int) -> tuple:
    """(برنده‌ی کل پات پس از کارمزد یا ۰ برای مساوی، کارمزدِ سوخته). مساوی: کارمزد صفر و هر کس پولش رو پس می‌گیره."""
    if res == 0:
        return 0, 0
    pot = 2 * amount
    fee = max(1, pot * RPS_FEE_PCT // 100)
    return pot - fee, fee
