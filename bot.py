import os
import sqlite3
import threading
import time
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = {123456789}  # replace with your Telegram user ID

DB_FILE = "bot.db"
COOLDOWN = 10  # seconds for anti-spam
LAST_ACTION = {}  # anti-spam tracking

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
    conn.commit()
    conn.close()

# ---------------- ANTI-SPAM ----------------
def is_spamming(user_id):
    now = time.time()
    last = LAST_ACTION.get(user_id, 0)
    if now - last < COOLDOWN:
        return True
    LAST_ACTION[user_id] = now
    return False

# ---------------- ADMIN CHECK ----------------
def is_admin(user_id):
    return user_id in ADMIN_IDS

# ---------------- FLASK KEEP-ALIVE ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Viral Music Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

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
    await update.message.reply_text(
        "🎶 Welcome!\n\nListen to a song then take a quiz to unlock rewards.",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
        "🧠 Quiz: What are the songs mainly about?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data in ["q1_mama", "q1_teachers"]:
        unlock_reward(user_id)
        await query.message.reply_text(
            "✅ Correct! Reward unlocked.\nYou can now promote your link 20 times.\nUse /promote <link>"
        )
    else:
        await query.message.reply_text("❌ Incorrect. Listen again and retry.")

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if is_spamming(user_id):
        await update.message.reply_text("⏳ Slow down. Try again later.")
        return

    if user[1] == 0:
        await update.message.reply_text("🔒 Pass the quiz first to unlock rewards.")
        return
    if user[2] <= 0:
        await update.message.reply_text("🚫 You have used all 20 promotions.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /promote <your_link>")
        return

    reduce_share(user_id)
    await update.message.reply_text(
        f"📣 Promotion sent!\n🔗 {context.args[0]}\nRemaining shares: {user[2]-1}"
    )

async def myreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user[1] == 0:
        await update.message.reply_text("⚠️ Pass the quiz first to unlock rewards.")
        return
    await update.message.reply_text(
        f"🎯 Reward Status:\nShares left: {user[2]}/20"
    )

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
    text = "🏆 Leaderboard\n\n"
    for i, (uid, q, p) in enumerate(rows, 1):
        text += f"{i}. User {uid}\n   🎧 Quizzes: {q} | 📣 Promos: {p}\n"
    await update.message.reply_text(text)

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
    for (uid,) in users:
        try:
            await context.bot.send_message(uid, message)
        except:
            pass
    await update.message.reply_text("✅ Broadcast sent.")

async def addreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addreward <user_id>")
        return
    uid = int(context.args[0])
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET shares_left = shares_left + 20 WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Added 20 shares to user {uid}")

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
    conn.close()
    await update.message.reply_text(
        f"📊 Stats:\nTotal Users: {total_users}\nTotal Quizzes Passed: {total_quizzes}\nTotal Promotions Used: {total_promos}"
    )

# ---------------- MONETIZATION PLACEHOLDERS ----------------
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 Buy Promotion Boost\n\n"
        "Send KES 100 via MPESA to 07XXXXXXXX\n"
        "After payment, send screenshot to admin to get extra shares."
    )

# ---------------- MAIN ----------------
def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return
    init_db()
    threading.Thread(target=run_flask).start()
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    # User commands
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("promote", promote))
    app_bot.add_handler(CommandHandler("myreward", myreward))
    app_bot.add_handler(CommandHandler("leaderboard", leaderboard))
    app_bot.add_handler(CommandHandler("help", start))
    app_bot.add_handler(CommandHandler("buy", buy))

    # Admin commands
    app_bot.add_handler(CommandHandler("broadcast", broadcast))
    app_bot.add_handler(CommandHandler("addreward", addreward))
    app_bot.add_handler(CommandHandler("stats", stats))

    # Quiz
    app_bot.add_handler(CallbackQueryHandler(quiz, pattern="quiz"))
    app_bot.add_handler(CallbackQueryHandler(quiz_answer, pattern="q1_"))

    app_bot.run_polling()

if __name__ == "__main__":
    main()
