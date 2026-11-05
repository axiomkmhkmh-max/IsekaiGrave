"""🌍 داده و قوانینِ خالصِ دنیای زنده (بدون دیتابیس/تلگرام/AI): ساعتِ دنیا، NPCهای اولیه، اقتصاد، قالبِ رویدادها و تعامل‌ها."""

import random
import zlib
from typing import Optional

REGIONS = ["forest", "sea", "ruins", "city"]
REGION_SHORT = {"forest": "جنگل", "sea": "دریا", "ruins": "خرابه‌ها", "city": "پایتخت"}
REGION_FA = {"forest": "جنگل عمیق", "sea": "دریای طوفانی", "ruins": "خرابه‌های باستانی", "city": "پایتخت درخشان"}
ROAD = "road"        # NPCِ در حال سفر

PHASES = {"dawn": ("🌅", "سپیده‌دم"), "day": ("☀️", "روز"), "dusk": ("🌆", "غروب"), "night": ("🌙", "شب")}


def world_clock(now: float, epoch: float, scale: int) -> dict:
    """ساعتِ پایدارِ دنیا: فقط تابعِ زمانِ واقعی؛ پس وقتی بازیکن/ربات خاموشه هم جلو میره."""
    minutes = int(max(0.0, now - epoch) / 60 * scale)
    hour = (minutes // 60) % 24
    phase = "dawn" if 5 <= hour < 8 else "day" if 8 <= hour < 17 else "dusk" if 17 <= hour < 20 else "night"
    return {"day": minutes // 1440 + 1, "hour": hour, "minute": minutes % 60, "phase": phase,
            "icon": PHASES[phase][0], "phase_fa": PHASES[phase][1]}


# ───────────────────────────── جناح‌ها ─────────────────────────────
FACTIONS = {
    "guards": {"name": "نگهبانانِ پایتخت", "icon": "🛡", "power": 50},
    "merchants": {"name": "اتحادیه‌ی تجار", "icon": "💰", "power": 50},
    "cabal": {"name": "کابالِ سایه", "icon": "🕶", "power": 40},
    "explorers": {"name": "حلقه‌ی کاشفان", "icon": "🧭", "power": 45},
}
FACTION_RELATIONS = {  # روابطِ اولیه (متقارن)
    ("guards", "merchants"): 25, ("guards", "cabal"): -45, ("guards", "explorers"): 10,
    ("merchants", "cabal"): -20, ("merchants", "explorers"): 15, ("cabal", "explorers"): -15,
}


def rel_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


# ───────────────────────────── NPCهای اولیه ─────────────────────────────
def _npc(id, name, icon, race, cls, occupation, traits, style, background, goals, faction, routine, ambition,
         important=True, trader=False, gold=0, emotion="آرام", rel=None):
    return {
        "id": id, "name": name, "icon": icon, "race": race, "cls": cls, "occupation": occupation,
        "personality": {"traits": traits, "style": style}, "background": background, "goals": goals,
        "faction": faction, "routine": routine, "location": routine["day"], "travel": None,
        "emotion": emotion, "plan": goals[0], "ambition": ambition, "important": important, "trader": trader,
        "gold": gold, "cargo": {}, "relationships": rel or {}, "bonds": {}, "memories": [], "summary": "",
        "opinions": {}, "known_rumors": [], "decision_due": 0, "talk_log": {},
    }


def _rt(d, dy, du, n):
    return {"dawn": d, "day": dy, "dusk": du, "night": n}


NPC_SEEDS = [
    _npc("old_man", "گریگورِ پیر", "👴", "انسان", "حکیم", "elder", ["وراج", "مهربان", "مرموز"],
         "آروم و پرحاشیه، وسط حرف‌هاش خاطره‌های صدساله می‌گه.",
         "گریگور نگهبانِ آخرین دهکده‌ی پیش از ظهورِ ایزدبانو بود و هنوز دنبالِ جوابِ یه سؤالِ قدیمیه.",
         ["پیدا کردنِ وارثِ دهکده", "نوشتنِ تاریخِ آخرین جنگ"], "explorers", _rt("forest", "forest", "city", "city"),
         "دیدنِ دهکده‌ی گم‌شده برای آخرین بار", rel={"tomas": 40, "sera": 15}),
    _npc("shop", "ولادیکِ بی‌اعتماد", "🧔", "انسان", "تاجر", "merchant", ["بدگمان", "حسابگر", "خسیس"],
         "کوتاه و شکاک؛ هر جمله‌ش یه سؤال یا یه قیمته.",
         "ولادیک یه بار با یه سکه‌ی تقلبی ورشکست شد و از اون موقع به هیچ‌کس اعتماد نمی‌کنه.",
         ["جمع کردنِ سکه‌های اصل", "پیدا کردنِ تأمین‌کننده‌ی ارزون"], "merchants", _rt("city", "city", "city", "city"),
         "تبدیل شدن به بزرگ‌ترین تاجرِ ایسکا", trader=True, gold=450, rel={"mara": 20, "borin": 10, "dray": -25}),
    _npc("cafe", "ماریوسِ فیلسوف", "☕", "انسان", "کافه‌دار", "innkeeper", ["فیلسوف", "غمگین", "آرام"],
         "شعرگونه و تلخ؛ از قهوه برای حرف زدن از مرگ استفاده می‌کنه.",
         "ماریوس قبلاً شاگردِ یه جادوگرِ بزرگ بود؛ حالا فقط قهوه می‌جوشونه و سؤال می‌پرسه.",
         ["پیدا کردنِ بهترین دانه‌ی قهوه", "فهمیدنِ معنیِ زندگی"], "merchants", _rt("city", "forest", "city", "city"),
         "ساختنِ کافه‌ای که همه‌ی ایسکا توش بنشینن", important=False, rel={"sera": 30}),
    _npc("guard", "کاپیتان هِلگا", "💂", "انسان", "نگهبان", "guard", ["جدی", "کم‌حوصله", "وظیفه‌شناس"],
         "رسمی و خشک؛ همیشه یه چشمش به دور و بره.",
         "هلگا از ارتشِ پادشاه اومده و حالا بی‌حوصله پاسبانی می‌کنه و هنوز به کابال مشکوکه.",
         ["مهارِ کابالِ سایه", "آموزشِ نگهبانانِ جوان"], "guards", _rt("city", "sea", "ruins", "city"),
         "فرماندهیِ کلِ نگهبانانِ ایسکا", rel={"dray": -45, "kael": -10, "tomas": 20}),
    _npc("witch", "اوندینِ ناراضی", "🧙‍♀️", "الف", "جادوگر", "witch", ["شاکی", "تیزبین", "کنایه‌زن"],
         "کنایه‌دار و گزنده؛ هیچ‌وقت راضی نیست ولی همیشه کمک می‌کنه.",
         "اوندین یه طلسمِ ممنوعه رو آزمایش کرد و از اون موقع هر چیزی که می‌خنده بهش مشکوکه.",
         ["جمعِ گیاهانِ نادر", "پیدا کردنِ طلسمِ گمشده"], "cabal", _rt("forest", "ruins", "forest", "city"),
         "شکستنِ نفرینی که روی خودشه", rel={"nia": 25, "dray": 5}),
    _npc("borin", "بورینِ آهنگر", "🔨", "کوتوله", "آهنگر", "blacksmith", ["مغرور", "صادق", "پرحرارت"],
         "بلند و رک؛ هر چیزی رو با فلز مقایسه می‌کنه.",
         "بورین سه نسل شمشیرساز بوده و معتقده هیچ تیغی بدونِ غرورِ سازنده‌ش ارزش نداره.",
         ["پیدا کردنِ سنگ‌معدنِ ناب", "ساختنِ شمشیرِ شاهکار"], "merchants", _rt("city", "city", "city", "city"),
         "ساختنِ تیغی که اسمِ ایسکا رو جاودان کنه", important=False, rel={"shop": 10, "mara": 15}),
    _npc("mara", "مارا کاروان‌دار", "🐪", "انسان", "تاجر", "merchant", ["شاد", "زیرک", "ماجراجو"],
         "پرانرژی و خندون؛ هر جمله‌ش یه فرصتِ فروشه.",
         "مارا کاروانش رو از صفر ساخت و عاشقِ جاده‌ست؛ همیشه دنبالِ مسیر یا بازارِ تازه‌ست.",
         ["بازکردنِ راه‌های تجاریِ جدید", "استخدامِ ماجراجویِ مطمئن"], "merchants", _rt("city", "sea", "sea", "city"),
         "ساختنِ شبکه‌ی کاروانیِ سراسری", trader=True, gold=520, rel={"shop": 20, "borin": 15, "lyra": 20}),
    _npc("tomas", "ریش‌سفید تُماس", "🧓", "انسان", "رهبر", "leader", ["دلسوز", "محتاط", "خسته"],
         "آرام و با متانت؛ برای هر مشکلی اول سکوت می‌کنه.",
         "تماس رهبرِ دهکده‌ی حاشیه‌ی جنگله و مسئول جونِ ده‌ها خانواده‌ست.",
         ["محافظت از دهکده", "گرفتنِ کمک از گیلدها"], "explorers", _rt("forest", "forest", "forest", "forest"),
         "برقراری صلحِ پایدار تو جنگل", rel={"old_man": 40, "guard": 20, "lyra": 15}),
    _npc("kael", "کائلِ رقیب", "⚔️", "انسان", "جنگجو", "adventurer", ["مغرور", "رقابت‌جو", "شجاع"],
         "پرهیاهو و طعنه‌زن؛ همه‌چیز رو مسابقه می‌بینه.",
         "کائل عضوِ یه گیلدِ رقیبه و هنوز نمی‌بخشه که بهش «مبتدی» گفتن.",
         ["شکستنِ رکوردِ گیلدِ رقیب", "کشتنِ هیولای خرابه"], "guards", _rt("ruins", "ruins", "city", "city"),
         "اولین قهرمانِ ثبت‌شده‌ی ایسکا", rel={"lyra": -30, "guard": -10, "sera": 10}),
    _npc("lyra", "لیرایِ کاشف", "🏹", "الف", "کماندار", "adventurer", ["کنجکاو", "آرام", "مستقل"],
         "کم‌حرف و دقیق؛ از جاده‌ها و ستاره‌ها حرف می‌زنه.",
         "لیرا مسیرهای ناشناخته رو نقشه می‌کنه و به هیچ گیلدی وفادار نیست.",
         ["نقشه‌کشیِ ناحیه‌ی ناشناخته", "پیدا کردنِ دروازه‌ی گم‌شده"], "explorers", _rt("forest", "forest", "sea", "city"),
         "کشفِ آخرین سرزمینِ ناشناخته", rel={"kael": -30, "mara": 20, "tomas": 15}),
    _npc("sera", "سرایِ خنیاگر", "🎻", "نیم‌الف", "خنیاگر", "bard", ["بذله‌گو", "فضول", "جذاب"],
         "پرحرارت و نمایشی؛ هر خبری رو قصه می‌کنه.",
         "سرا شهر به شهر آواز می‌خونه و بیشتر از آواز، خبر و شایعه می‌فروشه.",
         ["جمع کردنِ بهترین شایعه‌ها", "نوشتنِ ترانه‌ی یه قهرمان"], "merchants", _rt("city", "city", "sea", "city"),
         "ساختنِ ترانه‌ای که هیچ‌وقت فراموش نشه", rel={"cafe": 30, "kael": 10, "old_man": 15}),
    _npc("dray", "درای سایه‌دار", "🕶", "انسان", "دزد", "outlaw", ["محتاط", "حیله‌گر", "خونسرد"],
         "کم‌حرف و دوپهلو؛ همیشه نیمی از واقعیت رو می‌گه.",
         "درای رهبرِ کابالِ سایه‌ست و همه‌ی قاچاقِ خرابه‌ها از دست اون رد میشه.",
         ["گسترشِ نفوذ در پایتخت", "پیدا کردنِ خزانه‌ی گمشده"], "cabal", _rt("ruins", "ruins", "city", "ruins"),
         "کنترلِ کاملِ بازارِ سیاهِ ایسکا", rel={"guard": -45, "shop": -25, "witch": 5}),
    _npc("nia", "نیا شاگرد جادوگر", "🔮", "انسان", "جادوگر", "apprentice", ["کنجکاو", "خجالتی", "مضطرب"],
         "تپق‌زن و پرسشگر؛ بیشتر از جواب، سؤال داره.",
         "نیا شاگردِ اوندینه و می‌ترسه که هیچ‌وقت به اندازه‌ی استادش نشه.",
         ["یادگرفتنِ اولین طلسمِ واقعی", "ساکت نموندنِ استاد"], "cabal", _rt("city", "city", "ruins", "city"),
         "تبدیل شدن به جادوگرِ بزرگِ ایسکا", important=False, rel={"witch": 25}),
]
NPC_IDS = [n["id"] for n in NPC_SEEDS]


# ───────────────────────────── اقتصاد ─────────────────────────────
RESOURCES = {"herbs": "گیاهان", "ore": "سنگ‌معدن", "cloth": "پارچه", "relics": "یادگارها", "food": "آذوقه"}
SUPPLY_MIN, SUPPLY_MAX = 20, 180


def item_resource(name: str) -> str:
    keys = list(RESOURCES)
    return keys[zlib.crc32(name.encode("utf-8")) % len(keys)]


def price_mult(supply: float, bias: float = 0.0) -> float:
    """ضریبِ قیمت: عرضه‌ی کم = گران، عرضه‌ی زیاد = ارزان. محدود به ۰٫۷ تا ۱٫۷."""
    return round(max(0.7, min(1.7, (100.0 + bias) / max(float(SUPPLY_MIN), float(supply)))), 2)


def initial_economy(rng: random.Random) -> dict:
    return {
        "supply": {r: {k: rng.randint(80, 120) for k in RESOURCES} for r in REGIONS},
        "bias": {r: {k: rng.randint(-15, 15) for k in RESOURCES} for r in REGIONS},
    }


def clamp_supply(v: float) -> int:
    return int(max(SUPPLY_MIN, min(SUPPLY_MAX, v)))


# ───────────────────────────── رویدادها ─────────────────────────────
# mods.w: ضریبِ وزنِ نوعِ رخداد در گشت؛ ok/fail: پیامدهای پایان (danger/prosperity: ۰..۱۰۰، supply، power جناح)
EVENT_TYPES = {
    "monster_migration": {"regions": ["forest", "ruins", "sea"], "w": 3, "diff": (2, 4), "hours": (2, 4), "icon": "🐾",
                          "title": "مهاجرتِ هیولاها به {r}", "desc": "گله‌ای از هیولاها از {r} رد میشن. گشت اونجا خطرناک‌تره ولی غنیمت بیشتری داره.",
                          "mods": {"monster": 1.6, "trap": 1.15},
                          "ok": {"danger": -12, "prosperity": 4, "supply": {"food": 10}}, "fail": {"danger": 15, "prosperity": -6, "supply": {"food": -15}}},
    "new_dungeon": {"regions": ["ruins", "forest"], "w": 2, "diff": (2, 5), "hours": (3, 5), "icon": "🕳",
                    "title": "دخمه‌ی تازه در {r}", "desc": "ورودیِ یه دخمه‌ی ناشناخته تو {r} باز شده؛ گنج زیاد، خطر زیاد.",
                    "mods": {"find": 1.35, "death": 1.2},
                    "ok": {"danger": 5, "prosperity": 8, "supply": {"relics": 20}}, "fail": {"danger": 10, "prosperity": -3, "supply": {}}},
    "caravan_lost": {"regions": ["sea", "forest"], "w": 2, "diff": (2, 3), "hours": (2, 4), "icon": "🐪",
                     "title": "گم شدنِ کاروانِ تجاری در {r}", "desc": "کاروانِ بزرگی تو {r} گم شده. بازارها دارن خالی میشن.",
                     "mods": {"trap": 1.25},
                     "ok": {"danger": -4, "prosperity": 5, "supply": {"cloth": 15, "ore": 10}},
                     "fail": {"danger": 6, "prosperity": -8, "supply": {"cloth": -20, "ore": -15, "food": -10}}, "power": {"merchants": 6}},
    "guild_war": {"regions": ["city"], "w": 1, "diff": (3, 4), "hours": (2, 3), "icon": "⚔️",
                  "title": "اعلامِ جنگِ گیلدها در {r}", "desc": "تنش بینِ نگهبانان و کابال بالا گرفته و خیابون‌های {r} ناامنن.",
                  "mods": {"monster": 1.25, "death": 1.15},
                  "ok": {"danger": -10, "prosperity": 3, "supply": {}}, "fail": {"danger": 14, "prosperity": -8, "supply": {}},
                  "power": {"guards": 6, "cabal": -6}},
    "rare_resource": {"regions": ["forest", "sea", "ruins"], "w": 2, "diff": (1, 3), "hours": (2, 4), "icon": "💎",
                      "title": "کشفِ منبعِ کمیاب در {r}", "desc": "یه رگه‌ی نادر تو {r} پیدا شده. هر کسی زودتر برسه سود می‌بره.",
                      "mods": {"find": 1.5},
                      "ok": {"danger": 0, "prosperity": 10, "supply": {"ore": 25, "relics": 10}}, "fail": {"danger": 2, "prosperity": 0, "supply": {}}},
    "regional_threat": {"regions": REGIONS, "w": 2, "diff": (3, 5), "hours": (3, 5), "icon": "☠️",
                        "title": "تهدیدِ تازه در {r}", "desc": "یه موجودِ قدرتمند تو {r} ظاهر شده و منطقه رو به وحشت انداخته.",
                        "mods": {"monster": 1.4, "death": 1.2},
                        "ok": {"danger": -18, "prosperity": 6, "supply": {}}, "fail": {"danger": 20, "prosperity": -10, "supply": {"food": -10}}},
    "prosperity": {"regions": ["city", "sea"], "w": 2, "diff": (1, 2), "hours": (2, 4), "icon": "🎉",
                   "title": "رونقِ بازار در {r}", "desc": "رونق و جشن تو {r}؛ مردم سخاوتمندن و گشت امن‌تره.",
                   "mods": {"find": 1.2, "heal": 1.2, "trap": 0.85},
                   "ok": {"danger": -4, "prosperity": 10, "supply": {"food": 12}}, "fail": {"danger": 0, "prosperity": 2, "supply": {}}},
    "decline": {"regions": ["forest", "sea"], "w": 1, "diff": (1, 3), "hours": (2, 4), "icon": "🥀",
                "title": "افولِ دهکده‌های {r}", "desc": "قحطی و مهاجرت {r} رو ضعیف کرده؛ شفا کمیابه.",
                "mods": {"heal": 0.8, "trap": 1.1},
                "ok": {"danger": 0, "prosperity": 6, "supply": {"food": 12}}, "fail": {"danger": 4, "prosperity": -10, "supply": {"food": -15}}},
    "world_boss": {"regions": REGIONS, "w": 0.4, "diff": (5, 5), "hours": (3, 5), "icon": "🐉",
                   "title": "بیداری‌ی غولِ {r}", "desc": "چیزی عظیم تو {r} بیدار شده؛ همه‌ی ایسکا لرزید.",
                   "mods": {"monster": 1.8, "death": 1.3},
                   "ok": {"danger": -25, "prosperity": 12, "supply": {"relics": 25}}, "fail": {"danger": 25, "prosperity": -15, "supply": {"food": -20, "ore": -15}}},
}
EVENT_GOLD_CAP, EVENT_XP_CAP = 120, 100


def event_target(diff: int) -> int:
    return 2 + 2 * diff


def event_reward(diff: int) -> dict:
    return {"gold": min(EVENT_GOLD_CAP, 25 * diff), "xp": min(EVENT_XP_CAP, 20 * diff)}


def weight_multipliers(region_state: dict, active_events: list) -> dict:
    """ضریبِ وزنِ رخدادهای گشت برای یه منطقه: از خطر/رونقِ منطقه + مودِ رویدادهای فعال. سقفِ ۰٫۶ تا ۲٫۲."""
    m = {"find": 1.0, "monster": 1.0, "heal": 1.0, "trap": 1.0, "death": 1.0, "lore": 1.0}
    d = (region_state or {}).get("danger", 50)
    p = (region_state or {}).get("prosperity", 50)
    if d > 60:
        m["monster"] *= 1.2; m["trap"] *= 1.1
    elif d < 35:
        m["monster"] *= 0.85; m["death"] *= 0.9
    if p > 60:
        m["find"] *= 1.15; m["heal"] *= 1.1
    elif p < 35:
        m["find"] *= 0.85; m["heal"] *= 0.9
    for ev in active_events:
        for k, v in (ev.get("mods") or {}).items():
            if k in m:
                m[k] *= float(v)
    return {k: round(max(0.6, min(2.2, v)), 2) for k, v in m.items()}


# ───────────────────────────── تعامل NPC با NPC ─────────────────────────────
def pick_interaction(a: dict, b: dict, fac_rel: int, rng: random.Random) -> Optional[dict]:
    """تعاملِ سبکِ پایتونی بینِ دو NPC هم‌مکان. خروجی: {kind, delta, text, rumor, ...} یا None."""
    A, B = a["name"], b["name"]
    oa, ob = a["occupation"], b["occupation"]
    rel = a["relationships"].get(b["id"], 0)
    pair = {oa, ob}
    if pair == {"merchant", "blacksmith"} and rng.random() < 0.7:
        return {"kind": "trade", "delta": 2, "text": f"{A} و {B} سرِ قیمتِ سنگ‌معدن چانه زدن و معامله بستن.", "rumor": False, "ore": rng.choice([-6, 6])}
    if "merchant" in pair and "adventurer" in pair and rng.random() < 0.35:
        return {"kind": "hire", "delta": 5, "text": f"{A if oa == 'merchant' else B} یه ماجراجو ({B if oa == 'merchant' else A}) رو برای محافظتِ کاروان استخدام کرد.",
                "rumor": True, "hire": True}
    if "leader" in pair and ("adventurer" in pair or "guard" in pair) and rng.random() < 0.4:
        return {"kind": "help", "delta": 3, "text": f"{A if oa == 'leader' else B} از {B if oa == 'leader' else A} برای محافظتِ دهکده کمک خواست.", "rumor": True, "help": True}
    if fac_rel <= -30 and rng.random() < 0.55:
        return {"kind": "argue", "delta": -4, "text": f"{A} و {B} سرِ نفوذ تو منطقه با هم جر و بحث کردن.", "rumor": rng.random() < 0.4}
    if rel <= -25 and rng.random() < 0.5:
        return {"kind": "argue", "delta": -3, "text": f"{A} و {B} دوباره به هم تیکه انداختن.", "rumor": rng.random() < 0.3}
    if rel >= 45 and not a["bonds"].get(b["id"]) and "romance" not in (a.get("tags") or []) and rng.random() < 0.06:
        return {"kind": "romance", "delta": 6, "text": f"می‌گن بینِ {A} و {B} یه چیزی هست…", "rumor": True, "bond": "lovers"}
    if fac_rel >= 30 and rng.random() < 0.08:
        return {"kind": "alliance", "delta": 3, "text": f"نمایندگان {A} و {B} یه قرارِ همکاریِ موقت گذاشتن.", "rumor": True, "alliance": True}
    if rng.random() < 0.6:
        return {"kind": "chat", "delta": 1, "text": f"{A} و {B} با هم گپ زدن.", "rumor": False}
    return None


# ───────────────────────────── حرف‌های fallback ─────────────────────────────
FALLBACK_LINES = {
    "مهربان": ["«سلام {p}! بشین یه دم؛ دنیا خیلی تند می‌گذره.»", "«از دیدنت خوشحالم {p}. مواظبِ خودت باش.»"],
    "وراج": ["«آهای {p}! می‌دونی چقدر وقته کسی بهم گوش نداده؟ بذار برات بگم…»", "«{p}؟ اوه، من یه بار تو همین‌جا یه اژدها دیدم… البته شاید مرغ بود.»"],
    "بدگمان": ["«تو، {p}. دستات رو بذار جایی که ببینم.»", "«چی می‌خوای؟ هیچ‌چیز مفت نیست، حتی نگاه کردن.»"],
    "فیلسوف": ["«می‌دونی {p}؟ قهوه و مرگ هر دو تلخن؛ فقط یکی‌شون برمی‌گرده.»", "«سلام {p}. هر که می‌میره، یه سؤال جا می‌ذاره.»"],
    "جدی": ["«{p}. وضعیت؟ گزارش بده، بعد برو.»", "«اینجا امن نیست. مراقب باش.»"],
    "شاکی": ["«وای، {p}. حتماً چیزی خواستی. همیشه یه چیزی می‌خوان.»", "«سلام. نه، نمی‌دونم برای چی ناراحتم. فقط هستم.»"],
    "مغرور": ["«{p}! خوبه که به دیدنِ بهترین‌ها اومدی.»", "«تو؟ باشه. ولی حواست باشه من اینجا تازه‌واردها رو می‌سنجم.»"],
    "شاد": ["«هی {p}! خبرِ خوب دارم، خبرِ بدشم دارم؛ کدوم رو اول؟»", "«{p}! امروز یه روز خوبه، مگه نه؟ معامله‌ای نمی‌خوای؟»"],
    "دلسوز": ["«سلام {p}. اگه کمکی از دستت برمیاد، دهکده ممنونت می‌شه.»", "«سخته؛ ولی با هم از پسش برمیایم.»"],
    "بذله‌گو": ["«{p}! تو الان یه ترانه‌ای! حالا فقط باید یه ماجرا هم بسازی.»", "«بیا بشین؛ خبرای داغِ امروز رو بگم.»"],
    "محتاط": ["«…{p}. صداتو بیار پایین. دیوارها گوش دارن.»", "«کسی دنبالت نیست؟ نه؟ خوب.»"],
    "کنجکاو": ["«{p}! تو هم حس کردی هوا امروز عجیبه؟»", "«می‌شه یه سؤال بپرسم؟ …نه، بذار اول فکر کنم.»"],
    "_": ["«سلام {p}. روزِ عجیبیه، نه؟»", "«{p}. دنیا بی‌رحمه؛ ولی هنوز راه هست.»"],
}


def fallback_line(npc: dict, player_name: str) -> str:
    """بدونِ «» (صدازننده خودش می‌پیچه)."""
    for t in npc["personality"]["traits"]:
        if t in FALLBACK_LINES:
            return random.choice(FALLBACK_LINES[t]).replace("{p}", player_name).strip("«»")
    return random.choice(FALLBACK_LINES["_"]).replace("{p}", player_name).strip("«»")


def opinion_label(score: int) -> str:
    return ("😍 عاشقِ تو" if score >= 60 else "🙂 دوستانه" if score >= 25 else "😐 بی‌تفاوت" if score > -25
            else "😒 ناراضی" if score > -60 else "😡 دشمن")


NEWS_TEMPLATES = {
    "event_start": "📣 {icon} {title}!",
    "event_ok": "✅ مردم تونستن «{title}» رو مهار کنن.",
    "event_fail": "❌ «{title}» مهار نشد و پیامدهاش به منطقه رسید.",
}
