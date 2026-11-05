"""🎲 ساخت رندومِ کلاس و چیت‌اسکیل (خالص: بدون دیتابیس/تلگرام/AI).

اصول:
- قطعی: همه‌چیز از seed = sha256(salt:uid) ساخته میشه؛ بعد از ساخت تو پروفایل ذخیره میشه (ریرول با ریستارت ممکن نیست).
- مکانیک فقط «داده‌ی ساختاریِ اعتبارسنجی‌شده» ـه: effectها از یه whitelist میان و سقفِ سخت دارن.
  AI فقط flavor (متنِ توصیف) می‌نویسه؛ هیچ کدی اجرا نمی‌شه و هیچ effectـی GS/آیتم نمی‌سازه یا به دیتابیس دست می‌زنه.
- اجرا: سیستم‌های موجودِ بازی (نبرد، گشت، فروشگاه، رویدادها) از effect_total(doc, name) می‌خونن.
"""

import hashlib
import html
import random
import time
from typing import Optional

# ───────────────────────────── whitelist و سقف‌ها ─────────────────────────────
EFFECTS = {
    "atk_pct": "قدرت حمله",
    "hp_pct": "جان (HP) در نبرد",
    "gold_pct": "GS گشت",
    "heal_pct": "شفا",
    "loss_cut_pct": "کاهش ضرر بقا",
    "loot_chance_pct": "شانس غنیمت",
    "npc_affinity": "جلب نظر NPCها",
    "shop_discount_pct": "تخفیف خرید",
    "event_reward_pct": "جایزه‌ی رویدادهای جهان",
}
CAPS = {  # سقف مجموعِ کلاس + چیت (درصد) — هیچ‌وقت از این بیشتر نمیشه
    "atk_pct": 25, "hp_pct": 25, "gold_pct": 25, "heal_pct": 30, "loss_cut_pct": 30,
    "loot_chance_pct": 15, "npc_affinity": 50, "shop_discount_pct": 20, "event_reward_pct": 25,
}
PASSIVE_ACTIVE_RATIO = 0.4          # چیت‌اسکیل بدون فعال‌سازی ۴۰٪ قدرتشه
EVOLUTION_LEVELS = (10, 25, 50)
EVO_BONUS = 0.15                    # هر مرحله تکامل +۱۵٪ به passiveهای کلاس

RARITIES = [  # (کلید، نام، ایموجی، وزن، ضریب)
    ("common", "معمولی", "🪵", 55.0, 1.0),
    ("rare", "نادر", "💎", 28.0, 1.2),
    ("epic", "حماسی", "🔮", 12.0, 1.5),
    ("legendary", "افسانه‌ای", "👑", 4.5, 1.8),
    ("mythic", "اسطوره‌ای", "🌌", 0.5, 2.2),
]
RARITY_BY_KEY = {r[0]: r for r in RARITIES}
CLASS_PASSIVE_COUNT = {"common": 2, "rare": 2, "epic": 3, "legendary": 3, "mythic": 4}

# کلید: (en, fa, کلاسِ پایه‌ی بازی، نقش)
ARCHETYPES = {
    "warrior": ("Warrior", "جنگجو", "warrior", "frontline"),
    "mage": ("Mage", "جادوگر", "mage", "ranged"),
    "assassin": ("Assassin", "آدم‌کُش", "rogue", "burst"),
    "summoner": ("Summoner", "احضارگر", "mage", "control"),
    "knight": ("Knight", "شوالیه", "warrior", "tank"),
    "necromancer": ("Necromancer", "نکرومنسر", "mage", "drain"),
    "archer": ("Archer", "کمان‌دار", "rogue", "ranged"),
    "monk": ("Monk", "راهب", "priest", "hybrid"),
    "spellblade": ("Spellblade", "شمشیرزنِ جادویی", "warrior", "hybrid"),
    "guardian": ("Guardian", "نگهبان", "priest", "tank"),
    "berserker": ("Berserker", "برسرکر", "warrior", "burst"),
}
ARCH_PREFIX = {  # برای ساخت هیبریدِ اورجینال
    "warrior": ("War", "رزم"), "mage": ("Arcane", "رمز"), "assassin": ("Shade", "سایه"),
    "summoner": ("Call", "ندا"), "knight": ("Iron", "آهن"), "necromancer": ("Necro", "مرگ"),
    "archer": ("Sky", "آسمان"), "monk": ("Zen", "آرام"), "spellblade": ("Spell", "افسون"),
    "guardian": ("Ward", "پاس"), "berserker": ("Rage", "خشم"),
}
ELEMENTS = {
    "fire": ("Flame", "شعله‌ور"), "frost": ("Frostblood", "یخ‌خون"), "storm": ("Storm", "طوفانی"),
    "void": ("Voidbound", "تهی‌پیوند"), "astral": ("Astral", "اختری"), "eclipse": ("Eclipse", "خسوف"),
    "soul": ("Soul", "روح‌خوار"), "chrono": ("Chrono", "زمان‌پیچ"), "blood": ("Bloodsworn", "خون‌سوگند"),
    "nature": ("Thorn", "خارزار"), "holy": ("Radiant", "تابناک"), "shadow": ("Umbral", "سایه‌دار"),
}
WEAPONS = {
    "sword": "شمشیر", "greatsword": "شمشیرِ بزرگ", "staff": "عصا", "daggers": "خنجرهای جفت", "bow": "کمان",
    "scythe": "داس", "fists": "مشت‌های آهنین", "shield": "سپر و گرز", "tome": "کتابِ افسون", "spear": "نیزه",
    "chains": "زنجیر",
}
ARCH_WEAPONS = {
    "warrior": ["sword", "greatsword", "spear"], "mage": ["staff", "tome"], "assassin": ["daggers", "chains"],
    "summoner": ["tome", "staff", "chains"], "knight": ["sword", "shield", "spear"], "necromancer": ["scythe", "tome", "staff"],
    "archer": ["bow", "daggers"], "monk": ["fists", "staff"], "spellblade": ["sword", "greatsword", "tome"],
    "guardian": ["shield", "spear"], "berserker": ["greatsword", "chains", "fists"],
}
# نقش → effectهای محتملِ passive (با وزن)
ROLE_EFFECTS = {
    "frontline": [("hp_pct", 3), ("atk_pct", 3), ("loss_cut_pct", 2)],
    "tank": [("hp_pct", 4), ("loss_cut_pct", 3), ("heal_pct", 1)],
    "ranged": [("atk_pct", 3), ("loot_chance_pct", 2), ("gold_pct", 2)],
    "burst": [("atk_pct", 4), ("gold_pct", 2), ("loot_chance_pct", 1)],
    "control": [("loot_chance_pct", 2), ("npc_affinity", 2), ("atk_pct", 2), ("gold_pct", 1)],
    "drain": [("heal_pct", 3), ("atk_pct", 2), ("loss_cut_pct", 2)],
    "hybrid": [("atk_pct", 2), ("hp_pct", 2), ("heal_pct", 2), ("gold_pct", 1)],
}
PASSIVE_RANGE = {  # مقدارِ پایه‌ی هر passive (قبل از ضریب کمیابی)
    "atk_pct": (2, 4), "hp_pct": (3, 6), "gold_pct": (3, 6), "heal_pct": (4, 8), "loss_cut_pct": (3, 6),
    "loot_chance_pct": (2, 4), "npc_affinity": (5, 10), "shop_discount_pct": (3, 6), "event_reward_pct": (4, 8),
}
PASSIVE_NAMES = {
    "atk_pct": ["تیغِ تیز", "خشمِ نهفته", "ضربه‌ی دقیق"], "hp_pct": ["پوستِ آهنین", "تنِ سخت‌جان", "اراده‌ی پولادین"],
    "gold_pct": ["دستِ طلایی", "بوی پول", "چشمِ حراج"], "heal_pct": ["نفسِ شفابخش", "خونِ زنده", "لمسِ مرهم"],
    "loss_cut_pct": ["بختِ سخت‌جان", "سپرِ نامرئی", "کندیِ آسیب"], "loot_chance_pct": ["چشمِ غنیمت‌یاب", "نسیمِ گنج", "دستِ دزدِ شانس"],
    "npc_affinity": ["زبانِ نرم", "نگاهِ دلنشین", "اعتبارِ مبهم"], "shop_discount_pct": ["چانه‌زنِ ماهر", "لبخندِ تخفیف", "سکه‌شمارِ تیز"],
    "event_reward_pct": ["قهرمانِ مردم", "نامِ بلند", "بختِ جنگ"],
}
ACTIVE_VERBS = {
    "warrior": ("Cleave", "شکافتن"), "mage": ("Nova", "انفجارِ نور"), "assassin": ("Shadowstep", "گام سایه"),
    "summoner": ("Call", "فراخوان"), "knight": ("Bulwark", "دیوارِ آهنین"), "necromancer": ("Reap", "درو"),
    "archer": ("Barrage", "رگبار"), "monk": ("Palm", "کفِ آرام"), "spellblade": ("Edge", "لبه‌ی افسون"),
    "guardian": ("Aegis", "سپرِ مقدس"), "berserker": ("Frenzy", "جنون"),
}
ACTIVE_KINDS = {"warrior": "pierce", "mage": "burst", "rogue": "drain", "priest": "guard"}  # فقط توصیف؛ مکانیکش همون مهارتِ کلاس پایه‌ست
EVO_NAMES = [("Awakened", "بیدارشده"), ("Sovereign", "فرمانروا"), ("Transcendent", "فراتر")]
CLASS_FLAVORS = [
    "ایسکا دوستش نداره، ولی می‌ترسه ازش.", "سرنوشتش رو با تیغِ خودش می‌نویسه، نه با دستِ ایزدبانو.",
    "از وقتی تو این دنیا چشم باز کرده، همه‌چی ازش دور نمی‌شه.", "یه تاریخچه‌ی ناگفته پشتِ این کلاسه.",
]

# ───────────────────────────── چیت‌اسکیل‌ها ─────────────────────────────
# id: (en, fa, category, [(effect, lo, hi)], cost_type, cost_range, cooldown_range(min), duration)
CHEATS = {
    "appraisal": ("Absolute Appraisal", "ارزیابیِ مطلق", "exploration", [("loot_chance_pct", 6, 11), ("gold_pct", 6, 12)], "survival", (4, 8), (30, 60), (2, 4)),
    "soul_archive": ("Soul Archive", "بایگانیِ ارواح", "support", [("heal_pct", 12, 20), ("npc_affinity", 12, 20)], "survival", (5, 9), (40, 80), (2, 3)),
    "adaptation": ("Infinite Adaptation", "سازگاریِ بی‌پایان", "survival", [("loss_cut_pct", 12, 20), ("hp_pct", 6, 12)], "survival", (3, 6), (30, 60), (3, 5)),
    "devourer": ("Skill Devourer", "بلعنده‌ی مهارت", "combat", [("atk_pct", 10, 16), ("hp_pct", 4, 8)], "survival", (6, 10), (45, 90), (2, 3)),
    "rewrite": ("Reality Rewrite", "بازنویسیِ واقعیت", "world", [("event_reward_pct", 12, 20), ("loot_chance_pct", 4, 8)], "gold", (30, 60), (60, 120), (2, 3)),
    "echo": ("Temporal Echo", "پژواکِ زمان", "combat", [("hp_pct", 10, 16), ("loss_cut_pct", 6, 10)], "survival", (5, 8), (40, 80), (2, 4)),
    "shadow": ("Shadow Sovereignty", "حاکمیتِ سایه", "summoning", [("atk_pct", 8, 13), ("loot_chance_pct", 5, 9)], "survival", (6, 10), (45, 90), (2, 3)),
    "inventory": ("World Inventory", "انبارِ جهان", "trading", [("shop_discount_pct", 8, 14), ("gold_pct", 6, 12)], "gold", (20, 50), (30, 70), (3, 5)),
    "crafting": ("Divine Crafting", "ساختِ الهی", "crafting", [("shop_discount_pct", 6, 10), ("gold_pct", 8, 14)], "gold", (25, 55), (40, 80), (2, 4)),
    "counter": ("Perfect Counter", "ضدحمله‌ی بی‌نقص", "combat", [("loss_cut_pct", 10, 16), ("atk_pct", 6, 10)], "survival", (5, 9), (35, 70), (2, 4)),
    "wanderer": ("Wayfarer's Grace", "لطفِ رهگذر", "exploration", [("gold_pct", 8, 14), ("loss_cut_pct", 6, 10)], "survival", (3, 7), (25, 50), (3, 5)),
    "silver_tongue": ("Silver Tongue Law", "قانونِ زبانِ نقره‌ای", "trading", [("npc_affinity", 15, 25), ("shop_discount_pct", 6, 10)], "gold", (20, 45), (30, 60), (3, 5)),
    "bonded": ("Bonded Legion", "لژیونِ پیمان‌بسته", "summoning", [("atk_pct", 6, 11), ("hp_pct", 6, 10)], "survival", (5, 9), (40, 80), (2, 3)),
    "lifeline": ("Lifeline Weave", "بافتِ رشته‌ی زندگی", "survival", [("heal_pct", 14, 22), ("loss_cut_pct", 6, 10)], "survival", (4, 8), (35, 70), (2, 4)),
    "worldwalker": ("World Walker", "جهان‌گرد", "world", [("event_reward_pct", 10, 16), ("npc_affinity", 8, 14)], "survival", (4, 8), (40, 80), (2, 4)),
}
CHEAT_CATEGORY_FA = {
    "combat": "رزمی", "exploration": "کاوش", "support": "پشتیبانی", "survival": "بقا", "world": "تعامل با جهان",
    "summoning": "احضار", "trading": "تجارت", "crafting": "ساخت",
}
CHEAT_EPITHETS = ["قرمزِ شفق", "خاموش", "بی‌نام", "طلوعِ آخر", "شکسته", "نجوا", "زنگارگرفته", "ابدی", "گمشده", "ممنوعه"]
CHEAT_RARITY_WEIGHTS = {"common": 50.0, "rare": 30.0, "epic": 14.0, "legendary": 5.0, "mythic": 1.0}
CHEAT_FLAVORS = [
    "هدیه‌ای که ایزدبانو با اکراه امضاش کرد.", "قدرتی که فقط یه بار تو هر هزار سال به یه روح داده میشه.",
    "پشتش یه قیمت هست؛ ولی آدم‌ها همیشه قیمت رو دیر می‌فهمن.", "تو این دنیا، کسی مثلِ تو چیزی تو دست نداره.",
]


# ───────────────────────────── کمکی‌ها ─────────────────────────────
def _rng(uid: int, salt: str, tag: str) -> random.Random:
    h = hashlib.sha256(f"{salt}:{uid}:{tag}".encode()).hexdigest()
    return random.Random(int(h, 16))


def _pick_rarity(rng: random.Random, weights: Optional[dict] = None) -> str:
    keys = [r[0] for r in RARITIES]
    w = [weights[k] if weights else RARITY_BY_KEY[k][3] for k in keys]
    return rng.choices(keys, weights=w)[0]


def rarity_label(key: str) -> str:
    r = RARITY_BY_KEY.get(key) or RARITIES[0]
    return f"{r[2]} {r[1]}"


def _wchoice(rng: random.Random, pairs: list, exclude: set):
    pool = [(k, w) for k, w in pairs if k not in exclude] or list(pairs)
    return rng.choices([k for k, _ in pool], weights=[w for _, w in pool])[0]


# ───────────────────────────── ساخت کلاس ─────────────────────────────
def generate_class(uid: int, salt: str = "isekai", base_cls: Optional[str] = None) -> dict:
    rng = _rng(uid, salt, "class")
    pool = [k for k, v in ARCHETYPES.items() if base_cls is None or v[2] == base_cls] or list(ARCHETYPES)
    a1 = rng.choice(pool)
    a2 = None
    if rng.random() < 0.30:                                   # 🧬 هیبریدِ اورجینال
        a2 = rng.choice([k for k in ARCHETYPES if k != a1])
    elem = rng.choice(list(ELEMENTS))
    rarity = _pick_rarity(rng)
    mult = RARITY_BY_KEY[rarity][4]
    en1, fa1, base, role = ARCHETYPES[a1]
    if a2:
        pre_en, pre_fa = ARCH_PREFIX[a1]
        en_arch, fa_arch = f"{pre_en}-{ARCHETYPES[a2][0]}", f"{ARCHETYPES[a2][1]} {pre_fa}‌محور"
        role2 = ARCHETYPES[a2][3]
    else:
        en_arch, fa_arch, role2 = en1, fa1, None
    ee, ef = ELEMENTS[elem]
    wpool = ARCH_WEAPONS[a1] + (ARCH_WEAPONS[a2] if a2 else [])
    weapon = rng.choice(wpool)

    passives, used = [], set()
    roles = [role] + ([role2] if role2 else [])
    for _ in range(CLASS_PASSIVE_COUNT[rarity]):
        eff = _wchoice(rng, ROLE_EFFECTS[rng.choice(roles)], used)
        used.add(eff)
        lo, hi = PASSIVE_RANGE[eff]
        passives.append({"effect": eff, "value": max(1, min(CAPS[eff], int(round(rng.randint(lo, hi) * mult)))), "name": rng.choice(PASSIVE_NAMES[eff])})

    verb_en, verb_fa = ACTIVE_VERBS[a1]
    active = {"name_en": f"{ee} {verb_en}", "name_fa": f"{verb_fa}ِ {ef}", "kind": ACTIVE_KINDS[base],
              "mechanic": "base_class_skill"}
    evo = [{"level": lv, "name_en": f"{n_en} {ee} {en_arch}", "name_fa": f"{fa_arch} {ef} {n_fa}"}
           for lv, (n_en, n_fa) in zip(EVOLUTION_LEVELS, EVO_NAMES)]
    return {
        "v": 1, "name_en": f"{ee} {en_arch}", "name_fa": f"{fa_arch} {ef}", "archetype": a1, "archetype2": a2,
        "element": elem, "weapon": weapon, "rarity": rarity, "base_cls": base, "role": role,
        "passives": passives, "active": active, "evolution": evo, "flavor": rng.choice(CLASS_FLAVORS), "flavor_ai": False,
    }


# ───────────────────────────── ساخت چیت‌اسکیل ─────────────────────────────
def generate_cheat(uid: int, salt: str = "isekai") -> dict:
    rng = _rng(uid, salt, "cheat")
    cid = rng.choice(list(CHEATS))
    en, fa, cat, effs, ctype, crange, cd, dur = CHEATS[cid]
    rarity = _pick_rarity(rng, CHEAT_RARITY_WEIGHTS)
    mult = RARITY_BY_KEY[rarity][4]
    effects = [{"effect": e, "value": max(1, min(CAPS[e], int(round(rng.randint(lo, hi) * mult))))} for e, lo, hi in effs]
    cost_amt = rng.randint(*crange)
    cooldown = rng.randint(*cd) * 60
    duration = rng.randint(*dur)
    uniq = hashlib.sha256(f"{salt}:{uid}:cheat-id".encode()).hexdigest()[:6]
    cost = {ctype: cost_amt}
    lim = (f"هر فعال‌سازی {cost_amt}٪ از بقات رو می‌خوره" if ctype == "survival" else f"هر فعال‌سازی {cost_amt} GS می‌سوزونه") + \
          f" و {cooldown // 60} دقیقه خنک‌سازی داره؛ بدون فعال‌سازی فقط {int(PASSIVE_ACTIVE_RATIO * 100)}٪ قدرت داره."
    return {
        "v": 1, "id": f"{cid}-{uniq}", "template": cid, "name_en": en, "name_fa": fa, "epithet_fa": rng.choice(CHEAT_EPITHETS),
        "category": cat, "rarity": rarity, "effects": effects, "cost": cost, "cooldown_s": cooldown, "duration": duration,
        "limitation": lim, "flavor": rng.choice(CHEAT_FLAVORS), "flavor_ai": False,
    }


def generate_profile(uid: int, salt: str = "isekai", base_cls: Optional[str] = None) -> tuple:
    return generate_class(uid, salt, base_cls), generate_cheat(uid, salt)


# ───────────────────────────── اعتبارسنجی ─────────────────────────────
def _valid_effects(lst) -> list:
    out = []
    for e in lst or []:
        try:
            name, val = e.get("effect"), int(e.get("value"))
        except (AttributeError, TypeError, ValueError):
            continue
        if name in EFFECTS and 0 < val <= CAPS[name]:
            out.append({"effect": name, "value": val})
    return out


def validate_class(c) -> bool:
    return (isinstance(c, dict) and c.get("rarity") in RARITY_BY_KEY and c.get("archetype") in ARCHETYPES
            and c.get("element") in ELEMENTS and c.get("base_cls") in ("warrior", "mage", "rogue", "priest")
            and len(_valid_effects(c.get("passives"))) == len(c.get("passives") or [0]) > 0)


def validate_cheat(c) -> bool:
    if not (isinstance(c, dict) and c.get("rarity") in RARITY_BY_KEY and c.get("category") in CHEAT_CATEGORY_FA):
        return False
    cost = c.get("cost") or {}
    ok_cost = (len(cost) == 1 and ((cost.get("survival") and 1 <= int(cost["survival"]) <= 20)
                                   or (cost.get("gold") and 1 <= int(cost["gold"]) <= 120)))
    return bool(_valid_effects(c.get("effects"))) and bool(ok_cost) and 60 <= int(c.get("cooldown_s", 0)) <= 6 * 3600


# ───────────────────────────── اجرا (خوانده میشه توسط سیستم‌های بازی) ─────────────────────────────
def evolution_stage(doc: dict) -> int:
    lvl = int(doc.get("level", 1))
    return sum(1 for x in EVOLUTION_LEVELS if lvl >= x)


def cheat_level(doc: dict) -> int:
    return 1 + min(4, int(doc.get("cheat_uses", 0)) // 8)


def cheat_is_active(doc: dict) -> bool:
    return int(doc.get("cheat_charges", 0) or 0) > 0


def effect_total(doc: Optional[dict], name: str) -> int:
    """مجموعِ effectِ «name» از کلاس + چیت‌اسکیل (٪)، با سقفِ سخت. بدون پروفایل = ۰."""
    if not doc or name not in EFFECTS:
        return 0
    total = 0.0
    gc = doc.get("gclass")
    if validate_class(gc):
        k = 1 + EVO_BONUS * evolution_stage(doc)
        total += sum(p["value"] for p in _valid_effects(gc.get("passives")) if p["effect"] == name) * k
    ch = doc.get("cheat")
    if validate_cheat(ch):
        scale = (1.0 if cheat_is_active(doc) else PASSIVE_ACTIVE_RATIO) * (1 + 0.1 * (cheat_level(doc) - 1))
        total += sum(e["value"] for e in _valid_effects(ch.get("effects")) if e["effect"] == name) * scale
    return max(0, min(int(total), CAPS[name]))


def current_class_name(doc: dict) -> str:
    gc = doc.get("gclass") or {}
    st = evolution_stage(doc)
    if st and validate_class(gc) and len(gc.get("evolution") or []) >= st:
        return gc["evolution"][st - 1]["name_fa"]
    return gc.get("name_fa") or ""


def profile_lines(doc: dict, detail: bool = False) -> list:
    """خطوطِ نمایشی (HTML-safe) کلاس و چیت‌اسکیل برای کارت/ثبت‌نام."""
    e = html.escape
    lines = []
    gc, ch = doc.get("gclass"), doc.get("cheat")
    if validate_class(gc):
        lines.append(f"🎲 کلاس: <b>{e(current_class_name(doc))}</b> ‹{e(gc['name_en'])}› {rarity_label(gc['rarity'])}")
        if detail:
            lines.append(f"🗡 سلاح: {e(WEAPONS.get(gc['weapon'], gc['weapon']))} · ✨ مهارت: {e(gc['active']['name_fa'])}")
            for p in _valid_effects(gc["passives"]):
                lines.append(f"  ▫️ {e(EFFECTS[p['effect']])} +{p['value']}٪")
            nxt = [x for x in EVOLUTION_LEVELS if x > int(doc.get('level', 1))]
            if nxt:
                lines.append(f"🌱 تکاملِ بعدی: سطح {nxt[0]}")
            if gc.get("flavor"):
                lines.append(f"<i>{e(gc['flavor'])}</i>")
    if validate_cheat(ch):
        lines.append(f"🌟 چیت‌اسکیل: <b>{e(ch['name_fa'])} «{e(ch['epithet_fa'])}»</b> {rarity_label(ch['rarity'])} · {e(CHEAT_CATEGORY_FA[ch['category']])}")
        if detail:
            lv = cheat_level(doc)
            lines.append(f"📶 سطح {lv}/5 · {'🔥 فعال' if cheat_is_active(doc) else '💤 غیرفعال'}")
            for x in _valid_effects(ch["effects"]):
                lines.append(f"  ▫️ {e(EFFECTS[x['effect']])} تا +{x['value']}٪")
            lines.append(f"⚠️ {e(ch['limitation'])}")
            if ch.get("flavor"):
                lines.append(f"<i>{e(ch['flavor'])}</i>")
    return lines


def now_ts() -> float:
    return time.time()
