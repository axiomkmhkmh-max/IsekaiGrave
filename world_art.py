"""Offline fantasy artwork delivery for Telegram world panels.

Primary images are pre-rendered assets bundled with the repository. Pillow-based
procedural cards remain only as an offline fallback when an asset is missing.
No external image API, credentials, GPU, or paid service is required.
"""
from __future__ import annotations

import hashlib
import io
import random
import os
import logging
from pathlib import Path
from functools import lru_cache
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1200, 720
log = logging.getLogger("isekai-grave.art")
ART_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "world_art"
ART_STYLE = ("Premium cinematic fantasy MMORPG concept art, highly detailed painterly realism, richly layered environment, physically based materials, dramatic atmospheric lighting, volumetric rays, intricate architecture and props, believable scale and perspective, professional AAA game key art, 16:9 landscape composition, no text, no letters, no watermark. Dark-fantasy-adventure aesthetic with rich color grading.")
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
    "forest": ((8, 42, 35), (30, 105, 70), (137, 224, 135)),
    "sea": ((5, 28, 58), (17, 103, 145), (95, 220, 239)),
    "ruins": ((37, 30, 46), (103, 77, 67), (224, 181, 112)),
    "castle": ((24, 27, 57), (67, 75, 120), (184, 197, 255)),
    "volcano": ((45, 12, 12), (137, 39, 20), (255, 151, 52)),
    "desert": ((72, 43, 16), (174, 111, 43), (255, 218, 126)),
    "snow": ((24, 47, 73), (94, 139, 176), (205, 239, 255)),
    "swamp": ((13, 39, 32), (57, 86, 57), (166, 214, 112)),
    "forge": ((48, 20, 12), (128, 57, 26), (255, 179, 67)),
    "inventory": ((24, 34, 58), (65, 83, 115), (220, 205, 157)),
    "arena": ((52, 17, 32), (128, 43, 54), (255, 184, 99)),
    "profile": ((30, 20, 55), (83, 44, 118), (255, 204, 119)),
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
    elif kind in {"forest", "sea", "ruins", "castle", "volcano", "desert", "snow", "swamp"}:
        _draw_island(d, accent, seed)
        # Region-specific silhouettes make each selected biome visually distinct.
        if kind == "forest":
            for x in (650, 760, 940, 1080):
                d.polygon([(x,430),(x-65,250),(x-15,285),(x,170),(x+18,285),(x+65,245),(x+35,430)], fill=(12,54,42,255), outline=accent)
        elif kind == "sea":
            for yy in (485,535,585):
                d.arc((620,yy-35,1170,yy+45), 0, 180, fill=accent, width=8)
        elif kind == "ruins":
            for x in (680,820,960):
                d.rectangle((x,300,x+28,480), fill=(88,75,72,255), outline=accent, width=3)
            d.polygon([(650,305),(850,250),(1010,305)], fill=(105,85,76,255), outline=accent)
        elif kind == "castle":
            d.rectangle((720,260,1030,455), fill=(37,43,76,255), outline=accent, width=4)
            for x in (700,800,950,1050):
                d.rectangle((x,220,x+55,330), fill=(43,49,82,255), outline=accent, width=3)
                d.polygon([(x-8,222),(x+27,165),(x+63,222)], fill=(52,55,90,255), outline=accent)
        elif kind == "volcano":
            d.polygon([(650,450),(850,130),(1080,450)], fill=(56,30,32,255), outline=accent, width=5)
            d.arc((800,115,900,210), 180, 350, fill=accent, width=10)
        elif kind == "desert":
            d.ellipse((700,380,1050,600), fill=(166,111,47,255), outline=accent, width=4)
            d.ellipse((850,420,1130,610), fill=(194,139,67,255), outline=accent, width=4)
        elif kind == "snow":
            d.polygon([(640,460),(810,170),(920,330),(1030,135),(1160,460)], fill=(190,215,232,255), outline=accent, width=4)
        elif kind == "swamp":
            for x in (700,850,1010):
                d.line((x,300,x-20,500), fill=(30,65,43,255), width=14)
                d.ellipse((x-70,250,x+45,335), fill=(32,78,46,255), outline=accent, width=3)
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


def _art_prompt(kind: str, title: str, subtitle: str = "", stats=None) -> str:
    """Create a scene-specific prompt; visible UI text is overlaid separately by Telegram."""
    scenes = {
        "world": "A breathtaking establishing view of a vast interconnected fantasy kingdom, distant castles, roads, settlements and atmospheric landscape",
        "boss": "A colossal terrifying ancient dragon world boss facing tiny adventurers, immense scale, dramatic fire and smoke",
        "npc": "A memorable fantasy RPG non-player character in a richly detailed lived-in location, expressive cinematic character portrait",
        "region": "A distinctive fantasy wilderness region with landmarks, layered terrain and environmental storytelling",
        "chronicle": "An ancient royal archive hall with open illuminated chronicle tome, relics, candles and magical history",
        "news": "A fantasy kingdom news scene showing heralds announcing a major event in a crowded medieval square",
        "character": "A legendary RPG hero character showcase, full-body heroic pose, ornate armor, signature weapon and magical effects",
        "market": "A bustling medieval fantasy bazaar packed with detailed stalls, merchants, rare glowing artifacts, coins and adventurers",
        "guild": "A grand fantasy guild headquarters interior with banners, a war table, adventurers and warm cinematic lighting",
        "quest": "An evocative fantasy quest location with a mysterious objective, ancient ruins, treasure and environmental clues",
        "forest": "An enchanted ancient forest with enormous trees, shafts of sunlight, mossy ruins and magical fireflies",
        "sea": "A dramatic fantasy storm coast, crashing waves, ships, sea cliffs and distant mysterious islands",
        "ruins": "Ancient colossal civilization ruins reclaimed by nature, intricate stonework and shafts of golden light",
        "castle": "A majestic fantasy castle and its surrounding medieval city, intricate towers, banners and dramatic landscape",
        "volcano": "A dangerous volcanic wasteland with rivers of lava, ash clouds, black rock and glowing fissures",
        "desert": "A vast fantasy desert with monumental sandstone ruins, dunes, caravan silhouettes and warm atmospheric light",
        "snow": "A majestic frozen mountain kingdom with icebound towers, snow-covered pines and aurora",
        "swamp": "An eerie fantasy swamp with twisted trees, luminous plants, ancient stone fragments and ground mist",
        "forge": "A legendary dwarven fantasy forge, blazing furnace, master-crafted weapons and glowing molten metal",
        "inventory": "An exquisite fantasy adventurer's equipment display, ornate weapons, armor, potions and relics arranged on a table",
        "arena": "A monumental fantasy coliseum filled with spectators, banners, dramatic sunlight and battle-ready champions",
        "profile": "A premium fantasy RPG character portrait backdrop with elegant magical motifs and cinematic depth",
    }
    scene = scenes.get(str(kind), scenes["world"])
    context = f" Scene title: {str(title)[:100]}."
    if subtitle:
        context += f" Story context: {str(subtitle)[:240]}."
    return f"{ART_STYLE} Scene: {scene}.{context} The image must communicate the scene visually; do not render any typography."


# Pre-rendered, bundled art assets: no external API, API key, GPU, or paid service.
# Assets are part of the deployment package, so they survive worker restarts/redeploys.
ART_ASSET_MAP = {
    "world": "floating_island.jpg",
    "region": "floating_island.jpg",
    "forest": "floating_island.jpg",
    "sea": "floating_island.jpg",
    "ruins": "guild_hall.jpg",
    "castle": "floating_island.jpg",
    "volcano": "world_boss.jpg",
    "desert": "market.jpg",
    "snow": "floating_island.jpg",
    "swamp": "guild_hall.jpg",
    "boss": "world_boss.jpg",
    "npc": "guild_hall.jpg",
    "chronicle": "guild_hall.jpg",
    "news": "guild_hall.jpg",
    "character": "character.jpg",
    "profile": "character.jpg",
    "market": "market.jpg",
    "guild": "guild_hall.jpg",
    "quest": "floating_island.jpg",
    "inventory": "character.jpg",
    "arena": "world_boss.jpg",
    "forge": "market.jpg",
}

@lru_cache(maxsize=32)
def _load_prebuilt_art(kind: str) -> Optional[bytes]:
    filename = ART_ASSET_MAP.get(str(kind), ART_ASSET_MAP["world"])
    path = ART_ASSET_DIR / filename
    try:
        payload = path.read_bytes()
        # Validate bundled asset once before caching it.
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        return payload
    except (OSError, ValueError) as exc:
        log.warning("Bundled artwork unavailable (%s): %s", path, exc)
        return None

async def send_world_art(message, kind: str, title: str, subtitle: str = "", stats=None) -> bool:
    """Send a bundled cinematic artwork asset without calling paid image APIs."""
    try:
        import asyncio
        from aiogram.types import BufferedInputFile
        payload = await asyncio.to_thread(_load_prebuilt_art, str(kind))
        if payload is None:
            # Last-resort offline fallback if an asset was accidentally omitted.
            payload = await asyncio.to_thread(render_world_art, kind, title, subtitle, stats)
            filename = f"isekai-{kind}.png"
        else:
            filename = f"isekai-{kind}.jpg"
        await message.reply_photo(BufferedInputFile(payload, filename=filename))
        return True
    except Exception:
        log.exception("Could not send world artwork (%s)", kind)
        return False


async def send_region_art(message, biome_key: str, title: str, subtitle: str = "", stats=None) -> bool:
    """Render a biome-specific image for the selected exploration region."""
    themes = {
        "forest": "forest", "sea": "sea", "ruins": "ruins",
        "city": "castle", "volcano": "volcano", "desert": "desert",
        "snow": "snow", "swamp": "swamp",
    }
    theme = themes.get(str(biome_key), "region")
    return await send_world_art(message, theme, title, subtitle, stats)
