"""جوابِ «ربط‌دار» بدونِ AI برای NPCها (وقتی OpenRouter جواب نمیده).

قانون: فقط وقتی جواب میده که قصدِ پیامِ بازیکن رو با قاعده تشخیص داده (معرفی، کارها، حال، رفتن/حافظه، کار، شایعه، معامله،
تشکر، خداحافظی) و جواب فقط از دیتای خودِ همون NPC (نام، شغل، پس‌زمینه، حال، برنامه، نظر) ساخته میشه. اگه قصد تشخیص داده نشد،
NPC صادقانه میگه نفهمیده و راه‌های پرسیدن رو نشون میده؛ هیچ‌وقت جمله‌ی بی‌ربط نمیگه. هیچ‌چیزی از مکانیکِ بازی قول داده نمیشه.
"""

import re
from typing import Optional

OCC_FA = {"elder": "پیرمرد", "merchant": "تاجر", "innkeeper": "کافه‌دار", "guard": "نگهبان", "witch": "جادوگر",
          "blacksmith": "آهنگر", "leader": "رهبر دهکده", "adventurer": "ماجراجو", "bard": "خنیاگر",
          "outlaw": "سردسته‌ی کابال", "apprentice": "شاگرد", "goddess": "ایزدبانو"}

SERVICE = {
    "elder": "از دهکده و گذشته‌ی ایسکا برات می‌گم و گاهی ماموریت دارم.",
    "merchant": "خرید و فروش و قیمت‌های منطقه؛ معامله‌ی روز رو من پیشنهاد می‌دم.",
    "innkeeper": "قهوه، شایعه و یه کم فلسفه‌ی تلخ.",
    "guard": "از شهر مراقبت می‌کنم و از خطرها و گشت‌ها خبر دارم.",
    "witch": "معجون و طلسم و اگه روحت ترک خورده باشه، ترمیمش.",
    "blacksmith": "تجهیز و ارتقای سلاح و زره‌ات تو کوره‌ی روح.",
    "leader": "غصه‌ی دهکده رو می‌خورم و دنبال کمک برای مشکلاتش‌ام.",
    "adventurer": "راه‌ها و خطرها رو می‌شناسم و گاهی خبرِ ماجراجویی دارم.",
    "bard": "ترانه، خبر و شایعه.",
    "outlaw": "ماجراهای پشتِ پرده؛ که خیلی هم نباید بدونی.",
    "apprentice": "یاد می‌گیرم و گاهی یه کمک کوچیک می‌کنم.",
    "goddess": "گوش می‌دم، کنایه می‌زنم و گاهی دل‌داری می‌دم؛ بیشتر از این از یه ایزدبانو نخواه.",
}

# ترتیب مهمه: قصدهای مشخص‌تر اول
INTENTS = [
    ("bye", r"(خداحافظ|فعلا|فعلاً|بای|به امید دیدار)"),
    ("thanks", r"(ممنون|مرسی|تشکر|دمت گرم)"),
    ("intro", r"(معرفی|کی هستی|تو کی|اسمت|چیکاره|چه کاره|کی ای|who are you)"),
    ("abilities", r"(چه کار(ی)?|چی کار|چکار|چه کمکی|می ?تونی|میتونی|بلدی|چه خدمات)"),
    ("how", r"(حالت|چطوری|احوال|خوبی|حال شما)"),
    ("leave", r"(برم|میرم|می رم|ترک|برگردم|یادت|یادم|فراموش|دوباره ببینمت|دلت تنگ)"),
    ("work", r"(کار داری|کاری داری|ماموریت|مأموریت|درخواستی|شغلی)"),
    ("rumor", r"(شایعه|چه خبر|اخبار|خبری|شنیدی)"),
    ("price", r"(قیمت|بخرم|بفروشم|معامله|خرید|فروش|تخفیف|چند میشه|چنده)"),
    ("greet", r"(سلام|درود|وقت بخیر|صبح بخیر|شب بخیر|hello|hi\b)"),
]


def norm(s) -> str:
    s = str(s or "").lower().replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def detect(say: str) -> list:
    t = norm(say)
    return [k for k, rx in INTENTS if re.search(rx, t)]


def _first_sentence(txt: str) -> str:
    return (txt or "").split(".")[0].strip()


def _answer(kind: str, npc: dict, p: str, op: int) -> Optional[str]:
    occ = npc.get("occupation", "")
    goddess = npc.get("id") == "goddess"
    if kind == "intro":
        return f"من {npc['name']}ام، {OCC_FA.get(occ, occ)} ({npc.get('race', '')}). {_first_sentence(npc.get('background', ''))}."
    if kind == "abilities":
        return SERVICE.get(occ, "کارِ من همین‌جاست و بیشتر از این نمی‌گم.")
    if kind == "how":
        return f"حالم «{npc.get('emotion', 'آروم')}»ـه و فکرم پیشِ «{npc.get('plan', 'کارای خودم')}»ـه."
    if kind == "leave":
        mood = ("ازت خوشم میاد؛ برگردی خوشحال می‌شم." if op >= 25 else
                "نه که دلم برات تنگ بشه…" if op <= -25 else f"اسمت رو یادم می‌مونه {p}، ولی هنوز زیاد نمی‌شناسمت.")
        return f"اگه بری هم «{npc.get('plan', 'کارام')}» ادامه داره. {mood}"
    if kind == "work":
        return ("کارِ من پایان دادنه؛ برو ماجراجویی کن، بعد بیا." if goddess
                else "برای کار و ماموریت دکمه‌ی «📜 کار داری؟» رو بزن.")
    if kind == "rumor":
        return ("شایعه‌ها همه از دروازه‌ی من رد میشن؛ ولی تعریفشون با تو نیست." if goddess
                else "برای شایعه دکمه‌ی «🗞 شایعه» رو بزن.")
    if kind == "price":
        return ("اینجا قیمتی نیست؛ جونتون بی‌قیمته." if goddess else
                "معامله‌ی امروز پیش منه؛ بنویس «مغازه‌دار» تا پیشنهادش رو ببینی." if npc.get("trader")
                else "من تاجر نیستم؛ برای معامله سراغ مغازه‌دار برو.")
    if kind == "thanks":
        return f"خواهش می‌کنم {p}."
    if kind == "bye":
        return f"به سلامت {p}؛ هر وقت خواستی برگرد."
    return None


def relevant_fallback(npc: dict, pname: str, say: str, op: int = 0) -> Optional[str]:
    """جوابِ ربط‌دار از دیتای همین NPC. None = فقط سلام بوده (صدازننده جمله‌ی سلامِ خودِ NPC رو می‌ده)."""
    kinds = detect(say)
    content = [k for k in kinds if k != "greet"]
    if not content:
        if kinds == ["greet"]:
            return None
        return (f"{pname}، دقیق نفهمیدم چی می‌پرسی. بپرس «کی هستی؟»، «چه کاری می‌تونی بکنی؟»، «حالت چطوره؟» "
                "یا از دکمه‌ها «شایعه» و «کار داری؟» رو بزن.")
    parts = [a for a in (_answer(k, npc, pname, op) for k in content[:2]) if a]
    return " ".join(parts)
