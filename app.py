import os
import random
import datetime
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, abort, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import telebot
from telebot import types

# ================= CONFIGURATION =================
TOKEN = "8850017539:AAHiANMx1D6C684ZVy7t3Rumwlt-Tmv-Gbg"
bot = telebot.TeleBot(TOKEN, threaded=False)

app = Flask(__name__)
app.secret_key = "job_card_secure_secret_key_change_in_production"

# Supabase PostgreSQL Session Pooler Connection String (IPv4 Compatible)
DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://postgres.pmjcidhceffemcrwbbyr:T%40tumsonic2026@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
)

# Session states for users navigating the chat flow in memory
USER_STATES = {}

# State constants
STATE_CHOOSING_CATEGORY = 1
STATE_WAITING_DESCRIPTION = 2
STATE_WAITING_PHOTO = 3
STATE_WAITING_COMPLETION_COMMENT = 4

# ================= DATABASE SETUP (SUPABASE) =================
def get_db_connection():
    """Connects to Supabase PostgreSQL database."""
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            reference TEXT PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            category TEXT,
            description TEXT,
            file_id TEXT,
            status TEXT,
            completion_notes TEXT,
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            password_hash TEXT,
            role TEXT DEFAULT 'Staff',
            category TEXT
        )
    ''')
    # Safely add columns if missing
    cursor.execute('ALTER TABLE jobs ADD COLUMN IF NOT EXISTS completion_notes TEXT;')
    cursor.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;')
    cursor.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS category TEXT;')
    conn.commit()
    cursor.close()
    conn.close()

init_db()

def save_job_to_db(job_record):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO jobs (reference, user_id, username, category, description, file_id, status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (reference) DO UPDATE SET 
            status = EXCLUDED.status,
            description = EXCLUDED.description
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
    cursor.close()
    conn.close()

def get_job_from_db(ref_number):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM jobs WHERE reference = %s', (ref_number,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return dict(row) if row else None

def update_job_status_and_notes(ref_number, status, notes=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if notes is not None:
        cursor.execute('UPDATE jobs SET status = %s, completion_notes = %s WHERE reference = %s', (status, notes, ref_number))
    else:
        cursor.execute('UPDATE jobs SET status = %s WHERE reference = %s', (status, ref_number))
    conn.commit()
    cursor.close()
    conn.close()

def get_responsible_person(category):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE category = %s AND role = %s', (category, 'Technician'))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else 8486991561

def seed_default_admin():
    conn = get_db_connection()
    cursor = conn.cursor()
    pwd_hash = generate_password_hash("admin123")
    cursor.execute('''
        INSERT INTO users (user_id, username, password_hash, role, category) 
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET role = 'Admin', password_hash = EXCLUDED.password_hash
    ''', (8486991561, "Logan", pwd_hash, "Admin", "Fault/Maintenance"))
    conn.commit()
    cursor.close()
    conn.close()

seed_default_admin()

# ================= TELEGRAM BOT LOGIC =================

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
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    USER_STATES[user_id]['file_id'] = file_id
    finalize_job(message, user_id)

@bot.message_handler(commands=['skip'], func=lambda msg: msg.from_user.id in USER_STATES and USER_STATES[msg.from_user.id]['state'] == STATE_WAITING_PHOTO)
def skip_media(message):
    user_id = message.from_user.id
    USER_STATES[user_id]['file_id'] = None
    finalize_job(message, user_id)

# Handle completion comments typed by technicians in Telegram
@bot.message_handler(func=lambda msg: msg.from_user.id in USER_STATES and USER_STATES[msg.from_user.id]['state'] == STATE_WAITING_COMPLETION_COMMENT)
def handle_completion_comment(message):
    user_id = message.from_user.id
    state_data = USER_STATES[user_id]
    ref_number = state_data['ref_number']
    comment = message.text
    
    update_job_status_and_notes(ref_number, "Completed", comment)
    del USER_STATES[user_id]
    
    bot.reply_to(message, f"✅ Job `{ref_number}` has been marked as Completed with your note.", parse_mode="Markdown")
    
    job = get_job_from_db(ref_number)
    if job:
        try:
            bot.send_message(job['user_id'], f"🎉 Good news! Your request `{ref_number}` has been **Completed**.\n📝 *Note:* {comment}", parse_mode="Markdown")
        except Exception:
            pass

def finalize_job(message, user_id):
    data = USER_STATES.get(user_id, {})
    ref_number = f"JC-{datetime.datetime.now().strftime('%Y')}-{random.randint(1000, 9999)}"
    category = data.get('category')
    
    job_record = {
        "reference": ref_number,
        "user_id": user_id,
        "username": message.from_user.username or message.from_user.first_name,
        "category": category,
        "description": data.get('description'),
        "file_id": data.get('file_id'),
        "status": "Pending Acceptance",
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    save_job_to_db(job_record)
    if user_id in USER_STATES:
        del USER_STATES[user_id]
    
    responsible_telegram_id = get_responsible_person(category)
    admin_dispatch_job(responsible_telegram_id, ref_number)
    
    bot.reply_to(
        message, 
        f"✅ *Request Logged Successfully!*\n\n"
        f"Reference Number: `{ref_number}`\n"
        f"Category: {category}\n"
        f"Status: Dispatched to Department\n\n"
        f"The responsible team has been notified.", 
        parse_mode="Markdown"
    )

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
    
    if job.get('file_id'):
        bot.send_photo(target_technician_telegram_id, job['file_id'], caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(target_technician_telegram_id, text, reply_markup=markup, parse_mode="Markdown")
        
    return True

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    data = call.data
    action, ref_number = data.split("_", 1)
    job = get_job_from_db(ref_number)
    if not job:
        bot.answer_callback_query(call.id, "Job reference not found.")
        return
        
    if action == "accept":
        update_job_status_and_notes(ref_number, "Accepted / In Progress")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎉 Mark as Complete", callback_data=f"complete_{ref_number}"))
        
        try:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=call.message.caption + f"\n\n🟢 *Status: Accepted by {call.from_user.first_name}*",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Job accepted successfully!")
        try:
            bot.send_message(job['user_id'], f"ℹ️ Your request `{ref_number}` has been accepted and is currently in progress.")
        except Exception:
            pass
            
    elif action == "complete":
        user_id = call.from_user.id
        USER_STATES[user_id] = {'state': STATE_WAITING_COMPLETION_COMMENT, 'ref_number': ref_number}
        bot.answer_callback_query(call.id, "Please type your completion comment in chat.")
        bot.send_message(user_id, f"📝 Please reply with a comment / notes for completing job `{ref_number}`:", parse_mode="Markdown")

# ================= FLASK WEB ROUTES & AUTH =================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user and user['password_hash'] and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            if user['role'] in ['Admin', 'Technician']:
                return redirect(url_for('index'))
            else:
                return redirect(url_for('my_jobs'))
        else:
            return render_template('login.html', error="Invalid username or password")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_id' not in session or session.get('role') not in ['Admin', 'Technician']:
        return redirect(url_for('login'))
        
    status_filter = request.args.get('status')
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    if status_filter:
        cursor.execute('SELECT * FROM jobs WHERE status = %s ORDER BY created_at DESC', (status_filter,))
    else:
        cursor.execute('SELECT * FROM jobs ORDER BY created_at DESC')
    jobs = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('SELECT * FROM users')
    users = [dict(row) for row in cursor.fetchall()]
    
    cursor.close()
    conn.close()
    
    return render_template('index.html', jobs=jobs, users=users, current_filter=status_filter)

@app.route('/my_jobs')
def my_jobs():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM jobs WHERE user_id = %s ORDER BY created_at DESC', (user_id,))
    jobs = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    
    return render_template('my_jobs.html', jobs=jobs)

@app.route('/update_job_action/<ref_number>/<action>', methods=['POST'])
def update_job_action(ref_number, action):
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    job = get_job_from_db(ref_number)
    if not job:
        return "Job not found", 404
        
    if action == 'complete':
        notes = request.form.get('completion_notes', 'Completed via admin web portal')
        update_job_status_and_notes(ref_number, "Completed", notes)
        try:
            bot.send_message(job['user_id'], f"🎉 Good news! Your request `{ref_number}` has been marked as **Completed**.\n📝 *Note:* {notes}", parse_mode="Markdown")
        except Exception:
            pass
    elif action == 'cancel':
        update_job_status_and_notes(ref_number, "Cancelled")
        try:
            bot.send_message(job['user_id'], f"⚠️ Your request `{ref_number}` has been **Cancelled**.", parse_mode="Markdown")
        except Exception:
            pass
            
    return redirect(url_for('index'))

@app.route('/add_user', methods=['POST'])
def add_user():
    if 'user_id' not in session or session.get('role') != 'Admin':
        return redirect(url_for('login'))
        
    user_id = int(request.form.get('user_id'))
    username = request.form.get('username')
    role = request.form.get('role')
    category = request.form.get('category')
    password = request.form.get('password', 'staff123')
    pwd_hash = generate_password_hash(password)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, username, password_hash, role, category)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET 
            username = EXCLUDED.username,
            role = EXCLUDED.role,
            category = EXCLUDED.category,
            password_hash = EXCLUDED.password_hash
    ''', (user_id, username, pwd_hash, role, category))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('index'))

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        abort(403)

 if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
