"""کوله‌پشتیِ بازیکن (با انتخابِ آیتم، فروش، تجهیز و سوزوندن؛ منطقش تو forge.py ـه)."""

from typing import Optional

from forge import inventory_panel
from guide import tut_mark


async def send_inventory(m, doc: Optional[dict] = None):
    await inventory_panel(m, doc)
    await tut_mark(m, "inv")           # 🎓 تورِ شروع: دیدنِ کوله‌پشتی
