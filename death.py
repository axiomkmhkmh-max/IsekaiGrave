"""مرگ داوطلبانه و پیام نگرانی (distress)."""

import time
from typing import Optional

from aiogram.types import Message

from config import SELF_DEATH_COOLDOWN
from menus import after_death_kb
from players import reincarnate
from render import render_rebirth, render_scene
from ui import say
from utils import esc, gid


_last_self_death: dict = {}


async def do_self_death(m: Message, forced_by: Optional[str] = None):
    uid = m.from_user.id
    now = time.time()
    if now - _last_self_death.get(uid, 0) < SELF_DEATH_COOLDOWN:
        await say(m, "یه کم آروم‌تر! چند ثانیه صبر کن و دوباره امتحان کن. ⏳", "⏳", "یه لحظه صبر کن", "orange")
        return
    _last_self_death[uid] = now
    doc, new = await reincarnate(uid, chat_id=gid(m))
    name = esc(m.from_user.full_name)
    await m.reply(f"{render_scene('<b>' + name + '</b>')}\n\n{render_rebirth(doc, new)}",
                  reply_markup=after_death_kb(uid))


async def do_distress(m: Message):
    await m.reply(
        "🤍 <b>یه لحظه نقش ایزدبانوی بداخلاق رو میذارم کنار.</b>\n\n"
        "اگه این حرف از ته دلته و واقعاً حالت بده، مهمه و جدیش می‌گیرم. "
        "با یه آدم مورد اعتماد حرف بزن. اگه تو ایران هستی، <b>۱۲۳</b> (اورژانس اجتماعی) "
        "یا خط مشاوره‌ی <b>۱۴۸۰</b> رو بگیر؛ اگه خطر همین الان تهدیدت می‌کنه، <b>۱۱۵</b>.\n\n"
        "من هم همین‌جام؛ بگو چی شده. اگه فقط شوخی بود و بازی می‌خوای، بنویس «زندگی من»."
    )
