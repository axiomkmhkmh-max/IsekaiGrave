"""اقتصادِ GRAVE SIGIL (GS): سقف درآمد، دفتر تراکنش، سوختن (sink)، مزایای قلمرو و ابزار امنِ کوله‌پشتی.

نکته: برای حفظ موجودیِ بازیکن‌ها، فیلد دیتابیس همچنان «gold» ـه و فقط نمایش GS شده؛ پس مهاجرتی لازم نیست."""

import asyncio
from typing import Callable, Optional

from config import (
    GS, GS_DAILY_HARD_CAP, GS_DAILY_SOFT_CAP, GS_SOFT_RATE, log,
)
from database import store
from rules import capped_amount
from utils import day_key, utcnow


def fmt(n: int) -> str:
    return f"{int(n):,} {GS}"


# ───────────────────────────── 🔒 قفل‌های درون‌پردازشی ─────────────────────────────
_locks: dict = {}


def ulock(uid: int) -> asyncio.Lock:
    """قفلِ هر بازیکن: دو کلیکِ همزمانِ یک نفر پشت سر هم اجرا میشن (امنیت اصلی ولی با شرط‌های اتمیک دیتابیسه)."""
    lk = _locks.get(uid)
    if lk is None:
        if len(_locks) > 5000:
            _locks.clear()
        lk = _locks[uid] = asyncio.Lock()
    return lk


# ───────────────────────────── 📒 دفتر و سوختن ─────────────────────────────
async def log_tx(uid: int, delta: int, reason: str, ref: Optional[str] = None):
    try:
        await store.ledger.insert_one({"uid": uid, "delta": int(delta), "reason": reason, "ref": ref, "at": utcnow()})
    except Exception:
        log.exception("ledger write failed")


async def burn(amount: int, reason: str = ""):
    """GS که از چرخه خارج شد (کارمزد، هزینه‌ی کوره، …) — برای آمار ادمین."""
    if amount <= 0:
        return
    try:
        await store.meta.update_one({"_id": "economy"}, {"$inc": {"burned": int(amount), f"burned_by.{reason or 'other'}": int(amount)}}, upsert=True)
    except Exception:
        log.exception("burn stat failed")


async def debit(uid: int, amount: int, reason: str = "", burn_it: bool = True) -> bool:
    """کم‌کردنِ اتمیک؛ هرگز منفی نمیشه. موفق = True."""
    if amount <= 0:
        return True
    res = await store.users.update_one({"user_id": uid, "gold": {"$gte": amount}}, {"$inc": {"gold": -amount}})
    if res.modified_count:
        await log_tx(uid, -amount, reason)
        if burn_it:
            await burn(amount, reason)
        return True
    return False


async def credit(uid: int, amount: int, reason: str = "") -> None:
    """واریزِ مستقیم (بدون سقف روزانه) — برای بازگشت پول و انتقال بین بازیکن‌ها."""
    if amount > 0:
        await store.users.update_one({"user_id": uid}, {"$inc": {"gold": amount}})
        await log_tx(uid, amount, reason)


# ───────────────────────────── 🧢 سقف درآمد روزانه ─────────────────────────────
async def cap_income(uid: int, amount: int) -> int:
    """درآمدِ «تولیدشده توسط بازی» (ماجراجویی، باس، ماموریت…) رو با سقفِ روزانه تعدیل می‌کنه.
    (انتقال بین بازیکن‌ها و بازار روح مشمول سقف نیست؛ چون GS جدیدی ساخته نمیشه.)"""
    if amount <= 0:
        return amount
    today = day_key()
    await store.users.update_one({"user_id": uid, "gs_day": {"$ne": today}}, {"$set": {"gs_day": today, "gs_earned": 0}})
    doc = await store.users.find_one({"user_id": uid}, {"gs_earned": 1})
    earned = int((doc or {}).get("gs_earned", 0))
    return capped_amount(earned, amount, GS_DAILY_SOFT_CAP, GS_DAILY_HARD_CAP, GS_SOFT_RATE)


# ───────────────────────────── 👑 مزایای قلمرو ─────────────────────────────
async def terr_perks(doc: Optional[dict]) -> set:
    """کلیدِ قلمروهایی که گیلدِ بازیکن مالکشونه (هر کدوم یه مزیت می‌ده)."""
    g = (doc or {}).get("guild")
    if not g:
        return set()
    return {t["key"] async for t in store.territories.find({"owner": g}, {"key": 1})}


# ───────────────────────────── 🎒 تغییرِ امنِ کوله‌پشتی (CAS) ─────────────────────────────
async def inv_update(uid: int, mutate: Callable, filt: Optional[dict] = None, upd: Optional[dict] = None,
                     upd_fn: Optional[Callable] = None, guard: tuple = (), tries: int = 4) -> Optional[dict]:
    """کوله‌پشتی رو «اتمیک» عوض می‌کنه: آرایه‌ی فعلی خونده میشه، mutate(inv, doc) آرایه‌ی جدید رو می‌سازه
    (یا None برای انصراف) و آپدیت فقط وقتی اعمال میشه که کوله‌پشتی هنوز دقیقاً همون آرایه باشه.
    filt/upd شرط و تغییرِ اضافه (مثلاً gold) رو توی همون آپدیتِ تک‌سندی می‌ذارن؛ پس کم‌کردنِ GS و دادنِ آیتم
    یا همزمان انجام میشن یا اصلاً. upd_fn(doc) بعد از mutate صدا زده میشه و آپدیتِ وابسته به نتیجه رو برمی‌گردونه.
    guard = اسم فیلدهایی (مثل equip) که باید بین خوندن و نوشتن دست‌نخورده بمونن. برمی‌گردونه: سندِ قبل از تغییر، یا None."""
    for _ in range(tries):
        doc = await store.get(uid)
        if not doc:
            return None
        old = list(doc.get("inventory") or [])
        new = mutate(list(old), doc)
        if new is None:
            return None
        q = {"user_id": uid, "inventory": old}
        for f in guard:
            q[f] = doc.get(f)
        if filt:
            q.update(filt)
        extra = dict(upd or {})
        if upd_fn:
            for k, v in (upd_fn(doc) or {}).items():
                extra.setdefault(k, {}).update(v)
        u = {k: dict(v) for k, v in extra.items()}
        u.setdefault("$set", {})["inventory"] = new
        res = await store.users.update_one(q, u)
        if res.matched_count:
            return doc
        # یا کوله‌پشتی بین خوندن و نوشتن عوض شد (دوباره امتحان)، یا شرطِ filt برقرار نیست
        again = await store.users.find_one({"user_id": uid, **(filt or {})}, {"_id": 1})
        if not again:
            return None
    return None
