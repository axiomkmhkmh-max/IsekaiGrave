"""تست‌های کنش‌های ریپلایی (حمله، دزدی، ترمیم، هدیه، جایزه‌ی سر، جاسوسی، حالت جنگ).
دیتابیس/تلگرام ساختگی‌ان؛ موتورِ نبردِ واقعی فقط تو تستِ smoke استفاده میشه.

اجرا (از ریشه‌ی پروژه):  python -m unittest test_skirmish -v
"""

import asyncio
import copy
import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _match(doc, flt):
    for k, v in flt.items():
        cur = doc.get(k)
        if isinstance(v, dict):
            for op, x in v.items():
                if op == "$ne" and cur == x:
                    return False
                if op == "$gt" and not (cur is not None and cur > x):
                    return False
                if op == "$lte" and not (cur is not None and cur <= x):
                    return False
        elif cur != v:
            return False
    return True


def _apply(doc, upd):
    for k, v in upd.get("$set", {}).items():
        _setp(doc, k, v)
    for k, v in upd.get("$inc", {}).items():
        _setp(doc, k, (_getp(doc, k) or 0) + v)
    for k in upd.get("$unset", {}):
        parts = k.split(".")
        d = doc
        for p in parts[:-1]:
            d = d.get(p, {})
        d.pop(parts[-1], None)


def _getp(doc, k):
    d = doc
    for p in k.split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


def _setp(doc, k, v):
    parts = k.split(".")
    d = doc
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = v


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, key, direction):
        self.rows.sort(key=lambda r: r[key], reverse=direction < 0)
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    async def to_list(self, n):
        return self.rows[:n]

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class Coll:
    def __init__(self):
        self.docs = []

    async def insert_one(self, d):
        self.docs.append(dict(d))

    def find(self, flt=None, proj=None):
        return Cursor([d for d in self.docs if _match(d, flt or {})])

    async def find_one_and_update(self, flt, upd):
        for d in self.docs:
            if _match(d, flt):
                before = copy.deepcopy(d)
                _apply(d, upd)
                return before
        return None


class Users:
    def __init__(self):
        self.docs = {}

    async def update_one(self, flt, upd):
        d = self.docs.get(flt["user_id"])
        if d is not None:
            _apply(d, upd)
        return types.SimpleNamespace(modified_count=1 if d is not None else 0)


def _user(uid, **kw):
    d = {"user_id": uid, "first_name": f"U{uid}", "level": 10, "survival_rate": 100, "gold": 1000, "cls": None, "registered": True}
    d.update(kw)
    return d


class FakeMsg:
    def __init__(self, uid, target=None, group=True):
        self.from_user = types.SimpleNamespace(id=uid, full_name=f"U{uid}", is_bot=False)
        self.reply_to_message = None
        if target is not None:
            self.reply_to_message = types.SimpleNamespace(from_user=types.SimpleNamespace(id=target, full_name=f"U{target}", is_bot=False))
        self.group = group
        self.out = []

    async def reply(self, text, reply_markup=None):
        self.out.append(text)


def _load():
    state = types.SimpleNamespace(users=Users(), bounties=Coll(), ledger=[], burned=0, says=[])
    store = types.SimpleNamespace(users=state.users, bounties=state.bounties)

    async def get(uid):
        d = state.users.docs.get(uid)
        return copy.deepcopy(d) if d else None

    async def touch(u):
        return True

    store.get, store.touch = get, touch

    eco = types.ModuleType("economy")
    locks = {}
    eco.ulock = lambda uid: locks.setdefault(uid, asyncio.Lock())

    async def debit(uid, amount, reason="", burn_it=True):
        d = state.users.docs[uid]
        if amount <= 0:
            return True
        if d["gold"] < amount:
            return False
        d["gold"] -= amount
        state.ledger.append((uid, -amount, reason))
        if burn_it:
            state.burned += amount
        return True

    async def credit(uid, amount, reason=""):
        if amount > 0:
            state.users.docs[uid]["gold"] += amount
            state.ledger.append((uid, amount, reason))

    async def burn(amount, reason=""):
        state.burned += max(0, amount)

    async def terr_perks(doc):
        return set()

    eco.debit, eco.credit, eco.burn, eco.terr_perks = debit, credit, burn, terr_perks

    pl = types.ModuleType("players")

    async def adjust_survival(uid, delta, counter=None):
        d = state.users.docs[uid]
        d["survival_rate"] = min(100, max(1, d["survival_rate"] + delta))
        return copy.deepcopy(d)

    async def grant(uid, gold=0, xp=0, item=None, survival=0):
        state.users.docs[uid]["xp"] = state.users.docs[uid].get("xp", 0) + xp
        return copy.deepcopy(state.users.docs[uid]), False

    pl.adjust_survival, pl.grant = adjust_survival, grant

    ui = types.ModuleType("ui")
    ui.panel = lambda color, icon, title, lines, foot=None: title + "|" + "|".join(lines)
    ui.hp_bar = lambda r: "#" * (r // 10)

    async def say(m, text, icon="", title="", color=""):
        state.says.append(text)
        m.out.append(text)

    ui.say = say
    rd = types.ModuleType("render")
    rd.display = lambda doc, link=False: f"<{doc['first_name']}>"
    ut = types.ModuleType("utils")
    ut.esc = lambda s: str(s)
    ut.is_group = lambda m: m.group
    ut.utcnow = datetime.utcnow
    ut.day_key = lambda: "2026-11-07"
    rules = types.ModuleType("rules")
    rules.echo_charges = lambda n: 0
    rules.gear_bonus = lambda item: 0
    pg = types.ModuleType("procgen")
    pg.effect_total = lambda d, k: 0
    db = types.ModuleType("database")
    db.store = store
    stubs = {"economy": eco, "players": pl, "ui": ui, "render": rd, "utils": ut, "rules": rules, "procgen": pg, "database": db}
    p = mock.patch.dict(sys.modules, stubs)
    p.start()
    for m in ("config", "npcreply", "battle_engine", "skirmish"):
        sys.modules.pop(m, None)
    import skirmish
    return skirmish, state, p


class Base(unittest.TestCase):
    def setUp(self):
        self.S, self.st, p = _load()
        self.addCleanup(p.stop)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.st.users.docs[1] = _user(1)
        self.st.users.docs[2] = _user(2)
        self.now = [1_000_000.0]
        pt = mock.patch.object(self.S.time, "time", lambda: self.now[0])
        pt.start()
        self.addCleanup(pt.stop)

    def run_cmd(self, text, uid=1, target=2, group=True, win=None, rnd=None):
        m = FakeMsg(uid, target, group)
        ctx = []
        if win is not None:
            ctx.append(mock.patch.object(self.S, "run_ai", lambda fa, fb, first=0: 0 if win else 1))
        if rnd is not None:
            ctx.append(mock.patch.object(self.S.random, "random", lambda: rnd))
        for c in ctx:
            c.start()
        try:
            handled = self.loop.run_until_complete(self.S.do_skirmish(m, text))
        finally:
            for c in ctx:
                c.stop()
        return handled, m

    def u(self, uid):
        return self.st.users.docs[uid]


class TestParsing(Base):
    def test_matches(self):
        for t in ("حمله", "حمله کن!", "بزنش", "دزدی", "جیب‌بری", "ترمیم", "هدیه ۵۰", "هدیه 50 GS", "جایزه روی سرش ۱۰۰",
                  "جایزه سر ۲۰۰", "جایزه‌ها", "جاسوسی", "حالت جنگ", "حالت صلح"):
            self.assertTrue(self.S.matches(t), t)
        for t in ("سلام", "حمله به باس", "ترمیم کردی؟", "هدیه", "جایزه"):
            self.assertFalse(self.S.matches(t), t)

    def test_needs_group_and_reply(self):
        handled, m = self.run_cmd("حمله", group=False)
        self.assertTrue(handled)
        self.assertIn("فقط تو گروه", m.out[-1])
        handled, m = self.run_cmd("حمله", target=None)
        self.assertIn("ریپلای", m.out[-1])

    def test_unrelated_text_not_handled(self):
        self.assertFalse(self.run_cmd("امروز هوا خوبه")[0])


class TestAttack(Base):
    def test_win_applies_bounded_effects(self):
        _, m = self.run_cmd("حمله", win=True)
        t, a = self.u(2), self.u(1)
        self.assertTrue(3 <= 100 - t["survival_rate"] <= 15)
        looted = a["gold"] - 1000
        self.assertTrue(0 <= looted <= 20)                      # غیرِ جنگ: سقف ۲۰
        self.assertEqual(t["gold"], 1000 - looted)              # انتقال: هیچ GS ساخته/سوخته نشد
        self.assertGreater(t["sk_shield"], self.now[0])
        self.assertIn("1", t["sk_rev"])                         # قربانی حق انتقام گرفت
        self.assertEqual(a["sk_charges"], 2)
        self.assertEqual(a["sk_wins"], 1)
        self.assertIn("پیروز", m.out[-1])

    def test_loss_hurts_attacker_only(self):
        self.run_cmd("حمله", win=False)
        self.assertEqual(self.u(2)["survival_rate"], 100)
        self.assertEqual(self.u(2)["gold"], 1000)
        self.assertTrue(3 <= 100 - self.u(1)["survival_rate"] <= 8)
        self.assertNotIn("sk_shield", self.u(2))

    def test_war_mode_target_has_higher_loot_cap(self):
        self.u(2).update(gold=5000, sk_war=True)
        self.run_cmd("حمله", win=True)
        self.assertEqual(self.u(1)["gold"] - 1000, 60)
        self.u(1).update(gold=1000, sk_charges=3)
        self.st.users.docs[3] = _user(3, gold=5000)
        self.run_cmd("حمله", target=3, win=True)
        self.assertEqual(self.u(1)["gold"] - 1000, 20)

    def test_victim_never_looted_below_floor(self):
        self.u(2).update(gold=50)
        self.run_cmd("حمله", win=True)
        self.assertEqual(self.u(2)["gold"], 50)
        self.st.users.docs[3] = _user(3, gold=70)
        self.run_cmd("حمله", target=3, win=True)
        self.assertGreaterEqual(self.u(3)["gold"], 50)

    def test_survival_floor_respected(self):
        self.u(2)["survival_rate"] = 6
        self.run_cmd("حمله", win=True)
        self.assertGreaterEqual(self.u(2)["survival_rate"], self.S.SURV_FLOOR)

    def test_protected_target_untouched_and_no_charge_spent(self):
        self.u(2)["opted_out"] = True
        _, m = self.run_cmd("حمله", win=True)
        self.assertIn("محافظت", m.out[-1])
        self.assertNotIn("sk_charges", self.u(1))
        self.assertEqual(self.u(2)["survival_rate"], 100)

    def test_attacker_protected_cannot_attack(self):
        self.u(1)["opted_out"] = True
        _, m = self.run_cmd("حمله", win=True)
        self.assertIn("برگردم به بازی", m.out[-1])

    def test_low_level_and_level_gap_refused(self):
        self.u(2)["level"] = 2
        self.assertIn("تحت حمایت", self.run_cmd("حمله", win=True)[1].out[-1])
        self.u(2)["level"] = 3
        self.u(1)["level"] = 20
        self.assertIn("زورگویی", self.run_cmd("حمله", win=True)[1].out[-1])
        self.assertEqual(self.u(2)["survival_rate"], 100)

    def test_charges_run_out_then_regenerate(self):
        for uid in (3, 4, 5, 6):
            self.st.users.docs[uid] = _user(uid)
        for uid in (3, 4, 5):
            self.run_cmd("حمله", target=uid, win=False)
        self.assertEqual(self.u(1)["sk_charges"], 0)
        _, m = self.run_cmd("حمله", target=6, win=False)
        self.assertIn("شارژِ حمله نداری", m.out[-1])
        self.now[0] += 21 * 60
        self.run_cmd("حمله", target=6, win=False)
        self.assertEqual(self.u(1)["sk_losses"], 4)

    def test_pair_cooldown_then_revenge_bypass(self):
        self.run_cmd("حمله", win=False)
        _, m = self.run_cmd("حمله", win=False)
        self.assertIn("تازه حمله کردی", m.out[-1])
        self.u(1)["sk_rev"] = {"2": self.now[0] + 1000}        # توکنِ انتقام
        self.run_cmd("حمله", win=True)
        self.assertEqual(self.u(1)["sk_wins"], 1)
        self.assertNotIn("2", self.u(1).get("sk_rev", {}))     # مصرف شد

    def test_shield_blocks_next_attacker_until_it_expires(self):
        self.st.users.docs[3] = _user(3)
        self.run_cmd("حمله", win=True)
        _, m = self.run_cmd("حمله", uid=3, target=2, win=True)
        self.assertIn("نفس می‌گیره", m.out[-1])
        self.now[0] += 21 * 60
        self.run_cmd("حمله", uid=3, target=2, win=True)
        self.assertEqual(self.u(3)["sk_wins"], 1)

    def test_real_engine_smoke_strong_beats_weak(self):
        self.u(1).update(level=30)
        self.u(2).update(level=22)
        wins = 0
        for _ in range(5):
            self.u(1).pop("sk_charges", None)
            self.u(1).pop("sk_pair", None)
            self.u(2).pop("sk_shield", None)
            self.u(2).update(survival_rate=100)
            self.run_cmd("حمله")
            wins = self.u(1).get("sk_wins", 0)
        self.assertGreaterEqual(wins, 1)


class TestOthers(Base):
    def test_steal_success_bounded(self):
        _, m = self.run_cmd("دزدی", rnd=0.0)
        got = self.u(1)["gold"] - 1000
        self.assertTrue(0 < got <= 25)
        self.assertEqual(self.u(2)["gold"], 1000 - got)
        _, m = self.run_cmd("دزدی", rnd=0.0)
        self.assertIn("هنوز داغه", m.out[-1])

    def test_steal_fail_pays_fine_and_gives_revenge(self):
        self.run_cmd("دزدی", rnd=0.99)
        self.assertEqual(self.u(1)["gold"], 990)
        self.assertEqual(self.u(2)["gold"], 1010)
        self.assertIn("1", self.u(2)["sk_rev"])

    def test_steal_never_below_floor_and_respects_protection(self):
        self.u(2)["gold"] = 50
        self.run_cmd("دزدی", rnd=0.0)
        self.assertEqual(self.u(2)["gold"], 50)
        self.u(2).update(opted_out=True, gold=1000)
        self.run_cmd("دزدی", rnd=0.0)
        self.assertEqual(self.u(2)["gold"], 1000)

    def test_heal_costs_gold_and_is_limited(self):
        self.u(2)["survival_rate"] = 50
        self.run_cmd("ترمیم")
        self.assertTrue(56 <= self.u(2)["survival_rate"] <= 62)
        self.assertEqual(self.u(1)["gold"], 992)
        _, m = self.run_cmd("ترمیم")
        self.assertIn("خسته", m.out[-1])
        for _ in range(6):
            self.now[0] += 11 * 60
            self.u(2)["survival_rate"] = 50
            self.run_cmd("ترمیم")
        self.assertIn("فردا", self.st.says[-1])

    def test_heal_refused_without_gold_or_when_healthy(self):
        self.u(2)["survival_rate"] = 98
        self.assertIn("سالمِ", self.run_cmd("ترمیم")[1].out[-1])
        self.u(2)["survival_rate"] = 40
        self.u(1)["gold"] = 3
        self.assertIn("نداری", self.run_cmd("ترمیم")[1].out[-1])

    def test_gift_fee_burned_and_limits(self):
        self.run_cmd("هدیه ۱۰۰")
        self.assertEqual(self.u(1)["gold"], 900)
        self.assertEqual(self.u(2)["gold"], 1095)
        self.assertEqual(self.st.burned, 5)
        self.assertIn("بین", self.run_cmd("هدیه ۵")[1].out[-1])
        self.u(1)["gold"] = 5000
        for _ in range(10):
            self.run_cmd("هدیه ۱۰۰")
        self.assertIn("سقفِ هدیه", self.st.says[-1])

    def test_bounty_escrow_claim_and_fee(self):
        self.st.users.docs[3] = _user(3)
        self.run_cmd("جایزه روی سرش ۱۰۰", uid=3, target=2)
        self.assertEqual(self.u(3)["gold"], 900)
        self.run_cmd("حمله", win=True)
        looted = self.u(1)["gold"] - 1000
        self.assertGreaterEqual(self.u(1)["gold"], 1000 + 90)          # ۹۰٪ جایزه رسید (+ غارتِ احتمالی)
        self.assertEqual(self.st.bounties.docs[0]["status"], "claimed")
        self.assertEqual(self.st.burned, 10)

    def test_placer_cannot_claim_own_bounty_and_expiry_refunds(self):
        self.run_cmd("جایزه روی سرش ۱۰۰", uid=1, target=2)
        self.u(1)["sk_charges"] = 3
        self.run_cmd("حمله", win=True)
        self.assertEqual(self.st.bounties.docs[0]["status"], "open")
        self.st.bounties.docs[0]["expires_at"] = datetime.utcnow() - timedelta(minutes=1)
        self.loop.run_until_complete(self.S._expire_bounties())
        self.assertEqual(self.st.bounties.docs[0]["status"], "expired")
        self.assertGreaterEqual(self.u(1)["gold"], 1000 - 0)   # ۱۰۰ برگشت (به‌علاوه‌ی غارت)

    def test_bounty_rules(self):
        self.assertIn("بین", self.run_cmd("جایزه سر ۵")[1].out[-1])
        self.u(2)["opted_out"] = True
        self.assertIn("محافظت", self.run_cmd("جایزه سر ۱۰۰")[1].out[-1])
        self.assertEqual(self.st.bounties.docs, [])
        self.u(2)["opted_out"] = False
        for _ in range(3):
            self.run_cmd("جایزه سر ۴۰۰")
        self.assertEqual(sum(b["amount"] for b in self.st.bounties.docs), 800)       # سومی از سقف ۱۰۰۰ رد شد؟ (۴۰۰×۳=۱۲۰۰)
        self.assertIn("کافی", self.st.says[-1])

    def test_spy_costs_gold_hides_exact_wealth_and_respects_protection(self):
        self.u(2)["gold"] = 1234
        _, m = self.run_cmd("جاسوسی")
        self.assertEqual(self.u(1)["gold"], 995)
        self.assertNotIn("1234", m.out[-1])
        self.assertIn("پولدار", m.out[-1])
        self.u(2)["opted_out"] = True
        self.now[0] += 60
        self.assertIn("محافظت", self.run_cmd("جاسوسی")[1].out[-1])

    def test_war_mode_toggle_with_minimum_duration(self):
        self.run_cmd("حالت جنگ", target=None)
        self.assertTrue(self.u(1)["sk_war"])
        _, m = self.run_cmd("حالت صلح", target=None)
        self.assertIn("هنوز نمی‌تونی", m.out[-1])
        self.now[0] += 2 * 3600 + 1
        self.run_cmd("حالت صلح", target=None)
        self.assertFalse(self.u(1)["sk_war"])

    def test_bounty_list(self):
        self.run_cmd("جایزه سر ۱۰۰")
        _, m = self.run_cmd("جایزه‌ها", target=None)
        self.assertIn("100", m.out[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
