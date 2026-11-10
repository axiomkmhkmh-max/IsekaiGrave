"""Procedural fantasy artwork for Telegram world panels.

Creates lightweight, deterministic 3D/isometric-inspired PNG cards locally with Pillow.
No external image API, credentials, or paid service is required.
"""
from __future__ import annotations

import hashlib
import io
import random
from functools import lru_cache
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1200, 720
FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"
LATIN_FONT = "/usr/share/fonts/truetype/lato/Lato-Regular.ttf"
LATIN_BOLD = "/usr/share/fonts/truetype/lato/Lato-Bold.ttf"
PALETTES = {
    "world": ((13, 18, 46), (54, 36, 104), (45, 180, 190)),
    "boss": ((35, 9, 27), (113, 27, 49), (255, 151, 69)),
    "npc": ((10, 43, 49), (31, 94, 91), (128, 227, 180)),
    "region": ((13, 33, 58), (37, 83, 111), (107, 203, 218)),
    "chronicle": ((30, 20, 51), (83, 48, 108), (238, 190, 111)),
    "news": ((16, 30, 48), (37, 71, 93), (242, 196, 107)),
    "character": ((30, 20, 55), (83, 44, 118), (255, 204, 119)),
    "market": ((11, 38, 42), (29, 99, 81), (247, 196, 89)),
    "guild": ((28, 25, 55), (69, 58, 116), (166, 155, 255)),
    "quest": ((30, 37, 61), (68, 83, 117), (237, 194, 112)),
}


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def _gradient(top, bottom):
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        t = y / max(1, H - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(W):
            px[x, y] = c
    return im


def _glow(draw, x, y, radius, color):
    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)


def _draw_island(draw, accent, seed):
    rng = random.Random(seed)
    # Floating island top, shaded sides and hanging rock facets.
    cx, cy = 800, 430
    top = [(cx-330, cy-25), (cx-210, cy-130), (cx+80, cy-150),
           (cx+310, cy-55), (cx+250, cy+70), (cx-90, cy+110)]
    draw.polygon(top, fill=(77, 112, 116), outline=(173, 218, 205), width=5)
    draw.polygon([(cx-330,cy-25),(cx-90,cy+110),(cx-35,cy+250),(cx-180,cy+185)], fill=(31,55,75))
    draw.polygon([(cx-90,cy+110),(cx+250,cy+70),(cx+130,cy+235),(cx-35,cy+250)], fill=(24,43,67))
    draw.polygon([(cx+250,cy+70),(cx+310,cy-55),(cx+230,cy+175),(cx+130,cy+235)], fill=(40,65,81))
    # Terrain facets, crystals and floating shards.
    draw.polygon([(cx-210,cy-130),(cx+80,cy-150),(cx+30,cy-35),(cx-120,cy+15)], fill=(76,137,119))
    draw.polygon([(cx+80,cy-150),(cx+310,cy-55),(cx+30,cy-35)], fill=(112,151,132))
    for _ in range(7):
        x, y = rng.randint(570, 1020), rng.randint(310, 440)
        h = rng.randint(25, 70)
        draw.polygon([(x,y),(x+14,y-h),(x+29,y),(x+14,y+13)], fill=accent, outline=(226,244,236))
    # Tiny fantasy tower silhouette.
    draw.rectangle((780, 245, 830, 350), fill=(28, 35, 62))
    draw.polygon([(770,247),(805,190),(840,247)], fill=(35, 42, 72))
    draw.rectangle((798, 295, 813, 350), fill=accent)


def _draw_boss(draw, accent, seed):
    # A dramatic horned dragon/ancient creature silhouette.
    rng = random.Random(seed)
    cx, cy = 820, 390
    draw.ellipse((cx-155,cy-160,cx+155,cy+165), fill=(22,15,34), outline=accent, width=7)
    draw.polygon([(cx-105,cy-80),(cx-260,cy-230),(cx-205,cy-35),(cx-115,cy+20)], fill=(25,17,35), outline=accent)
    draw.polygon([(cx+105,cy-80),(cx+260,cy-230),(cx+205,cy-35),(cx+115,cy+20)], fill=(25,17,35), outline=accent)
    draw.polygon([(cx-90,cy-105),(cx-160,cy-260),(cx-40,cy-165)], fill=(19,15,31), outline=accent, width=5)
    draw.polygon([(cx+90,cy-105),(cx+160,cy-260),(cx+40,cy-165)], fill=(19,15,31), outline=accent, width=5)
    draw.ellipse((cx-78,cy-25,cx-22,cy+22), fill=(255,205,104))
    draw.ellipse((cx+22,cy-25,cx+78,cy+22), fill=(255,205,104))
    draw.polygon([(cx-45,cy+75),(cx,cy+125),(cx+45,cy+75)], fill=(8,8,20))
    for _ in range(16):
        x, y = rng.randint(620, 1090), rng.randint(180, 590)
        r = rng.randint(2, 6)
        draw.ellipse((x-r,y-r,x+r,y+r), fill=accent)


def render_world_art(kind: str, title: str, subtitle: str = "", stats: Optional[Iterable[str]] = None) -> bytes:
    normalized_stats = tuple(str(x)[:60] for x in (stats or ()))
    return _render_world_art_cached(str(kind), str(title), str(subtitle), normalized_stats)


@lru_cache(maxsize=64)
def _render_world_art_cached(kind: str, title: str, subtitle: str, stats: tuple) -> bytes:
    kind = kind if kind in PALETTES else "world"
    top, bottom, accent = PALETTES[kind]
    seed = int(hashlib.sha256(f"{kind}|{title}|{subtitle}".encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    im = _gradient(top, bottom)
    # Atmospheric bloom and starfield.
    glow = Image.new("RGBA", (W,H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((650,70,1190,610), fill=(*accent,95))
    glow = glow.filter(ImageFilter.GaussianBlur(85))
    im = Image.alpha_composite(im.convert("RGBA"), glow)
    d = ImageDraw.Draw(im)
    for _ in range(125):
        x, y = rng.randrange(W), rng.randrange(H)
        r = rng.choice((1,1,2,3))
        d.ellipse((x-r,y-r,x+r,y+r), fill=(220,235,255,rng.randint(80,210)))
    # layered distant mountains
    d.polygon([(0,470),(170,300),(330,475),(490,320),(670,490),(850,330),(1050,490),(1200,370),(1200,720),(0,720)], fill=(20,35,64,190))
    d.polygon([(0,555),(210,405),(390,565),(620,400),(830,580),(1040,430),(1200,560),(1200,720),(0,720)], fill=(12,27,50,220))
    if kind == "boss":
        _draw_boss(d, accent, seed)
    else:
        _draw_island(d, accent, seed)
    # Framed typography zone.
    d.rounded_rectangle((42,42,610,678), radius=30, fill=(5,10,28,168), outline=(*accent,180), width=3)
    try:
        latin_head = ImageFont.truetype(LATIN_BOLD, 24)
        latin_foot = ImageFont.truetype(LATIN_BOLD, 16)
    except OSError:
        latin_head = _font(24, True)
        latin_foot = _font(16, True)
    d.text((78,85), "ISEKAI GRAVE  •  LIVING WORLD", font=latin_head, fill=(205,220,242))
    # Wrap long Persian heading safely.
    title = str(title or "جهان ایسکا")[:64]
    subtitle = str(subtitle or "")[:110]
    d.text((565,190), title, font=_font(48, True), fill=(255,245,225), anchor="ra", direction="rtl", language="fa", stroke_width=1, stroke_fill=(30,20,45))
    if subtitle:
        d.multiline_text((565,270), subtitle, font=_font(27), fill=(212,225,238), anchor="ra", align="right", spacing=12, direction="rtl", language="fa")
    y = 500
    for line in list(stats or ())[:4]:
        d.text((565,y), str(line)[:60], font=_font(23), fill=(*accent,255), anchor="ra", direction="rtl", language="fa")
        y += 39
    d.rounded_rectangle((76,610,390,650), radius=18, fill=(*accent,45), outline=(*accent,160), width=2)
    d.text((232,630), "ONE WORLD • ONE CHRONICLE", font=latin_foot, fill=(240,240,250), anchor="mm")
    out = io.BytesIO()
    im.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


async def send_world_art(message, kind: str, title: str, subtitle: str = "", stats=None) -> bool:
    """Send a generated section illustration; artwork failure never blocks gameplay."""
    try:
        import asyncio
        from aiogram.types import BufferedInputFile
        payload = await asyncio.to_thread(render_world_art, kind, title, subtitle, stats)
        await message.reply_photo(BufferedInputFile(payload, filename=f"isekai-{kind}.png"))
        return True
    except Exception:
        # Pillow/font/platform issues must not break the text-based game.
        return False
