"""سیستم ثبت‌نام: انتخاب کلاس و سوگند، و پیام دعوت به ثبت‌نام."""

import random
import time
from typing import Optional

from aiogram.types import InlineKeyboardMarkup, User

from config import REG_PROMPT_COOLDOWN, runtime
from content import BOONS, CHEATS, CLASSES, FORMS, GODDESS_NAME, GODDESS_TITLE, WORLDS
from database import store
from players import grant, status_for
from render import stat_lines
from ui import btn, kb, panel
from utils import esc, is_group, utcnow


_last_reg_prompt: dict = {}


# ───────────────────────────── 📜 سیستم ثبت‌نام ─────────────────────────────
def reg_text_intro(name: str) -> str:
    return panel("purple", "📜", "قرارداد روحِ ایسکای", [
        f"{GODDESS_NAME}، <i>{GODDESS_TITLE}</i>، به <b>{esc(name)}</b> خیره شد…",
        "💅 «یه روحِ تازه. اسمت تو لیست اشک‌ریزان نیست؛ یعنی هیچ‌کس برات گریه نمی‌کنه. عالی. قراردادمو امضا کن، وگرنه از دروازه‌م رد نمیشی.»",
        "┈┈┈┈┈┈┈┈┈┈",
        "برای شروع بازی فقط یه کلیک داری 🙂:",
        "🩸 امضای قرارداد",
        "🎲 کلاس و چیت‌اسکیلِ رندومِ مخصوصِ خودت همون لحظه ساخته میشه (و برای همیشه مالِ توئه).",
        "🕯 هدیه‌ی شروع رو بعدش برمی‌داری؛ مستقیم میری تو بازی!",
        "┈┈┈┈┈┈┈┈┈┈",
        "⚠️ <i>ریزنوشت: روحِ تو از این لحظه ملکِ منه. بازگشت پول و فرار ممنوع.</i>",
    ])


def reg_kb_intro(uid: int) -> InlineKeyboardMarkup:
    return kb(
        [btn("🩸 امضا می‌کنم", f"reg:sign:{uid}", "green")],
        [btn("🏃 فرار از ایزدبانو", f"reg:run:{uid}", "red")],
    )


def reg_text_class() -> str:
    lines = ["هر کلاس یه امتیاز ویژه داره؛ یکی رو انتخاب کن 👇", *[f"{c['icon']} <b>{c['name']}</b> — {c['desc']}" for c in CLASSES.values()]]
    return panel("blue", "🎭", "آخرین مرحله: کلاس‌ت رو انتخاب کن", lines,
                 "💅 <i>«زیاد فکر نکن؛ هر کدوم رو برداری، آخرش مال منی.»</i>")


def reg_kb_class(uid: int) -> InlineKeyboardMarkup:
    ks = list(CLASSES.items())
    mk = lambda k, c: btn(f"{c['icon']} {c['name']}", f"reg:cls:{k}:{uid}", c["color"])
    return kb([mk(*ks[0]), mk(*ks[1])], [mk(*ks[2]), mk(*ks[3])])


def reg_text_boon(cls_key: str) -> str:
    c = CLASSES[cls_key]
    lines = [f"{b['icon']} <b>{b['name']}</b> — {b['desc']}" for b in BOONS.values()]
    return panel("red", "🕯", "مرحله‌ی ۳: سوگند به ایزدبانو", [
        f"💅 «{c['quip']}»",
        "┈┈┈┈┈┈┈┈┈┈",
        "هدیه‌ی شروعت رو انتخاب کن (فقط یکی):",
        *lines,
    ])


def reg_kb_boon(cls_key: str, uid: int) -> InlineKeyboardMarkup:
    return kb(*[[btn(f"{b['icon']} {b['name']}", f"reg:boon:{cls_key}:{k}:{uid}", b["color"])] for k, b in BOONS.items()])


async def _give_boon(uid: int, boon_key: str):
    if boon_key == "gold":
        await grant(uid, gold=150)
    elif boon_key == "xp":
        await grant(uid, xp=100)
    else:
        item = f"🔗 {random.choice(['تاجِ فراموش‌شده‌ی آخرالزمان', 'شمشیرِ بی‌نامِ دروازه‌ی آخر', 'حلقه‌ی پایانِ همه‌چیز'])} ‹پیمان‌دار›"   # 🔗 روح‌پیوند: قابل تجهیز، غیرقابل فروش
        await grant(uid, item=item)


async def claim_gift(user: User, boon_key: str) -> Optional[dict]:
    """🕯 هدیه‌ی شروع (بعد از ثبت‌نام): اتمیک، فقط یک‌بار. اگه قبلاً برداشته باشه None."""
    res = await store.users.update_one({"user_id": user.id, "registered": True, "pact": None},
                                       {"$set": {"pact": boon_key}})
    if res.modified_count == 0:
        return None
    await _give_boon(user.id, boon_key)
    return await store.get(user.id)


async def finish_registration(user: User, cls_key: Optional[str] = None, boon_key: Optional[str] = None) -> Optional[dict]:
    """ثبت‌نام رو نهایی می‌کنه. اگه قبلاً ثبت‌نام شده باشه None برمی‌گردونه."""
    from worldnpc import enrich_flavor, new_profile_fields
    from worldsim import spawn
    form, _ = random.choice(FORMS)
    rate = random.randint(55, 90)
    prof = new_profile_fields(user.id, cls_key)       # 🎲 کلاس + چیت‌اسکیلِ رندومِ قطعی (seed ثابت = ریرول ممکن نیست)
    res = await store.users.update_one(
        {"user_id": user.id, "registered": {"$ne": True}},
        {"$set": {
            "registered": True, "cls": prof["cls"], "pact": boon_key, "registered_at": utcnow(),
            "gclass": prof["gclass"], "cheat": prof["cheat"], "cheat_uses": 0, "cheat_charges": 0,
            "form": form, "cheat_skill": prof["cheat_skill"], "world": random.choice(WORLDS),
            "survival_rate": rate, "status": status_for(rate), "first_name": user.full_name,
        }, "$push": {"titles": "روحِ ثبت‌شده‌ی ایزدبانو"}},
    )
    if res.modified_count == 0:
        return None
    if boon_key:
        await _give_boon(user.id, boon_key)
    spawn(enrich_flavor(user.id))                      # AI فقط متنِ توصیف رو (در پس‌زمینه) قشنگ می‌کنه
    return await store.get(user.id)


def reg_done_text(doc: dict, cls_key: str, boon_key: Optional[str] = None) -> str:
    from procgen import profile_lines
    c = CLASSES[doc.get("cls") or cls_key]
    b = BOONS.get(boon_key) if boon_key else None
    return panel("green", "🎉", "قرارداد امضا شد! به ایسکا خوش اومدی", [
        f"🪪 <b>{esc(doc.get('first_name'))}</b> — {c['icon']} {c['name']}",
        f"🕯 هدیه‌ی شروع: {b['icon']} {b['name']}" if b else "🎁 هدیه‌ی شروعت منتظره؛ از دکمه‌های پایین یکی رو بردار 👇",
        f"🧬 فرم اولیه: {esc(doc.get('form'))}",
        f"🌍 دنیا: {esc(doc.get('world'))}",
        *profile_lines(doc),
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
        "🏷 لقب: «روحِ ثبت‌شده‌ی ایزدبانو»",
    ], f"💅 <i>«{b['quip'] if b else 'هدیه‌ت رو بردار و گمشو تو ایسکا.'} حالا برو. هر کاری می‌خوای بکن؛ آخرش مال منی.»</i>\n💡 برای باز کردن منوی بازی بنویس «زندگی من».")


async def start_registration(m):
    """پیام مرحله‌ی ۱ رو برای کاربر می‌فرسته."""
    await m.reply(reg_text_intro(m.from_user.full_name), reply_markup=reg_kb_intro(m.from_user.id))


async def reg_prompt(m):
    """وقتی ثبت‌نام‌نشده می‌خواد بازی کنه."""
    uid = m.from_user.id
    now = time.time()
    if now - _last_reg_prompt.get(uid, 0) < REG_PROMPT_COOLDOWN:
        return
    _last_reg_prompt[uid] = now
    rows = [[btn("🩸 ثبت‌نام (همین‌جا)", f"reg:go:{uid}", "green")]]
    if is_group(m) and runtime.bot_username:
        rows.append([btn("📩 ثبت‌نام در پیوی", url=f"https://t.me/{runtime.bot_username}?start=reg")])
    await m.reply(panel("red", "🚪", "دروازه بسته‌ست", [
        f"💅 «{esc(m.from_user.first_name)}… بدون قرارداد، دروازه‌م به روت بسته‌ست. حتی مرده‌ها فرم پر می‌کنن؛ تو از مرده‌ها هم تنبل‌تری؟»",
        "برای شروع بازی اول ثبت‌نام کن؛ فقط یه کلیکه 🙂",
    ]), reply_markup=kb(*rows))


def reg_kb_done(uid: int, with_gift: bool) -> InlineKeyboardMarkup:
    rows = []
    if with_gift:
        rows += [[btn(f"{b['icon']} {b['name']} — {b['desc']}", f"reg:gift:{k}:{uid}", b["color"])] for k, b in BOONS.items()]
    rows += [[btn("🌍 اولین ماجراجویی", f"x:forest:{uid}", "green"), btn("🌙 منو", f"m:main:{uid}", "blue")]]
    return kb(*rows)
