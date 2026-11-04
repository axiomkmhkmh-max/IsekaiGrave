"""🔥 کوره‌ی روح: تجهیز، ارتقای ستاره‌ای، ادغام آیتم‌ها، سوزوندن و بازیابیِ روح (جادوگر).
هر خرجی اینجا GS رو «می‌سوزونه» (sink) و قدرتِ تجهیز سقف داره (GEAR_CAP)؛ پس پول‌دارترین، شکست‌ناپذیر نمیشه."""

import random
from typing import Optional

from config import GS, INV_CAP, WITCH_RESTORE_COST
from database import store
from economy import burn, debit, fmt, inv_update, log_tx, ulock
from players import grant, heal_bonus
from rules import (
    FORGE_NAMES, FUSE_COST, FUSE_COUNT, GEAR_CAP, RARITIES, can_equip, forged_item,
    gear_bonus, is_tradable, item_hash, item_stars, rarity_idx, upgrade_cost, with_stars,
)
from ui import back_kb, btn, kb, panel, say, show
from utils import esc


# ───────────────────────────── 🎒 کوله‌پشتی و انتخاب آیتم ─────────────────────────────
async def inventory_panel(m, doc: Optional[dict] = None):
    uid = m.from_user.id
    doc = doc or await store.get(uid)
    inv = doc.get("inventory") or []
    eq = (doc.get("equip") or {}).get("item")
    lines = []
    if eq:
        lines.append(f"⚔️ <b>روح‌سلاح:</b> {esc(eq)} (+{gear_bonus(eq)} حمله)")
        lines.append("┈┈┈┈┈┈┈┈┈┈")
    for i, x in enumerate(inv, 1):
        tag = " 🔗" if not is_tradable(x) else ""
        lines.append(f"{i}. {esc(x)}{tag}")
    if not inv:
        lines.append("کوله‌پشتیت خالیه. با ماجراجویی چیز جمع کن! 🎒")
    nums = [btn(str(i), f"inv:sel:{i - 1}:{uid}", "blue") for i in range(1, len(inv) + 1)]
    rows = [nums[i:i + 5] for i in range(0, len(nums), 5)]
    rows.append([btn("🪦 بازار روح", f"ex:home:{uid}", "green"), btn("🔥 کوره", f"fg:home:{uid}", "red")])
    rows.append(back_kb(uid))
    foot = f"🪙 {GS}: <b>{doc.get('gold', 0)}</b> | 🎒 {len(inv)}/{INV_CAP}  |  🔗 = روح‌پیوند (غیرقابل فروش)\nیه شماره بزن تا بفروشی، تجهیز کنی یا بسوزونی."
    await show(m, panel("brown", "🎒", "کوله‌پشتی", lines, foot), kb(*rows))


async def inv_select(m, idx0: int):
    uid = m.from_user.id
    doc = await store.get(uid)
    inv = doc.get("inventory") or []
    if idx0 < 0 or idx0 >= len(inv):
        await inventory_panel(m, doc)
        return
    item = inv[idx0]
    h = item_hash(item)
    lines = [esc(item)]
    rows = []
    if is_tradable(item):
        lines.append("🏷 قابل فروش در بازار روح")
        rows.append([btn("🏷 بفروش", f"ex:p:{idx0}:{h}:{uid}", "green")])
    else:
        lines.append("🔗 روح‌پیوند: به تو بسته شده و قابل فروش/معامله نیست.")
    if can_equip(item):
        lines.append(f"⚔️ قابل تجهیز: +{gear_bonus(item)} حمله در نبردها")
        rows.append([btn("⚔️ تجهیز", f"fg:eq:{idx0}:{h}:{uid}", "blue")])
    rows.append([btn("🔥 بسوزان (حذف دائمی)", f"fg:bn:{idx0}:{h}:{uid}", "red")])
    rows.append([btn("🔙 کوله‌پشتی", f"m:inv:{uid}", "blue")])
    await show(m, panel("brown", "🎒", f"آیتم شماره‌ی {idx0 + 1}", lines), kb(*rows))


# ───────────────────────────── ⚔️ تجهیز ─────────────────────────────
async def equip_item(m, idx0: int, h: Optional[str]):
    uid = m.from_user.id
    got: dict = {}

    def mut(inv, doc):
        if idx0 < 0 or idx0 >= len(inv) or (h and item_hash(inv[idx0]) != h) or not can_equip(inv[idx0]):
            return None
        got["new"] = inv[idx0]
        old = (doc.get("equip") or {}).get("item")
        got["old"] = old
        del inv[idx0]
        if old:
            inv.append(old)
        return inv

    async with ulock(uid):
        res = await inv_update(uid, mut, guard=("equip",), upd_fn=lambda d: {"$set": {"equip": {"item": got["new"]}}})
    if not res:
        await say(m, "این آیتم قابل تجهیز نیست یا کوله‌پشتیت عوض شده. 🎒", "⚔️", "تجهیز", "red")
        return
    lines = [f"⚔️ {esc(got['new'])} حالا روح‌سلاحته: <b>+{gear_bonus(got['new'])} حمله</b>"]
    if got["old"]:
        lines.append(f"↩️ {esc(got['old'])} برگشت کوله‌پشتی.")
    await show(m, panel("green", "⚔️", "تجهیز شد!", lines), kb([btn("🔥 کوره", f"fg:home:{uid}", "red"), btn("🎒", f"m:inv:{uid}", "blue")]))


async def equip_command(m, num: int):
    await equip_item(m, num - 1, None)


async def unequip(m):
    uid = m.from_user.id
    got: dict = {}

    def mut(inv, doc):
        eq = (doc.get("equip") or {}).get("item")
        if not eq or len(inv) >= INV_CAP:
            return None
        got["item"] = eq
        inv.append(eq)
        return inv

    async with ulock(uid):
        res = await inv_update(uid, mut, guard=("equip",), upd={"$set": {"equip": None}})
    if not res:
        await say(m, "چیزی تجهیز نیست یا کوله‌پشتیت پره. 🎒", "⚔️", "تجهیز", "red")
        return
    await forge_home(m)


# ───────────────────────────── ⭐ ارتقا ─────────────────────────────
async def upgrade(m):
    uid = m.from_user.id
    async with ulock(uid):
        doc = await store.get(uid)
        item = (doc.get("equip") or {}).get("item")
        cost = upgrade_cost(item) if item else None
        if not item or cost is None:
            await say(m, "روح‌سلاحی نداری یا به سقفِ ستاره رسیده. ⭐", "🔥", "کوره‌ی روح", "red")
            return
        new = with_stars(item, item_stars(item) + 1)
        res = await store.users.update_one(
            {"user_id": uid, "equip.item": item, "gold": {"$gte": cost}},
            {"$inc": {"gold": -cost}, "$set": {"equip.item": new}})
        if not res.modified_count:
            await say(m, f"برای ارتقا {fmt(cost)} لازمه و موجودیت کمه (یا تجهیزت عوض شده). 🪙", "🔥", "کوره‌ی روح", "red")
            return
        await log_tx(uid, -cost, "forge", "upgrade")
        await burn(cost, "forge")
    await show(m, panel("green", "⭐", "ارتقا موفق!", [
        f"{esc(new)}", f"💥 بونوس حمله: <b>+{gear_bonus(new)}</b> (سقف {GEAR_CAP})", f"🔥 −{fmt(cost)} (سوخت)",
    ], "💅 <i>«هر ستاره یه روحِ دیگه‌ست که توش حبس شد. قشنگه.»</i>"),
        kb([btn("🔥 کوره", f"fg:home:{uid}", "red")]))


# ───────────────────────────── 🔄 ادغام ─────────────────────────────
def _fuse_candidates(inv: list, tier: int) -> list:
    return [i for i, x in enumerate(inv) if rarity_idx(x) == tier and is_tradable(x) and item_stars(x) == 0]


async def fuse(m, tier: int):
    uid = m.from_user.id
    if not (0 <= tier < len(FUSE_COST)):
        return
    cost = FUSE_COST[tier]
    out: dict = {}

    def mut(inv, doc):
        idxs = _fuse_candidates(inv, tier)[:FUSE_COUNT]
        if len(idxs) < FUSE_COUNT:
            return None
        out["name"] = random.choice(FORGE_NAMES)
        for i in reversed(idxs):
            del inv[i]
        inv.append(forged_item(tier + 1, out["name"]))
        out["item"] = inv[-1]
        return inv

    async with ulock(uid):
        res = await inv_update(uid, mut, filt={"gold": {"$gte": cost}}, upd={"$inc": {"gold": -cost}})
        if res:
            await log_tx(uid, -cost, "forge", "fuse")
            await burn(cost, "forge")
    if not res:
        await say(m, f"برای ادغام {FUSE_COUNT} آیتمِ «{RARITIES[tier][0]}» (بدون ستاره، قابل‌معامله) و {fmt(cost)} لازمه. 🔥",
                  "🔥", "کوره‌ی روح", "red")
        return
    await show(m, panel("purple", "🔄", "ادغام کامل شد!", [
        f"🔥 {FUSE_COUNT} × {RARITIES[tier][0]} + {fmt(cost)}", f"✨ {esc(out['item'])}",
    ], "💅 <i>«سه تا آشغال، یه آشغالِ بهتر. معجزه‌ی کوره.»</i>"), kb([btn("🔥 کوره", f"fg:home:{uid}", "red"), btn("🎒", f"m:inv:{uid}", "blue")]))


# ───────────────────────────── 🔥 سوزوندن ─────────────────────────────
async def burn_confirm(m, idx0: int, h: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    inv = doc.get("inventory") or []
    if idx0 >= len(inv) or item_hash(inv[idx0]) != h:
        await inventory_panel(m, doc)
        return
    await show(m, panel("red", "🔥", "مطمئنی؟", [f"{esc(inv[idx0])}", "برای همیشه می‌سوزه و هیچ پولی نمی‌گیری."]),
               kb([btn("🔥 آره، بسوزون", f"fg:bn2:{idx0}:{h}:{uid}", "red"), btn("🔙 نه", f"m:inv:{uid}", "green")]))


async def burn_do(m, idx0: int, h: str):
    uid = m.from_user.id
    gone: dict = {}

    def mut(inv, doc):
        if idx0 >= len(inv) or item_hash(inv[idx0]) != h:
            return None
        gone["item"] = inv[idx0]
        del inv[idx0]
        return inv

    async with ulock(uid):
        res = await inv_update(uid, mut)
    if not res:
        await say(m, "آیتم دیگه اونجا نیست. 🎒", "🔥", "کوره", "red")
        return
    await show(m, panel("red", "🔥", "سوخت", [f"{esc(gone['item'])} خاکستر شد."]), kb([btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "blue")]))


# ───────────────────────────── 🕯 بازیابی روح (جادوگر) ─────────────────────────────
async def witch_restore(m):
    uid = m.from_user.id
    async with ulock(uid):
        doc = await store.get(uid)
        if int(doc.get("survival_rate", 0)) >= 95:
            await say(m, "نرخ بقات تقریباً کامله؛ پولت رو نگه دار. 🕯", "🧙‍♀️", "جادوگرِ ناراضی", "purple")
            return
        if not await debit(uid, WITCH_RESTORE_COST, "witch"):
            await say(m, f"بازیابیِ روح {fmt(WITCH_RESTORE_COST)} میشه و موجودیت کمه. 🪙", "🧙‍♀️", "جادوگرِ ناراضی", "purple")
            return
        h = heal_bonus(doc, 30)
        d2, _ = await grant(uid, survival=h, xp=4)
    await show(m, panel("purple", "🕯", "روحت ترمیم شد", [
        f"💚 +{h}٪ بقا → <b>{d2['survival_rate']}٪</b>", f"🔥 −{fmt(WITCH_RESTORE_COST)}",
    ], "🧙‍♀️ <i>«بدون چایِ سرد، بدون نفرین. این یکی رو مجانی دعا کردم… جدی نیستم، پولش رو گرفتم.»</i>"),
        kb([btn("🔥 کوره", f"fg:home:{uid}", "red"), btn("🌙 منو", f"m:main:{uid}", "green")]))


# ───────────────────────────── 🔥 خانه‌ی کوره ─────────────────────────────
async def forge_home(m):
    uid = m.from_user.id
    doc = await store.get(uid)
    inv = doc.get("inventory") or []
    eq = (doc.get("equip") or {}).get("item")
    lines = [f"🪙 موجودی: <b>{fmt(doc.get('gold', 0))}</b>", "┈┈┈┈┈┈┈┈┈┈"]
    rows = []
    if eq:
        cost = upgrade_cost(eq)
        lines.append(f"⚔️ <b>روح‌سلاح:</b> {esc(eq)}\n      +{gear_bonus(eq)} حمله (سقف {GEAR_CAP})")
        if cost:
            rows.append([btn(f"⭐ ارتقا ({cost} {GS})", f"fg:up:{uid}", "green")])
        rows.append([btn("↩️ درآوردن تجهیز", f"fg:un:{uid}", "blue")])
    else:
        lines.append("⚔️ روح‌سلاحی نداری: از «کوله‌پشتی» یه آیتم رو تجهیز کن.")
    lines.append("┈┈┈┈┈┈┈┈┈┈")
    lines.append(f"🔄 <b>ادغام:</b> {FUSE_COUNT} آیتمِ هم‌کمیاب (قابل‌معامله، بی‌ستاره) → ۱ آیتمِ یک پله بالاتر")
    fz = []
    for t in range(len(FUSE_COST)):
        n = len(_fuse_candidates(inv, t))
        if n >= FUSE_COUNT:
            fz.append(btn(f"{RARITIES[t][1]}→{RARITIES[t + 1][1]} ({FUSE_COST[t]})", f"fg:fz:{t}:{uid}", "red"))
    if fz:
        rows.append(fz[:2])
        if len(fz) > 2:
            rows.append(fz[2:])
    else:
        lines.append("      (الان آیتمِ کافی برای ادغام نداری)")
    rows.append([btn(f"🕯 بازیابی روح ({WITCH_RESTORE_COST} {GS})", f"fg:rs:{uid}", "blue")])
    rows.append([btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "blue"), btn("🪦 بازار", f"ex:home:{uid}", "green")])
    rows.append(back_kb(uid))
    await show(m, panel("red", "🔥", "کوره‌ی روح", lines, "💅 <i>«هر چی بسوزونی، یه چیزِ بدتر جاش درمیاد. اسمش پیشرفته.»</i>"), kb(*rows))


async def forge_cb(m, parts: list):
    act = parts[1]
    if act == "home":
        await forge_home(m)
    elif act == "eq" and len(parts) >= 5:
        await equip_item(m, int(parts[2]), parts[3])
    elif act == "un":
        await unequip(m)
    elif act == "up":
        await upgrade(m)
    elif act == "fz":
        await fuse(m, int(parts[2]))
    elif act == "bn" and len(parts) >= 5:
        await burn_confirm(m, int(parts[2]), parts[3])
    elif act == "bn2" and len(parts) >= 5:
        await burn_do(m, int(parts[2]), parts[3])
    elif act == "rs":
        await witch_restore(m)


async def inv_cb(m, parts: list):
    if parts[1] == "sel":
        await inv_select(m, int(parts[2]))
    else:
        await inventory_panel(m)
