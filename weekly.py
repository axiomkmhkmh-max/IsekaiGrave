"""امتیاز هفتگی گیلدها، پادشاه هفته، خراجِ قلمروها و عُشرِ ایزدبانو.

تغییرِ هفته «اتمیک» ادعا میشه (فقط یک پردازش پاداش‌ها رو می‌ده) تا چند اینستنسِ همزمان، پاداش رو دوبار ندن."""

import asyncio
from typing import Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from config import log, TERR_TRIBUTE, WEEKLY_TITHE_ABOVE, WEEKLY_TITHE_PCT
from database import store
from economy import burn
from leaderboard import group_score
from ui import panel
from utils import esc, week_key


_bot = None


async def _announce_top_group():
    """🏆 اعلام هفتگیِ «قوی‌ترین گروه» تو گروه‌های برتر (فقط پردازشی که هفته رو ادعا کرده صداش می‌زنه)."""
    if _bot is None:
        return
    groups = await store.groups.find({}).sort("activity", -1).limit(20).to_list(20)
    scored = sorted([await group_score(g["chat_id"], g) for g in groups], key=lambda x: -x["score"])
    if not scored:
        return
    top = scored[0]
    await store.meta.update_one({"_id": "week"}, {"$set": {"top_group": {"chat_id": top["chat_id"], "title": top["title"], "score": top["score"]}}})
    for i, sc in enumerate(scored[:10]):
        lines = [f"👑 قوی‌ترین گروهِ هفته: <b>{esc(top['title'])}</b> — ⚡{top['score']}",
                 f"📍 جایگاه گروه شما: <b>#{i + 1}</b> — ⚡{sc['score']}"]
        if i > 0:
            lines.append(f"🔥 تا صدرنشین فقط {max(top['score'] - sc['score'], 0)} امتیاز فاصله دارید؛ دوئل، جنگ و ماجراجویی یادتون نره!")
        else:
            lines.append("🏆 همه‌ی ایسکا الان اسم شما رو می‌دونه. ازش دفاع کنید!")
        try:
            await _bot.send_message(sc["chat_id"], panel("yellow", "🏆", "اعلامیه‌ی هفتگیِ ایزدبانو", lines, "💅 «لیدربرد کامل: بنویسید «لیدربرد».»"))
        except Exception:
            log.info("weekly announce skipped for %s", sc["chat_id"])
        await asyncio.sleep(0.1)


async def weekly_loop(bot):
    """هر نیم‌ساعت چک می‌کنه هفته عوض شده یا نه (قبلاً فقط با فعالیت گیلد چک می‌شد)."""
    global _bot
    _bot = bot
    while True:
        try:
            await ensure_week()
        except Exception:
            log.exception("weekly loop failed")
        await asyncio.sleep(1800)


async def _weekly_rollover(old_meta: Optional[dict], wk: str) -> dict:
    king = old_meta.get("king") if old_meta else None
    top = await store.guilds.find({"week_pts": {"$gt": 0}}).sort("week_pts", -1).limit(1).to_list(1)
    if top:
        g = top[0]
        leader = await store.get(g["owner_id"])
        king = {
            "guild": g["name"], "leader_id": g["owner_id"], "pts": g.get("week_pts", 0),
            "leader_name": (leader or {}).get("first_name") or "ناشناس",
            "week": (old_meta or {}).get("key") or wk,
        }
        await store.users.update_one(
            {"user_id": g["owner_id"]},
            {"$addToSet": {"titles": "👑 پادشاهِ هفته‌ی ایسکا"}, "$inc": {"gold": 200}},
        )
    # 👑 خراجِ قلمروها: هر قلمروی تحت کنترل، هفتگی به «خزانه‌ی گیلدِ مالک» (نه مستقیم به جیبِ اعضا) واریز میشه
    async for t in store.territories.find({"owner": {"$ne": None}}, {"owner": 1}):
        await store.guilds.update_one({"name": t["owner"]}, {"$inc": {"treasury": TERR_TRIBUTE}})
    await store.guilds.update_many({}, {"$set": {"week_pts": 0}})
    # 🕯 عُشرِ ایزدبانو: فقط روی بخشِ بالای آستانه (جلوگیری از انباشتِ بی‌پایان؛ ۰ = خاموش)
    if WEEKLY_TITHE_PCT > 0 and WEEKLY_TITHE_ABOVE > 0:
        try:
            tithe = {"$toInt": {"$floor": {"$multiply": [{"$subtract": ["$gold", WEEKLY_TITHE_ABOVE]}, WEEKLY_TITHE_PCT / 100]}}}
            agg = await store.users.aggregate([
                {"$match": {"gold": {"$gt": WEEKLY_TITHE_ABOVE}}},
                {"$group": {"_id": None, "t": {"$sum": tithe}}},
            ]).to_list(1)
            await store.users.update_many({"gold": {"$gt": WEEKLY_TITHE_ABOVE}}, [{"$set": {"gold": {"$subtract": ["$gold", tithe]}}}])
            if agg:
                await burn(int(agg[0]["t"]), "tithe")
        except Exception:
            log.exception("weekly tithe failed")
    await store.meta.update_one({"_id": "week"}, {"$set": {"king": king}})
    if old_meta:     # اولین دیپلوی (بدون هفته‌ی قبل) اعلامیه نمیده
        try:
            await _announce_top_group()
        except Exception:
            log.exception("weekly announce failed")
    return {"key": wk, "king": king}


async def ensure_week() -> dict:
    """اگه هفته عوض شده باشه، پادشاهِ هفته‌ی قبل رو تعیین و امتیازها رو صفر می‌کنه (فقط یک‌بار)."""
    wk = week_key()
    meta = await store.meta.find_one({"_id": "week"})
    if meta and meta.get("key") == wk:
        return meta
    try:
        old = await store.meta.find_one_and_update(
            {"_id": "week", "key": {"$ne": wk}}, {"$set": {"key": wk}},
            upsert=True, return_document=ReturnDocument.BEFORE)
    except DuplicateKeyError:
        # یکی دیگه همین الان ادعا کرد
        return await store.meta.find_one({"_id": "week"}) or {"key": wk, "king": None}
    return await _weekly_rollover(old, wk)


async def add_guild_pts(guild_name: Optional[str], pts: int):
    if not guild_name or pts <= 0:
        return
    await ensure_week()
    await store.guilds.update_one({"name": guild_name}, {"$inc": {"week_pts": pts}})
