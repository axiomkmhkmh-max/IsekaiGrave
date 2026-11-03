"""امتیاز هفتگی گیلدها و پادشاه هفته."""

from typing import Optional

from database import store
from utils import week_key


async def ensure_week() -> dict:
    """اگه هفته عوض شده باشه، پادشاهِ هفته‌ی قبل رو تعیین و امتیازها رو صفر می‌کنه."""
    wk = week_key()
    meta = await store.meta.find_one({"_id": "week"})
    if meta and meta.get("key") == wk:
        return meta
    king = meta.get("king") if meta else None
    top = await store.guilds.find({"week_pts": {"$gt": 0}}).sort("week_pts", -1).limit(1).to_list(1)
    if top:
        g = top[0]
        leader = await store.get(g["owner_id"])
        king = {
            "guild": g["name"], "leader_id": g["owner_id"], "pts": g.get("week_pts", 0),
            "leader_name": (leader or {}).get("first_name") or "ناشناس",
            "week": (meta or {}).get("key") or wk,
        }
        await store.users.update_one(
            {"user_id": g["owner_id"]},
            {"$addToSet": {"titles": "👑 پادشاهِ هفته‌ی ایسکا"}, "$inc": {"gold": 200}},
        )
    await store.guilds.update_many({}, {"$set": {"week_pts": 0}})
    new = {"key": wk, "king": king}
    await store.meta.update_one({"_id": "week"}, {"$set": new}, upsert=True)
    return new


async def add_guild_pts(guild_name: Optional[str], pts: int):
    if not guild_name or pts <= 0:
        return
    await ensure_week()
    await store.guilds.update_one({"name": guild_name}, {"$inc": {"week_pts": pts}})
