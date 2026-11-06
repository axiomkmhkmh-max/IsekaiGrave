"""تست‌های سفرِ ماجراجویی (ردپا ← ۳ مرحله). بدون تلگرام/دیتابیس/OpenRouterِ واقعی.

اجرا (از ریشه‌ی پروژه):  python -m unittest test_expedition -v
"""

import asyncio
import os
import sys
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load():
    u = types.ModuleType("utils")
    u.esc = lambda s: str(s)
    ui = types.ModuleType("ui")
    ui.btn = lambda text, data=None, color=None, url=None: (text, data)
    ui.kb = lambda *rows: [r for r in rows]
    ui.panel = lambda color, icon, title, lines, foot=None: title + "\n" + "\n".join(lines)
    pl = types.ModuleType("players")
    pl.cls_is = lambda d, c: False
    pl.gold_bonus = lambda d, g: g
    pl.loss_cut = lambda d, v: v

    async def grant(*a, **k):
        raise AssertionError("replaced per test")

    pl.grant = grant
    db = types.ModuleType("database")
    db.store = types.SimpleNamespace()
    stubs = {"utils": u, "ui": ui, "players": pl, "database": db}
    p = mock.patch.dict(sys.modules, stubs)
    p.start()
    for m in ("config", "aiclient", "content", "regions_new", "advscene", "expedition"):
        sys.modules.pop(m, None)
    import expedition
    return expedition, p


class Base(unittest.TestCase):
    def setUp(self):
        self.X, p = _load()
        self.addCleanup(p.stop)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.X._runs.clear()
        self.doc = {"user_id": 7, "level": 30, "survival_rate": 100}
        self.grants = []
        self.out = []

        async def grant(uid, gold=0, xp=0, item=None, survival=0):
            self.grants.append(dict(gold=gold, xp=xp, item=item, survival=survival))
            self.doc = dict(self.doc, survival_rate=self.doc["survival_rate"] + survival)
            return self.doc, False

        async def get(uid):
            return self.doc

        self.X.grant = grant
        self.X.store = types.SimpleNamespace(get=get)
        self.X.scene_ai = self._no_scene

    async def _no_scene(self, *a, **k):
        return None

    def step(self, act, stage, uid=7):
        async def edit(text, markup):
            self.out.append((text, markup))

        self.loop.run_until_complete(self.X.expedition_cb(uid, act, str(stage), edit))
        return self.out[-1]

    def buttons(self, markup):
        return [b for row in markup for b in row]


class TestTrail(Base):
    def test_start_trail_registers_run_and_returns_teaser(self):
        t = self.X.start_trail(7, "volcano")
        self.assertIn("ماجرا ادامه داره", t)
        self.assertEqual(self.X._runs[7]["biome"], "volcano")

    def test_expired_or_missing_run_says_trail_is_cold(self):
        text, mk = self.step("go", 0)
        self.assertIn("ردپا سرد شد", text)
        self.X.start_trail(7, "snow")
        self.X._runs[7]["t"] = time.time() - self.X.TTL - 1
        text, _ = self.step("go", 0)
        self.assertIn("ردپا سرد شد", text)
        self.assertNotIn(7, self.X._runs)

    def test_go_shows_stage_one_with_three_choices_owned_by_user(self):
        self.X.start_trail(7, "desert")
        text, mk = self.step("go", 0)
        self.assertIn("(1/3)", text)
        data = [d for _, d in self.buttons(mk)]
        self.assertEqual(data, ["e:a:1:7", "e:b:1:7", "e:c:1:7"])

    def test_stale_button_just_redisplays_current_stage(self):
        self.X.start_trail(7, "desert")
        self.step("go", 0)
        text, _ = self.step("a", 2)               # دکمه‌ی مرحله‌ی دیگه
        self.assertIn("(1/3)", text)
        self.assertEqual(self.grants, [])


class TestFullRun(Base):
    def run_all(self, biome, picks, force_win=True):
        self.X.start_trail(7, biome)
        self.step("go", 0)
        last = None
        with mock.patch.object(self.X.random, "random", return_value=0.0 if force_win else 0.99), \
                mock.patch.object(self.X.random, "randint", lambda a, b: b if force_win else a):
            for act in picks:
                stage = self.X._runs[7]["stage"] if 7 in self.X._runs else None
                last = self.step(act, stage)
        return last

    def test_winning_run_ends_with_bounded_giant_reward(self):
        text, mk = self.run_all("volcano", ["a", "a", "a"])
        self.assertIn("پایان", text)
        self.assertIn("غنیمت", text)
        self.assertNotIn(7, self.X._runs)
        total_gold = sum(g["gold"] for g in self.grants)
        self.assertTrue(0 < total_gold <= 15 + 30 + 90 + 5)        # سقفِ سه مرحله (پایه)
        self.assertTrue(any(g["item"] for g in self.grants))
        self.assertTrue(any(d.startswith("x:volcano:") for _, d in self.buttons(mk)))

    def test_low_level_finale_is_monster_not_giant(self):
        self.doc["level"] = 3
        self.X.start_trail(7, "volcano")
        self.step("go", 0)
        with mock.patch.object(self.X.random, "random", return_value=0.0):
            self.step("a", 1)
            self.step("b", 2)
        foe = self.X._runs[7]["foe"]
        self.assertFalse(foe[2])
        import content
        self.assertIn(foe[0], [n for n, _ in content.BIOMES["volcano"]["monsters"]])

    def test_high_level_finale_is_giant(self):
        self.X.start_trail(7, "swamp")
        self.step("go", 0)
        with mock.patch.object(self.X.random, "random", return_value=0.0):
            self.step("a", 1)
            self.step("b", 2)
        self.assertTrue(self.X._runs[7]["foe"][2])

    def test_losing_fight_at_stage_two_ends_run(self):
        self.doc.update(level=1, survival_rate=40)
        text, _ = self.run_all("volcano", ["a", "a"], force_win=False)
        self.assertIn("پایان", text)
        self.assertNotIn(7, self.X._runs)

    def test_survival_never_drops_below_minimum_even_on_worst_luck(self):
        self.doc.update(level=1, survival_rate=10)
        self.X.start_trail(7, "volcano")
        self.step("go", 0)
        with mock.patch.object(self.X.random, "random", return_value=0.99), \
                mock.patch.object(self.X.random, "randint", lambda a, b: b):
            self.step("a", 1)
            self.step("c", 2)                    # ریسک و شکست
        self.assertGreaterEqual(self.doc["survival_rate"], self.X.MIN_KEEP)

    def test_giving_up_at_stage_one_ends_with_tiny_xp(self):
        text, _ = self.run_all("snow", ["c"])
        self.assertIn("پایان", text)
        self.assertEqual(sum(g["gold"] for g in self.grants), 0)

    def test_ai_scene_only_narrates_finale_and_cannot_change_result(self):
        async def fake_scene(B, what, name, uid, wait=3):
            return "غول از دلِ مه بیرون میاد و خمیازه می‌کشه"

        self.X.scene_ai = fake_scene
        self.X.start_trail(7, "volcano")
        self.step("go", 0)
        with mock.patch.object(self.X.random, "random", return_value=0.0):
            self.step("a", 1)
            text, _ = self.step("b", 2)
        self.assertIn("غول از دلِ مه", text)
        self.assertIn("(3/3)", text)

    def test_every_biome_runs_to_the_end_without_error(self):
        import content
        for b in content.BIOMES:
            if b == "city":
                continue
            self.X._runs.clear()
            self.grants.clear()
            text, _ = self.run_all(b, ["a", "a", "a"])
            self.assertIn("پایان", text, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
