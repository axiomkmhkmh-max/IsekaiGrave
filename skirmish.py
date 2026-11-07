"""⚔️ کنش‌های ریپلایی بین بازیکن‌ها: حمله، دزدی، ترمیم، هدیه، جایزه‌ی سر، جاسوسی، حالت جنگ.

همه‌چیز با «ریپلای» روی پیامِ بازیکنِ دیگه تو گروه (به‌جز حالت جنگ و لیست جایزه‌ها).
حمله از موتورِ نبردِ تاکتیکیِ موجود (battle_engine.run_ai: کلاس، روح، سپر، رشته‌ی سرنوشت، بازتولد) استفاده می‌کنه.

قانون‌های ایمنی (همه ثابت و سقف‌دارن):
- «محافظت» (opted_out) مطلقه: نه حمله، نه دزدی، نه جاسوسی، نه جایزه‌ی سر.
- حداقل سطح ۳ (مهاجم و هدف)؛ هدف نباید بیشتر از LEVEL_GAP سطح کمتر باشه (ضد زورگویی؛ انتقام معاف).
- هر نفر ۳ «شارژ حمله» داره که هر ۲۰ دقیقه ۱ تا برمی‌گرده؛ هر جفت ۱ ساعت یک‌بار؛ بعد از ضربه‌ی موفق ۲۰ دقیقه سپرِ نفس‌گیری.
- بقا هیچ‌وقت با این سیستم زیر ۵٪ نمیره (مرگ اجباری نیست). غارتِ GS سقف‌دار و همیشه ≥ ۵۰ GS برای قربانی می‌ذاره.
- انتقال‌ها اتمیک (debit شرطی) و تو دفتر (ledger) ثبت میشن؛ کارمزدها می‌سوزن.
- قربانیِ ضربه ۲۴ ساعت حق «انتقام» داره (بدون محدودیتِ جفت، با غارتِ بیشتر).
وضعیتِ زمان‌ها روی سندِ کاربر (فیلدهای sk_*)؛ جایزه‌ها تو کالکشنِ bounties.
"""

import random
import re
import time
from datetime import timedelta
from typing import Optional

from battle_engine import make_fighter, run_ai, pct
from config import GS
from database import store
from economy import burn, credit, debit, terr_perks, ulock
from npcreply import norm
from players import adjust_survival, grant
from render import display
from rules import gear_bonus
from ui import hp_bar, panel, say
from utils import esc, is_group, utcnow
from utils import day_key

MIN_LEVEL = 3
LEVEL_GAP = 8
MAX_CHARGES = 3
CHARGE_SECS = 20 * 60
PAIR_COOLDOWN = 60 * 60
SHIELD_SECS = 20 * 60
REVENGE_SECS = 24 * 3600
SURV_FLOOR = 5
GOLD_FLOOR = 50                     # قربانی هیچ‌وقت با غارت زیر این مقدار نمیره
LOOT = {"base": (0.03, 20), "high": (0.06, 60)}      # (درصد از GS قربانی، سقف)
WAR_MIN_SECS = 2 * 3600
STEAL_COOLDOWN = 30 * 60
STEAL_SHIELD = 15 * 60
STEAL_PCT, STEAL_CAP, STEAL_FINE = 0.04, 25, 10
HEAL_COST, HEAL_COOLDOWN, HEAL_DAILY = 8, 10 * 60, 5
GIFT_MIN, GIFT_MAX, GIFT_FEE_PCT, GIFT_DAILY = 10, 500, 5, 1000
BOUNTY_MIN, BOUNTY_MAX, BOUNTY_TARGET_CAP, BOUNTY_TTL_H, BOUNTY_FEE_PCT = 20, 500, 1000, 24, 10
SPY_COST, SPY_COOLDOWN = 5, 30

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

ATTACK_RE = re.compile(r"(حمله|حمله کن|بزنش|بکوبش|ضربه بزن|ضربه بزنش)")
STEAL_RE = re.compile(r"(دزدی|دزدی کن|جیب بری|جیب بری کن|بدزدش)")
HEAL_RE = re.compile(r"(ترمیم|ترمیمش|ترمیم کن|شفاش بده|درمانش کن)")
GIFT_RE = re.compile(r"هدیه (\d{1,5})(?: gs| جی اس)?")
BOUNTY_RE = re.compile(r"جایزه (?:ی )?(?:سر|روی سر)ش? (\d{1,5})(?: gs| جی اس)?")
BOUNTY_LIST_RE = re.compile(r"(جایزه ها|لیست جایزه|لیست جایزه ها|شکارچی)")
SPY_RE = re.compile(r"(جاسوسی|جاسوسش|بررسیش|اسکنش)")
WAR_ON_RE = re.compile(r"(حالت جنگ|جنگ روشن|حالت جنگ روشن)")
WAR_OFF_RE = re.compile(r"(حالت صلح|جنگ خاموش|حالت جنگ خاموش)")
_ALL = (ATTACK_RE, STEAL_RE, HEAL_RE, GIFT_RE, BOUNTY_RE, BOUNTY_LIST_RE, SPY_RE, WAR_ON_RE, WAR_OFF_RE)


def _n(raw: str) -> str:
    return norm((raw or "").translate(_DIGITS))


def matches(raw: str) -> bool:
    t = _n(raw)
    return any(r.fullmatch(t) for r in _ALL)


def _dur(sec: float) -> str:
    sec = max(1, int(sec))
    return f"{sec // 60} دقیقه" if sec >= 60 else f"{sec} ثانیه"


class _Locks:
    """قفلِ چند بازیکن به ترتیبِ ثابت (بدون بن‌بست)."""
    def __init__(self, *uids):
        self.l = [ulock(u) for u in sorted(set(uids))]

    async def __aenter__(self):
        for lk in self.l:
            await lk.acquire()

    async def __aexit__(self, *a):
        for lk in reversed(self.l):
            lk.release()


def _regen(doc: dict, now: float) -> tuple:
    """(شارژِ فعلی، مبنای زمانیِ جدید) با برگشتِ تدریجی."""
    c, t0 = doc.get("sk_charges"), doc.get("sk_charge_t")
    if c is None or c >= MAX_CHARGES or t0 is None:
        return (MAX_CHARGES if c is None else min(c, MAX_CHARGES)), now
    gained = int((now - t0) // CHARGE_SECS)
    c2 = min(MAX_CHARGES, c + gained)
    return c2, (now if c2 >= MAX_CHARGES else t0 + gained * CHARGE_SECS)


def _loot_amount(tdoc: dict, high: bool) -> int:
    pct_, cap = LOOT["high" if high else "base"]
    g = int(tdoc.get("gold", 0))
    return max(0, min(cap, int(g * pct_), g - GOLD_FLOOR))


def _eligible(doc: dict) -> Optional[str]:
    if doc.get("registered") is False:
        return "هنوز ثبت‌نام نکرده."
    if int(doc.get("level", 1)) < MIN_LEVEL:
        return f"زیر سطح {MIN_LEVEL}؛ تازه‌کارها تحت حمایتن. 🐣"
    return None


async def _target(m):
    tu = m.reply_to_message.from_user if m.reply_to_message else None
    if not tu:
        return None, "روی پیامِ یه بازیکن ریپلای کن."
    if tu.is_bot:
        return None, "ربات‌ها وارد این بازی نمیشن. 🤖"
    if tu.id == m.from_user.id:
        return None, "با خودت؟ برو آینه رو بزن. 🪞"
    await store.touch(tu)
    return await store.get(tu.id), None


async def _expire_bounties():
    now = utcnow()
    while True:
        b = await store.bounties.find_one_and_update({"status": "open", "expires_at": {"$lte": now}}, {"$set": {"status": "expired"}})
        if not b:
            return
        await credit(b["placer"], int(b["amount"]), "bounty_refund")


async def _claim_bounties(target: int, claimer: int) -> int:
    total, now = 0, utcnow()
    while True:
        b = await store.bounties.find_one_and_update(
            {"target": target, "status": "open", "placer": {"$ne": claimer}, "expires_at": {"$gt": now}},
            {"$set": {"status": "claimed", "claimed_by": claimer, "claimed_at": now}})
        if not b:
            return total
        amt = int(b["amount"])
        net = amt * (100 - BOUNTY_FEE_PCT) // 100
        await credit(claimer, net, "bounty_claim")
        await burn(amt - net, "bounty_fee")
        total += net


async def _fighter(doc: dict) -> dict:
    return make_fighter(doc, gear=gear_bonus((doc.get("equip") or {}).get("item")), perks=await terr_perks(doc))


# ───────────────────────────── ⚔️ حمله ─────────────────────────────
async def _attack(m, adoc: dict, tdoc: dict):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    now = time.time()
    async with _Locks(aid, tid):
        adoc, tdoc = await store.get(aid), await store.get(tid)
        for who, d in (("تو", adoc), (None, tdoc)):
            why = _eligible(d)
            if why:
                return await say(m, (f"{who}: " if who else "") + why, "⚔️", "حمله", "orange")
        revenge = float((adoc.get("sk_rev") or {}).get(str(tid), 0)) > now
        if not revenge and int(tdoc.get("level", 1)) < int(adoc.get("level", 1)) - LEVEL_GAP:
            return await say(m, "این بازیکن خیلی از تو ضعیف‌تره؛ زورگویی تو ایسکا هم مد نیست. 😒", "⚔️", "حمله", "orange")
        if float(tdoc.get("sk_shield", 0)) > now:
            return await say(m, f"{display(tdoc)} تازه ضربه خورده و داره نفس می‌گیره؛ {_dur(tdoc['sk_shield'] - now)} دیگه. 🛡", "🛡", "نفس‌گیری", "blue")
        last = float((adoc.get("sk_pair") or {}).get(str(tid), 0))
        if not revenge and now - last < PAIR_COOLDOWN:
            return await say(m, f"به همین نفر تازه حمله کردی؛ {_dur(PAIR_COOLDOWN - (now - last))} دیگه. ⏳", "⏳", "صبر", "blue")
        charges, base_t = _regen(adoc, now)
        if charges <= 0:
            return await say(m, f"شارژِ حمله نداری؛ بعدی تا {_dur(base_t + CHARGE_SECS - now)} دیگه. 🔋", "🔋", "بی‌شارژ", "blue")

        fa, fb = await _fighter(adoc), await _fighter(tdoc)
        win = run_ai(fa, fb, first=0) == 0
        high = bool(tdoc.get("sk_war")) or revenge
        a_set = {"sk_charges": charges - 1, "sk_charge_t": (now if charges >= MAX_CHARGES else base_t), f"sk_pair.{tid}": now}
        a_inc = {"sk_wins" if win else "sk_losses": 1}
        a_unset = {f"sk_rev.{tid}": ""} if revenge else {}
        lines = [f"{display(adoc, link=True)} ⚔️ {display(tdoc, link=True)}"
                 + ("  🔥 انتقام!" if revenge else ""),
                 f"💥 ضربه‌ها: {esc(fa['name'])} {fa['dealt']} · {esc(fb['name'])} {fb['dealt']}"
                 + (" · 🔁 بازتولد" if fa["used_echo"] or fb["used_echo"] else "")]
        loot = bounty = 0
        if win:
            dmg = 5 + int(10 * pct(fa))
            if not high:
                dmg = max(3, dmg // 2)
            dmg = min(dmg, max(0, int(tdoc.get("survival_rate", 100)) - SURV_FLOOR))
            if dmg:
                tdoc = await adjust_survival(tid, -dmg, "sk_hits_taken")
            amt = _loot_amount(tdoc, high)
            if amt and await debit(tid, amt, "skirmish_lost", burn_it=False):
                await credit(aid, amt, "skirmish_loot")
                loot = amt
            bounty = await _claim_bounties(tid, aid)
            await store.users.update_one({"user_id": tid}, {"$set": {"sk_shield": now + SHIELD_SECS, f"sk_rev.{aid}": now + REVENGE_SECS},
                                                            "$inc": {"sk_lost": loot}})
            a_inc["sk_loot"] = loot + bounty
            await grant(aid, xp=random.randint(10, 20))
            lines += [f"🏆 <b>{esc(fa['name'])} پیروز شد!</b>",
                      f"💀 {display(tdoc)} −{dmg}٪ بقا {hp_bar(int(tdoc.get('survival_rate', 0)))}"]
            if loot:
                lines.append(f"🪙 غارت: +{loot} {GS}" + (" (حالت جنگ/انتقام)" if high else ""))
            if bounty:
                lines.append(f"🎯 جایزه‌ی سر: +{bounty} {GS}")
            lines.append(f"🛡 {display(tdoc)} ۲۰ دقیقه سپر گرفت؛ ولی ۲۴ ساعت حق انتقام داره!")
        else:
            dmg = min(random.randint(3, 8), max(0, int(adoc.get("survival_rate", 100)) - SURV_FLOOR))
            if dmg:
                await adjust_survival(aid, -dmg, "sk_hits_taken")
            lines += [f"🛡 <b>{esc(fb['name'])} دفاع کرد!</b> حمله‌ی {esc(fa['name'])} شکست خورد.",
                      f"🩸 {esc(fa['name'])} −{dmg}٪ بقا بابت حمله‌ی ناموفق."]
        upd = {"$set": a_set, "$inc": a_inc}
        if a_unset:
            upd["$unset"] = a_unset
        await store.users.update_one({"user_id": aid}, upd)
        lines.append(f"🔋 شارژ حمله‌ی {esc(fa['name'])}: {charges - 1}/{MAX_CHARGES}")
        await m.reply(panel("red" if win else "blue", "⚔️", "حمله!" if win else "دفاعِ موفق", lines))


# ───────────────────────────── 🥷 دزدی ─────────────────────────────
async def _steal(m, adoc: dict, tdoc: dict):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    now = time.time()
    async with _Locks(aid, tid):
        adoc, tdoc = await store.get(aid), await store.get(tid)
        for d in (adoc, tdoc):
            why = _eligible(d)
            if why:
                return await say(m, why, "🥷", "جیب‌بری", "orange")
        if now - float(adoc.get("sk_steal_t", 0)) < STEAL_COOLDOWN:
            return await say(m, f"دستت هنوز داغه؛ {_dur(STEAL_COOLDOWN - (now - adoc['sk_steal_t']))} دیگه. 🥷", "🥷", "جیب‌بری", "blue")
        if float(tdoc.get("sk_pshield", 0)) > now:
            return await say(m, f"جیبِ {display(tdoc)} تازه خالی شده؛ {_dur(tdoc['sk_pshield'] - now)} دیگه. 👜", "👜", "جیب‌بری", "blue")
        chance = min(0.75, max(0.2, 0.45 + 0.03 * (int(adoc.get("level", 1)) - int(tdoc.get("level", 1)))
                               + (0.15 if adoc.get("cls") == "rogue" else 0)))
        await store.users.update_one({"user_id": aid}, {"$set": {"sk_steal_t": now}})
        if random.random() < chance:
            amt = max(0, min(STEAL_CAP, int(int(tdoc.get("gold", 0)) * STEAL_PCT), int(tdoc.get("gold", 0)) - GOLD_FLOOR))
            if amt and await debit(tid, amt, "pickpocket_lost", burn_it=False):
                await credit(aid, amt, "pickpocket_loot")
                await store.users.update_one({"user_id": tid}, {"$set": {"sk_pshield": now + STEAL_SHIELD}})
                return await m.reply(panel("purple", "🥷", "جیب‌بری موفق", [
                    f"{display(adoc, link=True)} بی‌صدا جیبِ {display(tdoc, link=True)} رو خالی کرد!", f"🪙 +{amt} {GS}"]))
            return await m.reply(panel("purple", "🥷", "جیب خالی", [f"{display(tdoc)} چیزی تو جیبش نبود؛ دزدِ بدبخت! 😅"]))
        fine = STEAL_FINE if await debit(aid, STEAL_FINE, "pickpocket_fine", burn_it=False) else 0
        if fine:
            await credit(tid, fine, "pickpocket_fine_received")
        dmg = min(3, max(0, int(adoc.get("survival_rate", 100)) - SURV_FLOOR))
        if dmg:
            await adjust_survival(aid, -dmg, "sk_hits_taken")
        await store.users.update_one({"user_id": tid}, {"$set": {f"sk_rev.{aid}": now + REVENGE_SECS}})
        await m.reply(panel("red", "🚨", "دزد گرفتار شد!", [
            f"{display(tdoc, link=True)} دستِ {display(adoc, link=True)} رو تو جیبش گرفت!",
            f"💸 جریمه: {fine} {GS} به قربانی · 🩸 −{dmg}٪ بقا", "🔥 قربانی ۲۴ ساعت حق انتقام داره."]))


# ───────────────────────────── 🩹 ترمیم ─────────────────────────────
async def _heal(m, adoc: dict, tdoc: dict):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    now, today = time.time(), day_key()
    async with _Locks(aid):
        adoc = await store.get(aid)
        if now - float(adoc.get("sk_heal_t", 0)) < HEAL_COOLDOWN:
            return await say(m, f"هنوز خسته‌ای؛ {_dur(HEAL_COOLDOWN - (now - adoc['sk_heal_t']))} دیگه. 🩹", "🩹", "ترمیم", "blue")
        n_today = int(adoc.get("sk_heal_n", 0)) if adoc.get("sk_heal_day") == today else 0
        if n_today >= HEAL_DAILY:
            return await say(m, f"امروز {HEAL_DAILY} بار ترمیم کردی؛ فردا بیا. 🌙", "🩹", "ترمیم", "blue")
        if int(tdoc.get("survival_rate", 100)) >= 95:
            return await say(m, f"{display(tdoc)} سالمِ سالمه؛ ترمیم لازم نداره. 💪", "🩹", "ترمیم", "green")
        if not await debit(aid, HEAL_COST, "skirmish_heal"):
            return await say(m, f"ترمیم {HEAL_COST} {GS} خرج داره و نداری. 🪙", "🩹", "ترمیم", "orange")
        h = random.randint(6, 12)
        doc = await adjust_survival(tid, h, "blessings_received")
        await store.users.update_one({"user_id": aid}, {"$set": {"sk_heal_t": now, "sk_heal_day": today, "sk_heal_n": n_today + 1}})
        await grant(aid, xp=5)
        await m.reply(panel("green", "🩹", "ترمیم", [
            f"{display(adoc, link=True)} زخمای {display(doc, link=True)} رو بست. 💚",
            f"💀 +{h}٪ بقا → {doc['survival_rate']}٪ {hp_bar(int(doc['survival_rate']))}", f"🪙 هزینه: {HEAL_COST} {GS}"]))


# ───────────────────────────── 🎁 هدیه ─────────────────────────────
async def _gift(m, adoc: dict, tdoc: dict, amount: int):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    today = day_key()
    if not GIFT_MIN <= amount <= GIFT_MAX:
        return await say(m, f"هدیه باید بین {GIFT_MIN} تا {GIFT_MAX} {GS} باشه. 🎁", "🎁", "هدیه", "orange")
    async with _Locks(aid):
        adoc = await store.get(aid)
        if int(adoc.get("level", 1)) < MIN_LEVEL:
            return await say(m, f"هدیه دادن از سطح {MIN_LEVEL}. 🐣", "🎁", "هدیه", "orange")
        sent = int(adoc.get("sk_gift_amt", 0)) if adoc.get("sk_gift_day") == today else 0
        if sent + amount > GIFT_DAILY:
            return await say(m, f"سقفِ هدیه‌ی روزانه {GIFT_DAILY} {GS}ه (امروز {sent} دادی). 🎁", "🎁", "هدیه", "orange")
        if tdoc.get("registered") is False:
            return await say(m, "گیرنده هنوز ثبت‌نام نکرده. 📜", "🎁", "هدیه", "orange")
        if not await debit(aid, amount, "gift_sent", burn_it=False):
            return await say(m, "موجودیت کافی نیست. 🪙", "🎁", "هدیه", "orange")
        fee = max(1, amount * GIFT_FEE_PCT // 100)
        await credit(tid, amount - fee, "gift_received")
        await burn(fee, "gift_fee")
        await store.users.update_one({"user_id": aid}, {"$set": {"sk_gift_day": today, "sk_gift_amt": sent + amount}})
        await m.reply(panel("yellow", "🎁", "هدیه", [
            f"{display(adoc, link=True)} به {display(tdoc, link=True)} هدیه داد! 💛", f"🪙 {amount - fee} {GS} رسید (کارمزد {fee} سوخت)"]))


# ───────────────────────────── 🎯 جایزه‌ی سر ─────────────────────────────
async def _bounty_place(m, adoc: dict, tdoc: dict, amount: int):
    aid, tid = adoc["user_id"], tdoc["user_id"]
    await _expire_bounties()
    if not BOUNTY_MIN <= amount <= BOUNTY_MAX:
        return await say(m, f"جایزه‌ی سر بین {BOUNTY_MIN} تا {BOUNTY_MAX} {GS}. 🎯", "🎯", "جایزه", "orange")
    if tdoc.get("opted_out"):
        return await say(m, f"{display(tdoc)} «محافظت» فعال کرده؛ جایزه‌ای روی سرش نمیشه گذاشت. 🛡", "🛡", "جایزه", "blue")
    async with _Locks(aid):
        adoc = await store.get(aid)
        if int(adoc.get("level", 1)) < MIN_LEVEL:
            return await say(m, f"جایزه گذاشتن از سطح {MIN_LEVEL}. 🐣", "🎯", "جایزه", "orange")
        open_total = 0
        async for b in store.bounties.find({"target": tid, "status": "open"}):
            open_total += int(b["amount"])
        if open_total + amount > BOUNTY_TARGET_CAP:
            return await say(m, f"روی سرِ این نفر جایزه‌ی کافی هست (سقف {BOUNTY_TARGET_CAP} {GS}). 🎯", "🎯", "جایزه", "orange")
        if not await debit(aid, amount, "bounty_place", burn_it=False):
            return await say(m, "موجودیت کافی نیست. 🪙", "🎯", "جایزه", "orange")
        await store.bounties.insert_one({"target": tid, "placer": aid, "amount": amount, "status": "open", "created_at": utcnow(),
                                         "expires_at": utcnow() + timedelta(hours=BOUNTY_TTL_H)})
        await m.reply(panel("red", "🎯", "جایزه‌ی سر!", [
            f"{display(adoc, link=True)} روی سرِ {display(tdoc, link=True)} <b>{amount} {GS}</b> جایزه گذاشت!",
            f"هر کی تو {BOUNTY_TTL_H} ساعت بهش حمله‌ی موفق بزنه برنده‌ی جایزه‌ست (۱۰٪ کارمزد). بعدش پول برمی‌گرده به جایزه‌گذار."]))


async def _bounty_list(m):
    await _expire_bounties()
    rows = await store.bounties.find({"status": "open"}).sort("amount", -1).limit(5).to_list(5)
    if not rows:
        return await say(m, "الان هیچ جایزه‌ای روی سرِ کسی نیست. 🕊", "🎯", "جایزه‌ها", "blue")
    lines = []
    for b in rows:
        t = await store.get(b["target"])
        lines.append(f"🎯 {display(t) if t else 'ناشناس'} — <b>{int(b['amount'])} {GS}</b>")
    await m.reply(panel("red", "🎯", "جایزه‌های سر", lines, "برای گرفتنش، به هدف ریپلای کن و بنویس «حمله»"))


# ───────────────────────────── 🔍 جاسوسی ─────────────────────────────
async def _spy(m, adoc: dict, tdoc: dict):
    aid = adoc["user_id"]
    now = time.time()
    if tdoc.get("opted_out"):
        return await say(m, f"{display(tdoc)} «محافظت» فعال کرده؛ جاسوس‌ها ازش دورن. 🛡", "🛡", "جاسوسی", "blue")
    async with _Locks(aid):
        adoc = await store.get(aid)
        if now - float(adoc.get("sk_spy_t", 0)) < SPY_COOLDOWN:
            return await say(m, "جاسوست هنوز برنگشته. 🕵️", "🕵️", "جاسوسی", "blue")
        if not await debit(aid, SPY_COST, "skirmish_spy"):
            return await say(m, f"جاسوسی {SPY_COST} {GS} خرج داره. 🪙", "🕵️", "جاسوسی", "orange")
        await store.users.update_one({"user_id": aid}, {"$set": {"sk_spy_t": now}})
    g = int(tdoc.get("gold", 0))
    wealth = "کم‌پول" if g < 100 else "متوسط" if g < 500 else "پولدار" if g < 2000 else "خیلی ثروتمند"
    shield = float(tdoc.get("sk_shield", 0)) > now
    await m.reply(panel("purple", "🕵️", "گزارش جاسوس", [
        f"{display(tdoc, link=True)}",
        f"⭐ سطح {tdoc.get('level', 1)} · 🎭 {esc(str(tdoc.get('cls') or 'بدون کلاس'))}",
        f"💀 بقا {tdoc.get('survival_rate', 100)}٪ {hp_bar(int(tdoc.get('survival_rate', 100)))}",
        f"⚔️ نبردها: {tdoc.get('sk_wins', 0)} برد · {tdoc.get('sk_losses', 0)} باخت",
        f"💰 وضعِ مالی: {wealth}",
        f"{'🔥 حالت جنگ روشنه' if tdoc.get('sk_war') else '🕊 حالت صلح'}" + (" · 🛡 سپر فعال" if shield else "")]))


# ───────────────────────────── 🔥 حالت جنگ ─────────────────────────────
async def _war(m, on: bool):
    uid, now = m.from_user.id, time.time()
    async with _Locks(uid):
        doc = await store.get(uid)
        if not doc:
            return
        if on:
            if doc.get("sk_war"):
                return await say(m, "حالت جنگت از قبل روشنه. 🔥", "🔥", "حالت جنگ", "red")
            await store.users.update_one({"user_id": uid}, {"$set": {"sk_war": True, "sk_war_t": now + WAR_MIN_SECS}})
            return await say(m, f"حالت جنگ روشن شد! دیگران می‌تونن بیشتر ازت غارت کنن و تو هم همین‌طور. حداقل {_dur(WAR_MIN_SECS)} نمی‌تونی خاموشش کنی. 🔥", "🔥", "حالت جنگ", "red")
        if not doc.get("sk_war"):
            return await say(m, "حالت جنگت که خاموشه. 🕊", "🕊", "حالت صلح", "blue")
        if now < float(doc.get("sk_war_t", 0)):
            return await say(m, f"هنوز نمی‌تونی صلح کنی؛ {_dur(doc['sk_war_t'] - now)} دیگه. ⏳", "⏳", "حالت صلح", "blue")
        await store.users.update_one({"user_id": uid}, {"$set": {"sk_war": False}})
        await say(m, "حالت صلح فعال شد. 🕊", "🕊", "حالت صلح", "blue")


# ───────────────────────────── 🚪 ورودی ─────────────────────────────
async def do_skirmish(m, raw: str) -> bool:
    """True = پیام مالِ این سیستم بود و جواب داده شد."""
    t = _n(raw)
    if WAR_OFF_RE.fullmatch(t):
        await _war(m, False)
        return True
    if WAR_ON_RE.fullmatch(t):
        await _war(m, True)
        return True
    if BOUNTY_LIST_RE.fullmatch(t):
        await _bounty_list(m)
        return True
    gm, bm = GIFT_RE.fullmatch(t), BOUNTY_RE.fullmatch(t)
    acts = [(ATTACK_RE, "attack"), (STEAL_RE, "steal"), (HEAL_RE, "heal"), (SPY_RE, "spy")]
    kind = next((k for r, k in acts if r.fullmatch(t)), "gift" if gm else "bounty" if bm else None)
    if not kind:
        return False
    if not is_group(m):
        await say(m, "این کار فقط تو گروه و با ریپلای روی پیامِ یه بازیکنه. 👥", "⚔️", "ریپلای", "orange")
        return True
    tdoc, err = await _target(m)
    if err or not tdoc:
        await say(m, err or "هدف پیدا نشد.", "⚔️", "ریپلای", "orange")
        return True
    adoc = await store.get(m.from_user.id)
    if not adoc:
        return True
    if kind in ("attack", "steal", "spy") and tdoc.get("opted_out"):
        await say(m, f"{display(tdoc)} «محافظت» فعال کرده؛ بهش نمیشه دست زد. 🛡", "🛡", "محافظت", "blue")
        return True
    if kind in ("attack", "steal") and adoc.get("opted_out"):
        await say(m, "خودت «محافظت» رو فعال کردی؛ اول بنویس «برگردم به بازی». 🛡", "🛡", "محافظت", "blue")
        return True
    if kind == "attack":
        await _expire_bounties()
        await _attack(m, adoc, tdoc)
    elif kind == "steal":
        await _steal(m, adoc, tdoc)
    elif kind == "heal":
        await _heal(m, adoc, tdoc)
    elif kind == "spy":
        await _spy(m, adoc, tdoc)
    elif kind == "gift":
        await _gift(m, adoc, tdoc, int(gm.group(1)))
    else:
        await _bounty_place(m, adoc, tdoc, int(bm.group(1)))
    return True
