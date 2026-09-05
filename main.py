import asyncio
import random
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand

# --- Configuration ---
BOT_TOKEN = "8842030206:AAESkQUHJWrz_N-Ls7BE1em5-nY0APNgGFs"
SECRET_PASS = "mansour$vx"
DB_NAME = "bot_database.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Database Setup ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            chat_id INTEGER,
            warns INTEGER DEFAULT 0,
            daily_msgs INTEGER DEFAULT 0,
            weekly_msgs INTEGER DEFAULT 0,
            monthly_msgs INTEGER DEFAULT 0,
            total_msgs INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS appeals (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            reason TEXT,
            status TEXT DEFAULT 'Pending'
        );
        """)
        await db.commit()

async def add_msg_count(user_id: int, chat_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO users (user_id, chat_id, daily_msgs, weekly_msgs, monthly_msgs, total_msgs)
        VALUES (?, ?, 1, 1, 1, 1)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            daily_msgs = daily_msgs + 1,
            weekly_msgs = weekly_msgs + 1,
            monthly_msgs = monthly_msgs + 1,
            total_msgs = total_msgs + 1;
        """, (user_id, chat_id))
        await db.commit()

# --- Keyboards ---
def user_start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Submit Appeal", callback_data="user_appeal"),
         InlineKeyboardButton(text="📊 My Status", callback_data="user_status")],
        [InlineKeyboardButton(text="🔮 Kundli", callback_data="user_kundli"),
         InlineKeyboardButton(text="🏆 Leaderboard", callback_data="user_lb")],
        [InlineKeyboardButton(text="🌐 Language", callback_data="user_lang"),
         InlineKeyboardButton(text="❌ Close", callback_data="close_menu")]
    ])

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Security & Anti-Spam", callback_data="p_sec"),
         InlineKeyboardButton(text="👋 Welcome & Captcha", callback_data="p_greet")],
        [InlineKeyboardButton(text="🚫 Word & Link Filters", callback_data="p_filters"),
         InlineKeyboardButton(text="⏳ Warns & Auto-Delete", callback_data="p_warns")],
        [InlineKeyboardButton(text="🎭 Media & Permissions", callback_data="p_media"),
         InlineKeyboardButton(text="💬 Custom Auto-Replies", callback_data="p_custom")],
        [InlineKeyboardButton(text="📊 Recurring Broadcasts", callback_data="p_recur"),
         InlineKeyboardButton(text="📋 Review & Log Setup", callback_data="p_logs")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="p_back"),
         InlineKeyboardButton(text="❌ Close", callback_data="close_menu")]
    ])

# --- FSM States ---
class BotStates(StatesGroup):
    admin_pass = State()

# --- Kundli Predictions ---
KUNDLI_PREDICTIONS = [
    "Aaj admin se bina baat ki daant padne ke 99% yog hain. Shant rahein! 🧘‍♂️",
    "Grah bata rahe hain ki aaj aapka message group me viral hoga. ✨",
    "Dhan labh ke yog hain, recharge pack bachakar rakhein. 📶",
    "Aaj group me crush se reply aane ke pure chances hain. ❤️",
    "Galti se kisi galat message par report dabane ke aasar hain. Savdhan rahein! ⚠️"
]

# --- Handlers ---
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.chat.type == "private":
        await msg.answer("👋 **Welcome to Appeal X Bot**\nNiche diye gaye options se choose karein:", 
                         reply_markup=user_start_kb(), parse_mode="Markdown")

@dp.message(Command("claim"))
async def cmd_claim(msg: types.Message, state: FSMContext):
    if msg.chat.type == "private":
        await msg.answer("🔒 Kripya Admin Access Key enter karein:")
        await state.set_state(BotStates.admin_pass)

@dp.message(BotStates.admin_pass)
async def process_admin_key(msg: types.Message, state: FSMContext):
    if msg.text == SECRET_PASS:
        try:
            await msg.delete()
        except Exception:
            pass
        await msg.answer("⚙️ **Admin Control & Moderation Panel**\nFull access granted:", 
                         reply_markup=admin_panel_kb(), parse_mode="Markdown")
    else:
        await msg.answer("❌ Galat Password! Access Denied.")
    await state.clear()

@dp.message(Command("kundli"))
async def cmd_kundli(msg: types.Message):
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    fortune = random.choice(KUNDLI_PREDICTIONS)
    await msg.reply(f"🔮 **Kundli Fal for {target.first_name}:**\n\n📜 {fortune}", parse_mode="Markdown")

@dp.message(Command("ship"))
async def cmd_ship(msg: types.Message):
    score = random.randint(10, 100)
    await msg.reply(f"💘 **Match Compatibility:** `{score}%`", parse_mode="Markdown")

@dp.message(Command(commands=["report", "admin"]))
async def cmd_report(msg: types.Message):
    if not msg.reply_to_message:
        sent = await msg.reply("⚠️ Report karne ke liye kisi message ko reply karein.")
        await asyncio.sleep(10)
        try:
            await sent.delete()
        except Exception:
            pass
        return

    reported_user = msg.reply_to_message.from_user
    alert = await msg.reply(f"🚨 **Report Submitted!**\nAdmins have been notified about {reported_user.mention_html()}.", 
                            parse_mode="HTML")
    await asyncio.sleep(300)
    try:
        await alert.delete()
    except Exception:
        pass

@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def track_messages(msg: types.Message):
    if msg.from_user and not msg.from_user.is_bot:
        await add_msg_count(msg.from_user.id, msg.chat.id)

@dp.callback_query(F.data == "close_menu")
async def cb_close(cb: types.CallbackQuery):
    await cb.message.delete()

# --- Main Entry Point ---
async def main():
    await init_db()
    await bot.set_my_commands([
        BotCommand(command="start", description="Open Main Menu"),
        BotCommand(command="report", description="Report msg to admins"),
        BotCommand(command="admin", description="Call admins"),
        BotCommand(command="kundli", description="Astrology prediction"),
        BotCommand(command="ship", description="Compatibility meter")
    ])
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
