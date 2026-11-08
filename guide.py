"""راهنمای بازیکن: «الان چیکار کنم؟»، تور شروع، منوی تدریجی (قفل/بازشدنِ بخش‌ها)،
توضیحِ اولین‌بارِ هر بخش و جمله‌های کاربردیِ ایزدبانو.

ایده: بازیکن باید همیشه بدونه «قدم بعدی» چیه. این ماژول فقط به database/players/ui وابسته‌ست
(menus و callbacks ازش استفاده می‌کنن)؛ ایمپورت‌های quests داخلِ تابع‌ها تنبلن تا حلقه‌ی ایمپورت نشه.
"""

import random
import time
from typing import Optional

from config import GUILD_COST, WHEEL_COOLDOWN, log
from database import store
from players import grant
from ui import back_kb, btn, kb, panel, show
from utils import day_key, esc, utcnow

XP_PER_LEVEL = 100          # سطح = ۱ + xp // ۱۰۰ (همون فرمولِ players.grant)
ALL_UNLOCKED = 99           # وقتی doc نداریم، همه‌چیز باز فرض میشه (ایمنی)


# ───────────────────────────── 🗂 بخش‌ها: سطحِ بازشدن + توضیحِ یک‌خطی ─────────────────────────────
# lvl: از چه سطحی دکمه‌ی منو باز میشه (قفلِ «ظاهری»؛ دستورهای متنی مثل قبل کار می‌کنن)
# desc: توضیحِ یک‌خطی (≤ ~۷۰ کاراکتر؛ تو هشدارِ قفل هم میاد، پس کوتاه نگهش دار)
# tip: نکته‌ی کاربردی که فقط اولین‌بار نشون داده میشه
FEATURES = {
    "world":  dict(icon="🌐", name="جهان", lvl=1, cat="world", color="blue",
                   desc="ساعت، رویدادها و اخبارِ دنیای زنده؛ بدونی کجا خطرناکه.",
                   tip="قبل از سفر یه نگاه بنداز؛ منطقه‌ی خطرناک یعنی ریسکِ بیشتر."),
    "cheat":  dict(icon="🌟", name="چیت‌اسکیل و کلاس", lvl=1, cat="world", color="purple",
                   desc="مهارتِ ویژه‌ات؛ فعال‌سازی چند گشتِ بعدی رو قوی‌تر می‌کنه.",
                   tip="فعال‌سازی هزینه (GS یا بقا) و خنک‌سازی داره؛ قبل از ماجراجویی فعالش کن."),
    "wheel":  dict(icon="🎡", name="گردونه‌ی شانس", lvl=1, cat="world", color="green",
                   desc="هر ۲۴ ساعت یه چرخش: GS، شفا یا چیت‌اسکیل جدید (یا نفرین!).",
                   tip="بقات رو به یه عددِ تصادفی ریست می‌کنه؛ وقتی بقات پایینه بهترین وقتشه."),
    "board":  dict(icon="🏆", name="لیدربرد", lvl=1, cat="world", color="blue",
                   desc="رتبه‌ی برترین بازیکن‌ها و گروه‌ها.", tip=""),
    "arena":  dict(icon="🏟", name="میدان نبرد", lvl=3, cat="fight", color="red",
                   desc="حمله‌ی ژستی به بقیه تو گروه؛ رتبه (RP) و جایزه‌ی هفتگی.",
                   tip="تو گروه روی پیامِ یه نفر ریپلای کن و «حمله» بنویس؛ ژستت مخفیه و حریف ۴۵ ثانیه وقتِ دفاع داره. «تمرین» بدونِ ریسکه."),
    "boss":   dict(icon="🐉", name="باس گروه", lvl=3, cat="fight", color="red",
                   desc="تو گروه یه باسِ مشترک احضار کنید و با هم بزنیدش.",
                   tip="تو گروه «احضار باس» بنویس؛ بقیه با «حمله به باس» یا دکمه‌ها می‌زنن."),
    "war":    dict(icon="⚔️", name="جنگ گیلدها", lvl=3, cat="fight", color="red",
                   desc="گیلدت با یه گیلدِ دیگه رقابت می‌کنه.",
                   tip="اول عضو یه گیلد شو («پیوستن به گیلد [نام]»)."),
    "terr":   dict(icon="👑", name="قلمروها", lvl=3, cat="fight", color="green",
                   desc="گیلدها قلمرو می‌گیرن و مزیت و درآمد برمی‌دارن.",
                   tip="محاصره: «محاصره [نام قلمرو]» (گیلد لازمه)."),
    "gs":     dict(icon="🪙", name="GS", lvl=1, cat="eco", color="yellow",
                   desc="ارزِ بازی (GRAVE SIGIL)؛ با ماجراجویی و ماموریت می‌گیری.",
                   tip="خرجش: کوره، گیلد، بازار روح و چیت‌اسکیل. درآمدِ روزانه سقف داره."),
    "exch":   dict(icon="🪦", name="بازار روح", lvl=2, cat="eco", color="green",
                   desc="بازارِ بازیکن‌به‌بازیکن؛ آیتم می‌فروشی و می‌خری.",
                   tip="فروش: «فروش [شماره‌ی آیتم] [قیمت]». کارمزد ۸٪ ه و سوخته میشه."),
    "forge":  dict(icon="🔥", name="کوره‌ی روح", lvl=2, cat="eco", color="red",
                   desc="روح‌سلاح‌هات رو ارتقا و ادغام کن تا قوی‌تر بشی.",
                   tip="تجهیز: «تجهیز [شماره‌ی آیتم]». ارتقا و ادغام با GS انجام میشه."),
    "market": dict(icon="🕶", name="بازار سیاه", lvl=2, cat="eco", color="red",
                   desc="دلالِ سیاه (فقط تو گروه) گاهی آیتمِ خاص می‌فروشه.",
                   tip="وقتی ظاهر شد دکمه‌ی «میخرم» یا نوشتنِ «میخرم» رو بزن."),
    "guild":  dict(icon="🛡", name="گیلد من", lvl=2, cat="soc", color="blue",
                   desc="تیمِ بازیکن‌ها؛ خزانه، دژ، قلمرو و جنگ دارن.",
                   tip=f"ساخت: «ساخت گیلد [نام]» ({GUILD_COST} GS) · عضویت: «پیوستن به گیلد [نام]»."),
    "marry":  dict(icon="💍", name="پیوند", lvl=3, cat="soc", color="red",
                   desc="پیوندِ ایسکایی با یه بازیکنِ دیگه.",
                   tip="ریسک: وقتی یکی می‌میره، اون یکی هم زخمی میشه (−۶٪ بقا و −۱۰ GS)."),
}

CATS = {
    "world": ("🌐", "دنیا و مهارت", "blue"),
    "fight": ("⚔️", "نبرد", "red"),
    "eco":   ("💰", "اقتصاد", "green"),
    "soc":   ("👥", "اجتماعی", "blue"),
}
CAT_ACT = {"cworld": "world", "cfight": "fight", "ceco": "eco", "csoc": "soc"}   # callback act → دسته


def level_of(doc: Optional[dict]) -> int:
    if not doc:
        return ALL_UNLOCKED
    try:
        return int(doc.get("level", 1) or 1)
    except (TypeError, ValueError):
        return 1


def xp_to_next(doc: dict) -> int:
    return XP_PER_LEVEL - int(doc.get("xp", 0) or 0) % XP_PER_LEVEL


def is_open(doc: Optional[dict], key: str) -> bool:
    return level_of(doc) >= FEATURES[key]["lvl"]


def feat_button(uid: int, doc: Optional[dict], key: str):
    f = FEATURES[key]
    if is_open(doc, key):
        return btn(f"{f['icon']} {f['name']}", f"m:{key}:{uid}", f["color"])
    return btn(f"🔒 {f['name']} · سطح {f['lvl']}", f"m:lock:{key}:{uid}")


def cat_button(uid: int, doc: Optional[dict], ckey: str):
    icon, name, color = CATS[ckey]
    keys = [k for k, f in FEATURES.items() if f["cat"] == ckey]
    if any(is_open(doc, k) for k in keys):
        return btn(f"{icon} {name}", f"m:c{ckey}:{uid}", color)
    need = min(FEATURES[k]["lvl"] for k in keys)
    return btn(f"🔒 {name} · سطح {need}", f"m:lock:cat_{ckey}:{uid}")


def lock_text(doc: Optional[dict], key: str) -> str:
    """متنِ هشدارِ دکمه‌ی قفل (تلگرام: حداکثر ۲۰۰ کاراکتر)."""
    if key.startswith("cat_") and key[4:] in CATS:
        keys = [k for k, f in FEATURES.items() if f["cat"] == key[4:]]
        need = min(FEATURES[k]["lvl"] for k in keys)
        name = CATS[key[4:]][1]
        desc = "؛ ".join(FEATURES[k]["name"] for k in keys)
    elif key in FEATURES:
        f = FEATURES[key]
        need, name, desc = f["lvl"], f["name"], f["desc"]
    else:
        return "این بخش هنوز باز نشده. 🔒"
    cur = level_of(doc)
    left = f" ({xp_to_next(doc)} XP تا سطح بعد)" if doc else ""
    return f"🔒 «{name}» از سطح {need} باز میشه. الان سطح {cur}ی{left}.\n{desc}"[:195]


# ───────────────────────────── 🔓 اعلامِ بازشدن ─────────────────────────────
async def pop_unlock_news(doc: Optional[dict]) -> list:
    """بخش‌هایی که از آخرین اعلام تا سطحِ فعلی باز شدن؛ فقط یک‌بار (ادعای اتمیک با unlock_seen).
    بازیکنِ قدیمی (بدونِ فیلد) بی‌صدا به سطحِ فعلی علامت می‌خوره تا یهو پیامِ قدیمی نخوره."""
    if not doc or not doc.get("user_id"):
        return []
    uid, lvl = doc["user_id"], level_of(doc)
    seen = doc.get("unlock_seen")
    try:
        if seen is None:
            await store.users.update_one({"user_id": uid, "unlock_seen": {"$exists": False}}, {"$set": {"unlock_seen": lvl}})
            return []
        seen = int(seen)
        if lvl <= seen:
            return []
        res = await store.users.update_one({"user_id": uid, "unlock_seen": seen}, {"$set": {"unlock_seen": lvl}})
        if not res.modified_count:
            return []
    except Exception:
        log.exception("unlock news failed")
        return []
    new = [f for f in FEATURES.values() if seen < f["lvl"] <= lvl]
    if not new:
        return []
    lines = [f"🔓 <b>باز شد!</b> {f['icon']} {f['name']} — {f['desc']}" for f in new]
    lines.append("💅 <i>«سطحت بالا رفت و بازیچه‌های جدید گیرت اومد. خرابشون نکن… نه، خرابشون کن؛ دیدنش جالبه.»</i>")
    return lines


# ───────────────────────────── 📘 توضیحِ اولین‌بار ─────────────────────────────
INTRO_FEATS = {k for k, f in FEATURES.items() if f["tip"]}


async def intro_once(m, key: str):
    """اولین باری که بازیکن وارد یه بخش میشه، یه توضیحِ کوتاه (چیه؟ چه‌کار کنم؟) می‌فرسته."""
    if key not in INTRO_FEATS:
        return
    try:
        uid = m.from_user.id
        res = await store.users.update_one({"user_id": uid, f"seen.{key}": {"$exists": False}}, {"$set": {f"seen.{key}": True}})
        if not res.modified_count:
            return
        f = FEATURES[key]
        await m.reply(panel("blue", "📘", f"{f['name']} چیه؟", [f"{f['icon']} {f['desc']}", f"💡 {f['tip']}"]))
    except Exception:
        log.exception("intro_once failed")


# ───────────────────────────── 🎓 تور شروع ─────────────────────────────
# (کلید، آیکون، عنوان، توضیح، (متنِ دکمه، callback پایه))
TUT = [
    ("explore", "🌍", "اولین ماجراجویی", "دکمه‌ی «ماجراجویی» رو بزن و یه مکان انتخاب کن. گنج، هیولا و XP اونجا منتظره.",
     ("🌍 برو ماجراجویی", "m:go")),
    ("quest", "📜", "دفتر ماموریت‌ها", "هر روز ۳ ماموریت داری؛ انجامشون GS و XP می‌ده. یه نگاه بهشون بنداز.",
     ("📜 ماموریت‌ها", "m:quest")),
    ("inv", "🎒", "کوله‌پشتی", "آیتم‌هایی که پیدا می‌کنی اینجا جمع میشه؛ بعداً تجهیز، فروش یا ارتقاشون می‌دی.",
     ("🎒 کوله‌پشتی", "m:inv")),
    ("npc", "💬", "حرف زدن با یه NPC", "تو شهر و وسط ماجراجویی آدم‌های زنده سبز میشن؛ وقتی دکمه‌ی «💬 حرف زدن» اومد بزنش. شهر شانسش بیشتره.",
     ("🏰 برو شهر", "x:city")),
]
TUT_KEYS = [t[0] for t in TUT]
TUT_STEP_GS, TUT_STEP_XP = 15, 15
TUT_DONE_GS, TUT_DONE_XP = 40, 30


def tut_state(doc: Optional[dict]) -> Optional[dict]:
    t = (doc or {}).get("tut")
    return t if isinstance(t, dict) else None       # None = بازیکنِ قدیمی (تور نداره)


def tut_active(doc: Optional[dict]) -> bool:
    t = tut_state(doc)
    return t is not None and not t.get("skip") and not t.get("done")


def tut_next(doc: dict) -> Optional[tuple]:
    t = tut_state(doc) or {}
    for step in TUT:
        if not t.get(step[0]):
            return step
    return None


def tut_count(doc: dict) -> int:
    t = tut_state(doc) or {}
    return sum(1 for k in TUT_KEYS if t.get(k))


async def tut_mark(m, key: str, uid: Optional[int] = None):
    """یه مرحله‌ی تور رو تیک می‌زنه (فقط یک‌بار، اتمیک)، جایزه می‌ده و پیامِ کوتاه می‌فرسته. هیچ‌وقت خطا نمیده."""
    if key not in TUT_KEYS:
        return
    try:
        uid = uid or m.from_user.id
        doc = await store.get(uid)
        if not tut_active(doc):
            return
        res = await store.users.update_one(
            {"user_id": uid, f"tut.{key}": {"$exists": False}, "tut.skip": {"$ne": True}, "tut.done": {"$ne": True}},
            {"$set": {f"tut.{key}": True}})
        if not res.modified_count:
            return
        step = next(s for s in TUT if s[0] == key)
        n = tut_count(doc) + 1
        _, leveled = await grant(uid, gold=TUT_STEP_GS, xp=TUT_STEP_XP)
        lines = [f"✅ <b>{step[1]} {step[2]}</b> انجام شد!", f"🎁 🪙 +{TUT_STEP_GS} · ⭐ +{TUT_STEP_XP}"]
        all_done = n >= len(TUT)
        if all_done:
            fin = await store.users.update_one({"user_id": uid, "tut.done": {"$ne": True}}, {"$set": {"tut.done": True}})
            if fin.modified_count:
                _, lv2 = await grant(uid, gold=TUT_DONE_GS, xp=TUT_DONE_XP)
                leveled = leveled or lv2
                lines += ["┈┈┈┈┈┈┈┈┈┈", f"🎓 <b>تور شروع تموم شد!</b> جایزه‌ی پایانی: 🪙 +{TUT_DONE_GS} · ⭐ +{TUT_DONE_XP}",
                          "از اینجا به بعد، هر وقت گیج شدی دکمه‌ی «🎯 الان چیکار کنم؟» رو بزن."]
        fresh = await store.get(uid)
        if leveled:
            lines.append(f"🆙 سطحت بالا رفت! حالا سطح {level_of(fresh)} هستی.")
            lines += await pop_unlock_news(fresh)
        title = f"تور شروع — {min(n, len(TUT))} از {len(TUT)}"
        foot = None if all_done else "💅 <i>«آفرین. حالا برو سراغ قدم بعدی، قبل از اینکه حوصله‌م سر بره.»</i>"
        await m.reply(panel("green", "🎓", title, lines, foot),
                      reply_markup=kb([btn("🎯 قدم بعدی؟" if not all_done else "🎯 الان چیکار کنم؟", f"m:next:{uid}", "green")]))
    except Exception:
        log.exception("tut_mark failed")


# ───────────────────────────── 🎯 موتورِ «الان چیکار کنم؟» ─────────────────────────────
def wheel_ready(doc: dict) -> bool:
    last = doc.get("last_wheel_at")
    return not last or (utcnow() - last).total_seconds() >= WHEEL_COOLDOWN


def _cheat_info(doc: dict) -> Optional[tuple]:
    """(نام، نوعِ هزینه، مقدار) اگه چیت‌اسکیل الان قابل فعال‌سازیه؛ وگرنه None."""
    ch = doc.get("cheat")
    if not isinstance(ch, dict) or int(doc.get("cheat_charges", 0) or 0) > 0:
        return None
    if int(doc.get("cheat_cd") or 0) > time.time():
        return None
    try:
        (ctype, amt), = ch["cost"].items()
        name = ch.get("name_fa") or "چیت‌اسکیل"
        amt = int(amt)
    except Exception:
        return None
    ok = int(doc.get("survival_rate", 0)) > amt + 5 if ctype == "survival" else int(doc.get("gold", 0)) >= amt
    return (name, ctype, amt) if ok else None


_SOLO_QUESTS = ("trip", "npc", "wheel", "trade")


def _quest_button(uid: int, kind: str, lvl: int):
    if kind == "trip":
        return btn("🌍 برو ماجراجویی", f"m:go:{uid}", "green")
    if kind == "npc":
        return btn("🏰 برو شهر (NPC زیاده)", f"x:city:{uid}", "green")
    if kind == "wheel":
        return btn("🎡 چرخوندنِ گردونه", f"m:wheel:{uid}", "green")
    if kind == "trade" and lvl >= FEATURES["exch"]["lvl"]:
        return btn("🪦 بازار روح", f"m:exch:{uid}", "green")
    return None


def _sug(title: str, why: str, button=None) -> dict:
    return {"title": title, "why": why, "btn": button}


async def suggestions(doc: dict) -> list:
    """فهرستِ پیشنهادها به ترتیبِ اولویت (همیشه حداقل یکی). هر کدوم: title/why/btn."""
    uid, lvl = doc["user_id"], level_of(doc)
    r = int(doc.get("survival_rate", 100) or 0)
    out = []

    # ۰) تور شروع
    step = tut_next(doc) if tut_active(doc) else None
    if step:
        out.append(_sug(f"🎓 تور شروع ({tut_count(doc)}/{len(TUT)}): {step[1]} {step[2]}", step[3],
                        btn(step[4][0], f"{step[4][1]}:{uid}", "green")))

    # ۱) بقای خطرناک
    if r < 35:
        if wheel_ready(doc):
            out.append(_sug("🎡 بقات پایینه؛ گردونه رو بچرخون",
                            f"بقات {r}٪ه و زیر ۲٪ بمیری دوباره متولد میشی. گردونه بقات رو به یه عددِ تصادفیِ بالاتر ریست می‌کنه (بیشترِ وقت‌ها).",
                            btn("🎡 چرخوندنِ گردونه", f"m:wheel:{uid}", "green")))
        else:
            out.append(_sug("💚 بقات پایینه",
                            f"بقات {r}٪ه؛ هر شکستِ ماجراجویی ازش کم می‌کنه و زیر ۲٪ می‌میری. تو گروه از یه نفر بخواه روی پیامت ریپلای کنه و «ترمیم» بنویسه."))

    # ۲) ماموریت‌های ناتمومِ امروز (اول اونایی که تنها قابل انجامن)
    try:
        from quests import ensure_quests
        q = await ensure_quests(uid, doc)
        undone = [i for i in q.get("daily", []) if not i.get("done")]
        undone.sort(key=lambda i: 0 if i["k"] in _SOLO_QUESTS else 1)
        if undone:
            it = undone[0]
            b = _quest_button(uid, it["k"], lvl)
            why = f"({it['have']}/{it['need']}) جایزه: 🪙 {it['gold']} + ⭐ {it['xp']}"
            if not b:
                why += "\n👥 این یکی تو گروه انجام میشه (ریپلای روی پیامِ یه نفر یا نوشتنِ دستورش)."
            out.append(_sug(f"📜 ماموریتِ امروز: {esc(it['t'])}", why, b))
    except Exception:
        log.exception("suggestions: quests failed")

    # ۳) گردونه‌ی آماده (وقتی بقا متوسطه تا بالا نخوره)
    if wheel_ready(doc) and r < 55 and not any("گردونه" in s["title"] for s in out):
        out.append(_sug("🎡 گردونه‌ی امروز آماده‌ست", "هر ۲۴ ساعت یه بار؛ GS، شفا یا چیت‌اسکیلِ جدید می‌ده.",
                        btn("🎡 چرخوندنِ گردونه", f"m:wheel:{uid}", "green")))

    # ۴) چیت‌اسکیلِ آماده
    ci = _cheat_info(doc)
    if ci:
        name, ctype, amt = ci
        cost = f"{amt}٪ بقا" if ctype == "survival" else f"{amt} GS"
        out.append(_sug(f"🔥 {esc(name)} آماده‌ست", f"قبل از ماجراجویی فعالش کن تا چند گشتِ بعدی قوی‌تر باشی. هزینه: {cost}.",
                        btn("🔥 فعال‌سازی", f"ch:use:{uid}", "red")))

    # ۵) گیلد
    if lvl >= FEATURES["guild"]["lvl"] and not doc.get("guild") and int(doc.get("gold", 0) or 0) >= GUILD_COST:
        out.append(_sug("🛡 یه گیلد داشته باش",
                        f"با گیلد قلمرو، جنگ و خزانه باز میشه. «ساخت گیلد [نام]» ({GUILD_COST} GS) یا «پیوستن به گیلد [نام]» رو بنویس.",
                        btn("🛡 گیلد من", f"m:guild:{uid}", "blue")))

    # ۶) کوله‌پشتی پر
    inv = doc.get("inventory") or []
    if len(inv) >= 5 and lvl >= FEATURES["exch"]["lvl"]:
        out.append(_sug(f"🎒 کوله‌ت {len(inv)} تا آیتم داره",
                        "جاش محدوده (۱۵ تا). تجهیز کن، تو بازار روح بفروش یا تو کوره ارتقا بده.",
                        btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "green")))

    # ۷) میدان
    if lvl >= FEATURES["arena"]["lvl"]:
        out.append(_sug("🏟 برو سراغِ میدان نبرد",
                        "تو گروه روی پیامِ یه نفر ریپلای کن و «حمله» (یا برای تمرینِ بی‌ریسک «تمرین») بنویس. رتبه و جایزه‌ی هفتگی داره.",
                        btn("🏟 میدان نبرد", f"m:arena:{uid}", "red")))

    # ۸) همیشه یه راه: ماجراجویی
    out.append(_sug("🌍 برو ماجراجویی",
                    f"XP و GS و آیتم اینجا درمیاد. {xp_to_next(doc)} XP دیگه تا سطح {level_of(doc) + 1} (و بخش‌های جدید).",
                    btn("🌍 برو ماجراجویی", f"m:go:{uid}", "green")))
    return out


def hint_line(doc: dict) -> Optional[str]:
    """جمله‌ی کاربردیِ ایزدبانو برای پایینِ منو (همزمان): یه سرنخ به‌جای جمله‌ی تصادفی. None = جمله‌ی معمولی."""
    r = int(doc.get("survival_rate", 100) or 0)
    if r < 30:
        t = random.choice([
            f"بقات {r}٪ه، احمق. یه کاریش بکن؛ دکمه‌ی 🎯 رو بزن.",
            f"با {r}٪ بقا راه می‌ری؟ جسارتت رو تحسین می‌کنم؛ جنازه‌ت رو کمتر.",
        ])
    elif tut_active(doc):
        t = random.choice([
            "هنوز تور شروعت تموم نشده. دکمه‌ی 🎯 رو بزن تا بگم چیکار کنی.",
            "گم شدی؟ طبیعیه. 🎯 رو بزن تا راهنماییت کنم، قبل از اینکه پشیمون بشم.",
        ])
    elif wheel_ready(doc) and r < 55:
        t = "گردونه‌ی امروز آماده‌ست. بقات هم که… خب، بچرخونش."
    else:
        q = doc.get("quests") or {}
        n = sum(1 for i in q.get("daily", []) if not i.get("done")) if q.get("day") == day_key() else 0
        if n:
            t = f"{n} تا ماموریتِ امروز مونده. هر ماموریتِ نیمه‌کاره توهین به منه."
        else:
            return None
    return f"💅 <i>«{t}»</i>"


# ───────────────────────────── 🖼 پنل‌ها ─────────────────────────────
async def do_next_step(m, doc: Optional[dict] = None):
    uid = m.from_user.id
    doc = doc or await store.get(uid)
    sug = await suggestions(doc)
    top, rest = sug[0], sug[1:3]
    lines = [f"<b>{top['title']}</b>", top["why"]]
    if rest:
        lines += ["┈┈┈┈┈┈┈┈┈┈", "🔀 یا:"] + [f"• {s['title']}" for s in rest]
    rows = [[top["btn"]]] if top["btn"] else []
    rows += [[s["btn"]] for s in rest if s["btn"]]
    if tut_active(doc):
        rows.append([btn("⏭ رد کردنِ تور", f"m:tskip:{uid}", "red")])
    rows.append(back_kb(uid))
    await show(m, panel("green", "🎯", "قدم بعدیت", lines, hint_line(doc)), kb(*rows))


async def do_skip_tour(uid: int):
    await store.users.update_one({"user_id": uid, "tut": {"$type": "object"}}, {"$set": {"tut.skip": True}})


def cat_panel(uid: int, doc: dict, ckey: str):
    icon, name, color = CATS[ckey]
    keys = [k for k, f in FEATURES.items() if f["cat"] == ckey]
    lines = []
    for k in keys:
        f = FEATURES[k]
        if is_open(doc, k):
            lines.append(f"{f['icon']} <b>{f['name']}</b> — {f['desc']}")
        else:
            lines.append(f"🔒 <b>{f['name']}</b> (از سطح {f['lvl']}) — {f['desc']}")
    foot = f"⭐ الان سطح {level_of(doc)} هستی؛ {xp_to_next(doc)} XP تا سطحِ بعد. XP رو از ماجراجویی و ماموریت می‌گیری."
    btns = [feat_button(uid, doc, k) for k in keys]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] + [back_kb(uid)]
    return panel(color, icon, name, lines, foot), kb(*rows)
