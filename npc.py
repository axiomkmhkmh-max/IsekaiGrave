"""NPCهای زنده: برخورد وسط ماجراجویی، گفتگو، ماموریت‌های NPC و معامله."""

import random

from aiogram.types import Message
from pymongo import ReturnDocument

from config import GS, log, NPC_CITY_CHANCE, NPC_ENCOUNTER_CHANCE, WITCH_RESTORE_COST
from content import BIOME_LIST, BIOMES, NPC_ARRIVE, NPC_SPOTS, NPCS, QUEST_REWARD, roast_for, SHOP_ITEMS
from database import store
from economy import terr_perks
from procgen import effect_total
from players import grant, heal_bonus, spend
from quests import quest_progress
from render import stat_lines
from ui import btn, kb, panel, say
from utils import esc, is_group


async def do_npc(m: Message, npc_key: str):
    uid = m.from_user.id
    doc = await store.get(uid)
    npc = NPCS[npc_key]
    loc = doc.get("location") or "city"
    if loc != "city":
        # بیرونِ شهر فقط NPCـی که همین الان سر راهته اینجاست؛ هر برخورد یک گفتگو (اتمیک، ضد دابل‌کلیک)
        met = await store.users.find_one_and_update(
            {"user_id": uid, "npc_here": npc_key}, {"$pull": {"npc_here": npc_key}},
            return_document=ReturnDocument.BEFORE)
        if not met and await store.wnpcs.find_one({"id": npc_key, "location": loc}):
            met = True        # 🌍 شبیه‌سازی می‌گه همین الان تو این منطقه‌ست
        if not met:
            await m.reply(
                panel(npc["color"], npc["icon"], npc["name"], [
                    f"<b>{npc['name']}</b> دیگه اینجا نیست؛ همین الان رفت پی کارش. 🌬",
                    "تو شهر همیشه پیداشون می‌کنی، یا وسط راه بهشون برمی‌خوری. 👣",
                ]),
                reply_markup=kb([btn("🌍 ادامه‌ی ماجراجویی", f"x:{loc}:{uid}", "green")]),
            )
            return
    lines = [f"💬 <i>{roast_for(doc)}</i>", "┈┈┈┈┈┈┈┈┈┈"]
    foot = None

    if npc_key == "old_man":
        q = doc.get("quest")
        if q:
            b = BIOMES[q["biome"]]
            lines.append(f"📜 «هنوز اون ماموریتو انجام ندادی؟ برو <b>{b['name']}</b> {b['icon']} و برگرد!»\n🪙 جایزه: {q['reward']} {GS}")
        else:
            bkey = random.choice([b for b in BIOME_LIST if b != "city"])
            B = BIOMES[bkey]
            reward = random.randint(*QUEST_REWARD)
            await store.users.update_one(
                {"user_id": uid}, {"$set": {"quest": {"biome": bkey, "reward": reward}}}
            )
            lines.append(
                f"📜 <b>ماموریت جدید!</b>\n«جوون، برو <b>{B['name']}</b> {B['icon']} یه گشتی بزن و سالم برگرد. "
                f"اگه موفق شدی، {reward} {GS} جایزه داری! 🎁»\n"
                f"👉 هر وقت خواستی، از دکمه‌ی «ماجراجویی» یا با نوشتن «سفر به {B['kw'].strip('()').split('|')[0]}» برو."
            )
    elif npc_key == "shop":
        item, price = random.choice(SHOP_ITEMS)
        try:
            from worldsim import get_world
            from worlddata import item_resource, price_mult
            w = await get_world()
            if w and loc in w["economy"]["supply"]:     # 💱 قیمتِ منطقه‌ای: عرضه/تقاضا (ضریب ۰٫۷ تا ۱٫۷)
                res = item_resource(item)
                pm = price_mult(w["economy"]["supply"][loc][res], w["economy"]["bias"][loc][res])
                price = max(1, int(price * pm))
                lines.append(f"📈 قیمتِ {esc(item)} اینجا ×{pm} ({'کمیاب' if pm > 1.1 else 'فراوون' if pm < 0.9 else 'عادی'})")
        except Exception:
            log.exception("shop price failed")
        if "capital" in await terr_perks(doc):      # 🏰 مزیتِ پایتخت: ۱۰٪ تخفیف
            price = max(1, int(price * 0.9))
        price = max(1, int(price * (1 - effect_total(doc, "shop_discount_pct") / 100)))   # 🎲 تخفیفِ پاسیو/چیت
        await store.users.update_one({"user_id": uid}, {"$set": {"pending_trade": {"item": item, "price": price}}})
        lines.append(
            f"🛒 «فقط امروز! <b>{esc(item)}</b> — فقط <b>{price} {GS}</b>. فرصت خوبیه، بدو!»"
        )
        foot = f"💡 دکمه‌ی «قبول معامله» رو بزن یا بنویس «<b>قبول معامله</b>» ({GS} تو: {doc.get('gold', 0)} 🪙)"
    elif npc_key == "cafe":
        rumor = await rumor_for(m, doc)
        if rumor:
            lines.append(f"☕ «بین خودمون بمونه… {rumor}»")
        if await spend(uid, 10):
            h = heal_bonus(doc, int(random.randint(6, 14) * (1.2 if "forest" in await terr_perks(doc) else 1)))
            d2, _ = await grant(uid, xp=5, survival=h)
            lines.append(f"☕ یه قهوه‌ی «ضدمرگ» گرفتی (−۱۰ {GS}). +{h}٪ بقا.\n«نوش جان! زندگی یه کم تلخه، ولی ارزشش رو داره.»")
        else:
            lines.append(f"☕ قهوه ۱۰ {GS} میشه و تو نداری. کافه‌چی یه لیوان آب بهت داد: «برو ماجراجویی کن، بعد برگرد!»")
    elif npc_key == "guard":
        rumor = await rumor_for(m, doc)
        if rumor:
            lines.append(f"💂 «{rumor}»")
        gcount = await store.guilds.count_documents({})
        lines.append(
            f"💂 «الان {gcount} گیلد تو این قاره فعالن. اگه گیلد نداری، یکی بساز یا به یکی بپیوند؛ تنهایی سخته!»"
        )
    elif npc_key == "witch":
        roll = random.random()
        if roll < 0.5:
            b = heal_bonus(doc, random.randint(5, 12))
            await grant(uid, survival=b, xp=8)
            lines.append(f"🧪 جادوگر یه معجون بهت داد: «بخور، خوب میشی!» +{b}٪ بقا. (طعمش عجیبه، ولی اثر می‌کنه)")
        else:
            c = random.randint(4, 10)
            await grant(uid, survival=-c, xp=8)
            lines.append(f"🕯 جادوگر یه طلسم کوچیک روت امتحان کرد! −{c}٪ بقا. (طلسمِ «سه روز چای سرد»)")
        lines.append(f"🔥 «کوره‌ی من هم بازه: تجهیز، ارتقا، ادغام. و اگه روحت ترک خورده، {WITCH_RESTORE_COST} {GS} بده ترمیمش کنم.»")
    from config import WORLD_ENABLED as _WE
    if _WE:
        from worldnpc import world_voice
        v = await world_voice(doc, npc_key)         # 🗨 صدای شخصیت‌دارِ NPC (AI یا fallback) + حافظه/نظر
        if v:
            lines.insert(2, v)
    d3 = await store.get(uid)
    lines += ["┈┈┈┈┈┈┈┈┈┈", *stat_lines(d3)]
    rows = []
    if npc_key == "shop":
        rows.append([btn("🛒 قبول معامله", f"tr:ok:{uid}", "green")])
    if npc_key == "witch":
        rows.append([btn("🔥 کوره‌ی روح", f"fg:home:{uid}", "red"), btn(f"🕯 بازیابی روح ({WITCH_RESTORE_COST})", f"fg:rs:{uid}", "purple")])
    rows.append([btn("🌍 ادامه‌ی ماجراجویی", f"x:{loc}:{uid}", "green"), btn("🌙 منو", f"m:main:{uid}", "blue")])
    await m.reply(panel(npc["color"], npc["icon"], npc["name"], lines, foot), reply_markup=kb(*rows))
    await quest_progress(m, "npc")


async def do_trade(m: Message) -> bool:
    uid = m.from_user.id
    # پیشنهاد اتمیک «مصرف» میشه؛ دو بار «قبول معامله» دو بار نمی‌خره
    before = await store.users.find_one_and_update(
        {"user_id": uid, "pending_trade": {"$ne": None}}, {"$set": {"pending_trade": None}}, return_document=ReturnDocument.BEFORE)
    pt = (before or {}).get("pending_trade")
    if not pt:
        return False
    if not await spend(uid, pt["price"]):
        await store.users.update_one({"user_id": uid, "pending_trade": None}, {"$set": {"pending_trade": pt}})
        await say(m, f"«{GS}ـت کمه! برو ماجراجویی کن و با پول برگرد.» 🪙", "🧔", "مغازه‌دارِ بی‌اعتماد", "yellow")
        return True
    item = f"🕵️ {pt['item']} ‹معامله‌ی مشکوک›"
    await store.users.update_one({"user_id": uid}, {"$push": {"inventory": {"$each": [item], "$slice": -15}}})
    await m.reply(panel("yellow", "🛒", "معامله انجام شد",
                        [f"🎁 {esc(item)}", f"🪙 −{pt['price']} {GS}", "🧔 «معامله‌ی خوبی بود! دوباره بیا.»"]))
    return True


async def roll_encounter(doc: dict, biome: str) -> list:
    """
    NPCهای زنده: وسط ماجراجویی ممکنه یکی (یا تو شهر گاهی دو تا) سر راهِ بازیکن سبز بشه.
    خروجی: [(npc_key, جمله‌ی ورود), ...]. انتخاب به حال بازیکن حساسه (بقای کم → جادوگر/کافه،
    ماموریت فعال → پیرمرد، پول کافی → مغازه‌دار، بی‌گیلد → نگهبان) و NPCِ دفعه‌ی قبل تکرار نمیشه.
    ذخیره‌ی حضورشون (`npc_here`) رو خودِ این تابع انجام میده.
    """
    uid = doc["user_id"]
    from config import WORLD_ENABLED
    if WORLD_ENABLED:
        try:
            from worldnpc import world_encounter
            res = await world_encounter(doc, biome)       # 🌍 NPCهایی که طبقِ شبیه‌سازی همین الان اینجان
            if res is not None:
                return res
        except Exception:
            log.exception("world_encounter failed; falling back")
    in_city = biome == "city"
    if random.random() >= (NPC_CITY_CHANCE if in_city else NPC_ENCOUNTER_CHANCE):
        return []
    last = doc.get("npc_last")
    pool = [k for k, spots in NPC_SPOTS.items() if biome in spots and k != last]
    if not pool:
        return []
    surv = doc.get("survival_rate", 50)

    def weight(k: str) -> float:
        w = 1.0
        if k in ("witch", "cafe") and surv < 40:
            w *= 3
        if k == "old_man" and doc.get("quest"):
            w *= 3
        if k == "shop" and doc.get("gold", 0) >= 60:
            w *= 2
        if k == "guard" and not doc.get("guild"):
            w *= 2
        return w

    picks = []
    for _ in range(2 if in_city and random.random() < 0.35 else 1):
        if not pool:
            break
        k = random.choices(pool, weights=[weight(x) for x in pool])[0]
        pool.remove(k)
        picks.append((k, NPC_ARRIVE[k][biome]))
    await store.users.update_one({"user_id": uid}, {"$set": {"npc_here": [k for k, _ in picks], "npc_last": picks[0][0]}})
    return picks


async def rumor_for(m, doc: dict) -> str:
    """🗣 شایعه‌ی NPC درباره‌ی یکی از بازیکن‌های همین گروه (تو پیوی خالی برمی‌گرده)."""
    if not is_group(m):
        return ""
    cands = await store.users.aggregate([
        {"$match": {"chats": m.chat.id, "registered": True, "opted_out": {"$ne": True}, "banned": {"$ne": True},
                    "user_id": {"$ne": doc["user_id"]}}},
        {"$sample": {"size": 1}},
    ]).to_list(1)
    if not cands:
        return ""
    t = cands[0]
    name = f"<b>{esc(t.get('first_name') or 'یه ناشناس')}</b>"
    pool = []
    if t.get("death_count", 0) >= 2:
        pool.append(f"شنیدم {name} تا حالا {t['death_count']} بار مُرده و هنوز اصرار داره «نقشه داشت»!")
    if t.get("trips", 0) >= 5:
        pool.append(f"{name} {t['trips']} بار رفته ماجراجویی. یا قهرمانه یا خونه‌ش رو گم کرده.")
    if t.get("guild"):
        pool.append(f"{name} عضو گیلد «{esc(t['guild'])}» شده. می‌گن اونجا همه‌چی دست‌دومه، حتی وفاداری.")
    if t.get("spouse_name"):
        pool.append(f"{name} با {esc(t['spouse_name'])} پیوند بسته. ایزدبانو هنوز تو ماتمه.")
    if t.get("level", 1) >= 3:
        pool.append(f"{name} به سطح {t['level']} رسیده. مواظبش باش؛ بوی غرور میده.")
    pool.append(f"{name} دیروز از کنارم رد شد و به من سلام نکرد. یادداشت کردم.")
    return random.choice(pool)
