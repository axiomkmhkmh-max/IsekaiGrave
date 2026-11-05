"""کلاینت Cerebras (API سازگار با OpenAI): صف، محدودیت نرخ، کش، retry، backoff و fallback.

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
    AI_RETRIES, AI_TIMEOUT, CEREBRAS_API_KEY, CEREBRAS_BASE_URL, CEREBRAS_MODEL, log,
)

stats = {"ok": 0, "fail": 0, "cache_hit": 0, "rate_limited": 0, "queue_full": 0, "http_429": 0}

_session = None
_queue: Optional[asyncio.Queue] = None
_workers: list = []
_global_hits: deque = deque()
_player_hits: dict = {}
_cache: dict = {}
_blocked_until = 0.0          # بعد از 429، تا این زمان هیچ درخواستی نمی‌ره


def ai_available() -> bool:
    return bool(AI_ENABLED and CEREBRAS_API_KEY)


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


async def _http_call(messages: list, max_tokens: int, temperature: float) -> Optional[str]:
    global _blocked_until
    import aiohttp
    url = f"{CEREBRAS_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"}
    body = {"model": CEREBRAS_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    for attempt in range(AI_RETRIES + 1):
        if time.time() < _blocked_until:
            return None
        try:
            sess = await _get_session()
            async with sess.post(url, json=body, headers=headers) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    return (data.get("choices") or [{}])[0].get("message", {}).get("content")
                if r.status == 429:
                    stats["http_429"] += 1
                    try:
                        delay = float(r.headers.get("Retry-After", 2 * (attempt + 1)))
                    except ValueError:
                        delay = 2.0 * (attempt + 1)
                    delay = min(max(delay, 1.0), 10.0)
                    _blocked_until = time.time() + delay
                    await asyncio.sleep(delay)
                    continue
                if r.status >= 500:
                    await asyncio.sleep(1.5 ** attempt)
                    continue
                log.warning("AI HTTP %s: %s", r.status, (await r.text())[:200])
                return None
        except (asyncio.TimeoutError, aiohttp.ClientError):
            await asyncio.sleep(1.0 + attempt)
        except Exception:
            log.exception("AI call crashed")
            return None
    return None


async def _worker():
    while True:
        fut, messages, max_tokens, temperature = await _queue.get()
        try:
            if fut.done():          # صدازننده منتظر نموند
                continue
            res = await _http_call(messages, max_tokens, temperature)
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
              cache_key: Optional[str] = None, wait: Optional[float] = None) -> Optional[str]:
    """یک درخواست به Cerebras از طریق صف. None = AI در دسترس/مجاز نیست (fallback بزن)."""
    if not ai_available():
        return None
    ck = None
    if cache_key:
        ck = hashlib.sha1(f"{CEREBRAS_MODEL}|{cache_key}".encode()).hexdigest()
        hit = _cache.get(ck)
        if hit and time.time() - hit[0] < AI_CACHE_TTL:
            stats["cache_hit"] += 1
            return hit[1]
    if time.time() < _blocked_until or not _allow(uid):
        stats["rate_limited"] += 1
        return None
    _ensure_workers()
    fut = asyncio.get_running_loop().create_future()
    try:
        _queue.put_nowait((fut, messages, max_tokens, temperature))
    except asyncio.QueueFull:
        stats["queue_full"] += 1
        return None
    try:
        res = await asyncio.wait_for(fut, timeout=wait or (AI_TIMEOUT * (AI_RETRIES + 1) + 5))
    except asyncio.TimeoutError:
        fut.cancel()
        stats["fail"] += 1
        return None
    if not res:
        stats["fail"] += 1
        return None
    stats["ok"] += 1
    res = res.strip()
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
