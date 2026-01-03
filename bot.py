import os
import sqlite3
import threading
import time
import requests
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError

# ---------------- CONFIG ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required.")

# Replace with your actual Telegram user ID(s)
ADMIN_IDS = {123456789}  # ←←← CHANGE THIS TO YOUR REAL USER ID

DB_FILE = "bot.db"
COOLDOWN = 10  # seconds for anti-spam
LAST_ACTION = {}
LAST_ACTION_LOCK = threading.Lock()

# Get the Render app URL for self-pinging
RENDER_APP_URL = os.environ.get("RENDER_APP_URL", "https://your-app-name.onrender.com")

SONGS = {
    "song1": {
        "title": "Tribute to Dear Mama",
        "url": "https://youtu.be/gbprHnumaBM?si=R5ocaU_avNf7J4n2",
        "answer": "mama"
    },
    "song2": {
        "title": "Tribute to Nannies & Teachers",
        "url": "https://youtu.be/L8hiNjTcvDY?si=8uOj46Cohj2bylzk",
        "answer": "teachers"
    }
}

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            reward_unlocked INTEGER DEFAULT 0,
            shares_left INTEGER DEFAULT 0,
            quizzes_passed INTEGER DEFAULT 0,
            promotions_used INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS approved_groups (
            chat_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            title TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            link TEXT,
            promoted_by INTEGER,
            broadcast_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES approved_groups(chat_id)
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        row = (user_id, 0, 0, 0, 0)
    conn.close()
    return row

def unlock_reward(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET reward_unlocked=1, shares_left=20, quizzes_passed=1 WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()

def reduce_share(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET shares_left = shares_left - 1, promotions_used = promotions_used + 1 WHERE user_id=? AND shares_left > 0",
        (user_id,)
    )
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def register_group(chat_id, added_by, title, username=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO approved_groups (chat_id, added_by, title, username) 
        VALUES (?, ?, ?, ?)
    """, (chat_id, added_by, title, username))
    conn.commit()
    conn.close()

def get_approved_groups():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT chat_id, title, username FROM approved_groups")
    groups = c.fetchall()
    conn.close()
    return groups

def log_broadcast(chat_id, link, promoted_by):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO group_broadcasts (chat_id, link, promoted_by) 
        VALUES (?, ?, ?)
    """, (chat_id, link, promoted_by))
    conn.commit()
    conn.close()

def get_group_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT 
            g.title,
            COUNT(b.id) as broadcast_count,
            SUM(CASE WHEN b.broadcast_at > datetime('now', '-7 days') THEN 1 ELSE 0 END) as weekly_count
        FROM approved_groups g
        LEFT JOIN group_broadcasts b ON g.chat_id = b.chat_id
        GROUP BY g.chat_id
        ORDER BY weekly_count DESC
    """)
    stats = c.fetchall()
    conn.close()
    return stats

# ---------------- ANTI-SPAM ----------------
def is_spamming(user_id):
    now = time.time()
    with LAST_ACTION_LOCK:
        last = LAST_ACTION.get(user_id, 0)
        if now - last < COOLDOWN:
            return True
        LAST_ACTION[user_id] = now
    return False

# ---------------- ADMIN CHECK ----------------
def is_admin(user_id):
    return user_id in ADMIN_IDS

# ---------------- ENHANCED FLASK KEEP-ALIVE ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Viral Music Bot is running! 🎵"

@app.route("/health")
def health_check():
    """Enhanced health check endpoint for monitoring"""
    try:
        # Check database connection
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        conn.close()
        
        # Check bot token availability
        token_status = "✅ Available" if BOT_TOKEN else "❌ Missing"
        
        return {
            "status": "healthy",
            "timestamp": time.time(),
            "database_status": "✅ Connected",
            "user_count": user_count,
            "bot_token": token_status,
            "version": "1.2"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }, 500

@app.route("/keepalive")
def keepalive():
    """Endpoint specifically for uptime monitoring services"""
    return {
        "message": "Bot is active and healthy",
        "uptime_seconds": time.time() - START_TIME,
        "registered_groups": len(get_approved_groups())
    }

# Global start time for uptime tracking
START_TIME = time.time()

def run_flask():
    """Run Flask server with production settings"""
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)

# ---------------- AUTO-PING SYSTEM ----------------
def auto_ping_system():
    """Periodically ping the bot's own endpoints to stay active"""
    print("🔄 Auto-ping system started - keeping bot alive every 10 minutes")
    
    while True:
        try:
            # Ping the main endpoint
            main_response = requests.get(f"{RENDER_APP_URL}/", timeout=10)
            print(f"🏓 Main endpoint ping: {main_response.status_code}")
            
            # Ping the health endpoint
            health_response = requests.get(f"{RENDER_APP_URL}/health", timeout=10)
            print(f"🏥 Health check ping: {health_response.status_code}")
            
            # Ping the keepalive endpoint
            keepalive_response = requests.get(f"{RENDER_APP_URL}/keepalive", timeout=10)
            print(f"⚡ Keepalive ping: {keepalive_response.status_code}")
            
            print(f"✅ All endpoints pinged successfully at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
        except Exception as e:
            print(f"❌ Ping failed: {e}")
            print(f"⚠️  Trying backup ping method...")
            
            # Backup ping method
            try:
                backup_response = requests.get(f"{RENDER_APP_URL}/", timeout=15)
                print(f"🔄 Backup ping successful: {backup_response.status_code}")
            except Exception as backup_e:
                print(f"❌ Backup ping also failed: {backup_e}")
        
        # Wait 10 minutes (600 seconds) before next ping
        # This is more frequent than the 15-minute requirement to be safe
        time.sleep(600)

# ---------------- GROUP MANAGEMENT ----------------
async def register_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register a group for auto-broadcast - only works in groups"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            "🚫 This command only works in groups!\n\n"
            "Please add me to your group first, then use /register_group there."
        )
        return
    
    # Check if user is admin in this group or global admin
    is_global_admin = is_admin(user.id)
    
    if not is_global_admin:
        # Check if user is admin in this group
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    "🔐 Only group admins can register this group for broadcasting."
                )
                return
        except TelegramError as e:
            await update.message.reply_text(f"❌ Error checking admin status: {e}")
            return
    
    # Check if bot has posting permissions
    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if not bot_member.can_post_messages:
            await update.message.reply_text(
                "❌ I need 'Post Messages' permission to broadcast promotions in this group.\n\n"
                "Please make me an admin with posting permissions first."
            )
            return
    except TelegramError as e:
        await update.message.reply_text(f"❌ Error checking bot permissions: {e}")
        return
    
    # Register the group
    username = chat.username if hasattr(chat, 'username') and chat.username else None
    register_group(chat.id, user.id, chat.title or f"Group {chat.id}", username)
    
    # Create success message with group info
    group_info = f"✅ Group '{chat.title}' registered successfully!\n\n"
    group_info += "🔗 I'll now automatically broadcast promotions here when users share links.\n\n"
    
    if username:
        group_info += f"🌐 Public Group: @{username}\n"
    else:
        group_info += "🔒 Private Group\n"
    
    group_info += f"👑 Added by: {user.full_name} ({user.id})\n"
    group_info += "\n📊 Use /groupstats to see broadcast statistics for all registered groups."
    
    await update.message.reply_text(group_info)

async def unregister_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unregister a group from auto-broadcast"""
    user = update.effective_user
    chat = update.effective_chat
    
    if chat.type == ChatType.PRIVATE:
        await update.message.reply_text("🚫 This command only works in groups!")
        return
    
    # Only allow global admins or the person who registered the group
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT added_by FROM approved_groups WHERE chat_id=?", (chat.id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("⚠️ This group is not registered for broadcasting.")
        return
    
    added_by = result[0]
    if not (is_admin(user.id) or user.id == added_by):
        await update.message.reply_text(
            "🔐 Only the admin who registered this group or global admins can unregister it."
        )
        return
    
    # Remove from database
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM approved_groups WHERE chat_id=?", (chat.id,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ Group '{chat.title}' has been unregistered from auto-broadcasts.\n\n"
        "I will no longer broadcast promotions to this group."
    )

async def groupstats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics for registered groups"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    stats = get_group_stats()
    
    if not stats:
        await update.message.reply_text("📊 No groups registered for broadcasting yet.")
        return
    
    text = "📈 <b>Group Broadcast Statistics</b>\n\n"
    for i, (title, total_count, weekly_count) in enumerate(stats, 1):
        text += f"{i}. <b>{title}</b>\n"
        text += f"   📊 Total Broadcasts: {total_count}\n"
        text += f"   📈 This Week: {weekly_count}\n\n"
    
    text += f"\n🎯 <b>Total Registered Groups:</b> {len(stats)}"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def listgroups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all registered groups"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    groups = get_approved_groups()
    
    if not groups:
        await update.message.reply_text("📋 No groups registered for broadcasting yet.")
        return
    
    text = "📋 <b>Registered Groups for Broadcasting</b>\n\n"
    for i, (chat_id, title, username) in enumerate(groups, 1):
        group_type = "🌐 Public" if username else "🔒 Private"
        username_text = f"@{username}" if username else "N/A"
        
        text += f"{i}. <b>{title}</b>\n"
        text += f"   🆔 Chat ID: {chat_id}\n"
        text += f"   {group_type} | Username: {username_text}\n\n"
    
    text += f"\n🎯 <b>Total Groups:</b> {len(groups)}"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ---------------- BROADCAST TO GROUPS ----------------
async def broadcast_to_groups(context: ContextTypes.DEFAULT_TYPE, link: str, promoted_by: int, original_chat_id: int):
    """Broadcast a promotion link to all registered groups"""
    groups = get_approved_groups()
    
    if not groups:
        return 0  # No groups to broadcast to
    
    successful = 0
    failed = 0
    
    for chat_id, title, username in groups:
        # Skip the original chat if it's a group to avoid duplicate messages
        if chat_id == original_chat_id:
            continue
        
        try:
            # Format the broadcast message
            message = (
                "📣 <b>New Promotion Shared!</b>\n\n"
                f"🔗 <b>Link:</b> {link}\n\n"
                f"👤 <b>Shared by:</b> User {promoted_by}\n"
                f"🏠 <b>Group:</b> {title}"
            )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
            
            # Log the successful broadcast
            log_broadcast(chat_id, link, promoted_by)
            successful += 1
            
        except TelegramError as e:
            print(f"❌ Failed to broadcast to group {chat_id} ({title}): {e}")
            failed += 1
    
    return successful

# ---------------- BOT HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_spamming(user_id):
        await update.message.reply_text("⏳ Slow down. Try again in a few seconds.")
        return

    get_user(user_id)
    keyboard = [
        [InlineKeyboardButton("🎧 Listen to Song 1", url=SONGS["song1"]["url"])],
        [InlineKeyboardButton("🎧 Listen to Song 2", url=SONGS["song2"]["url"])],
        [InlineKeyboardButton("✅ I listened – Take Quiz", callback_data="quiz")]
    ]
    message = (
        "🎶 <b>Welcome to Viral Music Bot!</b>\n\n"
        "🎵 Listen to inspiring songs about mothers and teachers\n"
        "🧠 Take quizzes to unlock rewards\n"
        "📣 Share your links and get them promoted across multiple groups\n\n"
        "<b>How to get started:</b>\n"
        "1️⃣ Click a song link above\n"
        "2️⃣ Listen to the song\n"
        "3️⃣ Click 'I listened – Take Quiz'\n"
        "4️⃣ Pass the quiz to unlock 20 promotions\n"
        "5️⃣ Use /promote <your_link> to share\n\n"
        "<i>💡 Pro tip: Group admins can register their groups using /register_group to receive automatic broadcasts!</i>"
    )
    
    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    user = get_user(user_id)
    if user[1] == 1:
        await query.message.reply_text("⚠️ Quiz already passed. You have rewards unlocked.")
        return

    keyboard = [
        [InlineKeyboardButton("Tribute to my Dear Mama ❤️", callback_data="q1_mama")],
        [InlineKeyboardButton("Tribute to Nannies & Teachers 👩‍🏫", callback_data="q1_teachers")],
        [InlineKeyboardButton("Just a Party Song 🎉", callback_data="wrong")]
    ]
    await query.message.reply_text(
        "🧠 <b>Quiz: What are the songs mainly about?</b>\n\n"
        "<i>Listen carefully to the lyrics before answering!</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data in ["q1_mama", "q1_teachers"]:
        unlock_reward(user_id)
        await query.message.reply_text(
            "✅ <b>Correct!</b> Reward unlocked.\n\n"
            "🎯 You now have <b>20 promotions</b> to use!\n"
            "📣 Use <code>/promote your_link</code> to share your content\n"
            "🔄 Your link will be automatically broadcasted to all registered groups\n\n"
            "<i>💡 Want your group to receive these broadcasts? Ask an admin to use /register_group!</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await query.message.reply_text(
            "❌ <b>Incorrect.</b> Listen again and retry.\n\n"
            "🎧 Click the song links above to listen again.",
            parse_mode=ParseMode.HTML
        )

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    user = get_user(user_id)
    
    if is_spamming(user_id):
        await update.message.reply_text("⏳ Slow down. Try again later.")
        return

    if user[1] == 0:
        await update.message.reply_text("🔒 Pass the quiz first to unlock rewards.")
        return

    current_shares = user[2]
    if current_shares <= 0:
        await update.message.reply_text("🚫 You have used all 20 promotions.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/promote https://your-link.com</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/promote https://youtube.com/myvideo</code>\n"
            "<code>/promote https://t.me/mychannel</code>",
            parse_mode=ParseMode.HTML
        )
        return

    link = context.args[0]
    
    # Basic URL validation
    if not (link.startswith('http://') or link.startswith('https://')):
        await update.message.reply_text(
            "❌ Invalid link format. Please provide a valid URL starting with http:// or https://"
        )
        return
    
    # Reduce the share count
    if not reduce_share(user_id):
        await update.message.reply_text("🚫 Failed to reduce shares. Please try again.")
        return
    
    new_shares = current_shares - 1
    
    # Send confirmation to user
    confirmation_msg = (
        f"✅ <b>Promotion sent successfully!</b>\n\n"
        f"🔗 <b>Link:</b> {link}\n"
        f"🎯 <b>Remaining shares:</b> {new_shares}/20\n\n"
    )
    
    # Broadcast to groups if any are registered
    groups = get_approved_groups()
    if groups:
        successful_broadcasts = await broadcast_to_groups(context, link, user_id, chat.id)
        confirmation_msg += f"📢 <b>Broadcasted to {successful_broadcasts} groups!</b>"
    else:
        confirmation_msg += "⚠️ <b>No groups registered yet.</b> Ask admins to use /register_group to receive broadcasts."
    
    await update.message.reply_text(confirmation_msg, parse_mode=ParseMode.HTML)

async def myreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user[1] == 0:
        await update.message.reply_text("⚠️ Pass the quiz first to unlock rewards.")
        return
    
    status_msg = (
        f"🎯 <b>Reward Status</b>\n\n"
        f"✅ <b>Quiz Passed:</b> Yes\n"
        f"🔄 <b>Shares Left:</b> {user[2]}/20\n"
        f"📊 <b>Promotions Used:</b> {user[4]}\n\n"
    )
    
    # Add group broadcast info
    groups = get_approved_groups()
    if groups:
        status_msg += f"📢 <b>Registered Groups:</b> {len(groups)}\n"
        status_msg += "👥 Your promotions will be broadcasted to all registered groups!"
    else:
        status_msg += "⚠️ <b>No groups registered</b>\n"
        status_msg += "👥 Ask group admins to use /register_group to receive broadcasts!"
    
    await update.message.reply_text(status_msg, parse_mode=ParseMode.HTML)

# ---------------- LEADERBOARD ----------------
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT user_id, quizzes_passed, promotions_used
        FROM users
        ORDER BY quizzes_passed DESC, promotions_used DESC
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("🏆 Leaderboard is empty.")
        return
    text = "🏆 <b>Top Promoters Leaderboard</b>\n\n"
    for i, (uid, q, p) in enumerate(rows, 1):
        text += f"{i}. <b>User {uid}</b>\n"
        text += f"   🎧 Quizzes Passed: {q}\n"
        text += f"   📣 Promotions Used: {p}\n\n"
    text += "\n💪 <i>Keep promoting to climb the leaderboard!</i>"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ---------------- ADMIN COMMANDS ----------------
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Admin only command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    message = " ".join(context.args)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    sent = 0
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, message)
            sent += 1
        except Exception as e:
            print(f"Failed to send to {uid}: {e}")
            pass  # silently skip failed sends
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")

async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addreward <user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Invalid user ID.")
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET shares_left = shares_left + 20 WHERE user_id=?", (uid,))
    updated = c.rowcount
    conn.commit()
    conn.close()
    if updated:
        await update.message.reply_text(f"✅ Added 20 shares to user {uid}")
    else:
        await update.message.reply_text("⚠️ User not found.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT SUM(quizzes_passed) FROM users")
    total_quizzes = c.fetchone()[0] or 0
    c.execute("SELECT SUM(promotions_used) FROM users")
    total_promos = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM approved_groups")
    total_groups = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM group_broadcasts")
    total_broadcasts = c.fetchone()[0] or 0
    conn.close()
    await update.message.reply_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: {total_users}\n"
        f"🎓 Total Quizzes Passed: {total_quizzes}\n"
        f"📣 Total Promotions Used: {total_promos}\n"
        f"🏢 Registered Groups: {total_groups}\n"
        f"📡 Total Group Broadcasts: {total_broadcasts}",
        parse_mode=ParseMode.HTML
    )

# ---------------- MONETIZATION PLACEHOLDERS ----------------
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 <b>Buy Promotion Boost</b>\n\n"
        "🚀 Get more shares and reach more people!\n\n"
        "<b>Pricing:</b>\n"
        "• 20 shares: KES 100\n"
        "• 50 shares: KES 200\n"
        "• 100 shares: KES 350\n\n"
        "<b>How to pay:</b>\n"
        "1. Send MPESA to: <code>07XXXXXXXX</code>\n"
        "2. Include your Telegram ID in the message\n"
        "3. Send screenshot to @admin_username\n\n"
        "<i>💡 After payment confirmation, shares will be added to your account automatically!</i>",
        parse_mode=ParseMode.HTML
    )

# ---------------- HELP COMMAND ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 <b>Help & Commands</b>\n\n"
        "<b>User Commands:</b>\n"
        "/start - Start the bot and get instructions\n"
        "/promote <link> - Share your link (requires unlocked rewards)\n"
        "/myreward - Check your reward status and remaining shares\n"
        "/leaderboard - View top promoters\n"
        "/buy - Purchase additional shares\n"
        "/help - Show this help message\n\n"
        "<b>Group Admin Commands:</b>\n"
        "/register_group - Register your group for auto-broadcasts (in group only)\n"
        "/unregister_group - Remove your group from broadcasts (in group only)\n\n"
        "<b>Global Admin Commands:</b>\n"
        "/broadcast <message> - Send message to all users\n"
        "/addreward <user_id> - Add 20 shares to a user\n"
        "/stats - View bot statistics\n"
        "/listgroups - List all registered groups\n"
        "/groupstats - View group broadcast statistics\n\n"
        "<i>💡 Tip: To unlock promotions, listen to songs and pass the quiz first!</i>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# ---------------- MAIN ----------------
def main():
    init_db()
    
    # Start Flask in background for keep-alive (e.g., on Render/Heroku)
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start auto-ping system in a separate thread
    threading.Thread(target=auto_ping_system, daemon=True).start()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    # User commands
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("promote", promote))
    app_bot.add_handler(CommandHandler("myreward", myreward))
    app_bot.add_handler(CommandHandler("leaderboard", leaderboard))
    app_bot.add_handler(CommandHandler("help", help_cmd))
    app_bot.add_handler(CommandHandler("buy", buy))

    # Group management commands
    app_bot.add_handler(CommandHandler("register_group", register_group_cmd))
    app_bot.add_handler(CommandHandler("unregister_group", unregister_group_cmd))
    app_bot.add_handler(CommandHandler("listgroups", listgroups_cmd))
    app_bot.add_handler(CommandHandler("groupstats", groupstats_cmd))

    # Admin commands
    app_bot.add_handler(CommandHandler("broadcast", broadcast))
    app_bot.add_handler(CommandHandler("addreward", addreward))
    app_bot.add_handler(CommandHandler("stats", stats))

    # Quiz handlers
    app_bot.add_handler(CallbackQueryHandler(quiz, pattern="^quiz$"))
    app_bot.add_handler(CallbackQueryHandler(quiz_answer, pattern="^q1_"))

    print("🚀 Bot is running with group broadcasting feature...")
    print("🔧 Make sure to set BOT_TOKEN environment variable")
    print("👥 Add this bot to groups and use /register_group to enable auto-broadcasts")
    print(f"🌐 Render App URL: {RENDER_APP_URL}")
    print("🔄 Auto-ping system will keep bot alive every 10 minutes")
    
    app_bot.run_polling()

if __name__ == "__main__":
    main()
