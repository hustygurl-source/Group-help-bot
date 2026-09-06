import asyncio
import os
import random
import io
import time
import aiosqlite
from PIL import Image, ImageDraw, ImageFont
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BufferedInputFile, BotCommandScopeDefault, BotCommandScopeAllGroupChats

# --- Configuration ---
BOT_TOKEN = "8912103286:AAGBQTFYrTRFMGa6tEW5UHMtt3qCR6KcN8w"
SECRET_PASS = "mansour$vx"
DB_NAME = "bot_database.db"
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

PROFANITY_WORDS = ["gali", "abuse", "mc", "bc", "bhadve", "randi", "fuck", "shit", "tmkc", "tmkl"]

flood_tracker = {}

# --- Web Server & Health Check ---
async def handle_ping(request):
    return web.Response(text="Bot is Active and Running 24/7!", status=200)

async def handle_health(request):
    return web.json_response({"status": "healthy", "bot": "online"}, status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def keep_alive():
    await asyncio.sleep(60)
    while True:
        target_url = RENDER_EXTERNAL_URL or "http://127.0.0.1:8080"
        try:
            async with ClientSession() as session:
                async with session.get(f"{target_url}/health") as resp:
                    pass
        except Exception:
            pass
        await asyncio.sleep(600)

# --- Database Setup ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            full_name TEXT,
            warns INTEGER DEFAULT 0,
            daily_msgs INTEGER DEFAULT 0,
            weekly_msgs INTEGER DEFAULT 0,
            total_msgs INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS managed_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            antiflood_action TEXT DEFAULT 'warn',
            flood_limit INTEGER DEFAULT 3,
            flood_time INTEGER DEFAULT 2,
            flood_del INTEGER DEFAULT 1,
            max_warns INTEGER DEFAULT 3,
            mute_duration INTEGER DEFAULT 600,
            link_protection INTEGER DEFAULT 0,
            link_action TEXT DEFAULT 'warn',
            porn_protection INTEGER DEFAULT 0,
            masked_users INTEGER DEFAULT 1,
            masked_del INTEGER DEFAULT 1,
            welcome_status INTEGER DEFAULT 0
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_warn_counts (
            user_id INTEGER,
            chat_id INTEGER,
            warn_count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS banned_words_config (
            chat_id INTEGER PRIMARY KEY,
            action TEXT DEFAULT 'off',
            delete_msgs INTEGER DEFAULT 1
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS banned_words_list (
            chat_id INTEGER,
            word TEXT,
            PRIMARY KEY (chat_id, word)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS custom_commands (
            chat_id INTEGER,
            trigger_word TEXT,
            reply_text TEXT,
            PRIMARY KEY (chat_id, trigger_word)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS user_commands (
            chat_id INTEGER,
            trigger_word TEXT,
            reply_text TEXT,
            PRIMARY KEY (chat_id, trigger_word)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS inline_buttons_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            trigger_word TEXT,
            reply_text TEXT
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS inline_buttons_items (
            config_id INTEGER,
            button_name TEXT,
            button_url TEXT
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS appeals (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_key TEXT,
            reason TEXT,
            status TEXT DEFAULT 'Pending'
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS ban_tracker (
            user_id INTEGER,
            chat_key TEXT,
            is_banned INTEGER DEFAULT 1,
            appeal_used INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_key)
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_claims (
            user_id INTEGER PRIMARY KEY
        );
        """)
        await db.commit()

async def add_msg_count(user_id: int, chat_id: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        INSERT INTO users (user_id, chat_id, username, full_name, daily_msgs, weekly_msgs, total_msgs)
        VALUES (?, ?, ?, ?, 1, 1, 1)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            daily_msgs = daily_msgs + 1,
            weekly_msgs = weekly_msgs + 1,
            total_msgs = total_msgs + 1,
            username = excluded.username,
            full_name = excluded.full_name;
        """, (user_id, chat_id, username, full_name))
        await db.commit()

async def is_claimed_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admin_claims WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None

# --- PIL Image Generation for Leaderboards ---
async def generate_top3_card(title: str, top_users: list):
    img = Image.new("RGB", (700, 350), color=(15, 15, 22))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("arial.ttf", 24)
        font_name = ImageFont.truetype("arial.ttf", 16)
        font_msg = ImageFont.truetype("arial.ttf", 14)
    except IOError:
        font_title = ImageFont.load_default()
        font_name = ImageFont.load_default()
        font_msg = ImageFont.load_default()

    draw.text((230, 20), title, fill=(255, 215, 0), font=font_title)
    
    positions = [(260, 80), (60, 110), (460, 110)]
    for idx, user_data in enumerate(top_users[:3]):
        name = user_data[0] or "User"
        msgs = user_data[1]
        x, y = positions[idx]
        rank_label = f"#{idx+1}"
        draw.rectangle([x, y, x+180, y+200], outline=(70, 70, 100), width=2, fill=(25, 25, 35))
        draw.text((x+70, y+10), rank_label, fill=(255, 140, 0) if idx==0 else (200, 200, 200), font=font_name)
        draw.text((x+15, y+120), f"{name[:12]}", fill=(255, 255, 255), font=font_name)
        draw.text((x+25, y+150), f"{msgs} Messages", fill=(180, 180, 180), font=font_msg)

    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="top3.png")

async def generate_full_leaderboard_card(title: str, top_users: list):
    img = Image.new("RGB", (650, 450), color=(18, 18, 25))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("arial.ttf", 22)
        font_item = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font_title = ImageFont.load_default()
        font_item = ImageFont.load_default()

    draw.text((40, 25), title, fill=(0, 191, 255), font=font_title)
    y = 80
    for idx, user in enumerate(top_users[:8], 1):
        name = user[0] or "User"
        msgs = user[1]
        text = f"#{idx}   {name[:18]:<18} --- {msgs} msgs"
        draw.text((40, y), text, fill=(240, 240, 240), font=font_item)
        y += 40

    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="lead.png")

# --- States ---
class BotStates(StatesGroup):
    admin_pass = State()
    waiting_for_appeal_text = State()
    adding_banned_word = State()
    removing_banned_word = State()
    setting_pcmd_trigger = State()
    setting_pcmd_reply = State()
    setting_ucmd_trigger = State()
    setting_ucmd_reply = State()
    setting_inline_trigger = State()
    setting_inline_reply = State()
    setting_inline_buttons = State()

# --- Keyboards ---
def user_start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Submit Appeal", callback_data="menu_appeal"),
         InlineKeyboardButton(text="My Status", callback_data="menu_status")],
        [InlineKeyboardButton(text="Kundli", callback_data="menu_kundli"),
         InlineKeyboardButton(text="Leaderboard", callback_data="menu_lb")],
        [InlineKeyboardButton(text="Close", callback_data="close_menu")]
    ])

def group_selector_kb(groups):
    buttons = [[InlineKeyboardButton(text=f"{title}", callback_data=f"select_group_{cid}")] for cid, title in groups]
    buttons.append([InlineKeyboardButton(text="Back", callback_data="menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def main_admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Manage Groups", callback_data="admin_manage_groups")],
        [InlineKeyboardButton(text="Group", callback_data="adm_group"), InlineKeyboardButton(text="Channel", callback_data="adm_channel")],
        [InlineKeyboardButton(text="Close", callback_data="close_menu")]
    ])

def group_settings_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Regulation", callback_data=f"gs_reg_{chat_id}"), InlineKeyboardButton(text="Anti-Spam", callback_data=f"gs_spam_{chat_id}")],
        [InlineKeyboardButton(text="Welcome", callback_data=f"gs_welcome_{chat_id}"), InlineKeyboardButton(text="Anti-Flood", callback_data=f"gs_flood_{chat_id}")],
        [InlineKeyboardButton(text="Goodbye", callback_data=f"gs_goodbye_{chat_id}"), InlineKeyboardButton(text="Alphabets", callback_data=f"gs_alphabets_{chat_id}")],
        [InlineKeyboardButton(text="Captcha", callback_data=f"gs_captcha_{chat_id}"), InlineKeyboardButton(text="Checks", callback_data=f"gs_checks_{chat_id}")],
        [InlineKeyboardButton(text="Admin", callback_data=f"gs_admin_{chat_id}"), InlineKeyboardButton(text="Blocks", callback_data=f"gs_blocks_{chat_id}")],
        [InlineKeyboardButton(text="Media", callback_data=f"gs_media_{chat_id}"), InlineKeyboardButton(text="Porn", callback_data=f"gs_porn_{chat_id}")],
        [InlineKeyboardButton(text="Warns", callback_data=f"gs_warns_{chat_id}"), InlineKeyboardButton(text="Night", callback_data=f"gs_night_{chat_id}")],
        [InlineKeyboardButton(text="Tag", callback_data=f"gs_tag_{chat_id}"), InlineKeyboardButton(text="Link", callback_data=f"gs_link_{chat_id}")],
        [InlineKeyboardButton(text="Banned Words", callback_data=f"gs_bwords_{chat_id}"), InlineKeyboardButton(text="Recurring message", callback_data=f"gs_recurring_{chat_id}")],
        [InlineKeyboardButton(text="Masked users", callback_data=f"gs_masked_{chat_id}"), InlineKeyboardButton(text="Message length", callback_data=f"gs_mlen_{chat_id}")],
        [InlineKeyboardButton(text="Personal Commands", callback_data=f"gs_pcommands_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data="admin_manage_groups"), InlineKeyboardButton(text="Close", callback_data="close_menu")]
    ])

def anti_flood_menu_kb(chat_id: int, limit=3, time_sec=2, action="warn", del_msg=1):
    off_check = "✅ " if action == "off" else ""
    warn_check = "✅ " if action == "warn" else ""
    kick_check = "✅ " if action == "kick" else ""
    mute_check = "✅ " if action == "mute" else ""
    ban_check = "✅ " if action == "ban" else ""
    del_check = "✅" if del_msg else "❌"

    punishment_str = action.upper()
    if del_msg:
        punishment_str += " + DELETION"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Messages", callback_data=f"af_msgs_{chat_id}"), InlineKeyboardButton(text="Time", callback_data=f"af_time_{chat_id}")],
        [InlineKeyboardButton(text=f"{off_check}Off", callback_data=f"af_act_off_{chat_id}"), InlineKeyboardButton(text=f"{warn_check}Warn", callback_data=f"af_act_warn_{chat_id}")],
        [InlineKeyboardButton(text=f"{kick_check}Kick", callback_data=f"af_act_kick_{chat_id}"), InlineKeyboardButton(text=f"{mute_check}Mute", callback_data=f"af_act_mute_{chat_id}"), InlineKeyboardButton(text=f"{ban_check}Ban", callback_data=f"af_act_ban_{chat_id}")],
        [InlineKeyboardButton(text=f"Delete Messages {del_check}", callback_data=f"af_del_{chat_id}")],
        [InlineKeyboardButton(text="Set mute duration", callback_data=f"af_mdur_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def af_messages_selector_kb(chat_id: int):
    nums = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20]
    buttons = []
    row = []
    for n in nums:
        row.append(InlineKeyboardButton(text=str(n), callback_data=f"af_setmsg_{n}_{chat_id}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Back", callback_data=f"gs_flood_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def af_time_selector_kb(chat_id: int):
    secs = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20]
    buttons = []
    row = []
    for s in secs:
        row.append(InlineKeyboardButton(text=str(s), callback_data=f"af_settime_{s}_{chat_id}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Back", callback_data=f"gs_flood_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def warns_limit_selector_kb(chat_id: int, current_max: int):
    buttons = []
    row = []
    for i in range(1, 11):
        check = "✅ " if i == current_max else ""
        row.append(InlineKeyboardButton(text=f"{check}{i}", callback_data=f"w_setmax_{i}_{chat_id}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Back", callback_data=f"gs_flood_{chat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def link_protection_menu_kb(chat_id: int, status: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Status: {'Turn On ✅' if status else 'Turn Off ❌'}", callback_data=f"lnk_toggle_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def porn_protection_menu_kb(chat_id: int, status: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Status: {'Turn On ✅' if status else 'Turn Off ❌'}", callback_data=f"porn_toggle_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def banned_words_menu_kb(chat_id: int, action="off", del_msg=1, count=0):
    off_c = "✅ " if action == "off" else ""
    warn_c = "✅ " if action == "warn" else ""
    kick_c = "✅ " if action == "kick" else ""
    mute_c = "✅ " if action == "mute" else ""
    ban_c = "✅ " if action == "ban" else ""
    del_c = "✅" if del_msg else "❌"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{off_c}Off", callback_data=f"bw_act_off_{chat_id}"), InlineKeyboardButton(text=f"{warn_c}Warn", callback_data=f"bw_act_warn_{chat_id}"), InlineKeyboardButton(text=f"{kick_c}Kick", callback_data=f"bw_act_kick_{chat_id}")],
        [InlineKeyboardButton(text=f"{mute_c}Mute", callback_data=f"bw_act_mute_{chat_id}"), InlineKeyboardButton(text=f"{ban_c}Ban", callback_data=f"bw_act_ban_{chat_id}")],
        [InlineKeyboardButton(text=f"Delete Messages {del_c}", callback_data=f"bw_del_{chat_id}")],
        [InlineKeyboardButton(text="Add", callback_data=f"bw_add_{chat_id}"), InlineKeyboardButton(text="Remove", callback_data=f"bw_rem_{chat_id}")],
        [InlineKeyboardButton(text="List", callback_data=f"bw_list_{chat_id}")],
        [InlineKeyboardButton(text=f"{count} Banned Words", callback_data=f"bw_list_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def personal_commands_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Personal Commands", callback_data=f"pc_cmd_{chat_id}")],
        [InlineKeyboardButton(text="User Command", callback_data=f"pc_rep_{chat_id}")],
        [InlineKeyboardButton(text="User Incline Button", callback_data=f"pc_alias_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

# --- Helper Check for Admin Status ---
async def is_user_admin(message: types.Message) -> bool:
    if message.chat.type == "private":
        return True
    try:
        member = await message.chat.get_member(message.from_user.id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False

# --- Core Action Execution & Notifications ---
async def handle_user_violation(bot: Bot, chat_id: int, user: types.User, action_type: str, custom_reason: str = ""):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT max_warns, mute_duration FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    max_w = res[0] if res else 3
    mute_dur = res[1] if res else 600

    user_mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"
    user_tag_str = f"{user_mention} [{user.id}]"

    if action_type == "warn":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT warn_count FROM user_warn_counts WHERE user_id = ? AND chat_id = ?", (user.id, chat_id)) as cursor:
                row = await cursor.fetchone()
            current_warns = (row[0] if row else 0) + 1
            
            if current_warns >= max_w:
                await db.execute("DELETE FROM user_warn_counts WHERE user_id = ? AND chat_id = ?", (user.id, chat_id))
                await db.commit()
                
                try:
                    await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
                except Exception:
                    pass
                
                unban_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Unban", callback_data=f"mod_unban_{user.id}_{chat_id}")]
                ])
                await bot.send_message(
                    chat_id, 
                    f"{user_tag_str} banned.\n(Max warns reached)", 
                    reply_markup=unban_kb, 
                    parse_mode="HTML"
                )
                try:
                    appeal_link = f"https://t.me/{(await bot.get_me()).username}?start=appeal_{chat_id}"
                    await bot.send_message(user.id, f"Aapko group se ban kar diya gaya hai. Agar aapko appeal karni hai toh is link par click karein: {appeal_link}")
                except Exception:
                    pass
                return

            await db.execute("INSERT OR REPLACE INTO user_warn_counts (user_id, chat_id, warn_count) VALUES (?, ?, ?)", (user.id, chat_id, current_warns))
            await db.commit()

        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"mod_unwarn_{user.id}_{chat_id}")]
        ])
        await bot.send_message(
            chat_id, 
            f"{user_tag_str} warned ({current_warns} of {max_w}).", 
            reply_markup=cancel_kb, 
            parse_mode="HTML"
        )

    elif action_type == "mute":
        try:
            permissions = types.ChatPermissions(can_send_messages=False)
            await bot.restrict_chat_member(chat_id=chat_id, user_id=user.id, permissions=permissions, until_date=int(time.time() + mute_dur))
        except Exception:
            pass
        
        mute_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🕹 Permissions", callback_data=f"mod_perms_{user.id}_{chat_id}"),
             InlineKeyboardButton(text="✅ Unmute", callback_data=f"mod_unmute_{user.id}_{chat_id}")]
        ])
        await bot.send_message(
            chat_id, 
            f"{user_tag_str} has been muted.", 
            reply_markup=mute_kb, 
            parse_mode="HTML"
        )

    elif action_type == "ban":
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
        except Exception:
            pass

        unban_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Unban", callback_data=f"mod_unban_{user.id}_{chat_id}")]
        ])
        await bot.send_message(
            chat_id, 
            f"{user_tag_str} banned.", 
            reply_markup=unban_kb, 
            parse_mode="HTML"
        )
        try:
            appeal_link = f"https://t.me/{(await bot.get_me()).username}?start=appeal_{chat_id}"
            await bot.send_message(user.id, f"Aapko group se ban kar diya gaya hai. Agar aapko appeal karni hai toh is link par click karein: {appeal_link}")
        except Exception:
            pass

    elif action_type == "kick":
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            await bot.unban_chat_member(chat_id=chat_id, user_id=user.id)
        except Exception:
            pass
        await bot.send_message(
            chat_id, 
            f"{user_tag_str} has been kicked.", 
            parse_mode="HTML"
        )

# --- Callback Handlers for Moderation Inline Buttons ---
@dp.callback_query(F.data.startswith("mod_unwarn_"))
async def cb_mod_unwarn(cb: types.CallbackQuery):
    if not await is_user_admin(cb):
        await cb.answer("Only admins can cancel warns!", show_alert=True)
        return
    parts = cb.data.split("_")
    user_id = int(parts[2])
    chat_id = int(parts[3])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM user_warn_counts WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
        await db.commit()
    await cb.message.edit_text(f"{cb.message.text}\n\n~ Warn cancelled by admin", reply_markup=None)
    await cb.answer("Warn removed!")

@dp.callback_query(F.data.startswith("mod_unmute_"))
async def cb_mod_unmute(cb: types.CallbackQuery):
    if not await is_user_admin(cb):
        await cb.answer("Only admins can unmute users!", show_alert=True)
        return
    parts = cb.data.split("_")
    user_id = int(parts[2])
    chat_id = int(parts[3])
    try:
        permissions = types.ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=permissions)
    except Exception:
        pass
    await cb.message.edit_text(f"{cb.message.text}\n\n~ User unmuted", reply_markup=None)
    await cb.answer("User unmuted successfully!")

@dp.callback_query(F.data.startswith("mod_unban_"))
async def cb_mod_unban(cb: types.CallbackQuery):
    if not await is_user_admin(cb):
        await cb.answer("Only admins can unban users!", show_alert=True)
        return
    parts = cb.data.split("_")
    user_id = int(parts[2])
    chat_id = int(parts[3])
    try:
        await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
    except Exception:
        pass
    await cb.message.edit_text(f"{cb.message.text}\n\n~ User unbanned", reply_markup=None)
    await cb.answer("User unbanned successfully!")

# --- Handlers: Start & Menu ---
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.chat.type == "private":
        args = msg.text.split()
        if len(args) > 1 and args[1].startswith("appeal_"):
            chat_id = args[1].split("_")[1]
            await msg.answer(f"Aapne group ({chat_id}) ke ban ke khilaf appeal karne ke liye chat kholi hai. Kripya apna appeal reason yahan type karein:")
            return
        banner_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"
        caption = "Welcome to Appeal X Bot\nSelect an option below:"
        await msg.answer_photo(photo=banner_url, caption=caption, reply_markup=user_start_kb(), parse_mode="Markdown")

@dp.message(Command("claim"))
async def cmd_claim(msg: types.Message, state: FSMContext):
    if msg.chat.type == "private":
        await msg.answer("Please enter Admin Access Key:")
        await state.set_state(BotStates.admin_pass)

@dp.message(BotStates.admin_pass)
async def process_admin_key(msg: types.Message, state: FSMContext):
    if msg.text == SECRET_PASS:
        try:
            await msg.delete()
        except Exception:
            pass
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO admin_claims (user_id) VALUES (?)", (msg.from_user.id,))
            await db.commit()
        await state.clear()
        
        banner_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"
        await msg.answer_photo(
            photo=banner_url,
            caption="Manage Groups\nSelect an option below:",
            reply_markup=main_admin_panel_kb(),
            parse_mode="Markdown"
        )
    else:
        await msg.answer("Incorrect Password! Access Denied.")
        await state.clear()

@dp.message(Command("setting"))
async def cmd_setting(msg: types.Message):
    if msg.chat.type == "private":
        if not await is_claimed_admin(msg.from_user.id):
            await msg.answer("Access denied! Please use /claim first.")
            return
        banner_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"
        await msg.answer_photo(
            photo=banner_url,
            caption="Manage Groups\nSelect an option below:",
            reply_markup=main_admin_panel_kb(),
            parse_mode="Markdown"
        )

@dp.callback_query(F.data == "admin_manage_groups")
async def cb_manage_groups(cb: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT chat_id, title FROM managed_groups") as cursor:
            groups = await cursor.fetchall()
    
    if not groups:
        await cb.answer("No groups registered! First add the bot to a group.", show_alert=True)
        return
        
    await cb.message.edit_caption(
        caption="Manage Groups\nSelect the group whose settings you want to change:",
        reply_markup=group_selector_kb(groups),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("select_group_") & ~F.data.contains("gs_"))
async def cb_select_group_settings(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
    title = row[0] if row else "Group"
    
    await cb.message.edit_caption(
        caption=f"SETTINGS\nGroup: {title}\n\nSelect one of the settings that you want to change:",
        reply_markup=group_settings_menu_kb(chat_id),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("gs_"))
async def cb_group_setting_action(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    action = parts[1]
    chat_id = int(parts[2])
    
    if action == "flood":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT flood_limit, flood_time, antiflood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        limit, time_sec, act, del_m = res if res else (3, 2, "warn", 1)
        punishment_text = act.upper()
        if del_m:
            punishment_text += " + DELETION"
        await cb.message.edit_caption(
            caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent in {time_sec} seconds.\nPunishment: {punishment_text}",
            reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, act, del_m), parse_mode="Markdown"
        )
    elif action == "link":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT link_protection FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        status = res[0] if res else 0
        await cb.message.edit_caption(
            caption=f"Link Protection\nAuto-delete all links sent by non-admin users and warn them.\nStatus: {'Turned On' if status else 'Turned Off'}",
            reply_markup=link_protection_menu_kb(chat_id, status), parse_mode="Markdown"
        )
    elif action == "porn":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT porn_protection FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        status = res[0] if res else 0
        await cb.message.edit_caption(
            caption=f"Porn / Media Protection\nAuto-delete media/videos and auto-ban users.\nStatus: {'Turned On' if status else 'Turned Off'}",
            reply_markup=porn_protection_menu_kb(chat_id, status), parse_mode="Markdown"
        )
    elif action == "bwords":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT action, delete_msgs FROM banned_words_config WHERE chat_id = ?", (chat_id,)) as cursor:
                bw_conf = await cursor.fetchone()
            async with db.execute("SELECT COUNT(*) FROM banned_words_list WHERE chat_id = ?", (chat_id,)) as cursor:
                cnt = await cursor.fetchone()
        act = bw_conf[0] if bw_conf else "off"
        del_m = bw_conf[1] if bw_conf else 1
        total_words = cnt[0] if cnt else 0
        await cb.message.edit_caption(
            caption=f"Banned Words\nManage custom banned words and penalty.\nPenalty: {act.upper()}\nDeletion: {'Yes' if del_m else 'No'}",
            reply_markup=banned_words_menu_kb(chat_id, act, del_m, total_words), parse_mode="Markdown"
        )
    elif action == "pcommands":
        await cb.message.edit_caption(
            caption="Personal Commands, User Command, User Incline Button\nSelect an option below:",
            reply_markup=personal_commands_menu_kb(chat_id), parse_mode="Markdown"
        )
    else:
        await cb.answer(f"Opening {action.upper()} settings...", show_alert=False)

# Antiflood sub-menu interactions
@dp.callback_query(F.data.startswith("af_msgs_"))
async def cb_af_msgs(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT flood_limit, flood_time FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec = res if res else (3, 2)
    await cb.message.edit_caption(
        caption=f"From here you can select the maximum amount of sendable messages in the time interval.\nCurrently, the antiflood trigger when {limit} messages are sent in {time_sec} seconds.",
        reply_markup=af_messages_selector_kb(chat_id), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("af_setmsg_"))
async def cb_af_setmsg(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    new_limit = int(parts[2])
    chat_id = int(parts[3])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE managed_groups SET flood_limit = ? WHERE chat_id = ?", (new_limit, chat_id))
        await db.commit()
        async with db.execute("SELECT flood_limit, flood_time, antiflood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec, act, del_m = res
    punishment_text = act.upper()
    if del_m:
        punishment_text += " + DELETION"
    await cb.message.edit_caption(
        caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent in {time_sec} seconds.\nPunishment: {punishment_text}",
        reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, act, del_m), parse_mode="Markdown"
    )
    await cb.answer("Message limit updated!")

@dp.callback_query(F.data.startswith("af_time_"))
async def cb_af_time(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT flood_limit, flood_time FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec = res if res else (3, 2)
    await cb.message.edit_caption(
        caption=f"From here you can select the time interval considered to calculate the antiflood.\nCurrently, the antiflood trigger when {limit} messages are sent in {time_sec} seconds.",
        reply_markup=af_time_selector_kb(chat_id), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("af_settime_"))
async def cb_af_settime(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    new_time = int(parts[2])
    chat_id = int(parts[3])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE managed_groups SET flood_time = ? WHERE chat_id = ?", (new_time, chat_id))
        await db.commit()
        async with db.execute("SELECT flood_limit, flood_time, antiflood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec, act, del_m = res
    punishment_text = act.upper()
    if del_m:
        punishment_text += " + DELETION"
    await cb.message.edit_caption(
        caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent in {time_sec} seconds.\nPunishment: {punishment_text}",
        reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, act, del_m), parse_mode="Markdown"
    )
    await cb.answer("Time interval updated!")

@dp.callback_query(F.data.startswith("af_act_"))
async def cb_af_act(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    act = parts[2]
    chat_id = int(parts[3])
    if act == "warn":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT max_warns FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        max_w = res[0] if res else 3
        await cb.message.edit_caption(
            caption=f"Select maximum warns before banning the user.\nCurrent max warns: {max_w}",
            reply_markup=warns_limit_selector_kb(chat_id, max_w), parse_mode="Markdown"
        )
        await cb.answer("Select warn limit!")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE managed_groups SET antiflood_action = ? WHERE chat_id = ?", (act, chat_id))
        await db.commit()
        async with db.execute("SELECT flood_limit, flood_time, antiflood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec, action, del_m = res
    punishment_text = action.upper()
    if del_m:
        punishment_text += " + DELETION"
    
    try:
        await cb.message.edit_caption(
            caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent in {time_sec} seconds.\nPunishment: {punishment_text}",
            reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, action, del_m), parse_mode="Markdown"
        )
    except Exception:
        await cb.message.edit_reply_markup(reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, action, del_m))
    
    await cb.answer(f"Punishment set to {act.upper()}!")

@dp.callback_query(F.data.startswith("w_setmax_"))
async def cb_w_setmax(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    max_w = int(parts[2])
    chat_id = int(parts[3])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE managed_groups SET max_warns = ?, antiflood_action = 'warn' WHERE chat_id = ?", (max_w, chat_id))
        await db.commit()
        async with db.execute("SELECT flood_limit, flood_time, antiflood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec, action, del_m = res
    punishment_text = f"WARN (Max: {max_w})"
    if del_m:
        punishment_text += " + DELETION"
    await cb.message.edit_caption(
        caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent in {time_sec} seconds.\nPunishment: {punishment_text}",
        reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, action, del_m), parse_mode="Markdown"
    )
    await cb.answer(f"Max warns set to {max_w}!")

@dp.callback_query(F.data.startswith("af_del_"))
async def cb_af_del(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT flood_del, flood_limit, flood_time, antiflood_action, max_warns FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
        new_del = 0 if res[0] else 1
        await db.execute("UPDATE managed_groups SET flood_del = ? WHERE chat_id = ?", (new_del, chat_id))
        await db.commit()
    limit, time_sec, action, max_w = res[1], res[2], res[3], res[4]
    punishment_text = action.upper()
    if action == "warn":
        punishment_text += f" (Max: {max_w})"
    if new_del:
        punishment_text += " + DELETION"
    
    try:
        await cb.message.edit_caption(
            caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent in {time_sec} seconds.\nPunishment: {punishment_text}",
            reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, action, new_del), parse_mode="Markdown"
        )
    except Exception:
        await cb.message.edit_reply_markup(reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, action, new_del))
    
    await cb.answer("Delete option updated!")

# Link Protection Toggle
@dp.callback_query(F.data.startswith("lnk_toggle_"))
async def cb_lnk_toggle(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT link_protection FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
        new_status = 0 if res and res[0] else 1
        await db.execute("UPDATE managed_groups SET link_protection = ? WHERE chat_id = ?", (new_status, chat_id))
        await db.commit()
    await cb.message.edit_reply_markup(reply_markup=link_protection_menu_kb(chat_id, new_status))
    await cb.answer(f"Link protection turned {'on' if new_status else 'off'}!")

# Porn Protection Toggle
@dp.callback_query(F.data.startswith("porn_toggle_"))
async def cb_porn_toggle(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT porn_protection FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
        new_status = 0 if res and res[0] else 1
        await db.execute("UPDATE managed_groups SET porn_protection = ? WHERE chat_id = ?", (new_status, chat_id))
        await db.commit()
    await cb.message.edit_reply_markup(reply_markup=porn_protection_menu_kb(chat_id, new_status))
    await cb.answer(f"Porn/Media protection turned {'on' if new_status else 'off'}!")

# Banned Words Submenu Handlers
@dp.callback_query(F.data.startswith("bw_act_"))
async def cb_bw_act(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    act = parts[2]
    chat_id = int(parts[3])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO banned_words_config (chat_id, action) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET action = ?", (chat_id, act, act))
        await db.commit()
        async with db.execute("SELECT action, delete_msgs FROM banned_words_config WHERE chat_id = ?", (chat_id,)) as cursor:
            conf = await cursor.fetchone()
        async with db.execute("SELECT COUNT(*) FROM banned_words_list WHERE chat_id = ?", (chat_id,)) as cursor:
            cnt = await cursor.fetchone()
    act_v, del_v, total_w = conf[0], conf[1], cnt[0]
    await cb.message.edit_reply_markup(reply_markup=banned_words_menu_kb(chat_id, act_v, del_v, total_w))
    await cb.answer(f"Banned words penalty set to {act.upper()}!")

@dp.callback_query(F.data.startswith("bw_del_"))
async def cb_bw_del(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT action, delete_msgs FROM banned_words_config WHERE chat_id = ?", (chat_id,)) as cursor:
            conf = await cursor.fetchone()
        old_del = conf[1] if conf else 1
        new_del = 0 if old_del else 1
        act_v = conf[0] if conf else "off"
        await db.execute("INSERT INTO banned_words_config (chat_id, delete_msgs) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET delete_msgs = ?", (chat_id, new_del, new_del))
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM banned_words_list WHERE chat_id = ?", (chat_id,)) as cursor:
            cnt = await cursor.fetchone()
    total_w = cnt[0] if cnt else 0
    await cb.message.edit_reply_markup(reply_markup=banned_words_menu_kb(chat_id, act_v, new_del, total_w))
    await cb.answer("Banned words deletion toggled!")

@dp.callback_query(F.data.startswith("bw_list_"))
async def cb_bw_list(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT word FROM banned_words_list WHERE chat_id = ?", (chat_id,)) as cursor:
            rows = await cursor.fetchall()
    words = [r[0] for r in rows]
    txt = "Banned Words List:\n\n" + (", ".join(words) if words else "No banned words added yet.")
    await cb.answer(txt, show_alert=True)

@dp.callback_query(F.data.startswith("bw_add_"))
async def cb_bw_add(cb: types.CallbackQuery, state: FSMContext):
    chat_id = int(cb.data.split("_")[2])
    await state.update_data(bw_chat_id=chat_id)
    await state.set_state(BotStates.adding_banned_word)
    await cb.message.answer("Kripya naya banned word type karein jo aap list me add karna chahte hain:")
    await cb.answer()

@dp.message(BotStates.adding_banned_word)
async def process_add_banned_word(msg: types.Message, state: FSMContext):
    word = (msg.text or "").strip().lower()
    if not word:
        await msg.reply("Valid word type karein:")
        return
    data = await state.get_data()
    chat_id = data.get("bw_chat_id")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO banned_words_list (chat_id, word) VALUES (?, ?)", (chat_id, word))
        await db.commit()
    await state.clear()
    await msg.reply(f"Word '{word}' successfully banned list me add kar diya gaya hai!")

@dp.callback_query(F.data.startswith("bw_rem_"))
async def cb_bw_rem(cb: types.CallbackQuery, state: FSMContext):
    chat_id = int(cb.data.split("_")[2])
    await state.update_data(bw_chat_id=chat_id)
    await state.set_state(BotStates.removing_banned_word)
    await cb.message.answer("Kripya woh word type karein jise aap banned list se hatana (remove) chahte hain:")
    await cb.answer()

@dp.message(BotStates.removing_banned_word)
async def process_remove_banned_word(msg: types.Message, state: FSMContext):
    word = (msg.text or "").strip().lower()
    data = await state.get_data()
    chat_id = data.get("bw_chat_id")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM banned_words_list WHERE chat_id = ? AND word = ?", (chat_id, word))
        await db.commit()
    await state.clear()
    await msg.reply(f"Word '{word}' list se hata diya gaya hai!")

# --- Personal Commands Submenu Handlers ---
@dp.callback_query(F.data.startswith("pc_cmd_"))
async def cb_pc_cmd(cb: types.CallbackQuery, state: FSMContext):
    chat_id = int(cb.data.split("_")[2])
    await state.update_data(pc_chat_id=chat_id)
    await state.set_state(BotStates.setting_pcmd_trigger)
    await cb.message.answer("Personal Command setup: Abhi woh trigger word ya command type karein (jaise 'bmc'):")
    await cb.answer()

@dp.message(BotStates.setting_pcmd_trigger)
async def process_pcmd_trigger(msg: types.Message, state: FSMContext):
    trg = (msg.text or "").strip().lower()
    await state.update_data(pcmd_trg=trg)
    await state.set_state(BotStates.setting_pcmd_reply)
    await msg.reply("Ab is trigger ke badle bot jo reply text bhejeega, woh type karein:")

@dp.message(BotStates.setting_pcmd_reply)
async def process_pcmd_reply(msg: types.Message, state: FSMContext):
    rep = msg.text or ""
    data = await state.get_data()
    chat_id = data.get("pc_chat_id")
    trg = data.get("pcmd_trg")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO custom_commands (chat_id, trigger_word, reply_text) VALUES (?, ?, ?)", (chat_id, trg, rep))
        await db.commit()
    await state.clear()
    await msg.reply(f"Personal Command '{trg}' successfully save ho gaya hai!")

@dp.callback_query(F.data.startswith("pc_rep_"))
async def cb_pc_rep(cb: types.CallbackQuery, state: FSMContext):
    chat_id = int(cb.data.split("_")[2])
    await state.update_data(uc_chat_id=chat_id)
    await state.set_state(BotStates.setting_ucmd_trigger)
    await cb.message.answer("User Command setup: User ke liye trigger word type karein (jaise 'mm' ya 'gv'):")
    await cb.answer()

@dp.message(BotStates.setting_ucmd_trigger)
async def process_ucmd_trigger(msg: types.Message, state: FSMContext):
    trg = (msg.text or "").strip().lower()
    await state.update_data(ucmd_trg=trg)
    await state.set_state(BotStates.setting_ucmd_reply)
    await msg.reply("Ab is user command ke liye reply text type karein:")

@dp.message(BotStates.setting_ucmd_reply)
async def process_ucmd_reply(msg: types.Message, state: FSMContext):
    rep = msg.text or ""
    data = await state.get_data()
    chat_id = data.get("uc_chat_id")
    trg = data.get("ucmd_trg")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO user_commands (chat_id, trigger_word, reply_text) VALUES (?, ?, ?)", (chat_id, trg, rep))
        await db.commit()
    await state.clear()
    await msg.reply(f"User Command '{trg}' successfully save ho gaya hai!")

@dp.callback_query(F.data.startswith("pc_alias_"))
async def cb_pc_alias(cb: types.CallbackQuery, state: FSMContext):
    chat_id = int(cb.data.split("_")[2])
    await state.update_data(inline_chat_id=chat_id)
    await state.set_state(BotStates.setting_inline_trigger)
    await cb.message.answer("User Incline Button setup: Trigger word type karein (jaise 'panel'):")
    await cb.answer()

@dp.message(BotStates.setting_inline_trigger)
async def process_inline_trigger(msg: types.Message, state: FSMContext):
    trg = (msg.text or "").strip().lower()
    await state.update_data(inline_trg=trg)
    await state.set_state(BotStates.setting_inline_reply)
    await msg.reply("Ab is trigger ke sath main message text kya bheja jaye, woh type karein:")

@dp.message(BotStates.setting_inline_reply)
async def process_inline_reply(msg: types.Message, state: FSMContext):
    rep = msg.text or ""
    await state.update_data(inline_rep=rep)
    await state.set_state(BotStates.setting_inline_buttons)
    await msg.reply("Ab inline buttons format me bhejein (Format: ButtonName | URL per line, jaise:\nPanel 1 | https://t.me/...\nPanel 2 | https://t.me/...)")

@dp.message(BotStates.setting_inline_buttons)
async def process_inline_buttons(msg: types.Message, state: FSMContext):
    raw_btns = msg.text or ""
    data = await state.get_data()
    chat_id = data.get("inline_chat_id")
    trg = data.get("inline_trg")
    rep = data.get("inline_rep")

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("INSERT INTO inline_buttons_config (chat_id, trigger_word, reply_text) VALUES (?, ?, ?)", (chat_id, trg, rep))
        cfg_id = cursor.lastrowid
        
        for line in raw_btns.split("\n"):
            if "|" in line:
                b_name, b_url = line.split("|", 1)
                await db.execute("INSERT INTO inline_buttons_items (config_id, button_name, button_url) VALUES (?, ?, ?)", (cfg_id, b_name.strip(), b_url.strip()))
        await db.commit()

    await state.clear()
    await msg.reply("User Incline Button configuration successfully save ho gayi hai!")

@dp.callback_query(F.data.startswith(("mu_", "pc_")))
async def cb_other_submenus(cb: types.CallbackQuery):
    await cb.answer("Setting updated successfully!", show_alert=False)

# --- Direct Group Moderation Commands (/ban, /mute, /warn, etc.) ---
@dp.message(Command("userid"))
async def cmd_userid(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    await msg.reply(f"User ID for {target.first_name}: `{target.id}`", parse_mode="Markdown")

@dp.message(Command("ban"))
async def cmd_ban(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    if not await is_user_admin(msg):
        await msg.reply("This command is only for group admins!")
        return
    if not msg.reply_to_message:
        await msg.reply("Please reply to a user's message to ban.")
        return
    target_user = msg.reply_to_message.from_user
    await handle_user_violation(bot, msg.chat.id, target_user, "ban")

@dp.message(Command("mute"))
async def cmd_mute(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    if not await is_user_admin(msg):
        await msg.reply("This command is only for group admins!")
        return
    if not msg.reply_to_message:
        await msg.reply("Please reply to a user's message to mute.")
        return
    target_user = msg.reply_to_message.from_user
    await handle_user_
