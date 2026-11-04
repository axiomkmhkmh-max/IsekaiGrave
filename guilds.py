"""سیستم گیلد: ساخت، پیوستن، ترک، جنگ و دعوت."""

import random
from typing import Optional

from aiogram.types import Message

from datetime import timedelta

from config import FORT_COSTS, GS, GUILD_COST, GUILD_MAX_MEMBERS, GUILD_WAR_COOLDOWN
from database import store
from economy import burn, credit, debit, fmt, log_tx
from players import spend
from quests import quest_progress
from ui import btn, kb, panel, say
from utils import day_key, esc, gid, is_group, utcnow, week_key
from weekly import add_guild_pts


async def guild_power(guild: dict) -> int:
    pipe = [
        {"$match": {"user_id": {"$in": guild["members"]}}},
        {"$group": {"_id": None, "p": {"$sum": {"$add": [
            {"$multiply": [{"$ifNull": ["$level", 1]}, 10]},
            {"$ifNull": ["$survival_rate", 0]},
            {"$multiply": [{"$ifNull": ["$wins", 0]}, 5]},
        ]}}}},
    ]
    res = await store.users.aggregate(pipe).to_list(1)
    return int(res[0]["p"]) if res else 0


def effective_fort(g: dict) -> int:
    """سطحِ دژ فقط تا آخرِ همون هفته معتبره (هزینه‌ی تکرارشونده = مصرفِ GS)."""
    return int(g.get("fort", 0) or 0) if g.get("fort_week") == week_key() else 0


async def guild_income(g_id, amount: int, cap: int = 100) -> int:
    """درآمدِ جنگ به خزانه با سقفِ روزانه برای هر گیلد (جلوگیری از فارمِ گیلدِ جعلی). مقدارِ واقعی رو برمی‌گردونه."""
    today = day_key()
    await store.guilds.update_one({"_id": g_id, "war_day": {"$ne": today}}, {"$set": {"war_day": today, "war_gs": 0}})
    res = await store.guilds.update_one({"_id": g_id, "war_gs": {"$lte": cap - amount}}, {"$inc": {"treasury": amount, "war_gs": amount}})
    return amount if res.modified_count else 0


async def do_guild_create(m: Message, name: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if doc.get("guild"):
        await say(m, f"تو الان عضو گیلد «{esc(doc['guild'])}» هستی. اگه می‌خوای عوض کنی، اول بنویس «ترک گیلد». 🛡", "🛡", "گیلد", "blue")
        return
    if not (2 <= len(name) <= 24):
        await say(m, "اسم گیلد باید بین ۲ تا ۲۴ حرف باشه.", "📛", "گیلد", "blue")
        return
    if not await spend(uid, GUILD_COST):
        await say(m, f"ساخت گیلد {GUILD_COST} GS خرج داره و موجودیت کمه. با ماجراجویی GS جمع کن! 🪙", "🪙", "گیلد", "yellow",
                  kb([btn("🌍 ماجراجویی", f"m:go:{uid}", "green")]))
        return
    try:
        await store.guilds.insert_one({
            "name": name, "name_lower": name.lower(), "owner_id": uid, "members": [uid],
            "home_chat": gid(m), "wins": 0, "losses": 0, "created_at": utcnow(), "last_war_at": None,
        })
    except Exception:
        await store.users.update_one({"user_id": uid}, {"$inc": {"gold": GUILD_COST}})
        await say(m, "این اسم قبلاً ثبت شده. یه اسم دیگه امتحان کن. 😊", "🛡", "گیلد", "blue")
        return
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": name}})
    terr = "این گروه به‌عنوان قلمرو گیلد ثبت شد! 🚩" if is_group(m) else "برای ثبت قلمرو، بهتره تو یه گروه این کار رو بکنی. 🚩"
    await m.reply(panel("purple", "🛡", "گیلد جدید تأسیس شد", [
        f"📛 نام: <b>{esc(name)}</b>", f"👑 رهبر: {esc(m.from_user.full_name)}",
        f"🪙 هزینه: {GUILD_COST} GS", terr,
    ], f"دوستات می‌تونن بنویسن «<b>پیوستن به گیلد {esc(name)}</b>»"))


async def do_guild_join(m: Message, name: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    if doc.get("guild"):
        await say(m, f"تو الان عضو «{esc(doc['guild'])}» هستی. اگه می‌خوای عوض کنی، اول «ترک گیلد» بنویس. 🛡", "🛡", "گیلد", "blue")
        return
    g = await store.guilds.find_one({"name_lower": name.lower()})
    if not g:
        await say(m, "گیلدی با این اسم پیدا نشد. اسمش رو دقیق بنویس. 🔍", "🛡", "گیلد", "blue")
        return
    if len(g["members"]) >= GUILD_MAX_MEMBERS:
        await say(m, "این گیلد پره و جا نداره. یه گیلد دیگه رو امتحان کن. 🚪", "🛡", "گیلد", "blue")
        return
    await store.guilds.update_one({"_id": g["_id"]}, {"$addToSet": {"members": uid}})
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": g["name"]}})
    await m.reply(panel("blue", "🛡", "عضو جدید!", [
        f"{esc(m.from_user.full_name)} به گیلد <b>{esc(g['name'])}</b> پیوست.",
        f"👥 اعضا: {len(g['members']) + 1}",
    ], "💅 <i>«یه سرباز دیگه برای قربانی شدن.»</i>"))


async def do_guild_leave(m: Message):
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await say(m, "تو گیلدی نداری که ازش بری. 🛡", "🛡", "گیلد", "blue")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    await store.users.update_one({"user_id": uid}, {"$set": {"guild": None}})
    if g:
        members = [x for x in g["members"] if x != uid]
        if not members:
            await store.guilds.delete_one({"_id": g["_id"]})
        else:
            await store.guilds.update_one(
                {"_id": g["_id"]},
                {"$set": {"members": members, "owner_id": members[0] if g["owner_id"] == uid else g["owner_id"]}},
            )
    await say(m, "از گیلد خارج شدی. هر وقت خواستی می‌تونی دوباره به یه گیلد بپیوندی. 🚪", "🚪", "ترک گیلد", "blue")


async def do_guild_me(m: Message):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await say(m, "هنوز گیلد نداری. بنویس «<b>ساخت گیلد [نام]</b>» یا «<b>پیوستن به گیلد [نام]</b>». 🛡", "🛡", "گیلد", "blue")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"guild": None}})
        await say(m, "گیلدت منحل شده بود. می‌تونی یه گیلد جدید بسازی. 🪦", "🛡", "گیلد", "blue")
        return
    power = await guild_power(g)
    top = await store.users.find({"user_id": {"$in": g["members"]}}).sort("level", -1).limit(5).to_list(5)
    names = "، ".join(esc(u.get("first_name")) for u in top)
    terr = "—"
    if g.get("home_chat"):
        gr = await store.groups.find_one({"chat_id": g["home_chat"]})
        terr = esc(gr.get("title")) if gr and gr.get("title") else "ثبت‌شده"
    await m.reply(panel("purple", "🛡", f"گیلد {g['name']}", [
        f"👑 رهبر: {esc((await store.get(g['owner_id'])).get('first_name'))}",
        f"👥 اعضا: {len(g['members'])}  |  ⚡ قدرت: <b>{power}</b>",
        f"🚩 قلمرو: {terr}",
        f"⚔️ جنگ‌ها: {g.get('wins', 0)} برد / {g.get('losses', 0)} باخت",
        f"💰 خزانه: <b>{fmt(g.get('treasury', 0))}</b> | 🏯 دژ: سطح {effective_fort(g)}/{len(FORT_COSTS)}",
        f"🌟 برترین‌ها: {names}",
    ], "«اهدا ۵۰» ← واریز به خزانه · «تقویت دژ» ← (رهبر) دفاعِ هفته · خزانه خرجِ محاصره‌ی قلمروها میشه"))


async def do_guild_war(m: Message):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await say(m, "برای جنگ اول باید گیلد داشته باشی. یه گیلد بساز یا به یکی بپیوند. 🛡", "⚔️", "جنگ گیلدها", "red")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    if not g:
        return
    last = g.get("last_war_at")
    if last and (utcnow() - last).total_seconds() < GUILD_WAR_COOLDOWN:
        left = int(GUILD_WAR_COOLDOWN - (utcnow() - last).total_seconds()) // 60 + 1
        await say(m, f"گیلدت هنوز خسته‌ست. حدود {left} دقیقه‌ی دیگه دوباره بجنگین. 🩹", "⚔️", "جنگ گیلدها", "red")
        return
    others = await store.guilds.find({"_id": {"$ne": g["_id"]}}).to_list(50)
    if not others:
        await say(m, "هنوز گیلد دیگه‌ای نیست که باهاش بجنگی. دوستات رو دعوت کن! 😊", "⚔️", "جنگ گیلدها", "red")
        return
    foe = random.choice(others)
    pa, pb = await guild_power(g), await guild_power(foe)
    sa, sb = pa * random.uniform(0.75, 1.25), pb * random.uniform(0.75, 1.25)
    win = sa >= sb
    await store.guilds.update_one({"_id": g["_id"]}, {"$set": {"last_war_at": utcnow()}, "$inc": {"wins" if win else "losses": 1}})
    await store.guilds.update_one({"_id": foe["_id"]}, {"$inc": {"losses" if win else "wins": 1}})
    wg, lg = (g, foe) if win else (foe, g)
    # 🛡 پاداش به «اعضای فعال» (۲۴ ساعت اخیر) فقط XP؛ GS به خزانه‌ی برنده میره و فقط اگه حریف هم‌وزن بوده
    day_ago = utcnow() - timedelta(hours=24)
    await store.users.update_many({"user_id": {"$in": wg["members"]}, "last_seen": {"$gt": day_ago}}, {"$inc": {"xp": 15}})
    await store.users.update_many({"user_id": {"$in": lg["members"]}, "last_seen": {"$gt": day_ago}}, {"$inc": {"xp": 5}})
    worthy = min(pa, pb) >= 0.7 * max(pa, pb) and len(g["members"]) >= 2 and len(foe["members"]) >= 2
    got = await guild_income(wg["_id"], 20) if worthy else 0
    if is_group(m):
        await store.groups.update_one({"chat_id": m.chat.id}, {"$inc": {"wars": 1}}, upsert=True)
    await add_guild_pts(wg["name"], 20)
    await add_guild_pts(lg["name"], 5)
    await m.reply(panel("red", "⚔️", "جنگ گیلدها!", [
        f"🛡 <b>{esc(g['name'])}</b>  ⚡{int(sa)}",
        "      ⚔️ VS ⚔️",
        f"🗡 <b>{esc(foe['name'])}</b>  ⚡{int(sb)}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"🏆 برنده: <b>{esc(wg['name'])}</b> — اعضای فعال ۱۵ XP" + (f" و 💰+{got} {GS} به خزانه" if got else " (حریف هم‌وزن نبود یا سقف خزانه‌ی امروز پره)"),
        f"🪦 بازنده: {esc(lg['name'])} (دفعه‌ی بعد بهتر میشه! 💪)",
    ], "👑 +۲۰ امتیاز هفتگی برای برنده، +۵ برای بازنده"),
        reply_markup=kb([btn("🗺 قلمروها", f"m:terr:{m.from_user.id}", "blue"), btn("🌙 منو", f"m:main:{m.from_user.id}", "green")]))
    await quest_progress(m, "war")


async def do_guild_invite(m: Message, uname: Optional[str]):
    doc = await store.get(m.from_user.id)
    if not doc.get("guild"):
        await say(m, "اول باید خودت گیلد داشته باشی، بعد می‌تونی دعوت کنی. 🛡", "📯", "دعوت", "blue")
        return
    who = f"@{uname}" if uname else ""
    if not uname and m.reply_to_message and m.reply_to_message.from_user:
        who = esc(m.reply_to_message.from_user.full_name)
    if not who:
        await say(m, "کی رو دعوت کنم؟ روی پیامش ریپلای بزن یا @یوزرنیمش رو بنویس.", "📯", "دعوت", "blue")
        return
    await m.reply(panel("blue", "📯", "دعوت‌نامه‌ی گیلد", [
        f"{who} — {esc(m.from_user.full_name)} تو رو به گیلد <b>{esc(doc['guild'])}</b> دعوت کرد!",
        f"برای قبول بنویس: «<b>پیوستن به گیلد {esc(doc['guild'])}</b>»",
    ]))


async def do_guild_donate(m: Message, amount: int):
    """اهدا به خزانه‌ی گیلد: GS از جیب اعضا → خزانه (برای محاصره و دژ). دو مرحله‌ایِ برگشت‌پذیر."""
    uid = m.from_user.id
    doc = await store.get(uid)
    if not doc.get("guild"):
        await say(m, "اول باید عضو یه گیلد باشی. 🛡", "💰", "خزانه", "yellow")
        return
    if not (10 <= amount <= 100000):
        await say(m, "مبلغ اهدا باید حداقل ۱۰ GS باشه. 💰", "💰", "خزانه", "yellow")
        return
    if not await debit(uid, amount, "guild_donate", burn_it=False):
        await say(m, f"موجودیت برای اهدای {fmt(amount)} کافی نیست. 🪙", "💰", "خزانه", "yellow")
        return
    res = await store.guilds.update_one({"name": doc["guild"]}, {"$inc": {"treasury": amount}})
    if not res.matched_count:
        await credit(uid, amount, "guild_donate_refund")
        await say(m, "گیلدت پیدا نشد؛ پولت برگشت. 🪦", "💰", "خزانه", "yellow")
        return
    g = await store.guilds.find_one({"name": doc["guild"]})
    await m.reply(panel("yellow", "💰", "اهدا به خزانه", [
        f"{esc(m.from_user.full_name)} {fmt(amount)} به خزانه‌ی <b>{esc(doc['guild'])}</b> اهدا کرد.",
        f"💰 خزانه‌ی گیلد: <b>{fmt(g.get('treasury', 0))}</b>",
    ], "💅 <i>«پول به گور نمی‌بری، ولی به خزانه می‌بری. قشنگه.»</i>"))


async def do_guild_fort(m: Message):
    """تقویت دژ (فقط رهبر): هر سطح +۱۰٪ دفاع در محاصره‌ها، تا آخرِ همین هفته. هزینه از خزانه."""
    uid = m.from_user.id
    doc = await store.get(uid)
    g = await store.guilds.find_one({"name": doc.get("guild")}) if doc.get("guild") else None
    if not g:
        await say(m, "گیلدی نداری. 🛡", "🏯", "دژ", "blue")
        return
    if g["owner_id"] != uid:
        await say(m, "فقط رهبرِ گیلد می‌تونه دژ رو تقویت کنه. 👑", "🏯", "دژ", "blue")
        return
    cur = effective_fort(g)
    if cur >= len(FORT_COSTS):
        await say(m, "دژ به بالاترین سطحِ این هفته رسیده. 🏯", "🏯", "دژ", "blue")
        return
    cost = FORT_COSTS[cur]
    res = await store.guilds.update_one(
        {"_id": g["_id"], "owner_id": uid, "treasury": {"$gte": cost}, "fort": g.get("fort"), "fort_week": g.get("fort_week")},
        {"$inc": {"treasury": -cost}, "$set": {"fort": cur + 1, "fort_week": week_key()}})
    if not res.modified_count:
        await say(m, f"خزانه کمه (لازم: {fmt(cost)}). اعضا با «اهدا [مبلغ]» پرش کنن. 💰", "🏯", "دژ", "blue")
        return
    await burn(cost, "fort")
    await m.reply(panel("blue", "🏯", "دژ تقویت شد!", [
        f"🏯 سطح دژ: <b>{cur + 1}/{len(FORT_COSTS)}</b> (+{(cur + 1) * 10}٪ دفاع تا آخر هفته)", f"💰 −{fmt(cost)} از خزانه",
    ]))
