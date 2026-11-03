"""مرگ اجباری، نفرین و دعای خیر."""

import random

from aiogram.types import Message

from config import FORCED_TARGET_COOLDOWN, runtime
from content import FORCED_OPENERS
from database import store
from death import do_self_death
from intents import BLESS_RE, CURSE_RE, EXEC_RE, REPLY_EXEC_RE
from players import adjust_survival, refresh_titles, reincarnate
from quests import quest_progress
from render import display, render_rebirth, render_scene
from ui import hp_bar, panel, say
from utils import esc, gid, is_group, utcnow


async def do_forced(m: Message, n: str, c: str) -> bool:
    target_doc = None
    mm = EXEC_RE.search(n)
    if mm:
        uname = mm.group(1).lower()
        if uname == runtime.bot_username.lower():
            await say(m, "منو بفرستی ایسکای؟ من خودِ خدای اون‌جام. یه بار دیگه امتحان کن، تا ابد اونجا می‌مونی. 💅")
            return True
        target_doc = await store.users.find_one({"username_lower": uname})
        if not target_doc:
            await say(m, "این بازیکن رو هنوز تو دفترم ندارم. بگو یه پیام تو گروه بنویسه تا ثبتش کنم، بعد حکم رو صادر می‌کنم. 📖", "📖", "ناشناس", "red")
            return True
    elif m.reply_to_message and m.reply_to_message.from_user and REPLY_EXEC_RE.fullmatch(c):
        tu = m.reply_to_message.from_user
        if tu.is_bot:
            await say(m, "ربات‌ها هم‌صنف منن؛ دستشون به من نمی‌رسه و دست تو هم بهشون نمی‌رسه. 🤖")
            return True
        await store.touch(tu)
        target_doc = await store.get(tu.id)
    else:
        return False

    author = m.from_user
    if target_doc["user_id"] == author.id:
        await do_self_death(m)
        return True
    if target_doc.get("opted_out"):
        await m.reply(
            f"{display(target_doc)} حالت «محافظت» رو فعال کرده. حتی من هم قانون رو دور نمی‌زنم… "
            "فعلاً. تو هم لقب «جلاد بی‌دندون» رو از من هدیه بگیر. 😒"
        )
        return True
    last = target_doc.get("last_death_at")
    if last and (utcnow() - last).total_seconds() < FORCED_TARGET_COOLDOWN:
        await say(m, "این بازیکن تازه مرده. چند دقیقه صبر کن و دوباره امتحان کن. 🧊", "🧊", "یه لحظه صبر کن", "blue")
        return True

    doc, new = await reincarnate(target_doc["user_id"], forced=True, chat_id=gid(m))
    await store.users.update_one({"user_id": author.id}, {"$inc": {"executions_ordered": 1}})
    adoc = await store.get(author.id)
    if adoc:
        await refresh_titles(adoc)
    opener = random.choice(FORCED_OPENERS).format(a=f"<b>{esc(author.full_name)}</b>", t=display(doc, link=True))
    await m.reply(f"{opener}\n\n{render_scene(display(doc, link=True))}\n\n{render_rebirth(doc, new)}")
    return True


async def do_curse_bless(m: Message, c: str, n: str) -> bool:
    if not (is_group(m) and m.reply_to_message and m.reply_to_message.from_user):
        return False
    is_curse = bool(CURSE_RE.search(n))
    is_bless = bool(BLESS_RE.search(n))
    if not (is_curse or is_bless):
        return False
    tu = m.reply_to_message.from_user
    if tu.is_bot or tu.id == m.from_user.id:
        return False
    await store.touch(tu)
    tdoc = await store.get(tu.id)
    if tdoc.get("opted_out"):
        await say(m, "این بازیکن «محافظت» فعال کرده. نفرینت بی‌اثر شد و به خودت برگشت. 🪞", "🪞", "نفرین برگشت", "red")
        return True
    a = f"<b>{esc(m.from_user.full_name)}</b>"
    if is_curse:
        d = random.randint(3, 12)
        doc = await adjust_survival(tu.id, -d, "curses_received")
        text = random.choice([
            f"😈 {a} یه مشت خاک قبرستون ریخت تو دیگ نفرین و {display(doc, link=True)} رو نشونه گرفت!\nنرخ بقا <b>{d}٪</b> سقوط کرد.",
            f"🕯 صدای نفرین تو گروه پیچید: {a} روح {display(doc, link=True)} رو به یه مرگ چندقدمی‌تر کرد.\nمنفی <b>{d}٪</b> از بقا.",
            f"🧿 {a} نفرین‌نامه رو امضا کرد؛ {display(doc, link=True)} حالا یه طلسم سنگین رو دوششه.\n−{d}٪ بقا، رایگان.",
        ])
        color, icon, title = "red", "😈", "نفرین"
    else:
        d = random.randint(2, 8)
        doc = await adjust_survival(tu.id, d, "blessings_received")
        text = random.choice([
            f"🙏 دعای خیر {a} روی {display(doc, link=True)} نشست؛ نرخ بقا <b>+{d}٪</b>. ایزدبانو می‌دونه دعای گروهی یعنی نقشه داره.",
            f"✨ {a} برای {display(doc, link=True)} دعا کرد. ایزدبانو با بی‌میلی <b>+{d}٪</b> بقا داد.",
        ])
        color, icon, title = "green", "🙏", "دعای خیر"
    doc, new = await refresh_titles(doc)
    lines = [text, f"💀 نرخ بقا حالا: <b>{doc['survival_rate']}٪</b> {hp_bar(doc['survival_rate'])}"]
    out = panel(color, icon, title, lines)
    if new:
        out += "\n🏷 لقب جدید: " + "، ".join(f"«{esc(t)}»" for t in new)
    await m.reply(out)
    await quest_progress(m, "curse" if is_curse else "bless")
    return True
