"""کوله‌پشتیِ بازیکن (با انتخابِ آیتم، فروش، تجهیز و سوزوندن؛ منطقش تو forge.py ـه)."""

from typing import Optional

from forge import inventory_panel


async def send_inventory(m, doc: Optional[dict] = None):
    await inventory_panel(m, doc)
