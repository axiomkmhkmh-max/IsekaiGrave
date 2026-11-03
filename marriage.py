"""ازدواج و پیوند ایسکایی."""

from datetime import timedelta
from typing import Optional

from bson import ObjectId

from config import PROPOSAL_TTL
from database import store
from render import display
from ui import back_kb, btn, kb, panel, say
from utils import esc, is_group, utcnow


# ───────────────────────────── 💍 ازدواج و پیوند ایسکایی ─────────────────────────────
async def do_marry(m, uname: Optional[str]) -> bool:
    if not is_group(m):
        await say(m, "پیوند باید جلوی شاهدها باشه؛ تو یه گروه بنویس. 💍", "💍", "پیوند", "red")
        return True
    target = None
    if uname:
        target = await store.users.find_one({"username_lower": uname.lower()})
        if not target:
            await say(m, "این بازیکن رو هنوز نمی‌شناسم. بگو یه پیام تو گروه بنویسه تا ثبتش کنم. 📖", "💍", "پیوند", "red")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user:
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await say(m, "با ربات نمی‌شه ازدواج کرد! یه آدم واقعی رو انتخاب کن. 🤖", "💍", "پیوند", "red")
            return True
        await store.touch(tu)
        target = await store.get(tu.id)
    else:
        await say(m, "با کی؟ ریپلای بزن و «ازدواج» بنویس، یا «ازدواج با @یوزرنیم».", "💍", "پیوند", "blue")
        return True
    me = await store.get(m.from_user.id)
    if target["user_id"] == m.from_user.id:
        await say(m, "نمی‌تونی با خودت ازدواج کنی! یه نفر دیگه رو انتخاب کن. 🪞", "💍", "پیوند", "red")
        return True
    if me.get("spouse"):
        await say(m, f"تو الان با {esc(me.get('spouse_name'))} پیوند داری. اگه می‌خوای عوض کنی، اول «طلاق» بنویس. 💔", "💍", "پیوند", "red")
        return True
    if target.get("spouse"):
        await say(m, f"{display(target)} قبلاً پیوند بسته. یه نفر دیگه رو انتخاب کن. 💍", "💍", "پیوند", "red")
        return True
    if not target.get("registered"):
        await say(m, f"{display(target)} هنوز ثبت‌نام نکرده؛ اول باید ثبت‌نام کنه. 📜", "💍", "پیوند", "red")
        return True
    if target.get("opted_out"):
        await say(m, f"{display(target)} حالت «محافظت» رو فعال کرده. 🛡", "💍", "پیوند", "red")
        return True
    await store.proposals.update_many({"from": m.from_user.id, "status": "pending"}, {"$set": {"status": "expired"}})
    res = await store.proposals.insert_one({
        "chat_id": m.chat.id, "from": m.from_user.id, "from_name": m.from_user.full_name,
        "to": target["user_id"], "status": "pending", "expires_at": utcnow() + timedelta(seconds=PROPOSAL_TTL),
    })
    pid = str(res.inserted_id)
    await m.reply(panel("red", "💍", "پیشنهاد پیوند ایسکایی", [
        f"💞 {esc(m.from_user.full_name)} از {display(target, link=True)} خواستگاری کرد!",
        "اگه قبول کنن: بقا و سرنوشتشون به هم گره می‌خوره؛",
        "• مرگِ یکی ← −۶٪ بقا و −۱۰ طلا برای اون یکی",
        "• تو دوئل‌ها +۸ قدرت (انرژی عشق… یا ترس از تنها موندن)",
        "⏳ ۵ دقیقه وقت دارن.",
    ], "💅 <i>«عشق؟ تو ایسکا؟ ساده‌لوح‌ها… ولی باشه. فقط وقتی یکیتون مرد گریه نکنید.»</i>"),
        reply_markup=kb([btn("💍 قبول می‌کنم", f"mar:yes:{pid}:{target['user_id']}", "green"),
                         btn("💔 رد", f"mar:no:{pid}:{target['user_id']}", "red")]))
    return True


async def marriage_answer(m, yes: bool, pid: Optional[str]) -> bool:
    q = {"to": m.from_user.id, "status": "pending", "expires_at": {"$gt": utcnow()}}
    if pid and pid != "0":
        try:
            q["_id"] = ObjectId(pid)
        except Exception:
            return False
    else:
        q["chat_id"] = m.chat.id
    prop = await store.proposals.find_one_and_update(q, {"$set": {"status": "yes" if yes else "no"}})
    if not prop:
        if pid:
            await say(m, "این خواستگاری تموم شده یا برای تو نیست.", "💍", "پیوند", "red")
        return False
    if not yes:
        await m.reply(panel("red", "💔", "رد شد", [f"{esc(m.from_user.full_name)} پیشنهاد {esc(prop['from_name'])} رو رد کرد."],
                            "💅 <i>«رد شدی؟ دردناکه؟ عالی؛ دیدنش خنده‌دار بود.»</i>"))
        return True
    a, b = await store.get(prop["from"]), await store.get(m.from_user.id)
    if not a or not b or a.get("spouse") or b.get("spouse"):
        await say(m, "یکی از شما وسط راه با یه نفر دیگه پیوند بسته؛ پس این خواستگاری باطل شد. 😕", "💍", "پیوند", "red")
        return True
    await store.users.update_one({"user_id": a["user_id"]}, {"$set": {"spouse": b["user_id"], "spouse_name": b.get("first_name")}, "$inc": {"gold": 50}})
    await store.users.update_one({"user_id": b["user_id"]}, {"$set": {"spouse": a["user_id"], "spouse_name": a.get("first_name")}, "$inc": {"gold": 50}})
    await m.reply(panel("green", "💞", "پیوند ایسکایی بسته شد!", [
        f"{display(a, link=True)} 💍 {display(b, link=True)}",
        "🎁 هدیه‌ی عروسی: 🪙+۵۰ برای هر کدوم",
        "🔗 از این لحظه بقاتون به هم گره خورده؛ مراقب هم باشید! 💞",
    ], "💅 <i>«تبریک. و تسلیت. هر دو رو همزمان می‌گم.»</i>"))
    return True


async def do_divorce(m):
    me = await store.get(m.from_user.id)
    if not me.get("spouse"):
        await say(m, "الان پیوندی نداری که ازش جدا بشی. 🥀", "💔", "طلاق", "red")
        return
    sp = me["spouse"]
    await store.users.update_one({"user_id": m.from_user.id}, {"$set": {"spouse": None, "spouse_name": None}})
    await store.users.update_one({"user_id": sp}, {"$set": {"spouse": None, "spouse_name": None}})
    await m.reply(panel("red", "💔", "پیوند فسخ شد", [
        f"{esc(m.from_user.full_name)} و {esc(me.get('spouse_name'))} از هم جدا شدن.",
        "🔓 بقاشون دیگه به هم گره نیست.",
    ], "💅 <i>«یه پیوند دیگه که تو دفتر من خط خورد. خسته نشدی؟»</i>"))


async def do_marry_info(m, doc: dict):
    uid = m.from_user.id
    if doc.get("spouse"):
        lines = [f"💞 پیوند با <b>{esc(doc.get('spouse_name'))}</b> برقراره.",
                 "برای فسخ بنویس «<b>طلاق</b>»."]
        mk = kb([btn("💔 طلاق", f"m:divorce:{uid}", "red")], back_kb(uid))
    else:
        lines = ["الان مجردی. اگه می‌خوای پیوند ببندی، این‌طوری شروع کن 👇",
                 "برای پیوند: ریپلای + «<b>ازدواج</b>» یا «<b>ازدواج با @یوزرنیم</b>»"]
        mk = kb(back_kb(uid))
    await m.reply(panel("red", "💍", "پیوند ایسکایی", lines), reply_markup=mk)
