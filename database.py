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
        self.listings = db["listings"]      # 🪦 بازار روح
        self.ledger = db["ledger"]          # دفتر تراکنش‌های مهمِ GS
        self.battles = db["battles"]        # ⚔️ نبردهای تاکتیکی (دوئل)
        self.sieges = db["sieges"]          # 🏰 محاصره‌ها
        self.wnpcs = db["wnpcs"]            # 🌍 NPCهای زنده (حافظه، روابط، مکان، اهداف)
        self.wevents = db["wevents"]        # 🌍 رویدادهای جهان + تاریخچه
        self.chronicle = db["world_chronicle"]  # 📜 تاریخچه‌ی پایدار و سراسری جهان
        self.bounties = db["bounties"]      # 🎯 جایزه‌ی سر (skirmish.py)
        self.clashes = db["clashes"]        # 🏟 برخوردهای ژستی، تمرین‌ها و شرط‌بندی‌ها (arena.py)
        self.rrpg = db["rrpg"]              # 🎭 Reply-RPG: هیولای زنجیره‌ای، دوئلِ خیابانی، کمین، طلسم، سیاه‌چال (reply_rpg.py)
        self.rgames = db["rgames"]          # 🎭 بازی‌های باشگاهِ ریپلای: تاس، هفت‌تیر، بلوف (reply_games.py)

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
        await self.listings.create_index([("status", 1), ("created_at", -1)])
        await self.listings.create_index([("seller", 1), ("status", 1)])
        await self.listings.create_index([("buyer", 1), ("status", 1)])
        await self.ledger.create_index([("uid", 1), ("at", -1)])
        await self.battles.create_index([("status", 1), ("uids", 1)])
        await self.sieges.create_index([("status", 1), ("ends_at", 1)])
        # حداکثر یه محاصره‌ی بازِ همزمان برای هر قلمرو
        await self.sieges.create_index("key", unique=True, partialFilterExpression={"status": "open"},
                                       name="one_open_siege_per_territory")
        await self.wnpcs.create_index("id", unique=True)
        await self.bounties.create_index([("target", 1), ("status", 1)])
        await self.bounties.create_index([("status", 1), ("expires_at", 1)])
        await self.clashes.create_index([("kind", 1), ("status", 1), ("uids", 1)])
        await self.clashes.create_index("created_at", expireAfterSeconds=14 * 86400, name="clashes_ttl")
        await self.rgames.create_index([("uids", 1), ("status", 1)])
        await self.rgames.create_index("created_at", expireAfterSeconds=7 * 86400, name="rgames_ttl")
        await self.rrpg.create_index([("chat_id", 1), ("anchors", 1)])
        await self.rrpg.create_index([("kind", 1), ("status", 1), ("chat_id", 1)])
        await self.rrpg.create_index([("kind", 1), ("uids", 1), ("status", 1)])
        await self.rrpg.create_index("created_at", expireAfterSeconds=7 * 86400, name="rrpg_ttl")
        await self.users.create_index([("rg_best_ms", 1)], sparse=True)
        await self.users.create_index([("sk_rp_wk", 1), ("sk_rp_w", -1)])
        await self.users.create_index([("sk_rp", -1)])
        await self.users.create_index([("rr_streak_day", 1), ("rr_streak", -1)], sparse=True)   # 🔥 لیدربوردِ پشتکار
        await self.users.create_index([("rr_duel_wk", 1), ("rr_duel_wkw", -1)], sparse=True)    # 🎤 کریِ هفته
        await self.wevents.create_index("id", unique=True)
        # Normalize legacy worlds that may already have spawned one boss per region.
        # Keep the oldest active encounter and archive the extras instead of deleting them.
        active_bosses = await self.wevents.find({"type": "world_boss", "status": "active"}).sort("started", 1).to_list(100)
        for extra_boss in active_bosses[1:]:
            await self.wevents.update_one(
                {"id": extra_boss["id"], "status": "active"},
                {"$set": {"status": "failed", "resolved_at": utcnow(), "legacy_duplicate": True},
                 "$push": {"history": {"text": "برای یکپارچه‌سازی جهان، این برخورد تکراری بایگانی شد."}}},
            )
        # One active world boss across every region and Telegram chat.
        await self.wevents.create_index("type", unique=True,
            partialFilterExpression={"type": "world_boss", "status": "active"},
            name="one_active_global_world_boss")
        await self.chronicle.create_index("event_id", unique=True)
        await self.chronicle.create_index([("occurred_at", -1)])
        await self.chronicle.create_index([("players", 1), ("occurred_at", -1)])
        await self.chronicle.create_index([("guilds", 1), ("occurred_at", -1)])
        await self.chronicle.create_index([("region", 1), ("occurred_at", -1)])
        await self.wevents.create_index([("status", 1), ("region", 1)])
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
                    "banned": False, "quests": None, "equip": None, "reborn": 0,
                },
            },
            upsert=True,
        )
        return res.upserted_id is not None

    async def get(self, uid: int) -> Optional[dict]:
        return await self.users.find_one({"user_id": uid})


# نمونه‌ی مشترکِ Store؛ همه‌ی فایل‌ها همین رو import می‌کنن و main.py بهش دیتابیس رو وصل می‌کنه.
store = Store()
