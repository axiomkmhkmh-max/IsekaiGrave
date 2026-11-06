"""🧭 سفرِ ماجراجویی (فاز ۲): بعد از یه گشت، گاهی یه «ردپا» پیدا میشه و ماجرا ۳ مرحله ادامه داره — ساده، با ۳ دکمه‌ی انتخاب:

  مرحله ۱ ورودی (برو داخل / دور و بر رو بگرد / بی‌خیال) → مرحله ۲ مانع (بجنگ / دور بزن / ریسک کن) → مرحله ۳ پایان
  (غول یا نگهبانِ آخر: روبه‌رو / با تله / فرار).

قوانین: نتیجه و جایزه فقط با کد و قانون‌های ثابتِ پایین حساب میشه (AI فقط می‌تونه صحنه‌ی مرحله‌ی آخر رو روایت کنه).
داخلِ سفر بازیکن نمی‌میره (بقا هیچ‌وقت زیرِ MIN_KEEP نمیره)؛ جایزه‌ی کلِ ماجرا تقریباً هم‌ردیفِ ۴-۵ گشتِ معمولیه.
وضعیت فقط تو حافظه‌ست (دیتابیس/دیتای بازیکن عوض نمیشه)؛ ریستارت یا ۱۵ دقیقه بی‌حرکتی = ردپا سرد میشه.
"""

import random
import time
from typing import Callable, Optional

from advscene import scene as scene_ai
from config import GS
from content import BIOMES, roll_item
from database import store
from players import cls_is, gold_bonus, grant, loss_cut
from regions_new import GIANT_MIN_LVL
from ui import btn, kb, panel
from utils import esc

CHANCE = 0.35          # احتمالِ پیدا شدنِ ردپا بعد از هر گشتِ موفق (غیرِ شهر)
TTL = 900
MIN_KEEP = 3           # بقا داخلِ سفر هیچ‌وقت از این کمتر نمیشه
_runs: dict = {}

TEASERS = [
    "🕳 ردپای بزرگی روی زمین دیدی که به یه جای مشکوک می‌ره… (ماجرا ادامه داره)",
    "🗝 یه نقشه‌ی پاره با علامتِ ✖ گوشه‌ی کیفت پیدا کردی… (ماجرا ادامه داره)",
    "🔦 صدای ناله‌ای از دور میاد؛ شاید گنج، شاید تله… (ماجرا ادامه داره)",
    "🕯 نورِ ضعیفی لای تاریکی چشمک می‌زنه؛ ماجرا هنوز تموم نشده… (ماجرا ادامه داره)",
]


def start_trail(uid: int, key: str) -> str:
    """ردپا رو ثبت می‌کنه و جمله‌ی تیزر برمی‌گردونه (دکمه‌ی «دنبالش برو» رو صدازننده می‌ذاره)."""
    now = time.time()
    if len(_runs) > 3000:
        for k in [k for k, v in _runs.items() if now - v["t"] > TTL]:
            _runs.pop(k, None)
    _runs[uid] = {"biome": key, "stage": 1, "edge": 0, "started": False, "foe": None, "t": now}
    return random.choice(TEASERS)


def _power(doc: dict, edge: int) -> float:
    return (doc.get("level", 1) * 4 + doc.get("survival_rate", 50) / 2 + random.randint(0, 25)
            + (8 if cls_is(doc, "warrior") else 0) + edge)


def _hurt(doc: dict, v: int) -> int:
    """کاهشِ بقا؛ هیچ‌وقت بازیکن رو زیر MIN_KEEP نمی‌بره (داخلِ سفر مرگ نیست)."""
    return max(0, min(loss_cut(doc, v), doc.get("survival_rate", 50) - MIN_KEEP))


def _gold(doc: dict, g: int) -> int:
    return int(gold_bonus(doc, g))


def _best_item(B: dict) -> str:
    a, b = roll_item(B["items"]), roll_item(B["items"])
    return (a if a[1] >= b[1] else b)[0]


def _choices(uid: int, stage: int, labels: tuple):
    return kb(*[[btn(t, f"e:{k}:{stage}:{uid}", c)] for k, t, c in zip("abc", labels, ("green", "blue", "red"))])


def _end_kb(uid: int, key: str):
    return kb([btn("🌍 دوباره بگرد", f"x:{key}:{uid}", "green"), btn("🌙 منو", f"m:main:{uid}", "blue")])


async def _prompt(uid: int, run: dict, doc: dict, B: dict) -> tuple:
    """(خطوطِ سوالِ مرحله‌ی فعلی، کیبورد)."""
    st = run["stage"]
    if st == 1:
        return (["🕳 ردپا تو رو به ورودیِ یه جای مشکوک رسوند؛ تاریک، ساکت و بدجور دعوت‌کننده."],
                _choices(uid, 1, ("🚪 برو داخل", "🔍 اول دور و برو بگرد", "🏃 بی‌خیال")))
    if st == 2:
        name, strength = run["foe"]
        return ([f"👹 <b>{esc(name)}</b> راهت رو بسته! (قدرت {strength})"],
                _choices(uid, 2, ("⚔️ بجنگ", "🥷 دور بزن", "🎲 ریسک کن")))
    name, strength, giant = run["foe"]
    lines = [f"🐲 <b>غولِ {esc(name)}</b> آخرِ مسیر منتظرته! (قدرت {strength})" if giant
             else f"👹 <b>{esc(name)}</b>، نگهبانِ آخرِ مسیر، جلوته! (قدرت {strength})"]
    if giant:
        sc = await scene_ai(B, "giant", name, uid)
        if sc:
            lines.append(f"📖 <i>{esc(sc)}</i>")
    return lines, _choices(uid, 3, ("⚔️ نبرد روبه‌رو", "🪤 با تله و نقشه", "🏃 فرار با غنیمتِ مسیر"))


def _enter(run: dict, B: dict, doc: dict, stage: int) -> None:
    run["stage"] = stage
    if stage == 2:
        run["foe"] = random.choice(B["monsters"])
    elif stage == 3:
        if B.get("giants") and doc.get("level", 1) >= GIANT_MIN_LVL:
            n, s = random.choice(B["giants"])
            run["foe"] = (n, s, True)
        else:
            n, s = max(B["monsters"], key=lambda x: x[1])
            run["foe"] = (n, s, False)


async def expedition_cb(uid: int, act: str, stage_s: str, edit: Callable) -> None:
    """edit(text, markup): همون پیامِ دکمه رو ویرایش می‌کنه (ماجرا تو یک پیام جلو میره)."""
    run = _runs.get(uid)
    if not run or time.time() - run["t"] > TTL:
        _runs.pop(uid, None)
        await edit(panel("brown", "🧭", "ردپا سرد شد", ["ردپا قدیمی شده؛ یه گشتِ تازه بزن تا ردپای جدید پیدا کنی."]),
                   kb([btn("🌍 ماجراجویی", f"m:go:{uid}", "green")]))
        return
    doc = await store.get(uid)
    if not doc:
        return
    key = run["biome"]
    B = BIOMES[key]
    title = f"{B['name']} — ماجرا"
    run["t"] = time.time()

    if act == "go" or act not in ("a", "b", "c") or stage_s != str(run["stage"]):
        run["started"] = True                       # شروع، یا دکمه‌ی کهنه/دوبار کلیک → فقط صحنه‌ی فعلی رو دوباره نشون بده
        lines, mk = await _prompt(uid, run, doc, B)
        await edit(panel(B["color"], B["icon"], f"{title} ({run['stage']}/3)", lines), mk)
        return

    st = run["stage"]
    res: list = []
    gold = xp = surv = 0
    item: Optional[str] = None
    nxt: Optional[int] = None

    if st == 1:
        if act == "a":
            res, nxt = ["🚪 با احتیاط رفتی تو."], 2
        elif act == "b":
            if random.random() < 0.7:
                gold, xp = _gold(doc, random.randint(5, 15)), random.randint(6, 12)
                run["edge"] = 8
                res = [f"🔍 دور و بر رو گشتی و چیزی پیدا کردی و راهِ امن‌تری شناختی! 🪙 +{gold} {GS}"]
            else:
                run["edge"] = 3
                res = ["🔍 چیزِ خاصی پیدا نکردی، ولی با محیط آشنا شدی."]
            nxt = 2
        else:
            xp, res = 3, ["🏃 بی‌خیال شدی و ردپا سرد شد. (+۳ XP)"]
    elif st == 2:
        name, strength = run["foe"]
        if act == "a":
            if _power(doc, run["edge"]) >= strength + random.randint(0, 25):
                gold, xp = _gold(doc, random.randint(8, 30)), random.randint(18, 35)
                res, nxt = [f"⚔️ <b>{esc(name)}</b> رو شکست دادی! 🪙 +{gold} {GS}"], 3
            else:
                surv, xp = -_hurt(doc, random.randint(8, 20)), 4
                res = [f"🩸 <b>{esc(name)}</b> ازت قوی‌تر بود و مجبور شدی عقب بکشی. −{-surv}٪ بقا."]
        elif act == "b":
            if random.random() < 0.6:
                res = ["🥷 بی‌صدا ازش رد شدی."]
            else:
                surv = -_hurt(doc, random.randint(5, 12))
                res = [f"😬 لو رفتی و یه ضربه خوردی، ولی ردش کردی. −{-surv}٪ بقا."]
            nxt = 3
        else:
            if random.random() < 0.5:
                gold, xp = _gold(doc, random.randint(15, 40)), random.randint(10, 20)
                res, nxt = [f"🎲 شانس آوردی و یه راهِ میون‌بر پیدا کردی! 🪙 +{gold} {GS}"], 3
            else:
                surv, xp = -_hurt(doc, random.randint(12, 24)), 3
                res = [f"🎲 ریسک جواب نداد و زمین خوردی. −{-surv}٪ بقا."]
    else:
        name, strength, giant = run["foe"]
        if act == "c":
            gold, xp = _gold(doc, random.randint(10, 25)), 5
            res = [f"🏃 به‌موقع فرار کردی و غنیمتِ مسیر رو برداشتی. 🪙 +{gold} {GS}"]
        else:
            edge = run["edge"] + (12 if act == "b" else 0)
            if _power(doc, edge) >= strength + random.randint(0, 25):
                gold = _gold(doc, random.randint(40, 90) if giant else random.randint(20, 45))
                xp = random.randint(60, 100) if giant else random.randint(30, 50)
                item = _best_item(B)
                res = [f"🏆 <b>{esc(name)}</b> رو زمین زدی و ماجرا رو تموم کردی!\n🪙 +{gold} {GS}\n🎁 غنیمت: {esc(item)}"]
            else:
                surv, xp = -_hurt(doc, random.randint(18, 32)), 6
                res = [f"🩸 <b>{esc(name)}</b> تو رو کوبید و عقب‌نشینی کردی. −{-surv}٪ بقا. با سطح یا بقای بیشتر برگرد!"]

    leveled = False
    if gold or xp or surv or item:
        doc, leveled = await grant(uid, gold=gold, xp=xp, item=item, survival=surv)
    if leveled:
        res.append(f"🆙 <b>سطحت بالا رفت!</b> حالا سطح {doc.get('level', 1)} هستی. 🎉")

    if nxt is None:                                  # پایانِ ماجرا
        _runs.pop(uid, None)
        await edit(panel(B["color"], B["icon"], f"{title} — پایان", res), _end_kb(uid, key))
        return
    _enter(run, B, doc, nxt)
    lines, mk = await _prompt(uid, run, doc, B)
    await edit(panel(B["color"], B["icon"], f"{title} ({nxt}/3)", res + ["┈┈┈┈┈┈┈┈┈┈", *lines]), mk)
