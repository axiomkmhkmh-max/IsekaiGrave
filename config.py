"""تنظیمات و ثابت‌های ربات (متغیرهای محیطی، کولداون‌ها، شانس‌ها، لاگ)."""

import logging
import os
import time
from datetime import timedelta


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


log = logging.getLogger("isekai-grave")

# ───────────────────────────── Config ─────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME", "isekai_grave")
RANDOM_DROP_CHANCE = float(os.getenv("RANDOM_DROP_CHANCE", "0.02"))

# 📡 کانال لاگ: همه‌ی کارهای بازیکن‌ها اینجا میره (خالی = خاموش). ربات باید ادمینِ کانال باشه.
LOG_CHANNEL = os.getenv("LOG_CHANNEL", "@isekailog").strip()
LOG_NAV = os.getenv("LOG_NAV", "0") == "1"      # کلیک‌های ناوبریِ منو هم لاگ بشن؟

# آیدی‌های ادمین (با کاما جدا بشن، مثلاً: "123456789,987654321")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()]
# 🔄 اطلاع‌رسانی آپدیت: هر بار این عدد رو بالا ببری و دیپلوی کنی، همه‌ی پلیرها پیام «دوباره /start بزن» می‌گیرن.
BOT_VERSION = "3.6"
UPDATE_NOTES = [
    "🩸 «حمله‌ی ریسکی»: همه‌یا‌هیچ؛ برد = غارت و ضربه‌ی بیشتر، باخت = تاوانِ بیشتر (مدافع هم پاداشِ بیشتر می‌گیره)",
    "🎼 کامبو: سه ژستِ «متفاوتِ» پشت‌سرهم = +۱🕯 (مهاجم) · 🏰 سه دفاعِ متفاوت = +۱🕯 (مدافع)؛ ژست‌های آخرِ هر نفر علنیه، پس بلوف هم ممکنه",
    "🔮 تماشاچی‌ها ژستِ مخفیِ مهاجم رو حدس می‌زنن و با حدسِ درست RP می‌گیرن · ⏰ ثانیه‌های آخرِ دفاع، مدافع منشن میشه",
    "🆚 رقابت: هر جفتی که زیاد بجنگن «رقیب» → «دشمنِ خونی» → «رقیبِ دیرینه» میشن و برنده‌ی اون برخوردها RPِ بیشتری می‌گیره",
    "🔥 روزهای پشت‌سرهم تو میدان · 🎯 چالش‌های روزانه + 🎁 صندوقِ متغیر · 💢 «جان‌سخت» بعد از ۳ باخت · 🏷 لقب‌های جدید",
    "🥋 دکمه‌ی «ریمچِ تمرینی» زیرِ نتیجه‌ی هر برخورد؛ کولداونِ تمرین با یه حریف شد ۴۵ ثانیه",
    "🏆 جایزه‌ی هفتگیِ میدان: ۳ نفرِ اولِ RP هر هفته GS می‌گیرن و نفرِ اول لقبِ «قهرمانِ میدانِ هفته» (لیدربرد: «برترین ها»)",
    "🌅 اولین بردِ هر روز (حمله یا دفاع) XP و RPِ اضافه داره",
    "🎭 تخصصِ کلاس: تساوی‌ها به نفعِ کلاسِ مناسب می‌چرخن (جنگجو 💥↔🔄، دزد 🗡↔🛡، جادوگر 🌀↔💨 تو حمله؛ و برعکس تو دفاع) · کشیشِ مدافعِ پیروز ۴٪ بقا برمی‌گردونه",
    "🔁 حرکتِ تکراری: ژست یا دفاعِ سومین بارِ پشت‌سرهم لو میره و تو تساوی می‌بازه؛ ژست‌هات رو عوض کن",
    "🎲 تماشاچی‌ها می‌تونن ۱۰ GS روی مهاجم یا مدافع شرط ببندن؛ پات بینِ برنده‌ها تقسیم میشه",
    "⚡ ژستِ ویژه با تمرکز · 📜 فرمانِ روز · 🔔 حمایتِ تماشاچی‌ها · 🪤 «تله بذار»",
    "🏟 «میدان نبرد» · «تمرین» · «تحقیرش کن» · «شرط ۵۰» · «نجات» همچنان فعالن",
]
NOTIFY_ON_UPDATE = os.getenv("NOTIFY_ON_UPDATE", "1") == "1"   # برای خاموش کردن: 0

HERALD_CHANCE = 0.04
LOOT_CHANCE = 0.03             # صندوق گنج / بمب ساعتی‌ی تصادفی در گروه
RAID_SPAWN_CHANCE = 0.004      # ظهور خودکار باس
DROP_COOLDOWN = 20 * 60
LOOT_COOLDOWN = 8 * 60
SELF_DEATH_COOLDOWN = 20
FORCED_TARGET_COOLDOWN = 120
HERALD_COOLDOWN = 30 * 60
OFFER_TTL = 15 * 60
NPC_ENCOUNTER_CHANCE = 0.28     # شانسِ برخورد با NPC وسط ماجراجویی (بیرون شهر)
NPC_CITY_CHANCE = 0.55          # تو شهر NPCها بیشترن
EXPLORE_COOLDOWN = 12          # ثانیه بین دو سفر
WHEEL_COOLDOWN = 24 * 3600     # گردونه‌ی شانس
DUEL_TTL = 3 * 60              # مهلت قبول دوئل
GUILD_WAR_COOLDOWN = 30 * 60
SIEGE_COOLDOWN = 30 * 60
GUILD_COST = 60                # هزینه‌ی ساخت گیلد (GS)
GUILD_MAX_MEMBERS = 30
START_GOLD = 100
LOOT_TTL = 3 * 60
BOMB_FUSE = 45                 # ثانیه تا انفجار بمب
RAID_TTL = 30 * 60
RAID_COOLDOWN = 2 * 3600
RAID_HIT_COOLDOWN = 12
PROPOSAL_TTL = 5 * 60
REG_PROMPT_COOLDOWN = 45
BOT_STARTED = time.time()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ───────────────────────────── 🪙 GRAVE SIGIL (GS) ─────────────────────────────
# ارزِ داخلیِ بازی (نه کریپتو). برای حفظ موجودیِ بازیکن‌ها، فیلدِ دیتابیس همون «gold» مونده و فقط نمایشش GS شده.
GS = "GS"
GS_NAME = "GRAVE SIGIL"
INV_CAP = 15                                         # ظرفیت کوله‌پشتی (همون قبلی)
GS_DAILY_SOFT_CAP = _env_int("GS_DAILY_SOFT_CAP", 800)    # درآمد روزانه تا این عدد کامل حساب میشه
GS_DAILY_HARD_CAP = _env_int("GS_DAILY_HARD_CAP", 2000)   # بعد از این عدد، درآمدِ بازی صفر میشه
GS_SOFT_RATE = 0.3                                   # بین سقف نرم و سخت فقط ۳۰٪ می‌رسه
WEEKLY_TITHE_ABOVE = _env_int("WEEKLY_TITHE_ABOVE", 5000)  # عُشرِ هفتگیِ ایزدبانو: فقط روی موجودیِ بالای این عدد
WEEKLY_TITHE_PCT = _env_int("WEEKLY_TITHE_PCT", 2)         # ۰ = خاموش

# 🪦 بازار روح (Grave Exchange)
EXCHANGE_FEE_PCT = _env_int("EXCHANGE_FEE_PCT", 8)         # کارمزد فروش (سوخته میشه)
EXCHANGE_FEE_PCT_CAPITAL = max(0, EXCHANGE_FEE_PCT - 3)    # مالکانِ «پایتخت درخشان»
EXCHANGE_MAX_LISTINGS = _env_int("EXCHANGE_MAX_LISTINGS", 5)
EXCHANGE_MIN_LEVEL = _env_int("EXCHANGE_MIN_LEVEL", 2)
EXCHANGE_MAX_PRICE = 50000
LISTING_TTL = 72 * 3600
EXCHANGE_PAGE = 5

# ⚔️ نبرد
TURN_SECONDS = 75
BATTLE_STALE = 30 * 60
DUEL_REWARD_COOLDOWN = 3600      # تکرارِ دوئل با همون حریف تو این مدت، GS نمی‌ده
WITCH_RESTORE_COST = 45

# 🏰 جنگ قلمروها
SIEGE_WINDOW = _env_int("SIEGE_WINDOW_MIN", 10) * 60
SIEGE_COST = 80                  # از خزانه‌ی گیلد
SIEGE_MIN_JOIN = 2
SIEGE_PROTECT = 2 * 3600         # بعد از فتح، قلمرو مدتی محافظت میشه
SIEGE_MIN_SURVIVAL = 15
WAR_ALLIN_COST = 8               # ٪ بقا برای «تمام‌عیار»
WAR_ALLIN_BONUS = 1.4
WAR_CHEST_PLAYER_CAP = 70
TERR_TRIBUTE = 120               # GS هفتگی به خزانه‌ی گیلدِ مالکِ هر قلمرو
FORT_COSTS = [60, 120, 200]     # تقویت دژ تا ۳ سطح (هر سطح +۱۰٪ دفاع، فقط همین هفته)

# ───────────────────────────── 📜 ماموریت‌های روزانه و هفتگی ─────────────────────────────
IR_OFFSET = timedelta(hours=3, minutes=30)


class Runtime:
    """وضعیتِ زمان‌اجرا که بعد از استارت مقدار می‌گیره (مثلاً یوزرنیم ربات)."""
    bot_username: str = ""


runtime = Runtime()

# ───────────────────────────── 🤖 هوش مصنوعی (OpenRouter) و 🌍 دنیای زنده ─────────────────────────────
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


AI_ENABLED = os.getenv("AI_ENABLED", "1") != "0"                       # ۰ = AI کامل خاموش (دنیا با پایتون کار می‌کنه)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()      # فقط از env؛ هیچ‌جا لاگ/چاپ نمیشه
OPENROUTER_BASE_URL = (os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").strip().rstrip("/")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "").strip()          # شناسه‌ی دقیقِ مدل (مثلاً از openrouter.ai/models با فیلتر Free)؛ پیش‌فرض ندارد
AI_TIMEOUT = _env_int("AI_TIMEOUT", 30)                               # ثانیه برای هر درخواست HTTP (مدل‌های رایگان کندترن)
AI_RETRIES = _env_int("AI_RETRIES", 2)
AI_MAX_CONCURRENT = _env_int("AI_MAX_CONCURRENT", 2)                  # تعداد workerهای صف
AI_QUEUE_MAX = _env_int("AI_QUEUE_MAX", 40)
AI_GLOBAL_PER_MIN = _env_int("AI_GLOBAL_PER_MIN", 15)                 # مدل‌های رایگانِ OpenRouter ~۲۰ درخواست در دقیقه
AI_PLAYER_PER_MIN = _env_int("AI_PLAYER_PER_MIN", 4)
AI_CACHE_TTL = _env_int("AI_CACHE_TTL", 600)
AI_TALK_WAIT = _env_int("AI_TALK_WAIT", 12)                           # حداکثر انتظارِ بازیکن برای جوابِ NPC

WORLD_ENABLED = os.getenv("WORLD_ENABLED", "1") != "0"
WORLD_TICK_SECONDS = _env_int("WORLD_TICK_SECONDS", 300)
WORLD_TIME_SCALE = _env_int("WORLD_TIME_SCALE", 6)                    # هر ۱ دقیقه واقعی = N دقیقه‌ی دنیا (۶ → هر شبانه‌روز = ۴ ساعت)
WORLD_AI_DECISIONS_PER_TICK = _env_int("WORLD_AI_DECISIONS_PER_TICK", 2)
WORLD_EVENT_CHANCE = _env_float("WORLD_EVENT_CHANCE", 0.06)           # شانس ساخت رویداد در هر تیک
WORLD_EVENT_MAX_ACTIVE = _env_int("WORLD_EVENT_MAX_ACTIVE", 4)
WORLD_MAX_CATCHUP = _env_int("WORLD_MAX_CATCHUP", 12)                 # بعد از خاموشی حداکثر چند تیک جبران بشه
WORLD_ANNOUNCE_GROUPS = _env_int("WORLD_ANNOUNCE_GROUPS", 8)          # رویدادهای بزرگ تو چند گروهِ فعال اعلام بشن
CLASS_SEED_SALT = os.getenv("CLASS_SEED_SALT", "isekai-grave-v1")     # سالتِ ثابت: ساختِ کلاس/چیت قطعی و غیرقابل ریرول
