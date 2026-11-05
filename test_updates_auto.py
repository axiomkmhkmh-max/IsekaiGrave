"""تست‌های اطلاع‌رسانیِ خودکارِ آپدیت (بدون تلگرام، بدون دیتابیس، بدون OpenRouterِ واقعی).

اجرا (از ریشه‌ی پروژه):  python -m unittest test_updates_auto -v
"""

import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _AIter:
    def __init__(self, items):
        self.items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)


class FakeMeta:
    def __init__(self, prev):
        self.prev, self.saved = prev, None

    async def find_one_and_update(self, q, u, upsert=False):
        self.saved = u["$set"]["version"]
        return self.prev


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, uid, text):
        self.sent.append((uid, text))


def _stubs(prev):
    ag = types.ModuleType("aiogram")
    ag.Bot = FakeBot
    ex = types.ModuleType("aiogram.exceptions")
    for n in ("TelegramAPIError", "TelegramForbiddenError", "TelegramRetryAfter"):
        setattr(ex, n, type(n, (Exception,), {}))
    db = types.ModuleType("database")
    db.store = types.SimpleNamespace(
        meta=FakeMeta(prev), users=types.SimpleNamespace(find=lambda q, p: _AIter([{"user_id": 1}, {"user_id": 2}])))
    return {"aiogram": ag, "aiogram.exceptions": ex, "database": db}


class TestAutoUpdates(unittest.TestCase):
    def run_update(self, env, prev=None, ai=None, ai_up=True):
        """ai: خروجیِ ask_json (None/ dict). برمی‌گردونه (bot, store.meta)."""
        stubs = _stubs(prev)
        env = dict(env)
        for k in ("RAILWAY_GIT_COMMIT_SHA", "RAILWAY_GIT_COMMIT_MESSAGE", "AUTO_UPDATE_NOTES", "NOTIFY_ON_UPDATE"):
            os.environ.pop(k, None)
        with mock.patch.dict(sys.modules, stubs), mock.patch.dict(os.environ, env):
            for m in ("config", "aiclient", "updates"):
                sys.modules.pop(m, None)
            import updates
            self.up = updates
            fake_ai = mock.AsyncMock(return_value=ai)
            loop = asyncio.new_event_loop()
            real_sleep = asyncio.sleep

            async def nosleep(*a, **k):
                return None

            try:
                with mock.patch.object(updates.aiclient, "ai_available", return_value=ai_up), \
                        mock.patch.object(updates.aiclient, "ask_json", fake_ai), \
                        mock.patch("asyncio.sleep", nosleep):
                    bot = FakeBot()
                    loop.run_until_complete(updates.notify_if_updated(bot))
                    if updates._tasks:
                        loop.run_until_complete(asyncio.gather(*list(updates._tasks)))
            finally:
                loop.close()
            self.ai_calls = fake_ai.await_count
            return bot, stubs["database"].store.meta

    def test_new_commit_ai_notes_sent_to_all_players(self):
        bot, meta = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "abcdef1234567", "RAILWAY_GIT_COMMIT_MESSAGE": "Add church + NPC chat"},
                                    ai={"notes": ["⛪ کلیسای ایزدبانو اضافه شد", "🗣 با NPCها آزادانه حرف بزن"]})
        self.assertEqual({u for u, _ in bot.sent}, {1, 2})
        text = bot.sent[0][1]
        self.assertIn("کلیسای ایزدبانو اضافه شد", text)
        self.assertIn("/start", text)
        self.assertTrue(meta.saved.endswith("|abcdef1"))

    def test_same_commit_after_restart_sends_nothing(self):
        stubs_prev = None
        bot0, meta0 = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "abcdef1234567", "RAILWAY_GIT_COMMIT_MESSAGE": "x"},
                                      ai={"notes": ["🛠 تغییر"]})
        rel = meta0.saved
        bot, _ = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "abcdef1234567", "RAILWAY_GIT_COMMIT_MESSAGE": "x"},
                                 prev={"version": rel}, ai={"notes": ["🛠 تغییر"]})
        self.assertEqual(bot.sent, [])
        self.assertEqual(self.ai_calls, 0)

    def test_silent_commit_not_broadcast(self):
        bot, meta = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "1111111aaaa", "RAILWAY_GIT_COMMIT_MESSAGE": "fix typo [silent]"},
                                    ai={"notes": ["🛠 چیزی"]})
        self.assertEqual(bot.sent, [])
        self.assertIsNotNone(meta.saved)                      # نسخه ثبت میشه تا بعداً دوباره حساب نشه

    def test_ai_says_nothing_visible_skips_broadcast(self):
        bot, _ = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "2222222bbbb", "RAILWAY_GIT_COMMIT_MESSAGE": "refactor tests"},
                                 ai={"notes": []})
        self.assertEqual(bot.sent, [])

    def test_ai_down_uses_persian_commit_message(self):
        bot, _ = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "3333333cccc",
                                  "RAILWAY_GIT_COMMIT_MESSAGE": "کلیسا اضافه شد\n- ایزدبانو جواب میده\nCo-authored-by: x"},
                                 ai=None, ai_up=False)
        text = bot.sent[0][1]
        self.assertIn("کلیسا اضافه شد", text)
        self.assertIn("ایزدبانو جواب میده", text)
        self.assertNotIn("Co-authored", text)

    def test_ai_down_english_commit_gets_generic_line_not_raw_english(self):
        bot, _ = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "4444444dddd", "RAILWAY_GIT_COMMIT_MESSAGE": "Fix OpenRouter 429 handling"},
                                 ai=None, ai_up=False)
        text = bot.sent[0][1]
        self.assertIn("بهبودها", text)
        self.assertNotIn("OpenRouter", text)

    def test_ai_output_without_persian_is_dropped(self):
        bot, _ = self.run_update({"RAILWAY_GIT_COMMIT_SHA": "5555555eeee", "RAILWAY_GIT_COMMIT_MESSAGE": "Add shop"},
                                 ai={"notes": ["Added a shop"]})
        self.assertEqual(bot.sent, [])                         # AI جواب داد ولی بولتِ فارسیِ معتبر نبود → چیزی برای نمایش نیست

    def test_manual_mode_without_git_uses_static_notes(self):
        bot, meta = self.run_update({}, ai={"notes": ["🛠 نباید استفاده بشه"]})
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(meta.saved, self.up.BOT_VERSION)
        self.assertIn(self.up.UPDATE_NOTES[0], bot.sent[0][1].replace("&amp;", "&"))

    def test_auto_can_be_disabled(self):
        bot, meta = self.run_update({"AUTO_UPDATE_NOTES": "0", "RAILWAY_GIT_COMMIT_SHA": "6666666ffff",
                                     "RAILWAY_GIT_COMMIT_MESSAGE": "x"}, ai={"notes": ["🛠 تغییر"]})
        self.assertEqual(self.ai_calls, 0)
        self.assertEqual(meta.saved, self.up.BOT_VERSION)

    def test_notify_switch_off(self):
        bot, _ = self.run_update({"NOTIFY_ON_UPDATE": "0", "RAILWAY_GIT_COMMIT_SHA": "7777777aaaa",
                                  "RAILWAY_GIT_COMMIT_MESSAGE": "x"}, ai={"notes": ["🛠 تغییر"]})
        self.assertEqual(bot.sent, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
