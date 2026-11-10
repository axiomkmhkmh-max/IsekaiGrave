"""🌍 موتورِ دنیای زنده: ساعت، روتینِ NPCها، سفر، تعاملِ NPC↔NPC، اقتصاد، شایعه، رویداد و پایداری.

اصل: شبیه‌سازیِ عادی کاملاً پایتونیه (ارزون، قطعی، بدون AI). AI فقط برای تصمیم‌های مهمِ چند NPC در هر تیک
(با بودجه‌ی WORLD_AI_DECISIONS_PER_TICK) و متنِ رویدادهای بزرگ استفاده میشه و اگه در دسترس نبود، قاعده‌ی پایتونی جاش رو می‌گیره.
هیچ‌جای این فایل GS/آیتم‌ی بازیکن رو مستقیم دست نمی‌زنه؛ جایزه‌ی رویدادها فقط از players.grant (با سقفِ روزانه) میره.
"""

import asyncio
import random
import time
import uuid
from typing import Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import aiclient
import worlddata as WD
from aiclient import clean_text
from config import (
    WORLD_AI_DECISIONS_PER_TICK, WORLD_ANNOUNCE_GROUPS, WORLD_EVENT_CHANCE, WORLD_EVENT_MAX_ACTIVE,
    WORLD_MAX_CATCHUP, WORLD_TICK_SECONDS, WORLD_TIME_SCALE, log,
)
from database import store

TICK = WORLD_TICK_SECONDS
_bot = None
_bg: set = set()
_cache = {"t": 0.0, "w": None, "events": []}
_npc_cache: dict = {}          # id -> {"name","icon"}  (برای ساختِ دکمه‌ها بدون DB)
OWNED_FIELDS = ("location", "travel", "emotion", "plan", "goals", "relationships", "bonds", "memories", "summary",
                "known_rumors", "gold", "cargo", "override_to", "override_until", "decision_due")


def spawn(coro):
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)
    return t


# ───────────────────────────── راه‌اندازی ─────────────────────────────
async def ensure_world():
    """ساخت/تکمیلِ حالتِ دنیا و NPCها (idempotent؛ NPCِ جدید تو آپدیت‌های بعدی هم خودکار اضافه میشه)."""
    now = time.time()
    rng = random.Random()
    if not await store.meta.find_one({"_id": "world"}):
        w = {
            "_id": "world", "epoch": now, "last_tick": 0, "tick_n": 0,
            "regions": {r: {"danger": 50, "prosperity": 50} for r in WD.REGIONS},
            "factions": {k: dict(v) for k, v in WD.FACTIONS.items()},
            "frel": {WD.rel_key(a, b): v for (a, b), v in WD.FACTION_RELATIONS.items()},
            "economy": WD.initial_economy(rng), "rumors": [], "news": [],
        }
        try:
            await store.meta.insert_one(w)
        except DuplicateKeyError:
            pass
    w = await store.meta.find_one({"_id": "world"})
    phase = WD.world_clock(now, w["epoch"], WORLD_TIME_SCALE)["phase"]
    for seed in WD.NPC_SEEDS:
        doc = dict(seed)
        doc["location"] = doc["routine"][phase]
        await store.wnpcs.update_one({"id": seed["id"]}, {"$setOnInsert": doc}, upsert=True)
    await refresh_npc_cache()


async def refresh_npc_cache():
    async for n in store.wnpcs.find({}, {"id": 1, "name": 1, "icon": 1}):
        _npc_cache[n["id"]] = {"name": n["name"], "icon": n["icon"]}


def npc_label(npc_id: str) -> tuple:
    c = _npc_cache.get(npc_id)
    return (c["name"], c["icon"]) if c else (npc_id, "🧑")


# ───────────────────────────── خواندنِ حالتِ دنیا (با کش) ─────────────────────────────
async def get_world(force: bool = False) -> Optional[dict]:
    if force or time.time() - _cache["t"] > 20 or _cache["w"] is None:
        _cache["w"] = await store.meta.find_one({"_id": "world"})
        _cache["events"] = await store.wevents.find({"status": "active"}).to_list(30)
        _cache["t"] = time.time()
    return _cache["w"]


async def active_events(region: Optional[str] = None) -> list:
    await get_world()
    evs = _cache["events"]
    return [e for e in evs if region is None or e["region"] == region]


async def clock_now() -> dict:
    w = await get_world()
    return WD.world_clock(time.time(), w["epoch"] if w else time.time(), WORLD_TIME_SCALE)


# ───────────────────────────── کمک‌ها: حافظه، شایعه، خبر ─────────────────────────────
def add_memory(n: dict, text: str, now: float):
    mem = n.setdefault("memories", [])
    mem.append({"t": int(now), "x": clean_text(text, 140)})
    cap = 14 if n.get("important") else 5
    while len(mem) > cap:                     # حافظه‌ی قدیمی → خلاصه (سبک)
        old = mem.pop(0)
        n["summary"] = ((n.get("summary") or "") + " | " + old["x"])[-380:]


def add_rumor(ctx: dict, text: str, region: Optional[str], holders: list, about: Optional[int] = None, key: Optional[str] = None):
    rumors = ctx["w"].setdefault("rumors", [])
    if key and any(r.get("key") == key for r in rumors):
        return
    rumors.append({"id": uuid.uuid4().hex[:6], "text": clean_text(text, 160), "region": region, "born": ctx["now"],
                   "ttl": random.randint(24, 48) * 3600, "holders": list(holders), "about": about, "key": key})
    del rumors[:-25]


def add_news(ctx: dict, text: str, region: Optional[str] = None):
    news = ctx["w"].setdefault("news", [])
    news.append({"t": ctx["now"], "text": clean_text(text, 160), "region": region})
    del news[:-20]


def rel_change(a: dict, b: dict, d: int):
    for x, y in ((a, b), (b, a)):
        x["relationships"][y["id"]] = max(-100, min(100, x["relationships"].get(y["id"], 0) + d))


def start_travel(ctx: dict, n: dict, dest: str):
    if dest == n["location"] or dest not in WD.REGIONS:
        return
    n["travel"] = {"from": n["location"], "to": dest, "arrive": ctx["now"] + TICK * random.randint(1, 2)}
    n["location"] = WD.ROAD


# ───────────────────────────── گام‌های شبیه‌سازی (همگی همگام/سبک) ─────────────────────────────
def step_movement(ctx: dict):
    now, phase = ctx["now"], ctx["clock"]["phase"]
    for n in ctx["npcs"].values():
        tr = n.get("travel")
        if tr:
            if now >= tr["arrive"]:
                n["location"], n["travel"] = tr["to"], None
                ctx["dirty"].add(n["id"])
            continue
        if n.get("trader") and n.get("cargo"):
            continue
        target = n["override_to"] if (n.get("override_until") or 0) > now and n.get("override_to") else n["routine"][phase]
        if target != n["location"] and random.random() < 0.85:
            start_travel(ctx, n, target)
            ctx["dirty"].add(n["id"])


def step_interactions(ctx: dict):
    by_loc: dict = {}
    for n in ctx["npcs"].values():
        if n["location"] in WD.REGIONS:
            by_loc.setdefault(n["location"], []).append(n)
    pairs = []
    for loc, lst in by_loc.items():
        if len(lst) >= 2:
            random.shuffle(lst)
            pairs += [(loc, lst[i], lst[i + 1]) for i in range(0, len(lst) - 1, 2)]
    random.shuffle(pairs)
    for loc, a, b in pairs[:4]:
        frel = ctx["w"]["frel"].get(WD.rel_key(a["faction"], b["faction"]), 0)
        it = WD.pick_interaction(a, b, frel, random)
        if not it:
            continue
        rel_change(a, b, it["delta"])
        for x, y in ((a, b), (b, a)):
            add_memory(x, it["text"], ctx["now"])
        ctx["dirty"].update((a["id"], b["id"]))
        k = it["kind"]
        if k == "trade":
            ore = ctx["w"]["economy"]["supply"][loc]
            ore["ore"] = WD.clamp_supply(ore["ore"] + it.get("ore", 0))
        elif k == "hire":
            adv, mer = (a, b) if a["occupation"] == "adventurer" else (b, a)
            dest = random.choice([r for r in WD.REGIONS if r != loc])
            adv["override_to"], adv["override_until"] = dest, ctx["now"] + TICK * 4
            add_news(ctx, it["text"], loc)
        elif k == "help":
            add_news(ctx, it["text"], loc)
            ctx["spawn_event_at"] = loc if random.random() < 0.25 else ctx.get("spawn_event_at")
        elif k == "romance":
            a["bonds"][b["id"]] = b["bonds"][a["id"]] = "lovers"
            add_news(ctx, it["text"], loc)
        elif k == "alliance":
            key = WD.rel_key(a["faction"], b["faction"])
            ctx["w"]["frel"][key] = min(100, ctx["w"]["frel"].get(key, 0) + 5)
            add_news(ctx, it["text"], loc)
        elif k == "argue" and it["rumor"]:
            add_news(ctx, it["text"], loc)
        if it["rumor"]:
            add_rumor(ctx, it["text"], loc, [a["id"], b["id"]])
        # پخشِ شایعه بینِ دو NPCِ هم‌مکان
        for r in ctx["w"].get("rumors", []):
            for x, y in ((a, b), (b, a)):
                if x["id"] in r["holders"] and y["id"] not in r["holders"] and random.random() < 0.5:
                    r["holders"].append(y["id"])


def step_economy(ctx: dict):
    eco = ctx["w"]["economy"]
    sup, bias = eco["supply"], eco["bias"]
    for r in WD.REGIONS:                                   # بازگشت به میانگین + نویز
        for k in WD.RESOURCES:
            s = sup[r][k]
            sup[r][k] = WD.clamp_supply(s + (100 - s) * 0.04 + random.uniform(-2, 2))
    for n in ctx["npcs"].values():
        if not n.get("trader") or n["location"] not in WD.REGIONS:
            continue
        loc = n["location"]
        if n.get("cargo"):                                 # فروش
            res, qty = next(iter(n["cargo"].items()))
            pm = WD.price_mult(sup[loc][res], bias[loc][res])
            n["gold"] = min(900, n.get("gold", 0) + int(qty * 8 * pm))
            sup[loc][res] = WD.clamp_supply(sup[loc][res] + qty)
            n["cargo"] = {}
            if pm >= 1.3:
                add_rumor(ctx, f"{n['name']} تو {WD.REGION_FA[loc]} {WD.RESOURCES[res]} رو گرون فروخت؛ می‌گن اونجا کمیابه.", loc, [n["id"]], key=f"sell-{loc}-{res}")
        else:                                              # خرید از جاییکه فراوونه + حرکت به گرون‌ترین بازار
            res = max(WD.RESOURCES, key=lambda k: sup[loc][k])
            qty = random.randint(4, 10)
            cost = int(qty * 8 * WD.price_mult(sup[loc][res], bias[loc][res]))
            if sup[loc][res] > 105 and n.get("gold", 0) >= cost + 50:
                n["gold"] -= cost
                sup[loc][res] = WD.clamp_supply(sup[loc][res] - qty)
                n["cargo"] = {res: qty}
                dest = max((r for r in WD.REGIONS if r != loc), key=lambda r: WD.price_mult(sup[r][res], bias[r][res]))
                start_travel(ctx, n, dest)
            elif n.get("gold", 0) < 120:
                n["gold"] = n.get("gold", 0) + 25          # درآمدِ جانبیِ ثابت (NPC هیچ‌وقت ورشکسته‌ی دائم نمیشه)
        ctx["dirty"].add(n["id"])
    for r in WD.REGIONS:                                   # شایعه‌ی اقتصادی برای قیمت‌های غیرعادی
        for k in WD.RESOURCES:
            pm = WD.price_mult(sup[r][k], bias[r][k])
            if pm >= 1.5:
                add_rumor(ctx, f"{WD.RESOURCES[k]} تو {WD.REGION_FA[r]} کمیاب و گرون شده.", r, [], key=f"scarce-{r}-{k}")
            elif pm <= 0.8:
                add_rumor(ctx, f"{WD.RESOURCES[k]} تو {WD.REGION_FA[r]} ارزون و فراوونه.", r, [], key=f"cheap-{r}-{k}")
    for rg in ctx["w"]["regions"].values():                # آرام‌آرام برگشت به حالت نرمال
        rg["danger"] = int(rg["danger"] + (50 - rg["danger"]) * 0.03)
        rg["prosperity"] = int(rg["prosperity"] + (50 - rg["prosperity"]) * 0.03)


def step_rumors(ctx: dict):
    w = ctx["w"]
    w["rumors"] = [r for r in w.get("rumors", []) if ctx["now"] < r["born"] + r["ttl"]]


def step_player_rumor(ctx: dict, name_of: dict):
    """NPCهای مهم گاهی درباره‌ی بازیکنی که نظرشون نسبت بهش شدیده شایعه می‌سازن."""
    for n in ctx["npcs"].values():
        if not n.get("important") or random.random() > 0.04:
            continue
        strong = [(u, o["score"]) for u, o in (n.get("opinions") or {}).items() if abs(o.get("score", 0)) >= 30]
        if not strong:
            continue
        uid_s, score = random.choice(strong)
        nm = name_of.get(int(uid_s))
        if not nm:
            continue
        text = (f"{n['name']} می‌گه «{nm}» آدمِ قابل‌اعتمادیه." if score > 0 else f"{n['name']} از «{nm}» دل خوشی نداره.")
        add_rumor(ctx, text, n["location"] if n["location"] in WD.REGIONS else None, [n["id"]], about=int(uid_s), key=f"p-{n['id']}-{uid_s}")


# ───────────────────────────── تصمیم‌های NPC (AI + fallback) ─────────────────────────────
DECISION_ACTIONS = ("travel", "rumor", "befriend", "argue", "plan", "help_request")


async def ai_decision(ctx: dict, n: dict) -> Optional[dict]:
    if not aiclient.ai_available():
        return None
    rels = sorted(n["relationships"].items(), key=lambda kv: -abs(kv[1]))[:3]
    state = {
        "npc": {"id": n["id"], "name": n["name"], "occupation": n["occupation"], "traits": n["personality"]["traits"],
                "goals": n["goals"], "plan": n["plan"], "emotion": n["emotion"], "location": n["location"], "faction": n["faction"],
                "memory": (n.get("summary") or "")[-160:] + " ; " + " ; ".join(m["x"] for m in n["memories"][-2:]),
                "relationships": dict(rels)},
        "regions": ctx["w"]["regions"], "events": [e["title"] for e in ctx.get("events", [])][:3],
        "valid_regions": WD.REGIONS, "valid_npc_ids": [i for i in ctx["npcs"] if i != n["id"]], "valid_factions": list(WD.FACTIONS),
    }
    import json
    msgs = [
        {"role": "system", "content": (
            "You decide the next action of one fantasy RPG NPC. Reply with ONLY one JSON object: "
            '{"action": "travel|rumor|befriend|argue|plan|help_request", "target": "<region/npc id/faction id or empty>", '
            '"text": "<Persian, max 100 chars, or empty>", "emotion": "<one Persian word>"}. '
            "travel->target is a region; befriend/argue->target is an npc id; help_request->target is a faction id; "
            "rumor/plan->text is Persian. Stay consistent with the NPC's personality and goals. "
            "Never mention money, items, rewards or game rules.")},
        {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
    ]
    d = await aiclient.ask_json(msgs, max_tokens=160, temperature=0.8)
    return validate_decision(d, ctx, n)


def validate_decision(d, ctx: dict, n: dict) -> Optional[dict]:
    if not isinstance(d, dict) or d.get("action") not in DECISION_ACTIONS:
        return None
    a, t = d["action"], str(d.get("target") or "")
    if a == "travel" and t not in WD.REGIONS:
        return None
    if a in ("befriend", "argue") and (t not in ctx["npcs"] or t == n["id"]):
        return None
    if a == "help_request" and t not in WD.FACTIONS:
        return None
    text = clean_text(d.get("text"), 100)
    if a in ("rumor", "plan") and len(text) < 6:
        return None
    return {"action": a, "target": t, "text": text, "emotion": clean_text(d.get("emotion"), 20) or n["emotion"], "ai": True}


def rule_decision(ctx: dict, n: dict) -> dict:
    """تصمیمِ پایتونی (وقتی AI خاموشه یا بودجه تموم شده)."""
    others = [o for o in ctx["npcs"].values() if o["id"] != n["id"]]
    rival = [o for o in others if n["relationships"].get(o["id"], 0) <= -25]
    friend = [o for o in others if n["relationships"].get(o["id"], 0) >= 10]
    roll = random.random()
    if roll < 0.28:
        return {"action": "travel", "target": random.choice([r for r in WD.REGIONS if r != n["location"]]), "text": "", "emotion": n["emotion"]}
    if roll < 0.45 and ctx.get("events"):
        ev = random.choice(ctx["events"])
        return {"action": "rumor", "target": "", "text": f"{n['name']} می‌گه درباره‌ی «{ev['title']}» باید کاری کرد.", "emotion": "نگران"}
    if roll < 0.65 and friend:
        return {"action": "befriend", "target": random.choice(friend)["id"], "text": "", "emotion": "شاد"}
    if roll < 0.78 and rival:
        return {"action": "argue", "target": random.choice(rival)["id"], "text": "", "emotion": "عصبی"}
    if roll < 0.9:
        return {"action": "plan", "target": "", "text": random.choice(n["goals"]), "emotion": n["emotion"]}
    return {"action": "help_request", "target": random.choice(list(WD.FACTIONS)), "text": "", "emotion": "نگران"}


def apply_decision(ctx: dict, n: dict, act: dict):
    a, t, now = act["action"], act["target"], ctx["now"]
    n["emotion"] = act.get("emotion") or n["emotion"]
    if a == "travel":
        n["override_to"], n["override_until"] = t, now + TICK * 4
        add_memory(n, f"تصمیم گرفت به {WD.REGION_FA[t]} بره.", now)
    elif a == "rumor":
        add_rumor(ctx, act["text"], n["location"] if n["location"] in WD.REGIONS else None, [n["id"]])
        add_memory(n, f"شایعه‌ای پخش کرد: {act['text']}", now)
    elif a in ("befriend", "argue"):
        o = ctx["npcs"][t]
        rel_change(n, o, 8 if a == "befriend" else -8)
        for x, y in ((n, o), (o, n)):
            add_memory(x, f"{'با' if a == 'befriend' else 'با'} {y['name']} {'دوست‌تر شد' if a == 'befriend' else 'درگیر شد'}.", now)
        ctx["dirty"].add(o["id"])
        if a == "argue":
            add_news(ctx, f"{n['name']} و {o['name']} با هم درگیر شدن.", n["location"] if n["location"] in WD.REGIONS else None)
    elif a == "plan":
        n["plan"] = act["text"]
        add_memory(n, f"نقشه‌ی تازه: {act['text']}", now)
    elif a == "help_request":
        key = WD.rel_key(n["faction"], t)
        if n["faction"] != t:
            ctx["w"]["frel"][key] = max(-100, min(100, ctx["w"]["frel"].get(key, 0) + 5))
        add_news(ctx, f"{n['name']} از {WD.FACTIONS[t]['name']} کمک خواست.", n["location"] if n["location"] in WD.REGIONS else None)
    ctx["dirty"].add(n["id"])


# ───────────────────────────── رویدادهای جهان ─────────────────────────────
async def announce(text: str):
    """اعلامِ رویدادهای بزرگ تو گروه‌های فعال (کم‌هزینه و بی‌خطا)."""
    if _bot is None or WORLD_ANNOUNCE_GROUPS <= 0:
        return
    from ui import panel
    try:
        groups = await store.groups.find({}).sort("activity", -1).limit(WORLD_ANNOUNCE_GROUPS).to_list(WORLD_ANNOUNCE_GROUPS)
    except Exception:
        return
    for g in groups:
        try:
            await _bot.send_message(g["chat_id"], panel("orange", "🌍", "خبرِ فوریِ ایسکا", [text], "🌐 برای جزئیات بنویسید «جهان»"))
        except Exception:
            pass
        await asyncio.sleep(0.1)


async def create_event(ctx: dict, etype: Optional[str] = None, region: Optional[str] = None) -> Optional[dict]:
    now = ctx["now"]
    active = ctx.get("events", [])
    busy = {(e["type"], e["region"]) for e in active}
    # Exactly one shared world boss may exist globally, never one per region/chat.
    if etype == "world_boss" and any(e.get("type") == "world_boss" for e in active):
        return None
    cands = []
    for k, t in WD.EVENT_TYPES.items():
        if etype and k != etype:
            continue
        if k == "world_boss" and any(e.get("type") == "world_boss" for e in active):
            continue
        for r in ([region] if region and region in t["regions"] else t["regions"]):
            if (k, r) in busy:
                continue
            w = t["w"]
            d = ctx["w"]["regions"][r]["danger"]
            if k in ("monster_migration", "regional_threat", "world_boss") and d > 60:
                w *= 1.5
            if k in ("prosperity", "rare_resource") and ctx["w"]["regions"][r]["prosperity"] > 60:
                w *= 1.4
            cands.append((k, r, w))
    if not cands:
        return None
    k, r, _ = random.choices(cands, weights=[c[2] for c in cands])[0]
    t = WD.EVENT_TYPES[k]
    diff = random.randint(*t["diff"])
    ev = {
        "id": uuid.uuid4().hex[:8], "type": k, "region": r, "icon": t["icon"],
        "title": t["title"].format(r=WD.REGION_FA[r]), "desc": t["desc"].format(r=WD.REGION_FA[r]),
        "started": now, "ends_at": now + random.randint(*t["hours"]) * 3600, "difficulty": diff,
        "target": WD.event_target(diff), "progress": 0, "reward": WD.event_reward(diff), "mods": t["mods"],
        "on_success": t["ok"], "on_fail": t["fail"], "power": t.get("power", {}), "participants": {},
        "boss_hp": WD.event_target(diff) if k == "world_boss" else None,
        "boss_max_hp": WD.event_target(diff) if k == "world_boss" else None,
        "status": "active", "history": [{"t": now, "text": "رویداد آغاز شد."}],
    }
    try:
        await store.wevents.insert_one(ev)
    except DuplicateKeyError:
        # Another worker created the one globally unique boss in the same tick.
        if k == "world_boss":
            return None
        raise
    from world_engine import record_event
    await record_event("world_event_started", f"{ev['icon']} رویداد جهانی «{ev['title']}» در {WD.REGION_FA[r]} آغاز شد.", source_id=f"wevent:{ev['id']}:start", region=r, importance=3)
    ctx.setdefault("events", []).append(ev)
    add_news(ctx, WD.NEWS_TEMPLATES["event_start"].format(icon=ev["icon"], title=ev["title"]), r)
    add_rumor(ctx, f"می‌گن {ev['title']}.", r, [], key=f"ev-{ev['id']}")
    for n in ctx["npcs"].values():                         # NPCهای همون منطقه واکنش نشون میدن
        if n["location"] == r:
            n["emotion"] = "نگران" if diff >= 3 else n["emotion"]
            if n.get("important"):
                n["plan"] = f"کمک به مقابله با «{ev['title']}»"
                add_memory(n, f"رویداد «{ev['title']}» شروع شد.", now)
            ctx["dirty"].add(n["id"])
    if diff >= 3:
        spawn(announce(f"{ev['icon']} <b>{ev['title']}</b>\n{ev['desc']}"))
        spawn(polish_event(ev["id"]))
    return ev


async def polish_event(event_id: str):
    """AI فقط عنوان/توضیحِ رویدادهای بزرگ رو قشنگ می‌کنه (مکانیک دست‌نخورده می‌مونه)."""
    if not aiclient.ai_available():
        return
    ev = await store.wevents.find_one({"id": event_id})
    if not ev:
        return
    msgs = [
        {"role": "system", "content": 'Rewrite the title and description of a fantasy RPG world event in vivid Persian. Reply ONLY JSON: {"title": "<max 50 chars>", "desc": "<max 140 chars>"}. Keep the same meaning. No numbers, no rewards.'},
        {"role": "user", "content": f"title: {ev['title']}\ndesc: {ev['desc']}\nregion: {WD.REGION_FA[ev['region']]}"},
    ]
    d = await aiclient.ask_json(msgs, max_tokens=150, temperature=0.9)
    if d:
        title, desc = clean_text(d.get("title"), 50), clean_text(d.get("desc"), 140)
        if len(title) >= 4 and len(desc) >= 10:
            await store.wevents.update_one({"id": event_id, "status": "active"}, {"$set": {"title": title, "desc": desc}})


async def resolve_event(ctx: dict, ev: dict):
    from players import grant           # import تنبل (جلوگیری از حلقه)
    from procgen import effect_total
    success = ev["progress"] >= ev["target"]
    won = await store.wevents.find_one_and_update(
        {"id": ev["id"], "status": "active"},
        {"$set": {"status": "success" if success else "failed", "resolved_at": ctx["now"]},
         "$push": {"history": {"t": ctx["now"], "text": "موفق" if success else "شکست/پایان زمان"}}})
    if not won:
        return
    ev["status"] = "success" if success else "failed"
    from world_engine import record_event
    participant_ids = [int(u) for u, p in (ev.get("participants") or {}).items() if int(p.get("score", 0)) > 0]
    await record_event(
        "world_event_resolved",
        f"رویداد جهانی «{ev['title']}» در {WD.REGION_FA[ev['region']]} {'با موفقیت مهار شد' if success else 'با شکست پایان یافت'}.",
        source_id=f"wevent:{ev['id']}:resolved", players=participant_ids, region=ev["region"],
        importance=4, consequence={"result": "success" if success else "failed", "progress": ev.get("progress", 0), "target": ev.get("target", 0)}
    )
    cons = ev["on_success"] if success else ev["on_fail"]
    rg = ctx["w"]["regions"][ev["region"]]
    rg["danger"] = max(0, min(100, rg["danger"] + cons.get("danger", 0)))
    rg["prosperity"] = max(0, min(100, rg["prosperity"] + cons.get("prosperity", 0)))
    for res, dv in (cons.get("supply") or {}).items():
        for reg in ([ev["region"]] if abs(dv) >= 15 else WD.REGIONS):
            cur = ctx["w"]["economy"]["supply"][reg][res]
            ctx["w"]["economy"]["supply"][reg][res] = WD.clamp_supply(cur + (dv if reg == ev["region"] else dv // 3))
    for fid, pv in (ev.get("power") or {}).items():
        f = ctx["w"]["factions"][fid]
        f["power"] = max(0, min(100, f["power"] + (pv if success else -pv)))
    tpl = WD.NEWS_TEMPLATES["event_ok" if success else "event_fail"]
    add_news(ctx, tpl.format(title=ev["title"]), ev["region"])
    for n in ctx["npcs"].values():
        if n["location"] == ev["region"]:
            n["emotion"] = "آسوده" if success else "نگران"
            add_memory(n, f"«{ev['title']}» {'با موفقیت مهار شد' if success else 'مهار نشد'}.", ctx["now"])
            ctx["dirty"].add(n["id"])
    mult = 1.0 if success else 0.3
    paid = 0
    for uid_s, p in list((ev.get("participants") or {}).items())[:60]:
        if p.get("score", 0) < 1:
            continue
        uid = int(uid_s)
        try:
            udoc = await store.get(uid)
            bonus = 1 + effect_total(udoc, "event_reward_pct") / 100
            gold = int(ev["reward"]["gold"] * mult * bonus)
            xp = int(ev["reward"]["xp"] * mult * bonus)
            await grant(uid, gold=gold, xp=xp)           # از مسیرِ معمولِ بازی (با سقفِ روزانه‌ی GS)
            paid += 1
            if _bot is not None and paid <= 30:
                await _bot.send_message(uid, f"{ev['icon']} رویداد «{ev['title']}» {'با کمکِ تو مهار شد!' if success else 'مهار نشد، ولی تلاشت دیده شد.'}\n🪙 +{gold} GS · ✨ +{xp} XP")
        except Exception:
            pass
        await asyncio.sleep(0.05)
    if ev["difficulty"] >= 3:
        spawn(announce(("✅ " if success else "❌ ") + f"<b>{ev['title']}</b> " + ("مهار شد!" if success else "مهار نشد!")))


async def step_events(ctx: dict):
    active = await store.wevents.find({"status": "active"}).to_list(30)
    ctx["events"] = active
    for ev in list(active):
        if ctx["now"] >= ev["ends_at"] or ev["progress"] >= ev["target"]:
            await resolve_event(ctx, ev)
    ctx["events"] = [e for e in active if e.get("status") == "active"]
    forced = ctx.pop("spawn_event_at", None)
    if len(ctx["events"]) < WORLD_EVENT_MAX_ACTIVE and (forced or random.random() < WORLD_EVENT_CHANCE):
        await create_event(ctx, region=forced)


# ───────────────────────────── تیک ─────────────────────────────
async def _run_tick(sim_now: float, use_ai: bool) -> bool:
    w0 = await store.meta.find_one_and_update(
        {"_id": "world", "last_tick": {"$lt": sim_now - TICK * 0.9}},
        {"$set": {"last_tick": sim_now}, "$inc": {"tick_n": 1}}, return_document=ReturnDocument.AFTER)
    if not w0:
        return False                                       # پردازشِ دیگه‌ای همین تیک رو گرفته
    clock = WD.world_clock(sim_now, w0["epoch"], WORLD_TIME_SCALE)

    # ۱) تصمیم‌های AI روی snapshot (await طولانی) — قبل از خوندنِ تازه‌ی NPCها تا آپدیتِ همزمانِ بازیکن‌ها گم نشه
    ai_acts: dict = {}
    if use_ai and aiclient.ai_available() and WORLD_AI_DECISIONS_PER_TICK > 0:
        snap = {n["id"]: n async for n in store.wnpcs.find({})}
        snap_ctx = {"w": w0, "npcs": snap, "events": await store.wevents.find({"status": "active"}).to_list(10)}
        due = [n for n in snap.values() if n.get("important") and (n.get("decision_due") or 0) <= sim_now and n["location"] != WD.ROAD]
        random.shuffle(due)
        for n in due[:WORLD_AI_DECISIONS_PER_TICK]:
            act = await ai_decision(snap_ctx, n)
            if act:
                ai_acts[n["id"]] = act

    # ۲) خوندنِ تازه و شبیه‌سازیِ همگام
    w = await store.meta.find_one({"_id": "world"})
    npcs = {n["id"]: n async for n in store.wnpcs.find({})}
    ctx = {"w": w, "npcs": npcs, "now": sim_now, "clock": clock, "dirty": set()}
    step_movement(ctx)
    step_interactions(ctx)
    step_economy(ctx)
    step_rumors(ctx)
    ctx["events"] = await store.wevents.find({"status": "active"}).to_list(30)
    for n in npcs.values():                                # تصمیم‌ها: AI اگه بود، وگرنه قاعده‌ی پایتونی
        if n.get("important") and (n.get("decision_due") or 0) <= sim_now and n["location"] != WD.ROAD:
            act = ai_acts.get(n["id"]) or rule_decision(ctx, n)
            apply_decision(ctx, n, act)
            n["decision_due"] = sim_now + random.randint(3600, 3 * 3600)
    uids = {int(u) for n in npcs.values() for u in (n.get("opinions") or {})}
    names = {}
    if uids:
        async for u in store.users.find({"user_id": {"$in": list(uids)[:100]}}, {"user_id": 1, "first_name": 1}):
            names[u["user_id"]] = clean_text(u.get("first_name"), 20)
    step_player_rumor(ctx, names)
    await step_events(ctx)

    # ۳) ذخیره (فقط فیلدهای متعلق به شبیه‌ساز؛ opinions/talk_log دست‌نخورده می‌مونن)
    for nid in ctx["dirty"]:
        n = npcs[nid]
        await store.wnpcs.update_one({"id": nid}, {"$set": {k: n[k] for k in OWNED_FIELDS if k in n}})
    await store.meta.update_one({"_id": "world"}, {"$set": {
        "regions": w["regions"], "factions": w["factions"], "frel": w["frel"], "economy": w["economy"],
        "rumors": w["rumors"], "news": w["news"], "clock": clock}})
    _cache["t"] = 0.0
    return True


async def world_tick():
    """چک می‌کنه چند تیک عقب‌ایم (مثلاً بعد از خاموشیِ ربات) و جبران می‌کنه؛ آخرین تیک اجازه‌ی AI داره."""
    w = await store.meta.find_one({"_id": "world"}, {"last_tick": 1})
    if not w:
        return
    now = time.time()
    last = w.get("last_tick", 0)
    missed = 1 if not last else int((now - last) // TICK)
    if missed <= 0:
        return
    steps = min(missed, WORLD_MAX_CATCHUP)
    for i in range(steps):
        sim_now = now if i == steps - 1 else (last + (i + 1) * TICK if last else now)
        await _run_tick(sim_now, use_ai=(i == steps - 1))


async def contribute_world_boss(uid: int) -> Optional[dict]:
    """Join the single shared boss from any Telegram chat; max five valid actions/player/event."""
    active = await store.wevents.find_one({"type": "world_boss", "status": "active"})
    if not active:
        return None
    key = f"participants.{int(uid)}"
    result = await store.wevents.find_one_and_update(
        {"id": active["id"], "type": "world_boss", "status": "active",
         "progress": {"$lt": active["target"]},
         "$or": [{f"{key}.actions": {"$lt": 5}}, {f"{key}.actions": {"$exists": False}}]},
        {"$inc": {"progress": 1, f"{key}.score": 1, f"{key}.actions": 1},
         "$set": {f"{key}.joined": time.time()}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        return None
    hp = max(0, int(result.get("target", 0)) - int(result.get("progress", 0)))
    await store.wevents.update_one({"id": result["id"], "status": "active"}, {"$set": {"boss_hp": hp}})
    _cache["t"] = 0.0
    return {"event": result, "hp": hp, "target": int(result.get("target", 0)),
            "actions": int((result.get("participants") or {}).get(str(uid), {}).get("actions", 0))}


async def world_loop(bot):
    global _bot
    _bot = bot
    try:
        await ensure_world()
    except Exception:
        log.exception("ensure_world failed")
    while True:
        try:
            await world_tick()
        except Exception:
            log.exception("world tick failed")
        await asyncio.sleep(max(15, TICK // 10))


# ───────────────────────────── هوک‌های گشت (خوانده میشن توسط exploration.py) ─────────────────────────────
async def explore_weights(biome: str, base: dict) -> dict:
    """وزنِ رخدادهای گشت رو با وضعیتِ منطقه و رویدادهای فعالش تنظیم می‌کنه. خطا = همون وزن‌ها."""
    try:
        w = await get_world()
        if not w:
            return base
        mult = WD.weight_multipliers(w["regions"].get(biome), await active_events(biome))
        return {k: v * mult.get(k, 1.0) for k, v in base.items()}
    except Exception:
        log.exception("explore_weights failed")
        return base


async def explore_after(uid: int, biome: str, died: bool) -> list:
    """مشارکت در رویدادهای فعالِ همین منطقه + خطِ وضعیتِ دنیا. هرگز گشت رو خراب نمی‌کنه."""
    lines = []
    try:
        w = await get_world()
        if not w:
            return lines
        c = WD.world_clock(time.time(), w["epoch"], WORLD_TIME_SCALE)
        evs = await active_events(biome)
        if not died:
            for ev in evs:
                key = f"participants.{uid}"
                # Contribution is globally shared but capped per player/event to prevent exploration farming.
                r = await store.wevents.find_one_and_update(
                    {"id": ev["id"], "status": "active", "progress": {"$lt": ev["target"]},
                     "$or": [{f"{key}.actions": {"$lt": 5}}, {f"{key}.actions": {"$exists": False}}]},
                    {"$inc": {"progress": 1, f"{key}.score": 1, f"{key}.actions": 1},
                     "$set": {f"{key}.joined": time.time()}},
                    return_document=ReturnDocument.AFTER)
                if r:
                    if ev.get("type") == "world_boss":
                        await store.wevents.update_one({"id": ev["id"], "status": "active"}, {"$set": {"boss_hp": max(0, int(r.get("target", 0)) - int(r.get("progress", 0)))}})
                    lines.append(f"{ev['icon']} به «{ev['title']}» کمک کردی ({min(r['progress'], r['target'])}/{r['target']})")
        if evs:
            _cache["t"] = 0.0
        lines.append(f"{c['icon']} {c['phase_fa']} · روز {c['day']} دنیا")
    except Exception:
        log.exception("explore_after failed")
    return lines


# ───────────────────────────── نظرِ NPC درباره‌ی بازیکن ─────────────────────────────
async def adjust_opinion(npc_id: str, uid: int, delta: int, note: Optional[str] = None):
    """نظرِ NPC نسبت به بازیکن (−۱۰۰..۱۰۰) + یادداشتِ کوتاه؛ $inc اتمیک و بعدش clamp."""
    key = f"opinions.{uid}"
    await store.wnpcs.update_one({"id": npc_id}, {"$inc": {f"{key}.score": delta}, "$set": {f"{key}.last": clean_text(note, 80)}})
    await store.wnpcs.update_one({"id": npc_id, f"{key}.score": {"$gt": 100}}, {"$set": {f"{key}.score": 100}})
    await store.wnpcs.update_one({"id": npc_id, f"{key}.score": {"$lt": -100}}, {"$set": {f"{key}.score": -100}})
    return await store.wnpcs.find_one({"id": npc_id})


def opinion_of(npc: dict, uid: int) -> int:
    return int(((npc.get("opinions") or {}).get(str(uid)) or {}).get("score", 0))
