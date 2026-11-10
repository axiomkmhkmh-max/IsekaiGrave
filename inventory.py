"""کوله‌پشتیِ بازیکن (با انتخابِ آیتم، فروش، تجهیز و سوزوندن؛ منطقش تو forge.py ـه)."""

from typing import Optional

from forge import inventory_panel
from guide import tut_mark


async def send_inventory(m, doc: Optional[dict] = None):
    try:
        from world_art import send_world_art
        await send_world_art(m, "inventory", "کوله‌پشتی قهرمان", "دارایی‌ها و یادگارهای سفر")
    except Exception:
        pass
    await inventory_panel(m, doc)
    await tut_mark(m, "inv")           # 🎓 تورِ شروع: دیدنِ کوله‌پشتی
