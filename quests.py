"""ماموریت‌های روزانه و هفتگی."""

import random
from typing import Optional

from content import DAILY_POOL, WEEKLY_POOL
from database import store
from players import grant
from ui import btn, kb, panel
from utils import day_key, esc, week_key


def make_quest(item: tuple) -> dict:
    k, t, need, g, x = item
    return {"k": k, "t": t.replace("{n}", str(need)), "need": need, "have": 0, "gold": g, "xp": x, "done": False}


async def ensure_quests(uid: int, doc: Optional[dict] = None) -> dict:
    doc = doc or await store.get(uid)
    q = dict(doc.get("quests") or {})
    changed = False
    if q.get("day") != day_key():
        pool = DAILY_POOL[:]
        random.shuffle(pool)
        picks, kinds = [], set()
        for it in pool:
            if it[0] not in kinds:
                kinds.add(it[0])
                picks.append(it)
            if len(picks) == 3:
                break
        q["day"] = day_key()
        q["daily"] = [make_quest(p) for p in picks]
        changed = True
    if q.get("week") != week_key():
        q["week"] = week_key()
        q["weekly"] = [make_quest(random.choice(WEEKLY_POOL))]
        changed = True
    if changed:
        await store.users.update_one({"user_id": uid}, {"$set": {"quests": q}})
    return q


async def quest_progress(m, kind: str, n: int = 1, uid: Optional[int] = None):
    """پیشرفت ماموریت‌ها رو ثبت می‌کنه؛ اگه ماموریتی کامل شد، جایزه + پیام."""
    uid = uid or m.from_user.id
    doc = await store.get(uid)
    if not doc or not doc.get("registered"):
        return
    q = await ensure_quests(uid, doc)
    lines, gold, xp = [], 0, 0
    for bucket in ("daily", "weekly"):
        for it in q.get(bucket, []):
            if it["k"] == kind and not it["done"]:
                it["have"] = min(it["need"], it["have"] + n)
                if it["have"] >= it["need"]:
                    it["done"] = True
                    gold += it["gold"]
                    xp += it["xp"]
                    tag = "هفتگی" if bucket == "weekly" else "روزانه"
                    lines.append(f"✅ ماموریت {tag}: {esc(it['t'])}\n      🪙 +{it['gold']}  ⭐ +{it['xp']}")
    await store.users.update_one({"user_id": uid}, {"$set": {"quests": q}})
    if lines:
        await grant(uid, gold=gold, xp=xp)
        name = esc(doc.get("first_name") or "قهرمان")
        await m.reply(panel("green", "🎯", f"ماموریت انجام شد — {name}", lines,
                            "💅 <i>«ماموریتتو انجام دادی؟ …باشه، قبول. دفعه‌ی بعد سریع‌تر؛ من وقت ندارم.»</i>"),
                      reply_markup=kb([btn("📜 ماموریت‌های من", f"m:quest:{uid}", "blue")]))


async def do_quests(m):
    uid = m.from_user.id
    q = await ensure_quests(uid)

    def row(it: dict) -> str:
        mark = "✅" if it["done"] else "⏳"
        return f"{mark} {esc(it['t'])}\n      ({it['have']}/{it['need']}) 🪙{it['gold']} ⭐{it['xp']}"

    lines = ["👇 ماموریت‌ها رو انجام بده و طلا و XP بگیر!", "📅 <b>روزانه</b> (ریست ساعت ۰۰ به وقت ایران)"] + [row(i) for i in q.get("daily", [])]
    lines += ["┈┈┈┈┈┈┈┈┈┈", "🗓 <b>هفتگی</b>"] + [row(i) for i in q.get("weekly", [])]
    alld = all(i["done"] for i in q.get("daily", []))
    foot = "🎉 همه‌ی ماموریت‌های امروز رو انجام دادی! آفرین، فردا دوباره بیا. 🙂" if alld else "💅 <i>«ماموریت‌هات رو تموم کن. هر ماموریتِ نیمه‌کاره توهین به منه.»</i>"
    await m.reply(panel("blue", "📜", "دفتر ماموریت‌ها", lines, foot),
                  reply_markup=kb([btn("🌍 ماجراجویی", f"m:go:{uid}", "green"), btn("🌙 منو", f"m:main:{uid}", "blue")]))
