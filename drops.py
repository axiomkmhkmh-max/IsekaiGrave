"""صندوق گنج و بمب ساعتی تصادفی در گروه."""

import asyncio
import random
import time
from collections import defaultdict, deque
from datetime import timedelta

from aiogram import Bot

from config import BOMB_FUSE, log, LOOT_TTL
from content import BLACK_MARKET_ITEMS, roll_item
from database import store
from players import adjust_survival, gold_bonus, grant
from quests import quest_progress
from render import display
from ui import btn, kb, panel, say
from utils import esc, spawn, utcnow


# ───────────────────────────── 🔘 زیرساخت دکمه‌ها / پنل‌ها ─────────────────────────────
_recent_chatters: dict = defaultdict(lambda: deque(maxlen=8))   # chat_id → [(uid, name)]
_last_loot: dict = {}


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
        mk = kb([btn("📦 باز کردن صندوق", "loot:open:0", "green")])
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
            lines.append(f"🩸 <a href=\"tg://user?id={uid}\">{esc(name)}</a> تو محدوده بود: −{loss}٪ بقا و −۲۰ GS")
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
                f"🩸 −{loss}٪ بقا و −۲۰ GS",
            ], "💅 <i>«صندوق‌ها گاز می‌گیرن؛ مثل من. حالا فهمیدی چرا نباید به همه‌چی اعتماد کنی؟»</i>"))
        else:
            gold = gold_bonus(doc, random.randint(40, 120))
            item, _, _ = roll_item(BLACK_MARKET_ITEMS)
            d2, lv = await grant(uid, gold=gold, xp=random.randint(15, 30), item=item)
            lines = [f"{name} صندوق رو باز کرد!", f"🪙 +{gold} GS", f"🎁 {esc(item)}"]
            if lv:
                lines.append(f"🆙 لول‌آپ! سطح {d2.get('level', 1)}")
            await m.reply(panel("yellow", "🎁", "غنیمت!", lines, "💅 <i>«شانس آوردی. دفعه‌ی بعد شانس یادش میره سراغت بیاد.»</i>"))
    else:
        gold = gold_bonus(doc, random.randint(60, 140))
        await grant(uid, gold=gold, xp=30)
        await m.reply(panel("green", "✂️", "بمب خنثی شد!", [
            f"{name} سیم قرمز رو بریده… و سیم قرمز هم همون سیم درست بود! 😮‍💨",
            f"🪙 +{gold} GS و ۳۰ XP — جایزه‌ی قهرمانی",
        ], "💅 <i>«…باشه. این بار شجاع بودی. دفعه‌ی بعد جا بزنی، خودم سیم‌هات رو می‌برم.»</i>"))
    await quest_progress(m, "chest")
    return True
