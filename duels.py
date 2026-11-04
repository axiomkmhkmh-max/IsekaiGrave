"""دوئل بین بازیکن‌ها."""

import random
from datetime import timedelta
from typing import Optional

from aiogram.types import Message
from pymongo import ReturnDocument

from battle import start_duel
from config import DUEL_TTL, runtime
from content import GODDESS_NAME
from database import store
from render import display
from ui import btn, kb, panel, say
from utils import esc, is_group, utcnow


async def do_duel_request(m: Message, uname: Optional[str]) -> bool:
    if not is_group(m):
        await say(m, "دوئل فقط تو گروه کار می‌کنه؛ چون تماشاگر لازمه. ⚔️", "⚔️", "دوئل", "orange")
        return True
    target = None
    if uname:
        if uname.lower() == runtime.bot_username.lower():
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
        f"⚔️ {esc(a.full_name)} داره {display(target, link=True)} رو به دوئل دعوت می‌کنه!",
        "⏳ ۳ دقیقه وقت داره که قبول کنه.",
    ], "برای قبول بنویس: «<b>قبول دوئل</b>» یا دکمه‌ی پایین رو بزن 🥊\n🧿 نبردِ رشته‌ی سرنوشت: نوبتی و تاکتیکیه؛ سپر، روح و بازتولد تصمیم می‌گیرن!"),
        reply_markup=kb([btn("🥊 قبول دوئل", f"duelacc:{target['user_id']}", "green")]))
    return True


async def do_duel_accept(m: Message) -> bool:
    """قبولِ دوئل → شروعِ «نبردِ رشته‌ی سرنوشت» (battle.py). پذیرش اتمیکه: فقط یک‌بار."""
    duel = await store.duels.find_one_and_update(
        {"chat_id": m.chat.id, "b": m.from_user.id, "status": "pending", "expires_at": {"$gt": utcnow()}},
        {"$set": {"status": "fighting"}},
        return_document=ReturnDocument.AFTER,
    )
    if not duel:
        return False
    return await start_duel(m, duel)
