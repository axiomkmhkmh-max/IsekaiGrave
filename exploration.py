"""ماجراجویی و گشت در بیوم‌ها."""

import random
import re
import time
from typing import Optional

from aiogram.types import Message

import aiclient
from aiclient import clean_text

from config import EXPLORE_COOLDOWN, GS
from economy import terr_perks
from content import BIOMES, gline, LORE_LINES, RARITIES, roll_item
from regions_new import GIANT_MIN_LVL
from database import store
from menus import after_death_kb, after_explore_kb
from npc import roll_encounter
from procgen import cheat_is_active, effect_total
from worldnpc import ensure_gen_profile, on_quest_done
from worldsim import explore_after, explore_weights
from config import WORLD_ENABLED
from players import bump_streak, cls_is, loss_cut, gold_bonus, grant, heal_bonus, refresh_titles, reincarnate
from quests import quest_progress
from render import render_rebirth, render_scene, stat_lines
from territories import terr_income
from ui import panel, say
from utils import esc, gid
from weekly import add_guild_pts


_last_explore: dict = {}


async def _scene(B: dict, what: str, name: Optional[str], uid: int) -> Optional[str]:
    """📖 روایتِ ترکیبی: AI یک صحنه‌ی کوتاه می‌نویسه؛ نبود/خطا/کوتاه → None (متنِ ثابت می‌مونه). اثری روی جایزه/نتیجه نداره."""
    if not aiclient.ai_available():
        return None
    what_en = (f"The player is about to face the giant «{name}». Describe its menacing, darkly funny entrance, before any fight."
               if name else "A short strange lore moment the player witnesses (a rumor, a ruin detail, a weird traveler).")
    msgs = [
        {"role": "system", "content": (
            f"You are the dark-funny narrator of a Persian text isekai RPG. Location: {B['name']}. {what_en} "
            "Write 1-2 short Persian sentences, no emojis, no numbers, no rewards or instructions, and do not say who wins.")},
        {"role": "user", "content": "Narrate."},
    ]
    ck = f"scene|{B['name']}|{what}|{random.randint(0, 3)}"   # چند نسخه‌ی کش‌شده → صرفه‌جویی در سهمیه‌ی رایگان
    txt = await aiclient.ask(msgs, uid=uid, max_tokens=140, temperature=0.9, cache_key=ck, wait=5, tag="adv_scene:" + what)
    txt = clean_text(txt, 220) if txt else ""
    return txt if len(txt) >= 12 else None


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
    doc = await ensure_gen_profile(await store.get(uid))
    perks = await terr_perks(doc)      # 🎖 مزیتِ قلمروهای گیلد: بندر (+۱۰٪ GS) و جنگل (+۲۰٪ شفا)
    def gain(g: int) -> int:
        return int(gold_bonus(doc, g) * (1.1 if "port" in perks else 1))
    await store.users.update_one({"user_id": uid}, {"$set": {"location": key, "npc_here": []}, "$inc": {"trips": 1}})
    kinds = list(B["w"].keys())
    base_w = {k: B["w"][k] for k in kinds}
    wts = await explore_weights(key, base_w) if WORLD_ENABLED else base_w     # 🌍 خطر/رونق و رویدادهای فعالِ منطقه
    kind = random.choices(kinds, weights=[wts[k] for k in kinds])[0]
    if kind == "giant" and (doc.get("level", 1) < GIANT_MIN_LVL or not B.get("giants")):
        kind = "monster"          # 🐲 غول فقط برای سطحِ کافی؛ پایین‌تر هیولای معمولی

    lines = [f"<i>{random.choice(B['intro'])}</i>", "┈┈┈┈┈┈┈┈┈┈"]
    died = False
    leveled = False

    if kind == "find":
        item, idx, val = roll_item(B["items"])
        gold = gain(random.randint(5, 25) + val)
        cursed = idx == len(RARITIES) - 1
        doc, leveled = await grant(uid, gold=gold, xp=random.randint(8, 18), item=item,
                                   survival=-5 if cursed else 0)
        lines.append(f"✨ <b>گنج پیدا کردی!</b>\n🎁 {esc(item)}\n🪙 +{gold} {GS}")
        if cursed:
            lines.append("🩸 آیتم نفرین‌شده بود! −۵٪ بقا. ایزدبانو خندید: «اپس. لایقش بودی.»")
    elif kind == "monster":
        mname, strength = random.choice(B["monsters"])
        mine = doc.get("level", 1) * 4 + doc.get("survival_rate", 50) / 2 + random.randint(0, 25) + (8 if cls_is(doc, "warrior") else 0)
        theirs = strength + random.randint(0, 25)
        lines.append(f"👹 <b>{esc(mname)}</b> سر راهت سبز شد! (قدرت {strength})")
        if mine >= theirs:
            g = gain(random.randint(8, 30))
            doc, leveled = await grant(uid, gold=g, xp=random.randint(18, 35))
            lines.append(f"⚔️ <b>پیروز شدی!</b> هیولا فرار کرد و یه کیسه‌ی کوچیک جا گذاشت.\n🪙 +{g} {GS}")
            if random.random() < 0.3 + effect_total(doc, "loot_chance_pct") / 100:
                item, _, _ = roll_item(B["items"])
                doc, _ = await grant(uid, item=item)
                lines.append(f"🎁 غنیمت: {esc(item)}")
        else:
            loss = loss_cut(doc, random.randint(8, 20))
            doc, _ = await grant(uid, xp=4, survival=-loss)
            lines.append(f"🩸 <b>شکست خوردی!</b> {esc(mname)} ازت قوی‌تر بود. −{loss}٪ بقا. دفعه‌ی بعد بهتر میشه! 💪")
            if doc.get("survival_rate", 100) <= 2:
                died = True
    elif kind == "giant":
        gname, strength = random.choice(B["giants"])
        mine = doc.get("level", 1) * 4 + doc.get("survival_rate", 50) / 2 + random.randint(0, 25) + (8 if cls_is(doc, "warrior") else 0)
        theirs = strength + random.randint(0, 25)
        lines.append(f"🐲 <b>غولِ {esc(gname)}</b> جلوت ایستاده! (قدرت {strength})")
        scene = await _scene(B, "giant", gname, uid)
        if scene:
            lines.append(f"📖 <i>{esc(scene)}</i>")
        if mine >= theirs:
            g = gain(random.randint(40, 90))
            doc, leveled = await grant(uid, gold=g, xp=random.randint(60, 100))
            a, b2 = roll_item(B["items"]), roll_item(B["items"])
            item = (a if a[1] >= b2[1] else b2)[0]            # بهترِ دو بار قرعه
            doc, _ = await grant(uid, item=item)
            lines.append(f"⚔️ <b>غول رو زمین زدی!</b> 🏆\n🪙 +{g} {GS}\n🎁 غنیمتِ غول: {esc(item)}")
        else:
            loss = loss_cut(doc, random.randint(18, 32))
            doc, _ = await grant(uid, xp=6, survival=-loss)
            lines.append(f"🩸 <b>غول تو رو کوبید!</b> −{loss}٪ بقا. بعدش با سطحِ بالاتر یا بقای بیشتر برگرد. 💪")
            if doc.get("survival_rate", 100) <= 2:
                died = True
    elif kind == "heal":
        h = heal_bonus(doc, int(random.randint(8, 18) * (1.2 if "forest" in perks else 1)))
        doc, leveled = await grant(uid, xp=6, survival=h)
        lines.append(f"💚 یه چشمه‌ی شفابخش پیدا کردی و ازش خوردی. +{h}٪ بقا.")
    elif kind == "trap":
        loss = loss_cut(doc, random.randint(5, 14))
        doc, _ = await grant(uid, xp=3, survival=-loss)
        lines.append(f"🕳 {random.choice(B['traps'])}. −{loss}٪ بقا.")
        if doc.get("survival_rate", 100) <= 2:
            died = True
    elif kind == "death":
        lines.append(f"💀 {random.choice(B['deaths'])}")
        died = True
    else:  # lore
        doc, leveled = await grant(uid, xp=random.randint(6, 14))
        scene = await _scene(B, "lore", None, uid) if random.random() < 0.4 else None     # روایتِ ترکیبی: گاهی AI
        lines.append(f"📖 {esc(scene) if scene else random.choice(LORE_LINES)}")

    # ماموریت پیرمرد
    q = (await store.get(uid)).get("quest")
    if q and q.get("biome") == key and not died:
        reward = q.get("reward", 50)
        doc, lv2 = await grant(uid, gold=reward, xp=30)
        leveled = leveled or lv2
        await store.users.update_one({"user_id": uid}, {"$set": {"quest": None}})
        giver = q.get("giver") or "پیرمرد"
        lines.append(f"📜 <b>ماموریتِ {esc(giver)} انجام شد!</b> 🪙 +{reward} {GS} و ۳۰ XP. «آفرین! کارت عالی بود.»")
        await on_quest_done(uid, q)

    # 👑 درآمد قلمرو + امتیاز هفتگی گیلد
    if not died and doc.get("guild"):
        inc = await terr_income(doc)
        if inc:
            await grant(uid, gold=inc)
            lines.append(f"👑 درآمد قلمروهای گیلد: 🪙 +{inc}")
        await add_guild_pts(doc.get("guild"), 1)

    if cheat_is_active(doc):
        await store.users.update_one({"user_id": uid, "cheat_charges": {"$gt": 0}}, {"$inc": {"cheat_charges": -1}})
    if WORLD_ENABLED:
        lines += await explore_after(uid, key, died)
    if not died:
        sl = await bump_streak(doc)
        if sl:
            lines.append(sl)

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
        met = await roll_encounter(doc, key)          # 🧙 NPCِ زنده‌ی سرِ راه (اگه بود)
        if met:
            lines += ["┈┈┈┈┈┈┈┈┈┈", *[f"👣 {arrive}" for _, arrive in met]]
        lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(doc)]
        doc, new = await refresh_titles(doc)
        text = panel(B["color"], B["icon"], B["name"], lines, gline(doc) if random.random() < 0.3 else None)
        if new:
            text += "\n🏷 <b>لقب جدید:</b> " + "، ".join(f"«{esc(t)}»" for t in new)
        mk = after_explore_kb(uid, key, [k for k, _ in met])
    await m.reply(text, reply_markup=mk)
    await quest_progress(m, "trip")
