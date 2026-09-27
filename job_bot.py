import os
import random
import datetime
import sqlite3
import telebot
from telebot import types

# ================= CONFIGURATION =================
TOKEN = "8850017539:AAHiANMx1D6C684ZVy7t3Rumwlt-Tmv-Gbg"
bot = telebot.TeleBot(TOKEN)

# Session states for users navigating the chat flow
USER_STATES = {}

# State constants
STATE_CHOOSING_CATEGORY = 1
STATE_WAITING_DESCRIPTION = 2
STATE_WAITING_PHOTO = 3

# ================= DATABASE SETUP =================
def init_db():
    conn = sqlite3.connect('job_system.db')
    cursor = conn.cursor()
    
    # Jobs table (Existing)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            reference TEXT PRIMARY KEY,
            user_id INTEGER,
            username TEXT,
            category TEXT,
            description TEXT,
            file_id TEXT,
            status TEXT,
            created_at TEXT
        )
    ''')
    
    # Users & Roles table (Added for Admin Allocation)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT DEFAULT 'Staff'
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize the database when script starts
init_db()

def save_job_to_db(job_record):
    conn = sqlite3.connect('job_system.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        job_record['reference'],
        job_record['user_id'],
        job_record['username'],
        job_record['category'],
        job_record['description'],
        job_record['file_id'],
        job_record['status'],
        job_record['created_at']
    ))
    conn.commit()
    conn.close()

def get_job_from_db(ref_number):
    conn = sqlite3.connect('job_system.db')
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM jobs WHERE reference = ?', (ref_number,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_job_status_in_db(ref_number, status):
    conn = sqlite3.connect('job_system.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE jobs SET status = ? WHERE reference = ?', (status, ref_number))
    conn.commit()
    conn.close()

# ================= ADMIN ALLOCATION & SECURITY HELPERS =================
def set_user_as_admin(telegram_user_id, username):
    """Allocates or promotes a specific user ID as an Admin in the database."""
    conn = sqlite3.connect('job_system.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, role) 
        VALUES (?, ?, 'Admin')
    ''', (telegram_user_id, username))
    conn.commit()
    conn.close()
    print(f"[ADMIN SETUP] User {username} ({telegram_user_id}) is now configured as an ADMIN.")

def is_admin(user_id):
    """Checks if a given Telegram user ID has admin rights."""
    conn = sqlite3.connect('job_system.db')
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 'Admin'

# ================= STAFF WORKFLOW =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    USER_STATES[user_id] = {'state': STATE_CHOOSING_CATEGORY}
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("🛠️ Fault / Maintenance", "🎽 Uniform Request")
    
    bot.reply_to(
        message, 
        "Welcome to the Internal Support & Maintenance System.\nPlease select an option below:", 
        reply_markup=markup
    )

# Optional Admin Command to verify panel access via Telegram
@bot.message_handler(commands=['admin'])
def admin_panel_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access Denied. You are not authorized as an administrator.")
        return
    bot.reply_to(message, "👑 Admin verified successfully! You can access the web dashboard at http://127.0.0.1:5000")

@bot.message_handler(func=lambda msg: msg.from_user.id in USER_STATES and USER_STATES[msg.from_user.id]['state'] == STATE_CHOOSING_CATEGORY)
def handle_category(message):
    user_id = message.from_user.id
    text = message.text
    
    if "Fault" in text:
        category = "Fault/Maintenance"
    elif "Uniform" in text:
        category = "Uniform Request"
    else:
        bot.reply_to(message, "Please use the provided keyboard buttons.")
        return

    USER_STATES[user_id]['category'] = category
    USER_STATES[user_id]['state'] = STATE_WAITING_DESCRIPTION
    
    bot.reply_to(message, f"You selected *{category}*.\nPlease provide a short description of the issue or item needed:", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.from_user.id in USER_STATES and USER_STATES[msg.from_user.id]['state'] == STATE_WAITING_DESCRIPTION)
def handle_description(message):
    user_id = message.from_user.id
    USER_STATES[user_id]['description'] = message.text
    USER_STATES[user_id]['state'] = STATE_WAITING_PHOTO
    
    bot.reply_to(message, "Got it. Now, please upload a photo or document regarding this issue (or type /skip if none).")

@bot.message_handler(content_types=['photo', 'document'], func=lambda msg: msg.from_user.id in USER_STATES and USER_STATES[msg.from_user.id]['state'] == STATE_WAITING_PHOTO)
def handle_media(message):
    user_id = message.from_user.id
    
    if message.photo:
        file_id = message.photo[-1].file_id
        USER_STATES[user_id]['file_id'] = file_id
    
    finalize_job(message, user_id)

@bot.message_handler(commands=['skip'], func=lambda msg: msg.from_user.id in USER_STATES and USER_STATES[msg.from_user.id]['state'] == STATE_WAITING_PHOTO)
def skip_media(message):
    user_id = message.from_user.id
    USER_STATES[user_id]['file_id'] = None
    finalize_job(message, user_id)

def finalize_job(message, user_id):
    data = USER_STATES.get(user_id, {})
    
    # Generate Unique Reference Number
    ref_number = f"JC-{datetime.datetime.now().strftime('%Y')}-{random.randint(1000, 9999)}"
    
    job_record = {
        "reference": ref_number,
        "user_id": user_id,
        "username": message.from_user.username or message.from_user.first_name,
        "category": data.get('category'),
        "description": data.get('description'),
        "file_id": data.get('file_id'),
        "status": "Pending Acceptance",
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Save permanently to SQLite database
    save_job_to_db(job_record)
    
    # Clear session state
    del USER_STATES[user_id]
    
    bot.reply_to(
        message, 
        f"✅ *Request Logged Successfully!*\n\n"
        f"Reference Number: `{ref_number}`\n"
        f"Category: {job_record['category']}\n"
        f"Status: Pending Assignment\n\n"
        f"We will notify you once a technician accepts your request.", 
        parse_mode="Markdown"
    )
    
    print(f"[ADMIN ALERT] New Job Logged: {ref_number} by {job_record['username']}")

# ================= ADMIN DISPATCH FUNCTION =================
def admin_dispatch_job(target_technician_telegram_id, ref_number):
    job = get_job_from_db(ref_number)
    if not job:
        return False
        
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Accept Job", callback_data=f"accept_{ref_number}"),
        types.InlineKeyboardButton("❌ Decline", callback_data=f"decline_{ref_number}")
    )
    
    text = (
        f"🔔 *New Job Assigned!*\n\n"
        f"Ref: `{ref_number}`\n"
        f"Type: {job['category']}\n"
        f"Description: {job['description']}\n"
        f"Raised By: @{job['username']}"
    )
    
    if job['file_id']:
        bot.send_photo(target_technician_telegram_id, job['file_id'], caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(target_technician_telegram_id, text, reply_markup=markup, parse_mode="Markdown")
        
    return True

# ================= TECHNICIAN INTERACTION CALLBACKS =================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    data = call.data
    action, ref_number = data.split("_", 1)
    
    job = get_job_from_db(ref_number)
    if not job:
        bot.answer_callback_query(call.id, "Job reference not found.")
        return
        
    if action == "accept":
        update_job_status_in_db(ref_number, "Accepted / In Progress")
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎉 Mark as Complete", callback_data=f"complete_{ref_number}"))
        
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n🟢 *Status: Accepted by {call.from_user.first_name}*",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id, "Job accepted successfully!")
        
        try:
            bot.send_message(job['user_id'], f"ℹ️ Your request `{ref_number}` has been accepted and is currently in progress.")
        except Exception:
            pass
            
    elif action == "complete":
        update_job_status_in_db(ref_number, "Completed")
        
        bot.edit_message_caption(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            caption=call.message.caption + f"\n\n✅ *Status: Completed*",
            reply_markup=None,
            parse_mode="Markdown"
        )
        bot.answer_callback_query(call.id, "Job marked as complete!")
        
        try:
            bot.send_message(job['user_id'], f"🎉 Good news! Your request `{ref_number}` has been marked as **Completed**.")
        except Exception:
            pass

# ================= START BOT POLLING =================
if __name__ == '__main__':
    print("Database initialized successfully (job_system.db).")
    
    # 💡 TO ALLOCATE YOURSELF AS AN ADMIN:
    # Replace 8486991561 with your actual numeric Telegram ID and "Logan" with your name
    set_user_as_admin(8486991561, "Logan")
    
    print("Bot is up and running...")
    bot.infinity_polling()