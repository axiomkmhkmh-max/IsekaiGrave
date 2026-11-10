"""Shared-world foundation: canonical identity, durable chronicle and world status.

MongoDB is the source of truth. Telegram chat IDs are presentation gateways only;
player identity is always Telegram user_id.
"""
from typing import Iterable, Optional
import hashlib
import logging

from database import store
from utils import utcnow, esc
from ui import panel

log = logging.getLogger("isekai-grave.world")


def canonical_player_id(telegram_user_id: int) -> int:
    """Return the canonical global character key."""
    return int(telegram_user_id)


def _event_key(event_type: str, source_id: str) -> str:
    raw = f"{event_type}:{source_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


async def record_event(event_type: str, description: str, *, source_id: str,
                       players: Optional[Iterable[int]] = None,
                       guilds: Optional[Iterable[str]] = None,
                       region: Optional[str] = None, importance: int = 1,
                       consequence: Optional[dict] = None,
                       occurred_at=None) -> bool:
    """Append a chronicle entry once. Duplicate retries are harmless."""
    doc = {
        "event_id": _event_key(event_type, str(source_id)),
        "event_type": str(event_type)[:48],
        "source_id": str(source_id)[:128],
        "occurred_at": occurred_at or utcnow(),
        "players": sorted({int(x) for x in (players or [])}),
        "guilds": sorted({str(x)[:64] for x in (guilds or []) if x}),
        "region": str(region)[:48] if region else None,
        "description": str(description)[:500],
        "importance": max(1, min(5, int(importance))),
        "consequence": consequence or {},
    }
    try:
        await store.chronicle.insert_one(doc)
        return True
    except Exception as exc:
        # Duplicate event IDs mean this event was already recorded.
        if exc.__class__.__name__ == "DuplicateKeyError":
            return False
        log.exception("chronicle insert failed")
        return False


async def world_status() -> dict:
    w = await store.meta.find_one({"_id": "world"}) or {}
    active = await store.wevents.count_documents({"status": "active"})
    players = await store.users.count_documents({"registered": True})
    guilds = await store.guilds.count_documents({})
    return {
        "tick": int(w.get("tick_n", 0)),
        "regions": len(w.get("regions") or {}),
        "active_events": active,
        "players": players,
        "guilds": guilds,
        "epoch": w.get("epoch"),
    }


async def chronicle_entries(uid: Optional[int] = None, limit: int = 8) -> list:
    query = {"players": int(uid)} if uid is not None else {}
    return await store.chronicle.find(query).sort("occurred_at", -1).limit(max(1, min(20, limit))).to_list(max(1, min(20, limit)))


async def show_world_status(message):
    s = await world_status()
    lines = [
        f"👥 قهرمانان ثبت‌شده: <b>{s['players']:,}</b>",
        f"🛡 گیلدهای ثبت‌شده: <b>{s['guilds']:,}</b>",
        f"🗺 مناطق شناخته‌شده: <b>{s['regions']}</b>",
        f"🔥 رویدادهای فعال: <b>{s['active_events']}</b>",
        f"⏱ شماره‌ی تیک جهان: <b>{s['tick']:,}</b>",
        "🌐 هویت بازیکن با شناسه‌ی تلگرام سراسری است؛ گروه‌ها فقط درگاه‌های ارتباطی‌اند.",
    ]
    await message.reply(panel("purple", "🌍", "وضعیت جهان ایسکا", lines))


async def show_chronicle(message, personal: bool = False):
    uid = canonical_player_id(message.from_user.id) if personal else None
    entries = await chronicle_entries(uid, 10)
    title = "📜 تاریخچه‌ی شخصی تو" if personal else "📜 سال‌نامه‌ی جهان"
    if not entries:
        body = "هنوز رویداد مهمی در این بخش ثبت نشده."
    else:
        body = "\\n".join(
            f"• <b>{esc(e.get('description', 'رویداد ثبت‌شده'))}</b>\n"
            f"  <i>{e.get('occurred_at').strftime('%Y-%m-%d %H:%M UTC') if e.get('occurred_at') else 'زمان نامشخص'}</i>"
            + (f" · 🗺 {esc(e['region'])}" if e.get("region") else "")
            for e in entries
        )
    await message.reply(panel("blue", "📜", title, [body], "رویدادها از فعالیت‌های واقعی ثبت‌شده در دیتابیس ساخته می‌شوند."))


async def show_world_news(message):
    """Newspaper view backed exclusively by recorded world events."""
    entries = await chronicle_entries(limit=8)
    if not entries:
        body = "امروز هنوز خبر مهمی در سال‌نامه ثبت نشده."
    else:
        body = "\\n".join(
            f"📰 <b>{esc(e.get('description', 'خبر جهان'))}</b>"
            + (f" · 🗺 {esc(e['region'])}" if e.get("region") else "")
            for e in entries
        )
    await message.reply(panel("purple", "🗞", "روزنامه‌ی ایسکا", [body],
                              "این خبرها مستقیماً از رویدادهای ثبت‌شده‌ی جهان ساخته شده‌اند."))
