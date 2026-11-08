"""هندلر کلیک دکمه‌های اینلاین."""

from aiogram import Bot
from aiogram.types import CallbackQuery, Message

from arena import arena_cb
from battle import battle_cb
from admin import admin_clean, admin_health, ADMIN_HELP, admin_stats, is_admin
from content import BIOMES, BOONS, CLASSES, NPCS, TERRITORIES
from database import store
from death import do_self_death
from drops import claim_drop
from exchange import exchange_cb, exchange_home, gs_panel
from duels import do_duel_accept
from exploration import do_explore
from expedition import expedition_cb
from forge import forge_cb, forge_home, inv_cb
from guilds import do_guild_me, do_guild_war
from intents import SMALL_TALK_HELP
from inventory import send_inventory
from leaderboard import do_board
from market import do_buy, drop_offer
from marriage import do_divorce, do_marry_info, marriage_answer
from guide import CAT_ACT, INTRO_FEATS, cat_panel, do_next_step, do_skip_tour, intro_once, lock_text
from menus import help_kb, hub_payload
from npc import do_npc, do_trade
from worldnpc import do_cheat, do_use_cheat, do_world, do_world_npc, ensure_gen_profile
from quests import do_quests
from raid import do_boss_call, do_boss_status, do_raid_hit
from registration import (
    claim_gift, finish_registration, reg_kb_done, reg_done_text, reg_kb_boon, reg_kb_class, reg_prompt, reg_text_boon,
    reg_text_class, start_registration,
)
from render import render_passport
from territories import do_siege, do_terr, siege_cb
from ui import back_kb, btn, CbMsg, kb, panel, safe_edit, say
from utils import is_group
from wheel import do_wheel


async def handle_cb(cq: CallbackQuery, bot: Bot):
    data = cq.data or ""
    parts = data.split(":")
    if len(parts) < 2 or not parts[-1].lstrip("-").isdigit():
        await cq.answer()
        return
    if not isinstance(cq.message, Message):
        await cq.answer("این پنل قدیمی شده؛ بنویس «زندگی من» تا دوباره باز بشه.", show_alert=True)
        return
    kind, owner = parts[0], int(parts[-1])
    user = cq.from_user
    if owner and user.id != owner:
        await cq.answer("این پنل مال یکی دیگه‌ست 🙂 پنل خودت رو با نوشتن «زندگی من» باز کن.", show_alert=True)
        return
    await store.touch(user)
    doc = await store.get(user.id)
    if doc and doc.get("banned"):
        await cq.answer("تو بن شدی. ایزدبانو دیگه تو رو نمی‌بینه؛ برای ما وجود نداری. 🚫", show_alert=True)
        return
    m = CbMsg(cq, bot)
    uid = user.id
    registered = bool(doc and doc.get("registered"))

    # ⚔️ حرکتِ نبرد: خودش جواب کلیک رو می‌ده (هشدارِ «نوبتت نیست»)
    if kind == "bt":
        if registered:
            await battle_cb(cq, bot, parts)
        else:
            await cq.answer()
        return

    # 🏟 میدان (حمله‌ی ژستی، تمرین، شرط‌بندی، انتقام): خودش جواب کلیک رو می‌ده
    if kind == "sk":
        if registered:
            await arena_cb(cq, bot, parts)
        else:
            await cq.answer("اول ثبت‌نام کن. 🙂", show_alert=True)
        return

    # ── ادمین
    if kind == "adm":
        if not is_admin(uid):
            await cq.answer("این بخش فقط برای ادمین‌هاست. 🚫", show_alert=True)
            return
        await cq.answer()
        act = parts[1]
        if act == "stats":
            await m.reply(await admin_stats())
        elif act == "health":
            await m.reply(await admin_health())
        elif act == "clean":
            await m.reply(await admin_clean())
        elif act == "help":
            await m.reply(panel("red", "🛠", "فرمان‌های ادمین", ADMIN_HELP))
        return

    # ── ثبت‌نام
    if kind == "reg":
        act = parts[1]
        if act == "go":
            if registered:
                await cq.answer("قرارداد رو قبلاً امضا کردی؛ دیگه راه برگشتی نیست. 😈", show_alert=True)
                return
            await cq.answer()
            await start_registration(m)
        elif act == "gift" and len(parts) >= 4 and parts[2] in BOONS:
            if not registered:
                await cq.answer("اول ثبت‌نام کن. 🙂", show_alert=True)
                return
            gdoc = await claim_gift(user, parts[2])
            if not gdoc:
                await cq.answer("هدیه‌ی شروعت رو قبلاً برداشتی. 🎁", show_alert=True)
                return
            await cq.answer("هدیه برداشته شد! 🎁")
            await safe_edit(cq.message, reg_done_text(gdoc, gdoc.get("cls"), parts[2]), reg_kb_done(uid, False))
        elif registered:
            await cq.answer("ثبت‌نامت قبلاً انجام شده. 👍", show_alert=True)
        elif act == "sign":
            ndoc = await finish_registration(user, None, None)     # 🎲 کلاس/چیت‌اسکیلِ رندوم همین‌جا ساخته میشه
            if not ndoc:
                await cq.answer("قبلاً ثبت‌نام شدی.", show_alert=True)
                return
            await cq.answer("قرارداد امضا شد! 🎉")
            await safe_edit(cq.message, reg_done_text(ndoc, None, None), reg_kb_done(uid, True))
        elif act == "cls" and len(parts) >= 4 and parts[2] in CLASSES:
            ndoc = await finish_registration(user, parts[2], None)
            if not ndoc:
                await cq.answer("قبلاً ثبت‌نام شدی.", show_alert=True)
                return
            await cq.answer("قرارداد امضا شد! 🎉")
            await safe_edit(cq.message, reg_done_text(ndoc, parts[2], None), reg_kb_done(uid, True))
        elif act == "boon" and len(parts) >= 5 and parts[2] in CLASSES and parts[3] in BOONS:
            ndoc = await finish_registration(user, parts[2], parts[3])
            if not ndoc:
                await cq.answer("قبلاً ثبت‌نام شدی.", show_alert=True)
                return
            await cq.answer("قرارداد امضا شد! 🎉")
            await safe_edit(cq.message, reg_done_text(ndoc, parts[2], parts[3]),
                            kb([btn("🎯 الان چیکار کنم؟", f"m:next:{uid}", "green")],
                               [btn("🌍 اولین ماجراجویی", f"x:forest:{uid}", "blue"), btn("🌙 منو", f"m:main:{uid}", "blue")]))
        elif act == "run":
            await cq.answer("فرار؟ 🏃")
            await safe_edit(cq.message, panel("red", "🏃", "فرار ناموفق", [
                "💅 «فرار؟ از من؟ هیچ‌کس از دروازه‌ی من فرار نکرده. فرارت رو یه ثانیه تماشا کردم و خمیازه کشیدم. هر وقت خسته شدی، برگرد و التماس کن.»",
                "هر وقت آماده بودی، دکمه‌ی پایین رو بزن یا بنویس «<b>ثبت‌نام</b>».",
            ]), kb([btn("🩸 خیله‌خب، امضا می‌کنم", f"reg:go:{uid}", "green")]))
        else:
            await cq.answer()
        return

    # ── بدون ثبت‌نام فقط راهنما
    if not registered and not (kind == "m" and parts[1] == "help"):
        await cq.answer("اول ثبت‌نام کن، بعد بیا! 🙂", show_alert=True)
        await reg_prompt(m)
        return

    # 🔒 دکمه‌ی قفل: هشدارِ «از چه سطحی باز میشه» (باید قبل از cq.answer() خالی بیاد)
    if kind == "m" and parts[1] == "lock" and len(parts) >= 4:
        await cq.answer(lock_text(doc, parts[2]), show_alert=True)
        return

    await cq.answer()

    if kind == "x" and parts[1] in BIOMES:
        await do_explore(m, parts[1])
    elif kind == "e" and len(parts) >= 4:
        await expedition_cb(uid, parts[1], parts[2], lambda text, markup: safe_edit(cq.message, text, markup))
    elif kind == "n" and parts[1] in NPCS:
        await do_npc(m, parts[1])
    elif kind == "wn" and len(parts) >= 4:
        await do_world_npc(m, parts[1], parts[2] if parts[2] in ("hi", "rumor", "work") else "hi")
    elif kind == "ch" and parts[1] == "use":
        await do_use_cheat(m)
    elif kind == "tr":
        if not await do_trade(m):
            await say(m, "پیشنهادِ معامله‌ای باز نیست؛ شاید قبلاً قبول کردی یا مغازه‌دار منصرف شد. 🧔", "🛒", "معامله", "yellow")
    elif kind == "duelacc":
        if not await do_duel_accept(m):
            await say(m, "این دوئل تموم شده یا برای تو نیست.", "⚔️", "دوئل", "orange")
    elif kind == "buy":
        if not await do_buy(m):
            await say(m, "دلال رفت و بازار سیاه فعلاً بسته‌ست. بعداً دوباره سر بزن. 🕶", "🕶", "بازار سیاه", "black")
    elif kind == "loot":
        await claim_drop(m, parts[1], notify_fail=True)
    elif kind == "sg" and parts[1] in TERRITORIES:
        await do_siege(m, parts[1])
    elif kind == "inv":
        await inv_cb(m, parts)
    elif kind == "ex":
        await exchange_cb(m, parts)
    elif kind == "fg":
        await forge_cb(m, parts)
    elif kind == "war":
        await siege_cb(m, parts)
    elif kind == "raid":
        if parts[1] in ("hit", "ward", "fate"):
            if not await do_raid_hit(m, {"hit": "strike", "ward": "ward", "fate": "fate"}[parts[1]]):
                await say(m, "الان باسی نیست. برای احضار بنویس «احضار باس». 🐉", "🐉", "باس", "red")
        elif parts[1] == "call":
            await do_boss_call(m, bot)
        else:
            await do_boss_status(m)
    elif kind == "mar":
        await marriage_answer(m, parts[1] == "yes", parts[2])
    elif kind == "m":
        act = parts[1]
        if act in INTRO_FEATS:            # 📘 اولین بارِ ورود به یه بخش: توضیحِ کوتاه
            await intro_once(m, act)
        if act == "main":
            text, markup = await hub_payload(doc)
            await safe_edit(cq.message, text, markup)
        elif act == "next":               # 🎯 الان چیکار کنم؟
            await do_next_step(m, doc)
        elif act == "tskip":              # ⏭ رد کردنِ تورِ شروع
            await do_skip_tour(uid)
            doc = await store.get(uid)
            text, markup = await hub_payload(doc)
            await safe_edit(cq.message, text, markup)
        elif act in CAT_ACT:              # دسته‌های منو (نبرد / اقتصاد / ...)
            text, markup = cat_panel(uid, doc, CAT_ACT[act])
            await safe_edit(cq.message, text, markup)
        elif act in ("go", "npc"):      # «npc»: پنل‌های قدیمیِ قبل از NPCهای زنده
            rows = [[btn(f"{b['icon']} {b['name']}", f"x:{k}:{uid}", b["color"])] for k, b in BIOMES.items()]
            await safe_edit(cq.message, panel("green", "🌍", "کجا بریم؟", [
                "👇 یه مکان انتخاب کن تا ماجراجویی شروع بشه. 🧙 وسط راه ممکنه به آدم‌های زنده‌ی ایسکا بربخوری!\n💅 «هر جا بری، یا بدبخت میشی یا می‌میری. هر دو برای من سرگرم‌کننده‌ست.»",
            ]), kb(*rows, back_kb(uid)))
        elif act == "world":
            await do_world(m)
        elif act == "cheat":
            await do_cheat(m)
        elif act == "pass":
            doc = await ensure_gen_profile(doc)
            await m.reply(render_passport(doc), reply_markup=kb(back_kb(uid)))
        elif act == "inv":
            await send_inventory(m, doc)
        elif act == "exch":
            await exchange_home(m)
        elif act == "forge":
            await forge_home(m)
        elif act == "gs":
            await gs_panel(m)
        elif act == "wheel":
            await do_wheel(m)
        elif act == "arena":
            from arena import do_arena
            await do_arena(m)
        elif act == "guild":
            await do_guild_me(m)
        elif act == "war":
            await do_guild_war(m)
        elif act == "board":
            await do_board(m)
        elif act == "market":
            if is_group(m):
                await m.reply(await drop_offer(m.chat.id), reply_markup=kb([btn("💸 میخرم!", "buy:0:0", "green")]))
            else:
                await say(m, "بازار سیاه فقط تو گروه‌ها باز میشه. ربات رو به گروهت اضافه کن و اونجا امتحان کن. 🕶", "🕶", "بازار سیاه", "black")
        elif act == "quest":
            await do_quests(m)
        elif act == "terr":
            await do_terr(m)
        elif act == "boss":
            await do_boss_status(m)
        elif act == "marry":
            await do_marry_info(m, doc)
        elif act == "help":
            await m.reply(SMALL_TALK_HELP, reply_markup=help_kb(uid) if registered else None)
        elif act == "die":
            await safe_edit(cq.message, panel("red", "☠️", "مرگ داوطلبانه؟", [
                "💅 «خودت می‌خوای بمیری؟ بدون کامیون، بدون رامن؟ بی‌خلاقیت‌ترین مرگی که تو این ده سال دیدم. ولی قبوله؛ بیا.»",
                "ℹ️ بعد از مرگ دوباره متولد میشی: فرم، دنیا و مهارت جدید می‌گیری و نرخ بقات تصادفی میشه.",
            ]), kb([btn("☠️ آره، بفرست", f"m:die2:{uid}", "red"), btn("🔙 نه، پشیمون شدم", f"m:main:{uid}", "green")]))
        elif act == "die2":
            await do_self_death(m)
        elif act == "divorce":
            await do_divorce(m)
