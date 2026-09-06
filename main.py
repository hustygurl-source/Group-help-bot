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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BufferedInputFile, BotCommandScopeDefault

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
            flood_limit INTEGER DEFAULT 3,
            flood_time INTEGER DEFAULT 2,
            flood_action TEXT DEFAULT 'mute',
            flood_del INTEGER DEFAULT 1,
            mute_duration INTEGER DEFAULT 10,
            link_protection INTEGER DEFAULT 0,
            masked_users INTEGER DEFAULT 1,
            masked_del INTEGER DEFAULT 1,
            welcome_status INTEGER DEFAULT 0
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS group_warnings (
            chat_id INTEGER,
            action TEXT DEFAULT 'mute',
            max_warns INTEGER DEFAULT 3,
            mute_duration INTEGER DEFAULT 60,
            PRIMARY KEY (chat_id)
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
        CREATE TABLE IF NOT EXISTS recurring_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_text TEXT,
            interval_seconds INTEGER DEFAULT 3600,
            is_active INTEGER DEFAULT 1
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
        CREATE TABLE IF NOT EXISTS user_incline_buttons (
            chat_id INTEGER,
            trigger_word TEXT,
            reply_text TEXT,
            button_name TEXT,
            button_url TEXT,
            PRIMARY KEY (chat_id, trigger_word, button_name)
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

# --- Custom Leaderboard Image Generation ---
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
    adding_recurring_msg = State()
    setting_custom_cmd = State()
    setting_user_cmd = State()
    setting_incline_btn = State()

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

def anti_flood_menu_kb(chat_id: int, limit=3, time_sec=2, action="mute", del_msg=1):
    action_labels = {"off": "Off", "warn": "Warn", "kick": "Kick", "mute": "Mute", "ban": "Ban"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Messages: {limit}", callback_data=f"af_msgs_{chat_id}"), InlineKeyboardButton(text=f"Time: {time_sec}s", callback_data=f"af_time_{chat_id}")],
        [InlineKeyboardButton(text=f"{'✅ ' if action=='off':_}Off", callback_data=f"af_setact_off_{chat_id}"), InlineKeyboardButton(text=f"{'✅ ' if action=='warn':_}Warn", callback_data=f"af_setact_warn_{chat_id}")],
        [InlineKeyboardButton(text=f"{'✅ ' if action=='kick':_}Kick", callback_data=f"af_setact_kick_{chat_id}"), InlineKeyboardButton(text=f"{'✅ ' if action=='mute':_}Mute", callback_data=f"af_setact_mute_{chat_id}"), InlineKeyboardButton(text=f"{'✅ ' if action=='ban':_}Ban", callback_data=f"af_setact_ban_{chat_id}")],
        [InlineKeyboardButton(text=f"Delete Messages {'✅' if del_msg else '❌'}", callback_data=f"af_del_{chat_id}")],
        [InlineKeyboardButton(text="Set mute duration", callback_data=f"af_mdur_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def warns_menu_kb(chat_id: int, action="mute", max_warns=3):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Warned List", callback_data=f"w_list_{chat_id}")],
        [InlineKeyboardButton(text=f"{'✅ ' if action=='off':_}Off", callback_data=f"w_act_off_{chat_id}"), InlineKeyboardButton(text=f"{'✅ ' if action=='kick':_}Kick", callback_data=f"w_act_kick_{chat_id}")],
        [InlineKeyboardButton(text=f"{'✅ ' if action=='mute':_}Mute", callback_data=f"w_act_mute_{chat_id}"), InlineKeyboardButton(text=f"{'✅ ' if action=='ban':_}Ban", callback_data=f"w_act_ban_{chat_id}")],
        [InlineKeyboardButton(text="Set mute duration", callback_data=f"w_mdur_{chat_id}")],
        [
            InlineKeyboardButton(text=f"{'✅' if max_warns==2 else ''} 2", callback_data=f"w_cnt_2_{chat_id}"),
            InlineKeyboardButton(text=f"{'✅' if max_warns==3 else ''} 3", callback_data=f"w_cnt_3_{chat_id}"),
            InlineKeyboardButton(text=f"{'✅' if max_warns==4 else ''} 4", callback_data=f"w_cnt_4_{chat_id}"),
            InlineKeyboardButton(text=f"{'✅' if max_warns==5 else ''} 5", callback_data=f"w_cnt_5_{chat_id}"),
            InlineKeyboardButton(text=f"{'✅' if max_warns==6 else ''} 6", callback_data=f"w_cnt_6_{chat_id}")
        ],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def recurring_menu_kb(chat_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Add message", callback_data=f"rc_add_{chat_id}")],
        [InlineKeyboardButton(text="Active", callback_data=f"rc_toggle_{chat_id}"), InlineKeyboardButton(text="Delete", callback_data=f"rc_del_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def link_protection_menu_kb(chat_id: int, status: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Status: {'Turn On ✅' if status else 'Turn Off ❌'}", callback_data=f"lnk_toggle_{chat_id}")],
        [InlineKeyboardButton(text="Back", callback_data=f"select_group_{chat_id}")]
    ])

def masked_users_menu_kb(chat_id: int, status: int, del_msg: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Turn off {'✅' if not status else ''}", callback_data=f"mu_off_{chat_id}"), InlineKeyboardButton(text=f"Turn on {'✅' if status else ''}", callback_data=f"mu_on_{chat_id}")],
        [InlineKeyboardButton(text=f"Delete Messages {'✅' if del_msg else '❌'}", callback_data=f"mu_del_{chat_id}")],
        [InlineKeyboardButton(text="Exceptions", callback_data=f"mu_exc_{chat_id}")],
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
        
        banner_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600"
        await msg.answer_photo(
            photo=banner_url,
            caption="Manage Group Settings\nSelect an option below:",
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
            caption="Manage Group Settings\nSelect an option below:",
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
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT flood_limit, flood_time, flood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        limit, time_sec, act, del_m = res if res else (3, 2, "mute", 1)
        await cb.message.edit_caption(
            caption=f"Antiflood\nFrom this menu you can set a punishment for those who send many messages in a short time.\n\nCurrently, the antiflood triggers when {limit} messages are sent within {time_sec} seconds.\nPunishment: {act.upper()} + Deletion: {'Yes' if del_m else 'No'}",
            reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, act, del_m), parse_mode="Markdown"
        )
    elif action == "warns":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT action, max_warns FROM group_warnings WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        act, max_w = res if res else ("mute", 3)
        await cb.message.edit_caption(
            caption=f"User warnings\nMax warns allowed: {max_w}\nPunishment: {act.upper()}",
            reply_markup=warns_menu_kb(chat_id, act, max_w), parse_mode="Markdown"
        )
    elif action == "link":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT link_protection FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        status = res[0] if res else 0
        await cb.message.edit_caption(
            caption=f"Link Protection\nAuto-delete all links sent by non-admin users.\nStatus: {'Turned On' if status else 'Turned Off'}",
            reply_markup=link_protection_menu_kb(chat_id, status), parse_mode="Markdown"
        )
    elif action == "recurring":
        await cb.message.edit_caption(
            caption="Recurring messages\nFrom this menu you can set messages that will be sent repeatedly to the group.",
            reply_markup=recurring_menu_kb(chat_id), parse_mode="Markdown"
        )
    elif action == "masked":
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT masked_users, masked_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        status, del_m = res if res else (1, 1)
        await cb.message.edit_caption(
            caption=f"Masked users\nBlock users writing disguised as a channel.\nStatus: {'Active' if status else 'Inactive'}",
            reply_markup=masked_users_menu_kb(chat_id, status, del_m), parse_mode="Markdown"
        )
    elif action == "pcommands":
        await cb.message.edit_caption(
            caption="Personal Commands, User Command, User Incline Button",
            reply_markup=personal_commands_menu_kb(chat_id), parse_mode="Markdown"
        )
    else:
        await cb.answer(f"Opening {action.upper()} settings...", show_alert=False)

# Antiflood sub-handlers
@dp.callback_query(F.data.startswith("af_setact_"))
async def cb_af_setact(cb: types.CallbackQuery):
    _, _, act, chat_id_str = cb.data.split("_")
    chat_id = int(chat_id_str)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE managed_groups SET flood_action = ? WHERE chat_id = ?", (act, chat_id))
        await db.commit()
        async with db.execute("SELECT flood_limit, flood_time, flood_action, flood_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
    limit, time_sec, action, del_m = res
    await cb.message.edit_reply_markup(reply_markup=anti_flood_menu_kb(chat_id, limit, time_sec, action, del_m))
    await cb.answer("Punishment updated!")

@dp.callback_query(F.data.startswith("af_del_"))
async def cb_af_del(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[2])
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT flood_del, flood_limit, flood_time, flood_action FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
            res = await cursor.fetchone()
        new_del = 0 if res[0] else 1
        await db.execute("UPDATE managed_groups SET flood_del = ? WHERE chat_id = ?", (new_del, chat_id))
        await db.commit()
    await cb.message.edit_reply_markup(reply_markup=anti_flood_menu_kb(chat_id, res[1], res[2], res[3], new_del))
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

@dp.callback_query(F.data.startswith(("w_", "rc_", "mu_", "pc_")))
async def cb_other_submenus(cb: types.CallbackQuery):
    await cb.answer("Setting updated successfully!", show_alert=False)

# --- Direct Group Moderation Commands & Protection Logic ---
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

@dp.callback_query(F.data.startswith("select_group_") & ~F.data.contains("gs_"))
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

# --- Custom Leaderboard Commands ---
@dp.message(Command("today"))
async def cmd_today(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT full_name, daily_msgs FROM users WHERE chat_id = ? ORDER BY daily_msgs DESC LIMIT 3", (msg.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    photo = await generate_top3_card("Top 3 Chatters (Today)", rows)
    lb_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Leaderboard", callback_data=f"show_lb_{msg.chat.id}")]])
    await msg.answer_photo(photo=photo, caption="Today's top chatters list!", reply_markup=lb_kb)

@dp.message(Command("weekly"))
async def cmd_weekly(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT full_name, weekly_msgs FROM users WHERE chat_id = ? ORDER BY weekly_msgs DESC LIMIT 3", (msg.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    photo = await generate_top3_card("Top 3 Chatters (Weekly)", rows)
    lb_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Leaderboard", callback_data=f"show_lb_{msg.chat.id}")]])
    await msg.answer_photo(photo=photo, caption="Weekly top chatters list!", reply_markup=lb_kb)

@dp.message(Command("lead"))
async def cmd_lead(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT full_name, total_msgs FROM users WHERE chat_id = ? ORDER BY total_msgs DESC LIMIT 10", (msg.chat.id,)) as cursor:
            rows = await cursor.fetchall()
    photo = await generate_full_leaderboard_card("Group Leaderboard", rows)
    full_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Full Leaderboard", callback_data=f"show_lb_{msg.chat.id}")]])
    await msg.answer_photo(photo=photo, caption="All-time group leaderboard!", reply_markup=full_kb)

# --- Kundli in Hinglish ---
KUNDLI_PREDICTIONS_HINGLISH = [
    "Aaj admin se bina baat ke daant padne ke 99% yog hain. Shant rahein!",
    "Grahe bata rahe hain ki aaj aapka message group mein viral hoga.",
    "Dhan labh ke yog hain, apna recharge pack bacha kar rakhein.",
    "Aaj group mein crush se reply aane ke poore chance hain."
]

@dp.message(Command("kundli"))
async def cmd_kundli(msg: types.Message):
    if msg.chat.type not in ["group", "supergroup"]:
        return
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    fortune = random.choice(KUNDLI_PREDICTIONS_HINGLISH)
    await msg.reply(f"**{target.first_name} ki Kundli Fal:**\n\n{fortune}", parse_mode="Markdown")

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

# --- Protection & Group Activity Processor ---
@dp.message(F.chat.type.in_["group", "supergroup"])
async def group_message_processor(msg: types.Message):
    chat_id = msg.chat.id
    user = msg.from_user
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO managed_groups (chat_id, title) VALUES (?, ?)", (chat_id, msg.chat.title or "Group"))
        await db.commit()

    if not user or user.is_bot:
        return

    is_admin = await is_user_admin(msg)

    # 1. Masked User Protection Check
    if not is_admin and msg.sender_chat and msg.sender_chat.id != chat_id:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT masked_users, masked_del FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        if res and res[0] == 1:
            try:
                if res[1] == 1:
                    await msg.delete()
                else:
                    await bot.ban_chat_member(chat_id=chat_id, user_id=user.id)
            except Exception:
                pass
            return

    # 2. Link Protection Check
    if not is_admin and msg.text:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT link_protection FROM managed_groups WHERE chat_id = ?", (chat_id,)) as cursor:
                res = await cursor.fetchone()
        if res and res[0] == 1:
            if "http://" in msg.text or "https://" in msg.text or "t.me/" in msg.text or "www." in msg.text:
                try:
                    await msg.delete()
                except Exception:
                    pass
                return

    # Message Counter Update
    await add_msg_count(user.id, chat_id, user.username or "", user.first_name)

# --- Main Entry Point ---
async def main():
    await init_db()
    await start_web_server()
    asyncio.create_task(keep_alive())
    
    await bot.set_my_commands(
        [BotCommand(command="start", description="Open Main Menu")],
        scope=BotCommandScopeDefault()
    )
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
