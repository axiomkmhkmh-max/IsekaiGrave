"""منوی اصلی («زندگی من») و کیبوردهای کنار پیام‌ها."""

from typing import Optional

from aiogram.types import InlineKeyboardMarkup

from content import gline
from database import store
from render import class_label, stat_lines
from ui import back_kb, btn, kb, panel
from utils import esc


def hub_kb(uid: int) -> InlineKeyboardMarkup:
    u = uid
    return kb(
        [btn("🎴 کارت من", f"m:pass:{u}", "blue"), btn("🎒 کوله‌پشتی", f"m:inv:{u}", "green")],
        [btn("🌍 ماجراجویی", f"m:go:{u}", "green"), btn("🧙 NPCها", f"m:npc:{u}", "blue")],
        [btn("🎡 گردونه‌ی شانس", f"m:wheel:{u}", "green"), btn("📜 ماموریت‌ها", f"m:quest:{u}", "blue")],
        [btn("🛡 گیلد من", f"m:guild:{u}", "blue"), btn("⚔️ جنگ گیلدها", f"m:war:{u}", "red")],
        [btn("👑 قلمروها", f"m:terr:{u}", "green"), btn("🐉 باس گروه", f"m:boss:{u}", "red")],
        [btn("💍 پیوند", f"m:marry:{u}", "red"), btn("🏆 لیدربرد", f"m:board:{u}", "blue")],
        [btn("🪦 بازار روح", f"m:exch:{u}", "green"), btn("🔥 کوره‌ی روح", f"m:forge:{u}", "red"), btn("🪙 GS", f"m:gs:{u}", "yellow")],
        [btn("🕶 بازار سیاه", f"m:market:{u}", "red"), btn("📖 راهنما", f"m:help:{u}", "blue")],
        [btn("☠️ مرگ داوطلبانه", f"m:die:{u}", "red")],
    )


def hub_text(doc: dict) -> str:
    name = esc(doc.get("first_name") or "ناشناس")
    titles = doc.get("titles") or []
    lines = [
        f"👤 <b>{name}</b>" + (f" ‹{esc(titles[-1])}›" if titles else ""),
        f"🎭 {class_label(doc)}   🛡 {esc(doc.get('guild')) if doc.get('guild') else 'بی‌گیلد'}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
    ]
    return panel("purple", "🌙", "پنل‌های ایزدبانوی پایان", lines, gline(doc))


def after_explore_kb(uid: int, key: str) -> InlineKeyboardMarkup:
    return kb(
        [btn("🌍 دوباره بگرد", f"x:{key}:{uid}", "green"), btn("🎴 کارت من", f"m:pass:{uid}", "blue")],
        [btn("📜 ماموریت‌ها", f"m:quest:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "green")],
    )


def after_death_kb(uid: int) -> InlineKeyboardMarkup:
    return kb([btn("🌍 برگردم ماجراجویی", f"m:go:{uid}", "green"), btn("🎴 کارت من", f"m:pass:{uid}", "blue")])


async def send_hub(m, doc: Optional[dict] = None):
    doc = doc or await store.get(m.from_user.id)
    await m.reply(hub_text(doc), reply_markup=hub_kb(m.from_user.id))


# ───────────────────────────── 🎛 هندلر دکمه‌ها ─────────────────────────────
def help_kb(uid: int) -> InlineKeyboardMarkup:
    return kb(back_kb(uid))
