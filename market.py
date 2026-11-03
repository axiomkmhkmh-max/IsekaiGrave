"""بازار سیاه و خرید پیشنهادهای تصادفی."""

import random
import time
from datetime import timedelta

from aiogram.types import Message
from pymongo import ReturnDocument

from config import OFFER_TTL, runtime
from content import BLACK_MARKET_ITEMS, PRICES, roll_item
from database import store
from players import reincarnate, spend
from render import display, render_rebirth, render_scene
from ui import panel, say
from utils import esc, gid, utcnow


_last_drop: dict = {}


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
            link = f"https://t.me/{runtime.bot_username}?start=ref_{uid}"
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
