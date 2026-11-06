"""📖 روایتِ ترکیبی ماجراجویی: AI یک صحنه‌ی کوتاه می‌نویسه؛ نبود/خطا/کوتاه → None (متنِ ثابت می‌مونه).
اثری روی نتیجه/جایزه نداره. (گشت و سفرِ ماجراجویی هر دو ازش استفاده می‌کنن.)"""

import random
from typing import Optional

import aiclient
from aiclient import clean_text


async def scene(B: dict, what: str, name: Optional[str], uid: int, wait: int = 3) -> Optional[str]:
    if not aiclient.ai_available():
        return None
    what_en = (f"The player is about to face the giant «{name}». Describe its menacing, darkly funny entrance, before any fight."
               if name else "A short strange lore moment the player witnesses (a rumor, a ruin detail, a weird traveler).")
    msgs = [
        {"role": "system", "content": (
            f"You are the dark-funny narrator of a Persian text isekai RPG. Location: {B['name']}. {what_en} "
            "Write 1-2 short Persian sentences, no emojis, no numbers, no rewards or instructions, and do not say who wins.")},
        {"role": "user", "content": "Narrate."},
    ]
    ck = f"scene|{B['name']}|{what}|{name or ''}|{random.randint(0, 3)}"      # چند نسخه‌ی کش‌شده → صرفه‌جویی در سهمیه‌ی رایگان
    txt = await aiclient.ask(msgs, uid=uid, max_tokens=140, temperature=0.9, cache_key=ck, wait=wait, tag="adv_scene:" + what)
    txt = clean_text(txt, 220) if txt else ""
    return txt if len(txt) >= 12 else None
