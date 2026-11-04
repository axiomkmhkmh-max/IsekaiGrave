"""اطلاع‌رسانی آپدیت: اگه BOT_VERSION عوض شده باشه، یک‌بار به همه‌ی بازیکن‌ها پیام میره."""

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from config import BOT_VERSION, NOTIFY_ON_UPDATE, UPDATE_NOTES, log
from database import store

_META_ID = "bot_version"
_tasks: set = set()   # نگه‌داشتنِ رفرنس تا تسک جمع نشه


def _text() -> str:
    notes = "\n".join(f"• {n}" for n in UPDATE_NOTES)
    return (f"🪦 <b>آپدیت {BOT_VERSION} اومد!</b>\n\n{notes}\n\n"
            "برای اعمال تغییرات یه بار دوباره /start بزن.")


async def _broadcast(bot: Bot) -> None:
    sent = failed = 0
    text = _text()
    cursor = store.users.find({"registered": {"$ne": False}}, {"user_id": 1})
    async for doc in cursor:
        uid = doc["user_id"]
        for _ in range(3):
            try:
                await bot.send_message(uid, text)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except (TelegramForbiddenError, TelegramAPIError):
                failed += 1
                break
        await asyncio.sleep(0.05)   # ~20 پیام در ثانیه، زیر سقفِ تلگرام
    log.info("Update %s broadcast done: sent=%d failed=%d", BOT_VERSION, sent, failed)


async def notify_if_updated(bot: Bot) -> None:
    """نسخه رو اتمیک ثبت می‌کنه (فقط یک نمونه برنده میشه) و پخش رو تو پس‌زمینه شروع می‌کنه."""
    try:
        prev = await store.meta.find_one_and_update(
            {"_id": _META_ID}, {"$set": {"version": BOT_VERSION}}, upsert=True)
    except Exception:
        log.exception("update check failed")
        return
    if prev is not None and prev.get("version") == BOT_VERSION:
        return
    if not NOTIFY_ON_UPDATE:
        log.info("Version -> %s (notify disabled)", BOT_VERSION)
        return
    log.info("Version -> %s, notifying players", BOT_VERSION)
    t = asyncio.create_task(_broadcast(bot))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
