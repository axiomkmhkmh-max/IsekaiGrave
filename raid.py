"""باس گروهی (سیاه‌چاله‌ی چندنفره)."""

import asyncio
import random
import time
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from pymongo import ReturnDocument

from config import log, RAID_COOLDOWN, RAID_HIT_COOLDOWN, RAID_TTL
from content import BOSS_HITS, BOSSES
from database import store
from players import adjust_survival, cls_is, grant
from quests import quest_progress
from render import display
from ui import btn, kb, panel, say
from utils import esc, is_group, spawn, utcnow


_last_raid_hit: dict = {}


# ───────────────────────────── 🐉 باس گروهی (سیاه‌چاله‌ی چندنفره) ─────────────────────────────
def boss_bar(hp: int, mx: int) -> str:
    n = max(0, min(10, round(10 * max(hp, 0) / mx))) if mx else 0
    return "▰" * n + "▱" * (10 - n)


async def active_raid(chat_id: int) -> Optional[dict]:
    return await store.raids.find_one({"chat_id": chat_id, "status": "active", "expires_at": {"$gt": utcnow()}})


def raid_kb() -> InlineKeyboardMarkup:
    return kb([btn("⚔️ حمله!", "raid:hit:0", "red"), btn("📊 وضعیت", "raid:st:0", "blue")])


async def spawn_raid(bot: Bot, chat_id: int, caller: Optional[str] = None) -> str:
    """'ok' | 'active' | 'cool'"""
    if await active_raid(chat_id):
        return "active"
    last = await store.raids.find({"chat_id": chat_id}).sort("created_at", -1).limit(1).to_list(1)
    if last and (utcnow() - last[0]["created_at"]).total_seconds() < RAID_COOLDOWN:
        return "cool"
    members = await store.users.count_documents({"chats": chat_id})
    mx = 300 + 90 * max(1, min(members, 12))
    name, icon = random.choice(BOSSES)
    res = await store.raids.insert_one({
        "chat_id": chat_id, "name": name, "icon": icon, "hp": mx, "max_hp": mx, "dmg": {}, "names": {},
        "status": "active", "created_at": utcnow(), "expires_at": utcnow() + timedelta(seconds=RAID_TTL),
    })
    who = f"{esc(caller)} با یه ورد مشکوک" if caller else "از شکاف دروازه‌ی آخر"
    await bot.send_message(chat_id, panel("red", icon, f"باس ظاهر شد: {name}", [
        f"💥 {who} <b>{esc(name)}</b> رو احضار کرد!",
        f"❤️ HP: <b>{mx}</b> {boss_bar(mx, mx)}",
        "👥 همه با هم حمله کنید! بنویسید «<b>حمله به باس</b>» یا دکمه‌ی پایین رو بزنید.",
        f"⏳ {RAID_TTL // 60} دقیقه وقت دارید. غنیمت بین همه‌ی حمله‌کننده‌ها تقسیم میشه؛ هر کی بیشتر ضربه بزنه، جایزه‌ی ویژه می‌گیره! 🎁",
    ], "💅 <i>«من فقط تماشا می‌کنم. هر کی ترسید و فرار کرد، اسمش رو تو دفترم می‌نویسم.»</i>"), reply_markup=raid_kb())
    spawn(raid_timer(bot, chat_id, res.inserted_id, RAID_TTL))
    return "ok"


async def raid_timer(bot: Bot, chat_id: int, rid, ttl: int):
    try:
        await asyncio.sleep(ttl)
        r = await store.raids.find_one_and_update({"_id": rid, "status": "active"}, {"$set": {"status": "lost"}})
        if r:
            await bot.send_message(chat_id, panel("black", r["icon"], "باس فرار کرد!", [
                f"{esc(r['name'])} با بقایای HP خودش ({max(int(r['hp']), 0)}) توی مه ناپدید شد.",
                "این بار غنیمتی نیست. دفعه‌ی بعد با هماهنگی بیشتر امتحان کنید! 💪",
            ], "💅 <i>«گروه شما فقط یه استعداد داره: فرار. احمق‌ها.»</i>"))
    except Exception:
        log.exception("raid_timer failed")


async def do_boss_call(m, bot: Bot) -> bool:
    if not is_group(m):
        await say(m, "باس مخصوص گروه‌هاست؛ تنهایی نمی‌شه باهاش جنگید. ربات رو ببر تو یه گروه! 🐉", "🐉", "باس", "red")
        return True
    st = await spawn_raid(bot, m.chat.id, m.from_user.full_name)
    if st == "active":
        await say(m, "یه باس همین الان زنده‌ست! بنویس «حمله به باس» یا دکمه‌ی پایین رو بزن. 🐉", "🐉", "باس", "red", raid_kb())
    elif st == "cool":
        await say(m, "این گروه تازه یه باس رو شکست داده. هر ۲ ساعت فقط یه باس میاد؛ بعداً دوباره امتحان کنین. ⏳", "🐉", "باس", "red")
    return True


async def do_boss_status(m):
    if not is_group(m):
        await say(m, "باس تو گروه‌ها ظاهر میشه. ربات رو به گروهت اضافه کن! 🐉", "🐉", "باس", "red")
        return
    r = await active_raid(m.chat.id)
    if not r:
        await m.reply(panel("red", "🐉", "باس گروه", [
            "الان هیچ باسی زنده نیست.",
            "با «<b>احضار باس</b>» یکی رو صدا بزنید (هر ۲ ساعت). گاهی هم خودش بی‌دعوت میاد!",
        ]), reply_markup=kb([btn("🐉 احضار باس", f"raid:call:0", "red")]))
        return
    left = max(1, int((r["expires_at"] - utcnow()).total_seconds()) // 60)
    top = sorted(r["dmg"].items(), key=lambda x: -x[1])[:5]
    lines = [f"❤️ HP: <b>{max(int(r['hp']), 0)}/{r['max_hp']}</b> {boss_bar(int(r['hp']), r['max_hp'])}",
             f"⏳ ~{left} دقیقه مونده", "┈┈┈┈┈┈┈┈┈┈"]
    if top:
        lines.append("🏅 <b>بیشترین ضربه:</b>")
        lines += [f"{i}. {esc(r['names'].get(u, '؟'))} — {d} 💥" for i, (u, d) in enumerate(top, 1)]
    else:
        lines.append("هنوز کسی بهش ضربه نزده. شجاع‌ها کجان؟")
    await m.reply(panel("red", r["icon"], r["name"], lines), reply_markup=raid_kb())


async def do_raid_hit(m) -> bool:
    if not is_group(m):
        return False
    r = await active_raid(m.chat.id)
    if not r:
        return False
    uid = m.from_user.id
    now = time.time()
    if now - _last_raid_hit.get(uid, 0) < RAID_HIT_COOLDOWN:
        await say(m, f"دستت هنوز می‌لرزه! {RAID_HIT_COOLDOWN} ثانیه صبر کن. 💪", "🐉", "باس", "red")
        return True
    _last_raid_hit[uid] = now
    doc = await store.get(uid)
    dmg = doc.get("level", 1) * 5 + random.randint(15, 45) + (10 if cls_is(doc, "warrior") else 0)
    crit = random.random() < 0.12
    if crit:
        dmg *= 2
    name = m.from_user.full_name
    r2 = await store.raids.find_one_and_update(
        {"_id": r["_id"], "status": "active"},
        {"$inc": {"hp": -dmg, f"dmg.{uid}": dmg}, "$set": {f"names.{uid}": name}},
        return_document=ReturnDocument.AFTER,
    )
    if not r2:
        return False
    lines = [f"{random.choice(['⚔️', '🗡', '🔥', '⚡'])} {display(doc, link=True)} {random.choice(BOSS_HITS)}: <b>{dmg}</b>" + (" 💥 <b>ضربه‌ی بحرانی!</b>" if crit else "")]
    if random.random() < 0.35:
        loss = random.randint(4, 9)
        await adjust_survival(uid, -loss)
        lines.append(f"🩸 {esc(r['name'])} جواب داد: −{loss}٪ بقا")
    hp = max(int(r2["hp"]), 0)
    lines.append(f"❤️ {r2['icon']} {hp}/{r2['max_hp']} {boss_bar(hp, r2['max_hp'])}")
    won = False
    if r2["hp"] <= 0:
        won = bool(await store.raids.find_one_and_update({"_id": r["_id"], "status": "active"}, {"$set": {"status": "won"}}))
    await m.reply(panel("red", r2["icon"], r2["name"], lines), reply_markup=None if won else raid_kb())
    await quest_progress(m, "boss")
    if won:
        await raid_victory(m, r2)
    return True


async def raid_victory(m, r: dict):
    dmg = {int(u): int(d) for u, d in r["dmg"].items()}
    total = max(1, sum(dmg.values()))
    pool = 200 + 30 * len(dmg)
    top_uid = max(dmg, key=dmg.get)
    lines = [f"🏆 <b>{esc(r['name'])} شکست خورد!</b> 🎉", "┈┈┈┈┈┈┈┈┈┈"]
    for u, d in sorted(dmg.items(), key=lambda x: -x[1]):
        gold = int(pool * d / total) + 30
        item = None
        if u == top_uid:
            item = f"👑 {random.choice(['پوستِ', 'دندانِ', 'تاجِ', 'قلبِ'])} {r['name']} ‹غنیمت باس›"
        await grant(u, gold=gold, xp=60, item=item)
        lines.append(f"{'🥇' if u == top_uid else '•'} {esc(r['names'].get(str(u), '؟'))} — 💥{d}  🪙+{gold}" + (" 🎁 غنیمتِ ویژه" if item else ""))
    await m.reply(panel("green", "🏆", "غنایمِ باس", lines,
                        "💅 <i>«…بد نبود. ولی غنیمت رو خرج کن، قبل از این‌که برگردم و پسش بگیرم.»</i>"))
