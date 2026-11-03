"""گفتگو با NPCها، ماموریت‌های NPC و معامله."""

import random

from aiogram.types import Message

from content import BIOME_LIST, BIOMES, NPCS, QUEST_REWARD, roast_for, SHOP_ITEMS
from database import store
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
            lines.append(f"📜 «هنوز اون ماموریتو انجام ندادی؟ برو <b>{b['name']}</b> {b['icon']} و برگرد!»\n🪙 جایزه: {q['reward']} طلا")
        else:
            bkey = random.choice([b for b in BIOME_LIST if b != "city"])
            B = BIOMES[bkey]
            reward = random.randint(*QUEST_REWARD)
            await store.users.update_one(
                {"user_id": uid}, {"$set": {"quest": {"biome": bkey, "reward": reward}}}
            )
            lines.append(
                f"📜 <b>ماموریت جدید!</b>\n«جوون، برو <b>{B['name']}</b> {B['icon']} یه گشتی بزن و سالم برگرد. "
                f"اگه موفق شدی، {reward} طلا جایزه داری! 🎁»\n"
                f"👉 برای رفتن بنویس: «سفر به {B['kw'].strip('()').split('|')[0]}»"
            )
    elif npc_key == "shop":
        item, price = random.choice(SHOP_ITEMS)
        await store.users.update_one({"user_id": uid}, {"$set": {"pending_trade": {"item": item, "price": price}}})
        lines.append(
            f"🛒 «فقط امروز! <b>{esc(item)}</b> — فقط <b>{price} طلا</b>. فرصت خوبیه، بدو!»"
        )
        foot = f"💡 برای خرید بنویس «<b>قبول معامله</b>» (طلای تو: {doc.get('gold', 0)} 🪙)"
    elif npc_key == "cafe":
        if await spend(uid, 10):
            h = heal_bonus(doc, random.randint(6, 14))
            d2, _ = await grant(uid, xp=5, survival=h)
            lines.append(f"☕ یه قهوه‌ی «ضدمرگ» گرفتی (−۱۰ طلا). +{h}٪ بقا.\n«نوش جان! زندگی یه کم تلخه، ولی ارزشش رو داره.»")
        else:
            lines.append("☕ قهوه ۱۰ طلا میشه و تو نداری. کافه‌چی یه لیوان آب بهت داد: «برو ماجراجویی کن، بعد برگرد!»")
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
    d3 = await store.get(uid)
    lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(d3)]
    await m.reply(panel(npc["color"], npc["icon"], npc["name"], lines, foot),
                  reply_markup=kb([btn("🧙 NPCهای دیگه", f"m:npc:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")]))
    await quest_progress(m, "npc")


async def do_trade(m: Message) -> bool:
    uid = m.from_user.id
    doc = await store.get(uid)
    pt = doc.get("pending_trade")
    if not pt:
        return False
    if not await spend(uid, pt["price"]):
        await say(m, "«طلات کمه! برو ماجراجویی کن و با پول برگرد.» 🪙", "🧔", "مغازه‌دارِ بی‌اعتماد", "yellow")
        return True
    item = f"🕵️ {pt['item']} ‹معامله‌ی مشکوک›"
    await store.users.update_one(
        {"user_id": uid},
        {"$set": {"pending_trade": None}, "$push": {"inventory": {"$each": [item], "$slice": -15}}},
    )
    await m.reply(panel("yellow", "🛒", "معامله انجام شد",
                        [f"🎁 {esc(item)}", f"🪙 −{pt['price']} طلا", "🧔 «معامله‌ی خوبی بود! دوباره بیا.»"]))
    return True
