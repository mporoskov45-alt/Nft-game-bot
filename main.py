import os
import json
import random
import time
import threading
import traceback
import logging
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql

import telebot
from telebot import types

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

ADMINS = {
    1780243378,
    1780243308,
    1780243345,
}

TOP_UP_CONTACTS = [
    "@doxme",
    "@modeevil",
    "@bogkm",
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ============================================================
# STATES
# ============================================================

states = {}
user_locks = {}
locks_global = threading.Lock()

def get_lock(user_id):
    with locks_global:
        if user_id not in user_locks:
            user_locks[user_id] = threading.Lock()
        return user_locks[user_id]

# ============================================================
# DATABASE
# ============================================================

def get_db():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def init_db():
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Создание таблиц
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                stars BIGINT NOT NULL DEFAULT 0,
                inventory TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price BIGINT NOT NULL DEFAULT 0,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Добавление default кейсов
        default_cases = [
            ("bileter", "🎫 Билетёр", 100),
            ("risk", "🍬 Ириски и риски", 0),
            ("luxury", "💎 Лакшери", 2000),
            ("narkoman", "🥤 Наркоман", 100),
            ("colors", "🔴🔵🟡 Красный • Синий • Жёлтый", 100),
        ]
        
        for case_id, name, price in default_cases:
            cur.execute("""
                INSERT INTO cases (case_id, name, price, enabled)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (case_id) DO NOTHING
            """, (case_id, name, price))
        
        conn.commit()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database initialization error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================
# USER FUNCTIONS
# ============================================================

def ensure_user(user_id, username="", first_name=""):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        
        if user:
            cur.execute("""
                UPDATE users 
                SET username = %s, first_name = %s 
                WHERE user_id = %s
                RETURNING *
            """, (username or "", first_name or "", user_id))
            user = cur.fetchone()
            conn.commit()
            return user
        
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, stars, inventory)
            VALUES (%s, %s, %s, 0, '[]')
            RETURNING *
        """, (user_id, username or "", first_name or ""))
        
        user = cur.fetchone()
        conn.commit()
        return user
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Ensure user error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def get_balance(user_id):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT stars FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        
        if not result:
            cur.execute("""
                INSERT INTO users (user_id, stars, inventory)
                VALUES (%s, 0, '[]')
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id,))
            conn.commit()
            return 0
        
        return int(result[0])
    except Exception as e:
        logger.error(f"Get balance error: {e}")
        return 0
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def add_stars(user_id, amount):
    if amount == 0:
        return get_balance(user_id)
    
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id, stars, inventory)
            VALUES (%s, %s, '[]')
            ON CONFLICT (user_id)
            DO UPDATE SET stars = users.stars + EXCLUDED.stars
            RETURNING stars
        """, (user_id, amount))
        
        result = cur.fetchone()
        conn.commit()
        return int(result[0]) if result else get_balance(user_id)
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Add stars error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def remove_stars(user_id, amount):
    if amount <= 0:
        return False
    
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
            SET stars = stars - %s
            WHERE user_id = %s AND stars >= %s
            RETURNING stars
        """, (amount, user_id, amount))
        
        result = cur.fetchone()
        if not result:
            conn.rollback()
            return False
        
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Remove stars error: {e}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================
# INVENTORY FUNCTIONS
# ============================================================

def get_inventory(user_id):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT inventory FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        
        if not result:
            return []
        
        try:
            inventory = json.loads(result[0] or "[]")
            return inventory if isinstance(inventory, list) else []
        except json.JSONDecodeError:
            return []
    except Exception as e:
        logger.error(f"Get inventory error: {e}")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def add_inventory(user_id, item):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Блокировка строки
        cur.execute("SELECT inventory FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
        result = cur.fetchone()
        
        if not result:
            inventory = []
            cur.execute("""
                INSERT INTO users (user_id, stars, inventory)
                VALUES (%s, 0, %s)
            """, (user_id, json.dumps([], ensure_ascii=False)))
        else:
            try:
                inventory = json.loads(result[0] or "[]")
                if not isinstance(inventory, list):
                    inventory = []
            except json.JSONDecodeError:
                inventory = []
        
        inventory.append(item)
        
        cur.execute("""
            UPDATE users
            SET inventory = %s
            WHERE user_id = %s
        """, (json.dumps(inventory, ensure_ascii=False), user_id))
        
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Add inventory error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================
# CASES FUNCTIONS
# ============================================================

def get_case(case_id):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM cases WHERE case_id = %s", (case_id,))
        return cur.fetchone()
    except Exception as e:
        logger.error(f"Get case error: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def case_enabled(case_id):
    case = get_case(case_id)
    return bool(case and case.get("enabled", False))

def toggle_case(case_id):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE cases
            SET enabled = NOT enabled
            WHERE case_id = %s
            RETURNING enabled
        """, (case_id,))
        
        result = cur.fetchone()
        conn.commit()
        return bool(result[0]) if result else None
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Toggle case error: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def get_all_users():
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Get all users error: {e}")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================
# TEXT TEMPLATES
# ============================================================

HOME_TEXT = """
<b>🎁 CASES WAVEGRAM</b>

Добро пожаловать в кейс-сервис.

Здесь можно открывать кейсы,
получать ⭐ звёзды, NFT и подарки.

Выбери нужный раздел 👇
"""

def profile_text(user_id):
    try:
        user = ensure_user(user_id)
        username = f"@{user['username']}" if user.get('username') else "без username"
        inventory = get_inventory(user_id)
        
        return f"""
<b>👤 ПРОФИЛЬ</b>

🆔 ID: <code>{user_id}</code>
👤 Username: {username}
⭐ Баланс: <b>{user.get('stars', 0)} ⭐</b>
🎒 Предметов: <b>{len(inventory)}</b>
"""
    except Exception as e:
        logger.error(f"Profile text error: {e}")
        return "❌ Ошибка загрузки профиля"

def inventory_text(user_id):
    inventory = get_inventory(user_id)
    
    if not inventory:
        return """
<b>🎒 ИНВЕНТАРЬ</b>

Пока здесь ничего нет.

Открывай кейсы и получай призы 🎁
"""
    
    text = "<b>🎒 ИНВЕНТАРЬ</b>\n\n"
    for index, item in enumerate(inventory[-30:], 1):
        text += f"<b>{index}.</b> {item.get('name', 'Предмет')}\n"
        text += f"📦 {item.get('type', 'item')}\n\n"
    
    return text

def topup_text():
    return """
<b>⭐ ПОПОЛНЕНИЕ</b>

Для покупки ⭐ напиши:

👤 @doxme
👤 @modeevil
👤 @bogkm

<b>Как пополнить:</b>

1. Напиши продавцу.
2. Укажи количество ⭐.
3. После оплаты отправь свой Telegram ID.
4. Администратор зачислит ⭐.

Твой ID находится в профиле.
"""

# ============================================================
# KEYBOARDS
# ============================================================

def home_keyboard(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎁 Кейсы", callback_data="cases"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile")
    )
    kb.add(
        types.InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"),
        types.InlineKeyboardButton("⭐ Пополнить", callback_data="topup")
    )
    
    if user_id in ADMINS:
        kb.add(types.InlineKeyboardButton("👑 Админ-панель", callback_data="admin"))
    
    return kb

def back_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="home"))
    return kb

def cases_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    case_list = [
        ("bileter", "🎫 Билетёр — 100 ⭐"),
        ("risk", "🍬 Ириски и риски — ставка"),
        ("luxury", "💎 Лакшери — 2 000 ⭐"),
        ("narkoman", "🥤 Наркоман — 100 ⭐"),
        ("colors", "🔴🔵🟡 Цвет — 100 ⭐"),
    ]
    
    for case_id, title in case_list:
        if case_enabled(case_id):
            kb.add(types.InlineKeyboardButton(title, callback_data=f"open:{case_id}"))
    
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="home"))
    return kb

def admin_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("➕ Выдать ⭐", callback_data="admin_add"),
        types.InlineKeyboardButton("➖ Снять ⭐", callback_data="admin_remove")
    )
    kb.add(
        types.InlineKeyboardButton("🎁 Управление кейсами", callback_data="admin_cases"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    )
    kb.add(
        types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="home")
    )
    return kb

def admin_cases_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)
    
    case_ids = ["bileter", "risk", "luxury", "narkoman", "colors"]
    for case_id in case_ids:
        case = get_case(case_id)
        if not case:
            continue
        
        status = "🟢 ВКЛ" if case.get("enabled", False) else "🔴 ВЫКЛ"
        kb.add(types.InlineKeyboardButton(
            f"{case.get('name', case_id)} — {status}",
            callback_data=f"toggle:{case_id}"
        ))
    
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="admin"))
    return kb

# ============================================================
# SAFE EDIT
# ============================================================

def safe_edit(call, text, reply_markup=None):
    try:
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=reply_markup
        )
    except Exception as e:
        error = str(e).lower()
        if "message is not modified" in error:
            return
        try:
            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=reply_markup
            )
        except Exception:
            logger.error(f"Safe edit error: {e}")

# ============================================================
# ADMIN NOTIFICATION
# ============================================================

def notify_admins(user_id, username, case_name, prize):
    text = f"""
<b>🚨 ЦЕННЫЙ ВЫИГРЫШ</b>

👤 Игрок: <code>{user_id}</code>
👤 Username: {('@' + username) if username else 'нет'}
🎁 Кейс: <b>{case_name}</b>
🏆 Приз: <b>{prize}</b>
"""
    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, text)
        except Exception as e:
            logger.error(f"Admin notification error: {e}")

# ============================================================
# OPEN CASE LOGIC
# ============================================================

def open_case(call, case_id):
    user_id = call.from_user.id
    
    if not case_enabled(case_id):
        bot.answer_callback_query(call.id, "❌ Этот кейс выключен", show_alert=True)
        return
    
    case = get_case(case_id)
    if not case:
        return
    
    # Обработка специальных кейсов
    if case_id == "risk":
        states[user_id] = {"state": "risk_bet"}
        bot.send_message(
            call.message.chat.id,
            """
<b>🍬 ИРИСКИ И РИСКИ</b>

Введи ставку в ⭐.

50% шанс победы.

При победе: <b>×2</b>
При проигрыше: <b>ставка сгорает</b>

Пример: <code>100</code>
""",
            reply_markup=back_keyboard()
        )
        return
    
    if case_id == "colors":
        if not remove_stars(user_id, 100):
            bot.answer_callback_query(call.id, "❌ Недостаточно ⭐", show_alert=True)
            return
        
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("🔴 Красный", callback_data="color:red"),
            types.InlineKeyboardButton("🔵 Синий", callback_data="color:blue"),
            types.InlineKeyboardButton("🟡 Жёлтый", callback_data="color:yellow")
        )
        
        bot.send_message(
            call.message.chat.id,
            """
<b>🔴 🔵 🟡 ЦВЕТ</b>

Стоимость: <b>100 ⭐</b>

Один из цветов содержит NFT.

Выбирай 👇
""",
            reply_markup=kb
        )
        return
    
    # Обычный кейс
    price = int(case.get("price", 0))
    if not remove_stars(user_id, price):
        bot.answer_callback_query(call.id, "❌ Недостаточно ⭐", show_alert=True)
        return
    
    lock = get_lock(user_id)
    if not lock.acquire(blocking=False):
        add_stars(user_id, price)
        return
    
    try:
        msg = bot.send_message(call.message.chat.id, "<b>🎁 ОТКРЫВАЕМ...</b>")
        
        frames = ["🎁", "✨", "🎁", "💫", "🎁", "✨", "🎉"]
        for frame in frames:
            time.sleep(0.25)
            try:
                bot.edit_message_text(f"<b>{frame}</b>\n\nОткрываем кейс...", msg.chat.id, msg.message_id)
            except Exception:
                pass
        
        # Генерация приза
        if case_id == "bileter":
            if random.random() < 0.02:
                prize = {"name": "🥇 Золотой билет", "type": "NFT", "valuable": True}
            else:
                prize = {"name": "🎫 Обычный билет", "type": "stars", "stars": 50, "valuable": False}
        elif case_id == "narkoman":
            if random.random() < 0.50:
                prize = {"name": "⭐ 50 звёзд", "type": "stars", "stars": 50, "valuable": False}
            else:
                prize = {"name": "👁️ NFT Глазик", "type": "NFT", "valuable": True}
        elif case_id == "luxury":
            prize = {
                "name": random.choice([
                    "🎁 Wavegram Gift #1",
                    "🎁 Wavegram Gift #2",
                    "🎁 Wavegram Gift #3",
                    "💎 Wavegram Luxury Gift",
                    "👑 Wavegram Premium Gift"
                ]),
                "type": "Gift",
                "valuable": True
            }
        else:
            prize = {"name": "🎁 Приз", "type": "Gift", "valuable": True}
        
        # Выдача приза
        if prize["type"] == "stars":
            add_stars(user_id, int(prize["stars"]))
        else:
            add_inventory(user_id, {
                "name": prize["name"],
                "type": prize["type"],
                "time": int(time.time())
            })
        
        # Результат
        result = f"""
<b>🎉 ВЫИГРЫШ!</b>

🎁 Кейс: <b>{case.get('name', '')}</b>
🏆 Приз: <b>{prize['name']}</b>
"""
        if prize["type"] == "stars":
            result += f"\n⭐ Зачислено: <b>+{prize['stars']} ⭐</b>"
        
        result += f"\n\n💰 Баланс: <b>{get_balance(user_id)} ⭐</b>\n\n🍀 Поздравляем!"
        
        bot.send_message(call.message.chat.id, result, reply_markup=home_keyboard(user_id))
        
        if prize.get("valuable"):
            notify_admins(user_id, call.from_user.username, case.get('name', ''), prize["name"])
            
    except Exception as e:
        logger.error(f"Open case error: {e}")
        add_stars(user_id, price)
        bot.send_message(
            call.message.chat.id,
            "❌ Произошла ошибка. ⭐ возвращены на баланс.",
            reply_markup=home_keyboard(user_id)
        )
    finally:
        lock.release()

def color_game(call, selected):
    user_id = call.from_user.id
    
    colors = {
        "red": "🔴 Красный",
        "blue": "🔵 Синий", 
        "yellow": "🟡 Жёлтый"
    }
    
    if selected not in colors:
        return
    
    winning = random.choice(list(colors.keys()))
    
    if selected == winning:
        add_inventory(user_id, {
            "name": "🎁 NFT",
            "type": "NFT",
            "time": int(time.time())
        })
        
        bot.send_message(
            call.message.chat.id,
            f"""
<b>🎉 ПОБЕДА!</b>

Правильный цвет: <b>{colors[winning]}</b>

🎁 Ты получил: <b>NFT</b>

⭐ Баланс: <b>{get_balance(user_id)} ⭐</b>
""",
            reply_markup=home_keyboard(user_id)
        )
        
        notify_admins(user_id, call.from_user.username, "🔴🔵🟡 Красный • Синий • Жёлтый", "🎁 NFT")
    else:
        bot.send_message(
            call.message.chat.id,
            f"""
<b>💥 ПРОИГРЫШ</b>

NFT находился в: <b>{colors[winning]}</b>
Ты выбрал: <b>{colors[selected]}</b>

⭐ Баланс: <b>{get_balance(user_id)} ⭐</b>

🍀 Повезёт в следующий раз!
""",
            reply_markup=home_keyboard(user_id)
        )

# ============================================================
# BOT HANDLERS
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):
    try:
        user = message.from_user
        ensure_user(user.id, user.username, user.first_name)
        bot.send_message(
            message.chat.id,
            HOME_TEXT,
            reply_markup=home_keyboard(user.id)
        )
        logger.info(f"User started: {user.id}")
    except Exception as e:
        logger.error(f"Start error: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка запуска. Попробуй ещё раз через несколько секунд.")

@bot.message_handler(commands=["admin"])
def admin_command(message):
    user_id = message.from_user.id
    if user_id not in ADMINS:
        bot.send_message(message.chat.id, "❌ У тебя нет доступа к админ-панели.")
        return
    
    bot.send_message(
        message.chat.id,
        "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:",
        reply_markup=admin_keyboard()
    )

@bot.message_handler(commands=["id"])
def id_command(message):
    bot.send_message(
        message.chat.id,
        f"🆔 Твой Telegram ID:\n\n<code>{message.from_user.id}</code>"
    )

@bot.message_handler(commands=["balance"])
def balance_command(message):
    try:
        balance = get_balance(message.from_user.id)
        bot.send_message(message.chat.id, f"⭐ Твой баланс:\n\n<b>{balance} ⭐</b>")
    except Exception as e:
        logger.error(f"Balance error: {e}")

@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    states.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        "✅ Действие отменено.",
        reply_markup=home_keyboard(message.from_user.id)
    )

# ============================================================
# CALLBACK HANDLER
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data or ""
    
    try:
        ensure_user(user_id, call.from_user.username, call.from_user.first_name)
    except Exception as e:
        logger.error(f"Callback user error: {e}")
        return
    
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    
    # Навигация
    if data == "home":
        safe_edit(call, HOME_TEXT, home_keyboard(user_id))
        return
    
    if data == "profile":
        safe_edit(call, profile_text(user_id), back_keyboard())
        return
    
    if data == "inventory":
        safe_edit(call, inventory_text(user_id), back_keyboard())
        return
    
    if data == "topup":
        safe_edit(call, topup_text(), back_keyboard())
        return
    
    if data == "cases":
        safe_edit(
            call,
            """
<b>🎁 КЕЙСЫ</b>

Выбери кейс:

🎫 Билетёр — 100 ⭐
🍬 Ириски и риски — ставка
💎 Лакшери — 2 000 ⭐
🥤 Наркоман — 100 ⭐
🔴🔵🟡 Цвет — 100 ⭐
""",
            cases_keyboard()
        )
        return
    
    # Открытие кейса
    if data.startswith("open:"):
        case_id = data.split(":", 1)[1]
        open_case(call, case_id)
        return
    
    # Цветная игра
    if data.startswith("color:"):
        color = data.split(":", 1)[1]
        color_game(call, color)
        return
    
    # Админ-панель
    if data == "admin":
        if user_id not in ADMINS:
            return
        safe_edit(
            call,
            "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\nВыбери действие:",
            admin_keyboard()
        )
        return
    
    if data == "admin_add":
        if user_id not in ADMINS:
            return
        states[user_id] = {"state": "admin_add"}
        bot.send_message(
            user_id,
            """
<b>➕ ВЫДАТЬ ⭐</b>

Отправь: <code>ID количество</code>

Пример: <code>123456789 500</code>

Для отмены: <code>/cancel</code>
"""
        )
        return
    
    if data == "admin_remove":
        if user_id not in ADMINS:
            return
        states[user_id] = {"state": "admin_remove"}
        bot.send_message(
            user_id,
            """
<b>➖ СНЯТЬ ⭐</b>

Отправь: <code>ID количество</code>

Пример: <code>123456789 500</code>

Для отмены: <code>/cancel</code>
"""
        )
        return
    
    if data == "admin_cases":
        if user_id not in ADMINS:
            return
        safe_edit(
            call,
            "<b>🎁 УПРАВЛЕНИЕ КЕЙСАМИ</b>\n\nНажми на кейс, чтобы включить или выключить его.",
            admin_cases_keyboard()
        )
        return
    
    if data.startswith("toggle:"):
        if user_id not in ADMINS:
            return
        case_id = data.split(":", 1)[1]
        case = get_case(case_id)
        if not case:
            return
        
        new_status = toggle_case(case_id)
        status_text = "🟢 включён" if new_status else "🔴 выключен"
        
        try:
            bot.answer_callback_query(call.id, f"{case.get('name', '')} {status_text}")
        except Exception:
            pass
        
        safe_edit(
            call,
            "<b>🎁 УПРАВЛЕНИЕ КЕЙСАМИ</b>\n\nСтатус обновлён.",
            admin_cases_keyboard()
        )
        return
    
    if data == "admin_stats":
        if user_id not in ADMINS:
            return
        users = get_all_users()
        safe_edit(
            call,
            f"""
<b>📊 СТАТИСТИКА</b>

👥 Пользователей: <b>{len(users)}</b>
👑 Администраторов: <b>{len(ADMINS)}</b>
""",
            admin_keyboard()
        )
        return
    
    if data == "admin_broadcast":
        if user_id not in ADMINS:
            return
        states[user_id] = {"state": "broadcast"}
        bot.send_message(
            user_id,
            """
<b>📢 РАССЫЛКА</b>

Отправь текст, который нужно отправить всем пользователям.

Для отмены: <code>/cancel</code>
"""
        )
        return

# ============================================================
# TEXT HANDLER
# ============================================================

@bot.message_handler(func=lambda message: True, content_types=["text"])
def text_handler(message):
    user_id = message.from_user.id
    
    try:
        ensure_user(user_id, message.from_user.username, message.from_user.first_name)
    except Exception as e:
        logger.error(f"Text user error: {e}")
        return
    
    state = states.get(user_id)
    if not state:
        return
    
    current = state.get("state")
    
    # Обработка ставки в риске
    if current == "risk_bet":
        try:
            bet = int(message.text.strip())
        except ValueError:
            bot.send_message(message.chat.id, "❌ Введи целое число.")
            return
        
        if bet <= 0:
            bot.send_message(message.chat.id, "❌ Ставка должна быть больше 0.")
            return
        
        if not remove_stars(user_id, bet):
            bot.send_message(message.chat.id, "❌ Недостаточно ⭐.")
            return
        
        win = random.random() < 0.50
        
        if win:
            reward = bet * 2
            add_stars(user_id, reward)
            bot.send_message(
                message.chat.id,
                f"""
<b>🍬 ПОБЕДА!</b>

Ставка: <b>{bet} ⭐</b>
🎉 Выигрыш: <b>+{reward} ⭐</b>
💰 Баланс: <b>{get_balance(user_id)} ⭐</b>
""",
                reply_markup=home_keyboard(user_id)
            )
        else:
            bot.send_message(
                message.chat.id,
                f"""
<b>💥 ПРОИГРЫШ</b>

Ставка: <b>{bet} ⭐</b>
Ты проиграл.

💰 Баланс: <b>{get_balance(user_id)} ⭐</b>
""",
                reply_markup=home_keyboard(user_id)
            )
        
        states.pop(user_id, None)
        return
    
    # Админ: выдача звёзд
    if current == "admin_add":
        if user_id not in ADMINS:
            states.pop(user_id, None)
            return
        
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "Формат: <code>ID количество</code>")
            return
        
        try:
            target = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "❌ Используй числа.")
            return
        
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Количество должно быть больше 0.")
            return
        
        ensure_user(target)
        new_balance = add_stars(target, amount)
        
        bot.send_message(
            message.chat.id,
            f"""
<b>✅ ЗВЁЗДЫ ВЫДАНЫ</b>

👤 ID: <code>{target}</code>
➕ Выдано: <b>{amount} ⭐</b>
💰 Баланс: <b>{new_balance} ⭐</b>
"""
        )
        
        try:
            bot.send_message(
                target,
                f"""
⭐ <b>ПОПОЛНЕНИЕ</b>

Вам начислено: <b>+{amount} ⭐</b>
Текущий баланс: <b>{new_balance} ⭐</b>
"""
            )
        except Exception:
            pass
        
        states.pop(user_id, None)
        return
    
    # Админ: снятие звёзд
    if current == "admin_remove":
        if user_id not in ADMINS:
            states.pop(user_id, None)
            return        
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "Формат: <code>ID количество</code>")
            return
        
        try:
            target = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "❌ Используй числа.")
            return
        
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Количество должно быть больше 0.")
            return
        
        if not remove_stars(target, amount):
            bot.send_message(message.chat.id, "❌ У пользователя недостаточно ⭐.")
            return
        
        new_balance = get_balance(target)
        
        bot.send_message(
            message.chat.id,
            f"""
<b>✅ ЗВЁЗДЫ СНЯТЫ</b>

👤 ID: <code>{target}</code>
➖ Снято: <b>{amount} ⭐</b>
💰 Баланс: <b>{new_balance} ⭐</b>
"""
        )
        
        try:
            bot.send_message(
                target,
                f"""
⚠️ <b>СПИСАНИЕ</b>

С баланса снято: <b>-{amount} ⭐</b>
Текущий баланс: <b>{new_balance} ⭐</b>
"""
            )
        except Exception:
            pass
        
        states.pop(user_id, None)
        return
    
    # Админ: рассылка
    if current == "broadcast":
        if user_id not in ADMINS:
            states.pop(user_id, None)
            return
        
        users = get_all_users()
        success = 0
        failed = 0
        
        bot.send_message(message.chat.id, "📢 Рассылка началась...")
        
        for target in users:
            try:
                bot.send_message(target, message.text)
                success += 1
            except Exception:
                failed += 1
            time.sleep(0.04)
        
        bot.send_message(
            message.chat.id,
            f"""
<b>📢 РАССЫЛКА ЗАВЕРШЕНА</b>

✅ Успешно: <b>{success}</b>
❌ Ошибок: <b>{failed}</b>
"""
        )
        
        states.pop(user_id, None)
        return

# ============================================================
# MAIN
# ============================================================

def main():
    try:
        logger.info("=" * 60)
        logger.info("STARTING CASE BOT")
        logger.info("=" * 60)
        logger.info(f"Admins: {ADMINS}")
        
        logger.info("Connecting database...")
        init_db()
        logger.info("Database: OK")
        
        logger.info("Bot: STARTED")
        bot.infinity_polling(skip_pending=True, timeout=30)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
    except Exception as e:
        logger.error(f"Main error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
