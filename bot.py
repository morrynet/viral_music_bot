import os
import sqlite3
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

DB_FILE = "bot.db"

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

# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            reward_unlocked INTEGER DEFAULT 0,
            shares_left INTEGER DEFAULT 0
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
        row = (user_id, 0, 0)
    conn.close()
    return row

def unlock_reward(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET reward_unlocked=1, shares_left=20 WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()

def reduce_share(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET shares_left = shares_left - 1 WHERE user_id=? AND shares_left > 0",
        (user_id,)
    )
    conn.commit()
    conn.close()

# ---------- BOT HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    get_user(user_id)

    keyboard = [
        [InlineKeyboardButton("🎧 Listen to Song 1", url=SONGS["song1"]["url"])],
        [InlineKeyboardButton("🎧 Listen to Song 2", url=SONGS["song2"]["url"])],
        [InlineKeyboardButton("✅ I listened – Take Quiz", callback_data="quiz")]
    ]

    await update.message.reply_text(
        "🎶 Welcome!\n\n"
        "Listen to ANY song below, then pass the quiz to unlock promotion rewards.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("Tribute to my Dear Mama ❤️", callback_data="q1_mama")],
        [InlineKeyboardButton("Tribute to Nannies & Teachers 👩‍🏫", callback_data="q1_teachers")],
        [InlineKeyboardButton("Just a Party Song 🎉", callback_data="wrong")]
    ]

    await query.message.reply_text(
        "🧠 Quiz Question:\n\n"
        "What are the songs mainly about?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data in ["q1_mama", "q1_teachers"]:
        unlock_reward(user_id)
        await query.message.reply_text(
            "✅ Correct!\n\n"
            "🎉 Reward unlocked!\n"
            "You can now promote YOUR link to 20 people.\n\n"
            "Use /promote <your_link>"
        )
    else:
        await query.message.reply_text(
            "❌ Incorrect.\nPlease listen again and retry the quiz."
        )

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user[1] == 0:
        await update.message.reply_text(
            "🔒 Reward not unlocked.\nListen to a song and pass the quiz first."
        )
        return

    if user[2] <= 0:
        await update.message.reply_text("🚫 You have used all 20 promotions.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /promote https://yourlink.com")
        return

    reduce_share(user_id)
    await update.message.reply_text(
        f"📣 Promotion sent!\n\n"
        f"🔗 {context.args[0]}\n"
        f"Remaining shares: {user[2] - 1}"
    )

# ---------- FLASK KEEPALIVE ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Viral Music Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

# ---------- MAIN ----------
def main():
    init_db()
    threading.Thread(target=run_flask).start()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("promote", promote))
    app_bot.add_handler(CallbackQueryHandler(quiz, pattern="quiz"))
    app_bot.add_handler(CallbackQueryHandler(quiz_answer))

    app_bot.run_polling()

if __name__ == "__main__":
    main()
