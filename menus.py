"""منوی اصلی («زندگی من») و کیبوردهای کنار پیام‌ها."""

from typing import Optional

from aiogram.types import InlineKeyboardMarkup

from content import gline
from guide import CATS, cat_button, hint_line, pop_unlock_news, tut_active, tut_count, tut_next, TUT
from database import store
from render import class_label, stat_lines
from ui import back_kb, btn, kb, panel, share_btn
from utils import esc


def hub_kb(uid: int, doc: Optional[dict] = None) -> InlineKeyboardMarkup:
    """منوی اصلیِ تدریجی: هسته‌ی بازی همیشه بازه، بقیه تو ۴ دسته (با قفلِ سطح) جمع شدن.
    doc=None یعنی همه‌چیز باز (ایمنی)."""
    u = uid
    cats = [cat_button(u, doc, k) for k in CATS]
    return kb(
        [btn("🎯 الان چیکار کنم؟", f"m:next:{u}", "green")],
        [btn("🌍 ماجراجویی", f"m:go:{u}", "green"), btn("📜 ماموریت‌ها", f"m:quest:{u}", "blue")],
        [btn("🎴 کارت من", f"m:pass:{u}", "blue"), btn("🎒 کوله‌پشتی", f"m:inv:{u}", "green")],
        cats[0:2],
        cats[2:4],
        [btn("📖 راهنما", f"m:help:{u}", "blue"), btn("☠️ مرگ داوطلبانه", f"m:die:{u}", "red")],
    )


def hub_text(doc: dict, news: Optional[list] = None) -> str:
    name = esc(doc.get("first_name") or "ناشناس")
    titles = doc.get("titles") or []
    lines = [
        f"👤 <b>{name}</b>" + (f" ‹{esc(titles[-1])}›" if titles else ""),
        f"🎭 {class_label(doc)}   🛡 {esc(doc.get('guild')) if doc.get('guild') else 'بی‌گیلد'}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
    ]
    if tut_active(doc):
        step = tut_next(doc)
        if step:
            lines += ["┈┈┈┈┈┈┈┈┈┈", f"🎓 تور شروع {tut_count(doc)}/{len(TUT)} — قدم بعدی: {step[1]} {step[2]}"]
    if news:
        lines += ["┈┈┈┈┈┈┈┈┈┈", *news]
    return panel("purple", "🌙", "پنل‌های ایزدبانوی پایان", lines, hint_line(doc) or gline(doc))


async def hub_payload(doc: dict) -> tuple:
    """(متن، کیبورد) منوی اصلی؛ اعلامِ «بخشِ جدید باز شد» رو هم (یک‌بار) اضافه می‌کنه."""
    news = await pop_unlock_news(doc)
    return hub_text(doc, news), hub_kb(doc["user_id"], doc)


def after_explore_kb(uid: int, key: str, npcs: Optional[list] = None, trail: bool = False) -> InlineKeyboardMarkup:
    """npcs: کلیدِ NPCهایی که همین الان سر راه بازیکنن (دکمه‌ی گفتگو، بالای بقیه)."""
    from content import NPCS  # import تنبل
    from worldsim import npc_label
    npc_rows = []
    for k in (npcs or []):
        if k in NPCS:
            npc_rows.append([btn(f"💬 حرف زدن با {NPCS[k]['icon']} {NPCS[k]['name']}", f"n:{k}:{uid}", NPCS[k]["color"])])
        else:                                   # NPCِ زنده‌ی بدونِ مکانیکِ قدیمی (آهنگر، ماجراجو، خنیاگر، …)
            nm, ic = npc_label(k)
            npc_rows.append([btn(f"💬 حرف زدن با {ic} {nm}", f"wn:{k}:hi:{uid}", "purple")])
    if trail:                                   # 🧭 ردپای ماجرا (expedition.py)
        npc_rows.insert(0, [btn("🧭 دنبالش برو", f"e:go:0:{uid}", "green")])
    return kb(
        *npc_rows,
        [btn("🌍 دوباره بگرد", f"x:{key}:{uid}", "green"), btn("🎴 کارت من", f"m:pass:{uid}", "blue")],
        [btn("📜 ماموریت‌ها", f"m:quest:{uid}", "blue"), btn("🎯 قدم بعدی", f"m:next:{uid}", "green"), btn("🌙 منو", f"m:main:{uid}", "blue")],
    )


def after_death_kb(uid: int) -> InlineKeyboardMarkup:
    return kb(
        [btn("🌍 برگردم ماجراجویی", f"m:go:{uid}", "green"), btn("🎴 کارت من", f"m:pass:{uid}", "blue")],
        [share_btn(uid, "☠️ همین الان مُردم و ایزدبانو بهم خندید! بیا تو هم بازی کن و بمیر 😂")],
    )


async def send_hub(m, doc: Optional[dict] = None):
    doc = doc or await store.get(m.from_user.id)
    text, markup = await hub_payload(doc)
    await m.reply(text, reply_markup=markup)


# ───────────────────────────── 🎛 هندلر دکمه‌ها ─────────────────────────────
def help_kb(uid: int) -> InlineKeyboardMarkup:
    return kb([btn("📚 همه‌ی دستورها", f"hc:main:{uid}", "green")], back_kb(uid))
