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
BOT_STARTED = time.time()

# ───────────────────────────── 📜 ماموریت‌های روزانه و هفتگی ─────────────────────────────
IR_OFFSET = timedelta(hours=3, minutes=30)


class Runtime:
    """وضعیتِ زمان‌اجرا که بعد از استارت مقدار می‌گیره (مثلاً یوزرنیم ربات)."""
    bot_username: str = ""


runtime = Runtime()
