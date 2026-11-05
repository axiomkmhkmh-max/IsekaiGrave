"""کلاینت OpenRouter (API سازگار با OpenAI): صف، محدودیت نرخ، کش، retry، backoff، circuit-breaker و fallback.

قانون: هر تابعِ اینجا اگه AI خاموش/در دسترس‌نبودن/محدود بود None برمی‌گردونه و صدازننده باید fallbackِ پایتونی داشته باشه.
خروجیِ AI فقط «متن/داده» ـه؛ هیچ‌وقت کد اجرا نمی‌شه و هیچ‌جا مستقیم به دیتابیس نمی‌ره (همه‌چیز قبل از استفاده اعتبارسنجی میشه).
"""

import asyncio
import hashlib
import json
import re
import time
from collections import deque
from typing import Optional

from config import (
    AI_CACHE_TTL, AI_ENABLED, AI_GLOBAL_PER_MIN, AI_MAX_CONCURRENT, AI_PLAYER_PER_MIN, AI_QUEUE_MAX,
    AI_RETRIES, AI_TIMEOUT, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL, log,
)

stats = {"ok": 0, "fail": 0, "cache_hit": 0, "rate_limited": 0, "queue_full": 0, "http_429": 0, "http_401": 0, "http_other": 0}

_session = None
_queue: Optional[asyncio.Queue] = None
_workers: list = []
_global_hits: deque = deque()
_player_hits: dict = {}
_cache: dict = {}
_blocked_until = 0.0          # بعد از 429/خطای احراز هویت/قطعیِ پشت‌سرهم، تا این زمان هیچ درخواستی نمی‌ره
_fail_streak = 0              # تعداد شکست‌های پشت‌سرهم (با اولین موفقیت صفر میشه)
_merge_system = False         # بعضی مدل‌های رایگان نقشِ system رو قبول نمی‌کنن → ادغام با پیامِ user
_warned: set = set()
_COOLDOWNS = (30, 120, 600, 1800, 3600)   # ثانیه؛ پلکانیِ circuit-breaker (سهمیه‌ی رایگان تموم شد → کمتر می‌کوبیم)

_KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_\-]+|Bearer\s+\S+", re.I)


def _redact(text) -> str:
    """هر چیزی که شبیه کلید باشه قبل از لاگ حذف میشه (کلید واقعی + الگوی sk-or-… + هدرِ Bearer)."""
    t = str(text)
    if OPENROUTER_API_KEY:
        t = t.replace(OPENROUTER_API_KEY, "***")
    return _KEY_RE.sub("***", t)


def _warn_once(key: str, msg: str, *args):
    if key in _warned:
        return
    _warned.add(key)
    log.warning(_redact(msg % args if args else msg))


def config_problem() -> Optional[str]:
    """None = تنظیمات کامله (یا AI عمداً خاموشه). وگرنه متنِ راهنما برای ادمین/لاگ."""
    if not AI_ENABLED:
        return None
    if not OPENROUTER_API_KEY:
        return "OPENROUTER_API_KEY تنظیم نشده؛ AI خاموش است و دنیا با پایتون/پاسخ‌های جایگزین کار می‌کند."
    if not OPENROUTER_MODEL:
        return ("OPENROUTER_MODEL تنظیم نشده؛ AI خاموش است. شناسه‌ی دقیقِ یک مدل رایگان را از openrouter.ai/models "
                "(فیلتر Free؛ شناسه معمولاً با «:free» تموم میشه) کپی کن و تو Variables بذار. مدلی حدس زده نمیشه.")
    if "/" not in OPENROUTER_MODEL or any(ch.isspace() for ch in OPENROUTER_MODEL):
        return ("OPENROUTER_MODEL نامعتبره (باید شبیه vendor/model-name باشه، بدون فاصله)؛ شناسه‌ی دقیق رو از openrouter.ai/models کپی کن. "
                "AI خاموش است.")
    return None


def log_status():
    """یک‌بار موقع استارت صدا زده میشه؛ هیچ کلیدی چاپ نمیشه."""
    if not AI_ENABLED:
        log.info("AI خاموشه (AI_ENABLED=0): دنیا فقط با پایتون کار می‌کنه.")
        return
    prob = config_problem()
    if prob:
        _warn_once("config", prob)
    else:
        log.info("AI فعال: OpenRouter، مدل=%s", OPENROUTER_MODEL)


def ai_available() -> bool:
    if not AI_ENABLED:
        return False
    prob = config_problem()
    if prob:
        _warn_once("config", prob)
        return False
    return True


def _strip_think(s: str) -> str:
    """بعضی مدل‌های رایگان بلوکِ <think>…</think> تو جواب می‌ذارن؛ حذفش می‌کنیم (بلوکِ نیمه‌کاره = خالی)."""
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S | re.I)
    s = re.sub(r"<think>.*", "", s, flags=re.S | re.I)
    return s.strip()


def _merge_system_msgs(messages: list) -> list:
    sysm = "\n".join(str(m.get("content", "")) for m in messages if m.get("role") == "system")
    rest = [dict(m) for m in messages if m.get("role") != "system"]
    if sysm:
        if rest and rest[0].get("role") == "user":
            rest[0]["content"] = f"{sysm}\n\n{rest[0].get('content', '')}"
        else:
            rest.insert(0, {"role": "user", "content": sysm})
    return rest


def clean_text(s, n: int = 200) -> str:
    """متنِ خروجیِ AI رو امن می‌کنه: بدون کنترل‌کاراکتر/تگ، تک‌خطی و کوتاه."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(s or ""))
    s = s.replace("<", "").replace(">", "").replace("`", "")
    s = re.sub(r"\s+", " ", s).strip().strip("«»\"' ")
    return s[:n]


def _allow(uid: Optional[int]) -> bool:
    now = time.time()
    while _global_hits and now - _global_hits[0] > 60:
        _global_hits.popleft()
    if len(_global_hits) >= AI_GLOBAL_PER_MIN:
        return False
    if uid is not None:
        if len(_player_hits) > 3000:
            _player_hits.clear()
        dq = _player_hits.setdefault(uid, deque())
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= AI_PLAYER_PER_MIN:
            return False
        dq.append(now)
    _global_hits.append(now)
    return True


async def _get_session():
    global _session
    if _session is None or _session.closed:
        import aiohttp
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=AI_TIMEOUT))
    return _session


def _note_failure(rate_limited: bool = False):
    """شکستِ یک درخواستِ کامل (بعد از retryها). 429 فوراً cooldown می‌ده؛ بقیه بعد از ۳ شکستِ پشت‌سرهم."""
    global _fail_streak, _blocked_until
    _fail_streak += 1
    n = _fail_streak if rate_limited else _fail_streak - 2
    if n >= 1:
        cd = _COOLDOWNS[min(n - 1, len(_COOLDOWNS) - 1)]
        _blocked_until = max(_blocked_until, time.time() + cd)
        log.warning("AI: %d شکستِ پشت‌سرهم%s → %d ثانیه استراحت (بازی با fallback ادامه داره)",
                    _fail_streak, " (محدودیت/سهمیه)" if rate_limited else "", cd)


def _hard_block(seconds: int, key: str, msg: str):
    global _blocked_until
    _blocked_until = max(_blocked_until, time.time() + seconds)
    _warn_once(key, msg)


async def _http_call(messages: list, max_tokens: int, temperature: float, info: Optional[dict] = None) -> Optional[str]:
    global _blocked_until, _fail_streak, _merge_system
    import aiohttp
    url = f"{OPENROUTER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    merged = _merge_system
    rate_limited = False
    info = info if info is not None else {}
    for attempt in range(AI_RETRIES + 1):
        if time.time() < _blocked_until:
            info.setdefault("reason", "cooldown")
            return None
        body = {"model": OPENROUTER_MODEL, "messages": _merge_system_msgs(messages) if merged else messages,
                "max_tokens": max_tokens, "temperature": temperature}
        try:
            sess = await _get_session()
            async with sess.post(url, json=body, headers=headers) as r:
                status = r.status
                retry_after = r.headers.get("Retry-After")
                data, text = None, ""
                if status == 200:
                    data = await r.json(content_type=None)
                    err = data.get("error") if isinstance(data, dict) else None
                    if err:                      # OpenRouter گاهی با 200 هم خطا برمی‌گردونه
                        code = err.get("code") if isinstance(err, dict) else None
                        status = int(code) if str(code).isdigit() else 502
                        text = str(err)
                else:
                    text = await r.text()
            if status == 200:
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") if isinstance(data, dict) else None
                content = _strip_think(content) if isinstance(content, str) else ""
                if not content:
                    stats["http_other"] += 1
                    info["reason"] = "empty_response"
                    return None                  # جوابِ خالی (مثلاً مدلِ reasoning با max_tokens کم) → fallback
                _fail_streak = 0
                if merged:
                    _merge_system = True
                return content
            info["reason"] = f"http_{status}"
            if status == 429:
                stats["http_429"] += 1
                rate_limited = True
                try:
                    delay = float(retry_after) if retry_after else 2.0 * (attempt + 1)
                except ValueError:
                    delay = 2.0 * (attempt + 1)
                delay = min(max(delay, 1.0), 10.0)
                _blocked_until = time.time() + delay
                await asyncio.sleep(delay)
                continue
            if status in (401, 403):
                stats["http_401"] += 1
                _hard_block(900, "auth", "AI HTTP %d: کلید OpenRouter نامعتبر/غیرفعاله؛ OPENROUTER_API_KEY رو چک کن (۱۵ دقیقه درخواستی نمی‌ره)." % status)
                return None
            if status == 402:
                stats["http_other"] += 1
                _hard_block(900, "credits", "AI HTTP 402: اعتبار/سهمیه‌ی OpenRouter کافی نیست؛ مدلِ رایگان (:free) انتخاب کن یا بعداً تلاش کن.")
                return None
            if status == 404:
                stats["http_other"] += 1
                _hard_block(900, "model", "AI HTTP 404: مدل «%s» پیدا نشد یا فعلاً endpoint نداره؛ OPENROUTER_MODEL رو با شناسه‌ی دقیقِ openrouter.ai/models عوض کن." % OPENROUTER_MODEL)
                return None
            if status == 400 and not merged and any(m.get("role") == "system" for m in messages):
                merged = True                    # احتمالاً مدل نقشِ system رو نمی‌پذیره → یک‌بار با ادغام تلاش کن
                continue
            if status >= 500 or status == 408:
                await asyncio.sleep(1.5 ** attempt)
                continue
            stats["http_other"] += 1
            log.warning("AI HTTP %s: %s", status, _redact(text)[:200])
            return None
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            info["reason"] = "timeout" if isinstance(e, asyncio.TimeoutError) else f"client_error:{type(e).__name__}"
            await asyncio.sleep(1.0 + attempt)
        except Exception as e:
            info["reason"] = f"crash:{type(e).__name__}"
            log.error("AI call crashed: %s: %s", type(e).__name__, _redact(e)[:200])
            return None
    _note_failure(rate_limited)
    return None


async def _worker():
    while True:
        fut, messages, max_tokens, temperature, info = await _queue.get()
        try:
            if fut.done():          # صدازننده منتظر نموند
                continue
            res = await _http_call(messages, max_tokens, temperature, info)
            if not fut.done():
                fut.set_result(res)
        except Exception:
            log.exception("AI worker error")
            if not fut.done():
                fut.set_result(None)
        finally:
            _queue.task_done()


def _ensure_workers():
    global _queue
    if _queue is None:
        _queue = asyncio.Queue(maxsize=AI_QUEUE_MAX)
    alive = [w for w in _workers if not w.done()]
    _workers[:] = alive
    while len(_workers) < max(1, AI_MAX_CONCURRENT):
        _workers.append(asyncio.create_task(_worker()))


async def ask(messages: list, *, uid: Optional[int] = None, max_tokens: int = 200, temperature: float = 0.8,
              cache_key: Optional[str] = None, wait: Optional[float] = None, tag: str = "generic",
              info: Optional[dict] = None) -> Optional[str]:
    """یک درخواست به OpenRouter از طریق صف. None = AI در دسترس/مجاز نیست (fallback بزن).

    tag فقط برچسبِ لاگه (مثلاً npc_chat:guard)؛ info (اختیاری) دیکتی‌ـه که دلیلِ شکست رو تو کلیدِ "reason" می‌گیره.
    لاگ‌ها هرگز متنِ پیام‌ها/کلید رو نمی‌نویسن؛ فقط tag، مدل، وضعیتِ HTTP/نوعِ خطا.
    """
    info = info if info is not None else {}

    def _fail(reason: str):
        info.setdefault("reason", reason)
        stats["fail"] += 1
        log.warning("OpenRouter request failed tag=%s reason=%s", _redact(tag), _redact(info["reason"]))
        return None

    if not ai_available():
        info["reason"] = "disabled" if not AI_ENABLED else "not_configured"
        log.info("OpenRouter request skipped tag=%s reason=%s", _redact(tag), info["reason"])
        return None
    ck = None
    if cache_key:
        ck = hashlib.sha1(f"{OPENROUTER_MODEL}|{cache_key}".encode()).hexdigest()
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < AI_CACHE_TTL:
            stats["cache_hit"] += 1
            info["cached"] = True
            log.info("AI cache hit tag=%s", _redact(tag))
            return hit[1]
    if time.time() < _blocked_until or not _allow(uid):
        stats["rate_limited"] += 1
        info["reason"] = "cooldown_or_rate_limited"
        log.warning("OpenRouter request failed tag=%s reason=%s", _redact(tag), info["reason"])
        return None
    _ensure_workers()
    fut = asyncio.get_running_loop().create_future()
    log.info("OpenRouter request started tag=%s model=%s", _redact(tag), OPENROUTER_MODEL)
    try:
        _queue.put_nowait((fut, messages, max_tokens, temperature, info))
    except asyncio.QueueFull:
        stats["queue_full"] += 1
        info["reason"] = "queue_full"
        log.warning("OpenRouter request failed tag=%s reason=queue_full", _redact(tag))
        return None
    try:
        res = await asyncio.wait_for(fut, timeout=wait or (AI_TIMEOUT * (AI_RETRIES + 1) + 5))
    except asyncio.TimeoutError:
        fut.cancel()
        return _fail("wait_timeout")
    if not res:
        return _fail("no_result")
    stats["ok"] += 1
    res = res.strip()
    log.info("OpenRouter request succeeded tag=%s chars=%d", _redact(tag), len(res))
    if ck:
        if len(_cache) > 500:
            _cache.clear()
        _cache[ck] = (time.time(), res)
    return res


def parse_json(text: Optional[str]) -> Optional[dict]:
    """اولین آبجکتِ JSON داخلِ متن رو درمیاره (با/بدون ```). نامعتبر = None."""
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        d = json.loads(t[a:b + 1])
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) else None


async def ask_json(messages: list, **kw) -> Optional[dict]:
    return parse_json(await ask(messages, **kw))


async def shutdown():
    for w in _workers:
        w.cancel()
    _workers.clear()
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
