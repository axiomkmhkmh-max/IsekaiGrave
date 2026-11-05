"""
@IsekaiGraveBot — ایسکای‌ِ متنیِ رنگی با ایزدبانوی پایان
Stack: aiogram 3.27+ + motor (MongoDB) | Deploy: Railway (long polling worker)

ENV:
  TELEGRAM_BOT_TOKEN  (required)
  MONGO_URI           (required)
  MONGO_DB_NAME       (optional, default: isekai_grave)
  RANDOM_DROP_CHANCE  (optional, default: 0.02)   شانس بازار سیاه‌ی تصادفی
  ADMIN_USER_IDS      (optional) آیدی عددی ادمین‌ها با کاما: "123456789,987654321"
  LOG_CHANNEL         (optional, default: @isekailog) کانال لاگِ کارهای بازیکن‌ها؛ ربات باید ادمین کانال باشه. خالی = خاموش
  LOG_NAV             (optional, default: 0) 1 = کلیک‌های ناوبری منو هم لاگ بشه
  CEREBRAS_API_KEY / CEREBRAS_MODEL / CEREBRAS_BASE_URL / AI_ENABLED  (optional) هوش مصنوعیِ NPCها؛ بدونِ کلید دنیا با پایتون کار می‌کنه
  WORLD_ENABLED / WORLD_TICK_SECONDS / WORLD_TIME_SCALE / WORLD_EVENT_CHANCE  (optional) دنیای زنده

نکته: از BotFather گزینه‌ی Group Privacy رو Disable کن تا ربات پیام‌های عادی گروه رو ببینه.

🎨 رنگ پنل‌ها:
تلگرام به متن رنگ نمیده؛ تنها رنگِ واقعی همون «استایل دکمه‌های اینلاین»ـه (Bot API 9.4+):
  success = سبز | danger = قرمز | primary = آبی
پس هر پنل زیرش دکمه‌های رنگی داره (منوی اصلی با نوشتن «زندگی من» باز میشه).
"""

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from motor.motor_asyncio import AsyncIOMotorClient

from commands import setup_commands
from config import BOT_TOKEN, DB_NAME, log, MONGO_URI, runtime
from battle import recover_battles
from database import store
from exchange import recover_exchange
import logchannel
from handlers import router
from territories import recover_sieges
from updates import notify_if_updated
from weekly import weekly_loop
import aiclient
from config import WORLD_ENABLED
from worldsim import world_loop


async def main():
    if not BOT_TOKEN or not MONGO_URI:
        raise SystemExit("TELEGRAM_BOT_TOKEN و MONGO_URI باید تنظیم شده باشن.")
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    store.bind(client[DB_NAME])
    await store.ensure_indexes()

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    runtime.bot_username = (await bot.get_me()).username or ""
    log.info("Bot @%s is alive. God help us all.", runtime.bot_username)

    dp = Dispatcher()
    dp.include_router(router)
    await setup_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await logchannel.start(bot)
    await recover_exchange(bot)     # 🪦 معاملاتِ نیمه‌کاره (کرش) تمیز میشن
    await recover_battles(bot)      # ⚔️ نبردهای در جریان ادامه پیدا می‌کنن
    await recover_sieges(bot)       # 🏰 محاصره‌های باز نتیجه می‌گیرن
    await notify_if_updated(bot)   # اگه BOT_VERSION عوض شده باشه، به پلیرها پیام آپدیت میره
    weekly_task = asyncio.create_task(weekly_loop(bot))   # 🏆 تغییر هفته + اعلامیه‌ی گروه برتر
    world_task = asyncio.create_task(world_loop(bot)) if WORLD_ENABLED else None   # 🌍 دنیای زنده (ساعت، NPCها، رویدادها، اقتصاد)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        weekly_task.cancel()
        if world_task:
            world_task.cancel()
        await aiclient.shutdown()
        await logchannel.stop()


if __name__ == "__main__":
    asyncio.run(main())
