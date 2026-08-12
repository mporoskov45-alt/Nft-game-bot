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

API_SERVER = os.getenv(
    "API_SERVER",
    "http://31.76.20.193:8081"
).strip()

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

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    threaded=True
)

# Пользовательские состояния
states = {}

# Чтобы два действия одного пользователя
# не выполнялись одновременно
user_locks = {}

# ============================================================
# DATABASE
# ============================================================

def db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10
    )


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            stars BIGINT DEFAULT 0,
            inventory TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price BIGINT DEFAULT 0,
            enabled BOOLEAN DEFAULT TRUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()

    default_cases = [
        ("bileter", "🎫 Билетёр", 100, True),
        ("risk", "🍬 Ириски и риски", 0, True),
        ("luxury", "💎 Лакшери", 2000, True),
        ("narkoman", "🥤 Наркоман", 100, True),
        ("colors", "🔴🔵🟡 Красный • Синий • Жёлтый", 100, True),
    ]

    for case in default_cases:
        cur.execute("""
            INSERT INTO cases(case_id, name, price, enabled)
            VALUES(%s, %s, %s, %s)
            ON CONFLICT(case_id) DO NOTHING
        """, case)

    conn.commit()
    cur.close()
    conn.close()


def get_user(user_id: int, username="", first_name=""):
    conn = db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        "SELECT * FROM users WHERE user_id=%s",
        (user_id,)
    )

    user = cur.fetchone()

    if not user:
        cur.execute("""
            INSERT INTO users(
                user_id,
                username,
                first_name,
                stars,
                inventory
            )
            VALUES(%s, %s, %s, 0, '[]')
            RETURNING *
        """, (
            user_id,
            username or "",
            first_name or ""
        ))

        user = cur.fetchone()
    else:
        cur.execute("""
            UPDATE users
            SET username=%s,
                first_name=%s
            WHERE user_id=%s
        """, (
            username or "",
            first_name or "",
            user_id
        ))

    conn.commit()
    cur.close()
    conn.close()

    return user


def get_balance(user_id: int):
    user = get_user(user_id)
    return int(user["stars"])


def change_balance(user_id: int, amount: int):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET stars = stars + %s
        WHERE user_id=%s
        RETURNING stars
    """, (amount, user_id))

    result = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    if not result:
        return None

    return int(result[0])


def get_inventory(user_id: int):
    user = get_user(user_id)

    try:
        return json.loads(user["inventory"] or "[]")
    except Exception:
        return []


def add_inventory(user_id: int, item: dict):
    inventory = get_inventory(user_id)
    inventory.append(item)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET inventory=%s
        WHERE user_id=%s
    """, (
        json.dumps(
            inventory,
            ensure_ascii=False
        ),
        user_id
    ))

    conn.commit()
    cur.close()
    conn.close()


def get_all_users():
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM users")

    users = [row[0] for row in cur.fetchall()]

    cur.close()
    conn.close()

    return users


# ============================================================
# CASES
# ============================================================

def case_info(case_id):
    conn = db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT *
        FROM cases
        WHERE case_id=%s
    """, (case_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


def is_enabled(case_id):
    case = case_info(case_id)
    return bool(case and case["enabled"])


def set_case_enabled(case_id, enabled):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE cases
        SET enabled=%s
        WHERE case_id=%s
    """, (
        enabled,
        case_id
    ))

    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# UI
# ============================================================

def main_keyboard(user_id=None):
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton(
            "🎁 Кейсы",
            callback_data="cases"
        ),
        types.InlineKeyboardButton(
            "👤 Профиль",
            callback_data="profile"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🎒 Инвентарь",
            callback_data="inventory"
        ),
        types.InlineKeyboardButton(
            "⭐ Пополнить",
            callback_data="topup"
        )
    )

    if user_id in ADMINS:
        kb.add(
            types.InlineKeyboardButton(
                "👑 Админ-панель",
                callback_data="admin"
            )
        )

    return kb


def back_button():
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="home"
        )
    )
    return kb


def cases_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)

    cases = [
        ("bileter", "🎫 Билетёр — 100 ⭐"),
        ("risk", "🍬 Ириски и риски"),
        ("luxury", "💎 Лакшери — 2 000 ⭐"),
        ("narkoman", "🥤 Наркоман — 100 ⭐"),
        ("colors", "🔴🔵🟡 Цвет — 100 ⭐"),
    ]

    for case_id, text in cases:
        if is_enabled(case_id):
            kb.add(
                types.InlineKeyboardButton(
                    text,
                    callback_data=f"open:{case_id}"
                )
            )

    kb.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="home"
        )
    )

    return kb


# ============================================================
# TEXT
# ============================================================

HOME_TEXT = """
<b>🎁 CASES WAVEGRAM</b>

Добро пожаловать в приватный кейс-сервис.

Здесь ты можешь открывать кейсы,
получать ⭐ звёзды, NFT и подарки.

Выбери нужный раздел ниже 👇
"""


def profile_text(user_id):
    user = get_user(user_id)

    username = (
        f"@{user['username']}"
        if user["username"]
        else "без username"
    )

    inventory = get_inventory(user_id)

    return f"""
<b>👤 ПРОФИЛЬ</b>

🆔 ID: <code>{user_id}</code>
👤 Username: {username}

⭐ Баланс: <b>{user['stars']}</b>

🎒 Предметов: <b>{len(inventory)}</b>
"""


def inventory_text(user_id):
    inventory = get_inventory(user_id)

    if not inventory:
        return """
<b>🎒 ИНВЕНТАРЬ</b>

Пока здесь ничего нет.
Открывай кейсы и получай призы 🎁
"""

    text = "<b>🎒 ИНВЕНТАРЬ</b>\n\n"

    for i, item in enumerate(inventory[-30:], 1):
        text += (
            f"{i}. {item.get('name', 'Предмет')}\n"
            f"   📦 {item.get('type', 'item')}\n\n"
        )

    return text


def topup_text():
    return """
<b>⭐ ПОПОЛНЕНИЕ</b>

Чтобы купить ⭐ звёзды, напишите одному из продавцов:

👤 @doxme
👤 @modeevil
👤 @bogkm

<b>Инструкция:</b>

1. Напишите продавцу.
2. Укажите необходимое количество ⭐.
3. После оплаты сообщите свой Telegram ID.
4. Администратор зачислит звёзды на ваш баланс.

Ваш ID можно посмотреть в профиле.
"""


# ============================================================
# ADMIN
# ============================================================

def admin_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)

    kb.add(
        types.InlineKeyboardButton(
            "➕ Выдать ⭐",
            callback_data="admin:add"
        ),
        types.InlineKeyboardButton(
            "➖ Снять ⭐",
            callback_data="admin:remove"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "🎁 Кейсы",
            callback_data="admin:cases"
        ),
        types.InlineKeyboardButton(
            "📊 Статистика",
            callback_data="admin:stats"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "📢 Broadcast",
            callback_data="admin:broadcast"
        )
    )

    kb.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="home"
        )
    )

    return kb


def admin_cases_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=1)

    case_ids = [
        "bileter",
        "risk",
        "luxury",
        "narkoman",
        "colors"
    ]

    for case_id in case_ids:
        case = case_info(case_id)

        if not case:
            continue

        status = "🟢 ВКЛ" if case["enabled"] else "🔴 ВЫКЛ"

        kb.add(
            types.InlineKeyboardButton(
                f"{case['name']} — {status}",
                callback_data=f"toggle:{case_id}"
            )
        )

    kb.add(
        types.InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="admin"
        )
    )

    return kb


# ============================================================
# ADMIN NOTIFICATION
# ============================================================

def notify_admins_win(user_id, username, case_name, prize):
    text = f"""
<b>🚨 НОВЫЙ ВЫИГРЫШ</b>

👤 Пользователь:
<code>{user_id}</code>

Username:
{('@' + username) if username else 'нет'}

🎁 Кейс:
<b>{case_name}</b>

🏆 Приз:
<b>{prize}</b>
"""

    for admin_id in ADMINS:
        try:
            bot.send_message(
                admin_id,
                text
            )
        except Exception:
            pass


# ============================================================
# PRIZES
# ============================================================

def bileter_prize():
    # Обычный билет — основной результат
    # Золотой билет — очень маленький шанс.
    if random.random() < 0.02:
        return {
            "name": "🥇 Золотой билет",
            "type": "NFT",
            "valuable": True
        }

    return {
        "name": "🎫 Обычный билет",
        "type": "stars",
        "stars": 50,
        "valuable": False
    }


def narkoman_prize():
    if random.random() < 0.50:
        return {
            "name": "⭐ 50 звёзд",
            "type": "stars",
            "stars": 50,
            "valuable": False
        }

    return {
        "name": "👁️ NFT Глазик",
        "type": "NFT",
        "valuable": True
    }


def luxury_prize():
    # Здесь можно заменить список на реальные NFT/Gifts.
    prizes = [
        "🎁 Wavegram Gift #1",
        "🎁 Wavegram Gift #2",
        "🎁 Wavegram Gift #3",
        "💎 Wavegram Luxury Gift",
        "👑 Wavegram Premium Gift",
    ]

    return {
        "name": random.choice(prizes),
        "type": "Gift",
        "valuable": True
    }


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):
    user = message.from_user

    get_user(
        user.id,
        user.username,
        user.first_name
    )

    bot.send_message(
        message.chat.id,
        HOME_TEXT,
        reply_markup=main_keyboard(user.id)
    )


# ============================================================
# CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: True
)
def callbacks(call):
    user_id = call.from_user.id

    get_user(
        user_id,
        call.from_user.username,
        call.from_user.first_name
    )

    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    # ---------------- HOME ----------------

    if data == "home":
        bot.edit_message_text(
            HOME_TEXT,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_keyboard(user_id)
        )
        return

    # ---------------- PROFILE ----------------

    if data == "profile":
        bot.edit_message_text(
            profile_text(user_id),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_button()
        )
        return

    # ---------------- INVENTORY ----------------

    if data == "inventory":
        bot.edit_message_text(
            inventory_text(user_id),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_button()
        )
        return

    # ---------------- TOP UP ----------------

    if data == "topup":
        bot.edit_message_text(
            topup_text(),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_button()
        )
        return

    # ---------------- CASES ----------------

    if data == "cases":
        bot.edit_message_text(
            """
<b>🎁 КЕЙСЫ</b>

Выбери кейс:

🎫 Билетёр — 100 ⭐
🍬 Ириски и риски — ставка
💎 Лакшери — 2 000 ⭐
🥤 Наркоман — 100 ⭐
🔴🔵🟡 Цвет — 100 ⭐
""",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=cases_keyboard()
        )
        return

    # ---------------- OPEN CASE ----------------

    if data.startswith("open:"):
        case_id = data.split(":", 1)[1]
        open_case(call, case_id)
        return

    # ---------------- RISK ----------------

    if data == "risk_start":
        states[user_id] = {
            "state": "risk_bet"
        }

        bot.send_message(
            call.message.chat.id,
            """
<b>🍬 ИРИСКИ И РИСКИ</b>

Введите размер ставки в ⭐.

Например:

<code>100</code>
""",
            reply_markup=back_button()
        )
        return

    # ---------------- COLORS ----------------

    if data.startswith("color:"):
        selected = data.split(":", 1)[1]
        play_color(call, selected)
        return

    # ---------------- ADMIN ----------------

    if data == "admin":
        if user_id not in ADMINS:
            return

        bot.edit_message_text(
            "<b>👑 АДМИН-ПАНЕЛЬ</b>\n\nВыберите действие:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_keyboard()
        )
        return

    if data == "admin:add":
        if user_id not in ADMINS:
            return

        states[user_id] = {
            "state": "admin_add"
        }

        bot.send_message(
            user_id,
            """
<b>➕ ВЫДАТЬ ЗВЁЗДЫ</b>

Отправь:

<code>ID количество</code>

Например:

<code>123456789 500</code>
"""
        )
        return

    if data == "admin:remove":
        if user_id not in ADMINS:
            return

        states[user_id] = {
            "state": "admin_remove"
        }

        bot.send_message(
            user_id,
            """
<b>➖ СНЯТЬ ЗВЁЗДЫ</b>

Отправь:

<code>ID количество</code>
"""
        )
        return

    if data == "admin:broadcast":
        if user_id not in ADMINS:
            return

        states[user_id] = {
            "state": "broadcast"
        }

        bot.send_message(
            user_id,
            """
<b>📢 BROADCAST</b>

Отправь сообщение, которое нужно разослать всем пользователям.
"""
        )
        return

    if data == "admin:stats":
        if user_id not in ADMINS:
            return

        users = get_all_users()

        bot.edit_message_text(
            f"""
<b>📊 СТАТИСТИКА</b>

👥 Пользователей: <b>{len(users)}</b>
👑 Администраторов: <b>{len(ADMINS)}</b>
""",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_keyboard()
        )
        return

    if data == "admin:cases":
        if user_id not in ADMINS:
            return

        bot.edit_message_text(
            "<b>🎁 УПРАВЛЕНИЕ КЕЙСАМИ</b>\n\nНажми на кейс для включения/выключения:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_cases_keyboard()
        )
        return

    if data.startswith("toggle:"):
        if user_id not in ADMINS:
            return

        case_id = data.split(":", 1)[1]

        case = case_info(case_id)

        if not case:
            return

        new_status = not case["enabled"]

        set_case_enabled(
            case_id,
            new_status
        )

        bot.edit_message_text(
            "<b>🎁 УПРАВЛЕНИЕ КЕЙСАМИ</b>\n\n"
            "Статус обновлён:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=admin_cases_keyboard()
        )

        return


# ============================================================
# OPEN CASE
# ============================================================

def open_case(call, case_id):
    user_id = call.from_user.id

    if not is_enabled(case_id):
        bot.answer_callback_query(
            call.id,
            "❌ Этот кейс выключен",
            show_alert=True
        )
        return

    case = case_info(case_id)

    if not case:
        return

    # Ириски и риски
    if case_id == "risk":
        bot.answer_callback_query(
            call.id
        )

        states[user_id] = {
            "state": "risk_bet"
        }

        bot.send_message(
            call.message.chat.id,
            """
<b>🍬 ИРИСКИ И РИСКИ</b>

Введите ставку в ⭐.

При победе:
<b>ставка × 2</b>

При проигрыше:
<b>ставка сгорает</b>
"""
        )
        return

    # Цвета
    if case_id == "colors":
        balance = get_balance(user_id)

        if balance < 100:
            bot.answer_callback_query(
                call.id,
                "❌ Недостаточно звёзд",
                show_alert=True
            )
            return

        change_balance(
            user_id,
            -100
        )

        kb = types.InlineKeyboardMarkup(row_width=3)

        kb.add(
            types.InlineKeyboardButton(
                "🔴 Красный",
                callback_data="color:red"
            ),
            types.InlineKeyboardButton(
                "🔵 Синий",
                callback_data="color:blue"
            ),
            types.InlineKeyboardButton(
                "🟡 Жёлтый",
                callback_data="color:yellow"
            )
        )

        bot.send_message(
            call.message.chat.id,
            """
<b>🔴 🔵 🟡 КРАСНЫЙ • СИНИЙ • ЖЁЛТЫЙ</b>

Стоимость попытки: <b>100 ⭐</b>

В одном цвете находится NFT.

Выбери цвет 👇
""",
            reply_markup=kb
        )
        return

    price = int(case["price"])

    balance = get_balance(user_id)

    if balance < price:
        bot.answer_callback_query(
            call.id,
            "❌ Недостаточно звёзд",
            show_alert=True
        )
        return

    # Списываем цену
    change_balance(
        user_id,
        -price
    )

    # Анимация
    try:
        msg = bot.send_message(
            call.message.chat.id,
            "🎁 Открываем кейс..."
        )

        for emoji in ["🎁", "✨", "🎁", "💫", "🎁"]:
            time.sleep(0.25)

            try:
                bot.edit_message_text(
                    f"<b>{emoji}</b>\n\nОткрываем...",
                    msg.chat.id,
                    msg.message_id
                )
            except Exception:
                pass

    except Exception:
        pass

    # Приз
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
            "valuable": True
        }

    # Звёзды
    if prize.get("type") == "stars":
        amount = int(prize["stars"])

        change_balance(
            user_id,
            amount
        )

    else:
        add_inventory(
            user_id,
            {
                "name": prize["name"],
                "type": prize["type"],
                "time": int(time.time())
            }
        )

    # Ответ
    text = f"""
<b>🎉 ВЫИГРЫШ!</b>

🎁 Кейс:
<b>{case['name']}</b>

🏆 Ваш приз:

<b>{prize['name']}</b>
"""

    if prize.get("type") == "stars":
        text += f"\n⭐ Зачислено: <b>{prize['stars']}</b>"

    text += "\n\n🍀 Поздравляем!"

    try:
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=main_keyboard(user_id)
        )
    except Exception:
        pass

    # Уведомление админам только о ценном призе
    if prize.get("valuable"):
        notify_admins_win(
            user_id,
            call.from_user.username,
            case["name"],
            prize["name"]
        )


# ============================================================
# COLOR GAME
# ============================================================

def play_color(call, selected):
    user_id = call.from_user.id

    winning_color = random.choice([
        "red",
        "blue",
        "yellow"
    ])

    names = {
        "red": "🔴 Красный",
        "blue": "🔵 Синий",
        "yellow": "🟡 Жёлтый"
    }

    if selected == winning_color:
        prize = {
            "name": "🎁 NFT",
            "type": "NFT",
            "valuable": True
        }

        add_inventory(
            user_id,
            {
                "name": prize["name"],
                "type": "NFT",
                "time": int(time.time())
            }
        )

        bot.send_message(
            call.message.chat.id,
            f"""
<b>🎉 ПОБЕДА!</b>

Правильный цвет:

{names[winning_color]}

🎁 Вы получили:
<b>NFT</b>
""",
            reply_markup=main_keyboard(user_id)
        )

        notify_admins_win(
            user_id,
            call.from_user.username,
            "🔴🔵🟡 Красный • Синий • Жёлтый",
            "🎁 NFT"
        )

    else:
        bot.send_message(
            call.message.chat.id,
            f"""
<b>💥 ПРОИГРЫШ</b>

NFT находился в:

{names[winning_color]}

Ты выбрал:

{names[selected]}

Повезёт в следующий раз 🍀
""",
            reply_markup=main_keyboard(user_id)
        )


# ============================================================
# TEXT HANDLER
# ============================================================

@bot.message_handler(
    func=lambda message: True,
    content_types=["text"]
)
def text_handler(message):
    user_id = message.from_user.id

    get_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name
    )

    state = states.get(user_id)

    if not state:
        return

    current_state = state.get("state")

    # --------------------------------------------------------
    # RISK BET
    # --------------------------------------------------------

    if current_state == "risk_bet":

        try:
            bet = int(message.text.strip())
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ Введи число, например: <code>100</code>"
            )
            return

        if bet <= 0:
            bot.send_message(
                message.chat.id,
                "❌ Ставка должна быть больше 0."
            )
            return

        balance = get_balance(user_id)

        if balance < bet:
            bot.send_message(
                message.chat.id,
                "❌ У тебя недостаточно ⭐."
            )
            return

        change_balance(
            user_id,
            -bet
        )

        # 50/50
        win = random.choice([
            True,
            False
        ])

        if win:
            reward = bet * 2

            change_balance(
                user_id,
                reward
            )

            bot.send_message(
                message.chat.id,
                f"""
<b>🍬 ИРИСКА!</b>

Ставка: <b>{bet} ⭐</b>

🎉 Ты выиграл!

⭐ Получено:
<b>{reward} ⭐</b>

💰 Баланс:
<b>{get_balance(user_id)} ⭐</b>
""",
                reply_markup=main_keyboard(user_id)
            )

        else:
            bot.send_message(
                message.chat.id,
                f"""
<b>💥 ПРОИГРАННЫЙ РИСК</b>

Ставка: <b>{bet} ⭐</b>

Ты проиграл.

💰 Баланс:
<b>{get_balance(user_id)} ⭐</b>
""",
                reply_markup=main_keyboard(user_id)
            )

        states.pop(user_id, None)
        return

    # --------------------------------------------------------
    # ADMIN ADD
    # --------------------------------------------------------

    if current_state == "admin_add":

        if user_id not in ADMINS:
            states.pop(user_id, None)
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.send_message(
                message.chat.id,
                "Формат: <code>ID количество</code>"
            )
            return

        try:
            target_id = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ Неверный ID или количество."
            )
            return

        if amount <= 0:
            return

        get_user(target_id)

        new_balance = change_balance(
            target_id,
            amount
        )

        bot.send_message(
            message.chat.id,
            f"""
✅ Звёзды выданы.

👤 ID: <code>{target_id}</code>
➕ Количество: <b>{amount} ⭐</b>
💰 Новый баланс: <b>{new_balance} ⭐</b>
"""
        )

        try:
            bot.send_message(
                target_id,
                f"""
⭐ <b>Пополнение</b>

Вам начислено:
<b>+{amount} ⭐</b>

Текущий баланс:
<b>{new_balance} ⭐</b>
"""
            )
        except Exception:
            pass

        states.pop(user_id, None)
        return

    # --------------------------------------------------------
    # ADMIN REMOVE
    # --------------------------------------------------------

    if current_state == "admin_remove":

        if user_id not in ADMINS:
            states.pop(user_id, None)
            return

        parts = message.text.split()

        if len(parts) != 2:
            bot.send_message(
                message.chat.id,
                "Формат: <code>ID количество</code>"
            )
            return

        try:
            target_id = int(parts[0])
            amount = int(parts[1])
        except ValueError:
            return

        if amount <= 0:
            return

        balance = get_balance(target_id)

        if balance < amount:
            bot.send_message(
                message.chat.id,
                "❌ У пользователя недостаточно звёзд."
            )
            return

        new_balance = change_balance(
            target_id,
            -amount
        )

        bot.send_message(
            message.chat.id,
            f"""
✅ Звёзды сняты.

👤 ID: <code>{target_id}</code>
➖ Количество: <b>{amount} ⭐</b>
💰 Новый баланс: <b>{new_balance} ⭐</b>
"""
        )

        states.pop(user_id, None)
        return

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    if current_state == "broadcast":

        if user_id not in ADMINS:
            states.pop(user_id, None)
            return

        users = get_all_users()

        success = 0
        failed = 0

        for target_id in users:
            try:
                bot.send_message(
                    target_id,
                    message.text
                )
                success += 1
            except Exception:
                failed += 1

        bot.send_message(
            message.chat.id,
            f"""
<b>📢 BROADCAST ЗАВЕРШЁН</b>

✅ Отправлено: <b>{success}</b>
❌ Ошибок: <b>{failed}</b>
"""
        )

        states.pop(user_id, None)
        return


# ============================================================
# ERROR HANDLING
# ============================================================

def safe_polling():
    while True:
        try:
            print("=" * 50)
            print("CASE BOT STARTING")
            print("=" * 50)
            print("API SERVER:", API_SERVER)
            print("ADMIN IDS:", ADMINS)

            init_db()

            print("DATABASE: OK")
            print("BOT STARTED")

            bot.infinity_polling(
                skip_pending=True,
                timeout=30,
                long_polling_timeout=30
            )

        except Exception as e:
            print("BOT ERROR:", repr(e))
            print("Restarting in 5 seconds...")
            time.sleep(5)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    safe_polling()
