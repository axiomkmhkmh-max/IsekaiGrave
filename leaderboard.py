"""رتبه‌بندی و لیدربرد گروه."""

from aiogram.types import Message

from database import store
from ui import panel, say
from utils import esc, is_group


async def group_score(chat_id: int, g: dict) -> dict:
    pipe = [
        {"$match": {"chats": chat_id}},
        {"$group": {"_id": None, "n": {"$sum": 1}, "p": {"$sum": {"$add": [
            {"$multiply": [{"$ifNull": ["$level", 1]}, 10]}, {"$ifNull": ["$survival_rate", 0]}]}}}},
    ]
    res = await store.users.aggregate(pipe).to_list(1)
    members, power = (res[0]["n"], int(res[0]["p"])) if res else (0, 0)
    score = int(g.get("activity", 0)) + int(g.get("duels", 0)) * 10 + int(g.get("deaths", 0)) * 3 + int(g.get("wars", 0)) * 15 + power
    return {"chat_id": chat_id, "title": g.get("title") or "گروه ناشناس", "score": score,
            "members": members, "duels": g.get("duels", 0), "deaths": g.get("deaths", 0)}


async def do_board(m: Message):
    groups = await store.groups.find({}).sort("activity", -1).limit(20).to_list(20)
    if not groups:
        await say(m, "هنوز هیچ گروهی ثبت نشده. کمی فعالیت کنید تا لیست پر بشه. 📊", "📊", "لیدربرد", "yellow")
        return
    scored = sorted([await group_score(g["chat_id"], g) for g in groups], key=lambda x: -x["score"])
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, s in enumerate(scored[:8]):
        mk = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mk} <b>{esc(s['title'])}</b> — ⚡{s['score']}\n      👥{s['members']} ⚔️{s['duels']} ☠️{s['deaths']}")
    foot = ""
    if is_group(m):
        pos = next((i + 1 for i, s in enumerate(scored) if s["chat_id"] == m.chat.id), None)
        if pos:
            foot = f"📍 جایگاه گروه شما: <b>#{pos}</b>"
    top_g = await store.guilds.find({}).sort("wins", -1).limit(3).to_list(3)
    if top_g:
        lines.append("┈┈┈┈┈┈┈┈┈┈")
        lines.append("🛡 <b>گیلدهای برتر:</b> " + "، ".join(f"{esc(x['name'])} ({x.get('wins', 0)}🏆)" for x in top_g))
    inv = await store.users.find({"referrals_total": {"$gt": 0}, "opted_out": {"$ne": True}}).sort("referrals_total", -1).limit(3).to_list(3)
    if inv:
        lines.append("🔗 <b>برترین سفیرها:</b> " + "، ".join(f"{esc(x.get('first_name') or '؟')} ({x['referrals_total']})" for x in inv))
    await m.reply(panel("yellow", "🏆", "لیدربرد گروه‌ها (جنگ قلمروها)", lines, foot or None))
