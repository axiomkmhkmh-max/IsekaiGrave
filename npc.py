"""گفتگو با NPCها، ماموریت‌های NPC و معامله."""

import random

from aiogram.types import Message
from pymongo import ReturnDocument

from config import GS, WITCH_RESTORE_COST
from content import BIOME_LIST, BIOMES, NPCS, QUEST_REWARD, roast_for, SHOP_ITEMS
from database import store
from economy import terr_perks
from players import grant, heal_bonus, spend
from quests import quest_progress
from render import stat_lines
from ui import btn, kb, panel, say
from utils import esc


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
            lines.append(f"📜 «هنوز اون ماموریتو انجام ندادی؟ برو <b>{b['name']}</b> {b['icon']} و برگرد!»\n🪙 جایزه: {q['reward']} {GS}")
        else:
            bkey = random.choice([b for b in BIOME_LIST if b != "city"])
            B = BIOMES[bkey]
            reward = random.randint(*QUEST_REWARD)
            await store.users.update_one(
                {"user_id": uid}, {"$set": {"quest": {"biome": bkey, "reward": reward}}}
            )
            lines.append(
                f"📜 <b>ماموریت جدید!</b>\n«جوون، برو <b>{B['name']}</b> {B['icon']} یه گشتی بزن و سالم برگرد. "
                f"اگه موفق شدی، {reward} {GS} جایزه داری! 🎁»\n"
                f"👉 برای رفتن بنویس: «سفر به {B['kw'].strip('()').split('|')[0]}»"
            )
    elif npc_key == "shop":
        item, price = random.choice(SHOP_ITEMS)
        if "capital" in await terr_perks(doc):      # 🏰 مزیتِ پایتخت: ۱۰٪ تخفیف
            price = max(1, int(price * 0.9))
        await store.users.update_one({"user_id": uid}, {"$set": {"pending_trade": {"item": item, "price": price}}})
        lines.append(
            f"🛒 «فقط امروز! <b>{esc(item)}</b> — فقط <b>{price} {GS}</b>. فرصت خوبیه، بدو!»"
        )
        foot = f"💡 برای خرید بنویس «<b>قبول معامله</b>» ({GS} تو: {doc.get('gold', 0)} 🪙)"
    elif npc_key == "cafe":
        if await spend(uid, 10):
            h = heal_bonus(doc, int(random.randint(6, 14) * (1.2 if "forest" in await terr_perks(doc) else 1)))
            d2, _ = await grant(uid, xp=5, survival=h)
            lines.append(f"☕ یه قهوه‌ی «ضدمرگ» گرفتی (−۱۰ {GS}). +{h}٪ بقا.\n«نوش جان! زندگی یه کم تلخه، ولی ارزشش رو داره.»")
        else:
            lines.append(f"☕ قهوه ۱۰ {GS} میشه و تو نداری. کافه‌چی یه لیوان آب بهت داد: «برو ماجراجویی کن، بعد برگرد!»")
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
        lines.append(f"🔥 «کوره‌ی من هم بازه: تجهیز، ارتقا، ادغام. و اگه روحت ترک خورده، {WITCH_RESTORE_COST} {GS} بده ترمیمش کنم.»")
    d3 = await store.get(uid)
    lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(d3)]
    rows = []
    if npc_key == "witch":
        rows.append([btn("🔥 کوره‌ی روح", f"fg:home:{uid}", "red"), btn(f"🕯 بازیابی روح ({WITCH_RESTORE_COST})", f"fg:rs:{uid}", "purple")])
    await m.reply(panel(npc["color"], npc["icon"], npc["name"], lines, foot),
                  reply_markup=kb(*rows, [btn("🧙 NPCهای دیگه", f"m:npc:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")]))
    await quest_progress(m, "npc")


async def do_trade(m: Message) -> bool:
    uid = m.from_user.id
    # پیشنهاد اتمیک «مصرف» میشه؛ دو بار «قبول معامله» دو بار نمی‌خره
    before = await store.users.find_one_and_update(
        {"user_id": uid, "pending_trade": {"$ne": None}}, {"$set": {"pending_trade": None}}, return_document=ReturnDocument.BEFORE)
    pt = (before or {}).get("pending_trade")
    if not pt:
        return False
    if not await spend(uid, pt["price"]):
        await store.users.update_one({"user_id": uid, "pending_trade": None}, {"$set": {"pending_trade": pt}})
        await say(m, f"«{GS}ـت کمه! برو ماجراجویی کن و با پول برگرد.» 🪙", "🧔", "مغازه‌دارِ بی‌اعتماد", "yellow")
        return True
    item = f"🕵️ {pt['item']} ‹معامله‌ی مشکوک›"
    await store.users.update_one({"user_id": uid}, {"$push": {"inventory": {"$each": [item], "$slice": -15}}})
    await m.reply(panel("yellow", "🛒", "معامله انجام شد",
                        [f"🎁 {esc(item)}", f"🪙 −{pt['price']} {GS}", "🧔 «معامله‌ی خوبی بود! دوباره بیا.»"]))
    return True
