"""قلمروهای نقشه، محاصره و درآمد قلمرو."""

import random
import re
from typing import Optional

from config import SIEGE_COOLDOWN
from content import TERR_INCOME, TERRITORIES
from database import store
from guilds import guild_power
from quests import quest_progress
from ui import back_kb, btn, kb, panel, say
from utils import esc, utcnow
from weekly import add_guild_pts, ensure_week


# ───────────────────────────── 👑 قلمروها و پادشاه هفته ─────────────────────────────
TERR_ALIAS = {
    "capital": r"(پایتخت|شهر|درخشان)",
    "castle": r"(قلعه|تاریک)",
    "forest": r"(جنگل)",
    "port": r"(بندر|طوفان|دریا)",
    "ruins": r"(خرابه|ویرانه|معبد)",
}


def find_terr(text: str) -> Optional[str]:
    for k, rx in TERR_ALIAS.items():
        if re.search(rx, text):
            return k
    return None


async def do_terr(m):
    uid = m.from_user.id
    meta = await ensure_week()
    owners = {t["key"]: t.get("owner") async for t in store.territories.find({})}
    lines = []
    king = meta.get("king")
    if king:
        lines.append(f"👑 <b>پادشاه هفته‌ی قبل:</b> {esc(king['leader_name'])} — گیلد «{esc(king['guild'])}» ({king['pts']} امتیاز)")
    else:
        lines.append("👑 هنوز پادشاهی نداریم؛ تاج روی میز خاک می‌خوره.")
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    for k, (name, icon, power) in TERRITORIES.items():
        own = owners.get(k)
        lines.append(f"{icon} <b>{name}</b> — " + (f"🛡 {esc(own)}" if own else f"🏴 آزاد (نگهبان ⚡{power})"))
    top = await store.guilds.find({"week_pts": {"$gt": 0}}).sort("week_pts", -1).limit(5).to_list(5)
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    if top:
        lines.append("🏁 <b>رده‌بندی این هفته:</b>")
        lines += [f"{i}. {esc(g['name'])} — {g.get('week_pts', 0)} امتیاز" for i, g in enumerate(top, 1)]
    else:
        lines.append("🏁 هنوز هیچ گیلدی امتیازی نگرفته. وقتشه!")
    rows = []
    ks = list(TERRITORIES.items())
    for i in range(0, len(ks), 2):
        rows.append([btn(f"⚔️ {v[1]} {v[0]}", f"sg:{k}:{uid}", "red") for k, v in ks[i:i + 2]])
    await m.reply(panel("yellow", "🗺", "نقشه‌ی جهان و تاج پادشاهی", lines,
                        "امتیاز هفتگی از ماجراجویی، دوئل، جنگ و محاصره میاد. هر قلمرو برای اعضای گیلدِ مالک 🪙+" + str(TERR_INCOME) + " به‌ازای هر سفر."),
                  reply_markup=kb(*rows, back_kb(uid)))


async def do_siege(m, key: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await say(m, "برای محاصره باید عضو یه گیلد باشی. یه گیلد بساز یا به یکی بپیوند. 🛡", "🛡", "محاصره", "red")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        return
    last = g.get("last_siege_at")
    if last and (utcnow() - last).total_seconds() < SIEGE_COOLDOWN:
        left = int(SIEGE_COOLDOWN - (utcnow() - last).total_seconds()) // 60 + 1
        await say(m, f"گیلدت هنوز خسته‌ست. حدود {left} دقیقه‌ی دیگه می‌تونین دوباره حمله کنین. 🩹", "🩹", "محاصره", "red")
        return
    name, icon, garrison = TERRITORIES[key]
    t = await store.territories.find_one({"key": key})
    holder = await store.guilds.find_one({"name": t["owner"]}) if t and t.get("owner") else None
    if holder and holder["_id"] == g["_id"]:
        await say(m, f"{icon} «{name}» همین الان مال گیلد خودته! یه قلمرو دیگه رو برای حمله انتخاب کن. 👑", "👑", "محاصره", "yellow")
        return
    pa = await guild_power(g)
    pd = int(await guild_power(holder) * 1.1) if holder else garrison
    sa, sd = pa * random.uniform(0.75, 1.25), pd * random.uniform(0.75, 1.25)
    win = sa >= sd
    await store.guilds.update_one({"_id": g["_id"]}, {"$set": {"last_siege_at": utcnow()}})
    defender = esc(holder["name"]) if holder else f"نگهبانانِ {name}"
    lines = [
        f"🛡 <b>{esc(g['name'])}</b>  ⚡{int(sa)}",
        "      ⚔️ محاصره ⚔️",
        f"🗡 <b>{defender}</b>  ⚡{int(sd)}",
        "┈┈┈┈┈┈┈┈┈┈",
    ]
    if win:
        await store.territories.update_one({"key": key}, {"$set": {"owner": g["name"], "since": utcnow()}}, upsert=True)
        await store.users.update_many({"user_id": {"$in": g["members"]}}, {"$inc": {"gold": 20, "xp": 10}})
        await add_guild_pts(g["name"], 25)
        lines.append(f"🏆 <b>{icon} {name} فتح شد!</b> هر عضو 🪙+۲۰ و ۱۰ XP. +۲۵ امتیاز هفتگی.")
        color, foot = "green", "💅 <i>«پرچم جدید، ارباب جدید. ولی آخرش همه‌شون زیر پای منن.»</i>"
    else:
        await add_guild_pts(g["name"], 5)
        lines.append("🪦 محاصره شکست خورد. ناامید نشین! (+۵ امتیاز تشویقی) 💪")
        color, foot = "red", "💅 <i>«شکست خوردین. تو دفتر من، بازنده‌ها حتی اسم هم ندارن.»</i>"
    await m.reply(panel(color, "🏰", f"محاصره‌ی {name}", lines, foot),
                  reply_markup=kb([btn("🗺 نقشه", f"m:terr:{uid}", "blue")]))
    await quest_progress(m, "war")


async def terr_income(doc: dict) -> int:
    if not doc.get("guild"):
        return 0
    n = await store.territories.count_documents({"owner": doc["guild"]})
    return n * TERR_INCOME
