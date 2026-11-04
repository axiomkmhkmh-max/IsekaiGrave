"""منطق بازیکن: لقب‌ها، بازتولد (مرگ)، بقا، GS/XP/آیتم و بونوس کلاس‌ها."""

import random
from typing import Optional

from pymongo import ReturnDocument

from content import CHEATS, DEATH_TITLES, FORM_TITLE, FORMS, WORLDS
from database import store
from economy import burn, cap_income
from utils import utcnow


def status_for(rate: int) -> str:
    if rate < 8:
        return "در حال احتضارِ دائمی"
    if rate < 16:
        return "زنده‌ی معجزه‌آسا (به لطف باگ)"
    if rate < 26:
        return "زنده‌ی بدشانس"
    return "نیمه‌زنده، نیمه‌اسلایم"


def earned_titles(doc: dict) -> list:
    t = []
    dc = doc.get("death_count", 0)
    t += [title for th, title in DEATH_TITLES if dc >= th]
    t += [FORM_TITLE[f] for f in doc.get("past_forms", []) if f in FORM_TITLE]
    if doc.get("curses_received", 0) >= 3:
        t.append("نفرین‌خورِ حرفه‌ای")
    if doc.get("blessings_received", 0) >= 3:
        t.append("قدیسِ مشکوک")
    if doc.get("forced_count", 0) >= 2:
        t.append("قربانیِ مورد علاقه‌ی ایزدبانو")
    if doc.get("executions_ordered", 0) >= 3:
        t.append("دستیار جلاد")
    if doc.get("referrals_total", 0) >= 3:
        t.append("دلالِ برده‌های ایزدبانو")
    if doc.get("wins", 0) >= 5:
        t.append("دوئل‌بازِ حرفه‌ای")
    if doc.get("trips", 0) >= 20:
        t.append("مسافرِ بی‌سرانجام")
    if doc.get("level", 1) >= 5:
        t.append("قهرمانِ نیم‌بند")
    if doc.get("mx_sales", 0) >= 5:
        t.append("تاجرِ بازار روح")
    return t


async def refresh_titles(doc: dict) -> tuple:
    have = set(doc.get("titles", []))
    new = []
    for title in earned_titles(doc):
        if title not in have and title not in new:
            new.append(title)
    if new:
        doc = await store.users.find_one_and_update(
            {"user_id": doc["user_id"]},
            {"$push": {"titles": {"$each": new}}},
            return_document=ReturnDocument.AFTER,
        )
    return doc, new


async def reincarnate(uid: int, forced: bool = False, chat_id: Optional[int] = None) -> tuple:
    form, _ = random.choice(FORMS)
    rate = random.randint(1, 37)
    inc = {"death_count": 1}
    if forced:
        inc["forced_count"] = 1
    doc = await store.users.find_one_and_update(
        {"user_id": uid},
        {
            "$inc": inc,
            "$set": {
                "form": form, "cheat_skill": random.choice(CHEATS), "world": random.choice(WORLDS),
                "survival_rate": rate, "status": status_for(rate), "last_death_at": utcnow(),
                "reborn": 3,   # 🕯 هاله‌ی بازتولد: ۳ نبرد بعدی با ۲ روحِ شارژشده شروع میشه
            },
            "$push": {"past_forms": {"$each": [form], "$slice": -30}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if chat_id:
        await store.groups.update_one({"chat_id": chat_id}, {"$inc": {"deaths": 1}}, upsert=True)
    res = await refresh_titles(doc)
    # 💍 پیوند ایسکایی: مرگ یکی، دیگری رو هم زخمی می‌کنه
    sp = doc.get("spouse")
    if sp:
        sdoc = await adjust_survival(sp, -6)
        await store.users.update_one({"user_id": sp, "gold": {"$gte": 10}}, {"$inc": {"gold": -10}})
        if sdoc:
            res[0]["_bond"] = sdoc.get("first_name") or "همسرش"
    return res


async def adjust_survival(uid: int, delta: int, counter: Optional[str] = None) -> dict:
    stage = {"survival_rate": {"$min": [100, {"$max": [1, {"$add": [{"$ifNull": ["$survival_rate", 100]}, delta]}]}]}}
    if counter:
        stage[counter] = {"$add": [{"$ifNull": ["$" + counter, 0]}, 1]}
    return await store.users.find_one_and_update(
        {"user_id": uid}, [{"$set": stage}], return_document=ReturnDocument.AFTER
    )


async def grant(uid: int, gold: int = 0, xp: int = 0, item: Optional[str] = None,
                survival: int = 0, counters: Optional[dict] = None) -> tuple:
    """جایزه/جریمه‌ی ترکیبی؛ سطح رو هم خودکار آپدیت می‌کنه. (doc, leveled_up) برمی‌گردونه."""
    upd: dict = {}
    inc: dict = dict(counters or {})
    if gold:
        if gold > 0:
            inc["gs_earned"] = gold                       # شمارنده‌ی درآمدِ خامِ امروز (برای سقف روزانه)
            gold = await cap_income(uid, gold)            # GS تولیدشده‌ی بازی سقف روزانه داره
        inc["gold"] = gold
    if xp:
        if xp > 0:
            who = await store.users.find_one({"user_id": uid}, {"cls": 1})
            if who and who.get("cls") == "mage":
                xp = int(xp * 1.2)  # 🔮 جادوگر: ۲۰٪ XP بیشتر
        inc["xp"] = xp
    if inc:
        upd["$inc"] = inc
    if item:
        upd["$push"] = {"inventory": {"$each": [item], "$slice": -15}}
    doc = None
    if upd:
        doc = await store.users.find_one_and_update({"user_id": uid}, upd, return_document=ReturnDocument.AFTER)
    if survival:
        doc = await adjust_survival(uid, survival)
    if doc is None:
        doc = await store.get(uid)
    lvl = 1 + int(doc.get("xp", 0)) // 100
    leveled = lvl > int(doc.get("level", 1))
    if leveled:
        doc = await store.users.find_one_and_update(
            {"user_id": uid}, {"$set": {"level": lvl}}, return_document=ReturnDocument.AFTER
        )
    return doc, leveled


async def spend(uid: int, amount: int) -> bool:
    res = await store.users.update_one({"user_id": uid, "gold": {"$gte": amount}}, {"$inc": {"gold": -amount}})
    if res.modified_count:
        await burn(amount, "spend")     # خرجِ NPC/گیلد = GS که از چرخه خارج میشه
    return res.modified_count > 0


def cls_is(doc: Optional[dict], key: str) -> bool:
    return bool(doc) and doc.get("cls") == key


def gold_bonus(doc: Optional[dict], g: int) -> int:
    return int(g * 1.25) if cls_is(doc, "rogue") else g       # 🗡 دزد: ۲۵٪ GS بیشتر


def heal_bonus(doc: Optional[dict], h: int) -> int:
    return int(h * 1.3) if cls_is(doc, "priest") else h        # ✨ کشیش: ۳۰٪ شفای بیشتر
