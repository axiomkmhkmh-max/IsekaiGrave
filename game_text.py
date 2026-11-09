"""مغز تشخیص پیام‌های متنی بازی (handle_text)."""

import random
import re
import time

from aiogram import Bot
from aiogram.types import Message

from admin import handle_admin_commands
from config import (
    log, DROP_COOLDOWN, HERALD_CHANCE, HERALD_COOLDOWN, LOOT_CHANCE, LOOT_COOLDOWN, RAID_SPAWN_CHANCE,
    RANDOM_DROP_CHANCE, runtime,
)
from content import gline, GODDESS_NAME, NPCS, ROASTS
from curses import do_curse_bless, do_forced
from database import store
from death import do_distress, do_self_death
from drops import claim_drop, spawn_drop, _last_loot, _recent_chatters
from duels import do_duel_accept, do_duel_request
from exploration import detect_biome, do_explore
from exchange import exchange_home, gs_panel, sell_command
from forge import equip_command, forge_home
from guilds import (
    do_guild_create, do_guild_donate, do_guild_fort, do_guild_invite, do_guild_join, do_guild_leave, do_guild_me,
    do_guild_war,
)
import reply_games
import skirmish
from cmdhelp import CMDS_RE, do_commands
from intents import (
    ACCEPT_RE, BLESS_RE, BOARD_RE, BOSS_CALL_RE, BOSS_HIT_RE, BOSS_STATUS_RE, BUY_RE, CAFE_RE,
    CHURCH_RE, CURSE_RE, DEATH_RE, DEFUSE_RE, DISTRESS_RE, DIVORCE_RE, DUEL_RE, EXEC_RE, GUILD_CREATE_RE,
    GUILD_INVITE_RE, GUILD_JOIN_RE, GUILD_LEAVE_RE, GUILD_ME_RE, GUILD_WAR_RE, HELP_RE, INV_RE,
    INVITE_RE, MARKET_RE, MARRY_ACCEPT_RE, MARRY_DECLINE_RE, MARRY_RE, MENU_RE, NPC_RE, OPEN_RE,
    OPT_IN_RE, OPT_OUT_RE, PASSPORT_RE, QUEST_RE, REG_RE, REPLY_EXEC_RE, SIEGE_RE, SMALL_TALK_HELP,
    STROLL_RE, TERR_RE, TITLES_RE, TRADE_RE, TRAVEL_RE, WHEEL_RE, WORLD_RE, CHEAT_RE,
    DONATE_RE, EQUIP_RE, EXCH_RE, FORGE_RE, FORT_RE, GS_RE, SELL_RE,
)
from inventory import send_inventory
from leaderboard import do_board
from market import do_buy, drop_offer, _last_drop
from marriage import do_divorce, do_marry, marriage_answer
from menus import send_hub
from npc import do_npc, do_trade
from quests import do_quests
from raid import do_boss_call, do_boss_status, do_raid_hit, spawn_raid
from registration import reg_prompt, start_registration
from render import display, render_passport
from worldnpc import do_cheat, do_world, ensure_gen_profile
from territories import do_siege, do_terr, find_terr
from ui import back_kb, btn, kb, panel, say
from utils import clean, esc, is_group, norm, utcnow
from wheel import do_wheel


_last_herald: dict = {}


def looks_like_game(c: str, n: str, m: Message) -> bool:
    """آیا این پیام یه دستور بازی‌ست؟ (برای گیتِ ثبت‌نام؛ پیام‌های عادی گروه رو مزاحم نمی‌شه)"""
    full = (MENU_RE, QUEST_RE, TERR_RE, SIEGE_RE, MARRY_RE, MARRY_ACCEPT_RE, MARRY_DECLINE_RE, DIVORCE_RE,
            BOSS_CALL_RE, BOSS_HIT_RE, BOSS_STATUS_RE, DEATH_RE, PASSPORT_RE, TITLES_RE, INV_RE, INVITE_RE,
            STROLL_RE, DUEL_RE, GUILD_CREATE_RE, GUILD_JOIN_RE, GUILD_WAR_RE, GUILD_ME_RE, GUILD_LEAVE_RE,
            GUILD_INVITE_RE, EXCH_RE, SELL_RE, FORGE_RE, EQUIP_RE, GS_RE, DONATE_RE, FORT_RE, WORLD_RE, CHEAT_RE, CHURCH_RE)
    srch = (WHEEL_RE, BOARD_RE, CAFE_RE, NPC_RE, MARKET_RE, ACCEPT_RE, TRADE_RE)
    if any(r.fullmatch(c) for r in full) or any(r.search(c) for r in srch):
        return True
    if EXEC_RE.search(n):
        return True
    if m.reply_to_message and (REPLY_EXEC_RE.fullmatch(c) or CURSE_RE.search(n) or BLESS_RE.search(n)):
        return True
    if TRAVEL_RE.fullmatch(c) and detect_biome(c):
        return True
    if reply_games.matches(m.text or "", bool(m.reply_to_message)) or skirmish.matches(m.text or "", bool(m.reply_to_message)):   # ⚔️ حمله/تمرین/تحقیر/شرط/دزدی/ترمیم/هدیه/جایزه/جاسوسی/جنگ/میدان
        return True
    return False


async def handle_text(m: Message, bot: Bot):
    await store.touch(m.from_user)
    n = norm(m.text)
    mentioned = bool(runtime.bot_username) and ("@" + runtime.bot_username.lower()) in n
    replied_to_bot = bool(m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id == bot.id)
    if mentioned:
        n = n.replace("@" + runtime.bot_username.lower(), " ")
        n = re.sub(r"\s+", " ", n).strip()
    c = clean(n)
    group = is_group(m)

    # بن‌شده‌ها نادیده گرفته میشن؛ ادمین‌ها قبل از همه
    me_doc = await store.get(m.from_user.id)
    if me_doc and me_doc.get("banned"):
        return
    if await handle_admin_commands(m, bot, c):
        return
    if CMDS_RE.fullmatch(c):                      # 📚 «دستورات»: پنلِ همه‌ی دستورها (برای ثبت‌نام‌نشده‌ها هم)
        await do_commands(m)
        return
    registered = bool(me_doc and me_doc.get("registered"))

    # ۰) حرف‌های نگران‌کننده: بازی متوقف، پاسخ همدلانه
    if DISTRESS_RE.search(c):
        await do_distress(m)
        return

    # آمار فعالیت گروه (برای جنگ قلمروها)
    if group:
        await store.groups.update_one(
            {"chat_id": m.chat.id}, {"$set": {"title": m.chat.title}, "$inc": {"activity": 1}}, upsert=True
        )
        await store.users.update_one({"user_id": m.from_user.id}, {"$addToSet": {"chats": m.chat.id}})
        _recent_chatters[m.chat.id].append((m.from_user.id, m.from_user.full_name))

    # ۰.۵) ثبت‌نام: بدون قرارداد، ورود به ایسکا ممنوعه
    if REG_RE.fullmatch(c):
        if registered:
            await say(m, "تو قبلاً قرارداد رو امضا کردی. یادت رفته؟ حافظه‌ت از ماهی هم ضعیف‌تره. 📜", "📜", "ثبت‌نام", "purple")
        else:
            await start_registration(m)
        return
    if not registered:
        if HELP_RE.fullmatch(c):
            await m.reply(SMALL_TALK_HELP)
            return
        if not (OPT_OUT_RE.fullmatch(c) or OPT_IN_RE.fullmatch(c)):
            drop_try = (OPEN_RE.fullmatch(c) or DEFUSE_RE.fullmatch(c)) and group and \
                await store.drops.count_documents({"chat_id": m.chat.id, "status": "open", "expires_at": {"$gt": utcnow()}})
            if (not group) or mentioned or replied_to_bot or drop_try or looks_like_game(c, n, m):
                await reg_prompt(m)
                return

    # ۱) اعدام اجباری
    if group and (("@" in n) or m.reply_to_message) and await do_forced(m, n, c):
        return

    # ۱.۴) 🎭 باشگاهِ ریپلای: تاس، هفت‌تیر، بلوف، باشگاه، سریع ترین ها
    if await reply_games.handle(m, bot):
        return

    # ۱.۵) کنش‌های ریپلایی: حمله، دزدی، ترمیم، هدیه، جایزه‌ی سر، جاسوسی، حالت جنگ
    if await skirmish.do_skirmish(m, m.text or ""):
        return

    # ۲) دوئل
    if group:
        dm = DUEL_RE.fullmatch(c)
        if dm and await do_duel_request(m, dm.group(4)):
            return
        if ACCEPT_RE.search(c) and await do_duel_accept(m):
            return

    # ۳) نفرین/دعا
    if await do_curse_bless(m, c, n):
        return

    # ۴) خرید از بازار سیاه / معامله با مغازه‌دار
    if BUY_RE.fullmatch(c) and await do_buy(m):
        return
    if TRADE_RE.search(c) and await do_trade(m):
        return

    # 🪙🪦🔥 اقتصادِ GS، بازار روح و کوره
    if EXCH_RE.fullmatch(c):
        await exchange_home(m, bot)
        return
    if sm := SELL_RE.fullmatch(c):
        await sell_command(m, int(sm.group(1)), int(sm.group(2)))
        return
    if FORGE_RE.fullmatch(c):
        await forge_home(m)
        return
    if sm := EQUIP_RE.fullmatch(c):
        await equip_command(m, int(sm.group(1)))
        return
    if GS_RE.fullmatch(c):
        await gs_panel(m)
        return
    if sm := DONATE_RE.fullmatch(c):
        await do_guild_donate(m, int(sm.group(2)))
        return
    if FORT_RE.fullmatch(c):
        await do_guild_fort(m)
        return

    # ۵) گیلد
    if gm := GUILD_CREATE_RE.fullmatch(c):
        await do_guild_create(m, gm.group(1).strip())
        return
    if gm := GUILD_JOIN_RE.fullmatch(c):
        await do_guild_join(m, gm.group(1).strip())
        return
    if GUILD_WAR_RE.fullmatch(c):
        await do_guild_war(m)
        return
    if GUILD_ME_RE.fullmatch(c):
        await do_guild_me(m)
        return
    if GUILD_LEAVE_RE.fullmatch(c):
        await do_guild_leave(m)
        return
    if gm := GUILD_INVITE_RE.fullmatch(c):
        await do_guild_invite(m, gm.group(2))
        return

    # ۶) گردونه‌ی شانس و لیدربرد
    if WHEEL_RE.search(c):
        await do_wheel(m)
        return
    if BOARD_RE.search(c):
        await do_board(m)
        return

    # ۶.۴) 🌐 جهانِ زنده و 🌟 چیت‌اسکیل
    if WORLD_RE.fullmatch(c):
        await do_world(m)
        return
    if CHEAT_RE.fullmatch(c):
        await do_cheat(m)
        return

    # ۶.۵) منو، ماموریت، قلمرو، پیوند، صندوق/بمب، باس
    if MENU_RE.fullmatch(c):
        await send_hub(m, me_doc)
        return
    if QUEST_RE.fullmatch(c):
        await do_quests(m)
        return
    if TERR_RE.fullmatch(c):
        await do_terr(m)
        return
    if sm := SIEGE_RE.fullmatch(c):
        key = find_terr(sm.group(2))
        if key:
            await do_siege(m, key)
        else:
            await say(m, "کدوم قلمرو؟ یکی از اینا رو بنویس: «پایتخت»، «قلعه»، «جنگل»، «بندر» یا «خرابه».", "🗺", "محاصره", "blue")
        return
    if mm := MARRY_RE.fullmatch(c):
        if await do_marry(m, mm.group(3)):
            return
    if MARRY_ACCEPT_RE.fullmatch(c) and group and await marriage_answer(m, True, None):
        return
    if MARRY_DECLINE_RE.fullmatch(c) and group and await marriage_answer(m, False, None):
        return
    if DIVORCE_RE.fullmatch(c):
        await do_divorce(m)
        return
    if group and OPEN_RE.fullmatch(c) and await claim_drop(m, "open"):
        return
    if group and DEFUSE_RE.fullmatch(c) and await claim_drop(m, "defuse"):
        return
    if BOSS_CALL_RE.fullmatch(c):
        await do_boss_call(m, bot)
        return
    if BOSS_HIT_RE.fullmatch(c):
        if not await do_raid_hit(m):
            await say(m, "الان باسی نیست. برای احضار بنویس «احضار باس». 🐉", "🐉", "باس", "red")
        return
    if BOSS_STATUS_RE.fullmatch(c):
        await do_boss_status(m)
        return

    # ۷) NPC (قبل از سفر، تا «ورود به کافه» اشتباه تفسیر نشه)
    if CAFE_RE.search(c):
        await do_npc(m, "cafe")
        return
    if CHURCH_RE.fullmatch(c):
        from worldnpc import do_church
        await do_church(m)
        return
    if nm := NPC_RE.search(c):
        target = nm.group(2)
        for key, npc in NPCS.items():
            if re.search(npc["alias"], target):
                await do_npc(m, key)
                return
        await say(m, "همچین آدمی تو ایسکا نمی‌شناسم. 🤷 یکی از اینا رو امتحان کن: «پیرمرد»، «مغازه‌دار»، «کافه‌چی»، «نگهبان» یا «جادوگر»؛ تو شهر همیشه هستن و بیرون وسط ماجراجویی بهشون برمی‌خوری.", "🧙", "NPC", "purple",
                  kb([btn("🌍 برو ماجراجویی", f"m:go:{m.from_user.id}", "green")]))
        return

    # ۸) سفر و ماجراجویی
    if STROLL_RE.fullmatch(c):
        doc = await store.get(m.from_user.id)
        await do_explore(m, doc.get("location") or "city")
        return
    if tm := TRAVEL_RE.fullmatch(c):
        key = detect_biome(tm.group(tm.lastindex or 0)) if tm.lastindex else None
        key = key or detect_biome(c)
        if key:
            await do_explore(m, key)
            return

    # ۹) اینتنت‌های ساده
    uid = m.from_user.id
    if MARKET_RE.search(c):
        await m.reply(await drop_offer(m.chat.id), reply_markup=kb([btn("💸 میخرم!", "buy:0:0", "green")]))
        return
    if TITLES_RE.fullmatch(c):
        titles = me_doc.get("titles") or []
        if not titles:
            await say(m, "هنوز لقبی نداری. با ماجراجویی و بازتولد (بنویس «ریسپاون») لقب می‌گیری! 🏷", "🏷", "لقب‌ها", "purple")
        else:
            lines = [f"{i}. {esc(t)}" for i, t in enumerate(titles, 1)]
            await m.reply(panel("purple", "🏷", f"لقب‌های {m.from_user.full_name}", lines),
                          reply_markup=kb(back_kb(uid)))
        return
    if INV_RE.fullmatch(c):
        await send_inventory(m, me_doc)
        return
    if PASSPORT_RE.fullmatch(c):
        me_doc = await ensure_gen_profile(me_doc)
        await m.reply(render_passport(me_doc), reply_markup=kb(
            [btn("🌙 منو", f"m:main:{uid}", "blue"), btn("🎒 کوله‌پشتی", f"m:inv:{uid}", "green")]))
        return
    if DEATH_RE.fullmatch(c):
        await do_self_death(m)
        return
    if INVITE_RE.fullmatch(c):
        link = f"https://t.me/{runtime.bot_username}?start=ref_{uid}"
        await m.reply(panel("blue", "🔗", "لینک دعوت اختصاصی", [
            link, "هر ۳ نفر = یه شانس خرید از بازار سیاه 🎁 · ۵ نفر = لقب «سفیرِ ایزدبانو» 🏷 · ۱۰ نفر = «اسقفِ ارواح» 👑",
        ]), reply_markup=kb([btn("📩 باز کردن لینک", url=link)]))
        return
    if OPT_OUT_RE.fullmatch(c):
        await store.users.update_one({"user_id": uid}, {"$set": {"opted_out": True}})
        await say(m, "باشه! از این به بعد کسی نمی‌تونه اعدامت کنه، نفرینت کنه یا به دوئل دعوتت کنه. هر وقت پشیمون شدی بنویس «برگردم به بازی». 🛡", "🛡", "محافظت", "blue")
        return
    if OPT_IN_RE.fullmatch(c):
        await store.users.update_one({"user_id": uid}, {"$set": {"opted_out": False}})
        await say(m, "خوش برگشتی! 😈 از حالا دوباره بقیه می‌تونن اعدامت کنن، نفرینت کنن یا به دوئل دعوتت کنن. 😄", "😈", "برگشتی", "red")
        return
    if HELP_RE.fullmatch(c):
        await m.reply(SMALL_TALK_HELP, reply_markup=kb([btn("🌙 منوی اصلی", f"m:main:{uid}", "green")]))
        return

    # ۹.۵) گفتگوی آزاد با NPCـی که همین الان باهاش حرف می‌زنی (قبل از جوابِ پیش‌فرضِ ایزدبانو/راهنما)
    if me_doc and (mentioned or replied_to_bot or not group):
        try:
            from worldnpc import do_npc_chat
            if await do_npc_chat(m, me_doc, re.sub(r"@\w+", " ", m.text or "")):
                return
        except Exception:
            log.exception("npc chat failed")

    # ۱۰) صدا زدن بدون دستور معتبر: اگه متنی هست ایزدبانو (AI یا جوابِ ربط‌دار) جواب میده؛ فقط منشنِ خالی جمله‌ی رندوم می‌گیره
    if (mentioned or replied_to_bot) and me_doc:
        try:
            from worldnpc import do_npc_chat
            if await do_npc_chat(m, me_doc, re.sub(r"@\w+", " ", m.text or ""), default_npc="goddess"):
                return
        except Exception:
            log.exception("goddess chat failed")
    if mentioned or replied_to_bot:
        await m.reply(panel("purple", "💅", GODDESS_NAME, [random.choice(ROASTS)], gline(me_doc)),
                      reply_markup=kb([btn("🌙 پنل‌ها", f"m:main:{uid}", "blue")]))
        return
    if not group:
        await m.answer(SMALL_TALK_HELP, reply_markup=kb([btn("🌙 منوی اصلی", f"m:main:{uid}", "green")]))
        return

    # ۱۱) حرکات تصادفیِ گروه: لقب‌خوانی، بازار سیاه، صندوق/بمب، باس
    now = time.time()
    doc = me_doc
    if doc and doc.get("titles") and random.random() < HERALD_CHANCE and now - _last_herald.get(uid, 0) > HERALD_COOLDOWN:
        _last_herald[uid] = now
        await m.reply(panel("yellow", "🔔", "توجه توجه!", [
            f"👑 {display(doc, link=True)} وارد صحنه شد! همه دست بزنید. 👏",
        ], gline(doc)))
        return
    if random.random() < RANDOM_DROP_CHANCE and now - _last_drop.get(m.chat.id, 0) > DROP_COOLDOWN:
        await m.answer(await drop_offer(m.chat.id), reply_markup=kb([btn("💸 میخرم!", "buy:0:0", "green")]))
        return
    if random.random() < LOOT_CHANCE and now - _last_loot.get(m.chat.id, 0) > LOOT_COOLDOWN:
        await spawn_drop(bot, m.chat.id)
        return
    if random.random() < RAID_SPAWN_CHANCE:
        await spawn_raid(bot, m.chat.id)
