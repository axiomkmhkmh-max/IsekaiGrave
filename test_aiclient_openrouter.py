"""تست‌های اتصال OpenRouter (بدون هیچ درخواستِ واقعی و بدون نیاز به aiohttp/pytest).

اجرا:  python -m unittest tests.test_aiclient_openrouter -v      (از ریشه‌ی پروژه)

- aiohttp با یک نسخه‌ی ساختگی جایگزین میشه؛ هیچ شبکه‌ای باز نمیشه.
- کلیدِ استفاده‌شده تو تست‌ها ساختگیه (FAKE) و به هیچ سرویسی وصل نیست.
"""

import asyncio
import importlib
import logging
import os
import random
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_KEY = "sk-or-v1-FAKEKEY-for-tests-0123456789"
FAKE_MODEL = "vendor/test-model:free"


# ───────────────────────────── aiohttp ساختگی ─────────────────────────────
class _ClientError(Exception):
    pass


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status, self._payload, self.headers = status, payload, headers or {}

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        return str(self._payload)


class _Ctx:
    def __init__(self, item):
        self.item = item

    async def __aenter__(self):
        if isinstance(self.item, BaseException):
            raise self.item
        return self.item

    async def __aexit__(self, *a):
        return False


class FakeSession:
    script: list = []          # آیتم‌ها به ترتیب مصرف میشن؛ آخری تکرار میشه
    calls: list = []
    closed = False

    def __init__(self, *a, **k):
        pass

    def post(self, url, json=None, headers=None):
        FakeSession.calls.append({"url": url, "json": json, "headers": headers})
        item = FakeSession.script[0] if len(FakeSession.script) == 1 else FakeSession.script.pop(0)
        return _Ctx(item)

    async def close(self):
        self.closed = True


fake_aiohttp = types.ModuleType("aiohttp")
fake_aiohttp.ClientSession = FakeSession
fake_aiohttp.ClientTimeout = lambda total=None: None
fake_aiohttp.ClientError = _ClientError


def ok(text="سلام ای مسافر"):
    return _Resp(200, {"choices": [{"message": {"content": text}}]})


MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def load_modules(env: dict):
    """config و aiclient رو با env مشخص دوباره لود می‌کنه (کلیدِ env فقط داخلِ تست)."""
    keys = ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "AI_ENABLED")
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(env)
    import config
    importlib.reload(config)
    import aiclient
    importlib.reload(aiclient)
    return config, aiclient


_loop = None


def run(coro):
    """همه‌ی awaitهای یک تست رو روی یک event loop اجرا می‌کنه (مثل پروداکشن؛ صف/workerها به یک loop بسته‌ان)."""
    return _loop.run_until_complete(coro)


class Base(unittest.TestCase):
    def setUp(self):
        global _loop
        _loop = asyncio.new_event_loop()
        self._patch = mock.patch.dict(sys.modules, {"aiohttp": fake_aiohttp})
        self._patch.start()
        FakeSession.script, FakeSession.calls = [ok()], []

    def tearDown(self):
        ai = sys.modules.get("aiclient")
        if ai is not None:
            _loop.run_until_complete(ai.shutdown())
        _loop.close()
        self._patch.stop()
        for k in ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL", "AI_ENABLED"):
            os.environ.pop(k, None)

    def good(self, **extra):
        env = {"OPENROUTER_API_KEY": FAKE_KEY, "OPENROUTER_MODEL": FAKE_MODEL}
        env.update(extra)
        cfg, ai = load_modules(env)
        ai.AI_RETRIES = 2
        return cfg, ai

    async def _nosleep(self, *a, **k):
        ai = sys.modules.get("aiclient")
        if ai is not None:
            ai._blocked_until = 0.0        # sleepِ واقعی زمان رو جلو می‌برد؛ اینجا شبیه‌سازیش می‌کنیم
        return None


# ───────────────────────────── ۱) تنظیمات / بدون کلید / مدل از env ─────────────────────────────
class TestConfig(Base):
    def test_no_key_is_safe(self):
        _, ai = load_modules({"OPENROUTER_MODEL": FAKE_MODEL})
        self.assertFalse(ai.ai_available())
        self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(FakeSession.calls, [])            # هیچ درخواستی نرفت
        self.assertIn("OPENROUTER_API_KEY", ai.config_problem())

    def test_missing_model_gives_clear_error_and_no_guess(self):
        cfg, ai = load_modules({"OPENROUTER_API_KEY": FAKE_KEY})
        self.assertEqual(cfg.OPENROUTER_MODEL, "")          # هیچ پیش‌فرضی حدس زده نمیشه
        self.assertFalse(ai.ai_available())
        self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(FakeSession.calls, [])
        prob = ai.config_problem()
        self.assertIn("OPENROUTER_MODEL", prob)
        self.assertIn("openrouter.ai/models", prob)
        with self.assertLogs("isekai-grave", level="WARNING") as cm:
            ai._warned.clear()
            ai.log_status()
        self.assertIn("OPENROUTER_MODEL", "\n".join(cm.output))

    def test_model_and_urls_come_from_env(self):
        cfg, ai = self.good(OPENROUTER_MODEL="acme/free-model:free", OPENROUTER_BASE_URL="https://example.test/api/v1/")
        self.assertEqual(cfg.OPENROUTER_MODEL, "acme/free-model:free")
        self.assertEqual(cfg.OPENROUTER_BASE_URL, "https://example.test/api/v1")     # اسلشِ آخر حذف میشه
        self.assertEqual(run(ai.ask(MSGS, max_tokens=77)), "سلام ای مسافر")
        call = FakeSession.calls[0]
        self.assertEqual(call["json"]["model"], "acme/free-model:free")
        self.assertEqual(call["json"]["max_tokens"], 77)
        self.assertEqual(call["url"], "https://example.test/api/v1/chat/completions")

    def test_default_base_url_is_openrouter(self):
        cfg, _ = self.good()
        self.assertEqual(cfg.OPENROUTER_BASE_URL, "https://openrouter.ai/api/v1")

    def test_ai_enabled_zero_turns_everything_off(self):
        _, ai = self.good(AI_ENABLED="0")
        self.assertFalse(ai.ai_available())
        self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(FakeSession.calls, [])

    def test_key_not_in_source_files(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fn in ("aiclient.py", "config.py", "main.py"):
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                src = f.read()
            self.assertNotRegex(src, r"sk-or-v1-[A-Za-z0-9]{10,}")
            self.assertNotIn("cerebras", src.lower())


# ───────────────────────────── ۲) موفقیت، هدر، کش ─────────────────────────────
class TestSuccess(Base):
    def test_success_headers_and_cache(self):
        _, ai = self.good()
        r1 = run(ai.ask(MSGS, cache_key="k1"))
        r2 = run(ai.ask(MSGS, cache_key="k1"))
        self.assertEqual((r1, r2), ("سلام ای مسافر",) * 2)
        self.assertEqual(len(FakeSession.calls), 1)          # دومی از کش
        self.assertEqual(ai.stats["cache_hit"], 1)
        self.assertEqual(FakeSession.calls[0]["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertNotIn(FAKE_KEY, str(FakeSession.calls[0]["json"]))   # کلید داخلِ body نیست

    def test_think_block_is_stripped_and_empty_is_none(self):
        _, ai = self.good()
        FakeSession.script = [ok("<think>فکر می‌کنم...</think>سلام مسافر")]
        self.assertEqual(run(ai.ask(MSGS)), "سلام مسافر")
        FakeSession.script = [ok("<think>نیمه‌کاره بدون پایان")]
        self.assertIsNone(run(ai.ask(MSGS)))
        FakeSession.script = [ok("")]
        self.assertIsNone(run(ai.ask(MSGS)))

    def test_parse_json_and_ask_json(self):
        _, ai = self.good()
        FakeSession.script = [ok('```json\n{"action": "plan", "text": "x"}\n```')]
        self.assertEqual(run(ai.ask_json(MSGS)), {"action": "plan", "text": "x"})
        self.assertIsNone(ai.parse_json("not json"))


# ───────────────────────────── ۳) خطاها: 401 / 429 / timeout / ... ─────────────────────────────
class TestErrors(Base):
    def test_401_no_retry_blocks_and_logs_without_key(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(401, {"error": {"message": f"bad key {FAKE_KEY}"}})]
        with self.assertLogs("isekai-grave", level="WARNING") as cm:
            self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(len(FakeSession.calls), 1)          # retry نشد
        self.assertGreater(ai._blocked_until, time.time() + 800)
        self.assertEqual(ai.stats["http_401"], 1)
        logs = "\n".join(cm.output)
        self.assertIn("OPENROUTER_API_KEY", logs)
        self.assertNotIn(FAKE_KEY, logs)
        # درخواست بعدی اصلاً به شبکه نمیره
        self.assertIsNone(run(ai.ask(MSGS, cache_key="other")))
        self.assertEqual(len(FakeSession.calls), 1)

    def test_429_then_success_retries(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(429, {}, {"Retry-After": "1"}), ok("بعد از ۴۲۹")]
        with mock.patch("asyncio.sleep", self._nosleep):
            self.assertEqual(run(ai.ask(MSGS)), "بعد از ۴۲۹")
        self.assertEqual(len(FakeSession.calls), 2)
        self.assertEqual(ai.stats["http_429"], 1)

    def test_429_exhausted_cooldown_then_no_traffic(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(429, {}, {})]
        with mock.patch("asyncio.sleep", self._nosleep), self.assertLogs("isekai-grave", level="WARNING"):
            self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(len(FakeSession.calls), 2)          # 1 + فقط ۱ تلاشِ مجدد (بازیکن معطل نمیشه)
        self.assertGreater(ai._blocked_until, time.time() + 20)
        n = len(FakeSession.calls)
        self.assertIsNone(run(ai.ask(MSGS, cache_key="x")))
        self.assertEqual(len(FakeSession.calls), n)          # دیگه نمی‌کوبیم
        self.assertGreaterEqual(ai.stats["rate_limited"], 1)

    def test_429_inside_200_body(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(200, {"error": {"code": 429, "message": "rate limited"}}), ok("اوکی")]
        with mock.patch("asyncio.sleep", self._nosleep):
            self.assertEqual(run(ai.ask(MSGS)), "اوکی")

    def test_timeout_retries_then_none(self):
        _, ai = self.good()
        FakeSession.script = [asyncio.TimeoutError()]
        with mock.patch("asyncio.sleep", self._nosleep):
            self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(len(FakeSession.calls), 3)
        self.assertEqual(ai.stats["fail"], 1)

    def test_client_error_then_success(self):
        _, ai = self.good()
        FakeSession.script = [_ClientError("boom"), ok("برگشتم")]
        with mock.patch("asyncio.sleep", self._nosleep):
            self.assertEqual(run(ai.ask(MSGS)), "برگشتم")

    def test_500_retries(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(503, {}), ok("ok بعد از ۵۰۳")]
        with mock.patch("asyncio.sleep", self._nosleep):
            self.assertEqual(run(ai.ask(MSGS)), "ok بعد از ۵۰۳")

    def test_404_model_not_found_blocks_with_hint(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(404, {"error": {"message": "no endpoints"}})]
        with self.assertLogs("isekai-grave", level="WARNING") as cm:
            self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(len(FakeSession.calls), 1)
        self.assertIn("OPENROUTER_MODEL", "\n".join(cm.output))

    def test_402_credits_blocks(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(402, {"error": {}})]
        with self.assertLogs("isekai-grave", level="WARNING"):
            self.assertIsNone(run(ai.ask(MSGS)))
        self.assertEqual(len(FakeSession.calls), 1)

    def test_system_role_rejected_retries_merged(self):
        _, ai = self.good()
        FakeSession.script = [_Resp(400, {"error": {"message": "Developer instruction is not enabled"}}), ok("ادغام شد")]
        self.assertEqual(run(ai.ask(MSGS)), "ادغام شد")
        second = FakeSession.calls[1]["json"]["messages"]
        self.assertTrue(all(m["role"] != "system" for m in second))
        self.assertIn("sys", second[0]["content"])
        # بعدی‌ها مستقیم ادغام‌شده میرن
        run(ai.ask(MSGS, cache_key="again"))
        self.assertTrue(all(m["role"] != "system" for m in FakeSession.calls[2]["json"]["messages"]))

    def test_crash_log_has_no_key(self):
        _, ai = self.good()
        FakeSession.script = [RuntimeError(f"weird {FAKE_KEY}")]
        with self.assertLogs("isekai-grave", level="ERROR") as cm:
            self.assertIsNone(run(ai.ask(MSGS)))
        self.assertNotIn(FAKE_KEY, "\n".join(cm.output))

    def test_redact(self):
        _, ai = self.good()
        self.assertNotIn(FAKE_KEY, ai._redact(f"x {FAKE_KEY} y"))
        self.assertNotIn("sk-or-v1-abcdef", ai._redact("token sk-or-v1-abcdef123"))
        self.assertNotIn("secret123", ai._redact("Authorization: Bearer secret123"))


# ───────────────────────────── ۴) محدودیت نرخ و صف ─────────────────────────────
class TestLimits(Base):
    def test_player_rate_limit(self):
        _, ai = self.good()
        ai.AI_PLAYER_PER_MIN = 2
        for i in range(2):
            self.assertIsNotNone(run(ai.ask(MSGS, uid=1, cache_key=f"p{i}")))
        self.assertIsNone(run(ai.ask(MSGS, uid=1, cache_key="p3")))
        self.assertEqual(len(FakeSession.calls), 2)
        self.assertEqual(ai.stats["rate_limited"], 1)

    def test_global_rate_limit(self):
        _, ai = self.good()
        ai.AI_GLOBAL_PER_MIN = 1
        self.assertIsNotNone(run(ai.ask(MSGS, cache_key="a")))
        self.assertIsNone(run(ai.ask(MSGS, cache_key="b")))


# ───────────────────────────── ۵) fallback و شبیه‌سازی بدون API ─────────────────────────────
def _import_world(ai_module_loader):
    """worldsim/worldnpc رو ایمپورت می‌کنه؛ اگه pymongo/aiogram نصب نبود ماژول‌های سنگین stub میشن."""
    stubs = {}
    try:
        import pymongo  # noqa
    except ImportError:
        pm = types.ModuleType("pymongo")
        pm.ReturnDocument = types.SimpleNamespace(AFTER="after")
        pe = types.ModuleType("pymongo.errors")
        pe.DuplicateKeyError = type("DuplicateKeyError", (Exception,), {})
        stubs.update({"pymongo": pm, "pymongo.errors": pe})
    try:
        import aiogram  # noqa
    except ImportError:
        import html
        ui = types.ModuleType("ui")
        ui.btn = ui.kb = ui.panel = lambda *a, **k: None
        ut = types.ModuleType("utils")
        ut.esc = html.escape
        stubs.update({"ui": ui, "utils": ut})
    if "database" not in sys.modules:
        db = types.ModuleType("database")
        db.store = types.SimpleNamespace()
        stubs["database"] = db
    return stubs


class TestFallbackAndSim(Base):
    def _world(self):
        stubs = _import_world(None)
        p = mock.patch.dict(sys.modules, stubs)
        p.start()
        self.addCleanup(p.stop)
        for m in ("worldsim", "worldnpc"):
            sys.modules.pop(m, None)
        import worldnpc, worldsim, worlddata
        return worldnpc, worldsim, worlddata

    def _npc(self, WD):
        seed = dict(WD.NPC_SEEDS[0])
        seed["location"] = list(seed["routine"].values())[0] if isinstance(seed["routine"], dict) else seed["location"]
        return seed

    def test_npc_voice_fallback_when_api_down(self):
        _, ai = self.good()
        WN, WS, WD = self._world()
        WN.aiclient = ai
        FakeSession.script = [_Resp(503, {})]

        async def fake_clock():
            return {"phase_fa": "روز", "phase": "day"}

        async def fake_world(force=False):
            return {"news": []}

        npc = self._npc(WD)
        doc = {"user_id": 5, "first_name": "علی"}
        with mock.patch("asyncio.sleep", self._nosleep), mock.patch.object(WS, "clock_now", fake_clock), \
                mock.patch.object(WS, "get_world", fake_world):
            txt, from_ai = run(WN.npc_voice(npc, doc))
        self.assertFalse(from_ai)
        self.assertGreater(len(txt), 3)                      # پاسخ جایگزینِ شخصیت‌محور

    def test_npc_voice_uses_ai_when_ok_and_prompt_is_small(self):
        _, ai = self.good()
        WN, WS, WD = self._world()
        WN.aiclient = ai
        FakeSession.script = [ok("سلام ای غریبه، شب‌ها مراقب باش")]

        async def fake_clock():
            return {"phase_fa": "شب", "phase": "night"}

        async def fake_world(force=False):
            return {"news": [{"text": "n%d" % i} for i in range(10)]}

        npc = self._npc(WD)
        npc["memories"] = [{"x": "m%d" % i} for i in range(20)]
        with mock.patch.object(WS, "clock_now", fake_clock), mock.patch.object(WS, "get_world", fake_world):
            txt, from_ai = run(WN.npc_voice(npc, {"user_id": 7, "first_name": "سارا"}))
        self.assertTrue(from_ai)
        body = FakeSession.calls[0]["json"]
        self.assertLessEqual(body["max_tokens"], 120)        # خروجی محدوده
        self.assertEqual(len(body["messages"]), 2)           # تاریخچه‌ی کامل نمی‌ره
        self.assertLess(sum(len(m["content"]) for m in body["messages"]), 3000)
        self.assertNotIn("m0", body["messages"][0]["content"])   # فقط ۳ خاطره‌ی آخر

    def test_world_simulation_runs_without_any_api_request(self):
        _, ai = load_modules({})                              # بدون کلید/مدل
        WN, WS, WD = self._world()
        WS.aiclient = ai
        self.assertFalse(ai.ai_available())
        rng = random.Random(1)
        now = time.time()
        w = {"epoch": now - 3600, "regions": {r: {"danger": 50, "prosperity": 50} for r in WD.REGIONS},
             "factions": {k: dict(v) for k, v in WD.FACTIONS.items()},
             "frel": {WD.rel_key(a, b): v for (a, b), v in WD.FACTION_RELATIONS.items()},
             "economy": WD.initial_economy(rng), "rumors": [], "news": []}
        phase = WD.world_clock(now, w["epoch"], 6)["phase"]
        npcs = {}
        for seed in WD.NPC_SEEDS:
            d = dict(seed)
            d["location"] = d["routine"][phase]
            npcs[d["id"]] = d
        ctx = {"w": w, "npcs": npcs, "now": now, "clock": WD.world_clock(now, w["epoch"], 6), "dirty": set(), "events": []}
        for _ in range(12):
            ctx["now"] += 300
            WS.step_movement(ctx)
            WS.step_interactions(ctx)
            WS.step_economy(ctx)
            WS.step_rumors(ctx)
            for n in npcs.values():
                if n.get("important") and n["location"] != WD.ROAD:
                    WS.apply_decision(ctx, n, WS.rule_decision(ctx, n))
        self.assertEqual(FakeSession.calls, [])              # هیچ درخواستِ AI
        self.assertEqual(run(WS.ai_decision(ctx, next(iter(npcs.values())))), None)
        # polish/enrich هم بدون AI فوراً برمی‌گردن
        run(WS.polish_event("x"))
        self.assertEqual(FakeSession.calls, [])

    def test_ai_decision_returns_none_when_api_down(self):
        _, ai = self.good()
        WN, WS, WD = self._world()
        WS.aiclient = ai
        FakeSession.script = [_Resp(500, {})]
        rng = random.Random(2)
        w = {"regions": {r: {"danger": 50, "prosperity": 50} for r in WD.REGIONS}}
        npcs = {s["id"]: dict(s, location=WD.REGIONS[0] if isinstance(WD.REGIONS, (list, tuple)) else next(iter(WD.REGIONS))) for s in WD.NPC_SEEDS}
        ctx = {"w": w, "npcs": npcs, "events": []}
        n = next(x for x in npcs.values() if x.get("important"))
        with mock.patch("asyncio.sleep", self._nosleep):
            self.assertIsNone(run(WS.ai_decision(ctx, n)))   # صدازننده rule_decision رو می‌زنه


if __name__ == "__main__":
    unittest.main(verbosity=2)
