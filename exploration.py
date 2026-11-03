"""ماجراجویی و گشت در بیوم‌ها."""

import random
import re
import time
from typing import Optional

from aiogram.types import Message

from config import EXPLORE_COOLDOWN
from content import BIOMES, gline, LORE_LINES, RARITIES, roll_item
from database import store
from menus import after_death_kb, after_explore_kb
from players import cls_is, gold_bonus, grant, heal_bonus, refresh_titles, reincarnate
from quests import quest_progress
from render import render_rebirth, render_scene, stat_lines
from territories import terr_income
from ui import panel, say
from utils import esc, gid
from weekly import add_guild_pts


_last_explore: dict = {}


def detect_biome(text: str) -> Optional[str]:
    for key, b in BIOMES.items():
        if re.search(b["kw"], text):
            return key
    return None


async def do_explore(m: Message, key: str):
    uid = m.from_user.id
    now = time.time()
    if now - _last_explore.get(uid, 0) < EXPLORE_COOLDOWN:
        await say(m, "پاهات هنوز داغه! چند ثانیه نفس بکش و دوباره برو. 🥵", "🥵", "یه کم استراحت", "orange")
        return
    _last_explore[uid] = now

    B = BIOMES[key]
    doc = await store.get(uid)
    await store.users.update_one({"user_id": uid}, {"$set": {"location": key}, "$inc": {"trips": 1}})
    kinds = list(B["w"].keys())
    kind = random.choices(kinds, weights=[B["w"][k] for k in kinds])[0]

    lines = [f"<i>{random.choice(B['intro'])}</i>", "┈┈┈┈┈┈┈┈┈┈"]
    died = False
    leveled = False

    if kind == "find":
        item, idx, val = roll_item(B["items"])
        gold = gold_bonus(doc, random.randint(5, 25) + val)
        cursed = idx == len(RARITIES) - 1
        doc, leveled = await grant(uid, gold=gold, xp=random.randint(8, 18), item=item,
                                   survival=-5 if cursed else 0)
        lines.append(f"✨ <b>گنج پیدا کردی!</b>\n🎁 {esc(item)}\n🪙 +{gold} طلا")
        if cursed:
            lines.append("🩸 آیتم نفرین‌شده بود! −۵٪ بقا. ایزدبانو خندید: «اپس. لایقش بودی.»")
    elif kind == "monster":
        mname, strength = random.choice(B["monsters"])
        mine = doc.get("level", 1) * 4 + doc.get("survival_rate", 50) / 2 + random.randint(0, 25) + (8 if cls_is(doc, "warrior") else 0)
        theirs = strength + random.randint(0, 25)
        lines.append(f"👹 <b>{esc(mname)}</b> سر راهت سبز شد! (قدرت {strength})")
        if mine >= theirs:
            g = gold_bonus(doc, random.randint(8, 30))
            doc, leveled = await grant(uid, gold=g, xp=random.randint(18, 35))
            lines.append(f"⚔️ <b>پیروز شدی!</b> هیولا فرار کرد و یه کیسه‌ی کوچیک جا گذاشت.\n🪙 +{g} طلا")
            if random.random() < 0.3:
                item, _, _ = roll_item(B["items"])
                doc, _ = await grant(uid, item=item)
                lines.append(f"🎁 غنیمت: {esc(item)}")
        else:
            loss = random.randint(8, 20)
            doc, _ = await grant(uid, xp=4, survival=-loss)
            lines.append(f"🩸 <b>شکست خوردی!</b> {esc(mname)} ازت قوی‌تر بود. −{loss}٪ بقا. دفعه‌ی بعد بهتر میشه! 💪")
            if doc.get("survival_rate", 100) <= 2:
                died = True
    elif kind == "heal":
        h = heal_bonus(doc, random.randint(8, 18))
        doc, leveled = await grant(uid, xp=6, survival=h)
        lines.append(f"💚 یه چشمه‌ی شفابخش پیدا کردی و ازش خوردی. +{h}٪ بقا.")
    elif kind == "trap":
        loss = random.randint(5, 14)
        doc, _ = await grant(uid, xp=3, survival=-loss)
        lines.append(f"🕳 {random.choice(B['traps'])}. −{loss}٪ بقا.")
        if doc.get("survival_rate", 100) <= 2:
            died = True
    elif kind == "death":
        lines.append(f"💀 {random.choice(B['deaths'])}")
        died = True
    else:  # lore
        doc, leveled = await grant(uid, xp=random.randint(6, 14))
        lines.append(f"📖 {random.choice(LORE_LINES)}")

    # ماموریت پیرمرد
    q = (await store.get(uid)).get("quest")
    if q and q.get("biome") == key and not died:
        reward = q.get("reward", 50)
        doc, lv2 = await grant(uid, gold=reward, xp=30)
        leveled = leveled or lv2
        await store.users.update_one({"user_id": uid}, {"$set": {"quest": None}})
        lines.append(f"📜 <b>ماموریت پیرمرد انجام شد!</b> 🪙 +{reward} طلا و ۳۰ XP. «آفرین! کارت عالی بود.»")

    # 👑 درآمد قلمرو + امتیاز هفتگی گیلد
    if not died and doc.get("guild"):
        inc = await terr_income(doc)
        if inc:
            await grant(uid, gold=inc)
            lines.append(f"👑 درآمد قلمروهای گیلد: 🪙 +{inc}")
        await add_guild_pts(doc.get("guild"), 1)

    if leveled:
        lines.append(f"🆙 <b>تبریک! سطحت بالا رفت!</b> حالا سطح {doc.get('level', 1)} هستی. 🎉")

    if died:
        rdoc, new = await reincarnate(uid, chat_id=gid(m))
        scene = render_scene(f"<b>{esc(m.from_user.full_name)}</b>")
        text = (
            panel(B["color"], B["icon"], f"{B['name']} — مرگ ناگهانی!", lines)
            + f"\n\n{scene}\n\n{render_rebirth(rdoc, new)}"
        )
        mk = after_death_kb(uid)
    else:
        doc = await store.get(uid)
        lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(doc)]
        doc, new = await refresh_titles(doc)
        text = panel(B["color"], B["icon"], B["name"], lines, gline(doc) if random.random() < 0.3 else None)
        if new:
            text += "\n🏷 <b>لقب جدید:</b> " + "، ".join(f"«{esc(t)}»" for t in new)
        mk = after_explore_kb(uid, key)
    await m.reply(text, reply_markup=mk)
    await quest_progress(m, "trip")
