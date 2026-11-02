"""
@IsekaiGraveBot — ایسکای‌ِ متنیِ رنگی با ایزدبانوی پایان
Stack: aiogram 3.27+ + motor (MongoDB) | Deploy: Railway (long polling worker)

ENV:
  TELEGRAM_BOT_TOKEN  (required)
  MONGO_URI           (required)
  MONGO_DB_NAME       (optional, default: isekai_grave)
  RANDOM_DROP_CHANCE  (optional, default: 0.02)   شانس بازار سیاه‌ی تصادفی
  ADMIN_USER_IDS      (optional) آیدی عددی ادمین‌ها با کاما: "123456789,987654321"

نکته: از BotFather گزینه‌ی Group Privacy رو Disable کن تا ربات پیام‌های عادی گروه رو ببینه.

🎨 رنگ پنل‌ها:
تلگرام به متن رنگ نمیده؛ تنها رنگِ واقعی همون «استایل دکمه‌های اینلاین»ـه (Bot API 9.4+):
  success = سبز | danger = قرمز | primary = آبی
پس هر پنل زیرش دکمه‌های رنگی داره (منوی اصلی با نوشتن «زندگی من» باز میشه).
"""

import asyncio
import html
import logging
import os
import random
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message, User,
)
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from pymongo import ReturnDocument

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("isekai-grave")

# ───────────────────────────── Config ─────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "isekai_grave")
RANDOM_DROP_CHANCE = float(os.getenv("RANDOM_DROP_CHANCE", "0.02"))
# آیدی‌های ادمین (با کاما جدا بشن، مثلاً: "123456789,987654321")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()]
HERALD_CHANCE = 0.04
LOOT_CHANCE = 0.03             # صندوق گنج / بمب ساعتی‌ی تصادفی در گروه
RAID_SPAWN_CHANCE = 0.004      # ظهور خودکار باس

DROP_COOLDOWN = 20 * 60
LOOT_COOLDOWN = 8 * 60
SELF_DEATH_COOLDOWN = 20
FORCED_TARGET_COOLDOWN = 120
HERALD_COOLDOWN = 30 * 60
OFFER_TTL = 15 * 60
EXPLORE_COOLDOWN = 12          # ثانیه بین دو سفر
WHEEL_COOLDOWN = 24 * 3600     # گردونه‌ی شانس
DUEL_TTL = 3 * 60              # مهلت قبول دوئل
GUILD_WAR_COOLDOWN = 30 * 60
SIEGE_COOLDOWN = 30 * 60
GUILD_COST = 60                # هزینه‌ی ساخت گیلد (طلا)
GUILD_MAX_MEMBERS = 30
START_GOLD = 100
LOOT_TTL = 3 * 60
BOMB_FUSE = 45                 # ثانیه تا انفجار بمب
RAID_TTL = 30 * 60
RAID_COOLDOWN = 2 * 3600
RAID_HIT_COOLDOWN = 12
PROPOSAL_TTL = 5 * 60
REG_PROMPT_COOLDOWN = 45

store: "Store" = None  # type: ignore
BOT_USERNAME = ""
BOT_STARTED = time.time()

# ───────────────────────────── 🎨 Color system ─────────────────────────────
# تلگرام فقط برای «دکمه‌ها» رنگ واقعی داره: success=سبز، danger=قرمز، primary=آبی.
STYLE = {"red": "danger", "orange": "danger", "green": "success", "blue": "primary", "purple": "primary"}

# کمیابی آیتم‌ها: (نام، ایموجی رنگی، وزن، ارزش طلا)
RARITIES = [
    ("معمولی", "⬜", 50, 5),
    ("غیرمعمول", "🟩", 25, 12),
    ("نادر", "🟦", 14, 30),
    ("حماسی", "🟪", 7, 70),
    ("افسانه‌ای", "🟨", 3, 150),
    ("نفرین‌شده", "🟥", 1, 0),
]


def btn(text: str, data: Optional[str] = None, color: Optional[str] = None, url: Optional[str] = None):
    """دکمه‌ی اینلاین رنگی. color: green / red / blue (بقیه = رنگ پیش‌فرض تلگرام)."""
    kw: dict = {"text": text}
    if url:
        kw["url"] = url
    else:
        kw["callback_data"] = data
    st = STYLE.get(color or "")
    if st:
        kw["style"] = st
    return InlineKeyboardButton(**kw)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


PANEL_SQUARES = {"red": "🟥", "orange": "🟧", "yellow": "🟨", "green": "🟩",
                 "blue": "🟦", "purple": "🟪", "black": "⬛", "brown": "🟫"}


def panel(color: str, icon: str, title: str, lines: list, foot: Optional[str] = None) -> str:
    """پنل رنگی: نوار رنگیِ بالا + عنوان + بلاک‌کوت. lines باید از قبل HTML-safe باشن."""
    sq = PANEL_SQUARES.get(color, "🟪")
    body = "\n".join(lines).replace("┈┈┈┈┈┈┈┈┈┈", sq * 6)
    s = f"{sq * 8}\n{icon} <b>{esc(title)}</b>\n<blockquote>{body}</blockquote>"
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
    "امتیاز هنری مرگ: {s}/۱۰. من داور بی‌رحمی‌ام و این امتیاز، عادلانه‌ست. 😮‍💨",
    "امتیاز هنری مرگ: {s}/۱۰. وسطش خمیازه کشیدم. دفعه‌ی بعد حداقل تلاش کن. 🥱",
    "امتیاز هنری مرگ: {s}/۱۰. هیچ‌کس دست نزد؛ فقط پشه‌ها وزوز کردن. 🦟",
]

FORCED_OPENERS = [
    "💅 <b>ایزدبانوی بی‌رحم</b> انگشتشو بالا آورد: {a} اعدام {t} رو سفارش داد. قبول کردم؛ چون دلم می‌خواست.",
    "📜 حکم صادر شد! {a} می‌خواد {t} رو بفرستیم ایسکای. دلیلش؟ «حال گروه خوب بشه». بی‌رحمانه‌ترین دلیل ممکن؛ دوستش دارم.",
    "🔔 اعلام عمومی: {t} یه نفس اضافه تو این گروه کشید. {a} هم نخواست تنها بره جهنم… یعنی ایسکا. حکم اجرا میشه.",
]

ROASTS = [
    "صدام زدی؟ جرئتت رو تحسین می‌کنم، عقلت رو نه. یه بار دیگه بی‌دلیل صدام کنی، روحت رو ته صف می‌ذارم. 💀",
    "من ایزدبانوی پایانم، نه خدمتکار تو. حرف حسابی داری بزن، وگرنه گم شو و «ریسپاون» بنویس. 🙄",
    "اوه، یه انسان دیگه. حدس می‌زنم حوصله‌ت سر رفته و فکر کردی من باید سرگرمت کنم؟ اشتباه فکر کردی. 😒",
    "پنجاه میلیون روح تو صف دارم و تو وقتم رو با حرف‌های بی‌ربطت می‌گیری. دلت می‌خواد جاشون وایسی؟",
    "نشنیدم. نمی‌خوام هم بشنوم. برو کاری بکن که ارزش دیدن داشته باشه. ✨",
    "من دروازه‌ی آخر رو نگه می‌دارم، نه جواب پیام‌های بی‌ربط رو. دفعه‌ی بعد جوابت یه نفرینه.",
    "سرنوشتت رو نوشته بودم، بعد قهوه ریختم روش. حالا هر چی بشه تقصیر خودته. 😌☕",
]

GODDESS_NAME = "ایزدبانوی پایان"
GODDESS_TITLE = "الیسیا، نگهبانِ دروازه‌ی آخر"

# لحن ایزدبانو: تند، تئاتری، بی‌حوصله… و گاهی (خیلی کم) یه لغزشِ مهربونانه
G_TENDER = [
    "…(زیر لب) مراقب خودت باش. نه برای این‌که مهمی؛ برای این‌که کاغذبازیِ بازتولدت حالمو بد می‌کنه. 🌙",
    "هه. امروز کمتر از همیشه ازت متنفرم. قدرشو بدون؛ فردا برمی‌گردم سر عادتم. ✨",
    "اگه یه روز واقعاً ته خط رسیدی، اول منو صدا بزن. نه برای کمک؛ می‌خوام اولین نفری باشم که می‌خنده. …شوخی بود. شاید. 🤍",
]
G_BY_MOOD = {
    "newbie": [
        "بوی «تازه‌واردِ بی‌تجربه» میاد. نگران نباش، همه‌ی قبرها یه روز خالی بودن… قبر تو هم آماده‌ست. ⚰️",
        "هنوز یه بارم نمردی؟ تو رو تو دفترم ندارم. یا خیلی ترسوئی، یا خیلی بی‌اهمیت. 🥱",
    ],
    "fragile": [
        "نرخ بقات اونقدر پایینه که حتی عنکبوت‌ها نگرانت شدن. زنده موندنت فقط حوصله‌ی منو سر می‌بره. 🕯",
        "با آخرین قطره‌ی بقات ماجراجویی می‌کنی؟ احمق‌ها همیشه خوشمزه‌ترین روح‌های صف‌ان. 💀",
    ],
    "veteran": [
        "اوه، مشتریِ ثابتِ دروازه‌ی من. تخفیف؟ نه. ولی یه چای سرد برات دارم. ☕",
        "اسمتو با ماژیک قرمز تو دفتر نوشتم؛ چون جوهر سیاه تموم شده بود. نه چون مهمی. 🖋",
    ],
    "rich": [
        "بوی طلا میاد… آه، منظورم «بوی گناه» بود. پولداری؟ سهم من رو آماده کن، وگرنه همه‌ش رو می‌گیرم. 🪙",
    ],
    "default": [
        "ادامه بده. من تماشا می‌کنم و چای می‌خورم؛ هر چی بیشتر بمیری، سریال طولانی‌تر میشه. 🍵",
        "قهرمان؟ نه. ولی سرگرم‌کننده‌ای. تو ایسکا، همین هم به‌زور کافیه.",
        "وقتی همه‌چی خراب شد، تقصیر «شانس» نیست؛ تقصیر توئه. من فقط شاهدم… و می‌خندم. 😌",
    ],
}


def goddess_mood(doc: Optional[dict]) -> str:
    if not doc:
        return "default"
    if doc.get("survival_rate", 100) < 18:
        return "fragile"
    if doc.get("death_count", 0) >= 8:
        return "veteran"
    if doc.get("gold", 0) >= 600:
        return "rich"
    if doc.get("death_count", 0) == 0:
        return "newbie"
    return "default"


def gsay(doc: Optional[dict] = None) -> str:
    """یه جمله‌ی کوتاهِ ایزدبانو؛ متناسب با وضعیت بازیکن. ۸٪ مواقع لغزش مهربونانه."""
    if random.random() < 0.08:
        return random.choice(G_TENDER)
    return random.choice(G_BY_MOOD[goddess_mood(doc)] + G_BY_MOOD["default"])


def gline(doc: Optional[dict] = None) -> str:
    return f"💅 <i>«{gsay(doc)}»</i>"


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

# ───────────────────────────── 📜 ثبت‌نام: کلاس‌ها و سوگندها ─────────────────────────────
CLASSES = {
    "warrior": {"name": "شمشیرزنِ ورشکسته", "icon": "⚔️", "color": "red",
                "desc": "در نبردها و دوئل‌ها قوی‌تری 💪",
                "quip": "شمشیرتو آوردی؟ آه، «قرض گرفتی». تو اولین کسی نیستی که با شمشیرِ قرضی می‌میره."},
    "mage": {"name": "جادوگرِ بی‌مجوز", "icon": "🔮", "color": "blue",
             "desc": "۲۰٪ تجربه‌ی (XP) بیشتر می‌گیری 📈",
             "quip": "بی‌مجوز؟ مهم نیست؛ من رئیس سازمان مجوزهام. ولی اگه جادوت اذیتم کنه، مجوزت باطله… همراه با خودت."},
    "rogue": {"name": "دزدِ پاره‌وقت", "icon": "🗡", "color": "green",
              "desc": "۲۵٪ طلای بیشتر از گنج‌ها و غنیمت‌ها 🪙",
              "quip": "جیب‌برها رو دوست دارم؛ حداقل تو کارشون صادقن. فقط از جیب من نگذر، وگرنه دستت رو نمی‌بینی."},
    "priest": {"name": "کشیشِ بی‌اعتقاد", "icon": "✨", "color": "purple",
               "desc": "۳۰٪ شفای بیشتر از چشمه‌ها، قهوه و معجون‌ها 💚",
               "quip": "کشیشی که به من اعتقاد نداره؟ جالبه. نگران نباش؛ بعد از مرگ، اعتقاد خودش میاد."},
}

BOONS = {
    "gold": {"name": "کیسه‌ی طلای ایزدبانو", "icon": "🪙", "color": "green",
             "desc": "+۱۵۰ طلای اولیه", "quip": "پول؟ ازش بد استفاده می‌کنی؛ همه همین‌کارو می‌کنن."},
    "xp": {"name": "پرتوی تجربه", "icon": "🌟", "color": "blue",
           "desc": "+۱۰۰ XP و شروع از سطح ۲", "quip": "سطح دو؟ از جای بلندتر سقوط می‌کنی. چه خوب."},
    "relic": {"name": "یادگارِ آخرالزمانی", "icon": "🏺", "color": "red",
              "desc": "یه آیتم افسانه‌ایِ تضمینی", "quip": "یه شیء خاص… اغلب با نفرین بسته‌بندی شده. هدیه‌ی منه؛ قدرشو بدون، وگرنه پس می‌گیرمش."},
}

# ───────────────────────────── 📜 ماموریت‌های روزانه/هفتگی ─────────────────────────────
# (kind، متن، هدف، طلا، XP)
DAILY_POOL = [
    ("trip", "امروز {n} بار ماجراجویی کن (سفر/گردش)", 3, 45, 25),
    ("trip", "امروز {n} بار به سرزمین‌های ایسکای سفر کن", 5, 70, 35),
    ("curse", "تو گروه یه نفر رو نفرین کن (ریپلای + «نفرینت می‌کنم»)", 1, 40, 20),
    ("bless", "برای یه نفر تو گروه دعای خیر کن (ریپلای + «دعات می‌کنم»)", 1, 40, 20),
    ("duel", "تو یه دوئل شرکت کن", 1, 50, 25),
    ("wheel", "گردونه‌ی شانس رو بچرخون", 1, 35, 15),
    ("npc", "با {n} تا NPC تو شهر حرف بزن", 2, 40, 20),
    ("chest", "یه صندوق گنج یا بمب ساعتی‌ی گروه رو برنده شو", 1, 60, 30),
    ("boss", "به باس گروه {n} بار حمله کن", 3, 70, 40),
]
WEEKLY_POOL = [
    ("trip", "این هفته {n} بار ماجراجویی کن", 40, 250, 120),
    ("duel_win", "این هفته {n} دوئل رو ببر", 5, 280, 130),
    ("war", "این هفته {n} بار تو جنگ گیلدها شرکت کن", 3, 260, 120),
]

# ───────────────────────────── 🐉 باس‌ها و قلمروها ─────────────────────────────
BOSSES = [
    ("اژدهای وگانِ سه‌سر", "🐉"), ("پادشاه شیاطینِ بیکار", "👿"), ("کراکنِ بدهکار", "🐙"),
    ("گولِمِ اداری", "🗿"), ("وای‌فایِ نفرین‌شده‌ی اعظم", "📶"), ("هیولای صف نون", "👹"),
]
BOSS_HITS = [
    "با تمام قدرتش ضربه زد", "یه ضربه‌ی سینمایی فرود آورد", "با شجاعتِ احمقانه حمله کرد",
    "از پشت نامردانه زد", "طلسم خوند و ضربه خورد (هر دو)",
]

# قلمروهای نقشه‌ی جهان: کلید → (نام، ایکون، قدرت نگهبان NPC)
TERRITORIES = {
    "capital": ("پایتخت درخشان", "🏰", 140),
    "castle": ("قلعه‌ی تاریک", "🏯", 190),
    "forest": ("جنگل عمیق", "🌲", 100),
    "port": ("بندر طوفان", "⚓", 120),
    "ruins": ("خرابه‌های باستانی", "🏛", 160),
}
TERR_INCOME = 4  # طلای اضافه به‌ازای هر قلمرو در هر سفر (برای اعضای گیلدِ مالک)


def roast_for(doc: dict) -> str:
    dc = doc.get("death_count", 0)
    titles = doc.get("titles") or []
    t = f" «{esc(titles[-1])}»" if titles else ""
    if dc == 0:
        return "اوه، یه چهره‌ی تازه! هنوز یه بار هم نمردی؛ خوش اومدی، مراقب خودت باش. 🙂"
    if dc < 3:
        return f"{dc} بار مردی و باز برگشتی. پشتکارت قشنگه! 💪"
    if dc < 10:
        return f"آه، همون{t} که {dc} بار مرده! پشتکارت رو دوست دارم؛ یه چای مهمون من. ☕"
    return f"{dc} بار مردی؟! تو دیگه از قدیمی‌های اینجایی. بیا، یه چای مهمون من. 🍵"


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
    # علائم نگارشی حذف میشن ولی @یوزرنیم‌ها (که ممکنه _ داشته باشن) دست‌نخورده می‌مونن
    parts = re.split(r"(@\w{1,32})", n)
    out = "".join(p if p.startswith("@") else _PUNCT.sub(" ", p) for p in parts)
    return re.sub(r"\s+", " ", out).strip()


def esc(s: Optional[str]) -> str:
    return html.escape(s or "", quote=False)


DISTRESS_RE = re.compile(
    r"(می\s*خوام\s*بمیرم|می\s*خوام\s*خودمو\s*بکشم|دلم\s*می\s*خواد\s*بمیرم|"
    r"کاش\s*(بمیرم|می\s*مردم|نبودم)|(?<!\S)منو\s*بکش(?!\S)|(?<!\S)منو\s*بکشید|خودکشی\s*(می\s*کنم|کنم))"
)
DEATH_RE = re.compile(r"(ریسپاون|ریسپان|مرگ\s*داوطلبانه|منو\s*بفرست\s*(به\s*)?(ایسکای|ایسکا|ایزکای))")
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
# --- جدید ---
MENU_RE = re.compile(r"^(زندگی\s*من|منو|منوی\s*اصلی|پنل|پنل\s*ها|پنل\s*من)$")
REG_RE = re.compile(r"^(ثبت\s*نام|ثبتنام|قرارداد|امضا\s*قرارداد|ثبت\s*نام\s*میکنم)$")
QUEST_RE = re.compile(r"^(ماموریت(\s*ها)?(\s*(روزانه|هفتگی|من))?|ماموریت\s*امروز|دفتر\s*ماموریت)$")
TERR_RE = re.compile(r"^(قلمرو(ها)?|نقشه(\s*جهان)?|تاج\s*پادشاهی|پادشاه\s*هفته|پادشاه)$")
SIEGE_RE = re.compile(r"^(محاصره|حمله\s*به\s*قلمرو)\s+(.+)$")
OPEN_RE = re.compile(r"^(باز\s*کردن|باز\s*کن|صندوق\s*رو\s*باز\s*میکنم|خالی\s*کردن(\s*صندوق)?|صندوق\s*رو\s*خالی\s*میکنم)$")
DEFUSE_RE = re.compile(r"^(خنثی(\s*کردن)?|بمب\s*رو\s*خنثی\s*میکنم|خنثی\s*میکنم)$")
MARRY_RE = re.compile(r"^ازدواج(\s*با\s*(@(\w{4,32})|من))?$")
MARRY_ACCEPT_RE = re.compile(r"^(قبول\s*ازدواج|قبول\s*پیوند|بله\s*قبوله|ازدواج\s*رو\s*قبول\s*میکنم)$")
MARRY_DECLINE_RE = re.compile(r"^(رد\s*ازدواج|رد\s*پیوند|نه\s*ممنون)$")
DIVORCE_RE = re.compile(r"^(طلاق|جدایی|فسخ\s*پیوند)$")
BOSS_CALL_RE = re.compile(r"^(احضار\s*(باس|غول|اژدها)|باس\s*احضار\s*کن|باس\s*بیار)$")
BOSS_HIT_RE = re.compile(r"^(حمله\s*به\s*(باس|غول|اژدها|هیولا)|حمله\s*باس|ضربه\s*به\s*باس)$")
BOSS_STATUS_RE = re.compile(r"^(وضعیت\s*باس|باس)$")
# --- ادمین ---
ADMIN_PANEL_RE = re.compile(r"^(پنل\s*ادمین|مدیریت|ادمین\s*پنل)$")
ADMIN_STATS_RE = re.compile(r"^(آمار\s*ربات|وضعیت\s*سیستم|آمار)$")
ADMIN_HEALTH_RE = re.compile(r"^(سلامت\s*سرور|سلامت\s*سیستم|چک\s*سرور)$")
ADMIN_CLEAN_RE = re.compile(r"^(پاکسازی|پاکسازی\s*دیتابیس)$")
ADMIN_BAN_RE = re.compile(r"^بن(\s*(\d+))?$")
ADMIN_UNBAN_RE = re.compile(r"^آنبن(\s*(\d+))?$")
ADMIN_KILL_RE = re.compile(r"^کشتن\s*(\d+)$")
ADMIN_BROADCAST_RE = re.compile(r"^سراسری\s+(.+)$", re.DOTALL)

BOARD_RE = re.compile(r"(رتبه\s*گروه|لیدربرد|جدول\s*رتبه|رده\s*بندی|رتبه\s*بندی)")

SMALL_TALK_HELP = (
    "📖 <b>راهنمای بازی</b>\n"
    "همه‌چیز با نوشتن یه جمله‌ی ساده یا زدن دکمه انجام میشه. 😊\n\n"
    "🟩 <b>شروع:</b> بنویس «زندگی من» تا منوی بازی باز بشه\n"
    "🟢 <b>سفر:</b> «سفر به جنگل» · «رفتم دریا» · «ورود به شهر» · «خرابه» · «گردش»\n"
    "🟣 <b>NPC (آدم‌های شهر):</b> «گفتگو با پیرمرد» · «حرف زدن با مغازه‌دار» · «ورود به کافه»\n"
    "🔵 <b>گیلد (تیم):</b> «ساخت گیلد [نام]» · «پیوستن به گیلد [نام]» · «گیلد من» · «جنگ گیلدها»\n"
    "👑 <b>قلمرو:</b> «قلمروها» · «محاصره [نام قلمرو]»\n"
    "🟠 <b>دوئل:</b> «دوئل با @یوزرنیم» یا ریپلای + «دوئل» · «قبول دوئل»\n"
    "🟡 <b>شانس:</b> «گردونه شانس» · «ماموریت» · «رتبه گروه» · «لیدربرد»\n"
    "🎁 <b>گروه:</b> «باز کردن» (صندوق) · «خنثی کردن» (بمب) · «احضار باس» · «حمله به باس»\n"
    "💍 <b>پیوند:</b> «ازدواج با @یوزرنیم» · «قبول ازدواج» · «طلاق»\n"
    "⬛ <b>بازار سیاه:</b> «بازار سیاه» · «میخرم»\n"
    "🔴 <b>مرگ و نفرین:</b> «ریسپاون» · «@یوزرنیم رو بفرست ایسکای» · ریپلای + «نفرینت می‌کنم» یا «دعات می‌کنم»\n"
    "⚪ <b>پروفایل:</b> «کارت من» · «لقب هام چیه» · «کوله پشتی» · «لینک دعوت» · «من بازی نمیکنم»\n\n"
    "💡 <i>گیج شدی؟ فقط «زندگی من» بنویس و دکمه‌ها رو بزن.</i>"
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
        self.meta = db["meta"]
        self.proposals = db["proposals"]
        self.drops = db["drops"]
        self.raids = db["raids"]
        self.territories = db["territories"]

    async def ensure_indexes(self):
        await self.users.create_index("user_id", unique=True)
        await self.users.create_index("username_lower")
        await self.users.create_index("chats")
        await self.users.create_index("guild")
        await self.offers.create_index([("chat_id", 1), ("status", 1)])
        await self.guilds.create_index("name_lower", unique=True)
        await self.groups.create_index("chat_id", unique=True)
        await self.duels.create_index([("chat_id", 1), ("status", 1)])
        await self.proposals.create_index([("to", 1), ("status", 1)])
        await self.drops.create_index([("chat_id", 1), ("status", 1)])
        await self.raids.create_index([("chat_id", 1), ("status", 1)])
        await self.territories.create_index("key", unique=True)
        # کاربرهای قدیمی (قبل از سیستم ثبت‌نام) رو خودکار «ثبت‌شده» حساب کن
        await self.users.update_many({"registered": {"$exists": False}}, {"$set": {"registered": True, "cls": None}})

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
                    "registered": False, "cls": None, "pact": None, "spouse": None, "spouse_name": None,
                    "banned": False, "quests": None,
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
    res = await refresh_titles(doc)
    # 💍 پیوند ایسکایی: مرگ یکی، دیگری رو هم زخمی می‌کنه
    sp = doc.get("spouse")
    if sp:
        sdoc = await adjust_survival(sp, -6)
        await store.users.update_one({"user_id": sp, "gold": {"$gte": 10}}, {"$inc": {"gold": -10}})
        if sdoc:
            res[0]["_bond"] = sdoc.get("first_name") or "همسرش"
    return res


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
        if xp > 0:
            who = await store.users.find_one({"user_id": uid}, {"cls": 1})
            if who and who.get("cls") == "mage":
                xp = int(xp * 1.2)  # 🔮 جادوگر: ۲۰٪ XP بیشتر
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


def cls_is(doc: Optional[dict], key: str) -> bool:
    return bool(doc) and doc.get("cls") == key


def gold_bonus(doc: Optional[dict], g: int) -> int:
    return int(g * 1.25) if cls_is(doc, "rogue") else g       # 🗡 دزد: ۲۵٪ طلای بیشتر


def heal_bonus(doc: Optional[dict], h: int) -> int:
    return int(h * 1.3) if cls_is(doc, "priest") else h        # ✨ کشیش: ۳۰٪ شفای بیشتر


# ───────────────────────────── Rendering ─────────────────────────────

def rate_comment(r: int) -> str:
    if r < 8:
        return "بقات از آبکش هم سوراخ‌تره. نگران نباش؛ مرگت رو شخصاً تماشا می‌کنم. 🫥"
    if r < 16:
        return "با این آمار، اسلایم‌ها هم بهت می‌خندن. منم همین‌طور. 😏"
    if r < 26:
        return "نه عالی، نه افتضاح؛ یعنی کاملاً معمولی. حوصله‌م سر رفت."
    return "نسبتاً بالاست… یعنی فقط تا اولین اشتباهت. منتظرم. 😏"


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
    if doc.get("_bond"):
        lines.append(f"💍 پیوندِ ایسکایی! {esc(doc['_bond'])} هم از این مرگ زخمی شد (−۶٪ بقا، −۱۰ طلا).")
    s = panel(color, "🔮", "بازتولد موفق!", lines, rate_comment(r))
    if new_titles:
        s += "\n\n🏷 <b>لقب جدید ثبت شد:</b> " + "، ".join(f"«{esc(t)}»" for t in new_titles)
    return s


def render_scene(name_html: str) -> str:
    scene = random.choice(SCENES).replace("{n}", name_html)
    judge = random.choice(GODDESS_JUDGE).format(s=random.randint(1, 10))
    return f"{scene}\n\n🗣 آخرین حرف: {random.choice(LAST_WORDS)}\n<i>{judge}</i>"


def class_label(doc: dict) -> str:
    c = CLASSES.get(doc.get("cls") or "")
    return f"{c['icon']} {c['name']}" if c else "—"


def render_passport(doc: dict) -> str:
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
        f"🎭 کلاس: {class_label(doc)}",
        f"💍 پیوند: {esc(doc.get('spouse_name')) if doc.get('spouse') else 'مجرد'}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
        f"📌 وضعیت: {esc(doc.get('status'))}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"☠️ مرگ‌ها: {doc.get('death_count', 0)} | 😈 نفرین‌ها: {doc.get('curses_received', 0)} | 🙏 دعاها: {doc.get('blessings_received', 0)}",
        f"⚔️ دوئل: {doc.get('wins', 0)} برد / {doc.get('losses', 0)} باخت",
    ]
    foot = f"🎒 کوله‌پشتی: {esc('، '.join(inv[-3:])) if inv else 'خالی'}"
    if not doc.get("death_count"):
        foot += "\n💅 <i>«هنوز یه بارم نمردی؟ حیف. بنویس «ریسپاون» تا یه مرگِ درست‌وحسابی بهت هدیه بدم.»</i>"
    return panel("purple", "🎴", "پاسپورت ایسکای", lines, foot)


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
        await say(m, "یه کم آروم‌تر! چند ثانیه صبر کن و دوباره امتحان کن. ⏳", "⏳", "یه لحظه صبر کن", "orange")
        return
    _last_self_death[uid] = now
    doc, new = await reincarnate(uid, chat_id=gid(m))
    name = esc(m.from_user.full_name)
    await m.reply(f"{render_scene('<b>' + name + '</b>')}\n\n{render_rebirth(doc, new)}",
                  reply_markup=after_death_kb(uid))


async def do_distress(m: Message):
    await m.reply(
        "🤍 <b>یه لحظه نقش ایزدبانوی بداخلاق رو میذارم کنار.</b>\n\n"
        "اگه این حرف از ته دلته و واقعاً حالت بده، مهمه و جدیش می‌گیرم. "
        "با یه آدم مورد اعتماد حرف بزن. اگه تو ایران هستی، <b>۱۲۳</b> (اورژانس اجتماعی) "
        "یا خط مشاوره‌ی <b>۱۴۸۰</b> رو بگیر؛ اگه خطر همین الان تهدیدت می‌کنه، <b>۱۱۵</b>.\n\n"
        "من هم همین‌جام؛ بگو چی شده. اگه فقط شوخی بود و بازی می‌خوای، بنویس «زندگی من»."
    )


# ───────────────────────────── 🔘 زیرساخت دکمه‌ها / پنل‌ها ─────────────────────────────
_recent_chatters: dict = defaultdict(lambda: deque(maxlen=8))   # chat_id → [(uid, name)]
_bg_tasks: set = set()
_last_reg_prompt: dict = {}
_last_loot: dict = {}
_last_raid_hit: dict = {}


def spawn(coro):
    """اجرای تسک پس‌زمینه بدون اینکه garbage-collect بشه."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


class CbMsg:
    """شیمِ پیام برای کلیک دکمه‌ها: توابع do_* رو بدون تغییر با دکمه اجرا می‌کنه."""

    def __init__(self, cq: CallbackQuery, bot: Bot):
        self.from_user = cq.from_user
        self.chat = cq.message.chat
        self.message_id = cq.message.message_id
        self.bot = bot
        self.reply_to_message = None
        self.text = ""
        self._msg = cq.message

    async def reply(self, text, **kw):
        return await self._msg.answer(text, **kw)

    answer = reply


async def say(m, text: str, icon: str = "💅", title: str = GODDESS_NAME, color: str = "purple",
              markup: Optional[InlineKeyboardMarkup] = None, foot: Optional[str] = None):
    """پیام ربات داخل پنل (به‌جای متن خالی)."""
    return await m.reply(panel(color, icon, title, [text], foot), reply_markup=markup)


async def safe_edit(msg, text: str, markup: Optional[InlineKeyboardMarkup] = None):
    try:
        await msg.edit_text(text, reply_markup=markup)
    except Exception as e:  # message is not modified / پیام قدیمی
        log.debug("edit failed: %s", e)


def mention(u: User) -> str:
    return f'<a href="tg://user?id={u.id}">{esc(u.full_name)}</a>'


def hub_kb(uid: int) -> InlineKeyboardMarkup:
    u = uid
    return kb(
        [btn("🎴 کارت من", f"m:pass:{u}", "blue"), btn("🎒 کوله‌پشتی", f"m:inv:{u}", "green")],
        [btn("🌍 ماجراجویی", f"m:go:{u}", "green"), btn("🧙 NPCها", f"m:npc:{u}", "blue")],
        [btn("🎡 گردونه‌ی شانس", f"m:wheel:{u}", "green"), btn("📜 ماموریت‌ها", f"m:quest:{u}", "blue")],
        [btn("🛡 گیلد من", f"m:guild:{u}", "blue"), btn("⚔️ جنگ گیلدها", f"m:war:{u}", "red")],
        [btn("👑 قلمروها", f"m:terr:{u}", "green"), btn("🐉 باس گروه", f"m:boss:{u}", "red")],
        [btn("💍 پیوند", f"m:marry:{u}", "red"), btn("🏆 لیدربرد", f"m:board:{u}", "blue")],
        [btn("🕶 بازار سیاه", f"m:market:{u}", "red"), btn("📖 راهنما", f"m:help:{u}", "blue")],
        [btn("☠️ مرگ داوطلبانه", f"m:die:{u}", "red")],
    )


def hub_text(doc: dict) -> str:
    name = esc(doc.get("first_name") or "ناشناس")
    titles = doc.get("titles") or []
    lines = [
        f"👤 <b>{name}</b>" + (f" ‹{esc(titles[-1])}›" if titles else ""),
        f"🎭 {class_label(doc)}   🛡 {esc(doc.get('guild')) if doc.get('guild') else 'بی‌گیلد'}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
    ]
    return panel("purple", "🌙", "پنل‌های ایزدبانوی پایان", lines, gline(doc))


def back_kb(uid: int) -> list:
    return [btn("🔙 برگشت به منو", f"m:main:{uid}", "blue")]


def after_explore_kb(uid: int, key: str) -> InlineKeyboardMarkup:
    return kb(
        [btn("🌍 دوباره بگرد", f"x:{key}:{uid}", "green"), btn("🎴 کارت من", f"m:pass:{uid}", "blue")],
        [btn("📜 ماموریت‌ها", f"m:quest:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")],
    )


def after_death_kb(uid: int) -> InlineKeyboardMarkup:
    return kb([btn("🌍 برگردم ماجراجویی", f"m:go:{uid}", "green"), btn("🎴 کارت من", f"m:pass:{uid}", "blue")])


async def send_hub(m, doc: Optional[dict] = None):
    doc = doc or await store.get(m.from_user.id)
    await m.reply(hub_text(doc), reply_markup=hub_kb(m.from_user.id))


# ───────────────────────────── 📜 سیستم ثبت‌نام ─────────────────────────────
def reg_text_intro(name: str) -> str:
    return panel("purple", "📜", "قرارداد روحِ ایسکای", [
        f"{GODDESS_NAME}، <i>{GODDESS_TITLE}</i>، به <b>{esc(name)}</b> خیره شد…",
        "💅 «یه روحِ تازه. اسمت تو لیست اشک‌ریزان نیست؛ یعنی هیچ‌کس برات گریه نمی‌کنه. عالی. قراردادمو امضا کن، وگرنه از دروازه‌م رد نمیشی.»",
        "┈┈┈┈┈┈┈┈┈┈",
        "برای شروع بازی، ۳ مرحله داری (فقط چند کلیکه 🙂):",
        "① 🩸 امضای قرارداد",
        "② 🎭 انتخاب کلاس (نوع شخصیتت)",
        "③ 🕯 انتخاب هدیه‌ی شروع",
        "┈┈┈┈┈┈┈┈┈┈",
        "⚠️ <i>ریزنوشت: روحِ تو از این لحظه ملکِ منه. بازگشت پول و فرار ممنوع.</i>",
    ])


def reg_kb_intro(uid: int) -> InlineKeyboardMarkup:
    return kb(
        [btn("🩸 امضا می‌کنم", f"reg:sign:{uid}", "green")],
        [btn("🏃 فرار از ایزدبانو", f"reg:run:{uid}", "red")],
    )


def reg_text_class() -> str:
    lines = ["هر کلاس یه امتیاز ویژه داره؛ یکی رو انتخاب کن 👇", *[f"{c['icon']} <b>{c['name']}</b> — {c['desc']}" for c in CLASSES.values()]]
    return panel("blue", "🎭", "مرحله‌ی ۲: کلاس‌ت رو انتخاب کن", lines,
                 "💅 <i>«زیاد فکر نکن؛ هر کدوم رو برداری، آخرش مال منی.»</i>")


def reg_kb_class(uid: int) -> InlineKeyboardMarkup:
    ks = list(CLASSES.items())
    mk = lambda k, c: btn(f"{c['icon']} {c['name']}", f"reg:cls:{k}:{uid}", c["color"])
    return kb([mk(*ks[0]), mk(*ks[1])], [mk(*ks[2]), mk(*ks[3])])


def reg_text_boon(cls_key: str) -> str:
    c = CLASSES[cls_key]
    lines = [f"{b['icon']} <b>{b['name']}</b> — {b['desc']}" for b in BOONS.values()]
    return panel("red", "🕯", "مرحله‌ی ۳: سوگند به ایزدبانو", [
        f"💅 «{c['quip']}»",
        "┈┈┈┈┈┈┈┈┈┈",
        "هدیه‌ی شروعت رو انتخاب کن (فقط یکی):",
        *lines,
    ])


def reg_kb_boon(cls_key: str, uid: int) -> InlineKeyboardMarkup:
    return kb(*[[btn(f"{b['icon']} {b['name']}", f"reg:boon:{cls_key}:{k}:{uid}", b["color"])] for k, b in BOONS.items()])


async def finish_registration(user: User, cls_key: str, boon_key: str) -> Optional[dict]:
    """ثبت‌نام رو نهایی می‌کنه. اگه قبلاً ثبت‌نام شده باشه None برمی‌گردونه."""
    form, _ = random.choice(FORMS)
    rate = random.randint(55, 90)
    res = await store.users.update_one(
        {"user_id": user.id, "registered": {"$ne": True}},
        {"$set": {
            "registered": True, "cls": cls_key, "pact": boon_key, "registered_at": utcnow(),
            "form": form, "cheat_skill": random.choice(CHEATS), "world": random.choice(WORLDS),
            "survival_rate": rate, "status": status_for(rate), "first_name": user.full_name,
        }, "$push": {"titles": "روحِ ثبت‌شده‌ی ایزدبانو"}},
    )
    if res.modified_count == 0:
        return None
    if boon_key == "gold":
        await grant(user.id, gold=150)
    elif boon_key == "xp":
        await grant(user.id, xp=100)
    else:
        item = f"🟨 {random.choice(['تاجِ فراموش‌شده‌ی آخرالزمان', 'شمشیرِ بی‌نامِ دروازه‌ی آخر', 'حلقه‌ی پایانِ همه‌چیز'])} ‹افسانه‌ای›"
        await grant(user.id, item=item)
    return await store.get(user.id)


def reg_done_text(doc: dict, cls_key: str, boon_key: str) -> str:
    c, b = CLASSES[cls_key], BOONS[boon_key]
    return panel("green", "🎉", "قرارداد امضا شد! به ایسکا خوش اومدی", [
        f"🪪 <b>{esc(doc.get('first_name'))}</b> — {c['icon']} {c['name']}",
        f"🕯 سوگند: {b['icon']} {b['name']}",
        f"🧬 فرم اولیه: {esc(doc.get('form'))}",
        f"🌍 دنیا: {esc(doc.get('world'))}",
        f"🎁 چیت‌اسکیل: {esc(doc.get('cheat_skill'))}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
        "🏷 لقب: «روحِ ثبت‌شده‌ی ایزدبانو»",
    ], f"💅 <i>«{b['quip']} حالا برو. هر کاری می‌خوای بکن؛ آخرش مال منی.»</i>\n💡 برای باز کردن منوی بازی بنویس «زندگی من».")


async def start_registration(m):
    """پیام مرحله‌ی ۱ رو برای کاربر می‌فرسته."""
    await m.reply(reg_text_intro(m.from_user.full_name), reply_markup=reg_kb_intro(m.from_user.id))


async def reg_prompt(m):
    """وقتی ثبت‌نام‌نشده می‌خواد بازی کنه."""
    uid = m.from_user.id
    now = time.time()
    if now - _last_reg_prompt.get(uid, 0) < REG_PROMPT_COOLDOWN:
        return
    _last_reg_prompt[uid] = now
    rows = [[btn("🩸 ثبت‌نام (همین‌جا)", f"reg:go:{uid}", "green")]]
    if is_group(m) and BOT_USERNAME:
        rows.append([btn("📩 ثبت‌نام در پیوی", url=f"https://t.me/{BOT_USERNAME}?start=reg")])
    await m.reply(panel("red", "🚪", "دروازه بسته‌ست", [
        f"💅 «{esc(m.from_user.first_name)}… بدون قرارداد، دروازه‌م به روت بسته‌ست. حتی مرده‌ها فرم پر می‌کنن؛ تو از مرده‌ها هم تنبل‌تری؟»",
        "برای شروع بازی اول ثبت‌نام کن؛ فقط ۳ تا کلیکه 🙂",
    ]), reply_markup=kb(*rows))


def welcome_group_text() -> str:
    return panel("purple", "🌙", f"{GODDESS_NAME} به این گروه فرود اومد", [
        "💅 «یه گروه دیگه. چه جمعیتِ قشنگی از قربانی‌های بالقوه. از این به بعد جونتون دست منه؛ رفتارتون رو درست کنید.»",
        f"من <b>{GODDESS_TITLE}</b> هستم. از این لحظه سرنوشت همه‌ی شما دست منه.",
        "┈┈┈┈┈┈┈┈┈┈",
        "⚔️ دوئل و جنگ گیلدها  •  👑 محاصره‌ی قلمروها",
        "🎁 صندوق گنج و بمب ساعتیِ تصادفی  •  🐉 باس گروهی",
        "📜 ماموریت‌های روزانه  •  💍 پیوند ایسکایی",
        "┈┈┈┈┈┈┈┈┈┈",
        "🚀 <b>شروع سریع:</b> هر نفر یه‌بار «ثبت‌نام» می‌کنه، بعدش بنویسید «<b>زندگی من</b>» تا منوی بازی باز بشه.",
    ], "⚙️ <i>برای دیدن پیام‌های عادی گروه، Group Privacy ربات رو تو BotFather روی Disable بذارید.</i>")


WELCOME_NEW = [
    "«یه روحِ تازه‌واردِ دیگه. به باشگاه بدبخت‌ها خوش اومدی؛ ورود رایگان، خروج ممنوع.»",
    "«گوشت تازه! … منظورم «مهمون» بود. بیا تو، قبل از این‌که گرسنه‌م بشه.»",
    "«قبل از هر چیز: غذای یخچال ایسکا مال منه. دست بزنی، روحت رو برمی‌دارم. بعدش: خوش اومدی.»",
    "«این گروه یه دروازه‌ی کوچیک به جهنمه. خوش اومدی. جدی نمی‌گم… ولی خنده‌دار هم نیست.»",
]


def welcome_member_text(users: list) -> str:
    names = "، ".join(mention(u) for u in users[:4])
    return panel("green", "👁", "روحِ تازه‌وارد!", [
        f"{names} از دروازه‌ی آخر رد شد… 👋 خوش اومدی!",
        f"💅 {random.choice(WELCOME_NEW)}",
        "📜 برای شروع بازی، بنویس «ثبت‌نام» و قراردادت رو امضا کن.",
    ])


# ───────────────────────────── 🎛 هندلر دکمه‌ها ─────────────────────────────
def help_kb(uid: int) -> InlineKeyboardMarkup:
    return kb(back_kb(uid))


async def handle_cb(cq: CallbackQuery, bot: Bot):
    data = cq.data or ""
    parts = data.split(":")
    if len(parts) < 2 or not parts[-1].lstrip("-").isdigit():
        await cq.answer()
        return
    if not isinstance(cq.message, Message):
        await cq.answer("این پنل قدیمی شده؛ بنویس «زندگی من» تا دوباره باز بشه.", show_alert=True)
        return
    kind, owner = parts[0], int(parts[-1])
    user = cq.from_user
    if owner and user.id != owner:
        await cq.answer("این پنل مال یکی دیگه‌ست 🙂 پنل خودت رو با نوشتن «زندگی من» باز کن.", show_alert=True)
        return
    await store.touch(user)
    doc = await store.get(user.id)
    if doc and doc.get("banned"):
        await cq.answer("تو بن شدی. ایزدبانو دیگه تو رو نمی‌بینه؛ برای ما وجود نداری. 🚫", show_alert=True)
        return
    m = CbMsg(cq, bot)
    uid = user.id
    registered = bool(doc and doc.get("registered"))

    # ── ادمین
    if kind == "adm":
        if not is_admin(uid):
            await cq.answer("این بخش فقط برای ادمین‌هاست. 🚫", show_alert=True)
            return
        await cq.answer()
        act = parts[1]
        if act == "stats":
            await m.reply(await admin_stats())
        elif act == "health":
            await m.reply(await admin_health())
        elif act == "clean":
            await m.reply(await admin_clean())
        elif act == "help":
            await m.reply(panel("red", "🛠", "فرمان‌های ادمین", ADMIN_HELP))
        return

    # ── ثبت‌نام
    if kind == "reg":
        act = parts[1]
        if act == "go":
            if registered:
                await cq.answer("قرارداد رو قبلاً امضا کردی؛ دیگه راه برگشتی نیست. 😈", show_alert=True)
                return
            await cq.answer()
            await start_registration(m)
        elif registered:
            await cq.answer("ثبت‌نامت قبلاً انجام شده. 👍", show_alert=True)
        elif act == "sign":
            await cq.answer("قلم رو بردار… 🩸")
            await safe_edit(cq.message, reg_text_class(), reg_kb_class(uid))
        elif act == "cls" and len(parts) >= 4 and parts[2] in CLASSES:
            await cq.answer(CLASSES[parts[2]]["name"])
            await safe_edit(cq.message, reg_text_boon(parts[2]), reg_kb_boon(parts[2], uid))
        elif act == "boon" and len(parts) >= 5 and parts[2] in CLASSES and parts[3] in BOONS:
            ndoc = await finish_registration(user, parts[2], parts[3])
            if not ndoc:
                await cq.answer("قبلاً ثبت‌نام شدی.", show_alert=True)
                return
            await cq.answer("قرارداد امضا شد! 🎉")
            await safe_edit(cq.message, reg_done_text(ndoc, parts[2], parts[3]),
                            kb([btn("🌙 باز کردن پنل‌ها", f"m:main:{uid}", "green")],
                               [btn("🌍 اولین ماجراجویی", f"x:forest:{uid}", "blue")]))
        elif act == "run":
            await cq.answer("فرار؟ 🏃")
            await safe_edit(cq.message, panel("red", "🏃", "فرار ناموفق", [
                "💅 «فرار؟ از من؟ هیچ‌کس از دروازه‌ی من فرار نکرده. فرارت رو یه ثانیه تماشا کردم و خمیازه کشیدم. هر وقت خسته شدی، برگرد و التماس کن.»",
                "هر وقت آماده بودی، دکمه‌ی پایین رو بزن یا بنویس «<b>ثبت‌نام</b>».",
            ]), kb([btn("🩸 خیله‌خب، امضا می‌کنم", f"reg:go:{uid}", "green")]))
        else:
            await cq.answer()
        return

    # ── بدون ثبت‌نام فقط راهنما
    if not registered and not (kind == "m" and parts[1] == "help"):
        await cq.answer("اول ثبت‌نام کن، بعد بیا! 🙂", show_alert=True)
        await reg_prompt(m)
        return

    await cq.answer()

    if kind == "x" and parts[1] in BIOMES:
        await do_explore(m, parts[1])
    elif kind == "n" and parts[1] in NPCS:
        await do_npc(m, parts[1])
    elif kind == "duelacc":
        if not await do_duel_accept(m):
            await say(m, "این دوئل تموم شده یا برای تو نیست.", "⚔️", "دوئل", "orange")
    elif kind == "buy":
        if not await do_buy(m):
            await say(m, "دلال رفت و بازار سیاه فعلاً بسته‌ست. بعداً دوباره سر بزن. 🕶", "🕶", "بازار سیاه", "black")
    elif kind == "loot":
        await claim_drop(m, parts[1], notify_fail=True)
    elif kind == "sg" and parts[1] in TERRITORIES:
        await do_siege(m, parts[1])
    elif kind == "raid":
        if parts[1] == "hit":
            if not await do_raid_hit(m):
                await say(m, "الان باسی نیست. برای احضار بنویس «احضار باس». 🐉", "🐉", "باس", "red")
        elif parts[1] == "call":
            await do_boss_call(m, bot)
        else:
            await do_boss_status(m)
    elif kind == "mar":
        await marriage_answer(m, parts[1] == "yes", parts[2])
    elif kind == "m":
        act = parts[1]
        if act == "main":
            await safe_edit(cq.message, hub_text(doc), hub_kb(uid))
        elif act == "go":
            rows = [[btn(f"{b['icon']} {b['name']}", f"x:{k}:{uid}", b["color"])] for k, b in BIOMES.items()]
            await safe_edit(cq.message, panel("green", "🌍", "کجا بریم؟", [
                "👇 یه مکان انتخاب کن تا ماجراجویی شروع بشه.\n💅 «هر جا بری، یا بدبخت میشی یا می‌میری. هر دو برای من سرگرم‌کننده‌ست.»",
            ]), kb(*rows, back_kb(uid)))
        elif act == "npc":
            rows = [[btn(f"{n['icon']} {n['name']}", f"n:{k}:{uid}", n["color"])] for k, n in NPCS.items()]
            await safe_edit(cq.message, panel("purple", "🧙", "با کی حرف بزنیم؟", [
                "💡 NPCها فقط تو «شهر» هستن. اول به شهر برو، بعد باهاشون حرف بزن. 🏰",
            ]), kb(*rows, back_kb(uid)))
        elif act == "pass":
            await m.reply(render_passport(doc), reply_markup=kb(back_kb(uid)))
        elif act == "inv":
            await send_inventory(m, doc)
        elif act == "wheel":
            await do_wheel(m)
        elif act == "guild":
            await do_guild_me(m)
        elif act == "war":
            await do_guild_war(m)
        elif act == "board":
            await do_board(m)
        elif act == "market":
            if is_group(m):
                await m.reply(await drop_offer(m.chat.id), reply_markup=kb([btn("💸 میخرم!", "buy:0:0", "green")]))
            else:
                await say(m, "بازار سیاه فقط تو گروه‌ها باز میشه. ربات رو به گروهت اضافه کن و اونجا امتحان کن. 🕶", "🕶", "بازار سیاه", "black")
        elif act == "quest":
            await do_quests(m)
        elif act == "terr":
            await do_terr(m)
        elif act == "boss":
            await do_boss_status(m)
        elif act == "marry":
            await do_marry_info(m, doc)
        elif act == "help":
            await m.reply(SMALL_TALK_HELP, reply_markup=help_kb(uid) if registered else None)
        elif act == "die":
            await safe_edit(cq.message, panel("red", "☠️", "مرگ داوطلبانه؟", [
                "💅 «خودت می‌خوای بمیری؟ بدون کامیون، بدون رامن؟ بی‌خلاقیت‌ترین مرگی که تو این ده سال دیدم. ولی قبوله؛ بیا.»",
                "ℹ️ بعد از مرگ دوباره متولد میشی: فرم، دنیا و مهارت جدید می‌گیری و نرخ بقات تصادفی میشه.",
            ]), kb([btn("☠️ آره، بفرست", f"m:die2:{uid}", "red"), btn("🔙 نه، پشیمون شدم", f"m:main:{uid}", "green")]))
        elif act == "die2":
            await do_self_death(m)
        elif act == "divorce":
            await do_divorce(m)


# ───────────────────────────── ✨ پیام‌های خوش‌آمد (گروه) ─────────────────────────────

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
        await say(m, "پاهات هنوز داغه! چند ثانیه نفس بکش و دوباره برو. 🥵", "🥵", "یه کم استراحت", "orange")
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
        gold = gold_bonus(doc, random.randint(5, 25) + val)
        cursed = idx == len(RARITIES) - 1
        doc, leveled = await grant(uid, gold=gold, xp=random.randint(8, 18), item=item,
                                   survival=-5 if cursed else 0)
        lines.append(f"✨ <b>گنج پیدا کردی!</b>\n🎁 {esc(item)}\n🪙 +{gold} طلا")
        if cursed:
            lines.append("🩸 آیتم نفرین‌شده بود! −۵٪ بقا. ایزدبانو خندید: «اپس. لایقش بودی.»")
    elif kind == "monster":
        mname, strength = random.choice(B["monsters"])
        mine = doc.get("level", 1) * 4 + doc.get("survival_rate", 50) / 2 + random.randint(0, 25) + (8 if cls_is(doc, "warrior") else 0)
        theirs = strength + random.randint(0, 25)
        lines.append(f"👹 <b>{esc(mname)}</b> سر راهت سبز شد! (قدرت {strength})")
        if mine >= theirs:
            g = gold_bonus(doc, random.randint(8, 30))
            doc, leveled = await grant(uid, gold=g, xp=random.randint(18, 35))
            lines.append(f"⚔️ <b>پیروز شدی!</b> هیولا فرار کرد و یه کیسه‌ی کوچیک جا گذاشت.\n🪙 +{g} طلا")
            if random.random() < 0.3:
                item, _, _ = roll_item(B["items"])
                doc, _ = await grant(uid, item=item)
                lines.append(f"🎁 غنیمت: {esc(item)}")
        else:
            loss = random.randint(8, 20)
            doc, _ = await grant(uid, xp=4, survival=-loss)
            lines.append(f"🩸 <b>شکست خوردی!</b> {esc(mname)} ازت قوی‌تر بود. −{loss}٪ بقا. دفعه‌ی بعد بهتر میشه! 💪")
            if doc.get("survival_rate", 100) <= 2:
                died = True
    elif kind == "heal":
        h = heal_bonus(doc, random.randint(8, 18))
        doc, leveled = await grant(uid, xp=6, survival=h)
        lines.append(f"💚 یه چشمه‌ی شفابخش پیدا کردی و ازش خوردی. +{h}٪ بقا.")
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
        lines.append(f"📜 <b>ماموریت پیرمرد انجام شد!</b> 🪙 +{reward} طلا و ۳۰ XP. «آفرین! کارت عالی بود.»")

    # 👑 درآمد قلمرو + امتیاز هفتگی گیلد
    if not died and doc.get("guild"):
        inc = await terr_income(doc)
        if inc:
            await grant(uid, gold=inc)
            lines.append(f"👑 درآمد قلمروهای گیلد: 🪙 +{inc}")
        await add_guild_pts(doc.get("guild"), 1)

    if leveled:
        lines.append(f"🆙 <b>تبریک! سطحت بالا رفت!</b> حالا سطح {doc.get('level', 1)} هستی. 🎉")

    if died:
        rdoc, new = await reincarnate(uid, chat_id=gid(m))
        scene = render_scene(f"<b>{esc(m.from_user.full_name)}</b>")
        text = (
            panel(B["color"], B["icon"], f"{B['name']} — مرگ ناگهانی!", lines)
            + f"\n\n{scene}\n\n{render_rebirth(rdoc, new)}"
        )
        mk = after_death_kb(uid)
    else:
        doc = await store.get(uid)
        lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(doc)]
        doc, new = await refresh_titles(doc)
        text = panel(B["color"], B["icon"], B["name"], lines, gline(doc) if random.random() < 0.3 else None)
        if new:
            text += "\n🏷 <b>لقب جدید:</b> " + "، ".join(f"«{esc(t)}»" for t in new)
        mk = after_explore_kb(uid, key)
    await m.reply(text, reply_markup=mk)
    await quest_progress(m, "trip")


# ───────── 🧙 NPC ─────────

async def do_npc(m: Message, npc_key: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    npc = NPCS[npc_key]
    if (doc.get("location") or "city") != "city":
        await m.reply(
            panel(npc["color"], npc["icon"], npc["name"], [
                "اینجا کسی نیست جز باد و اسلایم. 🌬",
                f"برای حرف زدن با <b>{npc['name']}</b> اول به «شهر» برو. 👇",
            ]),
            reply_markup=kb([btn("🏰 ورود به شهر", f"x:city:{uid}", "green")]),
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
                f"📜 <b>ماموریت جدید!</b>\n«جوون، برو <b>{B['name']}</b> {B['icon']} یه گشتی بزن و سالم برگرد. "
                f"اگه موفق شدی، {reward} طلا جایزه داری! 🎁»\n"
                f"👉 برای رفتن بنویس: «سفر به {B['kw'].strip('()').split('|')[0]}»"
            )
    elif npc_key == "shop":
        item, price = random.choice(SHOP_ITEMS)
        await store.users.update_one({"user_id": uid}, {"$set": {"pending_trade": {"item": item, "price": price}}})
        lines.append(
            f"🛒 «فقط امروز! <b>{esc(item)}</b> — فقط <b>{price} طلا</b>. فرصت خوبیه، بدو!»"
        )
        foot = f"💡 برای خرید بنویس «<b>قبول معامله</b>» (طلای تو: {doc.get('gold', 0)} 🪙)"
    elif npc_key == "cafe":
        if await spend(uid, 10):
            h = heal_bonus(doc, random.randint(6, 14))
            d2, _ = await grant(uid, xp=5, survival=h)
            lines.append(f"☕ یه قهوه‌ی «ضدمرگ» گرفتی (−۱۰ طلا). +{h}٪ بقا.\n«نوش جان! زندگی یه کم تلخه، ولی ارزشش رو داره.»")
        else:
            lines.append("☕ قهوه ۱۰ طلا میشه و تو نداری. کافه‌چی یه لیوان آب بهت داد: «برو ماجراجویی کن، بعد برگرد!»")
    elif npc_key == "guard":
        gcount = await store.guilds.count_documents({})
        lines.append(
            f"💂 «الان {gcount} گیلد تو این قاره فعالن. اگه گیلد نداری، یکی بساز یا به یکی بپیوند؛ تنهایی سخته!»"
        )
    elif npc_key == "witch":
        roll = random.random()
        if roll < 0.5:
            b = heal_bonus(doc, random.randint(5, 12))
            await grant(uid, survival=b, xp=8)
            lines.append(f"🧪 جادوگر یه معجون بهت داد: «بخور، خوب میشی!» +{b}٪ بقا. (طعمش عجیبه، ولی اثر می‌کنه)")
        else:
            c = random.randint(4, 10)
            await grant(uid, survival=-c, xp=8)
            lines.append(f"🕯 جادوگر یه طلسم کوچیک روت امتحان کرد! −{c}٪ بقا. (طلسمِ «سه روز چای سرد»)")
    d3 = await store.get(uid)
    lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(d3)]
    await m.reply(panel(npc["color"], npc["icon"], npc["name"], lines, foot),
                  reply_markup=kb([btn("🧙 NPCهای دیگه", f"m:npc:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")]))
    await quest_progress(m, "npc")


async def do_trade(m: Message) -> bool:
    uid = m.from_user.id
    doc = await store.get(uid)
    pt = doc.get("pending_trade")
    if not pt:
        return False
    if not await spend(uid, pt["price"]):
        await say(m, "«طلات کمه! برو ماجراجویی کن و با پول برگرد.» 🪙", "🧔", "مغازه‌دارِ بی‌اعتماد", "yellow")
        return True
    item = f"🟪 {pt['item']} ‹معامله‌ی مشکوک›"
    await store.users.update_one(
        {"user_id": uid},
        {"$set": {"pending_trade": None}, "$push": {"inventory": {"$each": [item], "$slice": -15}}},
    )
    await m.reply(panel("yellow", "🛒", "معامله انجام شد",
                        [f"🎁 {esc(item)}", f"🪙 −{pt['price']} طلا", "🧔 «معامله‌ی خوبی بود! دوباره بیا.»"]))
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
        await say(m, f"تو الان عضو گیلد «{esc(doc['guild'])}» هستی. اگه می‌خوای عوض کنی، اول بنویس «ترک گیلد». 🛡", "🛡", "گیلد", "blue")
        return
    if not (2 <= len(name) <= 24):
        await say(m, "اسم گیلد باید بین ۲ تا ۲۴ حرف باشه.", "📛", "گیلد", "blue")
        return
    if not await spend(uid, GUILD_COST):
        await say(m, f"ساخت گیلد {GUILD_COST} طلا خرج داره و طلات کمه. با ماجراجویی طلا جمع کن! 🪙", "🪙", "گیلد", "yellow",
                  kb([btn("🌍 ماجراجویی", f"m:go:{uid}", "green")]))
        return
    try:
        await store.guilds.insert_one({
            "name": name, "name_lower": name.lower(), "owner_id": uid, "members": [uid],
            "home_chat": gid(m), "wins": 0, "losses": 0, "created_at": utcnow(), "last_war_at": None,
        })
    except Exception:
        await store.users.update_one({"user_id": uid}, {"$inc": {"gold": GUILD_COST}})
        await say(m, "این اسم قبلاً ثبت شده. یه اسم دیگه امتحان کن. 😊", "🛡", "گیلد", "blue")
        return
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": name}})
    terr = "این گروه به‌عنوان قلمرو گیلد ثبت شد! 🚩" if is_group(m) else "برای ثبت قلمرو، بهتره تو یه گروه این کار رو بکنی. 🚩"
    await m.reply(panel("purple", "🛡", "گیلد جدید تأسیس شد", [
        f"📛 نام: <b>{esc(name)}</b>", f"👑 رهبر: {esc(m.from_user.full_name)}",
        f"🪙 هزینه: {GUILD_COST} طلا", terr,
    ], f"دوستات می‌تونن بنویسن «<b>پیوستن به گیلد {esc(name)}</b>»"))


async def do_guild_join(m: Message, name: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if doc.get("guild"):
        await say(m, f"تو الان عضو «{esc(doc['guild'])}» هستی. اگه می‌خوای عوض کنی، اول «ترک گیلد» بنویس. 🛡", "🛡", "گیلد", "blue")
        return
    g = await store.guilds.find_one({"name_lower": name.lower()})
    if not g:
        await say(m, "گیلدی با این اسم پیدا نشد. اسمش رو دقیق بنویس. 🔍", "🛡", "گیلد", "blue")
        return
    if len(g["members"]) >= GUILD_MAX_MEMBERS:
        await say(m, "این گیلد پره و جا نداره. یه گیلد دیگه رو امتحان کن. 🚪", "🛡", "گیلد", "blue")
        return
    await store.guilds.update_one({"_id": g["_id"]}, {"$addToSet": {"members": uid}})
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": g["name"]}})
    await m.reply(panel("blue", "🛡", "عضو جدید!", [
        f"{esc(m.from_user.full_name)} به گیلد <b>{esc(g['name'])}</b> پیوست.",
        f"👥 اعضا: {len(g['members']) + 1}",
    ], "💅 <i>«یه سرباز دیگه برای قربانی شدن.»</i>"))


async def do_guild_leave(m: Message):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await say(m, "تو گیلدی نداری که ازش بری. 🛡", "🛡", "گیلد", "blue")
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
    await say(m, "از گیلد خارج شدی. هر وقت خواستی می‌تونی دوباره به یه گیلد بپیوندی. 🚪", "🚪", "ترک گیلد", "blue")


async def do_guild_me(m: Message):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await say(m, "هنوز گیلد نداری. بنویس «<b>ساخت گیلد [نام]</b>» یا «<b>پیوستن به گیلد [نام]</b>». 🛡", "🛡", "گیلد", "blue")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"guild": None}})
        await say(m, "گیلدت منحل شده بود. می‌تونی یه گیلد جدید بسازی. 🪦", "🛡", "گیلد", "blue")
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
        await say(m, "برای جنگ اول باید گیلد داشته باشی. یه گیلد بساز یا به یکی بپیوند. 🛡", "⚔️", "جنگ گیلدها", "red")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        return
    last = g.get("last_war_at")
    if last and (utcnow() - last).total_seconds() < GUILD_WAR_COOLDOWN:
        left = int(GUILD_WAR_COOLDOWN - (utcnow() - last).total_seconds()) // 60 + 1
        await say(m, f"گیلدت هنوز خسته‌ست. حدود {left} دقیقه‌ی دیگه دوباره بجنگین. 🩹", "⚔️", "جنگ گیلدها", "red")
        return
    others = await store.guilds.find({"_id": {"$ne": g["_id"]}}).to_list(50)
    if not others:
        await say(m, "هنوز گیلد دیگه‌ای نیست که باهاش بجنگی. دوستات رو دعوت کن! 😊", "⚔️", "جنگ گیلدها", "red")
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
    await add_guild_pts(wg["name"], 20)
    await add_guild_pts(lg["name"], 5)
    await m.reply(panel("red", "⚔️", "جنگ گیلدها!", [
        f"🟦 <b>{esc(g['name'])}</b>  ⚡{int(sa)}",
        "      ⚔️ VS ⚔️",
        f"🟥 <b>{esc(foe['name'])}</b>  ⚡{int(sb)}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"🏆 برنده: <b>{esc(wg['name'])}</b> — هر عضو 🪙+۳۰ و ۱۵ XP",
        f"🪦 بازنده: {esc(lg['name'])} (دفعه‌ی بعد بهتر میشه! 💪)",
    ], "👑 +۲۰ امتیاز هفتگی برای برنده، +۵ برای بازنده"),
        reply_markup=kb([btn("🗺 قلمروها", f"m:terr:{m.from_user.id}", "blue"), btn("🌙 منو", f"m:main:{m.from_user.id}", "green")]))
    await quest_progress(m, "war")


async def do_guild_invite(m: Message, uname: Optional[str]):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await say(m, "اول باید خودت گیلد داشته باشی، بعد می‌تونی دعوت کنی. 🛡", "📯", "دعوت", "blue")
        return
    who = f"@{uname}" if uname else ""
    if not uname and m.reply_to_message and m.reply_to_message.from_user:
        who = esc(m.reply_to_message.from_user.full_name)
    if not who:
        await say(m, "کی رو دعوت کنم؟ روی پیامش ریپلای بزن یا @یوزرنیمش رو بنویس.", "📯", "دعوت", "blue")
        return
    await m.reply(panel("blue", "📯", "دعوت‌نامه‌ی گیلد", [
        f"{who} — {esc(m.from_user.full_name)} تو رو به گیلد <b>{esc(doc['guild'])}</b> دعوت کرد!",
        f"برای قبول بنویس: «<b>پیوستن به گیلد {esc(doc['guild'])}</b>»",
    ]))


# ───────── ⚔️ Duels ─────────

async def do_duel_request(m: Message, uname: Optional[str]) -> bool:
    if not is_group(m):
        await say(m, "دوئل فقط تو گروه کار می‌کنه؛ چون تماشاگر لازمه. ⚔️", "⚔️", "دوئل", "orange")
        return True
    target = None
    if uname:
        if uname.lower() == BOT_USERNAME.lower():
            await say(m, "با من دوئل؟ من ایزدبانوام، نه کیسه‌ی بوکس. جرئتت رو دوست دارم؛ ولی یه بار دیگه بگی، همین‌جا تموم‌ت می‌کنم. 💅", "💅", GODDESS_NAME, "purple")
            return True
        target = await store.users.find_one({"username_lower": uname.lower()})
        if not target:
            await say(m, "این بازیکن رو هنوز نمی‌شناسم. بگو یه پیام تو گروه بنویسه تا ثبتش کنم. 📖", "📖", "ناشناس", "purple")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user:
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await say(m, "ربات‌ها دوئل نمی‌کنن. با یه آدم واقعی دوئل کن! 🤖", "🤖", "دوئل", "orange")
            return True
        await store.touch(tu)
        target = await store.get(tu.id)
    else:
        return False
    a = m.from_user
    if target["user_id"] == a.id:
        await say(m, "نمی‌تونی با خودت دوئل کنی. یه حریف پیدا کن! 🙃", "⚔️", "دوئل", "orange")
        return True
    if target.get("opted_out"):
        await say(m, f"{display(target)} حالت «محافظت» رو فعال کرده و دوئل نمی‌کنه. 🛡", "🛡", "دوئل", "orange")
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
        "⏳ ۳ دقیقه وقت داره که قبول کنه.",
    ], "برای قبول بنویس: «<b>قبول دوئل</b>» یا دکمه‌ی پایین رو بزن 🥊"),
        reply_markup=kb([btn("🥊 قبول دوئل", f"duelacc:{target['user_id']}", "green")]))
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
        bonus = (6 if cls_is(d, "warrior") else 0) + (8 if d.get("spouse") else 0)
        return d.get("level", 1) * 5 + d.get("survival_rate", 50) * 0.6 + len(d.get("inventory") or []) * 2 + random.uniform(0, 50) + bonus

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
    await m.reply(text, reply_markup=kb([btn("🌙 منو", f"m:main:{m.from_user.id}", "green")]))
    await add_guild_pts(wdoc.get("guild"), 5)
    await quest_progress(m, "duel", uid=duel["a"])
    await quest_progress(m, "duel", uid=duel["b"])
    await quest_progress(m, "duel_win", uid=win_doc["user_id"])
    return True


# ───────── 🎡 Wheel / Leaderboard ─────────

async def do_wheel(m: Message):
    uid = m.from_user.id
    doc = await store.get(uid)
    last = doc.get("last_wheel_at")
    if last and (utcnow() - last).total_seconds() < WHEEL_COOLDOWN:
        rem = int(WHEEL_COOLDOWN - (utcnow() - last).total_seconds())
        await say(m, f"گردونه هنوز آماده نیست! <b>{rem // 3600}</b> ساعت و <b>{(rem % 3600) // 60}</b> دقیقه‌ی دیگه بیا. 🎡", "🎡", "گردونه‌ی شانس", "orange")
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
    await m.reply(panel(color, "🎡", "گردونه‌ی شانس", lines, "فردا دوباره بیا. 🎡 (هر ۲۴ ساعت یه بار)"),
                  reply_markup=kb([btn("📜 ماموریت‌ها", f"m:quest:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")]))
    await quest_progress(m, "wheel")


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
        await say(m, "هنوز هیچ گروهی ثبت نشده. کمی فعالیت کنید تا لیست پر بشه. 📊", "📊", "لیدربرد", "yellow")
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
            await say(m, "منو بفرستی ایسکای؟ من خودِ خدای اون‌جام. یه بار دیگه امتحان کن، تا ابد اونجا می‌مونی. 💅")
            return True
        target_doc = await store.users.find_one({"username_lower": uname})
        if not target_doc:
            await say(m, "این بازیکن رو هنوز تو دفترم ندارم. بگو یه پیام تو گروه بنویسه تا ثبتش کنم، بعد حکم رو صادر می‌کنم. 📖", "📖", "ناشناس", "red")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user and REPLY_EXEC_RE.fullmatch(c):
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await say(m, "ربات‌ها هم‌صنف منن؛ دستشون به من نمی‌رسه و دست تو هم بهشون نمی‌رسه. 🤖")
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
            f"{display(target_doc)} حالت «محافظت» رو فعال کرده. حتی من هم قانون رو دور نمی‌زنم… "
            "فعلاً. تو هم لقب «جلاد بی‌دندون» رو از من هدیه بگیر. 😒"
        )
        return True
    last = target_doc.get("last_death_at")
    if last and (utcnow() - last).total_seconds() < FORCED_TARGET_COOLDOWN:
        await say(m, "این بازیکن تازه مرده. چند دقیقه صبر کن و دوباره امتحان کن. 🧊", "🧊", "یه لحظه صبر کن", "blue")
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
        await say(m, "این بازیکن «محافظت» فعال کرده. نفرینت بی‌اثر شد و به خودت برگشت. 🪞", "🪞", "نفرین برگشت", "red")
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
            f"🙏 دعای خیر {a} روی {display(doc, link=True)} نشست؛ نرخ بقا <b>+{d}٪</b>. ایزدبانو می‌دونه دعای گروهی یعنی نقشه داره.",
            f"✨ {a} برای {display(doc, link=True)} دعا کرد. ایزدبانو با بی‌میلی <b>+{d}٪</b> بقا داد.",
        ])
        color, icon, title = "green", "🙏", "دعای خیر"
    doc, new = await refresh_titles(doc)
    lines = [text, f"💀 نرخ بقا حالا: <b>{doc['survival_rate']}٪</b> {hp_bar(doc['survival_rate'])}"]
    out = panel(color, icon, title, lines)
    if new:
        out += "\n🏷 لقب جدید: " + "، ".join(f"«{esc(t)}»" for t in new)
    await m.reply(out)
    await quest_progress(m, "curse" if is_curse else "bless")
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
        "⏳ ۱۵ دقیقه وقت داری. اولین نفری که بنویسه «<b>میخرم</b>» برنده‌ست!",
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
                "🪙 شرایط این جنس «معرفی ۳ نفر» بود و تو هنوز ۳ معرفی نداری.\n"
                f"لینک اختصاصی‌ت: {link}\nهر کس با این لینک ربات رو استارت کنه، یه امتیاز می‌گیری."
            )
            return True
    elif offer["price_key"] == "gold":
        if not await spend(uid, int(offer.get("price") or 80)):
            await reopen()
            await say(m, f"{offer.get('price_label')} نداری! با ماجراجویی طلا جمع کن و دفعه‌ی بعد بیا. 🙂", "🕶", "بازار سیاه", "black")
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
        "دلال با لبخند گفت: «معامله‌ی خوبی بود! دفعه‌ی بعد هم بیا.»",
    ]))
    return True


# ───────────────────────────── 🎒 کوله‌پشتی ─────────────────────────────
async def send_inventory(m, doc: Optional[dict] = None):
    doc = doc or await store.get(m.from_user.id)
    inv = doc.get("inventory") or []
    lines = [f"{i}. {esc(x)}" for i, x in enumerate(inv, 1)] or ["کوله‌پشتیت خالیه. با ماجراجویی چیز جمع کن! 🎒"]
    await m.reply(panel("brown", "🎒", "کوله‌پشتی", lines, f"🪙 طلا: <b>{doc.get('gold', 0)}</b>"),
                  reply_markup=kb(back_kb(m.from_user.id)))


# ───────────────────────────── 📜 ماموریت‌های روزانه و هفتگی ─────────────────────────────
IR_OFFSET = timedelta(hours=3, minutes=30)


def ir_now() -> datetime:
    return utcnow() + IR_OFFSET


def day_key() -> str:
    return ir_now().strftime("%Y-%m-%d")


def week_key() -> str:
    y, w, _ = ir_now().isocalendar()
    return f"{y}-W{w:02d}"


def make_quest(item: tuple) -> dict:
    k, t, need, g, x = item
    return {"k": k, "t": t.replace("{n}", str(need)), "need": need, "have": 0, "gold": g, "xp": x, "done": False}


async def ensure_quests(uid: int, doc: Optional[dict] = None) -> dict:
    doc = doc or await store.get(uid)
    q = dict(doc.get("quests") or {})
    changed = False
    if q.get("day") != day_key():
        pool = DAILY_POOL[:]
        random.shuffle(pool)
        picks, kinds = [], set()
        for it in pool:
            if it[0] not in kinds:
                kinds.add(it[0])
                picks.append(it)
            if len(picks) == 3:
                break
        q["day"] = day_key()
        q["daily"] = [make_quest(p) for p in picks]
        changed = True
    if q.get("week") != week_key():
        q["week"] = week_key()
        q["weekly"] = [make_quest(random.choice(WEEKLY_POOL))]
        changed = True
    if changed:
        await store.users.update_one({"user_id": uid}, {"$set": {"quests": q}})
    return q


async def quest_progress(m, kind: str, n: int = 1, uid: Optional[int] = None):
    """پیشرفت ماموریت‌ها رو ثبت می‌کنه؛ اگه ماموریتی کامل شد، جایزه + پیام."""
    uid = uid or m.from_user.id
    doc = await store.get(uid)
    if not doc or not doc.get("registered"):
        return
    q = await ensure_quests(uid, doc)
    lines, gold, xp = [], 0, 0
    for bucket in ("daily", "weekly"):
        for it in q.get(bucket, []):
            if it["k"] == kind and not it["done"]:
                it["have"] = min(it["need"], it["have"] + n)
                if it["have"] >= it["need"]:
                    it["done"] = True
                    gold += it["gold"]
                    xp += it["xp"]
                    tag = "هفتگی" if bucket == "weekly" else "روزانه"
                    lines.append(f"✅ ماموریت {tag}: {esc(it['t'])}\n      🪙 +{it['gold']}  ⭐ +{it['xp']}")
    await store.users.update_one({"user_id": uid}, {"$set": {"quests": q}})
    if lines:
        await grant(uid, gold=gold, xp=xp)
        name = esc(doc.get("first_name") or "قهرمان")
        await m.reply(panel("green", "🎯", f"ماموریت انجام شد — {name}", lines,
                            "💅 <i>«ماموریتتو انجام دادی؟ …باشه، قبول. دفعه‌ی بعد سریع‌تر؛ من وقت ندارم.»</i>"),
                      reply_markup=kb([btn("📜 ماموریت‌های من", f"m:quest:{uid}", "blue")]))


async def do_quests(m):
    uid = m.from_user.id
    q = await ensure_quests(uid)

    def row(it: dict) -> str:
        mark = "✅" if it["done"] else "▫️"
        return f"{mark} {esc(it['t'])}\n      ({it['have']}/{it['need']}) 🪙{it['gold']} ⭐{it['xp']}"

    lines = ["👇 ماموریت‌ها رو انجام بده و طلا و XP بگیر!", "📅 <b>روزانه</b> (ریست ساعت ۰۰ به وقت ایران)"] + [row(i) for i in q.get("daily", [])]
    lines += ["┈┈┈┈┈┈┈┈┈┈", "🗓 <b>هفتگی</b>"] + [row(i) for i in q.get("weekly", [])]
    alld = all(i["done"] for i in q.get("daily", []))
    foot = "🎉 همه‌ی ماموریت‌های امروز رو انجام دادی! آفرین، فردا دوباره بیا. 🙂" if alld else "💅 <i>«ماموریت‌هات رو تموم کن. هر ماموریتِ نیمه‌کاره توهین به منه.»</i>"
    await m.reply(panel("blue", "📜", "دفتر ماموریت‌ها", lines, foot),
                  reply_markup=kb([btn("🌍 ماجراجویی", f"m:go:{uid}", "green"), btn("🌙 منو", f"m:main:{uid}", "blue")]))


# ───────────────────────────── 👑 قلمروها و پادشاه هفته ─────────────────────────────
TERR_ALIAS = {
    "capital": r"(پایتخت|شهر|درخشان)",
    "castle": r"(قلعه|تاریک)",
    "forest": r"(جنگل)",
    "port": r"(بندر|طوفان|دریا)",
    "ruins": r"(خرابه|ویرانه|معبد)",
}


def find_terr(text: str) -> Optional[str]:
    for k, rx in TERR_ALIAS.items():
        if re.search(rx, text):
            return k
    return None


async def ensure_week() -> dict:
    """اگه هفته عوض شده باشه، پادشاهِ هفته‌ی قبل رو تعیین و امتیازها رو صفر می‌کنه."""
    wk = week_key()
    meta = await store.meta.find_one({"_id": "week"})
    if meta and meta.get("key") == wk:
        return meta
    king = meta.get("king") if meta else None
    top = await store.guilds.find({"week_pts": {"$gt": 0}}).sort("week_pts", -1).limit(1).to_list(1)
    if top:
        g = top[0]
        leader = await store.get(g["owner_id"])
        king = {
            "guild": g["name"], "leader_id": g["owner_id"], "pts": g.get("week_pts", 0),
            "leader_name": (leader or {}).get("first_name") or "ناشناس",
            "week": (meta or {}).get("key") or wk,
        }
        await store.users.update_one(
            {"user_id": g["owner_id"]},
            {"$addToSet": {"titles": "👑 پادشاهِ هفته‌ی ایسکا"}, "$inc": {"gold": 200}},
        )
    await store.guilds.update_many({}, {"$set": {"week_pts": 0}})
    new = {"key": wk, "king": king}
    await store.meta.update_one({"_id": "week"}, {"$set": new}, upsert=True)
    return new


async def add_guild_pts(guild_name: Optional[str], pts: int):
    if not guild_name or pts <= 0:
        return
    await ensure_week()
    await store.guilds.update_one({"name": guild_name}, {"$inc": {"week_pts": pts}})


async def do_terr(m):
    uid = m.from_user.id
    meta = await ensure_week()
    owners = {t["key"]: t.get("owner") async for t in store.territories.find({})}
    lines = []
    king = meta.get("king")
    if king:
        lines.append(f"👑 <b>پادشاه هفته‌ی قبل:</b> {esc(king['leader_name'])} — گیلد «{esc(king['guild'])}» ({king['pts']} امتیاز)")
    else:
        lines.append("👑 هنوز پادشاهی نداریم؛ تاج روی میز خاک می‌خوره.")
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    for k, (name, icon, power) in TERRITORIES.items():
        own = owners.get(k)
        lines.append(f"{icon} <b>{name}</b> — " + (f"🛡 {esc(own)}" if own else f"🏴 آزاد (نگهبان ⚡{power})"))
    top = await store.guilds.find({"week_pts": {"$gt": 0}}).sort("week_pts", -1).limit(5).to_list(5)
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    if top:
        lines.append("🏁 <b>رده‌بندی این هفته:</b>")
        lines += [f"{i}. {esc(g['name'])} — {g.get('week_pts', 0)} امتیاز" for i, g in enumerate(top, 1)]
    else:
        lines.append("🏁 هنوز هیچ گیلدی امتیازی نگرفته. وقتشه!")
    rows = []
    ks = list(TERRITORIES.items())
    for i in range(0, len(ks), 2):
        rows.append([btn(f"⚔️ {v[1]} {v[0]}", f"sg:{k}:{uid}", "red") for k, v in ks[i:i + 2]])
    await m.reply(panel("yellow", "🗺", "نقشه‌ی جهان و تاج پادشاهی", lines,
                        "امتیاز هفتگی از ماجراجویی، دوئل، جنگ و محاصره میاد. هر قلمرو برای اعضای گیلدِ مالک 🪙+" + str(TERR_INCOME) + " به‌ازای هر سفر."),
                  reply_markup=kb(*rows, back_kb(uid)))


async def do_siege(m, key: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await say(m, "برای محاصره باید عضو یه گیلد باشی. یه گیلد بساز یا به یکی بپیوند. 🛡", "🛡", "محاصره", "red")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        return
    last = g.get("last_siege_at")
    if last and (utcnow() - last).total_seconds() < SIEGE_COOLDOWN:
        left = int(SIEGE_COOLDOWN - (utcnow() - last).total_seconds()) // 60 + 1
        await say(m, f"گیلدت هنوز خسته‌ست. حدود {left} دقیقه‌ی دیگه می‌تونین دوباره حمله کنین. 🩹", "🩹", "محاصره", "red")
        return
    name, icon, garrison = TERRITORIES[key]
    t = await store.territories.find_one({"key": key})
    holder = await store.guilds.find_one({"name": t["owner"]}) if t and t.get("owner") else None
    if holder and holder["_id"] == g["_id"]:
        await say(m, f"{icon} «{name}» همین الان مال گیلد خودته! یه قلمرو دیگه رو برای حمله انتخاب کن. 👑", "👑", "محاصره", "yellow")
        return
    pa = await guild_power(g)
    pd = int(await guild_power(holder) * 1.1) if holder else garrison
    sa, sd = pa * random.uniform(0.75, 1.25), pd * random.uniform(0.75, 1.25)
    win = sa >= sd
    await store.guilds.update_one({"_id": g["_id"]}, {"$set": {"last_siege_at": utcnow()}})
    defender = esc(holder["name"]) if holder else f"نگهبانانِ {name}"
    lines = [
        f"🟦 <b>{esc(g['name'])}</b>  ⚡{int(sa)}",
        "      ⚔️ محاصره ⚔️",
        f"🟥 <b>{defender}</b>  ⚡{int(sd)}",
        "┈┈┈┈┈┈┈┈┈┈",
    ]
    if win:
        await store.territories.update_one({"key": key}, {"$set": {"owner": g["name"], "since": utcnow()}}, upsert=True)
        await store.users.update_many({"user_id": {"$in": g["members"]}}, {"$inc": {"gold": 20, "xp": 10}})
        await add_guild_pts(g["name"], 25)
        lines.append(f"🏆 <b>{icon} {name} فتح شد!</b> هر عضو 🪙+۲۰ و ۱۰ XP. +۲۵ امتیاز هفتگی.")
        color, foot = "green", "💅 <i>«پرچم جدید، ارباب جدید. ولی آخرش همه‌شون زیر پای منن.»</i>"
    else:
        await add_guild_pts(g["name"], 5)
        lines.append("🪦 محاصره شکست خورد. ناامید نشین! (+۵ امتیاز تشویقی) 💪")
        color, foot = "red", "💅 <i>«شکست خوردین. تو دفتر من، بازنده‌ها حتی اسم هم ندارن.»</i>"
    await m.reply(panel(color, "🏰", f"محاصره‌ی {name}", lines, foot),
                  reply_markup=kb([btn("🗺 نقشه", f"m:terr:{uid}", "blue")]))
    await quest_progress(m, "war")


async def terr_income(doc: dict) -> int:
    if not doc.get("guild"):
        return 0
    n = await store.territories.count_documents({"owner": doc["guild"]})
    return n * TERR_INCOME


# ───────────────────────────── 🎁 صندوق گنج و بمب ساعتی ─────────────────────────────
async def spawn_drop(bot: Bot, chat_id: int):
    kind = "chest" if random.random() < 0.65 else "bomb"
    _last_loot[chat_id] = time.time()
    await store.drops.update_many({"chat_id": chat_id, "status": "open"}, {"$set": {"status": "expired"}})
    ttl = LOOT_TTL if kind == "chest" else BOMB_FUSE
    res = await store.drops.insert_one({
        "chat_id": chat_id, "kind": kind, "status": "open",
        "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=ttl),
    })
    if kind == "chest":
        text = panel("yellow", "🎁", "صندوقِ گنجِ عتیقه!", [
            "یه صندوق قدیمی از میون مه‌ی دروازه‌ی آخر افتاد وسط گروه… ✨",
            "اولین نفری که «<b>باز کردن</b>» بنویسه (یا دکمه رو بزنه) صاحبش میشه.",
            "💅 <i>«شاید گنج باشه، شاید دندون‌دار. ریسکش با خودته.»</i>",
        ], f"⏳ {LOOT_TTL // 60} دقیقه وقت داری")
        mk = kb([btn("🟩 باز کردن صندوق", "loot:open:0", "green")])
    else:
        text = panel("red", "💣", "بمب ساعتیِ جادویی!", [
            "یه بمبِ ساعتیِ کوچولو افتاد وسط گروه و داره تیک‌تاک می‌کنه… ⏱",
            "فوری «<b>خنثی کردن</b>» بنویس (یا دکمه رو بزن) تا قبل از انفجار نجاتش بدی!",
            f"💥 {BOMB_FUSE} ثانیه تا انفجار!",
        ])
        mk = kb([btn("✂️ خنثی کردن!", "loot:defuse:0", "red")])
    await bot.send_message(chat_id, text, reply_markup=mk)
    spawn(drop_timer(bot, chat_id, res.inserted_id, ttl, kind))


async def drop_timer(bot: Bot, chat_id: int, did, ttl: int, kind: str):
    try:
        await asyncio.sleep(ttl)
        d = await store.drops.find_one_and_update({"_id": did, "status": "open"}, {"$set": {"status": "expired"}})
        if not d:
            return
        if kind == "chest":
            await bot.send_message(chat_id, panel("black", "🔒", "صندوق قفل شد", [
                "هیچ‌کس جرأت نکرد… و صندوق با یه «پوف» تو مه ناپدید شد.",
            ], "💅 <i>«ترسوها. بدون ریسک، هیچ‌چیز گیرتون نمیاد؛ حتی احترام من.»</i>"))
            return
        victims = list({u: n for u, n in _recent_chatters[chat_id]}.items())
        random.shuffle(victims)
        victims = victims[:2]
        lines = ["⏱ تیک… تیک… <b>بووووم!</b> 💥 هیچ‌کس خنثی‌ش نکرد."]
        for uid, name in victims:
            loss = random.randint(10, 22)
            await adjust_survival(uid, -loss)
            await store.users.update_one({"user_id": uid, "gold": {"$gte": 20}}, {"$inc": {"gold": -20}})
            lines.append(f"🩸 <a href=\"tg://user?id={uid}\">{esc(name)}</a> تو محدوده بود: −{loss}٪ بقا و −۲۰ طلا")
        if not victims:
            lines.append("خوشبختانه کسی نزدیکش نبود… فقط یه گربه، که فرار کرد. 🐈")
        await bot.send_message(chat_id, panel("red", "💥", "انفجار!", lines,
                                              "💅 <i>«گروهی که از بمب نمی‌ترسه، حتماً از من می‌ترسه. بجاست.»</i>"))
    except Exception:
        log.exception("drop_timer failed")


async def claim_drop(m, want: str, notify_fail: bool = False) -> bool:
    kind = "chest" if want == "open" else "bomb"
    d = await store.drops.find_one_and_update(
        {"chat_id": m.chat.id, "kind": kind, "status": "open", "expires_at": {"$gt": utcnow()}},
        {"$set": {"status": "taken", "by": m.from_user.id}},
    )
    if not d:
        if notify_fail:
            await say(m, "یکی زودتر از تو رسید یا زمانش تموم شد. دفعه‌ی بعد سریع‌تر باش! ⚡", "⏳", "یه کم دیر شد", "black")
        return False
    uid = m.from_user.id
    doc = await store.get(uid)
    name = display(doc, link=True)
    if kind == "chest":
        if random.random() < 0.2:
            loss = random.randint(8, 15)
            await adjust_survival(uid, -loss)
            await store.users.update_one({"user_id": uid, "gold": {"$gte": 20}}, {"$inc": {"gold": -20}})
            await m.reply(panel("red", "👅", "میمیک!", [
                f"{name} در صندوق رو باز کرد… و صندوق اونو گاز گرفت! 🦷",
                f"🩸 −{loss}٪ بقا و −۲۰ طلا",
            ], "💅 <i>«صندوق‌ها گاز می‌گیرن؛ مثل من. حالا فهمیدی چرا نباید به همه‌چی اعتماد کنی؟»</i>"))
        else:
            gold = gold_bonus(doc, random.randint(40, 120))
            item, _, _ = roll_item(BLACK_MARKET_ITEMS)
            d2, lv = await grant(uid, gold=gold, xp=random.randint(15, 30), item=item)
            lines = [f"{name} صندوق رو باز کرد!", f"🪙 +{gold} طلا", f"🎁 {esc(item)}"]
            if lv:
                lines.append(f"🆙 لول‌آپ! سطح {d2.get('level', 1)}")
            await m.reply(panel("yellow", "🎁", "غنیمت!", lines, "💅 <i>«شانس آوردی. دفعه‌ی بعد شانس یادش میره سراغت بیاد.»</i>"))
    else:
        gold = gold_bonus(doc, random.randint(60, 140))
        await grant(uid, gold=gold, xp=30)
        await m.reply(panel("green", "✂️", "بمب خنثی شد!", [
            f"{name} سیم قرمز رو بریده… و سیم قرمز هم همون سیم درست بود! 😮‍💨",
            f"🪙 +{gold} طلا و ۳۰ XP — جایزه‌ی قهرمانی",
        ], "💅 <i>«…باشه. این بار شجاع بودی. دفعه‌ی بعد جا بزنی، خودم سیم‌هات رو می‌برم.»</i>"))
    await quest_progress(m, "chest")
    return True


# ───────────────────────────── 💍 ازدواج و پیوند ایسکایی ─────────────────────────────
async def do_marry(m, uname: Optional[str]) -> bool:
    if not is_group(m):
        await say(m, "پیوند باید جلوی شاهدها باشه؛ تو یه گروه بنویس. 💍", "💍", "پیوند", "red")
        return True
    target = None
    if uname:
        target = await store.users.find_one({"username_lower": uname.lower()})
        if not target:
            await say(m, "این بازیکن رو هنوز نمی‌شناسم. بگو یه پیام تو گروه بنویسه تا ثبتش کنم. 📖", "💍", "پیوند", "red")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user:
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await say(m, "با ربات نمی‌شه ازدواج کرد! یه آدم واقعی رو انتخاب کن. 🤖", "💍", "پیوند", "red")
            return True
        await store.touch(tu)
        target = await store.get(tu.id)
    else:
        await say(m, "با کی؟ ریپلای بزن و «ازدواج» بنویس، یا «ازدواج با @یوزرنیم».", "💍", "پیوند", "blue")
        return True
    me = await store.get(m.from_user.id)
    if target["user_id"] == m.from_user.id:
        await say(m, "نمی‌تونی با خودت ازدواج کنی! یه نفر دیگه رو انتخاب کن. 🪞", "💍", "پیوند", "red")
        return True
    if me.get("spouse"):
        await say(m, f"تو الان با {esc(me.get('spouse_name'))} پیوند داری. اگه می‌خوای عوض کنی، اول «طلاق» بنویس. 💔", "💍", "پیوند", "red")
        return True
    if target.get("spouse"):
        await say(m, f"{display(target)} قبلاً پیوند بسته. یه نفر دیگه رو انتخاب کن. 💍", "💍", "پیوند", "red")
        return True
    if not target.get("registered"):
        await say(m, f"{display(target)} هنوز ثبت‌نام نکرده؛ اول باید ثبت‌نام کنه. 📜", "💍", "پیوند", "red")
        return True
    if target.get("opted_out"):
        await say(m, f"{display(target)} حالت «محافظت» رو فعال کرده. 🛡", "💍", "پیوند", "red")
        return True
    await store.proposals.update_many({"from": m.from_user.id, "status": "pending"}, {"$set": {"status": "expired"}})
    res = await store.proposals.insert_one({
        "chat_id": m.chat.id, "from": m.from_user.id, "from_name": m.from_user.full_name,
        "to": target["user_id"], "status": "pending", "expires_at": utcnow() + timedelta(seconds=PROPOSAL_TTL),
    })
    pid = str(res.inserted_id)
    await m.reply(panel("red", "💍", "پیشنهاد پیوند ایسکایی", [
        f"💞 {esc(m.from_user.full_name)} از {display(target, link=True)} خواستگاری کرد!",
        "اگه قبول کنن: بقا و سرنوشتشون به هم گره می‌خوره؛",
        "• مرگِ یکی ← −۶٪ بقا و −۱۰ طلا برای اون یکی",
        "• تو دوئل‌ها +۸ قدرت (انرژی عشق… یا ترس از تنها موندن)",
        "⏳ ۵ دقیقه وقت دارن.",
    ], "💅 <i>«عشق؟ تو ایسکا؟ ساده‌لوح‌ها… ولی باشه. فقط وقتی یکیتون مرد گریه نکنید.»</i>"),
        reply_markup=kb([btn("💍 قبول می‌کنم", f"mar:yes:{pid}:{target['user_id']}", "green"),
                         btn("💔 رد", f"mar:no:{pid}:{target['user_id']}", "red")]))
    return True


async def marriage_answer(m, yes: bool, pid: Optional[str]) -> bool:
    q = {"to": m.from_user.id, "status": "pending", "expires_at": {"$gt": utcnow()}}
    if pid and pid != "0":
        try:
            q["_id"] = ObjectId(pid)
        except Exception:
            return False
    else:
        q["chat_id"] = m.chat.id
    prop = await store.proposals.find_one_and_update(q, {"$set": {"status": "yes" if yes else "no"}})
    if not prop:
        if pid:
            await say(m, "این خواستگاری تموم شده یا برای تو نیست.", "💍", "پیوند", "red")
        return False
    if not yes:
        await m.reply(panel("red", "💔", "رد شد", [f"{esc(m.from_user.full_name)} پیشنهاد {esc(prop['from_name'])} رو رد کرد."],
                            "💅 <i>«رد شدی؟ دردناکه؟ عالی؛ دیدنش خنده‌دار بود.»</i>"))
        return True
    a, b = await store.get(prop["from"]), await store.get(m.from_user.id)
    if not a or not b or a.get("spouse") or b.get("spouse"):
        await say(m, "یکی از شما وسط راه با یه نفر دیگه پیوند بسته؛ پس این خواستگاری باطل شد. 😕", "💍", "پیوند", "red")
        return True
    await store.users.update_one({"user_id": a["user_id"]}, {"$set": {"spouse": b["user_id"], "spouse_name": b.get("first_name")}, "$inc": {"gold": 50}})
    await store.users.update_one({"user_id": b["user_id"]}, {"$set": {"spouse": a["user_id"], "spouse_name": a.get("first_name")}, "$inc": {"gold": 50}})
    await m.reply(panel("green", "💞", "پیوند ایسکایی بسته شد!", [
        f"{display(a, link=True)} 💍 {display(b, link=True)}",
        "🎁 هدیه‌ی عروسی: 🪙+۵۰ برای هر کدوم",
        "🔗 از این لحظه بقاتون به هم گره خورده؛ مراقب هم باشید! 💞",
    ], "💅 <i>«تبریک. و تسلیت. هر دو رو همزمان می‌گم.»</i>"))
    return True


async def do_divorce(m):
    me = await store.get(m.from_user.id)
    if not me.get("spouse"):
        await say(m, "الان پیوندی نداری که ازش جدا بشی. 🥀", "💔", "طلاق", "red")
        return
    sp = me["spouse"]
    await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"spouse": None, "spouse_name": None}})
    await store.users.update_one({"user_id": sp}, {"$set": {"spouse": None, "spouse_name": None}})
    await m.reply(panel("red", "💔", "پیوند فسخ شد", [
        f"{esc(m.from_user.full_name)} و {esc(me.get('spouse_name'))} از هم جدا شدن.",
        "🔓 بقاشون دیگه به هم گره نیست.",
    ], "💅 <i>«یه پیوند دیگه که تو دفتر من خط خورد. خسته نشدی؟»</i>"))


async def do_marry_info(m, doc: dict):
    uid = m.from_user.id
    if doc.get("spouse"):
        lines = [f"💞 پیوند با <b>{esc(doc.get('spouse_name'))}</b> برقراره.",
                 "برای فسخ بنویس «<b>طلاق</b>»."]
        mk = kb([btn("💔 طلاق", f"m:divorce:{uid}", "red")], back_kb(uid))
    else:
        lines = ["الان مجردی. اگه می‌خوای پیوند ببندی، این‌طوری شروع کن 👇",
                 "برای پیوند: ریپلای + «<b>ازدواج</b>» یا «<b>ازدواج با @یوزرنیم</b>»"]
        mk = kb(back_kb(uid))
    await m.reply(panel("red", "💍", "پیوند ایسکایی", lines), reply_markup=mk)


# ───────────────────────────── 🐉 باس گروهی (سیاه‌چاله‌ی چندنفره) ─────────────────────────────
def boss_bar(hp: int, mx: int) -> str:
    n = max(0, min(10, round(10 * max(hp, 0) / mx))) if mx else 0
    return "🟥" * n + "⬛" * (10 - n)


async def active_raid(chat_id: int) -> Optional[dict]:
    return await store.raids.find_one({"chat_id": chat_id, "status": "active", "expires_at": {"$gt": utcnow()}})


def raid_kb() -> InlineKeyboardMarkup:
    return kb([btn("⚔️ حمله!", "raid:hit:0", "red"), btn("📊 وضعیت", "raid:st:0", "blue")])


async def spawn_raid(bot: Bot, chat_id: int, caller: Optional[str] = None) -> str:
    """'ok' | 'active' | 'cool'"""
    if await active_raid(chat_id):
        return "active"
    last = await store.raids.find({"chat_id": chat_id}).sort("created_at", -1).limit(1).to_list(1)
    if last and (utcnow() - last[0]["created_at"]).total_seconds() < RAID_COOLDOWN:
        return "cool"
    members = await store.users.count_documents({"chats": chat_id})
    mx = 300 + 90 * max(1, min(members, 12))
    name, icon = random.choice(BOSSES)
    res = await store.raids.insert_one({
        "chat_id": chat_id, "name": name, "icon": icon, "hp": mx, "max_hp": mx, "dmg": {}, "names": {},
        "status": "active", "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=RAID_TTL),
    })
    who = f"{esc(caller)} با یه ورد مشکوک" if caller else "از شکاف دروازه‌ی آخر"
    await bot.send_message(chat_id, panel("red", icon, f"باس ظاهر شد: {name}", [
        f"💥 {who} <b>{esc(name)}</b> رو احضار کرد!",
        f"❤️ HP: <b>{mx}</b> {boss_bar(mx, mx)}",
        "👥 همه با هم حمله کنید! بنویسید «<b>حمله به باس</b>» یا دکمه‌ی پایین رو بزنید.",
        f"⏳ {RAID_TTL // 60} دقیقه وقت دارید. غنیمت بین همه‌ی حمله‌کننده‌ها تقسیم میشه؛ هر کی بیشتر ضربه بزنه، جایزه‌ی ویژه می‌گیره! 🎁",
    ], "💅 <i>«من فقط تماشا می‌کنم. هر کی ترسید و فرار کرد، اسمش رو تو دفترم می‌نویسم.»</i>"), reply_markup=raid_kb())
    spawn(raid_timer(bot, chat_id, res.inserted_id, RAID_TTL))
    return "ok"


async def raid_timer(bot: Bot, chat_id: int, rid, ttl: int):
    try:
        await asyncio.sleep(ttl)
        r = await store.raids.find_one_and_update({"_id": rid, "status": "active"}, {"$set": {"status": "lost"}})
        if r:
            await bot.send_message(chat_id, panel("black", r["icon"], "باس فرار کرد!", [
                f"{esc(r['name'])} با بقایای HP خودش ({max(int(r['hp']), 0)}) توی مه ناپدید شد.",
                "این بار غنیمتی نیست. دفعه‌ی بعد با هماهنگی بیشتر امتحان کنید! 💪",
            ], "💅 <i>«گروه شما فقط یه استعداد داره: فرار. احمق‌ها.»</i>"))
    except Exception:
        log.exception("raid_timer failed")


async def do_boss_call(m, bot: Bot) -> bool:
    if not is_group(m):
        await say(m, "باس مخصوص گروه‌هاست؛ تنهایی نمی‌شه باهاش جنگید. ربات رو ببر تو یه گروه! 🐉", "🐉", "باس", "red")
        return True
    st = await spawn_raid(bot, m.chat.id, m.from_user.full_name)
    if st == "active":
        await say(m, "یه باس همین الان زنده‌ست! بنویس «حمله به باس» یا دکمه‌ی پایین رو بزن. 🐉", "🐉", "باس", "red", raid_kb())
    elif st == "cool":
        await say(m, "این گروه تازه یه باس رو شکست داده. هر ۲ ساعت فقط یه باس میاد؛ بعداً دوباره امتحان کنین. ⏳", "🐉", "باس", "red")
    return True


async def do_boss_status(m):
    if not is_group(m):
        await say(m, "باس تو گروه‌ها ظاهر میشه. ربات رو به گروهت اضافه کن! 🐉", "🐉", "باس", "red")
        return
    r = await active_raid(m.chat.id)
    if not r:
        await m.reply(panel("red", "🐉", "باس گروه", [
            "الان هیچ باسی زنده نیست.",
            "با «<b>احضار باس</b>» یکی رو صدا بزنید (هر ۲ ساعت). گاهی هم خودش بی‌دعوت میاد!",
        ]), reply_markup=kb([btn("🐉 احضار باس", f"raid:call:0", "red")]))
        return
    left = max(1, int((r["expires_at"] - utcnow()).total_seconds()) // 60)
    top = sorted(r["dmg"].items(), key=lambda x: -x[1])[:5]
    lines = [f"❤️ HP: <b>{max(int(r['hp']), 0)}/{r['max_hp']}</b> {boss_bar(int(r['hp']), r['max_hp'])}",
             f"⏳ ~{left} دقیقه مونده", "┈┈┈┈┈┈┈┈┈┈"]
    if top:
        lines.append("🏅 <b>بیشترین ضربه:</b>")
        lines += [f"{i}. {esc(r['names'].get(u, '؟'))} — {d} 💥" for i, (u, d) in enumerate(top, 1)]
    else:
        lines.append("هنوز کسی بهش ضربه نزده. شجاع‌ها کجان؟")
    await m.reply(panel("red", r["icon"], r["name"], lines), reply_markup=raid_kb())


async def do_raid_hit(m) -> bool:
    if not is_group(m):
        return False
    r = await active_raid(m.chat.id)
    if not r:
        return False
    uid = m.from_user.id
    now = time.time()
    if now - _last_raid_hit.get(uid, 0) < RAID_HIT_COOLDOWN:
        await say(m, f"دستت هنوز می‌لرزه! {RAID_HIT_COOLDOWN} ثانیه صبر کن. 💪", "🐉", "باس", "red")
        return True
    _last_raid_hit[uid] = now
    doc = await store.get(uid)
    dmg = doc.get("level", 1) * 5 + random.randint(15, 45) + (10 if cls_is(doc, "warrior") else 0)
    crit = random.random() < 0.12
    if crit:
        dmg *= 2
    name = m.from_user.full_name
    r2 = await store.raids.find_one_and_update(
        {"_id": r["_id"], "status": "active"},
        {"$inc": {"hp": -dmg, f"dmg.{uid}": dmg}, "$set": {f"names.{uid}": name}},
        return_document=ReturnDocument.AFTER,
    )
    if not r2:
        return False
    lines = [f"{random.choice(['⚔️', '🗡', '🔥', '⚡'])} {display(doc, link=True)} {random.choice(BOSS_HITS)}: <b>{dmg}</b>" + (" 💥 <b>ضربه‌ی بحرانی!</b>" if crit else "")]
    if random.random() < 0.35:
        loss = random.randint(4, 9)
        await adjust_survival(uid, -loss)
        lines.append(f"🩸 {esc(r['name'])} جواب داد: −{loss}٪ بقا")
    hp = max(int(r2["hp"]), 0)
    lines.append(f"❤️ {r2['icon']} {hp}/{r2['max_hp']} {boss_bar(hp, r2['max_hp'])}")
    won = False
    if r2["hp"] <= 0:
        won = bool(await store.raids.find_one_and_update({"_id": r["_id"], "status": "active"}, {"$set": {"status": "won"}}))
    await m.reply(panel("red", r2["icon"], r2["name"], lines), reply_markup=None if won else raid_kb())
    await quest_progress(m, "boss")
    if won:
        await raid_victory(m, r2)
    return True


async def raid_victory(m, r: dict):
    dmg = {int(u): int(d) for u, d in r["dmg"].items()}
    total = max(1, sum(dmg.values()))
    pool = 200 + 30 * len(dmg)
    top_uid = max(dmg, key=dmg.get)
    lines = [f"🏆 <b>{esc(r['name'])} شکست خورد!</b> 🎉", "┈┈┈┈┈┈┈┈┈┈"]
    for u, d in sorted(dmg.items(), key=lambda x: -x[1]):
        gold = int(pool * d / total) + 30
        item = None
        if u == top_uid:
            item = f"🟨 {random.choice(['پوستِ', 'دندانِ', 'تاجِ', 'قلبِ'])} {r['name']} ‹غنیمت باس›"
        await grant(u, gold=gold, xp=60, item=item)
        lines.append(f"{'🥇' if u == top_uid else '▫️'} {esc(r['names'].get(str(u), '؟'))} — 💥{d}  🪙+{gold}" + (" 🎁 غنیمتِ ویژه" if item else ""))
    await m.reply(panel("green", "🏆", "غنایمِ باس", lines,
                        "💅 <i>«…بد نبود. ولی غنیمت رو خرج کن، قبل از این‌که برگردم و پسش بگیرم.»</i>"))


# ───────────────────────────── 🛠 پنل ادمین ─────────────────────────────
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def admin_kb(uid: int) -> InlineKeyboardMarkup:
    return kb(
        [btn("📊 آمار ربات", f"adm:stats:{uid}", "blue"), btn("🩺 سلامت سرور", f"adm:health:{uid}", "green")],
        [btn("🧹 پاکسازی دیتابیس", f"adm:clean:{uid}", "red"), btn("📖 دستورها", f"adm:help:{uid}", "blue")],
    )


ADMIN_HELP = [
    "فرمان‌های ادمین (متنی):",
    "• <b>آمار ربات</b> ← آمار کلی",
    "• <b>سلامت سرور</b> ← وضعیت MongoDB و آپتایم",
    "• <b>پاکسازی</b> ← حذف رکوردهای منقضی",
    "• <b>بن [user_id]</b> / <b>آنبن [user_id]</b> (یا ریپلای + «بن»)",
    "• <b>کشتن [user_id]</b> ← ارسال اجباری به ایسکا",
    "• <b>سراسری [متن]</b> ← پیام همگانی به همه‌ی کاربران و گروه‌ها",
]


async def admin_stats() -> str:
    day_ago = utcnow() - timedelta(hours=24)
    u_count = await store.users.count_documents({})
    reg = await store.users.count_documents({"registered": True})
    banned = await store.users.count_documents({"banned": True})
    active = await store.users.count_documents({"last_seen": {"$gt": day_ago}})
    married = await store.users.count_documents({"spouse": {"$ne": None}})
    g_count = await store.guilds.count_documents({})
    gr_count = await store.groups.count_documents({})
    raids_won = await store.raids.count_documents({"status": "won"})
    d_res = await store.users.aggregate([{"$group": {"_id": None, "t": {"$sum": "$death_count"}}}]).to_list(1)
    deaths = d_res[0]["t"] if d_res else 0
    return panel("blue", "📊", "آمار حیاتی ربات", [
        f"👤 کل کاربران: <b>{u_count}</b>  (ثبت‌نام‌شده: {reg})",
        f"🟢 فعال در ۲۴ ساعت: <b>{active}</b>",
        f"🚫 بن‌شده: <b>{banned}</b>",
        f"☠️ مجموع مرگ‌ومیرها: <b>{deaths}</b>",
        f"🛡 گیلدها: <b>{g_count}</b>  |  👥 گروه‌ها: <b>{gr_count}</b>",
        f"💍 متأهل‌ها: <b>{married}</b>  |  🐉 باس‌های کشته‌شده: <b>{raids_won}</b>",
    ])


async def admin_health() -> str:
    t0 = time.time()
    try:
        await store.users.database.command("ping")
        ping = f"✅ MongoDB پاسخ داد ({int((time.time() - t0) * 1000)}ms)"
    except Exception as e:
        ping = f"❌ MongoDB: {esc(str(e)[:80])}"
    up = int(time.time() - BOT_STARTED)
    return panel("green", "🩺", "سلامت سیستم", [
        ping,
        f"⏱ آپتایم: {up // 3600} ساعت و {(up % 3600) // 60} دقیقه",
        f"🧵 تسک‌های پس‌زمینه: {len(_bg_tasks)}",
        f"🔑 ادمین‌ها: {len(ADMIN_IDS)}",
    ])


async def admin_clean() -> str:
    cut = utcnow() - timedelta(days=1)
    r1 = await store.offers.delete_many({"status": {"$ne": "open"}, "created_at": {"$lt": cut}})
    r2 = await store.duels.delete_many({"status": {"$ne": "pending"}, "created_at": {"$lt": cut}})
    r3 = await store.drops.delete_many({"status": {"$ne": "open"}, "created_at": {"$lt": cut}})
    r4 = await store.proposals.delete_many({"expires_at": {"$lt": cut}})
    r5 = await store.raids.delete_many({"status": {"$ne": "active"}, "created_at": {"$lt": utcnow() - timedelta(days=3)}})
    return panel("red", "🧹", "پاکسازی انجام شد", [
        f"🕶 پیشنهادهای بازار سیاه: {r1.deleted_count}",
        f"⚔️ دوئل‌ها: {r2.deleted_count}",
        f"🎁 صندوق/بمب: {r3.deleted_count}",
        f"💍 خواستگاری‌ها: {r4.deleted_count}",
        f"🐉 باس‌ها: {r5.deleted_count}",
    ])


async def broadcast(bot: Bot, admin_chat: int, text: str):
    ok = fail = 0
    targets = [u["user_id"] async for u in store.users.find({"banned": {"$ne": True}}, {"user_id": 1})]
    targets += [g["chat_id"] async for g in store.groups.find({}, {"chat_id": 1})]
    body = panel("purple", "📢", f"پیام همگانی ایزدبانو", [text])
    for cid in targets:
        try:
            await bot.send_message(cid, body)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.06)  # جلوگیری از Flood
    try:
        await bot.send_message(admin_chat, f"✅ پیام همگانی تموم شد.\nموفق: {ok}\nناموفق: {fail}")
    except Exception:
        pass


def admin_target(m, g: Optional[str]) -> Optional[int]:
    if g and g.strip().isdigit():
        return int(g.strip())
    if m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user.id
    return None


async def handle_admin_commands(m: Message, bot: Bot, c: str) -> bool:
    uid = m.from_user.id
    if not is_admin(uid):
        return False
    if ADMIN_PANEL_RE.fullmatch(c):
        await m.reply(panel("red", "🛠", "پنل مدیریت ادمین", ADMIN_HELP), reply_markup=admin_kb(uid))
        return True
    if ADMIN_STATS_RE.fullmatch(c):
        await m.reply(await admin_stats())
        return True
    if ADMIN_HEALTH_RE.fullmatch(c):
        await m.reply(await admin_health())
        return True
    if ADMIN_CLEAN_RE.fullmatch(c):
        await m.reply(await admin_clean())
        return True
    if bm := ADMIN_BAN_RE.fullmatch(c):
        tid = admin_target(m, bm.group(2))
        if not tid:
            return False
        await store.users.update_one({"user_id": tid}, {"$set": {"banned": True, "opted_out": True}})
        await m.reply(f"🚫 کاربر <code>{tid}</code> بن شد.")
        return True
    if ubm := ADMIN_UNBAN_RE.fullmatch(c):
        tid = admin_target(m, ubm.group(2))
        if not tid:
            return False
        await store.users.update_one({"user_id": tid}, {"$set": {"banned": False, "opted_out": False}})
        await m.reply(f"✅ کاربر <code>{tid}</code> آنبن شد.")
        return True
    if km := ADMIN_KILL_RE.fullmatch(c):
        tid = int(km.group(1))
        if not await store.get(tid):
            await m.reply("❌ کاربر پیدا نشد.")
            return True
        rdoc, new = await reincarnate(tid, forced=True)
        await m.reply(f"⚡ ادمین حکم مرگ کاربر <code>{tid}</code> رو صادر کرد!\n\n{render_rebirth(rdoc, new)}")
        return True
    raw = (m.text or "").strip()
    if bcm := ADMIN_BROADCAST_RE.match(raw):
        await m.reply("⏳ پیام همگانی تو صف ارسال قرار گرفت…")
        spawn(broadcast(bot, m.chat.id, bcm.group(1)))
        return True
    return False


# ───────────────────────────── ✨ ورود به گروه ─────────────────────────────
@router.message(F.new_chat_members)
async def on_join(m: Message, bot: Bot):
    try:
        if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            await store.groups.update_one({"chat_id": m.chat.id}, {"$set": {"title": m.chat.title}}, upsert=True)
        joined = m.new_chat_members or []
        if any(u.id == bot.id for u in joined):
            await m.answer(welcome_group_text(), reply_markup=kb(
                [btn("🩸 ثبت‌نام و امضای قرارداد", "reg:go:0", "green")],
                [btn("📖 راهنما", "m:help:0", "blue")],
            ))
            return
        humans = [u for u in joined if not u.is_bot]
        if humans:
            await m.answer(welcome_member_text(humans), reply_markup=kb(
                [btn("🩸 امضای قرارداد (ثبت‌نام)", "reg:go:0", "green")],
            ))
    except Exception:
        log.exception("join welcome failed")


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
                    await m.bot.send_message(ref, "🎉 یه نفر با لینک تو وارد بازی شد! +۱ امتیاز معرفی. 🙌")
                except Exception:
                    pass
                rdoc = await store.get(ref)
                if rdoc:
                    await refresh_titles(rdoc)
    doc = await store.get(m.from_user.id)
    if doc.get("banned"):
        return
    if is_group(m):
        if doc.get("registered"):
            await send_hub(m, doc)
        else:
            await reg_prompt(m)
        return
    if doc.get("registered"):
        await m.answer(
            f"💅 <i>«اوه… <b>{esc(m.from_user.first_name)}</b> برگشته. فکر می‌کردم بالاخره مُردی و از دستت راحت شدم.»</i>\n\n" + hub_text(doc),
            reply_markup=hub_kb(m.from_user.id),
        )
        return
    await m.answer(panel("purple", "🌌", f"دروازه‌ی آخرِ ایسکا باز شد", [
        f"مه‌ی بنفش کنار می‌ره و روی تخت استخوانی، <b>{GODDESS_NAME}</b> پدیدار میشه؛ چای به دست، خسته و بی‌حوصله…",
        f"💅 «من <b>{GODDESS_TITLE}</b> هستم. هر روحی که از این دروازه رد بشه، دیر یا زود برام زانو می‌زنه… یا التماس می‌کنه. معمولاً هر دو.»",
        "┈┈┈┈┈┈┈┈┈┈",
        "اینجا یه بازی متنیه با ماجراجویی، دوئل، گیلد، باس، صندوق گنج، ازدواج و… مرگ‌های بی‌شمار 😄",
        "همه‌چی با نوشتن یه جمله‌ی ساده یا زدن دکمه‌های رنگی انجام میشه. برای شروع، ثبت‌نام کن 👇",
    ]))
    await start_registration(m)


@router.callback_query()
async def on_callback(cq: CallbackQuery, bot: Bot):
    try:
        await handle_cb(cq, bot)
    except Exception:
        log.exception("callback failed")
        try:
            await cq.answer("یه مشکل کوچیک پیش اومد. دوباره امتحان کن. 🛠", show_alert=True)
        except Exception:
            pass


@router.message(F.text)
async def on_text(m: Message, bot: Bot):
    if not m.from_user or m.from_user.is_bot or not m.text or m.text.startswith("/"):
        return
    try:
        await handle_text(m, bot)
    except Exception:
        log.exception("handler failed")
        await say(m, "یه مشکل فنی پیش اومد. چند لحظه‌ی دیگه دوباره امتحان کن. 🛠", "🛠", "خطای سیستم", "red")


def looks_like_game(c: str, n: str, m: Message) -> bool:
    """آیا این پیام یه دستور بازی‌ست؟ (برای گیتِ ثبت‌نام؛ پیام‌های عادی گروه رو مزاحم نمی‌شه)"""
    full = (MENU_RE, QUEST_RE, TERR_RE, SIEGE_RE, MARRY_RE, MARRY_ACCEPT_RE, MARRY_DECLINE_RE, DIVORCE_RE,
            BOSS_CALL_RE, BOSS_HIT_RE, BOSS_STATUS_RE, DEATH_RE, PASSPORT_RE, TITLES_RE, INV_RE, INVITE_RE,
            STROLL_RE, DUEL_RE, GUILD_CREATE_RE, GUILD_JOIN_RE, GUILD_WAR_RE, GUILD_ME_RE, GUILD_LEAVE_RE,
            GUILD_INVITE_RE)
    srch = (WHEEL_RE, BOARD_RE, CAFE_RE, NPC_RE, MARKET_RE, ACCEPT_RE, TRADE_RE)
    if any(r.fullmatch(c) for r in full) or any(r.search(c) for r in srch):
        return True
    if EXEC_RE.search(n):
        return True
    if m.reply_to_message and (REPLY_EXEC_RE.fullmatch(c) or CURSE_RE.search(n) or BLESS_RE.search(n)):
        return True
    if TRAVEL_RE.fullmatch(c) and detect_biome(c):
        return True
    return False


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

    # بن‌شده‌ها نادیده گرفته میشن؛ ادمین‌ها قبل از همه
    me_doc = await store.get(m.from_user.id)
    if me_doc and me_doc.get("banned"):
        return
    if await handle_admin_commands(m, bot, c):
        return
    registered = bool(me_doc and me_doc.get("registered"))

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
        _recent_chatters[m.chat.id].append((m.from_user.id, m.from_user.full_name))

    # ۰.۵) ثبت‌نام: بدون قرارداد، ورود به ایسکا ممنوعه
    if REG_RE.fullmatch(c):
        if registered:
            await say(m, "تو قبلاً قرارداد رو امضا کردی. یادت رفته؟ حافظه‌ت از ماهی هم ضعیف‌تره. 📜", "📜", "ثبت‌نام", "purple")
        else:
            await start_registration(m)
        return
    if not registered:
        if HELP_RE.fullmatch(c):
            await m.reply(SMALL_TALK_HELP)
            return
        if not (OPT_OUT_RE.fullmatch(c) or OPT_IN_RE.fullmatch(c)):
            drop_try = (OPEN_RE.fullmatch(c) or DEFUSE_RE.fullmatch(c)) and group and \
                await store.drops.count_documents({"chat_id": m.chat.id, "status": "open", "expires_at": {"$gt": utcnow()}})
            if (not group) or mentioned or replied_to_bot or drop_try or looks_like_game(c, n, m):
                await reg_prompt(m)
                return

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

    # ۶.۵) منو، ماموریت، قلمرو، پیوند، صندوق/بمب، باس
    if MENU_RE.fullmatch(c):
        await send_hub(m, me_doc)
        return
    if QUEST_RE.fullmatch(c):
        await do_quests(m)
        return
    if TERR_RE.fullmatch(c):
        await do_terr(m)
        return
    if sm := SIEGE_RE.fullmatch(c):
        key = find_terr(sm.group(2))
        if key:
            await do_siege(m, key)
        else:
            await say(m, "کدوم قلمرو؟ یکی از اینا رو بنویس: «پایتخت»، «قلعه»، «جنگل»، «بندر» یا «خرابه».", "🗺", "محاصره", "blue")
        return
    if mm := MARRY_RE.fullmatch(c):
        if await do_marry(m, mm.group(3)):
            return
    if MARRY_ACCEPT_RE.fullmatch(c) and group and await marriage_answer(m, True, None):
        return
    if MARRY_DECLINE_RE.fullmatch(c) and group and await marriage_answer(m, False, None):
        return
    if DIVORCE_RE.fullmatch(c):
        await do_divorce(m)
        return
    if group and OPEN_RE.fullmatch(c) and await claim_drop(m, "open"):
        return
    if group and DEFUSE_RE.fullmatch(c) and await claim_drop(m, "defuse"):
        return
    if BOSS_CALL_RE.fullmatch(c):
        await do_boss_call(m, bot)
        return
    if BOSS_HIT_RE.fullmatch(c):
        if not await do_raid_hit(m):
            await say(m, "الان باسی نیست. برای احضار بنویس «احضار باس». 🐉", "🐉", "باس", "red")
        return
    if BOSS_STATUS_RE.fullmatch(c):
        await do_boss_status(m)
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
        await say(m, "این آدم تو شهر نیست. یکی از اینا رو امتحان کن: «پیرمرد»، «مغازه‌دار»، «کافه‌چی»، «نگهبان» یا «جادوگر». 🤷", "🧙", "NPC", "purple",
                  kb([btn("🧙 لیست NPCها", f"m:npc:{m.from_user.id}", "blue")]))
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
    uid = m.from_user.id
    if MARKET_RE.search(c):
        await m.reply(await drop_offer(m.chat.id), reply_markup=kb([btn("💸 میخرم!", "buy:0:0", "green")]))
        return
    if TITLES_RE.fullmatch(c):
        titles = me_doc.get("titles") or []
        if not titles:
            await say(m, "هنوز لقبی نداری. با ماجراجویی و بازتولد (بنویس «ریسپاون») لقب می‌گیری! 🏷", "🏷", "لقب‌ها", "purple")
        else:
            lines = [f"{i}. {esc(t)}" for i, t in enumerate(titles, 1)]
            await m.reply(panel("purple", "🏷", f"لقب‌های {m.from_user.full_name}", lines),
                          reply_markup=kb(back_kb(uid)))
        return
    if INV_RE.fullmatch(c):
        await send_inventory(m, me_doc)
        return
    if PASSPORT_RE.fullmatch(c):
        await m.reply(render_passport(me_doc), reply_markup=kb(
            [btn("🌙 منو", f"m:main:{uid}", "blue"), btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "green")]))
        return
    if DEATH_RE.fullmatch(c):
        await do_self_death(m)
        return
    if INVITE_RE.fullmatch(c):
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
        await m.reply(panel("blue", "🔗", "لینک دعوت اختصاصی", [
            link, "هر ۳ نفر که با این لینک وارد بازی بشن = یه شانس خرید از بازار سیاه 🎁",
        ]), reply_markup=kb([btn("📩 باز کردن لینک", url=link)]))
        return
    if OPT_OUT_RE.fullmatch(c):
        await store.users.update_one({"user_id": uid}, {"$set": {"opted_out": True}})
        await say(m, "باشه! از این به بعد کسی نمی‌تونه اعدامت کنه، نفرینت کنه یا به دوئل دعوتت کنه. هر وقت پشیمون شدی بنویس «برگردم به بازی». 🛡", "🛡", "محافظت", "blue")
        return
    if OPT_IN_RE.fullmatch(c):
        await store.users.update_one({"user_id": uid}, {"$set": {"opted_out": False}})
        await say(m, "خوش برگشتی! 😈 از حالا دوباره بقیه می‌تونن اعدامت کنن، نفرینت کنن یا به دوئل دعوتت کنن. 😄", "😈", "برگشتی", "red")
        return
    if HELP_RE.fullmatch(c):
        await m.reply(SMALL_TALK_HELP, reply_markup=kb([btn("🌙 منوی اصلی", f"m:main:{uid}", "green")]))
        return

    # ۱۰) صدا زدن بدون دستور معتبر
    if mentioned or replied_to_bot:
        await m.reply(panel("purple", "💅", GODDESS_NAME, [random.choice(ROASTS)], gline(me_doc)),
                      reply_markup=kb([btn("🌙 پنل‌ها", f"m:main:{uid}", "blue")]))
        return
    if not group:
        await m.answer(SMALL_TALK_HELP, reply_markup=kb([btn("🌙 منوی اصلی", f"m:main:{uid}", "green")]))
        return

    # ۱۱) حرکات تصادفیِ گروه: لقب‌خوانی، بازار سیاه، صندوق/بمب، باس
    now = time.time()
    doc = me_doc
    if doc and doc.get("titles") and random.random() < HERALD_CHANCE and now - _last_herald.get(uid, 0) > HERALD_COOLDOWN:
        _last_herald[uid] = now
        await m.reply(panel("yellow", "🔔", "توجه توجه!", [
            f"👑 {display(doc, link=True)} وارد صحنه شد! همه دست بزنید. 👏",
        ], gline(doc)))
        return
    if random.random() < RANDOM_DROP_CHANCE and now - _last_drop.get(m.chat.id, 0) > DROP_COOLDOWN:
        await m.answer(await drop_offer(m.chat.id), reply_markup=kb([btn("💸 میخرم!", "buy:0:0", "green")]))
        return
    if random.random() < LOOT_CHANCE and now - _last_loot.get(m.chat.id, 0) > LOOT_COOLDOWN:
        await spawn_drop(bot, m.chat.id)
        return
    if random.random() < RAID_SPAWN_CHANCE:
        await spawn_raid(bot, m.chat.id)


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
