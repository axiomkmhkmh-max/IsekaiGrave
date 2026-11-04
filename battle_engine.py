"""موتورِ «نبردِ رشته‌ی سرنوشت» — خالص و بدون رندوم.

قانون‌ها (ساده):
• هر نفر HP، 🕯 روح (۰ تا ۵)، 🛡 سپر و 🔁 پژواک داره. نوبتی بازی می‌کنین؛ همه‌چیز دیده میشه.
• ⚔️ ضربه: آسیبِ کامل، +۱ روح.
• 🛡 سپر: ۶۰٪ از ضربه‌ی بعدیِ حریف رو می‌گیره، +۱ روح.
• 🌀 رشته‌ی سرنوشت (۳ روح): مهارتِ کلاس — خیلی قوی‌تر از ضربه.
• 🔁 بازتولد (فقط وقتی HP ≤ ۳۵٪ و پژواک داری): ۴۵٪ HP برمی‌گرده، روح صفر میشه، بعد از نبرد ۸٪ بقا کم میشه.
هیچ رندومی نیست؛ تصمیم‌ها (سپر یا ضربه؟ کِی رشته؟ کِی بازتولد؟) برنده رو مشخص می‌کنن."""

from typing import Optional

from rules import echo_charges

MAX_SOUL = 5
FATE_COST = 3
WARD_BLOCK = 0.6
ECHO_THRESHOLD = 0.35
ECHO_HEAL = 0.45
REBIRTH_TOLL = 8          # ٪ بقا که بعد از نبرد بابت بازتولد کم میشه
MAX_TURNS = 8             # نوبت برای هر نفر

SKILLS = {
    "warrior": "شکافِ سرنوشت",
    "mage": "رشته‌ی تقدیر",
    "rogue": "سایه‌ی دزد",
    "priest": "نفَسِ بازتولد",
    None: "رشته‌ی سرنوشت",
}
SKILL_HELP = {
    "warrior": "آسیب ×۲ و سپرِ حریف رو می‌شکنه",
    "mage": "آسیب ×۱٫۸ و ۲ روحِ حریف رو می‌سوزونه",
    "rogue": "آسیب ×۱٫۵، ۱ روح پس می‌گیری و ۱ روحِ حریف رو می‌دزدی",
    "priest": "آسیب ×۱٫۲ و ۲۰٪ HP رو شفا می‌ده",
    None: "آسیب ×۱٫۸",
}
MOVES = ("strike", "ward", "fate", "echo")


def make_fighter(doc: dict, gear: int = 0, perks=(), reborn: bool = False) -> dict:
    lvl = int(doc.get("level", 1))
    sv = int(doc.get("survival_rate", 50))
    cls = doc.get("cls")
    max_hp = 80 + lvl * 6 + int(sv * 0.6)
    atk = 18 + lvl * 3 + gear
    if "castle" in perks:
        atk = int(atk * 1.08)
    echo = echo_charges(int(doc.get("death_count", 0))) + (1 if "ruins" in perks else 0)
    return {
        "uid": doc["user_id"], "name": doc.get("first_name") or "ناشناس", "cls": cls, "lvl": lvl,
        "hp": max_hp, "max_hp": max_hp, "atk": atk, "soul": 2 if reborn else 0, "ward": False,
        "echo": echo, "used_echo": 0, "dealt": 0, "taken": 0,
    }


def legal_moves(me: dict) -> list:
    mv = ["strike"]
    if not me["ward"]:
        mv.append("ward")
    if me["soul"] >= FATE_COST:
        mv.append("fate")
    if me["echo"] > 0 and me["hp"] <= me["max_hp"] * ECHO_THRESHOLD:
        mv.append("echo")
    return mv


def _hit(me: dict, foe: dict, dmg: float, pierce: bool = False) -> str:
    dmg = max(1, int(dmg))
    note = ""
    if foe["ward"]:
        if pierce:
            note = " (سپر شکست!)"
        else:
            dmg = max(1, int(dmg * (1 - WARD_BLOCK)))
            note = " (سپر ۶۰٪ گرفت)"
        foe["ward"] = False
    foe["hp"] -= dmg
    me["dealt"] += dmg
    foe["taken"] += dmg
    return f"−{dmg}{note}"


def apply_move(me: dict, foe: dict, move: str) -> str:
    """حرکت رو اعمال می‌کنه (me و foe در جا تغییر می‌کنن) و یه خطِ لاگ برمی‌گردونه."""
    n = me["name"]
    if move == "ward":
        me["ward"] = True
        me["soul"] = min(MAX_SOUL, me["soul"] + 1)
        return f"🛡 {n} سپرِ روح بالا برد"
    if move == "echo":
        heal = int(me["max_hp"] * ECHO_HEAL)
        me["hp"] = min(me["max_hp"], me["hp"] + heal)
        me["soul"] = 0
        me["echo"] -= 1
        me["used_echo"] += 1
        return f"🔁 {n} از مرز مرگ بازتولد شد! +{heal} HP"
    if move == "fate":
        me["soul"] -= FATE_COST
        cls, atk = me["cls"], me["atk"]
        if cls == "warrior":
            return f"🌀 {n} «{SKILLS[cls]}» زد: " + _hit(me, foe, atk * 2.0, pierce=True)
        if cls == "mage":
            foe["soul"] = max(0, foe["soul"] - 2)
            return f"🌀 {n} «{SKILLS[cls]}» زد: " + _hit(me, foe, atk * 1.8) + " و ۲ روحِ حریف سوخت"
        if cls == "rogue":
            me["soul"] = min(MAX_SOUL, me["soul"] + 1)
            stolen = 1 if foe["soul"] > 0 else 0
            foe["soul"] -= stolen
            return f"🌀 {n} «{SKILLS[cls]}» زد: " + _hit(me, foe, atk * 1.5) + (" و ۱ روح دزدید" if stolen else "")
        if cls == "priest":
            heal = int(me["max_hp"] * 0.20)
            me["hp"] = min(me["max_hp"], me["hp"] + heal)
            return f"🌀 {n} «{SKILLS[cls]}» زد: " + _hit(me, foe, atk * 1.2) + f" و +{heal} HP شفا"
        return f"🌀 {n} «{SKILLS[None]}» زد: " + _hit(me, foe, atk * 1.8)
    # strike
    me["soul"] = min(MAX_SOUL, me["soul"] + 1)
    return f"⚔️ {n} ضربه زد: " + _hit(me, foe, me["atk"])


def auto_move(me: dict, foe: dict) -> str:
    """حرکتِ پیش‌فرض (وقتی بازیکن دیر کنه). عاقلانه ولی ساده."""
    lm = legal_moves(me)
    if "echo" in lm:
        return "echo"
    if foe["soul"] >= FATE_COST and "ward" in lm and me["hp"] > foe["atk"] * 0.5:
        return "ward"
    if "fate" in lm:
        return "fate"
    return "strike"


def pct(f: dict) -> float:
    return max(0, f["hp"]) / f["max_hp"]


def decide_on_turns(a: dict, b: dict) -> dict:
    """بعد از آخرین نوبت: HP٪ بیشتر برنده‌ست؛ مساوی → آسیبِ بیشتر؛ باز مساوی → b (مدافع)."""
    if abs(pct(a) - pct(b)) > 1e-9:
        return a if pct(a) > pct(b) else b
    if a["dealt"] != b["dealt"]:
        return a if a["dealt"] > b["dealt"] else b
    return b


def winner_if_over(fs: list, turns_done: int) -> Optional[int]:
    """index برنده یا None اگه ادامه داره."""
    for i in (0, 1):
        if fs[i]["hp"] <= 0:
            return 1 - i
    if turns_done >= MAX_TURNS * 2:
        w = decide_on_turns(fs[0], fs[1])
        return 0 if w is fs[0] else 1
    return None


# ───────────────────────────── 🐉 باس (رِید) ─────────────────────────────
RAGE_MAX = 5
BOSS_COUNTER = 8   # ٪ بقا


def raid_base_damage(doc: dict, gear: int = 0, perks=()) -> int:
    lvl = int(doc.get("level", 1))
    d = lvl * 5 + 30 + gear * 2
    if doc.get("cls") == "warrior":
        d += 10
    if "castle" in perks:
        d = int(d * 1.08)
    return d


def raid_fate(cls: Optional[str]) -> dict:
    """ضریب و اثرِ «رشته‌ی سرنوشت» روی باس."""
    return {
        "warrior": {"mult": 3.0, "refund": 0, "rage": 1, "heal": 0},
        "mage": {"mult": 2.4, "refund": 0, "rage": 0, "heal": 0},     # خشمِ باس جلو نمی‌افته
        "rogue": {"mult": 2.0, "refund": 1, "rage": 1, "heal": 0},    # یه روح پس می‌گیره
        "priest": {"mult": 1.6, "refund": 0, "rage": 1, "heal": 12},  # خودش رو شفا می‌ده
    }.get(cls, {"mult": 2.2, "refund": 0, "rage": 1, "heal": 0})


# ───────────────────────────── 🏰 محاصره ─────────────────────────────
def war_power(doc: dict, gear: int = 0) -> int:
    wp = 25 + int(doc.get("level", 1)) * 6 + gear * 3 + int(int(doc.get("survival_rate", 50)) * 0.2)
    if doc.get("cls") == "warrior":
        wp = int(wp * 1.10)
    return wp


def run_ai(fa: dict, fb: dict, first: int = 0) -> int:
    """شبیه‌سازیِ کاملِ یه نبرد با auto_move؛ index برنده (0=fa). برای تست توازن."""
    fs = [fa, fb]
    i, t = first, 0
    while True:
        me, foe = fs[i], fs[1 - i]
        apply_move(me, foe, auto_move(me, foe))
        t += 1
        w = winner_if_over(fs, t)
        if w is not None:
            return w
        i = 1 - i
