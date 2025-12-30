import os
import sqlite3
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# ---------- Flask dummy server ----------
app_web = Flask(__name__)

@app_web.route("/")
def index():
    return "Viral Music Bot is running! 🚀"

def run_flask():
    app_web.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# ---------- Telegram Bot Code ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SONG_LINK = "https://mdundo.com/song/5321016"
REWARD_TOP = 3

conn = sqlite3.connect("referrals.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    referrer INTEGER,
    referrals INTEGER DEFAULT 0
)
""")
conn.commit()

def add_user(user_id, username, referrer=None):
    cursor.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?, ?)", (user_id, username))
    conn.commit()
    if referrer:
        cursor.execute("SELECT referrer FROM users WHERE user_id=?", (user_id,))
        if cursor.fetchone()[0] is None and referrer != user_id:
            cursor.execute("UPDATE users SET referrer=? WHERE user_id=?", (referrer, user_id))
            cursor.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id=?", (referrer,))
            conn.commit()
            return referrer
    return None

def get_leaderboard(top=10):
    cursor.execute("SELECT username, referrals FROM users ORDER BY referrals DESC LIMIT ?", (top,))
    return cursor.fetchall()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    username = update.message.from_user.username or str(user_id)
    args = context.args
    referrer_id = int(args[0]) if args else None
    add_user(user_id, username, referrer_id)
    referral_link = f"https://t.me/{context.bot.username}?start={user_id}"
    keyboard = [
        [InlineKeyboardButton("▶️ Listen / Download", url=SONG_LINK)],
        [InlineKeyboardButton("📤 Share Song", switch_inline_query=SONG_LINK)],
        [InlineKeyboardButton("🏆 My Referrals", callback_data="stats")],
        [InlineKeyboardButton("🌟 Leaderboard", callback_data="leaderboard")]
    ]
    await update.message.reply_text(
        "🔥 *NEW VIRAL HIT SONG!* 🔥\\n🎧 Listen & download below\\n📢 Share with friends & groups\\n🏆 Top promoters get rewards!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text(f"🔗 *Your referral link:*\\n{referral_link}\\nShare this link everywhere!", parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    cursor.execute("SELECT referrals FROM users WHERE user_id=?", (user_id,))
    count = cursor.fetchone()[0]
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(f"🏆 *Your Total Referrals:* {count}\\nKeep sharing!", parse_mode="Markdown")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = get_leaderboard(10)
    text = "🌟 *Top 10 Promoters* 🌟\\n"
    for idx, (username, referrals) in enumerate(top_users, start=1):
        text += f"{idx}. @{username} - {referrals} referrals\\n"
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(text, parse_mode="Markdown")

async def reward_job(context: ContextTypes.DEFAULT_TYPE):
    top_users = get_leaderboard(REWARD_TOP)
    for idx, (username, referrals) in enumerate(top_users, start=1):
        try:
            user_id = cursor.execute("SELECT user_id FROM users WHERE username=?", (username,)).fetchone()[0]
            await context.bot.send_message(chat_id=user_id, text=f"🎉 Congrats @{username}! You are currently #{idx} on the leaderboard with {referrals} referrals! Keep sharing to win rewards! 🏆")
        except:
            continue

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not set!")
        return

    # Start Flask server in a thread
    threading.Thread(target=run_flask).start()

    # Start Telegram Bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(stats, pattern="stats"))
    app.add_handler(CallbackQueryHandler(leaderboard, pattern="leaderboard"))
    job_queue = app.job_queue
    job_queue.run_repeating(reward_job, interval=21600, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()
