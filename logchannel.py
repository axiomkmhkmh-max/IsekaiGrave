"""📡 لاگ‌چنل تلگرام: هر کاری بازیکن‌ها می‌کنن (دستور، دکمه، نتیجه) میره تو کانال.

چطور کار می‌کنه:
  • handlers.py هر ورودی (متن / اسلش / دکمه) رو داخل `track(...)` می‌پیچه و یه «برچسب کار» می‌ده.
  • یه Request-Middleware روی Bot، جواب‌هایی که ربات تو همون لحظه می‌فرسته (نتیجه‌ی ماجراجویی، دوئل،
    مرگ، باس، محاصره، ازدواج، …) رو می‌گیره؛ پس لازم نیست تک‌تک فایل‌های بازی دست بخورن.
  • وقتی هندلر تموم شد، یه رکورد کوتاه ساخته میشه و تو صف می‌ره؛ یه ورکر پس‌زمینه رکوردها رو
    دسته‌ای (batch) و با رعایت محدودیت نرخ تلگرام تو کانال می‌فرسته. هیچ‌وقت بازی رو کند یا خراب نمی‌کنه.

ENV:
  LOG_CHANNEL  (اختیاری، پیش‌فرض: @isekailog)   خالی بذاری = لاگ خاموش
  LOG_NAV      (اختیاری، پیش‌فرض: 0)            1 = کلیک‌های ناوبری منو هم لاگ بشه

⚠️ ربات باید تو کانال «ادمین» باشه و اجازه‌ی Post Messages داشته باشه.
"""

import asyncio
import contextvars
import html
import re
from typing import Optional

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import LinkPreviewOptions

from config import LOG_CHANNEL, LOG_NAV, log
from intents import (
    ACCEPT_RE, ADMIN_BAN_RE, ADMIN_BROADCAST_RE, ADMIN_CLEAN_RE, ADMIN_HEALTH_RE, ADMIN_KILL_RE,
    ADMIN_PANEL_RE, ADMIN_STATS_RE, ADMIN_UNBAN_RE, BLESS_RE, BOARD_RE, BOSS_CALL_RE, BOSS_HIT_RE,
    BOSS_STATUS_RE, BUY_RE, CAFE_RE, CURSE_RE, DEATH_RE, DEFUSE_RE, DISTRESS_RE, DIVORCE_RE, DUEL_RE,
    EXEC_RE, DONATE_RE, EQUIP_RE, EXCH_RE, FORGE_RE, FORT_RE, GS_RE, SELL_RE, GUILD_CREATE_RE, GUILD_INVITE_RE, GUILD_JOIN_RE, GUILD_LEAVE_RE, GUILD_ME_RE,
    GUILD_WAR_RE, HELP_RE, INV_RE, INVITE_RE, MARKET_RE, MARRY_ACCEPT_RE, MARRY_DECLINE_RE,
    MARRY_RE, MENU_RE, NPC_RE, OPEN_RE, OPT_IN_RE, OPT_OUT_RE, PASSPORT_RE, QUEST_RE, REG_RE,
    REPLY_EXEC_RE, SIEGE_RE, STROLL_RE, TERR_RE, TITLES_RE, TRADE_RE, TRAVEL_RE, WHEEL_RE,
)
from utils import esc, ir_now

# ───────────────────────────── ثابت‌ها ─────────────────────────────
SEND_INTERVAL = 3.0       # حداقل فاصله‌ی دو ارسال به کانال (≈۲۰ پیام در دقیقه، سقف تلگرام)
BATCH_WINDOW = 2.0        # چند ثانیه صبر کن تا رکوردهای نزدیک به هم تو یه پیام جمع بشن
BATCH_MAX_CHARS = 3600
BATCH_MAX_ITEMS = 12
ENTRY_MAX_CHARS = 1400
REPLY_SNIPPET = 450
QUEUE_MAX = 5000

_queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=QUEUE_MAX)
_worker_task: Optional[asyncio.Task] = None
_bot: Optional[Bot] = None
_warned_send_fail = False
_dropped = 0

_TAG_RE = re.compile(r"<[^>]+>")


# ───────────────────────────── برچسب‌گذاری متن/دکمه ─────────────────────────────
# (regex, برچسب، حالت تطبیق، ناوبری؟) — ترتیب مهمه؛ اولین تطبیق برنده‌ست.
_TEXT_RULES = [
    (DISTRESS_RE, "🤍 پیام نگران‌کننده (پاسخ همدلانه)", "search", False),
    (REG_RE, "📜 درخواست ثبت‌نام", "full", False),
    (ADMIN_PANEL_RE, "🛠 پنل ادمین", "full", False),
    (ADMIN_STATS_RE, "🛠 ادمین: آمار", "full", False),
    (ADMIN_HEALTH_RE, "🛠 ادمین: سلامت سرور", "full", False),
    (ADMIN_CLEAN_RE, "🛠 ادمین: پاکسازی", "full", False),
    (ADMIN_BAN_RE, "🛠 ادمین: بن", "full", False),
    (ADMIN_UNBAN_RE, "🛠 ادمین: آنبن", "full", False),
    (ADMIN_KILL_RE, "🛠 ادمین: کشتن", "full", False),
    (ADMIN_BROADCAST_RE, "🛠 ادمین: پیام سراسری", "full", False),
    (EXEC_RE, "⚰️ دستور اعدام (@یوزرنیم)", "search", False),
    (REPLY_EXEC_RE, "⚰️ دستور اعدام (ریپلای)", "full", False),
    (EXCH_RE, "🪦 بازار روح", "full", False),
    (SELL_RE, "🏷 فروش در بازار روح", "full", False),
    (FORGE_RE, "🔥 کوره‌ی روح", "full", False),
    (EQUIP_RE, "⚔️ تجهیز آیتم", "full", False),
    (GS_RE, "🪙 موجودی GS", "full", False),
    (DONATE_RE, "💰 اهدا به خزانه‌ی گیلد", "full", False),
    (FORT_RE, "🏯 تقویت دژ", "full", False),
    (DUEL_RE, "⚔️ چالش دوئل", "full", False),
    (ACCEPT_RE, "🥊 قبول دوئل", "search", False),
    (CURSE_RE, "🩸 نفرین", "search", False),
    (BLESS_RE, "🙏 دعای خیر", "search", False),
    (BUY_RE, "💸 خرید از بازار سیاه", "full", False),
    (TRADE_RE, "🤝 قبول معامله‌ی مغازه‌دار", "search", False),
    (GUILD_CREATE_RE, "🛡 ساخت گیلد", "full", False),
    (GUILD_JOIN_RE, "🛡 پیوستن به گیلد", "full", False),
    (GUILD_WAR_RE, "⚔️ جنگ گیلدها", "full", False),
    (GUILD_ME_RE, "🏰 گیلد من", "full", False),
    (GUILD_LEAVE_RE, "🚪 ترک گیلد", "full", False),
    (GUILD_INVITE_RE, "📨 دعوت به گیلد", "full", False),
    (WHEEL_RE, "🎡 گردونه‌ی شانس", "search", False),
    (BOARD_RE, "🏆 لیدربرد", "search", False),
    (MENU_RE, "🌙 باز کردن منو", "full", True),
    (QUEST_RE, "📜 ماموریت‌ها", "full", False),
    (TERR_RE, "🗺 قلمروها", "full", False),
    (SIEGE_RE, "🏰 محاصره‌ی قلمرو", "full", False),
    (MARRY_RE, "💍 پیشنهاد ازدواج", "full", False),
    (MARRY_ACCEPT_RE, "💞 قبول ازدواج", "full", False),
    (MARRY_DECLINE_RE, "💔 رد ازدواج", "full", False),
    (DIVORCE_RE, "💔 طلاق", "full", False),
    (OPEN_RE, "🎁 باز کردن صندوق", "full", False),
    (DEFUSE_RE, "✂️ خنثی‌سازی بمب", "full", False),
    (BOSS_CALL_RE, "🐉 احضار باس", "full", False),
    (BOSS_HIT_RE, "🗡 حمله به باس", "full", False),
    (BOSS_STATUS_RE, "🐉 وضعیت باس", "full", False),
    (CAFE_RE, "☕ ورود به کافه", "search", False),
    (NPC_RE, "🗣 گفتگو با NPC", "search", False),
    (STROLL_RE, "🧭 گشت و ماجراجویی", "full", False),
    (MARKET_RE, "🕶 بازار سیاه", "search", False),
    (TITLES_RE, "🏷 لقب‌ها", "full", False),
    (INV_RE, "🎒 کوله‌پشتی", "full", False),
    (PASSPORT_RE, "🪪 کارت بازیکن", "full", False),
    (DEATH_RE, "☠️ مرگ داوطلبانه", "full", False),
    (INVITE_RE, "🔗 لینک دعوت", "full", False),
    (OPT_OUT_RE, "🛡 فعال‌کردن محافظت", "full", False),
    (OPT_IN_RE, "😈 برگشت به بازی", "full", False),
    (HELP_RE, "📖 راهنما", "full", True),
]

_M_LABELS = {
    "main": ("🌙 منوی اصلی", True), "go": ("🌍 لیست مکان‌ها", True), "npc": ("🧙 لیست NPCها", True),
    "help": ("📖 راهنما", True), "die": ("☠️ درخواست مرگ داوطلبانه", True),
    "pass": ("🪪 کارت بازیکن", False), "inv": ("🎒 کوله‌پشتی", False), "wheel": ("🎡 گردونه‌ی شانس", False),
    "guild": ("🏰 گیلد من", False), "war": ("⚔️ جنگ گیلدها", False), "board": ("🏆 لیدربرد", False),
    "market": ("🕶 بازار سیاه", False), "quest": ("📜 ماموریت‌ها", False), "terr": ("🗺 قلمروها", False),
    "boss": ("🐉 وضعیت باس", False), "marry": ("💍 پیوند", False), "die2": ("☠️ مرگ داوطلبانه (تأیید)", False),
    "divorce": ("💔 طلاق", False), "exch": ("🪦 بازار روح", False), "forge": ("🔥 کوره‌ی روح", False), "gs": ("🪙 موجودی GS", False),
}


def label_text(c: str) -> Optional[tuple]:
    """متن پیام (نرمال‌شده) → (برچسب، ناوبری؟) یا None اگه دستور بازی نیست."""
    for rx, label, mode, nav in _TEXT_RULES:
        if (rx.fullmatch(c) if mode == "full" else rx.search(c)):
            return label, nav
    if TRAVEL_RE.fullmatch(c):
        from content import BIOMES  # import تنبل
        if any(re.search(b["kw"], c) for b in BIOMES.values()):
            return "🧭 سفر", False
    return None


def label_cb(data: str) -> tuple:
    """callback_data → (برچسب، ناوبری؟)."""
    from content import BIOMES, NPCS, TERRITORIES  # import تنبل
    parts = (data or "").split(":")
    kind, act = parts[0], (parts[1] if len(parts) > 1 else "")
    if kind == "x" and act in BIOMES:
        return f"🧭 سفر به {BIOMES[act]['icon']} {BIOMES[act]['name']}", False
    if kind == "n" and act in NPCS:
        return f"🗣 گفتگو با {NPCS[act]['icon']} {NPCS[act]['name']}", False
    if kind == "sg" and act in TERRITORIES:
        return f"🏰 محاصره‌ی {TERRITORIES[act][1]} {TERRITORIES[act][0]}", False
    if kind == "m":
        return _M_LABELS.get(act, (f"🔘 منو ({act})", True))
    if kind == "reg":
        return {"go": ("📜 شروع ثبت‌نام", False), "sign": ("🩸 امضای قرارداد", False),
                "cls": ("🎭 انتخاب کلاس", False), "boon": ("🎁 انتخاب هدیه‌ی قرارداد", False),
                "run": ("🏃 تلاش برای فرار از ثبت‌نام", False)}.get(act, (f"📜 ثبت‌نام ({act})", False))
    if kind == "raid":
        return {"hit": ("🗡 حمله به باس", False), "call": ("🐉 احضار باس", False)}.get(act, ("🐉 وضعیت باس", False))
    if kind == "mar":
        return ("💞 قبول ازدواج" if act == "yes" else "💔 رد ازدواج"), False
    simple = {"wn": "🗣 NPCِ زنده", "ch": "🌟 چیت‌اسکیل", "tr": "🛒 قبول معامله", "duelacc": "🥊 قبول دوئل", "sk": "🏟 میدان نبرد", "buy": "💸 خرید از بازار سیاه", "loot": "🎁 برداشتن صندوق/بمب", "adm": "🛠 ادمین"}
    return simple.get(kind, f"🔘 {kind}"), False


# ───────────────────────────── ردیابی یک کنش ─────────────────────────────
_cur: "contextvars.ContextVar[Optional[Track]]" = contextvars.ContextVar("log_track", default=None)


class Track:
    """context manager: جواب‌های ربات رو تو طول یه کنش جمع می‌کنه و آخرش یه رکورد لاگ می‌سازه."""

    def __init__(self, user, chat, label: Optional[str], detail: Optional[str] = None,
                 nav: bool = False, capture_edits: bool = False):
        self.user, self.chat, self.label, self.detail = user, chat, label, detail
        self.nav, self.capture_edits = nav, capture_edits
        self.replies: list = []
        self.error = False
        self.active = True
        self._token = None

    async def __aenter__(self):
        self._token = _cur.set(self)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.active = False          # تسک‌های پس‌زمینه‌ای که از این کنش spawn شدن دیگه ثبت نمی‌شن
        _cur.reset(self._token)
        if exc_type is not None:
            self.error = True
        try:
            self._emit()
        except Exception:
            log.debug("log emit failed", exc_info=True)
        return False

    def _emit(self):
        if not LOG_CHANNEL or not self.label:
            return
        if self.nav and not LOG_NAV and not self.error:
            return
        u, ch = self.user, self.chat
        who = f"<b>{esc(getattr(u, 'full_name', '؟'))}</b>"
        if getattr(u, "username", None):
            who += f" @{esc(u.username)}"
        who += f" <code>{u.id}</code>"
        ctype = getattr(getattr(ch, "type", None), "value", getattr(ch, "type", ""))
        where = f"گروه «{esc(ch.title)}»" if ctype in ("group", "supergroup") and getattr(ch, "title", None) else "پیوی"
        lines = [f"{self.label}", f"👤 {who}", f"📍 {where} · 🕐 {ir_now().strftime('%H:%M:%S')}"]
        if self.detail:
            lines.append(f"💬 <i>«{esc(self.detail[:100])}»</i>")
        if self.error:
            lines.append("❗️ <b>خطای داخلی تو این کنش رخ داد</b>")
        if self.replies:
            snip = _plain(self.replies[0])
            if len(self.replies) > 1:
                snip += f"\n… (+{len(self.replies) - 1} پیام دیگه)"
            lines.append(f"<blockquote expandable>{esc(snip)}</blockquote>")
        enqueue("\n".join(lines)[:ENTRY_MAX_CHARS])


def track(user, chat, label: Optional[str], detail: Optional[str] = None, nav: bool = False,
          capture_edits: bool = False) -> Track:
    return Track(user, chat, label, detail, nav, capture_edits)


def mark_error():
    t = _cur.get()
    if t:
        t.error = True


def _plain(text: str) -> str:
    t = html.unescape(_TAG_RE.sub("", text or ""))
    t = re.sub(r"\n{2,}", "\n", t).strip()
    return t[:REPLY_SNIPPET] + ("…" if len(t) > REPLY_SNIPPET else "")


# ───────────────────────────── Middleware (گرفتن جواب‌های ربات) ─────────────────────────────
class LogRequestMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        try:
            t = _cur.get()
            if t and t.active:
                if isinstance(method, SendMessage) and method.text and str(method.chat_id) != str(LOG_CHANNEL):
                    t.replies.append(method.text)
                elif isinstance(method, EditMessageText) and t.capture_edits and method.text:
                    t.replies.append(method.text)
        except Exception:
            pass
        return result


# ───────────────────────────── صف و ورکر ─────────────────────────────
def enqueue(entry: str):
    """یه رکورد (HTML) رو تو صف بذار. هیچ‌وقت بلاک یا خطا نمیده."""
    global _dropped
    if not LOG_CHANNEL or _bot is None:
        return
    try:
        _queue.put_nowait(entry)
    except asyncio.QueueFull:
        _dropped += 1


def event(text_html: str):
    """رکورد دستی (مثلاً بازیکن جدید، ورود به گروه)."""
    enqueue(f"{text_html}\n🕐 {ir_now().strftime('%H:%M:%S')}"[:ENTRY_MAX_CHARS])


async def _send(text: str):
    global _warned_send_fail
    for _ in range(4):
        try:
            await _bot.send_message(LOG_CHANNEL, text, disable_notification=True,
                                    link_preview_options=LinkPreviewOptions(is_disabled=True))
            _warned_send_fail = False
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramAPIError as e:
            if not _warned_send_fail:
                _warned_send_fail = True
                log.warning("ارسال به لاگ‌چنل %s ناموفق: %s — ربات رو تو کانال ادمین (با اجازه‌ی Post) کن.", LOG_CHANNEL, e)
            return
        except Exception:
            log.exception("log send failed")
            return


async def _worker():
    global _dropped
    loop = asyncio.get_running_loop()
    carry: Optional[str] = None
    while True:
        first = carry if carry is not None else await _queue.get()
        carry = None
        batch, size = [first], len(first)
        deadline = loop.time() + BATCH_WINDOW
        while len(batch) < BATCH_MAX_ITEMS:
            left = deadline - loop.time()
            if left <= 0:
                break
            try:
                item = await asyncio.wait_for(_queue.get(), timeout=left)
            except asyncio.TimeoutError:
                break
            if size + len(item) + 20 > BATCH_MAX_CHARS:
                carry = item
                break
            batch.append(item)
            size += len(item) + 20
        extra = ""
        if _dropped:
            extra = f"\n\n⚠️ {_dropped} رکورد به‌خاطر شلوغی حذف شد."
            _dropped = 0
        await _send("\n┈┈┈┈┈┈┈┈┈┈\n".join(batch) + extra)
        await asyncio.sleep(SEND_INTERVAL)


async def start(bot: Bot):
    """ورکر رو بالا میاره و یه پیام تست می‌فرسته (تا اگه ربات ادمین نیست، همون اول بفهمیم)."""
    global _bot, _worker_task
    if not LOG_CHANNEL:
        log.info("لاگ‌چنل خاموشه (LOG_CHANNEL خالیه).")
        return
    _bot = bot
    bot.session.middleware(LogRequestMiddleware())
    _worker_task = asyncio.create_task(_worker())
    event("🟢 <b>ربات آنلاین شد</b> — لاگ‌چنل فعاله.")


async def stop():
    """قبل از خاموشی، چیزی که تو صفه رو بفرست."""
    if _worker_task is None:
        return
    try:
        event("🔴 <b>ربات خاموش شد.</b>")
        for _ in range(20):
            if _queue.empty():
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(BATCH_WINDOW + 0.5)
    finally:
        _worker_task.cancel()
