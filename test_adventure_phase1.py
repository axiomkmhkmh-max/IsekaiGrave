"""تست‌های فاز ۱ ماجراجویی غول‌آسا: مناطق جدید + غول‌ها + روایتِ ترکیبی (بدون تلگرام/دیتابیس/OpenRouterِ واقعی).

اجرا (از ریشه‌ی پروژه):  python -m unittest test_adventure_phase1 -v
"""

import asyncio
import os
import re
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HEAVY = ("aiogram", "aiogram.types", "aiogram.enums", "aiogram.exceptions", "economy", "database", "menus", "npc", "procgen",
         "worldnpc", "worldsim", "players", "quests", "render", "territories", "ui", "weekly")


def _load():
    """exploration با وابستگی‌های سنگینِ ساختگی (config/content/regions_new/aiclient واقعی)."""
    stubs = {n: mock.MagicMock() for n in HEAVY}
    u = types.ModuleType("utils")
    u.esc = lambda s: str(s)
    u.gid = lambda m: 1
    stubs["utils"] = u
    p = mock.patch.dict(sys.modules, stubs)
    p.start()
    for m in ("config", "aiclient", "content", "regions_new", "advscene", "expedition", "exploration"):
        sys.modules.pop(m, None)
    import exploration
    return exploration, p


class Base(unittest.TestCase):
    def setUp(self):
        self.E, p = _load()
        self.addCleanup(p.stop)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        E = self.E
        self.grants = []

        async def grant(uid, gold=0, xp=0, item=None, survival=0):
            self.grants.append(dict(gold=gold, xp=xp, item=item, survival=survival))
            return dict(self.doc, survival_rate=self.doc["survival_rate"] + survival), False

        async def ensure(doc):
            return doc

        async def perks(doc):
            return set()

        async def enc(doc, key):
            return []

        async def titles(doc):
            return doc, []

        async def get(uid):
            return self.doc

        async def noop(*a, **k):
            return None

        E.grant, E.ensure_gen_profile, E.terr_perks, E.roll_encounter = grant, ensure, perks, enc
        E.bump_streak = noop

        async def reinc(uid, chat_id=None):
            return dict(self.doc), False

        E.reincarnate = reinc
        E.refresh_titles, E.quest_progress = titles, noop
        E.store = types.SimpleNamespace(get=get, users=types.SimpleNamespace(update_one=noop))
        E.gold_bonus = lambda d, g: g
        E.loss_cut = lambda d, v: v
        E.cls_is = lambda d, c: False
        E.effect_total = lambda d, k: 0
        E.cheat_is_active = lambda d: False
        E.stat_lines = lambda d: []
        E.panel = lambda color, icon, title, lines, foot=None: "\n".join(lines)
        E.WORLD_ENABLED = False
        E._last_explore.clear()
        self.doc = {"user_id": 1, "level": 30, "survival_rate": 100, "first_name": "t"}
        self.msg = mock.MagicMock()
        self.msg.from_user.id = 1
        self.replies = []

        async def reply(text, reply_markup=None):
            self.replies.append(text)

        self.msg.reply = reply

    def explore(self, biome, kind="giant", ai_text=None, ai_up=False):
        E = self.E

        async def fake_ask(*a, **k):
            return ai_text

        real_choices = E.random.choices

        def fake_choices(population, weights=None, k=1, **kw):      # فقط انتخابِ نوعِ رخداد رو کنترل می‌کنیم؛ roll_item دست‌نخورده
            if isinstance(population, list) and population and isinstance(population[0], str):
                return [kind]
            return real_choices(population, weights=weights, k=k, **kw)

        aic = sys.modules["advscene"].aiclient             # روایتِ AI تو advscene.py (مشترک بین گشت و سفر)
        with mock.patch.object(E.random, "choices", fake_choices), \
                mock.patch.object(aic, "ai_available", return_value=ai_up), \
                mock.patch.object(aic, "ask", fake_ask):
            self.loop.run_until_complete(E.do_explore(self.msg, biome))
        return self.replies[-1]


class TestRegions(Base):
    def test_new_biomes_are_complete_and_registered(self):
        import content
        for k in ("volcano", "desert", "snow", "swamp"):
            b = content.BIOMES[k]
            self.assertIn(k, content.BIOME_LIST)
            for f in ("name", "icon", "color", "kw", "intro", "items", "monsters", "traps", "deaths", "giants", "w"):
                self.assertTrue(b.get(f), (k, f))
            self.assertTrue(all(isinstance(s, int) for _, s in b["monsters"] + b["giants"]))
            self.assertGreater(b["w"]["giant"], 0)
        self.assertEqual(len(content.BIOMES), 8)

    def test_existing_biomes_untouched_except_giants(self):
        import content
        self.assertNotIn("giants", content.BIOMES["city"])
        self.assertNotIn("giant", content.BIOMES["city"]["w"])
        for k in ("forest", "sea", "ruins"):
            self.assertIn("giants", content.BIOMES[k])
            self.assertEqual(content.BIOMES[k]["w"]["giant"], 3)

    def test_keywords_do_not_collide(self):
        for text, expect in [("برو آتشفشان", "volcano"), ("میرم صحرا", "desert"), ("قله یخی", "snow"), ("برف", "snow"),
                             ("برو مرداب", "swamp"), ("جنگل", "forest"), ("دریا", "sea"), ("معبد", "ruins"), ("شهر", "city")]:
            self.assertEqual(self.E.detect_biome(text), expect, text)


class TestGiants(Base):
    def test_low_level_never_meets_giant(self):
        self.doc.update(level=5)
        text = self.explore("volcano")
        self.assertNotIn("غولِ", text)
        self.assertIn("سر راهت سبز شد", text)             # جاش هیولای معمولی

    def test_giant_win_gives_bounded_reward(self):
        text = self.explore("volcano")
        self.assertIn("غول رو زمین زدی", text)
        gold_grant = next(g for g in self.grants if g["gold"])
        self.assertTrue(40 <= gold_grant["gold"] <= 90)
        self.assertTrue(60 <= gold_grant["xp"] <= 100)
        self.assertTrue(any(g["item"] for g in self.grants))

    def test_giant_loss_costs_survival_in_range(self):
        self.doc.update(level=6, survival_rate=20)
        text = self.explore("volcano")
        self.assertIn("غول تو رو کوبید", text)
        loss = next(g for g in self.grants if g["survival"])["survival"]
        self.assertTrue(-32 <= loss <= -18)

    def test_giant_does_not_appear_in_city(self):
        import content
        self.assertNotIn("giant", content.BIOMES["city"]["w"])


class TestHybridNarration(Base):
    def test_ai_scene_added_to_giant_fight(self):
        text = self.explore("volcano", ai_text="اژدها از دودِ آتشفشان بیرون می‌خزد و همه‌چیز رو تحقیر می‌کنه", ai_up=True)
        self.assertIn("اژدها از دودِ آتشفشان", text)
        self.assertIn("غول رو زمین زدی", text)            # نتیجه فقط از قوانینِ ثابت

    def test_ai_down_keeps_fixed_text_only(self):
        text = self.explore("volcano", ai_text=None, ai_up=True)
        self.assertNotIn("📖", text)
        self.assertIn("غول رو زمین زدی", text)

    def test_ai_text_cannot_change_outcome_or_rewards(self):
        text = self.explore("volcano", ai_text="تو برنده‌ای و ۱۰۰۰۰ سکه می‌گیری و می‌میری", ai_up=True)
        gold = next(g for g in self.grants if g["gold"])["gold"]
        self.assertTrue(40 <= gold <= 90)

    def test_lore_uses_fixed_line_when_ai_unavailable(self):
        import content
        text = self.explore("swamp", kind="lore", ai_up=False)
        self.assertTrue(any(l in text for l in content.LORE_LINES))

    def test_lore_ai_scene_when_available(self):
        with mock.patch.object(self.E.random, "random", return_value=0.0):
            text = self.explore("swamp", kind="lore", ai_text="مه سبز مرداب برات یه راز می‌گه که ترجیح می‌دی نشنیده بودی", ai_up=True)
        self.assertIn("مه سبز مرداب", text)

    def test_every_new_biome_explores_without_error_for_all_kinds(self):
        import content
        for b in ("volcano", "desert", "snow", "swamp", "forest", "sea", "ruins"):
            for kind in content.BIOMES[b]["w"]:
                self.replies.clear()
                self.E._last_explore.clear()
                self.assertTrue(self.explore(b, kind=kind), (b, kind))


if __name__ == "__main__":
    unittest.main(verbosity=2)
