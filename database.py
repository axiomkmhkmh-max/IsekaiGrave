"""اتصال به MongoDB: کلاس Store و کالکشن‌ها و ایندکس‌ها."""

from typing import Optional

from aiogram.types import User

from config import START_GOLD
from utils import utcnow


class Store:
    def __init__(self, db=None):
        if db is not None:
            self.bind(db)

    def bind(self, db):
        """وصل کردن Store به دیتابیس (بعد از ساخت اتصال Mongo در main.py)."""
        self.users = db["users"]
        self.offers = db["offers"]
        self.guilds = db["guilds"]
        self.groups = db["groups"]
        self.duels = db["duels"]
        self.meta = db["meta"]
        self.proposals = db["proposals"]
        self.drops = db["drops"]
        self.raids = db["raids"]
        self.territories = db["territories"]

    async def ensure_indexes(self):
        await self.users.create_index("user_id", unique=True)
        await self.users.create_index("username_lower")
        await self.users.create_index("chats")
        await self.users.create_index("guild")
        await self.offers.create_index([("chat_id", 1), ("status", 1)])
        await self.guilds.create_index("name_lower", unique=True)
        await self.groups.create_index("chat_id", unique=True)
        await self.duels.create_index([("chat_id", 1), ("status", 1)])
        await self.proposals.create_index([("to", 1), ("status", 1)])
        await self.drops.create_index([("chat_id", 1), ("status", 1)])
        await self.raids.create_index([("chat_id", 1), ("status", 1)])
        await self.territories.create_index("key", unique=True)
        # کاربرهای قدیمی (قبل از سیستم ثبت‌نام) رو خودکار «ثبت‌شده» حساب کن
        await self.users.update_many({"registered": {"$exists": False}}, {"$set": {"registered": True, "cls": None}})

    async def touch(self, u: User) -> bool:
        res = await self.users.update_one(
            {"user_id": u.id},
            {
                "$set": {
                    "first_name": u.full_name,
                    "username": u.username,
                    "username_lower": (u.username or "").lower() or None,
                    "last_seen": utcnow(),
                },
                "$setOnInsert": {
                    "death_count": 0, "survival_rate": 100, "form": None, "cheat_skill": None,
                    "world": None, "status": "انسان معمولی (فعلاً)", "titles": [], "past_forms": [],
                    "curses_received": 0, "blessings_received": 0, "forced_count": 0,
                    "executions_ordered": 0, "referrals_available": 0, "referrals_total": 0,
                    "inventory": [], "opted_out": False, "created_at": utcnow(),
                    "gold": START_GOLD, "xp": 0, "level": 1, "location": "city",
                    "guild": None, "wins": 0, "losses": 0, "trips": 0,
                    "quest": None, "pending_trade": None, "last_wheel_at": None, "chats": [],
                    "registered": False, "cls": None, "pact": None, "spouse": None, "spouse_name": None,
                    "banned": False, "quests": None,
                },
            },
            upsert=True,
        )
        return res.upserted_id is not None

    async def get(self, uid: int) -> Optional[dict]:
        return await self.users.find_one({"user_id": uid})


# نمونه‌ی مشترکِ Store؛ همه‌ی فایل‌ها همین رو import می‌کنن و main.py بهش دیتابیس رو وصل می‌کنه.
store = Store()
