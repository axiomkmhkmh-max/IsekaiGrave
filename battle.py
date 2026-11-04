"""⚔️ نبردِ رشته‌ی سرنوشت — لایه‌ی تلگرام برای دوئل (قوانین و توازن تو battle_engine.py ـه).

• نوبتی، همه‌چیز آشکار، بدون رندوم؛ فقط بازیکنِ فعال دکمه‌ها رو می‌بینه (owner = uid).
• هر حرکت با یک آپدیتِ اتمیک (شرط: همین نوبت) ثبت میشه؛ دکمه‌ی تکراری/قدیمی بی‌اثره و جایزه دقیقاً یک‌بار پرداخت میشه.
• اگه کسی ۷۵ ثانیه حرکت نکنه، ایزدبانو به‌جاش حرکتِ پیش‌فرض می‌زنه؛ پس نبرد هیچ‌وقت گیر نمی‌کنه."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatType
from bson import ObjectId
from pymongo import ReturnDocument

from battle_engine import (
    ECHO_THRESHOLD, FATE_COST, MAX_SOUL, MAX_TURNS, REBIRTH_TOLL, SKILL_HELP, SKILLS, apply_move, auto_move, legal_moves,
    make_fighter, pct, winner_if_over,
)
from config import BATTLE_STALE, DUEL_REWARD_COOLDOWN, GS, TURN_SECONDS, log
from content import CLASSES, GODDESS_NAME
from database import store
from economy import terr_perks
from players import grant, reincarnate
from quests import quest_progress
from render import display, render_rebirth, render_scene
from rules import gear_bonus
from ui import btn, kb, panel, safe_edit, say
from utils import esc, spawn, utcnow
from weekly import add_guild_pts


_CODE = {"s": "strike", "w": "ward", "f": "fate", "e": "echo"}
_CODE_REV = {v: k for k, v in _CODE.items()}


class _Shim:
    """جایگزینِ Message برای وقتی که از تایمر/کال‌بک بدون پیام اصلی کار می‌کنیم (quest_progress فقط reply می‌خواد)."""

    def __init__(self, bot: Bot, chat_id: int, uid: int):
        self.bot = bot
        self.chat = SimpleNamespace(id=chat_id, type=ChatType.SUPERGROUP)
        self.from_user = SimpleNamespace(id=uid, full_name="")

    async def reply(self, text, **kw):
        return await self.bot.send_message(self.chat.id, text, **kw)

    answer = reply


# ───────────────────────────── 🎨 نمایش ─────────────────────────────
def _bar(hp: int, mx: int) -> str:
    n = max(0, min(10, round(10 * max(hp, 0) / mx))) if mx else 0
    return "▰" * n + "▱" * (10 - n)


def _soul(n: int) -> str:
    return "●" * n + "○" * (MAX_SOUL - n)


def render_battle(b: dict, foot: Optional[str] = None) -> str:
    fs, i = b["f"], b["i"]
    rnd = min(MAX_TURNS, b["t"] // 2 + 1)
    lines = []
    for k, f in enumerate(fs):
        ic = CLASSES.get(f.get("cls") or "", {}).get("icon", "🧿")
        lines.append(f"{'👉' if k == i else '▫️'} {ic} <b>{esc(f['name'])}</b> ‹سطح {f['lvl']}›")
        lines.append(f"      ❤️ {max(f['hp'], 0)}/{f['max_hp']} {_bar(f['hp'], f['max_hp'])}")
        lines.append(f"      🕯 {_soul(f['soul'])}" + (" 🛡" if f["ward"] else "") + (" " + "🔁" * f["echo"] if f["echo"] else ""))
    if b.get("log"):
        lines.append("┈┈┈┈┈┈┈┈┈┈")
        lines += b["log"][-3:]
    me, foe = fs[i], fs[1 - i]
    hint = []
    if foe["soul"] >= FATE_COST:
        hint.append(f"⚠️ روحِ {esc(foe['name'])} پره؛ رشته‌ی سرنوشت میاد! سپر؟")
    if me["hp"] <= me["max_hp"] * ECHO_THRESHOLD and me["echo"] > 0:
        hint.append("🔁 می‌تونی بازتولد بشی!")
    foot = foot or ("\n".join(hint) + ("\n" if hint else "") + f"⏳ نوبتِ <b>{esc(me['name'])}</b> ({TURN_SECONDS} ثانیه)")
    return panel("orange", "⚔️", f"نبردِ رشته‌ی سرنوشت — پرده‌ی {rnd}/{MAX_TURNS}", lines, foot)


def _kb(b: dict):
    i = b["i"]
    me = b["f"][i]
    uid, base = me["uid"], f"bt:mv:{b['_id']}:{b['t']}"
    lm = legal_moves(me)
    skill = SKILLS.get(me.get("cls"), SKILLS[None])
    row1 = [btn("⚔️ ضربه (+۱🕯)", f"{base}:s:{uid}", "red")]
    if "ward" in lm:
        row1.append(btn("🛡 سپر (+۱🕯)", f"{base}:w:{uid}", "blue"))
    row2 = []
    if "fate" in lm:
        row2.append(btn(f"🌀 {skill} (۳🕯)", f"{base}:f:{uid}", "green"))
    if "echo" in lm:
        row2.append(btn("🔁 بازتولد", f"{base}:e:{uid}", "green"))
    return kb(row1, row2)


GUIDE = ("⚔️ ضربه (+۱🕯) · 🛡 سپر: ۶۰٪ ضربه‌ی بعدی رو می‌گیره (+۱🕯) · 🌀 مهارتِ کلاس با ۳🕯 · "
         "🔁 بازتولد وقتی HP ≤ ۳۵٪ (هزینه: ۸٪ بقا)")


# ───────────────────────────── 🚀 شروع ─────────────────────────────
async def _fighter(doc: dict) -> dict:
    perks = await terr_perks(doc)
    gear = gear_bonus((doc.get("equip") or {}).get("item"))
    had = await store.users.find_one_and_update({"user_id": doc["user_id"], "reborn": {"$gt": 0}}, {"$inc": {"reborn": -1}})
    return make_fighter(doc, gear=gear, perks=perks, reborn=bool(had))


async def start_duel(m, duel: dict) -> bool:
    da, db_ = await store.get(duel["a"]), await store.get(duel["b"])
    busy = await store.battles.count_documents({"status": "active", "uids": {"$in": [duel["a"], duel["b"]]}})
    if busy:
        await store.duels.update_one({"_id": duel["_id"]}, {"$set": {"status": "expired"}})
        await say(m, "یکی از شما هنوز تو یه نبرد دیگه‌ست. بعد از تموم شدنش دوباره چالش بدین. ⚔️", "⚔️", "دوئل", "orange")
        return True
    fa, fb = await _fighter(da), await _fighter(db_)
    if fa["lvl"] < fb["lvl"]:            # ضعیف‌تر: یه روحِ اضافه (جبرانِ شروعِ دیرتر)
        fa["soul"] = min(MAX_SOUL, fa["soul"] + 1)
    elif fb["lvl"] < fa["lvl"]:
        fb["soul"] = min(MAX_SOUL, fb["soul"] + 1)
    first = 1 if fb["lvl"] > fa["lvl"] else 0
    b = {
        "kind": "duel", "chat_id": m.chat.id, "duel_id": duel["_id"], "uids": [duel["a"], duel["b"]],
        "f": [fa, fb], "i": first, "t": 0, "status": "active", "log": [], "msg_id": None,
        "created_at": utcnow(), "deadline": utcnow() + timedelta(seconds=TURN_SECONDS),
    }
    res = await store.battles.insert_one(b)
    b["_id"] = res.inserted_id
    extra = []
    for f, d in ((fa, da), (fb, db_)):
        if f["soul"] >= 2:
            extra.append(f"🕯 {esc(f['name'])}: روحِ شارژشده از ابتدا")
    msg = await m.reply(render_battle(b, "\n".join(extra + [GUIDE, f"⏳ نوبتِ <b>{esc(b['f'][first]['name'])}</b>"])), reply_markup=_kb(b))
    mid = getattr(msg, "message_id", None)
    if mid:
        await store.battles.update_one({"_id": b["_id"]}, {"$set": {"msg_id": mid}})
    spawn(_watch(m.bot, b["_id"], 0))
    return True


# ───────────────────────────── 🧠 پیشروی ─────────────────────────────
async def _advance(bid, turn: int, uid: Optional[int], move: str) -> Optional[dict]:
    """یک حرکت. uid=None یعنی حرکتِ خودکار. اگه نوبت/وضعیت عوض شده باشه None."""
    b = await store.battles.find_one({"_id": bid, "status": "active"})
    if not b or b["t"] != turn:
        return None
    fs, i = b["f"], b["i"]
    me, foe = fs[i], fs[1 - i]
    auto = uid is None
    if not auto and me["uid"] != uid:
        return None
    lm = legal_moves(me)
    if auto or move not in lm:
        if not auto:
            return None
        move = auto_move(me, foe)
    line = apply_move(me, foe, move)
    if auto:
        line = f"⏳ {line} (خودکار)"
    t = b["t"] + 1
    w = winner_if_over(fs, t)
    upd = {"f": fs, "t": t, "i": 1 - i, "log": (b.get("log", []) + [line])[-4:],
           "deadline": utcnow() + timedelta(seconds=TURN_SECONDS)}
    if w is not None:
        upd["status"] = "finished"
        upd["winner"] = w
    res = await store.battles.update_one({"_id": bid, "status": "active", "t": turn}, {"$set": upd})
    if not res.modified_count:
        return None
    b.update(upd)
    return b


async def _watch(bot: Bot, bid, turn: int, delay: Optional[float] = None):
    try:
        await asyncio.sleep(TURN_SECONDS + 1 if delay is None else delay)
        b = await _advance(bid, turn, None, "auto")
        if b:
            await _after(bot, b, None)
    except Exception:
        log.exception("battle watch failed")


async def _after(bot: Bot, b: dict, cq_msg):
    """بعد از هر حرکتِ موفق: ویرایشِ پنل یا اعلامِ نتیجه + زمان‌سنجِ نوبتِ بعد."""
    if b["status"] == "finished":
        await _finish(bot, b, cq_msg)
        return
    text, mk = render_battle(b), _kb(b)
    try:
        if cq_msg is not None:
            await safe_edit(cq_msg, text, mk)
        elif b.get("msg_id"):
            await bot.edit_message_text(text, chat_id=b["chat_id"], message_id=b["msg_id"], reply_markup=mk)
    except Exception as e:
        log.debug("battle edit failed: %s", e)
    spawn(_watch(bot, b["_id"], b["t"]))


async def battle_cb(cq, bot: Bot, parts: list):
    """bt:mv:<battle>:<turn>:<code>:<uid>"""
    try:
        bid, turn, code = ObjectId(parts[2]), int(parts[3]), parts[4]
    except Exception:
        await cq.answer()
        return
    move = _CODE.get(code)
    if not move:
        await cq.answer()
        return
    b = await _advance(bid, turn, cq.from_user.id, move)
    if not b:
        await cq.answer("نوبتت نیست یا این دکمه قدیمی شده. ⏳", show_alert=False)
        return
    await cq.answer()
    await _after(bot, b, cq.message)


# ───────────────────────────── 🏁 پایان و جایزه ─────────────────────────────
async def _finish(bot: Bot, b: dict, cq_msg):
    """فقط کسی صداش می‌زنه که تو _advance وضعیت رو finished کرده؛ پس جایزه دقیقاً یک‌بار پرداخت میشه."""
    fs, w = b["f"], b["winner"]
    win, lose = fs[w], fs[1 - w]
    wid, lid = win["uid"], lose["uid"]
    now = utcnow()
    repeat = await store.duels.count_documents({
        "status": "done", "finished_at": {"$gt": now - timedelta(seconds=DUEL_REWARD_COOLDOWN)},
        "$or": [{"a": wid, "b": lid}, {"a": lid, "b": wid}], "_id": {"$ne": b.get("duel_id")}})
    margin = pct(win)
    toll_w, toll_l = REBIRTH_TOLL * win["used_echo"], REBIRTH_TOLL * lose["used_echo"]
    loss_l = 6 + round(10 * margin) + toll_l
    loss_w = round(6 * (1 - margin)) + toll_w
    reward = 0 if repeat else min(60, 15 + 2 * lose["lvl"])
    wdoc, leveled = await grant(wid, gold=reward, xp=10 if repeat else 25, survival=-loss_w if loss_w else 0, counters={"wins": 1})
    ldoc, _ = await grant(lid, xp=6, survival=-loss_l, counters={"losses": 1})
    await store.duels.update_one({"_id": b.get("duel_id")}, {"$set": {"status": "done", "finished_at": now, "winner": wid}})
    await store.battles.update_one({"_id": b["_id"]}, {"$set": {"closed_at": now}})
    await store.groups.update_one({"chat_id": b["chat_id"]}, {"$inc": {"duels": 1}}, upsert=True)

    lines = [
        f"🛡 {display(wdoc, link=True)} ❤️{max(win['hp'], 0)}/{win['max_hp']}",
        "      ⚔️ VS ⚔️",
        f"🗡 {display(ldoc, link=True)} ❤️{max(lose['hp'], 0)}/{lose['max_hp']}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"🏆 برنده: {display(wdoc, link=True)} — " + (f"🪙 +{reward} {GS} و " if reward else "") + ("۲۵ XP" if not repeat else "۱۰ XP"),
        f"🩸 بازنده: {display(ldoc, link=True)} — −{loss_l}٪ بقا ({_bar(int(ldoc['survival_rate']), 100)})",
    ]
    if repeat:
        lines.append("🔁 این دوئل تکراری بود؛ ایزدبانو GS نمی‌ده (یه ساعت صبر کنین).")
    for f, t in ((win, toll_w), (lose, toll_l)):
        if t:
            lines.append(f"🔁 {esc(f['name'])} بازتولد شد: −{t}٪ بقا (هزینه‌ی پژواک)")
    if leveled:
        lines.append(f"🆙 {esc(wdoc.get('first_name'))} لول‌آپ شد!")
    text = panel("orange", "🥊", "نتیجه‌ی نبردِ رشته‌ی سرنوشت", lines,
                 f"💅 <i>«{GODDESS_NAME}: …تماشاش سرگرم‌کننده بود. تکرارش کنین.»</i>")
    mk = kb([btn("🌙 منو", f"m:main:{wid}", "green")])
    try:
        if cq_msg is not None:
            await safe_edit(cq_msg, text, mk)
        elif b.get("msg_id"):
            await bot.edit_message_text(text, chat_id=b["chat_id"], message_id=b["msg_id"], reply_markup=mk)
        else:
            await bot.send_message(b["chat_id"], text, reply_markup=mk)
    except Exception:
        await bot.send_message(b["chat_id"], text, reply_markup=mk)
    # 💀 زخمِ کشنده → بازتولد (مثل قبل)؛ برنده هم اگه بابتِ هزینه‌ی پژواک به مرز رسید
    for d in (ldoc, wdoc):
        if int((await store.get(d["user_id"])).get("survival_rate", 100)) <= 2:
            rdoc, new = await reincarnate(d["user_id"], chat_id=b["chat_id"])
            await bot.send_message(b["chat_id"], f"💀 زخم‌های {display(rdoc, link=True)} کشنده بود!\n{render_scene(display(rdoc, link=True))}\n\n{render_rebirth(rdoc, new)}")
    shim_w = _Shim(bot, b["chat_id"], wid)
    await add_guild_pts(wdoc.get("guild"), 5)
    await quest_progress(shim_w, "duel", uid=wid)
    await quest_progress(shim_w, "duel", uid=lid)
    await quest_progress(shim_w, "duel_win", uid=wid)


# ───────────────────────────── 🩹 ریکاوری بعد از ری‌استارت ─────────────────────────────
async def recover_battles(bot: Bot):
    try:
        async for b in store.battles.find({"status": "active"}):
            age = (utcnow() - b["created_at"]).total_seconds()
            if age > BATTLE_STALE:
                await store.battles.update_one({"_id": b["_id"], "status": "active"}, {"$set": {"status": "abandoned"}})
                await store.duels.update_one({"_id": b.get("duel_id")}, {"$set": {"status": "expired"}})
                continue
            left = max(1.0, (b["deadline"] - utcnow()).total_seconds())
            spawn(_watch(bot, b["_id"], b["t"], delay=left))
    except Exception:
        log.exception("recover_battles failed")
