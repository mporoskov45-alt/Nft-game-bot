import os
import json
import random
import time
import threading
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import telebot
from telebot import types


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

TOP_UP_CONTACTS = ["@doxme", "@modeevil", "@bogkm"]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=True)

# user_id -> state dict
states = {}
state_lock = threading.RLock()

# Prevent double-click / concurrent case opening.
user_locks = {}
user_locks_lock = threading.Lock()


# ============================================================
# DATABASE
# ============================================================

def db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10,
    )


def init_db():
    conn = db()
    try:
        cur = conn.cursor()

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
                enabled BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS opening_history (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                case_id TEXT NOT NULL,
                case_name TEXT NOT NULL,
                prize_name TEXT NOT NULL,
                prize_type TEXT NOT NULL,
                price BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        default_cases = [
            ("bileter", "🎫 Билетёр", 100, True),
            ("risk", "🍬 Ириски и риски", 0, True),
            ("luxury", "💎 Лакшери", 2000, True),
            ("narkoman", "🥤 Наркоман", 100, True),
            ("colors", "🔴🔵🟡 Цвет", 100, True),
        ]

        for item in default_cases:
            cur.execute("""
                INSERT INTO cases(case_id, name, price, enabled)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(case_id) DO NOTHING
            """, item)

        conn.commit()
        cur.close()
    finally:
        conn.close()


def ensure_user(user_id: int, username="", first_name=""):
    conn = db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            INSERT INTO users(user_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT(user_id)
            DO UPDATE SET username=EXCLUDED.username,
                          first_name=EXCLUDED.first_name
            RETURNING *
        """, (user_id, username or "", first_name or ""))

        user = cur.fetchone()
        conn.commit()
        cur.close()
        return user
    finally:
        conn.close()


def get_user(user_id: int):
    conn = db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cur.fetchone()
        cur.close()
        return user
    finally:
        conn.close()


def get_balance(user_id: int) -> int:
    user = get_user(user_id)
    if not user:
        ensure_user(user_id)
        return 0
    return int(user["stars"])


def change_balance(user_id: int, amount: int, allow_negative=False):
    """
    Atomic balance update.
    Returns new balance or None if user doesn't exist / insufficient funds.
    """
    conn = db()
    try:
        cur = conn.cursor()

        if allow_negative:
            cur.execute("""
                UPDATE users
                SET stars = stars + %s
                WHERE user_id=%s
                RETURNING stars
            """, (amount, user_id))
        else:
            cur.execute("""
                UPDATE users
                SET stars = stars + %s
                WHERE user_id=%s AND stars + %s >= 0
                RETURNING stars
            """, (amount, user_id, amount))

        result = cur.fetchone()

        if not result:
            conn.rollback()
            return None

        conn.commit()
        return int(result[0])
    finally:
        conn.close()


def get_inventory(user_id: int):
    user = get_user(user_id)
    if not user:
        return []

    try:
        data = json.loads(user["inventory"] or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add_inventory(user_id: int, item: dict):
    conn = db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT inventory FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return False

        try:
            inventory = json.loads(row[0] or "[]")
            if not isinstance(inventory, list):
                inventory = []
        except Exception:
            inventory = []

        inventory.append(item)

        cur.execute("""
            UPDATE users
            SET inventory=%s
            WHERE user_id=%s
        """, (json.dumps(inventory, ensure_ascii=False), user_id))

        conn.commit()
        return True
    finally:
        conn.close()


def get_all_users():
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users ORDER BY user_id")
        result = [int(row[0]) for row in cur.fetchall()]
        cur.close()
        return result
    finally:
        conn.close()


def get_stats():
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), COALESCE(SUM(stars), 0) FROM users")
        users, stars = cur.fetchone()

        cur.execute("SELECT COUNT(*) FROM opening_history")
        openings = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM cases WHERE enabled=TRUE")
        enabled_cases = cur.fetchone()[0]

        cur.close()
        return int(users), int(stars), int(openings), int(enabled_cases)
    finally:
        conn.close()


# ============================================================
# CASES / HISTORY
# ============================================================

def case_info(case_id):
    conn = db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM cases WHERE case_id=%s", (case_id,))
        result = cur.fetchone()
        cur.close()
        return result
    finally:
        conn.close()


def is_enabled(case_id):
    case = case_info(case_id)
    return bool(case and case["enabled"])


def set_case_enabled(case_id, enabled):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE cases SET enabled=%s WHERE case_id=%s",
            (bool(enabled), case_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_history(user_id, case, prize, price):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO opening_history(
                user_id, case_id, case_name,
                prize_name, prize_type, price
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            case["case_id"],
            case["name"],
            prize["name"],
            prize["type"],
            price,
        ))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# USER LOCK
# ============================================================

def get_user_lock(user_id):
    with user_locks_lock:
        if user_id not in user_locks:
            user_locks[user_id] = threading.Lock()
        return user_locks[user_id]


# ============================================================
# UI
# ============================================================

def main_keyboard(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton("🎁 КЕЙСЫ", callback_data="cases"),
        types.InlineKeyboardButton("👤 ПРОФИЛЬ", callback_data="profile"),
    )
    kb.add(
        types.InlineKeyboardButton("🎒 ИНВЕНТАРЬ", callback_data="inventory"),
        types.InlineKeyboardButton("⭐ ПОПОЛНИТЬ", callback_data="topup"),
    )

    if user_id in ADMINS:
        kb.add(types.InlineKeyboardButton("👑 АДМИН-ПАНЕЛЬ", callback_data="admin"))

    return kb


def home_keyboard(user_id):
    return main_keyboard(user_id)


def back_keyboard(target="home"):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=target))
    return kb


def cases_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)

    for case_id in ["bileter", "risk", "luxury", "narkoman", "colors"]:
        case = case_info(case_id)
        if not case or not case["enabled"]:
            continue

        price = int(case["price"])
        if case_id == "risk":
            label = f"{case['name']} — 🎯 Ставка"
        else:
            label = f"{case['name']} — {price:,} ⭐".replace(",", " ")

        kb.add(types.InlineKeyboardButton(
            label,
            callback_data=f"open:{case_id}"
        ))

    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="home"))
    return kb


def color_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("🔴", callback_data="color:red"),
        types.InlineKeyboardButton("🔵", callback_data="color:blue"),
        types.InlineKeyboardButton("🟡", callback_data="color:yellow"),
    )
    kb.add(types.InlineKeyboardButton("❌ Отмена", callback_data="cases"))
    return kb


def admin_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton("⭐ Выдать", callback_data="admin:add"),
        types.InlineKeyboardButton("➖ Снять", callback_data="admin:remove"),
    )
    kb.add(
        types.InlineKeyboardButton("👤 Пользователь", callback_data="admin:user"),
        types.InlineKeyboardButton("🎁 Кейсы", callback_data="admin:cases"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin:stats"),
        types.InlineKeyboardButton("📜 История", callback_data="admin:history"),
    )
    kb.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="admin:broadcast"))
    kb.add(types.InlineKeyboardButton("⬅️ Главное меню", callback_data="home"))
    return kb


def admin_cases_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)

    for case_id in ["bileter", "risk", "luxury", "narkoman", "colors"]:
        case = case_info(case_id)
        if not case:
            continue

        status = "🟢 ВКЛЮЧЕН" if case["enabled"] else "🔴 ВЫКЛЮЧЕН"
        price = int(case["price"])

        kb.add(types.InlineKeyboardButton(
            f"{case['name']} • {price:,} ⭐ • {status}".replace(",", " "),
            callback_data=f"toggle:{case_id}"
        ))

    kb.add(types.InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin"))
    return kb


# ============================================================
# TEXT
# ============================================================

HOME_TEXT = """
<b>🎁 CASES WAVEGRAM</b>

━━━━━━━━━━━━━━━━━━━━

Добро пожаловать в кейс-сервис.

🎁 Открывай кейсы
⭐ Играй за звёзды
🎒 Забирай призы в инвентарь

Выбери раздел ниже 👇
"""


def profile_text(user_id):
    user = get_user(user_id) or ensure_user(user_id)
    inventory = get_inventory(user_id)
    username = f"@{user['username']}" if user["username"] else "не указан"

    return f"""
<b>👤 ПРОФИЛЬ</b>

━━━━━━━━━━━━━━━━━━━━

🆔 ID: <code>{user_id}</code>
👤 Username: {username}

⭐ Баланс: <b>{int(user['stars']):,}</b>
🎒 Предметов: <b>{len(inventory)}</b>
""".replace(",", " ")


def inventory_text(user_id):
    inventory = get_inventory(user_id)

    if not inventory:
        return """
<b>🎒 ИНВЕНТАРЬ</b>

━━━━━━━━━━━━━━━━━━━━

Пока пусто.

Открывай кейсы и получай призы 🎁
"""

    text = "<b>🎒 ИНВЕНТАРЬ</b>\n\n━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, item in enumerate(inventory[-30:], 1):
        text += (
            f"<b>{i}.</b> {item.get('name', 'Предмет')}\n"
            f"   └ {item.get('type', 'item')}\n\n"
        )

    return text


def topup_text():
    contacts = "\n".join(f"👤 {x}" for x in TOP_UP_CONTACTS)

    return f"""
<b>⭐ ПОПОЛНЕНИЕ</b>

━━━━━━━━━━━━━━━━━━━━

Для пополнения напиши продавцу:

{contacts}

После оплаты отправь продавцу свой Telegram ID.

🆔 ID можно посмотреть в разделе «Профиль».
"""


# ============================================================
# PRIZES
# ============================================================

def bileter_prize():
    if random.random() < 0.02:
        return {"name": "🥇 Золотой билет", "type": "NFT", "valuable": True}

    return {
        "name": "🎫 Обычный билет",
        "type": "stars",
        "stars": 50,
        "valuable": False,
    }


def narkoman_prize():
    if random.random() < 0.50:
        return {
            "name": "⭐ 50 звёзд",
            "type": "stars",
            "stars": 50,
            "valuable": False,
        }

    return {"name": "👁️ NFT Глазик", "type": "NFT", "valuable": True}


def luxury_prize():
    return {
        "name": random.choice([
            "🎁 Wavegram Gift #1",
            "🎁 Wavegram Gift #2",
            "🎁 Wavegram Gift #3",
            "💎 Wavegram Luxury Gift",
            "👑 Wavegram Premium Gift",
        ]),
        "type": "Gift",
        "valuable": True,
    }


# ============================================================
# ADMIN NOTIFICATION
# ============================================================

def notify_admins_win(user_id, username, case_name, prize):
    text = f"""
<b>🚨 ЦЕННЫЙ ВЫИГРЫШ</b>

👤 <code>{user_id}</code>
{('@' + username) if username else 'без username'}

🎁 {case_name}
🏆 <b>{prize}</b>
"""

    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, text)
        except Exception:
            pass


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    u = message.from_user
    ensure_user(u.id, u.username, u.first_name)

    bot.send_message(
        message.chat.id,
        HOME_TEXT,
        reply_markup=main_keyboard(u.id),
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    user_id = call.from_user.id
    u = call.from_user

    ensure_user(user_id, u.username, u.first_name)

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    data = call.data or ""

    # HOME
    if data == "home":
        try:
            bot.edit_message_text(
                HOME_TEXT,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_keyboard(user_id),
            )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                HOME_TEXT,
                reply_markup=main_keyboard(user_id),
            )
        return

    # PROFILE
    if data == "profile":
        bot.edit_message_text(
            profile_text(user_id),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard(),
        )
        return

    # INVENTORY
    if data == "inventory":
        bot.edit_message_text(
            inventory_text(user_id),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard(),
        )
        return

    # TOPUP
    if data == "topup":
        bot.edit_message_text(
            topup_text(),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_keyboard(),
        )
        return

    # CASES
    if data == "cases":
        text = """
<b>🎁 КЕЙСЫ</b>

━━━━━━━━━━━━━━━━━━━━

🎫 Билетёр — 100 ⭐
🍬 Ириски и риски — ставка
💎 Лакшери — 2 000 ⭐
🥤 Наркоман — 100 ⭐
🔴🔵🟡 Цвет — 100 ⭐

Выбери кейс 👇
"""
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=cases_keyboard(),
        )
        return

    # OPEN
    if data.startswith("open:"):
        open_case(call, data.split(":", 1)[1])
        return

    # COLORS
    if data.startswith("color:"):
        play_color(call, data.split(":", 1)[1])
        return

    # ADMIN
    if data == "admin":
        if user_id not in ADMINS:
            bot.answer_callback_query(call.id, "⛔ Нет доступа", show_alert=True)
            return

        bot.edit_message_text(
            """
<b>👑 ADMIN CONTROL</b>

━━━━━━━━━━━━━━━━━━━━

Управление ботом:

⭐ Балансы
👤 Пользователи
🎁 Кейсы
📊 Статистика
📜 История
📢 Рассылка
""",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_keyboard(),
        )
        return

    if data.startswith("admin:"):
        if user_id not in ADMINS:
            bot.answer_callback_query(call.id, "⛔ Нет доступа", show_alert=True)
            return

        admin_action(call, data.split(":", 1)[1])
        return

    if data.startswith("toggle:"):
        if user_id not in ADMINS:
            return

        case_id = data.split(":", 1)[1]
        case = case_info(case_id)
        if not case:
            return

        set_case_enabled(case_id, not case["enabled"])

        bot.edit_message_text(
            "<b>🎁 УПРАВЛЕНИЕ КЕЙСАМИ</b>\n\nСтатус обновлён.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_cases_keyboard(),
        )


# ============================================================
# ADMIN ACTIONS
# ============================================================

def admin_action(call, action):
    user_id = call.from_user.id

    if action == "add":
        set_state(user_id, "admin_add")
        bot.send_message(
            user_id,
            "<b>⭐ ВЫДАТЬ ЗВЁЗДЫ</b>\n\n"
            "Формат:\n<code>ID количество</code>\n\n"
            "Пример:\n<code>123456789 500</code>",
        )

    elif action == "remove":
        set_state(user_id, "admin_remove")
        bot.send_message(
            user_id,
            "<b>➖ СНЯТЬ ЗВЁЗДЫ</b>\n\n"
            "Формат:\n<code>ID количество</code>",
        )

    elif action == "user":
        set_state(user_id, "admin_user")
        bot.send_message(
            user_id,
            "<b>👤 ПОЛЬЗОВАТЕЛЬ</b>\n\n"
            "Отправь Telegram ID пользователя.",
        )

    elif action == "cases":
        bot.edit_message_text(
            "<b>🎁 УПРАВЛЕНИЕ КЕЙСАМИ</b>\n\n"
            "Нажми на кейс, чтобы включить или выключить его:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_cases_keyboard(),
        )

    elif action == "stats":
        users, stars, openings, enabled = get_stats()

        bot.edit_message_text(
            f"""
<b>📊 СТАТИСТИКА</b>

━━━━━━━━━━━━━━━━━━━━

👥 Пользователей: <b>{users}</b>
⭐ Всего звёзд: <b>{stars}</b>
🎁 Открытий: <b>{openings}</b>
🟢 Активных кейсов: <b>{enabled}</b>
👑 Админов: <b>{len(ADMINS)}</b>
""",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_keyboard(),
        )

    elif action == "history":
        bot.send_message(
            user_id,
            "<b>📜 ИСТОРИЯ</b>\n\n"
            "История открытий хранится в таблице "
            "<code>opening_history</code> PostgreSQL.\n"
            "Для просмотра конкретного пользователя отправь его ID через «Пользователь».",
        )

    elif action == "broadcast":
        set_state(user_id, "broadcast")
        bot.send_message(
            user_id,
            "<b>📢 BROADCAST</b>\n\n"
            "Отправь текст сообщения для рассылки.\n\n"
            "⚠️ Рассылка выполняется всем пользователям из базы.",
        )


# ============================================================
# OPEN CASE
# ============================================================

def open_case(call, case_id):
    user_id = call.from_user.id

    if not is_enabled(case_id):
        bot.answer_callback_query(
            call.id,
            "❌ Кейс сейчас выключен",
            show_alert=True,
        )
        return

    case = case_info(case_id)
    if not case:
        bot.answer_callback_query(
            call.id,
            "❌ Кейс не найден",
            show_alert=True,
        )
        return

    # RISK
    if case_id == "risk":
        set_state(user_id, "risk_bet")
        bot.send_message(
            call.message.chat.id,
            """
<b>🍬 ИРИСКИ И РИСКИ</b>

━━━━━━━━━━━━━━━━━━━━

Введи ставку в ⭐.

🎯 Победа: ставка × 2
💥 Проигрыш: ставка сгорает

Например:
<code>100</code>
""",
            reply_markup=back_keyboard("cases"),
        )
        return

    # COLORS
    if case_id == "colors":
        if get_balance(user_id) < 100:
            bot.answer_callback_query(
                call.id,
                "❌ Недостаточно ⭐",
                show_alert=True,
            )
            return

        # ВАЖНО: деньги списываются только один раз здесь.
        new_balance = change_balance(user_id, -100)
        if new_balance is None:
            bot.answer_callback_query(
                call.id,
                "❌ Недостаточно ⭐",
                show_alert=True,
            )
            return

        set_state(user_id, "color_game")

        bot.send_message(
            call.message.chat.id,
            """
<b>🔴 🔵 🟡 ЦВЕТ</b>

━━━━━━━━━━━━━━━━━━━━

Стоимость: <b>100 ⭐</b>

В одном из трёх цветов находится NFT.

Выбирай 👇
""",
            reply_markup=color_keyboard(),
        )
        return

    price = int(case["price"])

    # Atomic lock against double clicks.
    lock = get_user_lock(user_id)
    if not lock.acquire(blocking=False):
        bot.answer_callback_query(
            call.id,
            "⏳ Подожди, кейс уже открывается",
            show_alert=True,
        )
        return

    try:
        if get_balance(user_id) < price:
            bot.answer_callback_query(
                call.id,
                "❌ Недостаточно ⭐",
                show_alert=True,
            )
            return

        if change_balance(user_id, -price) is None:
            bot.answer_callback_query(
                call.id,
                "❌ Не удалось списать ⭐",
                show_alert=True,
            )
            return

        # Short animation.
        try:
            msg = bot.send_message(
                call.message.chat.id,
                "🎁 <b>Открываем кейс...</b>",
            )

            for emoji in ["🎁", "✨", "🎁", "💫", "🎁"]:
                time.sleep(0.18)
                try:
                    bot.edit_message_text(
                        f"<b>{emoji}</b>\n\nОткрываем...",
                        msg.chat.id,
                        msg.message_id,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        if case_id == "bileter":
            prize = bileter_prize()
        elif case_id == "narkoman":
            prize = narkoman_prize()
        elif case_id == "luxury":
            prize = luxury_prize()
        else:
            prize = {
                "name": "🎁 Приз",
                "type": "Gift",
                "valuable": True,
            }

        if prize.get("type") == "stars":
            amount = int(prize["stars"])
            change_balance(user_id, amount)
        else:
            add_inventory(
                user_id,
                {
                    "name": prize["name"],
                    "type": prize["type"],
                    "time": int(time.time()),
                },
            )

        save_history(user_id, case, prize, price)

        text = f"""
<b>🎉 ВЫИГРЫШ!</b>

━━━━━━━━━━━━━━━━━━━━

🎁 Кейс: <b>{case['name']}</b>

🏆 Приз:
<b>{prize['name']}</b>
"""

        if prize.get("type") == "stars":
            text += f"\n⭐ Зачислено: <b>{prize['stars']}</b>"

        text += f"\n\n💰 Баланс: <b>{get_balance(user_id)}</b> ⭐"

        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=main_keyboard(user_id),
        )

        if prize.get("valuable"):
            notify_admins_win(
                user_id,
                call.from_user.username,
                case["name"],
                prize["name"],
            )
    finally:
        lock.release()


# ============================================================
# COLOR GAME
# ============================================================

def play_color(call, selected):
    user_id = call.from_user.id

    with state_lock:
        state = states.get(user_id)

    if not state or state.get("state") != "color_game":
        bot.answer_callback_query(
            call.id,
            "❌ Эта игра уже завершена",
            show_alert=True,
        )
        return

    if selected not in {"red", "blue", "yellow"}:
        return

    with state_lock:
        states.pop(user_id, None)

    names = {
        "red": "🔴 Красный",
        "blue": "🔵 Синий",
        "yellow": "🟡 Жёлтый",
    }

    winning_color = random.choice(list(names.keys()))

    if selected == winning_color:
        prize = {
            "name": "🎁 NFT",
            "type": "NFT",
            "valuable": True,
        }

        add_inventory(
            user_id,
            {
                "name": prize["name"],
                "type": "NFT",
                "time": int(time.time()),
            },
        )

        case = case_info("colors")
        if case:
            save_history(user_id, case, prize, 100)

        bot.send_message(
            call.message.chat.id,
            f"""
<b>🎉 ПОБЕДА!</b>

━━━━━━━━━━━━━━━━━━━━

Правильный цвет:
<b>{names[winning_color]}</b>

🎁 Ты получил:
<b>NFT</b>
""",
            reply_markup=main_keyboard(user_id),
        )

        notify_admins_win(
            user_id,
            call.from_user.username,
            "🔴🔵🟡 Цвет",
            "🎁 NFT",
        )
    else:
        bot.send_message(
            call.message.chat.id,
            f"""
<b>💥 ПРОИГРЫШ</b>

━━━━━━━━━━━━━━━━━━━━

NFT находился в:
<b>{names[winning_color]}</b>

Ты выбрал:
<b>{names[selected]}</b>

🍀 Повезёт в следующий раз.
""",
            reply_markup=main_keyboard(user_id),
        )


# ============================================================
# STATE HELPERS
# ============================================================

def set_state(user_id, state, **extra):
    with state_lock:
        states[user_id] = {"state": state, **extra}


def pop_state(user_id):
    with state_lock:
        return states.pop(user_id, None)


# ============================================================
# TEXT HANDLER
# ============================================================

@bot.message_handler(content_types=["text"])
def text_handler(message):
    user_id = message.from_user.id
    ensure_user(user_id, message.from_user.username, message.from_user.first_name)

    with state_lock:
        state = dict(states.get(user_id, {}))

    current_state = state.get("state")
    if not current_state:
        return

    text = message.text.strip()

    # RISK
    if current_state == "risk_bet":
        try:
            bet = int(text)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ Введи целое число, например <code>100</code>.",
            )
            return

        if bet <= 0:
            bot.send_message(message.chat.id, "❌ Ставка должна быть больше 0.")
            return

        if bet > get_balance(user_id):
            bot.send_message(message.chat.id, "❌ Недостаточно ⭐.")
            return

        if change_balance(user_id, -bet) is None:
            bot.send_message(message.chat.id, "❌ Не удалось списать ставку.")
            return

        win = random.random() < 0.5

        if win:
            reward = bet * 2
            change_balance(user_id, reward)

            result = f"""
<b>🍬 ИРИСКА — ПОБЕДА!</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Ставка: <b>{bet}</b> ⭐
🎉 Выплата: <b>{reward}</b> ⭐

💰 Баланс: <b>{get_balance(user_id)}</b> ⭐
"""
        else:
            result = f"""
<b>💥 ИРИСКА — ПРОИГРЫШ</b>

━━━━━━━━━━━━━━━━━━━━

🎯 Ставка: <b>{bet}</b> ⭐
❌ Потеряно: <b>{bet}</b> ⭐

💰 Баланс: <b>{get_balance(user_id)}</b> ⭐
"""

        pop_state(user_id)

        bot.send_message(
            message.chat.id,
            result,
            reply_markup=main_keyboard(user_id),
        )
        return

    # ADMIN ADD
    if current_state == "admin_add":
        if user_id not in ADMINS:
            pop_state(user_id)
            return

        parts = text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "Формат: <code>ID количество</code>")
            return

        try:
            target_id = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "❌ ID и количество должны быть числами.")
            return

        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Количество должно быть больше 0.")
            return

        ensure_user(target_id)
        new_balance = change_balance(target_id, amount, allow_negative=True)

        pop_state(user_id)

        bot.send_message(
            message.chat.id,
            f"""
<b>✅ ЗВЁЗДЫ ВЫДАНЫ</b>

👤 ID: <code>{target_id}</code>
➕ <b>{amount}</b> ⭐
💰 Новый баланс: <b>{new_balance}</b> ⭐
""",
            reply_markup=admin_keyboard(),
        )

        try:
            bot.send_message(
                target_id,
                f"⭐ Вам начислено <b>+{amount}</b> ⭐\n"
                f"Баланс: <b>{new_balance}</b> ⭐",
            )
        except Exception:
            pass
        return

    # ADMIN REMOVE
    if current_state == "admin_remove":
        if user_id not in ADMINS:
            pop_state(user_id)
            return

        parts = text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "Формат: <code>ID количество</code>")
            return

        try:
            target_id = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "❌ ID и количество должны быть числами.")
            return

        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Количество должно быть больше 0.")
            return

        if not get_user(target_id):
            bot.send_message(message.chat.id, "❌ Пользователь не найден.")
            return

        new_balance = change_balance(target_id, -amount)

        if new_balance is None:
            bot.send_message(message.chat.id, "❌ Недостаточно ⭐ у пользователя.")
            return

        pop_state(user_id)

        bot.send_message(
            message.chat.id,
            f"""
<b>✅ ЗВЁЗДЫ СНЯТЫ</b>

👤 ID: <code>{target_id}</code>
➖ <b>{amount}</b> ⭐
💰 Новый баланс: <b>{new_balance}</b> ⭐
""",
            reply_markup=admin_keyboard(),
        )
        return

    # ADMIN USER
    if current_state == "admin_user":
        if user_id not in ADMINS:
            pop_state(user_id)
            return

        try:
            target_id = int(text)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Отправь корректный Telegram ID.")
            return

        target = get_user(target_id)
        if not target:
            bot.send_message(message.chat.id, "❌ Пользователь не найден.")
            return

        inventory = get_inventory(target_id)

        pop_state(user_id)

        bot.send_message(
            message.chat.id,
            f"""
<b>👤 ПОЛЬЗОВАТЕЛЬ</b>

━━━━━━━━━━━━━━━━━━━━

🆔 ID: <code>{target_id}</code>
👤 Username: @{target['username'] if target['username'] else 'нет'}

⭐ Баланс: <b>{target['stars']}</b>
🎒 Предметов: <b>{len(inventory)}</b>
""",
            reply_markup=admin_keyboard(),
        )
        return

    # BROADCAST
    if current_state == "broadcast":
        if user_id not in ADMINS:
            pop_state(user_id)
            return

        users = get_all_users()
        success = 0
        failed = 0

        for target_id in users:
            try:
                bot.send_message(target_id, text)
                success += 1
            except Exception:
                failed += 1
            time.sleep(0.03)

        pop_state(user_id)

        bot.send_message(
            message.chat.id,
            f"""
<b>📢 РАССЫЛКА ЗАВЕРШЕНА</b>

━━━━━━━━━━━━━━━━━━━━

✅ Успешно: <b>{success}</b>
❌ Ошибок: <b>{failed}</b>
""",
            reply_markup=admin_keyboard(),
        )
        return


# ============================================================
# ERRORS / POLLING
# ============================================================

def safe_polling():
    while True:
        try:
            print("=" * 50)
            print("CASE BOT STARTING")
            print("DATABASE:", "configured")
            print("ADMINS:", ADMINS)
            print("=" * 50)

            init_db()

            bot.infinity_polling(
                skip_pending=True,
                timeout=30,
                long_polling_timeout=30,
            )

        except Exception as e:
            print("BOT ERROR:", repr(e))
            print("Restarting in 5 seconds...")
            time.sleep(5)


if __name__ == "__main__":
    safe_polling()
