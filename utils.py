"""ابزارهای عمومی: نرمال‌سازی متن فارسی، escape، زمان، و چند کمک‌تابع کوچیک."""

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Optional

from aiogram.enums import ChatType
from aiogram.types import Message, User

from config import IR_OFFSET


# ───────────────────────────── Persian helpers ─────────────────────────────
_TR = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ؤ": "و",
    "\u200c": "", "\u200d": "", "\u200e": "", "\u200f": "",
})


_DIAC = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_PUNCT = re.compile(r"[؟?!.،,؛;…~\-_*«»\"'()]+")


def norm(text: str) -> str:
    t = text.translate(_TR)
    t = _DIAC.sub("", t).lower()
    return re.sub(r"\s+", " ", t).strip()


def clean(n: str) -> str:
    # علائم نگارشی حذف میشن ولی @یوزرنیم‌ها (که ممکنه _ داشته باشن) دست‌نخورده می‌مونن
    parts = re.split(r"(@\w{1,32})", n)
    out = "".join(p if p.startswith("@") else _PUNCT.sub(" ", p) for p in parts)
    return re.sub(r"\s+", " ", out).strip()


def esc(s: Optional[str]) -> str:
    return html.escape(s or "", quote=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_group(m: Message) -> bool:
    return m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


def gid(m: Message) -> Optional[int]:
    return m.chat.id if is_group(m) else None


_bg_tasks: set = set()


def spawn(coro):
    """اجرای تسک پس‌زمینه بدون اینکه garbage-collect بشه."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


def mention(u: User) -> str:
    return f'<a href="tg://user?id={u.id}">{esc(u.full_name)}</a>'


def ir_now() -> datetime:
    return utcnow() + IR_OFFSET


def day_key() -> str:
    return ir_now().strftime("%Y-%m-%d")


def week_key() -> str:
    y, w, _ = ir_now().isocalendar()
    return f"{y}-W{w:02d}"
