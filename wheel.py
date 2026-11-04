"""گردونه‌ی شانس روزانه."""

import random

from aiogram.types import Message

from config import WHEEL_COOLDOWN
from content import CHEATS, roll_item
from database import store
from players import adjust_survival, status_for
from quests import quest_progress
from ui import btn, hp_bar, kb, panel, say
from utils import esc, utcnow


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
        lines = ["🎡 <b>چرخش معمولی</b>", f"🎁 چیت‌اسکیل جدید: {esc(cheat)}", f"💚 بقا ریست شد: <b>{rate}٪</b> {hp_bar(rate)}"]
        color = "green"
    elif roll < 0.75:
        gold = random.randint(100, 250)
        item, _, _ = roll_item(["تاج گردونه‌ی شانس", "سکه‌ی چهارپری", "طلسم خوش‌شانسی (۵۰٪ جعلی)"])
        item = "👑 " + item.split(" ", 1)[1]
        rate = random.randint(50, 90)
        await store.users.update_one({"user_id": uid}, {
            "$set": {**base_set, "survival_rate": rate, "status": status_for(rate)},
            "$inc": {"gold": gold}, "$push": {"inventory": {"$each": [item], "$slice": -15}},
        })
        lines = ["💰 <b>جک‌پات!!</b> 🎰", f"🪙 +{gold} GS", f"🎁 {esc(item)}", f"✨ چیت‌اسکیل: {esc(cheat)}", f"💚 بقا: <b>{rate}٪</b> {hp_bar(rate)}"]
        color = "yellow"
    elif roll < 0.9:
        await store.users.update_one({"user_id": uid}, {"$set": base_set, "$inc": {"gold": 40}})
        d2 = await adjust_survival(uid, 15)
        lines = ["🙏 <b>برکت خفیف</b>", f"🪙 +۴۰ GS", f"💚 +۱۵٪ بقا → <b>{d2['survival_rate']}٪</b> {hp_bar(d2['survival_rate'])}", f"✨ چیت‌اسکیل: {esc(cheat)}"]
        color = "blue"
    else:
        rate = random.randint(1, 10)
        await store.users.update_one({"user_id": uid}, {"$set": {**base_set, "survival_rate": rate, "status": status_for(rate)}, "$inc": {"xp": 20}})
        lines = ["🩸 <b>نفرین گردونه!</b> ☠️", f"💚 بقا سقوط کرد: <b>{rate}٪</b> {hp_bar(rate)}", "🎁 جایزه‌ی تسلی: ۲۰ XP", f"✨ چیت‌اسکیل: {esc(cheat)}"]
        color = "red"
    await m.reply(panel(color, "🎡", "گردونه‌ی شانس", lines, "فردا دوباره بیا. 🎡 (هر ۲۴ ساعت یه بار)"),
                  reply_markup=kb([btn("📜 ماموریت‌ها", f"m:quest:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")]))
    await quest_progress(m, "wheel")
