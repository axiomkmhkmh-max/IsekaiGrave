"""نقطه‌های ورودیِ آپدیت‌ها: استارت، ورود به گروه، کال‌بک، اسلش و متن."""

import re

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from callbacks import handle_cb
from commands import _ALL_SLASH
from config import log
from content import GODDESS_NAME, GODDESS_TITLE
from database import store
from game_text import handle_text
from menus import hub_kb, hub_text, send_hub
from players import refresh_titles
from registration import reg_prompt, start_registration
from ui import btn, kb, panel, say
from utils import esc, is_group
from welcome import welcome_group_text, welcome_member_text


# ───────────────────────────── Handlers ─────────────────────────────
router = Router()


# ───────────────────────────── ✨ ورود به گروه ─────────────────────────────
@router.message(F.new_chat_members)
async def on_join(m: Message, bot: Bot):
    try:
        if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            await store.groups.update_one({"chat_id": m.chat.id}, {"$set": {"title": m.chat.title}}, upsert=True)
        joined = m.new_chat_members or []
        if any(u.id == bot.id for u in joined):
            await m.answer(welcome_group_text(), reply_markup=kb(
                [btn("🩸 ثبت‌نام و امضای قرارداد", "reg:go:0", "green")],
                [btn("📖 راهنما", "m:help:0", "blue")],
            ))
            return
        humans = [u for u in joined if not u.is_bot]
        if humans:
            await m.answer(welcome_member_text(humans), reply_markup=kb(
                [btn("🩸 امضای قرارداد (ثبت‌نام)", "reg:go:0", "green")],
            ))
    except Exception:
        log.exception("join welcome failed")


@router.message(CommandStart())
async def on_start(m: Message, command: CommandObject):
    if not m.from_user:
        return
    created = await store.touch(m.from_user)
    arg = command.args or ""
    if created and arg.startswith("ref_") and arg[4:].isdigit():
        ref = int(arg[4:])
        if ref != m.from_user.id:
            res = await store.users.update_one(
                {"user_id": ref}, {"$inc": {"referrals_available": 1, "referrals_total": 1}}
            )
            if res.matched_count:
                try:
                    await m.bot.send_message(ref, "🎉 یه نفر با لینک تو وارد بازی شد! +۱ امتیاز معرفی. 🙌")
                except Exception:
                    pass
                rdoc = await store.get(ref)
                if rdoc:
                    await refresh_titles(rdoc)
    doc = await store.get(m.from_user.id)
    if doc.get("banned"):
        return
    if is_group(m):
        if doc.get("registered"):
            await send_hub(m, doc)
        else:
            await reg_prompt(m)
        return
    if doc.get("registered"):
        await m.answer(
            f"💅 <i>«اوه… <b>{esc(m.from_user.first_name)}</b> برگشته. فکر می‌کردم بالاخره مُردی و از دستت راحت شدم.»</i>\n\n" + hub_text(doc),
            reply_markup=hub_kb(m.from_user.id),
        )
        return
    await m.answer(panel("purple", "🌌", f"دروازه‌ی آخرِ ایسکا باز شد", [
        f"مه‌ی بنفش کنار می‌ره و روی تخت استخوانی، <b>{GODDESS_NAME}</b> پدیدار میشه؛ چای به دست، خسته و بی‌حوصله…",
        f"💅 «من <b>{GODDESS_TITLE}</b> هستم. هر روحی که از این دروازه رد بشه، دیر یا زود برام زانو می‌زنه… یا التماس می‌کنه. معمولاً هر دو.»",
        "┈┈┈┈┈┈┈┈┈┈",
        "اینجا یه بازی متنیه با ماجراجویی، دوئل، گیلد، باس، صندوق گنج، ازدواج و… مرگ‌های بی‌شمار 😄",
        "همه‌چی با نوشتن یه جمله‌ی ساده یا زدن دکمه‌های رنگی انجام میشه. برای شروع، ثبت‌نام کن 👇",
    ]))
    await start_registration(m)


@router.callback_query()
async def on_callback(cq: CallbackQuery, bot: Bot):
    try:
        await handle_cb(cq, bot)
    except Exception:
        log.exception("callback failed")
        try:
            await cq.answer("یه مشکل کوچیک پیش اومد. دوباره امتحان کن. 🛠", show_alert=True)
        except Exception:
            pass


@router.message(Command(*_ALL_SLASH.keys()))
async def on_slash(m: Message, command: CommandObject, bot: Bot):
    """دستورهای اسلش رو به همون عبارت فارسی تبدیل می‌کنه و می‌ده به handle_text."""
    if not m.from_user or m.from_user.is_bot:
        return
    tpl, _desc, arg_mode = _ALL_SLASH[command.command.lower()]
    args = (command.args or "").strip()
    if arg_mode == "req" and not args:
        await m.reply(f"این دستور آرگومان می‌خواد. مثال:\n<code>/{command.command} …</code>\n{_desc}")
        return
    text = re.sub(r"\s+", " ", tpl.replace("{a}", args)).strip()
    try:
        await handle_text(m.model_copy(update={"text": text}), bot)
    except Exception:
        log.exception("slash handler failed")
        await say(m, "یه مشکل فنی پیش اومد. چند لحظه‌ی دیگه دوباره امتحان کن. 🛠", "🛠", "خطای سیستم", "red")


@router.message(F.text)
async def on_text(m: Message, bot: Bot):
    if not m.from_user or m.from_user.is_bot or not m.text or m.text.startswith("/"):
        return
    try:
        await handle_text(m, bot)
    except Exception:
        log.exception("handler failed")
        await say(m, "یه مشکل فنی پیش اومد. چند لحظه‌ی دیگه دوباره امتحان کن. 🛠", "🛠", "خطای سیستم", "red")
