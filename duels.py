"""دوئل بین بازیکن‌ها."""

import random
from datetime import timedelta
from typing import Optional

from aiogram.types import Message
from pymongo import ReturnDocument

from config import DUEL_TTL, runtime
from content import GODDESS_NAME
from database import store
from players import cls_is, grant, reincarnate
from quests import quest_progress
from render import display, render_rebirth, render_scene
from ui import btn, hp_bar, kb, panel, say
from utils import esc, is_group, utcnow
from weekly import add_guild_pts


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
        f"🛡 {display(da, link=True)} ⚡{int(pa)}",
        "      ⚔️ VS ⚔️",
        f"🗡 {display(db_, link=True)} ⚡{int(pb)}",
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
