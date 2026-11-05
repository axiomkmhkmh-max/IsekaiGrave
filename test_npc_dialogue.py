"""تست‌های گفتگوی آزاد با NPC (بدون هیچ درخواستِ واقعیِ OpenRouter؛ aiohttp و دیتابیس ساختگی‌ان).

اجرا (از ریشه‌ی پروژه):  python -m unittest test_npc_dialogue -v
"""

import os
import sys
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "tests"), os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_aiclient_openrouter as T  # noqa: E402  (FakeSession, Base, ok, _Resp, _import_world)

FAKE_KEY = T.FAKE_KEY


class FakeColl:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, q, *a, **k):
        return self.docs.get(q.get("id"))

    async def update_one(self, *a, **k):
        return types.SimpleNamespace(modified_count=0)


class _Handle:
    def __init__(self, box, i):
        self.box, self.i = box, i

    async def edit_text(self, text, reply_markup=None):
        self.box[self.i] = text


class FakeMsg:
    def __init__(self):
        self.replies = []

    async def reply(self, text, reply_markup=None):
        self.replies.append(text)
        return _Handle(self.replies, len(self.replies) - 1)   # مثل aiogram: پیامِ «فکر می‌کنه» بعداً ویرایش میشه


class NpcChat(T.Base):
    def setup_world(self, in_db=True, **env):
        _, self.ai = self.good(**env) if env.get("_good", True) else T.load_modules({})
        stubs = T._import_world(None)
        p = mock.patch.dict(sys.modules, stubs)
        p.start()
        self.addCleanup(p.stop)
        for m in ("worldsim", "worldnpc"):
            sys.modules.pop(m, None)
        import worldnpc, worldsim, worlddata
        self.WN, self.WS, self.WD = worldnpc, worldsim, worlddata
        self.WN.aiclient = self.ai
        seeds = {s["id"]: dict(s, location="city") for s in worlddata.NPC_SEEDS}
        self.WN.store = types.SimpleNamespace(wnpcs=FakeColl(seeds if in_db else {}))
        self.WN.panel = lambda color, icon, title, lines, foot=None: f"{title}|{'|'.join(lines)}|{foot or ''}"
        self.WN._talk.clear()

        async def clock():
            return {"phase_fa": "روز", "phase": "day"}

        async def world(force=False):
            return {"news": []}

        for patcher in (mock.patch.object(self.WS, "clock_now", clock), mock.patch.object(self.WS, "get_world", world)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.doc = {"user_id": 11, "first_name": "سارا", "location": "city"}

    def chat(self, text):
        m = FakeMsg()
        with mock.patch("asyncio.sleep", self._nosleep):
            ok = T.run(self.WN.do_npc_chat(m, self.doc, text))
        return ok, m

    def body(self, i=-1):
        return T.FakeSession.calls[i]["json"]


class TestIdentity(NpcChat):
    def test_correct_npc_identity_reaches_ai_client(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("من همه‌ی ورودی‌ها رو یادداشت می‌کنم")]
        self.WN.set_talk(11, "guard", "city")
        ok, m = self.chat("اگه از شهر برم چی یادت می‌مونه؟")
        self.assertTrue(ok)
        msgs = self.body()["messages"]
        sysm = msgs[0]["content"]
        self.assertIn("کاپیتان هِلگا", sysm)
        self.assertIn("guard", sysm.lower() + " guard")  # هویت از نامِ NPC میاد؛ نقش هم تو prompt هست
        self.assertIn("نگهبان", sysm)
        for other in ("اوندین", "گریگور", "ولادیک", "ماریوس"):
            self.assertNotIn(other, sysm)
        self.assertIn("اگه از شهر برم", msgs[-1]["content"])
        self.assertNotIn("ایزدبانو", sysm)

    def test_response_returned_for_same_npc_and_is_ai(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("هیچ‌کس رو فراموش نمی‌کنم، مسافر")]
        self.WN.set_talk(11, "guard", "city")
        ok, m = self.chat("منو یادت می‌مونه؟")
        self.assertTrue(ok)
        self.assertIn("کاپیتان هِلگا", m.replies[0])
        self.assertIn("هیچ‌کس رو فراموش نمی‌کنم", m.replies[0])

    def test_no_cross_npc_context(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("جواب نگهبان به تو")]
        self.WN.set_talk(11, "guard", "city")
        self.chat("سوال محرمانه‌ی نگهبان")
        T.FakeSession.script = [T.ok("جواب جادوگر برای تو")]
        self.WN.set_talk(11, "witch", "city")           # عوض شدنِ NPC → تاریخچه‌ی جدید
        ok, m = self.chat("سلام")
        self.assertTrue(ok)
        text = " ".join(x["content"] for x in self.body()["messages"])
        self.assertIn("اوندین", text)
        self.assertNotIn("کاپیتان هِلگا", text)
        self.assertNotIn("سوال محرمانه‌ی نگهبان", text)
        self.assertNotIn("جواب نگهبان", text)
        self.assertIn("اوندین", m.replies[0])

    def test_thinking_message_is_edited_into_answer(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("جواب نهایی نگهبان")]
        self.WN.set_talk(11, "guard", "city")
        ok, m = self.chat("سلام")
        self.assertEqual(len(m.replies), 1)                 # یک پیام؛ «فکر می‌کنه» با جواب جایگزین شد
        self.assertIn("جواب نهایی نگهبان", m.replies[0])
        self.assertNotIn("فکر می‌کنه", m.replies[0])

    def test_chat_prompt_gives_npc_freedom_but_no_mechanics(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("جواب آزاد نگهبان برای تو")]
        self.WN.set_talk(11, "guard", "city")
        self.chat("هر چی دوست داری بگو")
        body = self.body()
        sysm = body["messages"][0]["content"]
        self.assertIn("You decide freely", sysm)
        self.assertIn("Never promise or mention money", sysm)
        self.assertGreaterEqual(body["max_tokens"], 200)

    def test_fallback_does_not_repeat_same_line_twice(self):
        self.setup_world()
        self.WN.set_talk(11, "guard", "city")
        seen = []
        for _ in range(6):
            T.FakeSession.script = [T._Resp(503, {})]
            self.WN.aiclient._blocked_until = 0.0
            self.WN.aiclient._fail_streak = 0
            ok, m = self.chat("سلام")
            seen.append(m.replies[0])
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])))

    def test_history_kept_for_same_npc_only(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("جواب اول نگهبان")]
        self.WN.set_talk(11, "guard", "city")
        self.chat("سوال اول")
        T.FakeSession.script = [T.ok("جواب دوم نگهبان")]
        self.chat("سوال دوم")
        text = " ".join(x["content"] for x in self.body()["messages"])
        self.assertIn("سوال اول", text)
        self.assertIn("جواب اول نگهبان", text)

    def test_no_active_conversation_returns_false_without_request(self):
        self.setup_world()
        ok, m = self.chat("سلام")
        self.assertFalse(ok)
        self.assertEqual(T.FakeSession.calls, [])
        self.assertEqual(m.replies, [])

    def test_conversation_ends_on_location_change_or_ttl(self):
        self.setup_world()
        self.WN.set_talk(11, "guard", "city")
        self.assertIsNone(self.WN.current_talk(11, "forest"))
        self.WN.set_talk(11, "guard", "city")
        self.WN._talk[11]["t"] = time.time() - self.WN.TALK_TTL - 1
        self.assertIsNone(self.WN.current_talk(11, "city"))

    def test_seed_used_when_db_has_no_npc(self):
        self.setup_world(in_db=False)
        T.FakeSession.script = [T.ok("از دیتابیس نیومدم ولی نگهبانم")]
        self.WN.set_talk(11, "guard", "city")
        ok, m = self.chat("سلام")
        self.assertTrue(ok)
        self.assertIn("کاپیتان هِلگا", self.body()["messages"][0]["content"])


class TestChurchGoddess(NpcChat):
    def test_goddess_identity_and_reply(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("بشین، چای سرد شد ولی گوش می‌دم")]
        self.WN.set_talk(11, "goddess", "city")
        ok, m = self.chat("دلم گرفته")
        self.assertTrue(ok)
        sysm = self.body()["messages"][0]["content"]
        self.assertIn("ایزدبانوی پایان", sysm)
        self.assertIn("Never speak as any other character or narrator", sysm)
        for other in ("کاپیتان هِلگا", "اوندین", "گریگور"):
            self.assertNotIn(other, sysm)
        self.assertIn("ایزدبانوی پایان", m.replies[0])
        self.assertIn("چای سرد شد", m.replies[0])

    def test_goddess_fallback_is_her_own_lines(self):
        self.setup_world()
        T.FakeSession.script = [T._Resp(503, {})]
        self.WN.set_talk(11, "goddess", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        import content
        self.assertTrue(any(self.WN.esc(r) in m.replies[0] for r in content.ROASTS))
        self.assertIn("NPC fallback dialogue used npc=goddess", "\n".join(logs.output))

    def test_church_opens_only_in_city_and_starts_goddess_talk(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("خوش اومدی زائر خسته")]

        async def get(uid):
            return dict(self.doc)

        self.WN.store.get = get
        self.WN.kb = lambda *a, **k: None
        self.WN.btn = lambda *a, **k: None
        m = types.SimpleNamespace(from_user=types.SimpleNamespace(id=11), replies=[])

        async def reply(text, reply_markup=None):
            m.replies.append(text)

        m.reply = reply
        T.run(self.WN.do_church(m))
        self.assertIn("خوش اومدی زائر خسته", m.replies[-1])
        self.assertEqual(self.WN._talk[11]["npc"], "goddess")
        self.doc["location"] = "forest"
        m.replies.clear()
        T.run(self.WN.do_church(m))
        self.assertIn("پایتخت", m.replies[-1])

    def test_church_intent_regex(self):
        import intents
        for t in ("کلیسا", "میرم کلیسا", "ورود به کلیسا", "برم به کلیسای ایزدبانو"):
            self.assertTrue(intents.CHURCH_RE.fullmatch(t), t)
        self.assertIsNone(intents.CHURCH_RE.fullmatch("چرا کلیسا اینقدر خلوته؟"))


class TestFallback(NpcChat):
    def _guard_lines(self):
        names = ("سارا",)
        return {l.replace("{p}", names[0]).strip("«»") for l in self.WD.FALLBACK_LINES["جدی"]}

    def _assert_guard_fallback(self, m, logs):
        self.assertTrue(any(l.strip("<>") and l in m.replies[0] for l in self._guard_lines()), m.replies[0])
        self.assertIn("کاپیتان هِلگا", m.replies[0])
        joined = "\n".join(logs.output)
        self.assertIn("NPC fallback dialogue used npc=guard", joined)
        self.assertNotIn("OpenRouter request succeeded", joined)
        self.assertNotIn(FAKE_KEY, joined)

    def test_http_error_uses_same_npc_fallback(self):
        self.setup_world()
        T.FakeSession.script = [T._Resp(503, {})]
        self.WN.set_talk(11, "guard", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        self.assertTrue(ok)
        self._assert_guard_fallback(m, logs)
        self.assertIn("reason=http_503", "\n".join(logs.output))

    def test_timeout_uses_same_npc_fallback(self):
        self.setup_world()
        T.FakeSession.script = [T._ClientError("boom")]
        self.WN.set_talk(11, "guard", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        self._assert_guard_fallback(m, logs)

    def test_empty_model_response_falls_back(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("   ")]
        self.WN.set_talk(11, "guard", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        self._assert_guard_fallback(m, logs)
        self.assertIn("empty_response", "\n".join(logs.output))

    def test_rate_limit_429_falls_back_same_npc(self):
        self.setup_world()
        T.FakeSession.script = [T._Resp(429, {})]
        self.WN.set_talk(11, "witch", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        self.assertIn("اوندین", m.replies[0])
        self.assertIn("NPC fallback dialogue used npc=witch", "\n".join(logs.output))

    def test_missing_model_is_clear_and_makes_no_request(self):
        self.setup_world()
        self.ai.OPENROUTER_MODEL = ""
        self.assertIn("OPENROUTER_MODEL", self.ai.config_problem())
        self.WN.set_talk(11, "guard", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        self.assertTrue(ok)
        self.assertEqual(T.FakeSession.calls, [])
        self.assertIn("reason=not_configured", "\n".join(logs.output))
        self.assertIn("کاپیتان هِلگا", m.replies[0])

    def test_invalid_model_format_is_rejected_clearly(self):
        self.setup_world()
        self.ai.OPENROUTER_MODEL = "not a model"
        self.assertIn("نامعتبر", self.ai.config_problem())
        self.assertFalse(self.ai.ai_available())
        self.ai.OPENROUTER_MODEL = "google/gemma-4-26b-a4b-it:free"
        self.assertIsNone(self.ai.config_problem())


class TestLogsAndSecrets(NpcChat):
    def test_success_logs_and_no_secrets_or_player_text(self):
        self.setup_world()
        T.FakeSession.script = [T.ok("پاسخ از مدل برای مسافر")]
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            self.WN.set_talk(11, "guard", "city")
            self.chat("متنِ خصوصیِ بازیکن 12345")
        joined = "\n".join(logs.output)
        for needle in ("NPC conversation started npc=guard", "NPC identity selected npc=guard",
                       "OpenRouter request started tag=npc_chat:guard", "OpenRouter request succeeded tag=npc_chat:guard"):
            self.assertIn(needle, joined)
        self.assertNotIn("NPC fallback", joined)
        self.assertNotIn(FAKE_KEY, joined)
        self.assertNotIn("متنِ خصوصیِ بازیکن", joined)
        self.assertNotIn("پاسخ از مدل", joined)
        self.assertEqual(T.FakeSession.calls[0]["headers"]["Authorization"], f"Bearer {FAKE_KEY}")   # فقط تو هدر

    def test_401_failure_never_logs_key(self):
        self.setup_world()
        T.FakeSession.script = [T._Resp(401, {"error": "bad key " + FAKE_KEY})]
        self.WN.set_talk(11, "guard", "city")
        with self.assertLogs("isekai-grave", level="INFO") as logs:
            ok, m = self.chat("سلام")
        joined = "\n".join(logs.output)
        self.assertNotIn(FAKE_KEY, joined)
        self.assertIn("reason=http_401", joined)
        self.assertNotIn(FAKE_KEY, m.replies[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
