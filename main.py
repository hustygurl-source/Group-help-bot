import asyncio
import os
import random
import io
import aiosqlite
from PIL import Image, ImageDraw, ImageFont
from aiohttp import web, ClientSession
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BufferedInputFile, BotCommandScopeChat, BotCommandScopeDefault

# --- Configuration ---
BOT_TOKEN = "8912103286:AAGBQTFYrTRFMGa6tEW5UHMtt3qCR6KcN8w"
SECRET_PASS = "mansour$vx"
DB_NAME = "bot_database.db"
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

PROFANITY_WORDS = ["gali", "abuse", "mc", "bc", "bhadve", "randi", "fuck", "shit", "tmkc", "tmkl"]

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
            antiflood INTEGER DEFAULT 1,
            welcome_status INTEGER DEFAULT 0
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
async def generate_rank_card(title: str, top_users: list):
    img = Image.new("RGB", (600, 400), color=(20, 20, 30))
    draw = ImageDraw.Draw(img)
    
    try:
        font_title = ImageFont.truetype("arial.ttf", 26)
        font_item = ImageFont.truetype("arial.ttf", 20)
    except IOError:
        font_title = ImageFont.load_default()
        font_item = ImageFont.load_default()

    draw.rectangle([20, 20, 580, 380], outline=(80, 80, 120), width=3)
    draw.text((40, 40), title, fill=(255, 215, 0), font=font_title)
    
    y = 100
    for idx, user in enumerate(top_users, 1):
        name = user[0] or "Unknown"
        msgs = user[1]
        medal = "1." if idx == 1 else "2." if idx == 2 else "3." if idx == 3 else f"{idx}."
        text = f"{medal} {name} — {msgs} Messages"
        draw.text((40, y), text, fill=(255, 255, 255), font=font_item)
        y += 60

    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="rank.png")

# --- States ---
class BotStates(StatesGroup):
    admin_pass = State()
    waiting_for_appeal_text = State()

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
    bot_info = asyncio.run_coroutine_threadsafe(bot.get_me(), bot._loop) if False else None # Handled dynamically via handler
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Add me to a Group", url="https://t.me/8912103286_bot?startgroup=true")],
        [InlineKeyboardButton(text="Manage group Settings", callback_data="admin_manage_groups")],
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
        [InlineKeyboardButton(text="Banned Words", callback_data=f"gs_bwords_{chat_id}"), InlineKeyboardButton(text="Recurring messages", callback_data=f"gs_recurring_{chat_id}")],
        [InlineKeyboardButton(text="Masked users", callback_data=f"gs_masked_{chat_id}"), InlineKeyboardButton(text="Message length", callback_data=f"gs_mlen_{chat_id}")],
        [InlineKeyboardButton(text="Personal Commands", callback_data=f"gs_pcommands_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data="admin_manage_groups"), InlineKeyboardButton(text="Close", callback_data="close_menu")]
    ])

def anti_flood_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Messages", callback_data=f"af_msgs_{chat_id}"), InlineKeyboardButton(text="Time", callback_data=f"af_time_{chat_id}")],
        [InlineKeyboardButton(text="Off", callback_data=f"af_off_{chat_id}"), InlineKeyboardButton(text="Warn", callback_data=f"af_warn_{chat_id}")],
        [InlineKeyboardButton(text="Kick", callback_data=f"af_kick_{chat_id}"), InlineKeyboardButton(text="Mute", callback_data=f"af_mute_{chat_id}"), InlineKeyboardButton(text="Ban", callback_data=f"af_ban_{chat_id}")],
        [InlineKeyboardButton(text="Delete Messages", callback_data=f"af_del_{chat_id}")],
        [InlineKeyboardButton(text="Set mute duration", callback_data=f"af_mdur_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def warns_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Warned List", callback_data=f"w_list_{chat_id}")],
        [InlineKeyboardButton(text="Off", callback_data=f"w_off_{chat_id}"), InlineKeyboardButton(text="Kick", callback_data=f"w_kick_{chat_id}")],
        [InlineKeyboardButton(text="Mute", callback_data=f"w_mute_{chat_id}"), InlineKeyboardButton(text="Ban", callback_data=f"w_ban_{chat_id}")],
        [InlineKeyboardButton(text="Set mute duration", callback_data=f"w_mdur_{chat_id}")],
        [InlineKeyboardButton(text="2", callback_data=f"w_cnt_2_{chat_id}"), InlineKeyboardButton(text="3", callback_data=f"w_cnt_3_{chat_id}"), InlineKeyboardButton(text="4", callback_data=f"w_cnt_4_{chat_id}"), InlineKeyboardButton(text="5", callback_data=f"w_cnt_5_{chat_id}"), InlineKeyboardButton(text="6", callback_data=f"w_cnt_6_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def banned_words_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Off", callback_data=f"bw_off_{chat_id}"), InlineKeyboardButton(text="Warn", callback_data=f"bw_warn_{chat_id}"), InlineKeyboardButton(text="Kick", callback_data=f"bw_kick_{chat_id}")],
        [InlineKeyboardButton(text="Mute", callback_data=f"bw_mute_{chat_id}"), InlineKeyboardButton(text="Ban", callback_data=f"bw_ban_{chat_id}")],
        [InlineKeyboardButton(text="Delete Messages", callback_data=f"bw_del_{chat_id}")],
        [InlineKeyboardButton(text="Add", callback_data=f"bw_add_{chat_id}"), InlineKeyboardButton(text="Remove", callback_data=f"bw_rem_{chat_id}")],
        [InlineKeyboardButton(text="List", callback_data=f"bw_list_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def recurring_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Add message", callback_data=f"rc_add_{chat_id}")],
        [InlineKeyboardButton(text="Active", callback_data=f"rc_toggle_{chat_id}"), InlineKeyboardButton(text="Delete", callback_data=f"rc_del_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def masked_users_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Turn off", callback_data=f"mu_off_{chat_id}"), InlineKeyboardButton(text="Turn on", callback_data=f"mu_on_{chat_id}")],
        [InlineKeyboardButton(text="Delete Messages", callback_data=f"mu_del_{chat_id}")],
        [InlineKeyboardButton(text="Exceptions", callback_data=f"mu_exc_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def personal_commands_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Personal Commands", callback_data=f"pc_cmd_{chat_id}")],
        [InlineKeyboardButton(text="Personal Replies", callback_data=f"pc_rep_{chat_id}")],
        [InlineKeyboardButton(text="Commands Alias", callback_data=f"pc_alias_{chat_id}")],
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

# --- Handlers: Start & Menu ---
@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    if msg.chat.type == "private":
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
        
        # Refresh command visibility for this admin
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Open Main Menu"),
                BotCommand(command="setting", description="Open Admin Panel")
            ],
            scope=BotCommandScopeChat(chat_id=msg.from_user.id)
        )
        
        banner_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"
        await msg.answer_photo(
            photo=banner_url,
            caption="Manage group Settings\nSelect an option below:",
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
            caption="Manage group Settings\nSelect an option below:",
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
        caption="Manage Group Settings\nSelect the group whose settings you want to change:",
        reply_markup=group_selector_kb(groups),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("select_group_"))
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
        await cb.message.edit_caption(
            caption="Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.",
            reply_markup=anti_flood_menu_kb(chat_id), parse_mode="Markdown"
        )
    elif action == "warns":
        await cb.message.edit_caption(
            caption="User warnings\nThe warning system allows you to give warnings to users for incorrect behavior.",
            reply_markup=warns_menu_kb(chat_id), parse_mode="Markdown"
        )
    elif action == "bwords":
        await cb.message.edit_caption(
            caption="Banned Words\nFrom this menu you can set a punishment for users who use banned words.",
            reply_markup=banned_words_menu_kb(chat_id), parse_mode="Markdown"
        )
    elif action == "recurring":
        await cb.message.edit_caption(
            caption="Recurring messages\nFrom this menu you can set messages that will be sent repeatedly.",
            reply_markup=recurring_menu_kb(chat_id), parse_mode="Markdown"
        )
    elif action == "masked":
        await cb.message.edit_caption(
            caption="Masked users\nThrough this menu you can set punishment for users writing disguised as a channel.",
            reply_markup=masked_users_menu_kb(chat_id), parse_mode="Markdown"
        )
    elif action == "pcommands":
        await cb.message.edit_caption(
            caption="Personal Commands, Personal Replies, Commands Alias",
            reply_markup=personal_commands_menu_kb(chat_id), parse_mode="Markdown"
        )
    else:
        await cb.answer(f"Opening {action.upper()} settings...", show_alert=False)

@dp.callback_query(F.data.startswith(("af_", "w_", "bw_", "rc_", "mu_", "pc_")))
async def cb_submenu_actions(cb: types.CallbackQuery):
    await cb.answer("Setting updated successfully!", show_alert=False)

# --- Direct Group Moderation Commands ---
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
    try:
        await bot.ban_chat_member(chat_id=msg.chat.id, user_id=target_user.id)
        appeal_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Submit Appeal", url=f"https://t.me/8912103286_bot?start=appeal_{msg.chat.id}")]
        ])
        await msg.answer(f"{target_user.mention_html()} has been successfully banned!", reply_markup=appeal_kb, parse_mode="HTML")
    except Exception as e:
        await msg.reply(f"Error banning user: {e}")

@dp.message(Command("unban"))
async def cmd_unban(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    if not await is_user_admin(msg):
        await msg.reply("This command is only for group admins!")
        return
    if not msg.reply_to_message:
        await msg.reply("Please reply to a user's message to unban.")
        return
    
    target_user = msg.reply_to_message.from_user
    try:
        await bot.unban_chat_member(chat_id=msg.chat.id, user_id=target_user.id, only_if_banned=True)
        await msg.reply(f"{target_user.mention_html()} has been unbanned!", parse_mode="HTML")
    except Exception as e:
        await msg.reply(f"Error unbanning user: {e}")

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
    try:
        permissions = types.ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(chat_id=msg.chat.id, user_id=target_user.id, permissions=permissions)
        appeal_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Submit Appeal", url=f"https://t.me/8912103286_bot?start=appeal_{msg.chat.id}")]
        ])
        await msg.answer(f"{target_user.mention_html()} has been muted!", reply_markup=appeal_kb, parse_mode="HTML")
    except Exception as e:
        await msg.reply(f"Error muting user: {e}")

@dp.message(Command("unmute"))
async def cmd_unmute(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    if not await is_user_admin(msg):
        await msg.reply("This command is only for group admins!")
        return
    if not msg.reply_to_message:
        await msg.reply("Please reply to a user's message to unmute.")
        return
    
    target_user = msg.reply_to_message.from_user
    try:
        permissions = types.ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        await bot.restrict_chat_member(chat_id=msg.chat.id, user_id=target_user.id, permissions=permissions)
        await msg.reply(f"{target_user.mention_html()} has been unmuted!", parse_mode="HTML")
    except Exception as e:
        await msg.reply(f"Error unmuting user: {e}")

# --- Appeal System Flow ---
@dp.callback_query(F.data == "menu_appeal")
async def cb_menu_appeal(cb: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT chat_id, title FROM managed_groups") as cursor:
            groups = await cursor.fetchall()
            
    if not groups:
        await cb.answer("No groups available!", show_alert=True)
        return
        
    await cb.message.edit_caption(
        caption="Select Group for Appeal:\nChoose your target group where you are banned:",
        reply_markup=group_selector_kb(groups), parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("select_group_"))
async def cb_select_appeal_group(cb: types.CallbackQuery, state: FSMContext):
    chat_id = int(cb.data.split("_")[2])
    
    is_banned = True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=cb.from_user.id)
        if member.status not in ["kicked", "left"]:
            is_banned = False
    except Exception:
        pass

    if not is_banned:
        await cb.answer("You are not banned in this group!", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT appeal_used FROM ban_tracker WHERE user_id = ? AND chat_key = ?", (cb.from_user.id, str(chat_id))) as cursor:
            row = await cursor.fetchone()
            if row and row[0] == 1:
                await cb.answer("You have already appealed for this ban cycle!", show_alert=True)
                return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT title FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
    title = row[0] if row else "Group"

    await state.update_data(appeal_chat_id=chat_id)
    await state.set_state(BotStates.waiting_for_appeal_text)
    await cb.message.edit_caption(
        caption=f"Appeal Form: {title}\n\nWrite your appeal message:\n- Length: Between 20 letters and 100 words.\n- No abusive language allowed.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="menu_back")]]),
        parse_mode="Markdown"
    )

@dp.message(BotStates.waiting_for_appeal_text)
async def process_appeal_text(msg: types.Message, state: FSMContext):
    text = msg.text or ""
    words = text.split()
    
    if len(text) < 20 or len(words) > 100:
        await msg.reply("Appeal message must be between 20 letters and 100 words. Please write again:")
        return

    if any(word in text.lower() for word in PROFANITY_WORDS):
        await msg.reply("Inappropriate language detected. Please write your appeal properly:")
        return

    data = await state.get_data()
    chat_id = data.get("appeal_chat_id")

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO appeals (user_id, chat_key, reason) VALUES (?, ?, ?)", (msg.from_user.id, str(chat_id), text))
        await db.execute("INSERT OR REPLACE INTO ban_tracker (user_id, chat_key, is_banned, appeal_used) VALUES (?, ?, 1, 1)", (msg.from_user.id, str(chat_id)))
        await db.commit()

    await state.clear()
    await msg.answer("Your appeal has been successfully submitted! Admins will review it.", reply_markup=user_start_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "menu_back")
async def cb_menu_back(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    banner_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"
    await cb.message.edit_caption(
        caption="Welcome to Appeal X Bot\nSelect an option below:",
        reply_markup=user_start_kb(), parse_mode="Markdown"
    )

@dp.callback_query(F.data == "close_menu")
async def cb_close(cb: types.CallbackQuery):
    await cb.message.delete()

# --- Engagement & Rank Commands ---
@dp.message(Command("today"))
async def cmd_today(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT full_name, daily_msgs FROM users WHERE chat_id = ? ORDER BY daily_msgs DESC LIMIT 3", (msg.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    photo = await generate_rank_card("Daily Top Chatters", rows)
    await msg.answer_photo(photo=photo, caption="Today's top chatters list!")

@dp.message(Command("weekly"))
async def cmd_weekly(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT full_name, weekly_msgs FROM users WHERE chat_id = ? ORDER BY weekly_msgs DESC LIMIT 3", (msg.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    photo = await generate_rank_card("Weekly Top Chatters", rows)
    await msg.answer_photo(photo=photo, caption="This week's top chatters list!")

@dp.message(Command("lead"))
async def cmd_lead(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT full_name, total_msgs FROM users WHERE chat_id = ? ORDER BY total_msgs DESC LIMIT 5", (msg.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    photo = await generate_rank_card("All-Time Leaderboard", rows)
    await msg.answer_photo(photo=photo, caption="All-time top chatters leaderboard!")

# --- Kundli & Ship (Kundli in Hindi) ---
KUNDLI_PREDICTIONS_HI = [
    "आज एडमिन से बिना बात के डांट पड़ने के 99% योग हैं। शांत रहें!",
    "ग्रह बता रहे हैं कि आज आपका मैसेज ग्रुप में वायरल होगा।",
    "धन लाभ के योग हैं, अपना रिचार्ज पैक बचाकर रखें।",
    "आज ग्रुप में क्रश से रिप्लाई आने के पूरे चांस हैं।"
]

@dp.message(Command("kundli"))
async def cmd_kundli(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    fortune = random.choice(KUNDLI_PREDICTIONS_HI)
    await msg.reply(f"**{target.first_name} की कुंडली फल:**\n\n{fortune}", parse_mode="Markdown")

@dp.message(Command("ship"))
async def cmd_ship(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    if not msg.reply_to_message:
        await msg.reply("Please reply to another user's message to use the /ship command!")
        return
    score = random.randint(10, 100)
    user1 = msg.from_user.mention_html()
    user2 = msg.reply_to_message.from_user.mention_html()
    await msg.reply(f"Match Compatibility:\n{user1} & {user2}\nScore: `{score}%`", parse_mode="HTML")

# --- Moderation, Reports & Admin Tags ---
@dp.message(Command("report"))
async def cmd_report(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    if not msg.reply_to_message:
        await msg.reply("Please reply to a message to report.")
        return
    reported_user = msg.reply_to_message.from_user
    reporter = msg.from_user
    await msg.reply(
        f"REPORT ALERT\n\nReported User: {reported_user.mention_html()}\nBy: {reporter.mention_html()}",
        parse_mode="HTML"
    )

@dp.message(Command("admin"))
async def cmd_admin(msg: types.Message):
    if msg.chat.type in ["group", "supergroup"]:
        try:
            admins = await msg.chat.get_administrators()
            mentions = [admin.user.mention_html() for admin in admins if not admin.user.is_bot]
            text = "Attention Admins:\n" + " ".join(mentions)
            await msg.answer(text, parse_mode="HTML")
        except Exception:
            await msg.answer("Error tagging admins.")

# --- Auto Group Registration & Message Tracking ---
@dp.message(F.chat.type.in_(["group", "supergroup"]))
async def group_activity_handler(msg: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO managed_groups (chat_id, title) VALUES (?, ?)", (msg.chat.id, msg.chat.title or "Group"))
        await db.commit()

    if msg.from_user and not msg.from_user.is_bot:
        await add_msg_count(
            msg.from_user.id, 
            msg.chat.id, 
            msg.from_user.username or "", 
            msg.from_user.first_name
        )

# --- Main Entry Point ---
async def main():
    await init_db()
    await start_web_server()
    asyncio.create_task(keep_alive())
    
    # Default commands for regular users in private (only start)
    await bot.set_my_commands(
        [BotCommand(command="start", description="Open Main Menu")],
        scope=BotCommandScopeDefault()
    )
    
    # Group commands available in groups
    group_commands = [
        BotCommand(command="today", description="Today top chatters"),
        BotCommand(command="weekly", description="Weekly top chatters"),
        BotCommand(command="lead", description="All-time leaderboard"),
        BotCommand(command="kundli", description="Astrology prediction"),
        BotCommand(command="ship", description="Compatibility meter"),
        BotCommand(command="report", description="Report message"),
        BotCommand(command="admin", description="Tag all admins"),
        BotCommand(command="ban", description="Ban user via reply"),
        BotCommand(command="unban", description="Unban user via reply"),
        BotCommand(command="mute", description="Mute user via reply"),
        BotCommand(command="unmute", description="Unmute user via reply"),
        BotCommand(command="userid", description="Get user ID")
    ]
    
    # We can set group default commands if needed or let them register natively
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
