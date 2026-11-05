"""ساخت متن‌های نمایشی: کارت بازیکن، صحنه‌ی مرگ، نوار بقا و ..."""

import random

from config import GS_DAILY_SOFT_CAP
from content import BIOMES, CLASSES, GODDESS_JUDGE, LAST_WORDS, SCENES
from rules import echo_charges, gear_bonus
from procgen import profile_lines
from ui import hp_bar, panel, xp_bar
from utils import day_key, esc


def rate_comment(r: int) -> str:
    if r < 8:
        return "بقات از آبکش هم سوراخ‌تره. نگران نباش؛ مرگت رو شخصاً تماشا می‌کنم. 🫥"
    if r < 16:
        return "با این آمار، اسلایم‌ها هم بهت می‌خندن. منم همین‌طور. 😏"
    if r < 26:
        return "نه عالی، نه افتضاح؛ یعنی کاملاً معمولی. حوصله‌م سر رفت."
    return "نسبتاً بالاست… یعنی فقط تا اولین اشتباهت. منتظرم. 😏"


def display(doc: dict, link: bool = False) -> str:
    name = esc(doc.get("first_name") or doc.get("username") or "ناشناس")
    if link:
        name = f'<a href="tg://user?id={doc["user_id"]}">{name}</a>'
    else:
        name = f"<b>{name}</b>"
    titles = doc.get("titles") or []
    if titles:
        return f"{name} ‹{esc(titles[-1])}›"
    return name


def stat_lines(doc: dict) -> list:
    r = doc.get("survival_rate", 0)
    out = [
        f"💚 بقا: <b>{r}٪</b> {hp_bar(r)}",
        f"⭐ سطح <b>{doc.get('level', 1)}</b> {xp_bar(int(doc.get('xp', 0)))}",
        f"🪙 GS: <b>{doc.get('gold', 0)}</b>",
    ]
    if doc.get("gs_day") == day_key() and int(doc.get("gs_earned", 0)) >= GS_DAILY_SOFT_CAP:
        out.append("⏳ سقفِ درآمدِ امروز رسید؛ تا فردا GS کمتری می‌گیری.")
    return out


def render_rebirth(doc: dict, new_titles: list) -> str:
    r = doc["survival_rate"]
    color = "red" if r < 16 else ("orange" if r < 26 else "purple")
    lines = [
        f"🧬 فرم جدید: {esc(doc['form'])}",
        f"🌍 دنیا: {esc(doc['world'])}",
        f"🎁 جهشِ این زندگی: {esc(doc['cheat_skill'])}",
        f"💀 نرخ بقا: <b>{r}٪</b> {hp_bar(r)}",
        f"☠️ تعداد مرگ: {doc['death_count']}",
        f"🔁 پژواکِ بازتولد: <b>{echo_charges(int(doc['death_count']))}</b> — هر مرگ تو نبرد بهت قدرت می‌ده، نه ضعف!",
        "🕯 هاله‌ی بازتولد: ۳ نبردِ بعدی با ۲ روحِ شارژشده شروع میشه.",
    ]
    if doc.get("_bond"):
        lines.append(f"💍 پیوندِ ایسکایی! {esc(doc['_bond'])} هم از این مرگ زخمی شد (−۶٪ بقا، −۱۰ GS).")
    s = panel(color, "🔮", "بازتولد موفق!", lines, rate_comment(r))
    if new_titles:
        s += "\n\n🏷 <b>لقب جدید ثبت شد:</b> " + "، ".join(f"«{esc(t)}»" for t in new_titles)
    return s


def render_scene(name_html: str) -> str:
    scene = random.choice(SCENES).replace("{n}", name_html)
    judge = random.choice(GODDESS_JUDGE).format(s=random.randint(1, 10))
    return f"{scene}\n\n🗣 آخرین حرف: {random.choice(LAST_WORDS)}\n<i>{judge}</i>"


def class_label(doc: dict) -> str:
    c = CLASSES.get(doc.get("cls") or "")
    return f"{c['icon']} {c['name']}" if c else "—"


def render_passport(doc: dict) -> str:
    inv = doc.get("inventory") or []
    titles = doc.get("titles") or []
    loc = BIOMES.get(doc.get("location") or "city", BIOMES["city"])
    lines = [
        f"👤 نام: {esc(doc.get('first_name'))}",
        f"🏷 لقب: {esc(titles[-1]) if titles else '—'}",
        f"🧬 فرم فعلی: {esc(doc.get('form'))}",
        f"🌍 دنیا: {esc(doc.get('world'))}",
        *(profile_lines(doc) or [f"🎁 چیت‌اسکیل: {esc(doc.get('cheat_skill'))}"]),
        f"📍 مکان: {loc['icon']} {loc['name']}",
        f"🛡 گیلد: {esc(doc.get('guild')) if doc.get('guild') else 'بی‌گیلد'}",
        f"🎭 کلاس: {class_label(doc)}",
        f"💍 پیوند: {esc(doc.get('spouse_name')) if doc.get('spouse') else 'مجرد'}",
        "┈┈┈┈┈┈┈┈┈┈",
        *stat_lines(doc),
        f"📌 وضعیت: {esc(doc.get('status'))}",
        "┈┈┈┈┈┈┈┈┈┈",
        f"☠️ مرگ‌ها: {doc.get('death_count', 0)} | 😈 نفرین‌ها: {doc.get('curses_received', 0)} | 🙏 دعاها: {doc.get('blessings_received', 0)}",
        f"⚔️ دوئل: {doc.get('wins', 0)} برد / {doc.get('losses', 0)} باخت",
        f"🔁 پژواک: {echo_charges(int(doc.get('death_count', 0)))} | 🗡 روح‌سلاح: " + (f"{esc((doc.get('equip') or {}).get('item'))} (+{gear_bonus((doc.get('equip') or {}).get('item'))})" if (doc.get('equip') or {}).get('item') else "—"),
    ]
    foot = f"🎒 کوله‌پشتی: {esc('، '.join(inv[-3:])) if inv else 'خالی'}"
    if not doc.get("death_count"):
        foot += "\n💅 <i>«هنوز یه بارم نمردی؟ حیف. بنویس «ریسپاون» تا یه مرگِ درست‌وحسابی بهت هدیه بدم.»</i>"
    return panel("purple", "🎴", "پاسپورت ایسکای", lines, foot)
