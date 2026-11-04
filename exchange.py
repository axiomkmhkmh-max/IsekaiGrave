"""🪦 بازار روح (Grave Exchange): بازارِ بازیکن‌به‌بازیکن با GS.

امنیت (بدون تراکنشِ چنداسنادی، با حالت‌های اتمیک):
• فروش: اول آیتم از کوله‌ی فروشنده «اتمیک» برداشته میشه (CAS)، بعد آگهی ساخته میشه. شکستِ ساخت = برگشتِ آیتم.
• خرید: آگهی active→locked (فقط یک نفر برنده‌ست) → کم‌کردنِ GS و دادنِ آیتم در «یک» آپدیتِ تک‌سندیِ خریدار
  (شرط gold>=price و جای خالی) → locked→sold → واریزِ فروشنده (idempotent با مارکر روی سندِ خودش).
• لغو: active→cancelling → برگشتِ آیتم (idempotent با مارکر) → cancelled. اگه کوله‌پشتی پر باشه، آگهی فعال می‌مونه.
• ریکاوریِ خودکار: آگهی‌های نیمه‌کاره (کرش وسط کار) موقع استارت و هر چند دقیقه یک‌بار تمیز میشن."""

import secrets
import time
from datetime import timedelta
from typing import Optional

from bson import ObjectId
from pymongo import ReturnDocument

from config import (
    EXCHANGE_FEE_PCT, EXCHANGE_FEE_PCT_CAPITAL, EXCHANGE_MAX_LISTINGS, EXCHANGE_MAX_PRICE,
    EXCHANGE_MIN_LEVEL, EXCHANGE_PAGE, GS, GS_DAILY_SOFT_CAP, INV_CAP, LISTING_TTL, log,
)
from database import store
from economy import burn, fmt, inv_update, log_tx, terr_perks, ulock
from players import refresh_titles
from quests import quest_progress
from rules import base_value, exchange_fee, is_tradable, item_hash
from ui import back_kb, btn, kb, panel, say, show
from utils import day_key, esc, utcnow


NONCE_TTL = 5 * 60
_last_recover = 0.0


# ───────────────────────────── 🧰 کمک‌ها ─────────────────────────────
def _oid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(s)
    except Exception:
        return None


async def _make_pending(uid: int, data: dict) -> str:
    n = secrets.token_hex(3)
    await store.users.update_one({"user_id": uid}, {"$set": {"pending_ex": {"n": n, "at": utcnow(), **data}}})
    return n


async def _consume_pending(uid: int, nonce: str, kind: str) -> Optional[dict]:
    """یک‌بارمصرف: دو کلیکِ پشت‌سرهم روی «تأیید» فقط یکیش رد میشه."""
    d = await store.users.find_one_and_update(
        {"user_id": uid, "pending_ex.n": nonce, "pending_ex.k": kind},
        {"$set": {"pending_ex": None}}, return_document=ReturnDocument.BEFORE)
    if not d:
        return None
    p = d["pending_ex"]
    if (utcnow() - p["at"]).total_seconds() > NONCE_TTL:
        return None
    return p


async def _fee_pct_for(uid: int) -> int:
    perks = await terr_perks(await store.get(uid))
    return EXCHANGE_FEE_PCT_CAPITAL if "capital" in perks else EXCHANGE_FEE_PCT


def _home_kb(uid: int):
    return kb(
        [btn("🛒 مرور آگهی‌ها", f"ex:b:0:{uid}", "green"), btn("📜 آگهی‌های من", f"ex:my:{uid}", "blue")],
        [btn("🧾 تراکنش‌ها", f"ex:tx:{uid}", "blue"), btn("🎒 فروش از کوله‌پشتی", f"m:inv:{uid}", "green")],
        back_kb(uid),
    )


# ───────────────────────────── 🪦 خانه‌ی بازار ─────────────────────────────
async def exchange_home(m, bot=None):
    uid = m.from_user.id
    await recover_exchange(bot or getattr(m, "bot", None), throttle=True)
    doc = await store.get(uid)
    total = await store.listings.count_documents({"status": "active", "expires_at": {"$gt": utcnow()}})
    mine = await store.listings.count_documents({"seller": uid, "status": "active"})
    pct = await _fee_pct_for(uid)
    await show(m, panel("black", "🪦", "بازار روح (Grave Exchange)", [
        "اینجا ارواحِ سرگردان آیتم‌هاشون رو با GS دست‌به‌دست می‌کنن.",
        f"🪙 موجودی تو: <b>{fmt(doc.get('gold', 0))}</b>",
        f"📦 آگهیِ فعال: <b>{total}</b> | آگهی‌های تو: <b>{mine}/{EXCHANGE_MAX_LISTINGS}</b>",
        f"🔥 کارمزد فروش: <b>{pct}٪</b> (سوخته میشه) — مالکِ «پایتخت درخشان» کمتر می‌ده",
    ], "برای فروش: «کوله‌پشتی» ← انتخاب آیتم ← بفروش | یا بنویس «<b>فروش ۳ ۱۲۰</b>» (شماره‌ی آیتم، قیمت)"),
        _home_kb(uid))


# ───────────────────────────── 🛒 مرور ─────────────────────────────
async def browse(m, page: int = 0):
    uid = m.from_user.id
    page = max(0, page)
    q = {"status": "active", "expires_at": {"$gt": utcnow()}}
    total = await store.listings.count_documents(q)
    pages = max(1, (total + EXCHANGE_PAGE - 1) // EXCHANGE_PAGE)
    page = min(page, pages - 1)
    rows = await store.listings.find(q).sort("created_at", -1).skip(page * EXCHANGE_PAGE).limit(EXCHANGE_PAGE).to_list(EXCHANGE_PAGE)
    if not rows:
        await show(m, panel("black", "🪦", "بازار روح", ["هنوز آگهی‌ای نیست. اولین فروشنده باش! 🕯"]),
                   kb([btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "green")], [btn("🔙 بازار", f"ex:home:{uid}", "blue")]))
        return
    lines, buy_row = [], []
    for i, L in enumerate(rows, 1):
        mine = L["seller"] == uid
        lines.append(f"<b>{i}.</b> {esc(L['item'])}\n      💰 <b>{fmt(L['price'])}</b> · 👤 {esc(L.get('seller_name'))}" + (" (تو)" if mine else ""))
        if not mine:
            buy_row.append(btn(f"🛒 {i}", f"ex:buy:{L['_id']}:{uid}", "green"))
    nav = []
    if page > 0:
        nav.append(btn("⬅️", f"ex:b:{page - 1}:{uid}", "blue"))
    nav.append(btn(f"{page + 1}/{pages}", f"ex:b:{page}:{uid}", "blue"))
    if page < pages - 1:
        nav.append(btn("➡️", f"ex:b:{page + 1}:{uid}", "blue"))
    await show(m, panel("black", "🪦", "آگهی‌های بازار روح", lines, "شماره‌ی آگهی رو بزن تا خرید رو تأیید کنی."),
               kb(buy_row, nav, [btn("🔙 بازار", f"ex:home:{uid}", "blue")]))


# ───────────────────────────── 📜 آگهی‌ها و تراکنش‌های من ─────────────────────────────
async def my_listings(m):
    uid = m.from_user.id
    rows = await store.listings.find({"seller": uid, "status": {"$in": ["active", "cancelling"]}}).sort("created_at", -1).to_list(10)
    if not rows:
        await show(m, panel("black", "📜", "آگهی‌های من", ["آگهیِ فعالی نداری."]), kb([btn("🔙 بازار", f"ex:home:{uid}", "blue")]))
        return
    now = utcnow()
    lines, btns = [], []
    for i, L in enumerate(rows, 1):
        left = int((L["expires_at"] - now).total_seconds() // 3600)
        st = "⏳ منقضی‌شده (فقط پس‌گیری)" if L["expires_at"] <= now else f"🕐 {max(left, 0)} ساعت مونده"
        lines.append(f"<b>{i}.</b> {esc(L['item'])}\n      💰 {fmt(L['price'])} · {st}")
        btns.append([btn(f"❌ لغو و پس‌گرفتنِ {i}", f"ex:cx:{L['_id']}:{uid}", "red")])
    await show(m, panel("black", "📜", "آگهی‌های من", lines, "آیتمِ لغوشده برمی‌گرده کوله‌پشتی (جا باید داشته باشی)."),
               kb(*btns, [btn("🔙 بازار", f"ex:home:{uid}", "blue")]))


async def tx_history(m):
    uid = m.from_user.id
    rows = await store.listings.find({"status": "sold", "$or": [{"seller": uid}, {"buyer": uid}]}).sort("sold_at", -1).limit(8).to_list(8)
    lines = []
    for L in rows:
        if L["seller"] == uid:
            lines.append(f"🟢 فروش: {esc(L['item'])} → <b>+{fmt(L.get('net', 0))}</b> (کارمزد {L.get('fee', 0)})")
        else:
            lines.append(f"🔴 خرید: {esc(L['item'])} → <b>−{fmt(L['price'])}</b>")
    await show(m, panel("black", "🧾", "تراکنش‌های اخیر", lines or ["هنوز معامله‌ای نداشتی."]),
               kb([btn("🔙 بازار", f"ex:home:{uid}", "blue")]))


# ───────────────────────────── 🏷 فروش ─────────────────────────────
def _validate_seller(doc: dict) -> Optional[str]:
    if int(doc.get("level", 1)) < EXCHANGE_MIN_LEVEL:
        return f"برای معامله تو بازار روح حداقل سطح {EXCHANGE_MIN_LEVEL} لازمه. ⭐"
    return None


async def price_presets(m, idx0: int, h: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    inv = doc.get("inventory") or []
    if idx0 >= len(inv) or item_hash(inv[idx0]) != h:
        await say(m, "کوله‌پشتیت عوض شده؛ دوباره بازش کن. 🎒", "🎒", "فروش", "brown")
        return
    item = inv[idx0]
    if not is_tradable(item):
        await say(m, "این آیتم «روح‌پیوند»ه و قابل فروش نیست. 🔗", "🔗", "فروش", "brown")
        return
    base = base_value(item)
    prices = sorted({max(1, base), max(2, base * 2), max(3, base * 4)})
    await show(m, panel("black", "🏷", "قیمتِ فروش", [
        f"{esc(item)}", f"💡 ارزشِ پایه: <b>{fmt(base)}</b>",
        "یه قیمت انتخاب کن یا بنویس «<b>فروش {} قیمت</b>».".format(idx0 + 1),
    ]), kb([btn(fmt(p), f"ex:s:{idx0}:{h}:{p}:{uid}", "green") for p in prices], [btn("🔙 کوله‌پشتی", f"m:inv:{uid}", "blue")]))


async def sell_confirm(m, idx0: int, h: Optional[str], price: int):
    uid = m.from_user.id
    doc = await store.get(uid)
    err = _validate_seller(doc)
    inv = doc.get("inventory") or []
    if not err and (idx0 < 0 or idx0 >= len(inv) or (h and item_hash(inv[idx0]) != h)):
        err = "آیتم پیدا نشد یا کوله‌پشتیت عوض شده. دوباره بازش کن. 🎒"
    if not err and not is_tradable(inv[idx0]):
        err = "این آیتم «روح‌پیوند»ه (یا نفرین‌شده) و قابل فروش نیست. 🔗"
    if not err and not (1 <= price <= EXCHANGE_MAX_PRICE):
        err = f"قیمت باید بین ۱ تا {EXCHANGE_MAX_PRICE} {GS} باشه."
    if not err and await store.listings.count_documents({"seller": uid, "status": "active"}) >= EXCHANGE_MAX_LISTINGS:
        err = f"حداکثر {EXCHANGE_MAX_LISTINGS} آگهیِ فعال می‌تونی داشته باشی."
    if err:
        await say(m, err, "🪦", "بازار روح", "black")
        return
    item = inv[idx0]
    h = item_hash(item)
    pct = await _fee_pct_for(uid)
    fee = exchange_fee(price, pct)
    n = await _make_pending(uid, {"k": "list", "i": idx0, "h": h, "p": price})
    await show(m, panel("black", "🏷", "تأیید آگهی", [
        f"{esc(item)}", f"💰 قیمت: <b>{fmt(price)}</b>",
        f"🔥 کارمزد: {fmt(fee)} ← خالص برای تو: <b>{fmt(price - fee)}</b>",
        "آیتم تا فروش/لغو از کوله‌پشتیت خارج میشه و ۷۲ ساعت آگهی فعاله.",
    ]), kb([btn("✅ ثبت آگهی", f"ex:lst:{n}:{uid}", "green"), btn("🔙 انصراف", f"m:inv:{uid}", "red")]))


async def sell_command(m, num: int, price: int):
    await sell_confirm(m, num - 1, None, price)


async def do_list(m, nonce: str):
    uid = m.from_user.id
    async with ulock(uid):
        p = await _consume_pending(uid, nonce, "list")
        if not p:
            await say(m, "این تأییدیه قبلاً استفاده شده یا منقضی شده. 🕯", "🪦", "بازار روح", "black")
            return
        doc = await store.get(uid)
        err = _validate_seller(doc)
        if not err and await store.listings.count_documents({"seller": uid, "status": "active"}) >= EXCHANGE_MAX_LISTINGS:
            err = f"حداکثر {EXCHANGE_MAX_LISTINGS} آگهیِ فعال می‌تونی داشته باشی."
        if err:
            await say(m, err, "🪦", "بازار روح", "black")
            return
        idx0, h, price = p["i"], p["h"], p["p"]
        taken: dict = {}

        def mut(inv, d):
            if idx0 >= len(inv) or item_hash(inv[idx0]) != h or not is_tradable(inv[idx0]):
                return None
            taken["item"] = inv[idx0]
            del inv[idx0]
            return inv

        if not await inv_update(uid, mut):
            await say(m, "آیتم دیگه تو کوله‌پشتیت نیست (یا عوض شده). 🎒", "🪦", "بازار روح", "black")
            return
        item = taken["item"]
        try:
            now = utcnow()
            res = await store.listings.insert_one({
                "seller": uid, "seller_name": doc.get("first_name") or "ناشناس", "item": item, "price": price,
                "status": "active", "created_at": now, "expires_at": now + timedelta(seconds=LISTING_TTL),
            })
        except Exception:
            log.exception("listing insert failed; returning item")
            await store.users.update_one({"user_id": uid}, {"$push": {"inventory": item}})
            await say(m, "ثبت آگهی خطا داد؛ آیتمت برگشت کوله‌پشتی. دوباره امتحان کن. 🛠", "🛠", "بازار روح", "red")
            return
        await show(m, panel("green", "🪦", "آگهی ثبت شد!", [
            f"{esc(item)}", f"💰 {fmt(price)}", "تا خریدار پیدا بشه، آیتم امانتِ بازاره. ⏳",
        ]), kb([btn("📜 آگهی‌های من", f"ex:my:{uid}", "blue"), btn("🪦 بازار", f"ex:home:{uid}", "green")]))


# ───────────────────────────── 🛒 خرید ─────────────────────────────
async def buy_prompt(m, oid_s: str):
    uid = m.from_user.id
    oid = _oid(oid_s)
    L = await store.listings.find_one({"_id": oid, "status": "active", "expires_at": {"$gt": utcnow()}}) if oid else None
    if not L:
        await say(m, "این آگهی دیگه فعال نیست (فروخته شد یا لغو شد). 🕯", "🪦", "بازار روح", "black",
                  kb([btn("🛒 مرور", f"ex:b:0:{uid}", "green")]))
        return
    if L["seller"] == uid:
        await say(m, "آگهیِ خودته! برای پس‌گرفتن «آگهی‌های من» رو باز کن. 🙂", "🪦", "بازار روح", "black")
        return
    doc = await store.get(uid)
    n = await _make_pending(uid, {"k": "buy", "o": str(L["_id"])})
    enough = doc.get("gold", 0) >= L["price"]
    await show(m, panel("black", "🛒", "تأیید خرید", [
        f"{esc(L['item'])}", f"👤 فروشنده: {esc(L.get('seller_name'))}", f"💰 قیمت: <b>{fmt(L['price'])}</b>",
        f"🪙 موجودی تو: {fmt(doc.get('gold', 0))}" + ("" if enough else " ❌ کافی نیست"),
    ]), kb([btn("✅ بخر", f"ex:ok:{n}:{uid}", "green"), btn("🔙 انصراف", f"ex:b:0:{uid}", "red")]))


async def do_buy_confirm(m, nonce: str):
    uid = m.from_user.id
    async with ulock(uid):
        p = await _consume_pending(uid, nonce, "buy")
        if not p:
            await say(m, "این تأییدیه قبلاً استفاده شده یا منقضی شده. 🕯", "🪦", "بازار روح", "black")
            return
        ok, msg, L = await buy_listing(getattr(m, "bot", None), uid, p["o"])
    if ok:
        await show(m, panel("green", "🛒", "خرید انجام شد!", [
            f"🎁 {esc(L['item'])} رفت تو کوله‌پشتیت.", f"💸 −{fmt(L['price'])}",
        ], "💅 <i>«ارواح معامله می‌کنن؛ من فقط کارمزدش رو برمی‌دارم.»</i>"),
            kb([btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "green"), btn("🪦 بازار", f"ex:home:{uid}", "blue")]))
        await quest_progress(m, "trade")
    else:
        await say(m, msg, "🪦", "بازار روح", "black", kb([btn("🛒 مرور", f"ex:b:0:{uid}", "green")]))


async def buy_listing(bot, uid: int, oid_s: str) -> tuple:
    """(ok, پیام، آگهی). هر فراخوانی حداکثر یک‌بار خرید رو نهایی می‌کنه."""
    oid = _oid(oid_s)
    if not oid:
        return False, "آگهی نامعتبره.", None
    now = utcnow()
    L = await store.listings.find_one_and_update(
        {"_id": oid, "status": "active", "expires_at": {"$gt": now}, "seller": {"$ne": uid}},
        {"$set": {"status": "locked", "buyer": uid, "locked_at": now}}, return_document=ReturnDocument.AFTER)
    if not L:
        cur = await store.listings.find_one({"_id": oid})
        if cur and cur["seller"] == uid:
            return False, "آگهیِ خودت رو نمی‌تونی بخری. 🙂", None
        return False, "یکی زودتر خرید یا آگهی لغو/منقضی شد. 🕯", None
    price, item, sid = int(L["price"]), L["item"], str(L["_id"])

    def mut(inv, d):
        if len(inv) >= INV_CAP:
            return None
        inv.append(item)
        return inv

    # کم‌کردنِ GS + دادنِ آیتم + ثبتِ مارکر، همه در یک آپدیتِ اتمیکِ تک‌سندی
    res = await inv_update(
        uid, mut, filt={"gold": {"$gte": price}, "mx_bought": {"$ne": sid}},
        upd={"$inc": {"gold": -price}, "$push": {"mx_bought": {"$each": [sid], "$slice": -40}}})
    if not res:
        await store.listings.update_one({"_id": oid, "status": "locked", "buyer": uid},
                                        {"$set": {"status": "active"}, "$unset": {"buyer": "", "locked_at": ""}})
        d = await store.get(uid)
        if d and d.get("gold", 0) < price:
            return False, f"GS کافی نداری (لازم: {fmt(price)}). 🪙", None
        if d and len(d.get("inventory") or []) >= INV_CAP:
            return False, "کوله‌پشتیت پره! اول یه آیتم بفروش یا بسوزون. 🎒", None
        return False, "خطای موقت؛ دوباره امتحان کن. 🛠", None
    await _finish_sale(bot, L, uid)
    return True, "", L


async def _finish_sale(bot, L: dict, buyer: int):
    now = utcnow()
    sdoc = await store.get(L["seller"])
    pct = EXCHANGE_FEE_PCT_CAPITAL if "capital" in await terr_perks(sdoc) else EXCHANGE_FEE_PCT
    fee = exchange_fee(int(L["price"]), pct)
    await store.listings.update_one(
        {"_id": L["_id"], "status": "locked", "buyer": buyer},
        {"$set": {"status": "sold", "sold_at": now, "fee": fee, "net": int(L["price"]) - fee, "paid": False}})
    L2 = await store.listings.find_one({"_id": L["_id"]})
    if L2 and L2.get("status") == "sold":
        await _pay_seller(bot, L2)


async def _pay_seller(bot, L: dict):
    """واریزِ فروشنده — idempotent: حتی اگه ۱۰ بار صدا زده بشه، فقط یک‌بار پول می‌ره."""
    sid, net = str(L["_id"]), int(L.get("net", 0))
    res = await store.users.update_one(
        {"user_id": L["seller"], "mx_sold": {"$ne": sid}},
        {"$inc": {"gold": net, "mx_sales": 1}, "$push": {"mx_sold": {"$each": [sid], "$slice": -40}}})
    await store.listings.update_one({"_id": L["_id"], "paid": False}, {"$set": {"paid": True}})
    if not res.modified_count:
        return
    await log_tx(L["seller"], net, "exchange_sale", sid)
    await log_tx(L["buyer"], -int(L["price"]), "exchange_buy", sid)
    await burn(int(L.get("fee", 0)), "exchange_fee")
    try:
        sd = await store.get(L["seller"])
        if sd:
            await refresh_titles(sd)
        if bot:
            await bot.send_message(L["seller"], panel("green", "🪦", "آیتمت فروش رفت!", [
                f"{esc(L['item'])}", f"💰 +{fmt(net)} (کارمزد {fmt(L.get('fee', 0))})",
            ], "💅 <i>«یکی دیگه روحش رو فروخت. چه رشدی!»</i>"))
    except Exception:
        pass


# ───────────────────────────── ❌ لغو ─────────────────────────────
async def cancel_listing(m, oid_s: str):
    uid = m.from_user.id
    oid = _oid(oid_s)
    async with ulock(uid):
        L = await store.listings.find_one_and_update(
            {"_id": oid, "seller": uid, "status": "active"},
            {"$set": {"status": "cancelling", "cancel_at": utcnow()}}, return_document=ReturnDocument.AFTER) if oid else None
        if not L:
            await say(m, "این آگهی دیگه فعال نیست (شاید همین الان فروخته شد). 🕯", "🪦", "بازار روح", "black",
                      kb([btn("📜 آگهی‌های من", f"ex:my:{uid}", "blue")]))
            return
        sid, item = str(L["_id"]), L["item"]

        def mut(inv, d):
            if len(inv) >= INV_CAP:
                return None
            inv.append(item)
            return inv

        res = await inv_update(uid, mut, filt={"mx_ret": {"$ne": sid}},
                               upd={"$push": {"mx_ret": {"$each": [sid], "$slice": -40}}})
        if not res:
            await store.listings.update_one({"_id": L["_id"], "status": "cancelling"}, {"$set": {"status": "active"}})
            await say(m, "کوله‌پشتیت پره! اول جا باز کن، بعد آگهی رو لغو کن. 🎒", "🎒", "بازار روح", "black")
            return
        await store.listings.update_one({"_id": L["_id"], "status": "cancelling"}, {"$set": {"status": "cancelled"}})
    await show(m, panel("green", "↩️", "آگهی لغو شد", [f"{esc(item)} برگشت کوله‌پشتیت."]),
               kb([btn("📜 آگهی‌های من", f"ex:my:{uid}", "blue"), btn("🪦 بازار", f"ex:home:{uid}", "green")]))


# ───────────────────────────── 🩹 ریکاوری ─────────────────────────────
async def recover_exchange(bot, throttle: bool = False):
    """معاملاتِ نیمه‌کاره (مثلاً کرشِ وسط کار) رو تمیز می‌کنه. idempotent."""
    global _last_recover
    now_t = time.time()
    if throttle and now_t - _last_recover < 120:
        return
    _last_recover = now_t
    try:
        now = utcnow()
        async for L in store.listings.find({"status": "locked", "locked_at": {"$lt": now - timedelta(seconds=60)}}):
            charged = await store.users.find_one({"user_id": L["buyer"], "mx_bought": str(L["_id"])}, {"_id": 1})
            if charged:
                await _finish_sale(bot, L, L["buyer"])
            else:
                await store.listings.update_one({"_id": L["_id"], "status": "locked"},
                                                {"$set": {"status": "active"}, "$unset": {"buyer": "", "locked_at": ""}})
        async for L in store.listings.find({"status": "sold", "paid": False, "sold_at": {"$lt": now - timedelta(seconds=30)}}):
            await _pay_seller(bot, L)
        async for L in store.listings.find({"status": "cancelling", "cancel_at": {"$lt": now - timedelta(seconds=60)}}):
            back = await store.users.find_one({"user_id": L["seller"], "mx_ret": str(L["_id"])}, {"_id": 1})
            await store.listings.update_one({"_id": L["_id"], "status": "cancelling"},
                                            {"$set": {"status": "cancelled" if back else "active"}})
    except Exception:
        log.exception("recover_exchange failed")


# ───────────────────────────── 🪙 پنل GS ─────────────────────────────
async def gs_panel(m):
    uid = m.from_user.id
    doc = await store.get(uid)
    today = int(doc.get("gs_earned", 0)) if doc.get("gs_day") == day_key() else 0
    rows = await store.ledger.find({"uid": uid}).sort("at", -1).limit(5).to_list(5)
    names = {"exchange_sale": "فروش در بازار", "exchange_buy": "خرید از بازار", "forge": "کوره‌ی روح", "witch": "جادوگر",
             "guild_donate": "اهدا به گیلد"}
    lines = [
        f"🪙 موجودی: <b>{fmt(doc.get('gold', 0))}</b>",
        f"📅 درآمدِ بازیِ امروز: <b>{today}</b> / {GS_DAILY_SOFT_CAP} (بعد از سقف، درآمد کمتر میشه)",
        "┈┈┈┈┈┈┈┈┈┈",
    ]
    lines += [f"{'🟢' if r['delta'] > 0 else '🔴'} {names.get(r['reason'], r['reason'])}: {r['delta']:+d}" for r in rows] or ["هنوز تراکنشی ثبت نشده."]
    await show(m, panel("yellow", "🪙", f"GRAVE SIGIL ({GS})", lines,
                        "ارزِ داخلیِ بازی؛ خرج میشه تو بازار، کوره، گیلد و قلمرو."),
               kb([btn("🪦 بازار روح", f"ex:home:{uid}", "green"), btn("🔥 کوره", f"fg:home:{uid}", "red")], back_kb(uid)))


# ───────────────────────────── 🔘 مسیریابِ دکمه‌ها ─────────────────────────────
async def exchange_cb(m, parts: list):
    uid = m.from_user.id
    act = parts[1]
    if act == "home":
        await exchange_home(m)
    elif act == "b":
        await browse(m, int(parts[2]))
    elif act == "my":
        await my_listings(m)
    elif act == "tx":
        await tx_history(m)
    elif act == "p" and len(parts) >= 5:
        await price_presets(m, int(parts[2]), parts[3])
    elif act == "s" and len(parts) >= 6:
        await sell_confirm(m, int(parts[2]), parts[3], int(parts[4]))
    elif act == "lst":
        await do_list(m, parts[2])
    elif act == "buy":
        await buy_prompt(m, parts[2])
    elif act == "ok":
        await do_buy_confirm(m, parts[2])
    elif act == "cx":
        await cancel_listing(m, parts[2])
