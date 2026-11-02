"""
@IsekaiGraveBot — ایسکای‌ِ متنیِ رنگی با ایزدبانوی بی‌حوصله
Stack: aiogram 3.x + motor (MongoDB) | Deploy: Railway (long polling worker)

ENV:
  TELEGRAM_BOT_TOKEN  (required)
  MONGO_URI           (required)
  MONGO_DB_NAME       (optional, default: isekai_grave)
  RANDOM_DROP_CHANCE  (optional, default: 0.02)

نکته: از BotFather گزینه‌ی Group Privacy رو Disable کن تا ربات پیام‌های عادی گروه رو ببینه.

🎨 رنگی‌سازی پنل‌ها:
تلگرام رنگ متن نمی‌پذیره، پس پنل‌ها با «قاب ایموجیِ رنگی» (🟥🟧🟨🟩🟦🟪⬛) رنگ‌بندی میشن:
هر زیست‌بوم/سیستم یه رنگ مخصوص داره، نوار بقا بسته به مقدارش سبز/زرد/قرمز میشه،
و آیتم‌ها با ایموجیِ کمیابی (⬜🟩🟦🟪🟨🟥) رنگی نمایش داده میشن.
"""

import asyncio
import html
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message, User
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("isekai-grave")

# ───────────────────────────── Config ─────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "isekai_grave")
RANDOM_DROP_CHANCE = float(os.getenv("RANDOM_DROP_CHANCE", "0.02"))
HERALD_CHANCE = 0.04

DROP_COOLDOWN = 20 * 60
SELF_DEATH_COOLDOWN = 20
FORCED_TARGET_COOLDOWN = 120
HERALD_COOLDOWN = 30 * 60
OFFER_TTL = 15 * 60
EXPLORE_COOLDOWN = 12          # ثانیه بین دو سفر
WHEEL_COOLDOWN = 24 * 3600     # گردونه‌ی شانس
DUEL_TTL = 3 * 60              # مهلت قبول دوئل
GUILD_WAR_COOLDOWN = 30 * 60
GUILD_COST = 60                # هزینه‌ی ساخت گیلد (طلا)
GUILD_MAX_MEMBERS = 30
START_GOLD = 100

store: "Store" = None  # type: ignore
BOT_USERNAME = ""

# ───────────────────────────── 🎨 Color system ─────────────────────────────
SQ = {
    "red": "🟥", "orange": "🟧", "yellow": "🟨", "green": "🟩",
    "blue": "🟦", "purple": "🟪", "black": "⬛", "white": "⬜", "brown": "🟫",
}

# کمیابی آیتم‌ها: (نام، ایموجی رنگی، وزن، ارزش طلا)
RARITIES = [
    ("معمولی", "⬜", 50, 5),
    ("غیرمعمول", "🟩", 25, 12),
    ("نادر", "🟦", 14, 30),
    ("حماسی", "🟪", 7, 70),
    ("افسانه‌ای", "🟨", 3, 150),
    ("نفرین‌شده", "🟥", 1, 0),
]


def banner(color: str, n: int = 7) -> str:
    return SQ.get(color, "⬜") * n


def panel(color: str, icon: str, title: str, lines: list, foot: Optional[str] = None) -> str:
    """پنل رنگی: قاب ایموجیِ رنگی + بلاک‌کوت. lines باید از قبل HTML-safe باشن."""
    s = f"{banner(color)}\n{icon} <b>{esc(title)}</b>\n{banner(color)}\n<blockquote>" + "\n".join(lines) + "</blockquote>"
    if foot:
        s += "\n" + foot
    return s


def hp_bar(rate: int) -> str:
    """نوار بقای رنگی: سبز (امن) / زرد (خطر) / قرمز (بحرانی)."""
    rate = max(0, min(100, rate))
    n = round(rate / 10)
    cell = "🟩" if rate >= 60 else ("🟨" if rate >= 30 else "🟥")
    return cell * n + "⬛" * (10 - n)


def xp_bar(xp: int) -> str:
    n = max(0, min(10, (xp % 100) // 10))
    return "🟦" * n + "⬛" * (10 - n)


def roll_item(pool: list) -> tuple:
    """برمی‌گردونه (متن آیتم با ایموجی رنگی، ایندکس کمیابی، ارزش)."""
    idx = random.choices(range(len(RARITIES)), weights=[r[2] for r in RARITIES])[0]
    rname, emoji, _, val = RARITIES[idx]
    return f"{emoji} {random.choice(pool)} ‹{rname}›", idx, val


# ───────────────────────────── Content ─────────────────────────────
FORMS = [
    ("اسلایمِ افسرده‌ی طبقه‌ی دوم", "اسلایمِ افسرده‌ی سابق"),
    ("یک لنگه کفشِ چپِ بی‌جفت که ذهن داره", "کفشِ چپِ فیلسوف"),
    ("شمشیر جادویی‌ای که فقط کره‌بادام‌زمینی می‌بُره", "شمشیرزنِ کره‌بادام‌زمینی"),
    ("مرغ دریایی‌ای که از همه چیز می‌ترسه", "مرغِ ترسوی ایسکای"),
    ("تابلوی «ورود ممنوع» که همه ازش رد میشن", "تابلوی نادیده‌گرفته‌شده"),
    ("گربه‌ی خداگونه‌ای که فقط می‌خوابه", "گربه‌ی خدای تنبل"),
    ("آسانسور هوشمند در برج پادشاه شیطان", "آسانسورِ بدخلق"),
    ("لیوان چایی که آرزوی پادشاهی داره", "شاهِ لیوانی"),
    ("اژدهای وگان سه‌متری که از آتیش‌بازی می‌ترسه", "اژدهای وگانِ ترسو"),
    ("لوله‌ی بخاری که ورد می‌خونه", "جادوگرِ لوله‌بخاری"),
    ("پیتزای آناناسی در دنیای ایتالیایی‌ها", "پیتزای محکوم‌به‌اعدام"),
    ("قهرمانی با HP برابر یک و لقب «خوش‌شانس»", "قهرمانِ HP یک"),
    ("پشه‌ی ۵ ستاره‌ی نادر در گاچا", "پشه‌ی SSR"),
    ("وای‌فای ضعیفِ قلعه‌ی شیطان", "مودمِ لعنتی"),
]
FORM_TITLE = dict(FORMS)

CHEATS = [
    "تبدیل هر آب‌میوه‌ای به آب‌پرتقالِ ولرم",
    "شنیدن صدای همه‌ی پریزها وقتی خالی‌ان",
    "لول‌آپ شدن با هر عطسه (فقط وقتی خوابی)",
    "ضدگلوله بودن در برابر نامه‌های ناخوانده",
    "تله‌پورت ۳۰ سانتی‌متری، فقط به عقب",
    "صحبت با ماهی‌های تو بشقاب (ازشون متنفرن)",
    "اورا حماسی با ۴ ثانیه تأخیر",
    "ریجنریشن HP… فقط ۱ تا و فقط روزهای شنبه",
    "شناسایی خودکار نزدیک‌ترین دستشویی در هر دنیا",
    "افکت نور درخشان هنگام باز کردن بسته‌ی چیپس",
    "فراخوانی یک مرغ که فقط می‌تونه نصیحت کنه",
    "ترجمه‌ی هر زبانی به «باشه عزیزم»",
]

WORLDS = [
    "یخچالستان — هر چی بخوری یخ می‌زنی",
    "سرزمین ساندویچ‌های متحرک",
    "قلمرو ابری‌ای که اینترنتش ۲G ـه",
    "پادشاهی کفش‌های گمشده",
    "جنگل اسلایم‌های افسرده",
    "برج نامرئیِ پادشاه شیطانِ بیکار",
    "دنیای پیکسلیِ شهر ۸ بیتی",
    "قاره‌ی کارمندهای دائماً خسته‌ی ماوراء",
    "جزیره‌ی طلسم‌شده‌ی سلفی‌ها",
    "ایالت متحده‌ی چایِ سرد",
]

SCENES = [
    "{n} وسط خیابون داشت به فصل آخر یه انیمه فکر می‌کرد که کامیونِ تقدیر با پلاک «ISEKAI-777» از پشت اومد. راننده فقط گفت: «اوه، باز یکی دیگه.» 🚚💥",
    "{n} ساعت ۳ شب یه کاسه رامنِ داغ رو بلعید. رشته‌ی آخر تصمیم گرفت وارد جنگ بشه. رشته در گلو برنده شد. ناک‌اوت فنی. 🍜☠️",
    "{n} رو پوست موز پا گذاشت، ۴ ثانیه توی هوا موند، یه مونولوگ حماسی ۳ دقیقه‌ای تو ذهنش گفت، بعد با پشت‌گردن آغوش زمین رو تجربه کرد. 🍌",
    "{n} خواست مثل قهرمان‌ها شمشیر رو به آسمان بگیره؛ شمشیر (جارو بود) به پنکه‌ی سقفی خورد. پنکه برنده شد. جارو استعفا داد. 🧹",
    "{n} تو ۴۳امین بحث «فصل دو بدتره یا فصل یک؟» رگ غیرتش زد بالا. آخرین پیامش: «ولی تو کلاً سلیقه نداری». سیستم خاموش شد. 💻",
    "گوشی {n} یک درصد بود، شارژر ۳ متر اون‌ورتر. با بی‌خیالیِ یه قهرمان رفت سمتش. وسط راه، گوشی مرد. بعدش {n}. به ترتیب. 🔋",
    "{n} به یه دختر تسوندره اعتراف کرد. جواب: «ب-بی‌شعور!!» و یه کفش پاشنه‌بلند با سرعت مافوق صوت. فیلم رو شکستن، فکر کردن اکشنه. 👠",
    "{n} تو پول ۹۰ام گاچا هنوز SSR نگرفته بود. یه پول مونده به پیتی، قلبش ترکید. شخصیت ۵ ستاره همون لحظه‌ی خاکسپاری اومد. 🎰",
    "{n} تو آسانسور دکمه‌ی بسته شدن در رو زد و با صدای بلند فریاد کشید «زمان متوقف شد!». آسانسور جدی گرفت و ایستاد. بین طبقه‌ها. تا ابد. 🛗",
    "{n} گفت «پنج دقیقه دیگه می‌خوابم، بعد زندگیمو درست می‌کنم.» همین‌جا بود که بدنش تصمیم گرفت پنج دقیقه رو به ابد تعمیم بده. 😴",
    "{n} فکر کرد تابلوی «سقوط سنگ» یه پیشنهاده نه هشدار. سنگ هم فکر کرد {n} پیشنهاد داده. تعامل موفقی بود. 🪨",
    "{n} تو دعوای آخر سرِ یه تکه پیتزا با حریف نامرئی‌اش، با نهایت شجاعت به یخچال حمله کرد. یخچال تلافی کرد. 🍕",
]

LAST_WORDS = [
    "«دو دقیقه صبر کنین سیو کنم…»",
    "«من تو فصل بعد برمی‌گردم!»",
    "«این فقط یه خراشه…»",
    "«به مامانم بگین کلید رو زیر گلدونه.»",
    "«همه‌ی اینا نقشه‌ی من بود.»",
    "«مگه می‌شه؟ من پرچم مرگ نزده بودم!»",
    "«بگین آخرین قسمت رو اسپویل نکنن…»",
]

GODDESS_JUDGE = [
    "امتیاز هنری مرگ: {s}/۱۰. داور سخت‌گیره، ولی شاید برای تو سخت‌گیری کمتری کنم. 😮‍💨",
    "امتیاز هنری مرگ: {s}/۱۰. خمیازه‌م گرفت وسطش، ولی قبوله.",
    "امتیاز هنری مرگ: {s}/۱۰. تماشاگرا کف نزدن. فقط پشه‌ها وزوز کردن.",
]

FORCED_OPENERS = [
    "💅 <b>ایزدبانوی بی‌حوصله</b> انگشتشو بالا آورد: {a} اعدام {t} رو سفارش داد و من هم که بیکارم، قبول کردم.",
    "📜 حکم صادر شد! {a} خواست {t} رو بفرستیم ایسکای. دلیل؟ «حال گروه خوب بشه.» قانع‌کننده‌ترین دلیل ممکن.",
    "🔔 اعلام عمومی: {t} یه نفر بیشتر از لازم تو این گروه نفس کشید. {a} هم دلش نیومد کسی رو تنها بفرسته جهنم… یعنی ایسکای.",
]

ROASTS = [
    "چیه؟ صدام زدی؟ من ایزدبانوی ایسکایم نه پشتیبانی فنی تلگرام. 🙄",
    "یه بار دیگه بدون دلیل صدام کنی، تو رو با وای‌فای ضعیف بازتولد می‌کنم. 📶",
    "اوه، یه انسان دیگه. بذار حدس بزنم: وقت اضافه، دوست کم، آرزوی مرگ اسلایمی؟ 😒",
    "من اینجا پنجاه میلیون روحِ در صف دارم، تو هم میخوای ببینی «زنده‌ای یا نه»؟ برو «زندگی من» بنویس.",
    "نشنیدم. اصلاً هم نخواستم بشنوم. ✨",
]

DEATH_TITLES = [
    (1, "تازه‌وارد قبرستان"),
    (3, "مشتری ثابت قبرستان"),
    (5, "رکورددار مرگ با پوست موز"),
    (10, "کارمند رسمی دنیای مردگان"),
    (25, "جاودانه‌ی بدشانس"),
]

BLACK_MARKET_ITEMS = [
    "کلاه‌گیس جادویی برای فرار از اژدها",
    "نقشه‌ی گنج جعلی (امضا شده توسط یک اسلایم)",
    "معجون HP با طعم قورمه‌سبزِ سرد",
    "شمشیر افسانه‌ای (ساخت بازارچه‌ی تجریش)",
    "کفش دویدن دوقلوی نامتقارن",
    "قطعه‌ای از پادشاهی گمشده (فقط یک تکه سنگ)",
    "پیراهن نامرئی‌کننده، فقط برای کسانی که اصلاً دیده نمی‌شن",
    "لیوان دم‌کرده‌ی شجاعت، بدون ضمانت",
    "کتاب «چطور با شاه شیاطین دوست شویم» (فقط جلد)",
    "جوراب ایسکایی، بوی ابدیت می‌ده",
]
PRICES = [("referral", "معرفی ۳ نفر به ربات"), ("forced_death", "یک مرگ اجباری"), ("gold", "طلا")]

# ───────────────────────────── 🗺 Biomes ─────────────────────────────
# w = وزن رویدادها: find گنج | monster هیولا | heal شفا | trap تله | death مرگ ناگهانی | lore ماجرا
BIOMES = {
    "forest": {
        "name": "جنگل عمیق", "icon": "🌲", "color": "green", "kw": r"جنگل",
        "intro": [
            "درخت‌ها اینجا اونقدر قدیمی‌ان که از دست‌ت خسته شدن، قبل از اینکه برسی.",
            "مه سبز لابه‌لای تنه‌ها می‌چرخه و یه جایی صدای خنده‌ی یه اسلایم میاد.",
            "برگ‌ها پچ‌پچ می‌کنن: «باز یه قهرمان خوش‌خیال…»",
        ],
        "items": ["قارچ درخشانِ مشکوک", "تبر زنگ‌زده‌ی هیزم‌شکن افسانه‌ای", "پر ققنوسِ نیم‌سوخته", "گل‌ساز شبانه", "کمان بی‌زه", "کلید چوبیِ یه در نامعلوم"],
        "monsters": [("گابلینِ بیکار", 18), ("گرگِ وگان", 32), ("اسلایمِ افسرده", 10), ("درختِ بداخلاق", 42)],
        "traps": ["پات رفت تو لونه‌ی زنبورای متعصب", "روی ریشه‌ی درخت کمین‌دار سکندری خوردی", "عنکبوتِ غول‌پیکر تارشو دور مچ پات تنید"],
        "deaths": ["یه درختِ چندصدساله فکر کرد تو شاخه‌ای و قطعت کرد 🪓", "اسلایمِ سلطان تو رو با ژله‌ی خودش خفه کرد. ایزدبانو ازش قدردانی کرد. 🟢"],
        "w": {"find": 28, "monster": 28, "heal": 10, "trap": 14, "death": 3, "lore": 17},
    },
    "sea": {
        "name": "دریای طوفانی", "icon": "🌊", "color": "blue", "kw": r"(دریا|اقیانوس|ساحل)",
        "intro": [
            "موج‌ها شمشیرهاشونو تیز می‌کنن و مرغ‌های دریایی همه‌شون بدهکارن.",
            "آسمون رنگِ کبودیِ زیر چشمِ یه کارمنده و دریا اصلاً حوصله‌ی تو رو نداره.",
            "بوی نمک و تصمیم‌های بد دنیا رو برداشته.",
        ],
        "items": ["صدفِ آوازخوان", "مروارید طلسم‌شده", "نقشه‌ی خیس خزانه‌ی دزد دریایی", "دم‌پاییِ گمشده‌ی پوسایدون", "بطری پیامِ سی‌ساله", "قلاب طلایی"],
        "monsters": [("خرچنگِ کینه‌ای", 25), ("دزد دریاییِ بی‌مجوز", 36), ("مارماهیِ برقی", 44), ("کراکنِ خجالتی", 55)],
        "traps": ["موج غافلگیرت کرد و شلوارتو برد", "یه ماهی بداخلاق سیلی زد تو گوشت", "توفان قایقتو چرخوند و آب‌ نمک بلعیدی"],
        "deaths": ["کراکن تصمیم گرفت تو رو به منوی ناهار اضافه کنه 🐙", "گرداب تو رو بلعید و فقط یه دمپایی ازت موند 🌀"],
        "w": {"find": 24, "monster": 28, "heal": 6, "trap": 17, "death": 6, "lore": 19},
    },
    "ruins": {
        "name": "خرابه‌های باستانی", "icon": "🏛", "color": "purple", "kw": r"(خرابه|ویرانه|معبد|ruins)",
        "intro": [
            "ستون‌های شکسته هنوز دارن درباره‌ی بازسازی بحث می‌کنن.",
            "روی دیوار نوشته: «اینجا قبلاً یه تمدن بود. بعدش وای‌فای قطع شد.»",
            "گرد و غبار قرن‌ها روی کفش‌هات می‌نشینه و هیچ‌کس تعارف نمی‌کنه.",
        ],
        "items": ["لوح باستانیِ پر از غلط املایی", "تاج شاهِ فراموش‌شده", "کتیبه‌ی لعنت‌شده", "تندیس بی‌سر", "حلقه‌ی جادوییِ سایز اشتباه", "مومیاییِ سلفی‌گیر (فقط دستش)"],
        "monsters": [("اسکلتِ بی‌حوصله", 30), ("گولِم سنگی", 48), ("روحِ بدهکار", 38), ("نگهبانِ مومیایی", 52)],
        "traps": ["کف‌پوش مخفی زیر پات خالی شد", "تیرِ دیوار گوشتو بوسید", "طلسمِ در تو رو چند ثانیه فلج کرد"],
        "deaths": ["تله‌ی «سنگ غلتان» تو رو با سنگ ملاقات داد 🪨", "نفرین فرعون تو رو برای همیشه به لیست منتظران اضافه کرد 🏺"],
        "w": {"find": 30, "monster": 28, "heal": 4, "trap": 18, "death": 6, "lore": 14},
    },
    "city": {
        "name": "پایتخت درخشان", "icon": "🏰", "color": "yellow", "kw": r"(شهر|پایتخت|دهکده)",
        "intro": [
            "بازارچه شلوغه و هر فروشنده‌ای فکر می‌کنه تو بهترین مشتری دنیایی. اشتباه می‌کنن.",
            "بوی نون تازه، فاضلاب جادویی و سرنوشت از کوچه‌ها میاد.",
            "نگهبان‌ها بی‌حوصله به تو نگاه می‌کنن؛ شبیه کسی که می‌دونه سر و کله‌ت پیدا میشه.",
        ],
        "items": ["کیسه‌ی سکه‌ی نیم‌خورده", "نشان گیلد قدیمی", "قند جادوییِ گاه‌به‌گاه", "جیب‌بُر بازنشسته‌ی کارت", "پوستر «تحت تعقیب» با عکس یه اسلایم", "گردنبندِ ضدحسادت"],
        "monsters": [("جیب‌برِ ناشی", 14), ("اوباشِ کوچه‌ی ۷", 24), ("مست‌ِ تاورن", 20)],
        "traps": ["کیف پولت (که خالی بود) دزدیده شد و دزد هم دلش سوخت", "یه سطل آب از پنجره ریخت رو سرت", "روی شاشِ مرغ‌های شهری لیز خوردی"],
        "deaths": ["کالسکه‌ی سلطنتی با سرعت ۳ کیلومتر در ساعت… ولی تو فقط نیم‌ثانیه دیر پریدی 🐎"],
        "w": {"find": 30, "monster": 12, "heal": 14, "trap": 16, "death": 1, "lore": 27},
    },
}
BIOME_LIST = list(BIOMES.keys())

LORE_LINES = [
    "یه مسافر بهت گفت: «اینجا قدیم‌ها پر از قهرمان بود.» پرسیدی «حالا؟» گفت: «حالا پر از بدهکار.»",
    "یه پیرزن بدون هیچ دلیلی بهت یه سیب داد و ناپدید شد. سیبه حرف می‌زد: «فرار کن.»",
    "یه تابلوی چوبی دیدی: «به‌زودی اینجا یه فصل جدید باز میشه». کسی نمی‌دونه کی.",
    "یه شهاب از آسمون افتاد، رفت تو دره، و همه‌ی پرنده‌ها با هم گفتن «اوه نه».",
]

# ───────────────────────────── 🧙 NPCs ─────────────────────────────
NPCS = {
    "old_man": {"name": "پیرمردِ دهکده", "icon": "👴", "color": "purple", "alias": r"(پیر\s*مرد|کهنسال|بزرگ\s*دهکده)"},
    "shop": {"name": "مغازه‌دارِ بی‌اعتماد", "icon": "🧔", "color": "yellow", "alias": r"(مغازه\s*دار|فروشنده|دکاندار)"},
    "cafe": {"name": "کافه‌چیِ فیلسوف", "icon": "☕", "color": "orange", "alias": r"(کافه\s*چی|کافه|بارمن)"},
    "guard": {"name": "نگهبانِ شهر", "icon": "💂", "color": "blue", "alias": r"(نگهبان|گارد)"},
    "witch": {"name": "جادوگرِ ناراضی", "icon": "🧙‍♀️", "color": "purple", "alias": r"(جادوگر|ساحره)"},
}

SHOP_ITEMS = [
    ("یه چنگال که ادعا می‌کنه قبلاً شمشیر بوده", 35),
    ("بطری «بدشانسیِ بسته‌بندی‌شده» (خالی)", 20),
    ("سایه‌ی یه ننه‌قمر (دست‌دوم)", 55),
    ("بلیت یک‌طرفه به «جایی که کسی نمی‌شناسدت»", 45),
    ("سیب‌زمینیِ جادوییِ فاقد جادو", 15),
    ("نیم‌تاج پادشاهی (نصفش رو خودم خوردم)", 80),
]
QUEST_REWARD = (40, 90)


def roast_for(doc: dict) -> str:
    dc = doc.get("death_count", 0)
    titles = doc.get("titles") or []
    t = f" «{esc(titles[-1])}»" if titles else ""
    if dc == 0:
        return "هنوز یه بارم نمردی؟ تو رو نمی‌شناسم. حتماً مرگ هم از تو خجالت می‌کشه. 🥱"
    if dc < 3:
        return f"{dc} بار مردی و هنوز اینجایی؟ پشتکار داری، استعداد نه. 😏"
    if dc < 10:
        return f"آه، همون{t} که {dc} بار مرده. یه استکان چای هم به حساب مرگ‌هات ثبت می‌کنم. ☠️"
    return f"{dc} مرگ؟! تو دیگه مشتری ثابتی، تخفیف VIP داری: یه لگد رایگان. 💀"


# ───────────────────────────── Persian helpers ─────────────────────────────
_TR = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ؤ": "و",
    "\u200c": "", "\u200d": "", "\u200e": "", "\u200f": "",
})
_DIAC = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_PUNCT = re.compile(r"[؟?!.،,؛;…~\-_*«»\"'()]+")


def norm(text: str) -> str:
    t = text.translate(_TR)
    t = _DIAC.sub("", t).lower()
    return re.sub(r"\s+", " ", t).strip()


def clean(n: str) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", n)).strip()


def esc(s: Optional[str]) -> str:
    return html.escape(s or "", quote=False)


DISTRESS_RE = re.compile(
    r"(می\s*خوام\s*بمیرم|می\s*خوام\s*خودمو\s*بکشم|دلم\s*می\s*خواد\s*بمیرم|"
    r"کاش\s*(بمیرم|می\s*مردم|نبودم)|(?<!\S)منو\s*بکش(?!\S)|(?<!\S)منو\s*بکشید|خودکشی\s*(می\s*کنم|کنم))"
)
DEATH_RE = re.compile(r"(زندگی\s*من|ریسپاون|ریسپان|منو\s*بفرست\s*(به\s*)?(ایسکای|ایسکا|ایزکای))")
PASSPORT_RE = re.compile(r"(وضعیتم\s*چطوره|وضعیت\s*من|من\s*کیم|من\s*کی\s*ام|من\s*کیام|کارت\s*من|پاسپورت\s*من|پاسپورتم)")
TITLES_RE = re.compile(r"(لقب\s*(های\s*من|هام|ها\s*م|ام|م|هایم)(\s*(چیه|چیا|چیاست))?|لقبام)")
INV_RE = re.compile(r"(کوله\s*پشتی(\s*من|م)?|اینونتوری|انبار\s*من)")
MARKET_RE = re.compile(r"(بازار\s*سیاه)")
BUY_RE = re.compile(r"(من\s*)?(می\s*خرم(ش)?|بخرم)")
INVITE_RE = re.compile(r"(لینک\s*دعوت|لینک\s*معرفی)")
OPT_OUT_RE = re.compile(r"(من\s*بازی\s*نمی\s*کنم|منو\s*از\s*بازی\s*(حذف|خارج)\s*کن|بازی\s*نمی\s*خوام)")
OPT_IN_RE = re.compile(r"(برگردم\s*به\s*بازی|بازی\s*رو\s*فعال\s*کن|منو\s*برگردون\s*به\s*بازی)")
EXEC_RE = re.compile(
    r"@(\w{4,32})\s*(?:رو|را)?\s*(?:بفرستش|بفرست|بفرستین|بفرستید)\s*(?:به\s*)?(?:ایسکای|ایسکا|ایزکای)"
)
REPLY_EXEC_RE = re.compile(r"(بفرستش|بفرستینش|بفرست)\s*(به\s*)?(ایسکای|ایسکا|ایزکای)")
CURSE_RE = re.compile(r"نفرین")
BLESS_RE = re.compile(r"(دعات\s*می\s*کنم|دعای\s*خیر|دعا\s*می\s*کنم)")

# --- RPG intents ---
HELP_RE = re.compile(r"(راهنما|کمک|help|منو\s*بازی)")
CAFE_RE = re.compile(r"(ورود\s*به|وارد\s*(میشم|شدم)\s*(به)?|میرم|می\s*رم|رفتم|برم)\s*(به\s*)?کافه")
NPC_RE = re.compile(r"(گفتگو|گفت\s*و\s*گو|حرف\s*زدن|صحبت\s*کردن|صحبت|حرف\s*میزنم|حرف\s*بزنم)\s*با\s*(.+)")
TRADE_RE = re.compile(r"(قبول\s*معامله|معامله\s*قبول|معامله\s*رو\s*قبول\s*میکنم)")
TRAVEL_RE = re.compile(
    r"^(سفر\s*(کردم\s*)?به|رفتم(\s*به)?|میرم(\s*به)?|می\s*رم(\s*به)?|برم(\s*به)?|ورود\s*به|وارد\s*(میشم|شدم)\s*(به)?|برو\s*به|بریم(\s*به)?)\s*(.*)$"
)
STROLL_RE = re.compile(r"^(گردش|گشت|یه\s*گشتی\s*میزنم|گشت\s*میزنم|ماجراجویی|ماجراجویی\s*میکنم|بریم\s*ماجراجویی)$")
GUILD_CREATE_RE = re.compile(r"^ساخت\s*گیلد\s+(.+)$")
GUILD_JOIN_RE = re.compile(r"^پیوستن\s*به\s*گیلد\s+(.+)$")
GUILD_WAR_RE = re.compile(r"^جنگ\s*گیلد(ها)?$")
GUILD_ME_RE = re.compile(r"^(گیلد\s*من|گیلدم)$")
GUILD_LEAVE_RE = re.compile(r"^(ترک\s*گیلد|از\s*گیلد\s*میرم)$")
GUILD_INVITE_RE = re.compile(r"^دعوت\s*(@(\w{4,32})\s*)?به\s*گیلد$")
DUEL_RE = re.compile(r"^(دوئل|دوعل)(\s*با)?\s*(@(\w{4,32}))?$")
ACCEPT_RE = re.compile(r"(قبول\s*دوئل|دوئل\s*قبول|دوئل\s*رو\s*قبول\s*(میکنم|دارم))")
WHEEL_RE = re.compile(r"(گردونه\s*(ی\s*)?شانس|چرخوندن\s*گردونه|گردونه\s*رو\s*بچرخون)")
BOARD_RE = re.compile(r"(رتبه\s*گروه|لیدربرد|جدول\s*رتبه|رده\s*بندی|رتبه\s*بندی)")

SMALL_TALK_HELP = (
    "💀 <b>دروازه‌ی ایسکای</b> — دکمه و دستور نداریم، فقط حرف بزن:\n\n"
    "🟩 <b>سفر:</b> «سفر به جنگل» · «رفتم دریا» · «ورود به شهر» · «خرابه» · «گردش»\n"
    "🟪 <b>NPC:</b> «گفتگو با پیرمرد» · «حرف زدن با مغازه‌دار» · «ورود به کافه»\n"
    "🟦 <b>گیلد:</b> «ساخت گیلد [نام]» · «پیوستن به گیلد [نام]» · «گیلد من» · «جنگ گیلدها»\n"
    "🟧 <b>دوئل:</b> «دوئل با @یوزرنیم» یا ریپلای + «دوئل» · «قبول دوئل»\n"
    "🟨 <b>شانس:</b> «گردونه شانس» (هر ۲۴ ساعت) · «رتبه گروه» · «لیدربرد»\n"
    "⬛ <b>بازار سیاه:</b> «بازار سیاه» · «میخرم»\n"
    "🟥 <b>مرگ:</b> «زندگی من» · «@یوزرنیم رو بفرست ایسکای» · ریپلای + «نفرینت می‌کنم»/«دعات می‌کنم»\n"
    "⬜ <b>پروفایل:</b> «کارت من» · «لقب هام چیه» · «کوله پشتی» · «لینک دعوت» · «من بازی نمیکنم»"
)

# ───────────────────────────── Persistence ─────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Store:
    def __init__(self, db):
        self.users = db["users"]
        self.offers = db["offers"]
        self.guilds = db["guilds"]
        self.groups = db["groups"]
        self.duels = db["duels"]

    async def ensure_indexes(self):
        await self.users.create_index("user_id", unique=True)
        await self.users.create_index("username_lower")
        await self.users.create_index("chats")
        await self.users.create_index("guild")
        await self.offers.create_index([("chat_id", 1), ("status", 1)])
        await self.guilds.create_index("name_lower", unique=True)
        await self.groups.create_index("chat_id", unique=True)
        await self.duels.create_index([("chat_id", 1), ("status", 1)])

    async def touch(self, u: User) -> bool:
        res = await self.users.update_one(
            {"user_id": u.id},
            {
                "$set": {
                    "first_name": u.full_name,
                    "username": u.username,
                    "username_lower": (u.username or "").lower() or None,
                    "last_seen": utcnow(),
                },
                "$setOnInsert": {
                    "death_count": 0, "survival_rate": 100, "form": None, "cheat_skill": None,
                    "world": None, "status": "انسان معمولی (فعلاً)", "titles": [], "past_forms": [],
                    "curses_received": 0, "blessings_received": 0, "forced_count": 0,
                    "executions_ordered": 0, "referrals_available": 0, "referrals_total": 0,
                    "inventory": [], "opted_out": False, "created_at": utcnow(),
                    "gold": START_GOLD, "xp": 0, "level": 1, "location": "city",
                    "guild": None, "wins": 0, "losses": 0, "trips": 0,
                    "quest": None, "pending_trade": None, "last_wheel_at": None, "chats": [],
                },
            },
            upsert=True,
        )
        return res.upserted_id is not None

    async def get(self, uid: int) -> Optional[dict]:
        return await self.users.find_one({"user_id": uid})


def status_for(rate: int) -> str:
    if rate < 8:
        return "در حال احتضارِ دائمی"
    if rate < 16:
        return "زنده‌ی معجزه‌آسا (به لطف باگ)"
    if rate < 26:
        return "زنده‌ی بدشانس"
    return "نیمه‌زنده، نیمه‌اسلایم"


def earned_titles(doc: dict) -> list:
    t = []
    dc = doc.get("death_count", 0)
    t += [title for th, title in DEATH_TITLES if dc >= th]
    t += [FORM_TITLE[f] for f in doc.get("past_forms", []) if f in FORM_TITLE]
    if doc.get("curses_received", 0) >= 3:
        t.append("نفرین‌خورِ حرفه‌ای")
    if doc.get("blessings_received", 0) >= 3:
        t.append("قدیسِ مشکوک")
    if doc.get("forced_count", 0) >= 2:
        t.append("قربانیِ مورد علاقه‌ی ایزدبانو")
    if doc.get("executions_ordered", 0) >= 3:
        t.append("دستیار جلاد")
    if doc.get("referrals_total", 0) >= 3:
        t.append("دلالِ برده‌های ایزدبانو")
    if doc.get("wins", 0) >= 5:
        t.append("دوئل‌بازِ حرفه‌ای")
    if doc.get("trips", 0) >= 20:
        t.append("مسافرِ بی‌سرانجام")
    if doc.get("level", 1) >= 5:
        t.append("قهرمانِ نیم‌بند")
    return t


async def refresh_titles(doc: dict) -> tuple:
    have = set(doc.get("titles", []))
    new = []
    for title in earned_titles(doc):
        if title not in have and title not in new:
            new.append(title)
    if new:
        doc = await store.users.find_one_and_update(
            {"user_id": doc["user_id"]},
            {"$push": {"titles": {"$each": new}}},
            return_document=ReturnDocument.AFTER,
        )
    return doc, new


async def reincarnate(uid: int, forced: bool = False, chat_id: Optional[int] = None) -> tuple:
    form, _ = random.choice(FORMS)
    rate = random.randint(1, 37)
    inc = {"death_count": 1}
    if forced:
        inc["forced_count"] = 1
    doc = await store.users.find_one_and_update(
        {"user_id": uid},
        {
            "$inc": inc,
            "$set": {
                "form": form, "cheat_skill": random.choice(CHEATS), "world": random.choice(WORLDS),
                "survival_rate": rate, "status": status_for(rate), "last_death_at": utcnow(),
            },
            "$push": {"past_forms": {"$each": [form], "$slice": -30}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if chat_id:
        await store.groups.update_one({"chat_id": chat_id}, {"$inc": {"deaths": 1}}, upsert=True)
    return await refresh_titles(doc)


async def adjust_survival(uid: int, delta: int, counter: Optional[str] = None) -> dict:
    stage = {"survival_rate": {"$min": [100, {"$max": [1, {"$add": [{"$ifNull": ["$survival_rate", 100]}, delta]}]}]}}
    if counter:
        stage[counter] = {"$add": [{"$ifNull": ["$" + counter, 0]}, 1]}
    return await store.users.find_one_and_update(
        {"user_id": uid}, [{"$set": stage}], return_document=ReturnDocument.AFTER
    )


async def grant(uid: int, gold: int = 0, xp: int = 0, item: Optional[str] = None,
                survival: int = 0, counters: Optional[dict] = None) -> tuple:
    """جایزه/جریمه‌ی ترکیبی؛ سطح رو هم خودکار آپدیت می‌کنه. (doc, leveled_up) برمی‌گردونه."""
    upd: dict = {}
    inc: dict = dict(counters or {})
    if gold:
        inc["gold"] = gold
    if xp:
        inc["xp"] = xp
    if inc:
        upd["$inc"] = inc
    if item:
        upd["$push"] = {"inventory": {"$each": [item], "$slice": -15}}
    doc = None
    if upd:
        doc = await store.users.find_one_and_update({"user_id": uid}, upd, return_document=ReturnDocument.AFTER)
    if survival:
        doc = await adjust_survival(uid, survival)
    if doc is None:
        doc = await store.get(uid)
    lvl = 1 + int(doc.get("xp", 0)) // 100
    leveled = lvl > int(doc.get("level", 1))
    if leveled:
        doc = await store.users.find_one_and_update(
            {"user_id": uid}, {"$set": {"level": lvl}}, return_document=ReturnDocument.AFTER
        )
    return doc, leveled


async def spend(uid: int, amount: int) -> bool:
    res = await store.users.update_one({"user_id": uid, "gold": {"$gte": amount}}, {"$inc": {"gold": -amount}})
    return res.modified_count > 0


# ───────────────────────────── Rendering ─────────────────────────────

def rate_comment(r: int) -> str:
    if r < 8:
        return "آمار بقات از آبکش هم سوراخ‌تره. حتی NPCهای دهکده ازت فاصله می‌گیرن. 🫥"
    if r < 16:
        return "با این آمار، حتی اسلایم‌ها هم تو رو جدی نمی‌گیرن."
    if r < 26:
        return "نه عالی، نه افتضاح؛ مثل رامن بی‌مزه‌ی ساعت ۳ صبح."
    return "نسبتاً بالاست… یعنی تا اولین کلیکِ اشتباه. 😏"


def display(doc: dict, link: bool = False) -> str:
    name = esc(doc.get("first_name") or doc.get("username") or "ناشناس")
    if link:
        name = f'<a href="tg://user?id={doc["user_id"]}">{name}</a>'
    else:
        name = f"<b>{name}</b>"
    titles = doc.get("titles") or []
    if titles:
        return f"{name} ‹{esc(titles[-1])}›"
    return name


def stat_lines(doc: dict) -> list:
    r = doc.get("survival_rate", 0)
    return [
        f"💚 بقا: <b>{r}٪</b> {hp_bar(r)}",
        f"⭐ سطح <b>{doc.get('level', 1)}</b> {xp_bar(int(doc.get('xp', 0)))}",
        f"🪙 طلا: <b>{doc.get('gold', 0)}</b>",
    ]


def render_rebirth(doc: dict, new_titles: list) -> str:
    r = doc["survival_rate"]
    color = "red" if r < 16 else ("orange" if r < 26 else "purple")
    lines = [
        f"🧬 فرم جدید: {esc(doc['form'])}",
        f"🌍 دنیا: {esc(doc['world'])}",
        f"🎁 چیت‌اسکیل: {esc(doc['cheat_skill'])}",
        f"💀 نرخ بقا: <b>{r}٪</b> {hp_bar(r)}",
        f"☠️ تعداد مرگ: {doc['death_count']}",
    ]
    s = panel(color, "🔮", "بازتولد موفق (متأسفانه)", lines, rate_comment(r))
    if new_titles:
        s += "\n\n🏷 <b>لقب جدید ثبت شد:</b> " + "، ".join(f"«{esc(t)}»" for t in new_titles)
    return s


def render_scene(name_html: str) -> str:
    scene = random.choice(SCENES).replace("{n}", name_html)
    judge = random.choice(GODDESS_JUDGE).format(s=random.randint(1, 10))
    return f"{scene}\n\n🗣 آخرین حرف: {random.choice(LAST_WORDS)}\n<i>{judge}</i>"


def render_passport(doc: dict) -> str:
    if not doc.get("death_count"):
        return (
            f"{display(doc)}، هنوز یه انسان معمولی‌ای و پاسپورتت خالیه. 🥱\n"
            "برو بنویس «<b>زندگی من</b>» تا ایزدبانو یه مرگ درست‌وحسابی برات جور کنه.\n\n"
            + panel("white", "🎒", "وضعیت فعلی", stat_lines(doc))
        )
    inv = doc.get("inventory") or []
    titles = doc.get("titles") or []
    loc = BIOMES.get(doc.get("location") or "city", BIOMES["city"])
    lines = [
        f"👤 نام: {esc(doc.get('first_name'))}",
        f"🏷 لقب: {esc(titles[-1]) if titles else '—'}",
        f"🧬 فرم فعلی: {esc(doc.get('form'))}",
        f"🌍 دنیا: {esc(doc.get('world'))}",
        f"🎁 چیت‌اسکیل: {esc(doc.get('cheat_skill'))}",
        f"📍 مکان: {loc['icon']} {loc['name']}",
        f"🛡 گیلد: {esc(doc.get('guild')) if doc.get('guild') else 'بی‌گیلد'}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
        f"📌 وضعیت: {esc(doc.get('status'))}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"☠️ مرگ‌ها: {doc.get('death_count', 0)} | 😈 نفرین‌ها: {doc.get('curses_received', 0)} | 🙏 دعاها: {doc.get('blessings_received', 0)}",
        f"⚔️ دوئل: {doc.get('wins', 0)} برد / {doc.get('losses', 0)} باخت",
    ]
    return panel("purple", "🎴", "پاسپورت ایسکای", lines, f"🎒 کوله‌پشتی: {esc('، '.join(inv[-3:])) if inv else 'خالی (مثل مغزت)'}")


# ───────────────────────────── Handlers ─────────────────────────────
router = Router()
_last_self_death: dict = {}
_last_herald: dict = {}
_last_drop: dict = {}
_last_explore: dict = {}


def is_group(m: Message) -> bool:
    return m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def gid(m: Message) -> Optional[int]:
    return m.chat.id if is_group(m) else None


async def do_self_death(m: Message, forced_by: Optional[str] = None):
    uid = m.from_user.id
    now = time.time()
    if now - _last_self_death.get(uid, 0) < SELF_DEATH_COOLDOWN:
        await m.reply("آروم‌تر! روحت هنوز داره لود میشه. ⏳")
        return
    _last_self_death[uid] = now
    doc, new = await reincarnate(uid, chat_id=gid(m))
    name = esc(m.from_user.full_name)
    await m.reply(f"{render_scene('<b>' + name + '</b>')}\n\n{render_rebirth(doc, new)}")


async def do_distress(m: Message):
    await m.reply(
        "یه لحظه نقش ایزدبانوی بداخلاق رو میذارم کنار. 🤍\n\n"
        "اگه این حرف از ته دلته و واقعاً حالت بده، مهمه و جدیش می‌گیرم. "
        "با یه آدم مورد اعتماد حرف بزن. اگه تو ایران هستی، <b>۱۲۳</b> (اورژانس اجتماعی) "
        "یا خط مشاوره‌ی <b>۱۴۸۰</b> رو بگیر؛ اگه خطر همین الان تهدیدت می‌کنه، <b>۱۱۵</b>.\n\n"
        "من هم همین‌جام؛ بگو چی شده. اگه فقط شوخی بود و بازی می‌خوای، بنویس «زندگی من»."
    )


# ───────── 🗺 Exploration ─────────

def detect_biome(text: str) -> Optional[str]:
    for key, b in BIOMES.items():
        if re.search(b["kw"], text):
            return key
    return None


async def do_explore(m: Message, key: str):
    uid = m.from_user.id
    now = time.time()
    if now - _last_explore.get(uid, 0) < EXPLORE_COOLDOWN:
        await m.reply("🥵 پاهات هنوز داغه! چند ثانیه نفس بکش، قهرمان.")
        return
    _last_explore[uid] = now

    B = BIOMES[key]
    doc = await store.get(uid)
    await store.users.update_one({"user_id": uid}, {"$set": {"location": key}, "$inc": {"trips": 1}})
    kinds = list(B["w"].keys())
    kind = random.choices(kinds, weights=[B["w"][k] for k in kinds])[0]

    lines = [f"<i>{random.choice(B['intro'])}</i>", "┈┈┈┈┈┈┈┈┈┈"]
    died = False
    leveled = False

    if kind == "find":
        item, idx, val = roll_item(B["items"])
        gold = random.randint(5, 25) + val
        cursed = idx == len(RARITIES) - 1
        doc, leveled = await grant(uid, gold=gold, xp=random.randint(8, 18), item=item,
                                   survival=-5 if cursed else 0)
        lines.append(f"✨ <b>گنج پیدا کردی!</b>\n🎁 {esc(item)}\n🪙 +{gold} طلا")
        if cursed:
            lines.append("🩸 آیتمِ نفرین‌شده بود… −۵٪ بقا. ایزدبانو دست‌شو بلند کرد و گفت «اپس.»")
    elif kind == "monster":
        mname, strength = random.choice(B["monsters"])
        mine = doc.get("level", 1) * 4 + doc.get("survival_rate", 50) / 2 + random.randint(0, 25)
        theirs = strength + random.randint(0, 25)
        lines.append(f"👹 <b>{esc(mname)}</b> سر راهت سبز شد! (قدرت {strength})")
        if mine >= theirs:
            g = random.randint(8, 30)
            doc, leveled = await grant(uid, gold=g, xp=random.randint(18, 35))
            lines.append(f"⚔️ <b>پیروز شدی!</b> هیولا فرار کرد و یه کیسه‌ی کوچیک جا گذاشت.\n🪙 +{g} طلا")
            if random.random() < 0.3:
                item, _, _ = roll_item(B["items"])
                doc, _ = await grant(uid, item=item)
                lines.append(f"🎁 غنیمت: {esc(item)}")
        else:
            loss = random.randint(8, 20)
            doc, _ = await grant(uid, xp=4, survival=-loss)
            lines.append(f"🩸 <b>شکست خوردی!</b> {esc(mname)} حسابی ازت پذیرایی کرد. −{loss}٪ بقا.")
            if doc.get("survival_rate", 100) <= 2:
                died = True
    elif kind == "heal":
        h = random.randint(8, 18)
        doc, leveled = await grant(uid, xp=6, survival=h)
        lines.append(f"💚 یه چشمه‌ی شفابخشِ مشکوک پیدا کردی و ازش خوردی. +{h}٪ بقا. (عوارضِ جانبی: بدون ضمانت)")
    elif kind == "trap":
        loss = random.randint(5, 14)
        doc, _ = await grant(uid, xp=3, survival=-loss)
        lines.append(f"🕳 {random.choice(B['traps'])}. −{loss}٪ بقا.")
        if doc.get("survival_rate", 100) <= 2:
            died = True
    elif kind == "death":
        lines.append(f"💀 {random.choice(B['deaths'])}")
        died = True
    else:  # lore
        doc, leveled = await grant(uid, xp=random.randint(6, 14))
        lines.append(f"📖 {random.choice(LORE_LINES)}")

    # ماموریت پیرمرد
    q = (await store.get(uid)).get("quest")
    if q and q.get("biome") == key and not died:
        reward = q.get("reward", 50)
        doc, lv2 = await grant(uid, gold=reward, xp=30)
        leveled = leveled or lv2
        await store.users.update_one({"user_id": uid}, {"$set": {"quest": None}})
        lines.append(f"📜 <b>ماموریت پیرمرد انجام شد!</b> 🪙 +{reward} طلا و ۳۰ XP. «خوب… بالاخره یه کاری کردی.»")

    if leveled:
        lines.append(f"🆙 <b>لول‌آپ!</b> حالا سطح {doc.get('level', 1)} هستی؛ یعنی بیشتر از قبل اذیت می‌شی.")

    if died:
        rdoc, new = await reincarnate(uid, chat_id=gid(m))
        scene = render_scene(f"<b>{esc(m.from_user.full_name)}</b>")
        text = (
            panel(B["color"], B["icon"], f"{B['name']} — مرگ ناگهانی!", lines)
            + f"\n\n{scene}\n\n{render_rebirth(rdoc, new)}"
        )
    else:
        doc = await store.get(uid)
        lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(doc)]
        doc, new = await refresh_titles(doc)
        text = panel(B["color"], B["icon"], B["name"], lines)
        if new:
            text += "\n🏷 <b>لقب جدید:</b> " + "، ".join(f"«{esc(t)}»" for t in new)
    await m.reply(text)


# ───────── 🧙 NPC ─────────

async def do_npc(m: Message, npc_key: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    npc = NPCS[npc_key]
    if (doc.get("location") or "city") != "city":
        await m.reply(
            f"{npc['icon']} اینجا کسی جز باد و اسلایم نیست. برای حرف زدن با <b>{npc['name']}</b> اول بنویس «<b>ورود به شهر</b>». 🌬"
        )
        return
    lines = [f"💬 <i>{roast_for(doc)}</i>", "┈┈┈┈┈┈┈┈┈┈"]
    foot = None

    if npc_key == "old_man":
        q = doc.get("quest")
        if q:
            b = BIOMES[q["biome"]]
            lines.append(f"📜 «هنوز اون ماموریتو انجام ندادی؟ برو <b>{b['name']}</b> {b['icon']} و برگرد!»\n🪙 جایزه: {q['reward']} طلا")
        else:
            bkey = random.choice([b for b in BIOME_LIST if b != "city"])
            B = BIOMES[bkey]
            reward = random.randint(*QUEST_REWARD)
            await store.users.update_one(
                {"user_id": uid}, {"$set": {"quest": {"biome": bkey, "reward": reward}}}
            )
            lines.append(
                f"📜 <b>ماموریت جدید!</b>\n«جوون، برو <b>{B['name']}</b> {B['icon']} یه گشتی بزن و زنده برگرد. "
                f"اگه نمردی، {reward} طلا بهت می‌دم. اگه مُردی، یه مراسم ختم تخفیف‌دار برات می‌گیرم.»\n"
                f"👉 بنویس: «سفر به {B['kw'].strip('()').split('|')[0]}»"
            )
    elif npc_key == "shop":
        item, price = random.choice(SHOP_ITEMS)
        await store.users.update_one({"user_id": uid}, {"$set": {"pending_trade": {"item": item, "price": price}}})
        lines.append(
            f"🛒 «فقط امروز! <b>{esc(item)}</b> — فقط <b>{price} طلا</b>. بدون برگشت، بدون ضمانت، بدون وجدان.»"
        )
        foot = f"💡 اگه می‌خوای بخری بنویس «<b>قبول معامله</b>» (طلای تو: {doc.get('gold', 0)} 🪙)"
    elif npc_key == "cafe":
        if await spend(uid, 10):
            h = random.randint(6, 14)
            d2, _ = await grant(uid, xp=5, survival=h)
            lines.append(f"☕ یه قهوه‌ی «ضدمرگ» سفارش دادی (−۱۰ طلا). +{h}٪ بقا.\n«زندگی مثل قهوه‌ست: تلخ و گرون و آخرش پشیمونی.»")
        else:
            lines.append("☕ پول قهوه نداری؛ کافه‌چی فقط یه لیوان آب بهت داد و رو‌تو برگردوند. «برو کار کن.»")
    elif npc_key == "guard":
        gcount = await store.guilds.count_documents({})
        lines.append(
            f"💂 «شنیدم ${gcount} گیلد تو این قاره دارن همو می‌کُشن. اگه گیلد نداری، قراره تنها بمیری.» "
            "«ولی نگران نباش، ما نگهبان‌ها هم کمکی نمی‌کنیم.»".replace("$", "")
        )
    elif npc_key == "witch":
        roll = random.random()
        if roll < 0.5:
            b = random.randint(5, 12)
            await grant(uid, survival=b, xp=8)
            lines.append(f"🧪 جادوگر یه معجون بهت داد: «بخور، بعد بپرس.» +{b}٪ بقا. (طعمش مثل ماتیک قدیمی)")
        else:
            c = random.randint(4, 10)
            await grant(uid, survival=-c, xp=8)
            lines.append(f"🕯 «یه نفرین کوچولو. تعارف نکن، رایگانه.» −{c}٪ بقا. (طلسمِ «سه روز چای سرد»)")
    d3 = await store.get(uid)
    lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(d3)]
    await m.reply(panel(npc["color"], npc["icon"], npc["name"], lines, foot))


async def do_trade(m: Message) -> bool:
    uid = m.from_user.id
    doc = await store.get(uid)
    pt = doc.get("pending_trade")
    if not pt:
        return False
    if not await spend(uid, pt["price"]):
        await m.reply("🧔 «پول نداری؟ پس چرا اینجا وایسادی؟ برو یه سنگ بخور.» 🪨")
        return True
    item = f"🟪 {pt['item']} ‹معامله‌ی مشکوک›"
    await store.users.update_one(
        {"user_id": uid},
        {"$set": {"pending_trade": None}, "$push": {"inventory": {"$each": [item], "$slice": -15}}},
    )
    await m.reply(panel("yellow", "🛒", "معامله انجام شد",
                        [f"🎁 {esc(item)}", f"🪙 −{pt['price']} طلا", "🧔 «از معامله با شما لذت نبردم.»"]))
    return True


# ───────── 🛡 Guilds ─────────

async def guild_power(guild: dict) -> int:
    pipe = [
        {"$match": {"user_id": {"$in": guild["members"]}}},
        {"$group": {"_id": None, "p": {"$sum": {"$add": [
            {"$multiply": [{"$ifNull": ["$level", 1]}, 10]},
            {"$ifNull": ["$survival_rate", 0]},
            {"$multiply": [{"$ifNull": ["$wins", 0]}, 5]},
        ]}}}},
    ]
    res = await store.users.aggregate(pipe).to_list(1)
    return int(res[0]["p"]) if res else 0


async def do_guild_create(m: Message, name: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if doc.get("guild"):
        await m.reply(f"🛡 تو الان عضو گیلد «{esc(doc['guild'])}» هستی. اول بنویس «ترک گیلد».")
        return
    if not (2 <= len(name) <= 24):
        await m.reply("📛 اسم گیلد باید بین ۲ تا ۲۴ حرف باشه.")
        return
    if not await spend(uid, GUILD_COST):
        await m.reply(f"🪙 ساخت گیلد {GUILD_COST} طلا خرج داره و تو انقدر نداری. برو ماجراجویی کن!")
        return
    try:
        await store.guilds.insert_one({
            "name": name, "name_lower": name.lower(), "owner_id": uid, "members": [uid],
            "home_chat": gid(m), "wins": 0, "losses": 0, "created_at": utcnow(), "last_war_at": None,
        })
    except Exception:
        await store.users.update_one({"user_id": uid}, {"$inc": {"gold": GUILD_COST}})
        await m.reply("😤 این اسم قبلاً ثبت شده. یه اسم خلاق‌تر پیدا کن.")
        return
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": name}})
    terr = "این گروه به‌عنوان قلمرو گیلد ثبت شد! 🚩" if is_group(m) else "برای ثبت قلمرو، تو یه گروه بنویسی بهتره. 🚩"
    await m.reply(panel("purple", "🛡", "گیلد جدید تأسیس شد", [
        f"📛 نام: <b>{esc(name)}</b>", f"👑 رهبر: {esc(m.from_user.full_name)}",
        f"🪙 هزینه: {GUILD_COST} طلا", terr,
    ], f"دوستات می‌تونن بنویسن «<b>پیوستن به گیلد {esc(name)}</b>»"))


async def do_guild_join(m: Message, name: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if doc.get("guild"):
        await m.reply(f"🛡 تو الان عضو «{esc(doc['guild'])}» هستی. اول «ترک گیلد» بنویس.")
        return
    g = await store.guilds.find_one({"name_lower": name.lower()})
    if not g:
        await m.reply("🔍 همچین گیلدی تو دفترم نیست. اسمش رو درست بنویس.")
        return
    if len(g["members"]) >= GUILD_MAX_MEMBERS:
        await m.reply("🚪 این گیلد پره. دلال‌ها هم باید یه جایی صف بکشن.")
        return
    await store.guilds.update_one({"_id": g["_id"]}, {"$addToSet": {"members": uid}})
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": g["name"]}})
    await m.reply(panel("blue", "🛡", "عضو جدید!", [
        f"{esc(m.from_user.full_name)} به گیلد <b>{esc(g['name'])}</b> پیوست.",
        f"👥 اعضا: {len(g['members']) + 1}",
    ], "ایزدبانو یه بار دیگه خمیازه کشید."))


async def do_guild_leave(m: Message):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await m.reply("🛡 تو که گیلد نداری؛ از چی میری؟")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": None}})
    if g:
        members = [x for x in g["members"] if x != uid]
        if not members:
            await store.guilds.delete_one({"_id": g["_id"]})
        else:
            await store.guilds.update_one(
                {"_id": g["_id"]},
                {"$set": {"members": members, "owner_id": members[0] if g["owner_id"] == uid else g["owner_id"]}},
            )
    await m.reply("🚪 از گیلد رفتی. حتی تابلوی «خداحافظ» هم نداشتی.")


async def do_guild_me(m: Message):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await m.reply("🛡 گیلد نداری. بنویس «<b>ساخت گیلد [نام]</b>» یا «<b>پیوستن به گیلد [نام]</b>».")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"guild": None}})
        await m.reply("گیلدت منحل شده بود. 🪦")
        return
    power = await guild_power(g)
    top = await store.users.find({"user_id": {"$in": g["members"]}}).sort("level", -1).limit(5).to_list(5)
    names = "، ".join(esc(u.get("first_name")) for u in top)
    terr = "—"
    if g.get("home_chat"):
        gr = await store.groups.find_one({"chat_id": g["home_chat"]})
        terr = esc(gr.get("title")) if gr and gr.get("title") else "ثبت‌شده"
    await m.reply(panel("purple", "🛡", f"گیلد {g['name']}", [
        f"👑 رهبر: {esc((await store.get(g['owner_id'])).get('first_name'))}",
        f"👥 اعضا: {len(g['members'])}  |  ⚡ قدرت: <b>{power}</b>",
        f"🚩 قلمرو: {terr}",
        f"⚔️ جنگ‌ها: {g.get('wins', 0)} برد / {g.get('losses', 0)} باخت",
        f"🌟 برترین‌ها: {names}",
    ]))


async def do_guild_war(m: Message):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await m.reply("🛡 بدون گیلد توی جنگ فقط یه هدف متحرکی. اول گیلد بساز.")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        return
    last = g.get("last_war_at")
    if last and (utcnow() - last).total_seconds() < GUILD_WAR_COOLDOWN:
        left = int(GUILD_WAR_COOLDOWN - (utcnow() - last).total_seconds()) // 60 + 1
        await m.reply(f"🩹 گیلدت هنوز زخم‌هاشو می‌لیسه. ~{left} دقیقه‌ی دیگه.")
        return
    others = await store.guilds.find({"_id": {"$ne": g["_id"]}}).to_list(50)
    if not others:
        await m.reply("😴 هیچ گیلد دیگه‌ای نیست که باهاش بجنگی. ببین دوستات رو بیاری!")
        return
    foe = random.choice(others)
    pa, pb = await guild_power(g), await guild_power(foe)
    sa, sb = pa * random.uniform(0.75, 1.25), pb * random.uniform(0.75, 1.25)
    win = sa >= sb
    await store.guilds.update_one({"_id": g["_id"]}, {"$set": {"last_war_at": utcnow()}, "$inc": {"wins" if win else "losses": 1}})
    await store.guilds.update_one({"_id": foe["_id"]}, {"$inc": {"losses" if win else "wins": 1}})
    wg, lg = (g, foe) if win else (foe, g)
    await store.users.update_many({"user_id": {"$in": wg["members"]}}, {"$inc": {"gold": 30, "xp": 15}})
    await store.users.update_many({"user_id": {"$in": lg["members"]}}, {"$inc": {"xp": 5}})
    if is_group(m):
        await store.groups.update_one({"chat_id": m.chat.id}, {"$inc": {"wars": 1}}, upsert=True)
    await m.reply(panel("red", "⚔️", "جنگ گیلدها!", [
        f"🟦 <b>{esc(g['name'])}</b>  ⚡{int(sa)}",
        "      ⚔️ VS ⚔️",
        f"🟥 <b>{esc(foe['name'])}</b>  ⚡{int(sb)}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"🏆 برنده: <b>{esc(wg['name'])}</b> — هر عضو 🪙+۳۰ و ۱۵ XP",
        f"🪦 بازنده: {esc(lg['name'])} (تسلیت. ولی نه واقعاً.)",
    ]))


async def do_guild_invite(m: Message, uname: Optional[str]):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await m.reply("🛡 اول خودت گیلد داشته باش، بعد دعوت کن.")
        return
    who = f"@{uname}" if uname else ""
    if not uname and m.reply_to_message and m.reply_to_message.from_user:
        who = esc(m.reply_to_message.from_user.full_name)
    if not who:
        await m.reply("کی رو دعوت کنم؟ ریپلای بزن یا @یوزرنیم بنویس.")
        return
    await m.reply(panel("blue", "📯", "دعوت‌نامه‌ی گیلد", [
        f"{who} — {esc(m.from_user.full_name)} تو رو به گیلد <b>{esc(doc['guild'])}</b> دعوت کرد!",
        f"برای قبول بنویس: «<b>پیوستن به گیلد {esc(doc['guild'])}</b>»",
    ]))


# ───────── ⚔️ Duels ─────────

async def do_duel_request(m: Message, uname: Optional[str]) -> bool:
    if not is_group(m):
        await m.reply("⚔️ دوئل فقط تو گروه معنی داره؛ تماشاگر لازمه.")
        return True
    target = None
    if uname:
        if uname.lower() == BOT_USERNAME.lower():
            await m.reply("با من دوئل؟ من یه ایزدبانوام، نه یه کیسه‌ی بوکس. 💅")
            return True
        target = await store.users.find_one({"username_lower": uname.lower()})
        if not target:
            await m.reply("این روح رو هنوز نمی‌شناسم. بگو یه چیزی بنویسه تا ثبتش کنم. 📖")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user:
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await m.reply("ربات‌ها دوئل نمی‌کنن؛ فقط حقوق می‌خوان. 🤖")
            return True
        await store.touch(tu)
        target = await store.get(tu.id)
    else:
        return False
    a = m.from_user
    if target["user_id"] == a.id:
        await m.reply("با خودت دوئل؟ این اسمش خودزنیه، نه دوئل. 🙃")
        return True
    if target.get("opted_out"):
        await m.reply(f"{display(target)} قرارداد محافظت امضا کرده. دوئل ممنوع. 🛡")
        return True
    await store.duels.update_many(
        {"chat_id": m.chat.id, "status": "pending", "$or": [{"a": a.id}, {"b": target["user_id"]}]},
        {"$set": {"status": "expired"}},
    )
    await store.duels.insert_one({
        "chat_id": m.chat.id, "a": a.id, "a_name": a.full_name, "b": target["user_id"],
        "status": "pending", "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=DUEL_TTL),
    })
    await m.reply(panel("orange", "⚔️", "چالش دوئل!", [
        f"🟧 {esc(a.full_name)} داره {display(target, link=True)} رو به دوئل دعوت می‌کنه!",
        "⏳ ۳ دقیقه وقت داری.",
    ], "اگه جرأت داری بنویس: «<b>قبول دوئل</b>» 🥊"))
    return True


async def do_duel_accept(m: Message) -> bool:
    duel = await store.duels.find_one_and_update(
        {"chat_id": m.chat.id, "b": m.from_user.id, "status": "pending", "expires_at": {"$gt": utcnow()}},
        {"$set": {"status": "done"}},
        return_document=ReturnDocument.AFTER,
    )
    if not duel:
        return False
    da, db_ = await store.get(duel["a"]), await store.get(duel["b"])

    def power(d: dict) -> float:
        return d.get("level", 1) * 5 + d.get("survival_rate", 50) * 0.6 + len(d.get("inventory") or []) * 2 + random.uniform(0, 50)

    pa, pb = power(da), power(db_)
    win_doc, lose_doc = (da, db_) if pa >= pb else (db_, da)
    loss = random.randint(8, 20)
    wg = random.randint(20, 60)
    wdoc, leveled = await grant(win_doc["user_id"], gold=wg, xp=25, counters={"wins": 1})
    ldoc, _ = await grant(lose_doc["user_id"], xp=6, survival=-loss, counters={"losses": 1})
    await store.groups.update_one({"chat_id": m.chat.id}, {"$inc": {"duels": 1}}, upsert=True)
    lines = [
        f"🟧 {display(da, link=True)} ⚡{int(pa)}",
        "      ⚔️ VS ⚔️",
        f"🟦 {display(db_, link=True)} ⚡{int(pb)}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"🏆 برنده: {display(wdoc, link=True)} — 🪙+{wg} و ۲۵ XP",
        f"🩸 بازنده: {display(ldoc, link=True)} — −{loss}٪ بقا ({hp_bar(ldoc['survival_rate'])})",
    ]
    if leveled:
        lines.append(f"🆙 {esc(wdoc.get('first_name'))} لول‌آپ شد!")
    text = panel("orange", "🥊", "نتیجه‌ی دوئل", lines)
    if ldoc.get("survival_rate", 100) <= 2:
        rdoc, new = await reincarnate(lose_doc["user_id"], chat_id=m.chat.id)
        text += f"\n\n💀 زخم‌های بازنده کشنده بود!\n{render_scene(display(rdoc, link=True))}\n\n{render_rebirth(rdoc, new)}"
    await m.reply(text)
    return True


# ───────── 🎡 Wheel / Leaderboard ─────────

async def do_wheel(m: Message):
    uid = m.from_user.id
    doc = await store.get(uid)
    last = doc.get("last_wheel_at")
    if last and (utcnow() - last).total_seconds() < WHEEL_COOLDOWN:
        rem = int(WHEEL_COOLDOWN - (utcnow() - last).total_seconds())
        await m.reply(f"🎡 گردونه هنوز داغه! <b>{rem // 3600}</b> ساعت و <b>{(rem % 3600) // 60}</b> دقیقه‌ی دیگه بیا.")
        return
    roll = random.random()
    cheat = random.choice(CHEATS)
    base_set = {"last_wheel_at": utcnow(), "cheat_skill": cheat}
    if roll < 0.55:
        rate = random.randint(25, 70)
        await store.users.update_one({"user_id": uid}, {"$set": {**base_set, "survival_rate": rate, "status": status_for(rate)}})
        lines = ["🟩 <b>چرخش معمولی</b>", f"🎁 چیت‌اسکیل جدید: {esc(cheat)}", f"💚 بقا ریست شد: <b>{rate}٪</b> {hp_bar(rate)}"]
        color = "green"
    elif roll < 0.75:
        gold = random.randint(100, 250)
        item, _, _ = roll_item(["تاج گردونه‌ی شانس", "سکه‌ی چهارپری", "طلسم خوش‌شانسی (۵۰٪ جعلی)"])
        item = "🟨 " + item.split(" ", 1)[1]
        rate = random.randint(50, 90)
        await store.users.update_one({"user_id": uid}, {
            "$set": {**base_set, "survival_rate": rate, "status": status_for(rate)},
            "$inc": {"gold": gold}, "$push": {"inventory": {"$each": [item], "$slice": -15}},
        })
        lines = ["🟨 <b>جک‌پات!!</b> 🎰", f"🪙 +{gold} طلا", f"🎁 {esc(item)}", f"✨ چیت‌اسکیل: {esc(cheat)}", f"💚 بقا: <b>{rate}٪</b> {hp_bar(rate)}"]
        color = "yellow"
    elif roll < 0.9:
        await store.users.update_one({"user_id": uid}, {"$set": base_set, "$inc": {"gold": 40}})
        d2 = await adjust_survival(uid, 15)
        lines = ["🟦 <b>برکت خفیف</b>", f"🪙 +۴۰ طلا", f"💚 +۱۵٪ بقا → <b>{d2['survival_rate']}٪</b> {hp_bar(d2['survival_rate'])}", f"✨ چیت‌اسکیل: {esc(cheat)}"]
        color = "blue"
    else:
        rate = random.randint(1, 10)
        await store.users.update_one({"user_id": uid}, {"$set": {**base_set, "survival_rate": rate, "status": status_for(rate)}, "$inc": {"xp": 20}})
        lines = ["🟥 <b>نفرین گردونه!</b> ☠️", f"💚 بقا سقوط کرد: <b>{rate}٪</b> {hp_bar(rate)}", "🎁 جایزه‌ی تسلی: ۲۰ XP", f"✨ چیت‌اسکیل: {esc(cheat)}"]
        color = "red"
    await m.reply(panel(color, "🎡", "گردونه‌ی شانس", lines, "فردا دوباره بیا… اگه زنده بودی. 😈"))


async def group_score(chat_id: int, g: dict) -> dict:
    pipe = [
        {"$match": {"chats": chat_id}},
        {"$group": {"_id": None, "n": {"$sum": 1}, "p": {"$sum": {"$add": [
            {"$multiply": [{"$ifNull": ["$level", 1]}, 10]}, {"$ifNull": ["$survival_rate", 0]}]}}}},
    ]
    res = await store.users.aggregate(pipe).to_list(1)
    members, power = (res[0]["n"], int(res[0]["p"])) if res else (0, 0)
    score = int(g.get("activity", 0)) + int(g.get("duels", 0)) * 10 + int(g.get("deaths", 0)) * 3 + int(g.get("wars", 0)) * 15 + power
    return {"chat_id": chat_id, "title": g.get("title") or "گروه ناشناس", "score": score,
            "members": members, "duels": g.get("duels", 0), "deaths": g.get("deaths", 0)}


async def do_board(m: Message):
    groups = await store.groups.find({}).sort("activity", -1).limit(20).to_list(20)
    if not groups:
        await m.reply("📊 هنوز هیچ گروهی تو دفترم ثبت نشده. اول یه کم فعالیت کنید.")
        return
    scored = sorted([await group_score(g["chat_id"], g) for g in groups], key=lambda x: -x["score"])
    medals = ["🥇", "🥈", "🥉"]
    colors = ["🟨", "⬜", "🟫"]
    lines = []
    for i, s in enumerate(scored[:8]):
        mk = medals[i] if i < 3 else f"{i + 1}."
        co = colors[i] if i < 3 else "⬛"
        lines.append(f"{mk} {co} <b>{esc(s['title'])}</b> — ⚡{s['score']}\n      👥{s['members']} ⚔️{s['duels']} ☠️{s['deaths']}")
    foot = ""
    if is_group(m):
        pos = next((i + 1 for i, s in enumerate(scored) if s["chat_id"] == m.chat.id), None)
        if pos:
            foot = f"📍 جایگاه گروه شما: <b>#{pos}</b>"
    top_g = await store.guilds.find({}).sort("wins", -1).limit(3).to_list(3)
    if top_g:
        lines.append("┈┈┈┈┈┈┈┈┈┈")
        lines.append("🛡 <b>گیلدهای برتر:</b> " + "، ".join(f"{esc(x['name'])} ({x.get('wins', 0)}🏆)" for x in top_g))
    await m.reply(panel("yellow", "🏆", "لیدربرد گروه‌ها (جنگ قلمروها)", lines, foot or None))


# ───────── Existing: forced death, curse, black market ─────────

async def do_forced(m: Message, n: str, c: str) -> bool:
    target_doc = None
    mm = EXEC_RE.search(n)
    if mm:
        uname = mm.group(1).lower()
        if uname == BOT_USERNAME.lower():
            await m.reply("منو بفرستی ایسکای؟ من خودِ خدای اون‌جام، عزیز دل. 💅")
            return True
        target_doc = await store.users.find_one({"username_lower": uname})
        if not target_doc:
            await m.reply("این روح رو هنوز تو دفترم ندیدم. بگو یه چیزی بنویسه تا ثبتش کنم و بعد حکمو صادر می‌کنم. 📖")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user and REPLY_EXEC_RE.fullmatch(c):
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await m.reply("ربات‌ها هم‌صنف منن، نمی‌فرستمشون. 🤖")
            return True
        await store.touch(tu)
        target_doc = await store.get(tu.id)
    else:
        return False

    author = m.from_user
    if target_doc["user_id"] == author.id:
        await do_self_death(m)
        return True
    if target_doc.get("opted_out"):
        await m.reply(
            f"{display(target_doc)} قرارداد محافظت امضا کرده. حتی من هم قانون رو دور نمی‌زنم… "
            "فعلاً. تو هم یه لقب «جلاد بی‌دندون» از من هدیه بگیر. 😒"
        )
        return True
    last = target_doc.get("last_death_at")
    if last and (utcnow() - last).total_seconds() < FORCED_TARGET_COOLDOWN:
        await m.reply("این یکی تازه مرده، جسدش هنوز گرمه. بذار خنک شه. 🧊")
        return True

    doc, new = await reincarnate(target_doc["user_id"], forced=True, chat_id=gid(m))
    await store.users.update_one({"user_id": author.id}, {"$inc": {"executions_ordered": 1}})
    adoc = await store.get(author.id)
    if adoc:
        await refresh_titles(adoc)
    opener = random.choice(FORCED_OPENERS).format(a=f"<b>{esc(author.full_name)}</b>", t=display(doc, link=True))
    await m.reply(f"{opener}\n\n{render_scene(display(doc, link=True))}\n\n{render_rebirth(doc, new)}")
    return True


async def do_curse_bless(m: Message, c: str, n: str) -> bool:
    if not (is_group(m) and m.reply_to_message and m.reply_to_message.from_user):
        return False
    is_curse = bool(CURSE_RE.search(n))
    is_bless = bool(BLESS_RE.search(n))
    if not (is_curse or is_bless):
        return False
    tu = m.reply_to_message.from_user
    if tu.is_bot or tu.id == m.from_user.id:
        return False
    await store.touch(tu)
    tdoc = await store.get(tu.id)
    if tdoc.get("opted_out"):
        await m.reply("این آدم محافظت‌شده‌ست. نفرینت بی‌اثر شد و برگشت تو صورتت. 🪞")
        return True
    a = f"<b>{esc(m.from_user.full_name)}</b>"
    if is_curse:
        d = random.randint(3, 12)
        doc = await adjust_survival(tu.id, -d, "curses_received")
        text = random.choice([
            f"😈 {a} یه مشت خاک قبرستون ریخت تو دیگ نفرین و {display(doc, link=True)} رو نشونه گرفت!\nنرخ بقا <b>{d}٪</b> سقوط کرد.",
            f"🕯 صدای نفرین تو گروه پیچید: {a} روح {display(doc, link=True)} رو به یه مرگ چندقدمی‌تر کرد.\nمنفی <b>{d}٪</b> از بقا.",
            f"🧿 {a} نفرین‌نامه رو امضا کرد؛ {display(doc, link=True)} حالا یه طلسم سنگین رو دوششه.\n−{d}٪ بقا، رایگان.",
        ])
        color, icon, title = "red", "😈", "نفرین"
    else:
        d = random.randint(2, 8)
        doc = await adjust_survival(tu.id, d, "blessings_received")
        text = random.choice([
            f"🙏 دعای خیر {a} روی {display(doc, link=True)} نشست؛ نرخ بقا <b>+{d}٪</b>. ولی ایزدبانو می‌دونه دعا تو گروه یعنی نقشه داره.",
            f"✨ {a} برای {display(doc, link=True)} دعا کرد. ایزدبانو خمیازه کشید و <b>+{d}٪</b> بقا داد.",
        ])
        color, icon, title = "green", "🙏", "دعای خیر"
    doc, new = await refresh_titles(doc)
    lines = [text, f"💀 نرخ بقا حالا: <b>{doc['survival_rate']}٪</b> {hp_bar(doc['survival_rate'])}"]
    out = panel(color, icon, title, lines)
    if new:
        out += "\n🏷 لقب جدید: " + "، ".join(f"«{esc(t)}»" for t in new)
    await m.reply(out)
    return True


async def drop_offer(chat_id: int) -> str:
    item, _, _ = roll_item(BLACK_MARKET_ITEMS)
    pkey, plabel = random.choice(PRICES)
    price = random.randint(40, 150) if pkey == "gold" else None
    if price:
        plabel = f"{price} طلا"
    await store.offers.update_many({"chat_id": chat_id, "status": "open"}, {"$set": {"status": "expired"}})
    await store.offers.insert_one({
        "chat_id": chat_id, "item": item, "price_key": pkey, "price_label": plabel, "price": price,
        "status": "open", "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=OFFER_TTL),
    })
    _last_drop[chat_id] = time.time()
    return panel("black", "🕶", "بازار سیاه باز شد!", [
        "یه دلال مشکوک از لای پرده اومد بیرون…",
        f"🛒 کالا: {esc(item)}",
        f"💰 قیمت: <b>{esc(plabel)}</b>",
        "⏳ ۱۵ دقیقه وقت داری. اولین نفری که بنویسه «<b>میخرم</b>» برنده‌ست (یا قربانی).",
    ])


async def do_buy(m: Message) -> bool:
    offer = await store.offers.find_one_and_update(
        {"chat_id": m.chat.id, "status": "open", "expires_at": {"$gt": utcnow()}},
        {"$set": {"status": "sold", "buyer": m.from_user.id}},
        return_document=ReturnDocument.AFTER,
    )
    if not offer:
        return False
    uid = m.from_user.id

    async def reopen():
        await store.offers.update_one({"_id": offer["_id"]}, {"$set": {"status": "open"}})

    if offer["price_key"] == "referral":
        ok = await store.users.update_one(
            {"user_id": uid, "referrals_available": {"$gte": 3}}, {"$inc": {"referrals_available": -3}}
        )
        if ok.modified_count == 0:
            await reopen()
            link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
            await m.reply(
                "پول نداری، فقیر! 😒 این جنس رو با «معرفی ۳ نفر» میدن و تو ۳ تا دوست هم نداری.\n"
                f"لینک اختصاصی‌ت: {link}\nهر کس با این لینک ربات رو استارت کنه، یه امتیاز می‌گیری."
            )
            return True
    elif offer["price_key"] == "gold":
        if not await spend(uid, int(offer.get("price") or 80)):
            await reopen()
            await m.reply(f"🪙 {offer.get('price_label')} نداری! برو ماجراجویی کن، بعد بیا نق بزن. 😒")
            return True
    else:  # مرگ اجباری
        await store.users.update_one({"user_id": uid}, {"$push": {"inventory": {"$each": [offer["item"]], "$slice": -15}}})
        doc, new = await reincarnate(uid, chat_id=gid(m))
        await m.reply(
            f"😈 {display(doc, link=True)} بدون خوندن ریز‌نوشته‌ها «{esc(offer['item'])}» رو خرید.\n"
            f"قیمتش یه مرگ اجباری بود!\n\n{render_scene(display(doc, link=True))}\n\n{render_rebirth(doc, new)}"
        )
        return True
    await store.users.update_one({"user_id": uid}, {"$push": {"inventory": {"$each": [offer["item"]], "$slice": -15}}})
    await m.reply(panel("black", "💸", "معامله انجام شد", [
        f"🎁 {esc(offer['item'])} رفت تو کوله‌پشتیت.",
        "دلال با لبخند گفت: «برای دفعه‌ی بعد دوستای بیشتری بیار.»",
    ]))
    return True


# ───────────────────────────── Entry points ─────────────────────────────

@router.message(CommandStart())
async def on_start(m: Message, command: CommandObject):
    if not m.from_user:
        return
    created = await store.touch(m.from_user)
    arg = command.args or ""
    if created and arg.startswith("ref_") and arg[4:].isdigit():
        ref = int(arg[4:])
        if ref != m.from_user.id:
            res = await store.users.update_one(
                {"user_id": ref}, {"$inc": {"referrals_available": 1, "referrals_total": 1}}
            )
            if res.matched_count:
                try:
                    await m.bot.send_message(ref, "🎉 یه روح تازه با لینک تو وارد دروازه‌ی ایسکای شد! +۱ امتیاز معرفی. 😈")
                except Exception:
                    pass
                rdoc = await store.get(ref)
                if rdoc:
                    await refresh_titles(rdoc)
    await m.answer("🌙 <b>آه… یه انسان دیگه.</b> منم ایزدبانوی ایسکا، و تو داری وقت منو می‌گیری.\n\n" + SMALL_TALK_HELP)


@router.message(F.text)
async def on_text(m: Message, bot: Bot):
    if not m.from_user or m.from_user.is_bot or not m.text or m.text.startswith("/"):
        return
    try:
        await handle_text(m, bot)
    except Exception:
        log.exception("handler failed")
        await m.reply("ایزدبانو گفت سیستم باگ داره و فعلاً مرخصیه. دوباره امتحان کن. 🛠")


async def handle_text(m: Message, bot: Bot):
    await store.touch(m.from_user)
    n = norm(m.text)
    mentioned = bool(BOT_USERNAME) and ("@" + BOT_USERNAME.lower()) in n
    replied_to_bot = bool(m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id == bot.id)
    if mentioned:
        n = n.replace("@" + BOT_USERNAME.lower(), " ")
        n = re.sub(r"\s+", " ", n).strip()
    c = clean(n)
    group = is_group(m)

    # ۰) حرف‌های نگران‌کننده: بازی متوقف، پاسخ همدلانه
    if DISTRESS_RE.search(c):
        await do_distress(m)
        return

    # آمار فعالیت گروه (برای جنگ قلمروها)
    if group:
        await store.groups.update_one(
            {"chat_id": m.chat.id}, {"$set": {"title": m.chat.title}, "$inc": {"activity": 1}}, upsert=True
        )
        await store.users.update_one({"user_id": m.from_user.id}, {"$addToSet": {"chats": m.chat.id}})

    # ۱) اعدام اجباری
    if group and (("@" in n) or m.reply_to_message) and await do_forced(m, n, c):
        return

    # ۲) دوئل
    if group:
        dm = DUEL_RE.fullmatch(c)
        if dm and await do_duel_request(m, dm.group(4)):
            return
        if ACCEPT_RE.search(c) and await do_duel_accept(m):
            return

    # ۳) نفرین/دعا
    if await do_curse_bless(m, c, n):
        return

    # ۴) خرید از بازار سیاه / معامله با مغازه‌دار
    if BUY_RE.fullmatch(c) and await do_buy(m):
        return
    if TRADE_RE.search(c) and await do_trade(m):
        return

    # ۵) گیلد
    if gm := GUILD_CREATE_RE.fullmatch(c):
        await do_guild_create(m, gm.group(1).strip())
        return
    if gm := GUILD_JOIN_RE.fullmatch(c):
        await do_guild_join(m, gm.group(1).strip())
        return
    if GUILD_WAR_RE.fullmatch(c):
        await do_guild_war(m)
        return
    if GUILD_ME_RE.fullmatch(c):
        await do_guild_me(m)
        return
    if GUILD_LEAVE_RE.fullmatch(c):
        await do_guild_leave(m)
        return
    if gm := GUILD_INVITE_RE.fullmatch(c):
        await do_guild_invite(m, gm.group(2))
        return

    # ۶) گردونه‌ی شانس و لیدربرد
    if WHEEL_RE.search(c):
        await do_wheel(m)
        return
    if BOARD_RE.search(c):
        await do_board(m)
        return

    # ۷) NPC (قبل از سفر، تا «ورود به کافه» اشتباه تفسیر نشه)
    if CAFE_RE.search(c):
        await do_npc(m, "cafe")
        return
    if nm := NPC_RE.search(c):
        target = nm.group(2)
        for key, npc in NPCS.items():
            if re.search(npc["alias"], target):
                await do_npc(m, key)
                return
        await m.reply("🤷 همچین موجودی تو شهر نیست. «پیرمرد»، «مغازه‌دار»، «کافه‌چی»، «نگهبان» یا «جادوگر» رو امتحان کن.")
        return

    # ۸) سفر و ماجراجویی
    if STROLL_RE.fullmatch(c):
        doc = await store.get(m.from_user.id)
        await do_explore(m, doc.get("location") or "city")
        return
    if tm := TRAVEL_RE.fullmatch(c):
        key = detect_biome(tm.group(tm.lastindex or 0)) if tm.lastindex else None
        key = key or detect_biome(c)
        if key:
            await do_explore(m, key)
            return

    # ۹) اینتنت‌های ساده
    if MARKET_RE.search(c):
        await m.reply(await drop_offer(m.chat.id))
        return
    if TITLES_RE.fullmatch(c):
        doc = await store.get(m.from_user.id)
        titles = doc.get("titles") or []
        if not titles:
            await m.reply("هنوز لقبی نداری؛ یعنی آدم کاملاً بی‌اهمیتی هستی. بنویس «زندگی من» تا لقب بگیری. 🪦")
        else:
            lines = [f"{i}. {esc(t)}" for i, t in enumerate(titles, 1)]
            await m.reply(panel("purple", "🏷", f"لقب‌های سمّیِ {m.from_user.full_name}", lines))
        return
    if INV_RE.fullmatch(c):
        doc = await store.get(m.from_user.id)
        inv = doc.get("inventory") or []
        lines = [f"{i}. {esc(x)}" for i, x in enumerate(inv, 1)] or ["خالی (مثل مغزت)"]
        await m.reply(panel("brown", "🎒", "کوله‌پشتی", lines, f"🪙 طلا: <b>{doc.get('gold', 0)}</b>"))
        return
    if PASSPORT_RE.fullmatch(c):
        await m.reply(render_passport(await store.get(m.from_user.id)))
        return
    if DEATH_RE.fullmatch(c):
        await do_self_death(m)
        return
    if INVITE_RE.fullmatch(c):
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{m.from_user.id}"
        await m.reply(f"🔗 لینک دعوت اختصاصیت:\n{link}\nهر ۳ نفر = یه شانس خرید از بازار سیاه.")
        return
    if OPT_OUT_RE.fullmatch(c):
        await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"opted_out": True}})
        await m.reply("باشه، تو از لیست اعدام، نفرین و دوئل حذف شدی. جبران: ایزدبانو دیگه بهت توجه نمی‌کنه. 🚪")
        return
    if OPT_IN_RE.fullmatch(c):
        await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"opted_out": False}})
        await m.reply("خوش برگشتی به جهنم. 😈 دوباره قابل‌اعدامی.")
        return
    if HELP_RE.fullmatch(c):
        await m.reply(SMALL_TALK_HELP)
        return

    # ۱۰) صدا زدن بدون دستور معتبر
    if mentioned or replied_to_bot:
        await m.reply(random.choice(ROASTS))
        return
    if not group:
        await m.answer(SMALL_TALK_HELP)
        return

    # ۱۱) حرکات تصادفیِ گروه: لقب‌خوانی + بازار سیاه
    now = time.time()
    doc = await store.get(m.from_user.id)
    if doc and doc.get("titles") and random.random() < HERALD_CHANCE and now - _last_herald.get(m.from_user.id, 0) > HERALD_COOLDOWN:
        _last_herald[m.from_user.id] = now
        await m.reply(f"🔔 <b>توجه توجه!</b> {display(doc, link=True)} لب به سخن گشود. تماشاگران سکوت کنن، یا نه، فرقی نداره.")
        return
    if random.random() < RANDOM_DROP_CHANCE and now - _last_drop.get(m.chat.id, 0) > DROP_COOLDOWN:
        await m.answer(await drop_offer(m.chat.id))


async def main():
    global store, BOT_USERNAME
    if not BOT_TOKEN or not MONGO_URI:
        raise SystemExit("TELEGRAM_BOT_TOKEN و MONGO_URI باید تنظیم شده باشن.")
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    store = Store(client[DB_NAME])
    await store.ensure_indexes()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_USERNAME = (await bot.get_me()).username or ""
    log.info("Bot @%s is alive. God help us all.", BOT_USERNAME)

    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
