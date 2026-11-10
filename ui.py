"""ساختن دکمه، کیبورد و پنل‌های رنگی + پاسخ‌دهی/ویرایش امن پیام."""

from typing import Optional

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from urllib.parse import quote

from config import log, runtime
from content import GODDESS_NAME
from utils import esc


# ───────────────────────────── 🎨 Color system ─────────────────────────────
# تلگرام فقط برای «دکمه‌ها» رنگ واقعی داره: success=سبز، danger=قرمز، primary=آبی.
STYLE = {"red": "danger", "orange": "danger", "green": "success", "blue": "primary", "purple": "primary"}


def btn(text: str, data: Optional[str] = None, color: Optional[str] = None, url: Optional[str] = None):
    """دکمه‌ی اینلاین رنگی. color: green / red / blue (بقیه = رنگ پیش‌فرض تلگرام)."""
    kw: dict = {"text": text}
    if url:
        kw["url"] = url
    else:
        kw["callback_data"] = data
    st = STYLE.get(color or "")
    if st:
        kw["style"] = st
    return InlineKeyboardButton(**kw)


def share_btn(uid: int, text: str, label: str = "📤 بفرست برای دوستات"):
    """دکمه‌ی اشتراک‌گذاری: پیام آماده + لینک دعوتِ اختصاصی؛ هر مرگِ خنده‌دار یه تبلیغه."""
    link = f"https://t.me/{runtime.bot_username}?start=ref_{uid}"
    return InlineKeyboardButton(text=label, url=f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text)}")


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


PANEL_ACCENTS = {"red": "🔥", "orange": "☄️", "yellow": "✨", "green": "🌿",
                 "blue": "💠", "purple": "🔮", "black": "🌑", "brown": "🪵"}


def panel(color: str, icon: str, title: str, lines: list, foot: Optional[str] = None) -> str:
    """پنل رنگی: نوار رنگیِ بالا + عنوان + بلاک‌کوت. lines باید از قبل HTML-safe باشن."""
    ac = PANEL_ACCENTS.get(color, "🔮")
    body = "\n".join(lines)
    s = f"{ac} {icon} <b>{esc(title)}</b>\n<blockquote>{body}</blockquote>"
    if foot:
        s += "\n" + foot
    return s


def hp_bar(rate: int) -> str:
    """نوار بقای رنگی: سبز (امن) / زرد (خطر) / قرمز (بحرانی)."""
    rate = max(0, min(100, rate))
    n = round(rate / 10)
    return "▰" * n + "▱" * (10 - n)


def xp_bar(xp: int) -> str:
    n = max(0, min(10, (xp % 100) // 10))
    return "▰" * n + "▱" * (10 - n)


class CbMsg:
    """شیمِ پیام برای کلیک دکمه‌ها: توابع do_* رو بدون تغییر با دکمه اجرا می‌کنه."""

    def __init__(self, cq: CallbackQuery, bot: Bot):
        self.from_user = cq.from_user
        self.chat = cq.message.chat
        self.message_id = cq.message.message_id
        self.bot = bot
        self.reply_to_message = None
        self.text = ""
        self._msg = cq.message

    async def reply(self, text, **kw):
        return await self._msg.answer(text, **kw)

    async def reply_photo(self, photo, **kw):
        """Forward photo replies from callback-driven menus to the source Telegram message."""
        return await self._msg.answer_photo(photo, **kw)

    answer = reply


async def say(m, text: str, icon: str = "💅", title: str = GODDESS_NAME, color: str = "purple",
              markup: Optional[InlineKeyboardMarkup] = None, foot: Optional[str] = None):
    """پیام ربات داخل پنل (به‌جای متن خالی)."""
    return await m.reply(panel(color, icon, title, [text], foot), reply_markup=markup)


async def safe_edit(msg, text: str, markup: Optional[InlineKeyboardMarkup] = None):
    try:
        await msg.edit_text(text, reply_markup=markup)
    except Exception as e:  # message is not modified / پیام قدیمی
        log.debug("edit failed: %s", e)


def back_kb(uid: int) -> list:
    return [btn("🔙 برگشت به منو", f"m:main:{uid}", "blue")]


async def show(m, text: str, markup: Optional[InlineKeyboardMarkup] = None):
    """اگه از دکمه اومده باشیم همون پنل رو ویرایش می‌کنه (منوی تمیز)، وگرنه پیام جدید می‌فرسته."""
    msg = getattr(m, "_msg", None)
    if msg is not None:
        try:
            await msg.edit_text(text, reply_markup=markup)
            return
        except Exception as e:
            log.debug("show edit failed: %s", e)
    return await m.reply(text, reply_markup=markup)
