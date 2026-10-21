import asyncio
import os
import random
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.client.default import DefaultBotProperties

# Render Environment Variables bo'limidan kalitlar olinadi
TOKEN = os.getenv("TOKEN") or os.getenv("BOT_TOKEN") or "BU_YERGA_TOKEN"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

games: dict[int, dict] = {}   # chat_id -> faol o'yin holati

# ==================== GEMINI AI SERVISI (404 XATOSISIZ) ====================

async def ask_gemini(prompt: str) -> str:
    """Google Gemini AI bilan bog'lanuvchi funksiya"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "⚠️ Render Environment bo'limida GEMINI_API_KEY topilmadi!"
    
    # Model nomlari ro'yxati (biri bo'lmasa ikkinchisini avtomatik sinaydi)
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]
    
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    async with aiohttp.ClientSession() as session:
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"]
                    elif resp.status == 404:
                        # 404 bo'lsa, keyingi model variantiga o'tadi
                        continue
                    else:
                        res_text = await resp.text()
                        return f"⚠️ AI API Xatoligi ({resp.status}): {res_text[:150]}"
            except Exception as e:
                return f"⚠️ Ulanishda xatolik yuz berdi: {e}"
        
        return "⚠️ Gemini modellari bilan bog'lanib bo'lmadi. API Kalitingizni va kvotangizni tekshiring."

# ==================== MA'LUMOTLAR ====================

VIKTORINA = [
    {"q": "O'zbekiston poytaxti qaysi shahar?", "a": ["toshkent"]},
    {"q": "2 + 2 * 2 nechaga teng?", "a": ["6"]},
    {"q": "Dunyodagi eng katta okean?", "a": ["tinch okean", "tinchoq okean", "tinch"]},
    {"q": "O'zbekiston bayrog'ida nechta yulduz bor?", "a": ["12", "o'n ikki"]},
    {"q": "Quyosh sistemasidagi eng katta sayyora?", "a": ["yupiter"]},
    {"q": "Amir Temur qaysi yilda tug'ilgan?", "a": ["1336"]},
    {"q": "Dunyodagi eng baland cho'qqi?", "a": ["everest", "jomolungma"]},
    {"q": "Suvning kimyoviy formulasi?", "a": ["h2o"]},
    {"q": "Bir yilda necha kun bor (kabisa bo'lmagan)?", "a": ["365"]},
    {"q": "1 kg temir og'irmi yoki 1 kg paxta?", "a": ["teng", "tengdir", "bir xil"]},
]

TOPISHMOQLAR = [
    {"q": "Tishlari bor, lekin tishlamaydi.", "a": ["taroq"]},
    {"q": "O'zi suvda, boshi quruqda.", "a": ["qamish"]},
    {"q": "Oyog'i ko'p, qorni och.", "a": ["stol", "stul"]},
    {"q": "Yozda kiyinadi, qishda yechinadi.", "a": ["daraxt"]},
    {"q": "Eshikda turadi, hech kimga gap bermaydi.", "a": ["qulf"]},
    {"q": "Tili bor, gapirmaydi.", "a": ["kitob"]},
    {"q": "Bir piyola suvda cho'kmaydi ham, suzmaydi ham.", "a": ["muz"]},
    {"q": "Kunduzi to'lib yotadi, kechasi bo'shaydi.", "a": ["karavot"]},
]

CHAIN_START = ["olma", "anor", "uzum", "gilos", "tarvuz", "qovun", "nok", "shaftoli"]

# ==================== YORDAMCHILAR ====================

def norm(s: str) -> str:
    return (s.strip().lower()
            .replace("`", "'").replace("ʻ", "'").replace("’", "'"))

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        return False

def menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Oddiy Viktorina", callback_data="g:quiz")],
        [InlineKeyboardButton(text="🤖 AI Viktorina (Cheksiz)", callback_data="g:ai_quiz")],
        [InlineKeyboardButton(text="🧩 Topishmoq", callback_data="g:riddle")],
        [InlineKeyboardButton(text="🔢 Son topish", callback_data="g:number")],
        [InlineKeyboardButton(text="🔗 So'z zanjiri", callback_data="g:chain")],
        [InlineKeyboardButton(text="⛔ To'xtatish", callback_data="g:stop")],
    ])

# ==================== BOT STATUSI ====================

@dp.my_chat_member()
async def on_bot_status(update: types.ChatMemberUpdated):
    new = update.new_chat_member.status
    if new == ChatMemberStatus.ADMINISTRATOR:
        try:
            await bot.send_message(
                update.chat.id,
                "✅ Rahmat, men <b>admin</b> bo'ldim!\n\n"
                "🎮 O'yinlarni boshlash: /oyin\n"
                "🤖 AI ga savol berish: /ai [savol]\n"
                "🛑 To'xtatish: /stop"
            )
        except Exception:
            pass
    elif new == ChatMemberStatus.MEMBER:
        try:
            await bot.send_message(
                update.chat.id,
                "👋 Qo'shganingiz uchun rahmat!\n"
                "Iltimos, meni <b>admin</b> qiling — shunda barcha xabarlarni "
                "ko'rib, o'yinlarni to'g'ri boshqaraman.\n"
                "So'ng: /oyin"
            )
        except Exception:
            pass
    elif new in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        games.pop(update.chat.id, None)

# ==================== BUYRUQLAR ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            "Salom! Men guruh o'yinlari va Sun'iy Intellekt botiman 🤖🎮\n\n"
            "• Meni <b>guruhga qo'shing</b> va /oyin yozing.\n"
            "• AI ga savol berish uchun: <code>/ai [savolingiz]</code>"
        )
    else:
        await message.answer("🎮 O'yinni boshlash uchun /oyin yozing.")

@dp.message(Command("ai"))
async def cmd_ai(message: Message):
    """AI bilan muloqot buyrug'i"""
    prompt = message.text.replace("/ai", "").strip()
    if not prompt:
        return await message.reply("🤖 AI ga savol berish uchun buyruqdan so'ng matn yozing.\nMasalan: <code>/ai Toshkent haqida qiziqarli fakt ayting</code>")
    
    wait_msg = await message.reply("🤔 Sun'iy intellekt o'ylamoqda...")
    ai_response = await ask_gemini(prompt)
    await wait_msg.edit_text(ai_response)

@dp.message(Command("oyin", "game"))
async def cmd_game(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return await message.answer("Bu buyruq faqat guruhlarda ishlaydi.")
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("⚠️ Faqat guruh adminlari o'yin boshlashi mumkin.")
    await message.answer("🎮 <b>O'yinni tanlang:</b>", reply_markup=menu_kb())

@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    if message.chat.type == ChatType.PRIVATE:
        return
    if not await is_admin(message.chat.id, message.from_user.id):
        return await message.reply("⚠️ Faqat adminlar.")
    if message.chat.id in games:
        games.pop(message.chat.id)
        await message.answer("🛑 O'yin to'xtatildi.")
    else:
        await message.answer("Hozir faol o'yin yo'q.")

# ==================== O'YIN TANLASH ====================

@dp.callback_query(F.data.startswith("g:"))
async def on_choice(cb: CallbackQuery):
    action = cb.data.split(":", 1)[1]
    chat_id = cb.message.chat.id

    if not await is_admin(chat_id, cb.from_user.id):
        return await cb.answer("Faqat adminlar o'yin boshqaradi!", show_alert=True)
    if chat_id in games and action != "stop":
        return await cb.answer("Avval joriy o'yinni to'xtating (/stop).", show_alert=True)

    await cb.answer()

    if action == "quiz":
        q = random.choice(VIKTORINA)
        games[chat_id] = {"type": "quiz", "answers": [norm(a) for a in q["a"]]}
        await cb.message.answer(
            f"🧠 <b>Viktorina!</b>\n\n❓ {q['q']}\n\n"
            f"Birinchi to'g'ri javob yozgan yutadi!"
        )

    elif action == "ai_quiz":
        wait_msg = await cb.message.answer("🤖 AI yangi savol va javob tayyorlamoqda...")
        prompt = (
            "O'zbek tilida 1 ta qiziqarli mantiqiy yoki bilimga oid viktorina savoli va uning 1 ta so'zdan iborat javobini tuz.\n"
            "Aniq quyidagi formatda javob ber:\n"
            "Savol: [savol matni]\n"
            "Javob: [javob matni]"
        )
        ai_res = await ask_gemini(prompt)

        if ai_res.startswith("⚠️"):
            return await wait_msg.edit_text(ai_res)

        q_text, a_text = "", ""
        for line in ai_res.strip().split("\n"):
            clean_line = line.replace("*", "").strip()
            if clean_line.lower().startswith("savol:"):
                q_text = clean_line.split(":", 1)[1].strip()
            elif clean_line.lower().startswith("javob:"):
                a_text = clean_line.split(":", 1)[1].strip()

        if q_text and a_text:
            games[chat_id] = {"type": "quiz", "answers": [norm(a_text)]}
            await wait_msg.edit_text(
                f"🤖 <b>AI Viktorina!</b>\n\n❓ {q_text}\n\n"
                f"Birinchi to'g'ri javob yozgan yutadi!"
            )
        else:
            await wait_msg.edit_text(f"⚠️ AI javobi formati mos kelmadi:\n\n<code>{ai_res}</code>")

    elif action == "riddle":
        r = random.choice(TOPISHMOQLAR)
        games[chat_id] = {"type": "riddle", "answers": [norm(a) for a in r["a"]]}
        await cb.message.answer(f"🧩 <b>Topishmoq!</b>\n\n❓ {r['q']}")

    elif action == "number":
        games[chat_id] = {"type": "number", "target": random.randint(1, 100), "attempts": 0}
        await cb.message.answer("🔢 <b>Son topish!</b>\n\n1 dan 100 gacha son o'yladim. Toping!")

    elif action == "chain":
        word = random.choice(CHAIN_START)
        games[chat_id] = {"type": "chain", "used": {word}, "last": word[-1]}
        await cb.message.answer(
            f"🔗 <b>So'z zanjiri!</b>\n\n"
            f"Boshlang'ich so'z: <b>{word}</b>\n"
            f"Keyingi so'z <b>{word[-1].upper()}</b> harfi bilan boshlansin.\n"
            f"(Kamida 3 harf, so'zlar takrorlanmasin)"
        )

    elif action == "stop":
        if chat_id in games:
            games.pop(chat_id)
            await cb.message.answer("🛑 O'yin to'xtatildi.")
        else:
            await cb.message.answer("Faol o'yin yo'q.")

# ==================== JAVOBLARNI TEKSHIRISH ====================

@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message):
    chat_id = message.chat.id
    game = games.get(chat_id)
    if not game or message.from_user.is_bot:
        return

    text = norm(message.text)
    name = message.from_user.full_name

    if game["type"] in ("quiz", "riddle"):
        if text in game["answers"]:
            games.pop(chat_id)
            emoji = "🧠" if game["type"] == "quiz" else "🧩"
            await message.reply(f"🎉 <b>To'g'ri!</b> {emoji}\n🏆 G'olib: <b>{name}</b>")
        return

    if game["type"] == "number":
        try:
            n = int(text)
        except ValueError:
            return
        game["attempts"] += 1
        if n == game["target"]:
            tries = game["attempts"]
            games.pop(chat_id)
            await message.reply(
                f"🎉 <b>Topdingiz!</b> Son: <b>{n}</b>\n"
                f"🏆 G'olib: <b>{name}</b>\n"
                f"📊 Urinishlar: {tries}"
            )
        elif n < game["target"]:
            await message.reply("⬆️ Kattaroq son o'yladim.")
        else:
            await message.reply("⬇️ Kichikroq son o'yladim.")
        return

    if game["type"] == "chain":
        if len(text) < 3 or text in game["used"]:
            return
        if not text.startswith(game["last"]):
            return
        game["used"].add(text)
        game["last"] = text[-1]
        await message.reply(
            f"✅ <b>{text}</b> — qabul qilindi.\n"
            f"Keyingi so'z <b>{text[-1].upper()}</b> harfi bilan boshlansin!"
        )

# ==================== RENDER PORT UCHUN SERVER ====================

async def handle(request):
    return web.Response(text="Bot muvaffaqiyatli ishlamoqda!")

async def main():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
