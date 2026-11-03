"""کوله‌پشتی بازیکن."""

from typing import Optional

from database import store
from ui import back_kb, kb, panel
from utils import esc


# ───────────────────────────── 🎒 کوله‌پشتی ─────────────────────────────
async def send_inventory(m, doc: Optional[dict] = None):
    doc = doc or await store.get(m.from_user.id)
    inv = doc.get("inventory") or []
    lines = [f"{i}. {esc(x)}" for i, x in enumerate(inv, 1)] or ["کوله‌پشتیت خالیه. با ماجراجویی چیز جمع کن! 🎒"]
    await m.reply(panel("brown", "🎒", "کوله‌پشتی", lines, f"🪙 طلا: <b>{doc.get('gold', 0)}</b>"),
                  reply_markup=kb(back_kb(m.from_user.id)))
