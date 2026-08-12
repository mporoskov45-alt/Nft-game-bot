import os
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor


# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

API_SERVER = os.getenv(
    "API_SERVER",
    "http://31.76.20.193:8081"
)

DATABASE_URL = os.getenv("DATABASE_URL")

# 3 АДМИНИСТРАТОРА
ADMIN_IDS = {
    1780243378,
    1780243308,
    1780243345
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан")

API_URL = f"{API_SERVER}/bot{BOT_TOKEN}"


# ============================================================
# DATABASE
# ============================================================

def db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            stars BIGINT DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price BIGINT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            item_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    cur.close()
    conn.close()

    create_cases()


# ============================================================
# КЕЙСЫ
# ============================================================

CASES = [
    (
        "ticket",
        "🎫 Билетёр",
        100
    ),
    (
        "luxury",
        "💎 Лакшери",
        2000
    ),
    (
        "gift",
        "🎁 Gift Box",
        100
    ),
    (
        "color",
        "🎨 Red Yellow Blue",
        100
    )
]


def create_cases():
    conn = db()
    cur = conn.cursor()

    for case_id, name, price in CASES:

        cur.execute("""
            INSERT INTO cases
                (case_id, name, price, enabled)
            VALUES
                (%s, %s, %s, TRUE)

            ON CONFLICT (case_id)
            DO UPDATE SET
                name = EXCLUDED.name,
                price = EXCLUDED.price
        """, (
            case_id,
            name,
            price
        ))

    conn.commit()

    cur.close()
    conn.close()


def get_cases():
    conn = db()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cur.execute("""
        SELECT *
        FROM cases
        ORDER BY
            CASE case_id
                WHEN 'ticket' THEN 1
                WHEN 'gift' THEN 2
                WHEN 'luxury' THEN 3
                WHEN 'color' THEN 4
                ELSE 99
            END
    """)

    result = cur.fetchall()

    cur.close()
    conn.close()

    return result


def get_case(case_id):
    conn = db()
    cur = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cur.execute("""
        SELECT *
        FROM cases
        WHERE case_id = %s
    """, (case_id,))

    result = cur.fetchone()

    cur.close()
    conn.close()

    return result


def toggle_case(case_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE cases
        SET enabled = NOT enabled
        WHERE case_id = %s
    """, (case_id,))

    conn.commit()

    cur.close()
    conn.close()


# ============================================================
# USERS
# ============================================================

def create_user(user):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users
            (user_id, username, first_name)
        VALUES
            (%s, %s, %s)

        ON CONFLICT (user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name
    """, (
        user["id"],
        user.get("username", ""),
        user.get("first_name", "")
    ))

    conn.commit()

    cur.close()
    conn.close()


def get_balance(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT stars
        FROM users
        WHERE user_id = %s
    """, (user_id,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return 0

    return row[0]


def add_stars(user_id, amount):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users
            (user_id, stars)
        VALUES
            (%s, %s)

        ON CONFLICT (user_id)
        DO UPDATE SET
            stars = users.stars + EXCLUDED.stars
    """, (
        user_id,
        amount
    ))

    conn.commit()

    cur.close()
    conn.close()


def remove_stars(user_id, amount):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET stars = stars - %s
        WHERE user_id = %s
          AND stars >= %s
    """, (
        amount,
        user_id,
        amount
    ))

    success = cur.rowcount > 0

    conn.commit()

    cur.close()
    conn.close()

    return success


# ============================================================
# INVENTORY
# ============================================================

def add_item(user_id, item_name):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO inventory
            (user_id, item_name)
        VALUES
            (%s, %s)
    """, (
        user_id,
        item_name
    ))

    conn.commit()

    cur.close()
    conn.close()


def get_inventory(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT item_name, created_at
        FROM inventory
        WHERE user_id = %s
        ORDER BY id DESC
    """, (user_id,))

    items = cur.fetchall()

    cur.close()
    conn.close()

    return items


# ============================================================
# TELEGRAM API
# ============================================================

def api(method, data=None):
    try:
        response = requests.post(
            f"{API_URL}/{method}",
            json=data or {},
            timeout=40
        )

        if response.status_code != 200:
            print(
                "API HTTP ERROR:",
                response.status_code,
                response.text
            )
            return None

        return response.json()

    except Exception as e:
        print("API ERROR:", repr(e))
        return None


def send_message(
    chat_id,
    text,
    keyboard=None
):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        data["reply_markup"] = keyboard

    return api(
        "sendMessage",
        data
    )


def edit_message(
    chat_id,
    message_id,
    text,
    keyboard=None
):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if keyboard:
        data["reply_markup"] = keyboard

    return api(
        "editMessageText",
        data
    )


def answer_callback(callback_id):
    return api(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id
        }
    )


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_keyboard():
    return {
        "inline_keyboard": [

            [
                {
                    "text": "🎁 Кейсы",
                    "callback_data": "cases"
                }
            ],

            [
                {
                    "text": "👤 Профиль",
                    "callback_data": "profile"
                },
                {
                    "text": "🎒 Инвентарь",
                    "callback_data": "inventory"
                }
            ],

            [
                {
                    "text": "⭐ Пополнить",
                    "callback_data": "deposit"
                }
            ]
        ]
    }


def cases_keyboard():

    cases = get_cases()

    keyboard = []

    for case in cases:

        if not case["enabled"]:
            continue

        keyboard.append([
            {
                "text": (
                    f"{case['name']} — "
                    f"{case['price']} ⭐"
                ),
                "callback_data":
                    f"case:{case['case_id']}"
            }
        ])

    keyboard.append([
        {
            "text": "◀️ Назад",
            "callback_data": "home"
        }
    ])

    return {
        "inline_keyboard": keyboard
    }


def admin_keyboard():
    return {
        "inline_keyboard": [

            [
                {
                    "text": "⭐ Выдать",
                    "callback_data": "admin:add"
                },
                {
                    "text": "➖ Забрать",
                    "callback_data": "admin:remove"
                }
            ],

            [
                {
                    "text": "🎁 Управление кейсами",
                    "callback_data": "admin:cases"
                }
            ],

            [
                {
                    "text": "📊 Статистика",
                    "callback_data": "admin:stats"
                }
            ],

            [
                {
                    "text": "📢 Broadcast",
                    "callback_data": "admin:broadcast"
                }
            ],

            [
                {
                    "text": "◀️ Назад",
                    "callback_data": "home"
                }
            ]
        ]
    }


# ============================================================
# ADMIN STATES
# ============================================================

admin_states = {}


# ============================================================
# START
# ============================================================

def start(message):

    user = message["from"]

    create_user(user)

    chat_id = message["chat"]["id"]

    send_message(
        chat_id,
        (
            "🎁 CASES\n\n"
            "Добро пожаловать!\n\n"
            f"⭐ Баланс: "
            f"{get_balance(user['id'])}\n\n"
            "Выбери действие:"
        ),
        main_keyboard()
    )


# ============================================================
# ПОКАЗ КЕЙСА
# ============================================================

def show_case(
    chat_id,
    message_id,
    case_id
):

    case = get_case(case_id)

    if not case:
        return

    if not case["enabled"]:

        edit_message(
            chat_id,
            message_id,
            "❌ Этот кейс сейчас выключен.",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "◀️ Назад",
                            "callback_data": "cases"
                        }
                    ]
                ]
            }
        )

        return

    descriptions = {

        "ticket": (
            "🎫 БИЛЕТЁР\n\n"
            "Билетёр даёт вам билет "
            "на поезд.\n\n"
            "🎟 Обычный билет — 50 ⭐\n"
            "🎁 Также доступны "
            "коллекционные предметы."
        ),

        "luxury": (
            "💎 ЛАКШЕРИ\n\n"
            "Лучшие Gifts сервиса.\n\n"
            "💎 Премиальный предмет."
        ),

        "gift": (
            "🎁 GIFT BOX\n\n"
            "Коллекционный подарок."
        ),

        "color": (
            "🎨 RED YELLOW BLUE\n\n"
            "Выбери один из цветов "
            "и получи коллекционный "
            "предмет."
        )
    }

    description = descriptions.get(
        case_id,
        case["name"]
    )

    text = (
        f"{description}\n\n"
        f"💰 Цена: {case['price']} ⭐"
    )

    edit_message(
        chat_id,
        message_id,
        text,
        {
            "inline_keyboard": [

                [
                    {
                        "text": "🎁 Получить",
                        "callback_data":
                            f"buy:{case_id}"
                    }
                ],

                [
                    {
                        "text": "◀️ Назад",
                        "callback_data":
                            "cases"
                    }
                ]
            ]
        }
    )


# ============================================================
# ПОЛУЧЕНИЕ ПРЕДМЕТА
# ============================================================

def buy_case(
    user_id,
    case_id
):

    case = get_case(case_id)

    if not case:
        return False, "Кейс не найден."

    if not case["enabled"]:
        return False, "Кейс выключен."

    if not remove_stars(
        user_id,
        case["price"]
    ):
        return False, "Недостаточно ⭐."

    rewards = {

        "ticket":
            "🎫 Обычный билет",

        "luxury":
            "💎 Luxury Gift",

        "gift":
            "🎁 Gift",

        "color":
            "🎨 Коллекционный предмет"
    }

    item = rewards.get(
        case_id,
        case["name"]
    )

    add_item(
        user_id,
        item
    )

    return True, item


# ============================================================
# CALLBACK HANDLER
# ============================================================

def callback_handler(callback):

    callback_id = callback["id"]

    answer_callback(
        callback_id
    )

    user = callback["from"]

    user_id = user["id"]

    message = callback.get("message")

    if not message:
        return

    chat_id = message["chat"]["id"]

    message_id = message["message_id"]

    data = callback.get(
        "data",
        ""
    )

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "home":

        edit_message(
            chat_id,
            message_id,
            (
                "🎁 CASES\n\n"
                f"⭐ Баланс: "
                f"{get_balance(user_id)}"
            ),
            main_keyboard()
        )

    # --------------------------------------------------------
    # CASES
    # --------------------------------------------------------

    elif data == "cases":

        edit_message(
            chat_id,
            message_id,
            "🎁 ДОСТУПНЫЕ КЕЙСЫ",
            cases_keyboard()
        )

    # --------------------------------------------------------
    # CASE
    # --------------------------------------------------------

    elif data.startswith("case:"):

        case_id = data.split(
            ":",
            1
        )[1]

        show_case(
            chat_id,
            message_id,
            case_id
        )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    elif data.startswith("buy:"):

        case_id = data.split(
            ":",
            1
        )[1]

        success, result = buy_case(
            user_id,
            case_id
        )

        if success:

            text = (
                "✅ ПОЛУЧЕНО!\n\n"
                f"🎁 {result}\n\n"
                f"⭐ Баланс: "
                f"{get_balance(user_id)}"
            )

        else:

            text = (
                f"❌ {result}\n\n"
                f"⭐ Баланс: "
                f"{get_balance(user_id)}"
            )

        edit_message(
            chat_id,
            message_id,
            text,
            {
                "inline_keyboard": [

                    [
                        {
                            "text": "🎁 Кейсы",
                            "callback_data": "cases"
                        }
                    ],

                    [
                        {
                            "text": "◀️ Меню",
                            "callback_data": "home"
                        }
                    ]
                ]
            }
        )

    # --------------------------------------------------------
    # PROFILE
    # --------------------------------------------------------

    elif data == "profile":

        edit_message(
            chat_id,
            message_id,
            (
                "👤 ПРОФИЛЬ\n\n"
                f"🆔 ID: {user_id}\n"
                f"⭐ Баланс: "
                f"{get_balance(user_id)}"
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "◀️ Назад",
                            "callback_data": "home"
                        }
                    ]
                ]
            }
        )

    # --------------------------------------------------------
    # INVENTORY
    # --------------------------------------------------------

    elif data == "inventory":

        items = get_inventory(
            user_id
        )

        if not items:

            text = (
                "🎒 ИНВЕНТАРЬ\n\n"
                "Пока пусто."
            )

        else:

            lines = []

            for index, item in enumerate(
                items,
                1
            ):
                lines.append(
                    f"{index}. {item[0]}"
                )

            text = (
                "🎒 ИНВЕНТАРЬ\n\n"
                + "\n".join(lines)
            )

        edit_message(
            chat_id,
            message_id,
            text,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "◀️ Назад",
                            "callback_data": "home"
                        }
                    ]
                ]
            }
        )

    # --------------------------------------------------------
    # DEPOSIT
    # --------------------------------------------------------

    elif data == "deposit":

        edit_message(
            chat_id,
            message_id,
            (
                "⭐ ПОПОЛНЕНИЕ\n\n"
                "Для покупки ⭐ напиши:\n\n"
                "@doxme\n"
                "@modeevil\n"
                "@bogkm\n\n"
                "После покупки передай "
                "свой Telegram ID.\n\n"
                "Администратор зачислит "
                "⭐ на баланс."
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "◀️ Назад",
                            "callback_data": "home"
                        }
                    ]
                ]
            }
        )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    elif data == "admin":

        if user_id not in ADMIN_IDS:
            return

        edit_message(
            chat_id,
            message_id,
            "⚙️ АДМИН-ПАНЕЛЬ",
            admin_keyboard()
        )

    # --------------------------------------------------------
    # ADMIN ADD
    # --------------------------------------------------------

    elif data == "admin:add":

        if user_id not in ADMIN_IDS:
            return

        admin_states[user_id] = {
            "action": "add",
            "step": "id"
        }

        send_message(
            chat_id,
            "⭐ Введи Telegram ID пользователя:"
        )

    # --------------------------------------------------------
    # ADMIN REMOVE
    # --------------------------------------------------------

    elif data == "admin:remove":

        if user_id not in ADMIN_IDS:
            return

        admin_states[user_id] = {
            "action": "remove",
            "step": "id"
        }

        send_message(
            chat_id,
            "➖ Введи Telegram ID пользователя:"
        )

    # --------------------------------------------------------
    # ADMIN CASES
    # --------------------------------------------------------

    elif data == "admin:cases":

        if user_id not in ADMIN_IDS:
            return

        keyboard = []

        for case in get_cases():

            status = (
                "🟢"
                if case["enabled"]
                else "🔴"
            )

            keyboard.append([
                {
                    "text":
                        f"{status} {case['name']}",
                    "callback_data":
                        f"toggle:{case['case_id']}"
                }
            ])

        keyboard.append([
            {
                "text": "◀️ Назад",
                "callback_data": "admin"
            }
        ])

        edit_message(
            chat_id,
            message_id,
            (
                "🎁 УПРАВЛЕНИЕ КЕЙСАМИ\n\n"
                "🟢 — включён\n"
                "🔴 — выключен\n\n"
                "Нажми на кейс, чтобы "
                "переключить его."
            ),
            {
                "inline_keyboard": keyboard
            }
        )

    # --------------------------------------------------------
    # TOGGLE
    # --------------------------------------------------------

    elif data.startswith("toggle:"):

        if user_id not in ADMIN_IDS:
            return

        case_id = data.split(
            ":",
            1
        )[1]

        toggle_case(
            case_id
        )

        keyboard = []

        for case in get_cases():

            status = (
                "🟢"
                if case["enabled"]
                else "🔴"
            )

            keyboard.append([
                {
                    "text":
                        f"{status} {case['name']}",
                    "callback_data":
                        f"toggle:{case['case_id']}"
                }
            ])

        keyboard.append([
            {
                "text": "◀️ Назад",
                "callback_data": "admin"
            }
        ])

        edit_message(
            chat_id,
            message_id,
            (
                "🎁 УПРАВЛЕНИЕ КЕЙСАМИ\n\n"
                "Состояние изменено."
            ),
            {
                "inline_keyboard": keyboard
            }
        )

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    elif data == "admin:stats":

        if user_id not in ADMIN_IDS:
            return

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM users"
        )
        users = cur.fetchone()[0]

        cur.execute(
            "SELECT COALESCE(SUM(stars), 0) "
            "FROM users"
        )
        stars = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM inventory"
        )
        items = cur.fetchone()[0]

        cur.close()
        conn.close()

        edit_message(
            chat_id,
            message_id,
            (
                "📊 СТАТИСТИКА\n\n"
                f"👥 Пользователей: {users}\n"
                f"⭐ На балансах: {stars}\n"
                f"🎁 Предметов: {items}"
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "◀️ Назад",
                            "callback_data": "admin"
                        }
                    ]
                ]
            }
        )

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    elif data == "admin:broadcast":

        if user_id not in ADMIN_IDS:
            return

        admin_states[user_id] = {
            "action": "broadcast"
        }

        send_message(
            chat_id,
            "📢 Отправь текст для рассылки:"
        )


# ============================================================
# ADMIN TEXT
# ============================================================

def handle_admin_message(message):

    user_id = message["from"]["id"]

    if user_id not in ADMIN_IDS:
        return False

    if user_id not in admin_states:
        return False

    state = admin_states[user_id]

    text = message.get(
        "text",
        ""
    ).strip()

    chat_id = message["chat"]["id"]

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    if state["action"] == "broadcast":

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT user_id FROM users"
        )

        users = cur.fetchall()

        cur.close()
        conn.close()

        success = 0
        failed = 0

        for row in users:

            result = send_message(
                row[0],
                "📢 СООБЩЕНИЕ\n\n" + text
            )

            if result and result.get("ok"):
                success += 1
            else:
                failed += 1

            time.sleep(0.05)

        del admin_states[user_id]

        send_message(
            chat_id,
            (
                "✅ РАССЫЛКА ЗАВЕРШЕНА\n\n"
                f"📨 Отправлено: {success}\n"
                f"❌ Ошибок: {failed}"
            )
        )

        return True

    # --------------------------------------------------------
    # USER ID
    # --------------------------------------------------------

    if state["step"] == "id":

        try:
            target_id = int(text)

        except ValueError:

            send_message(
                chat_id,
                "❌ ID должен состоять из цифр."
            )

            return True

        state["target"] = target_id
        state["step"] = "amount"

        admin_states[user_id] = state

        send_message(
            chat_id,
            "⭐ Введи количество звёзд:"
        )

        return True

    # --------------------------------------------------------
    # AMOUNT
    # --------------------------------------------------------

    if state["step"] == "amount":

        try:
            amount = int(text)

        except ValueError:

            send_message(
                chat_id,
                "❌ Введи число."
            )

            return True

        if amount <= 0:

            send_message(
                chat_id,
                "❌ Количество должно быть больше 0."
            )

            return True

        target_id = state["target"]

        # ВЫДАЧА
        if state["action"] == "add":

            add_stars(
                target_id,
                amount
            )

            new_balance = get_balance(
                target_id
            )

            send_message(
                chat_id,
                (
                    "✅ ЗВЁЗДЫ ЗАЧИСЛЕНЫ\n\n"
                    f"👤 ID: {target_id}\n"
                    f"⭐ Зачислено: {amount}\n"
                    f"💰 Баланс: {new_balance}"
                )
            )

            send_message(
                target_id,
                (
                    "⭐ ПОПОЛНЕНИЕ\n\n"
                    f"Вам зачислено: {amount} ⭐\n\n"
                    f"Баланс: {new_balance} ⭐"
                )
            )

        # СПИСАНИЕ
        elif state["action"] == "remove":

            success = remove_stars(
                target_id,
                amount
            )

            if not success:

                send_message(
                    chat_id,
                    "❌ У пользователя недостаточно ⭐."
                )

                return True

            new_balance = get_balance(
                target_id
            )

            send_message(
                chat_id,
                (
                    "✅ ЗВЁЗДЫ СПИСАНЫ\n\n"
                    f"👤 ID: {target_id}\n"
                    f"➖ Списано: {amount}\n"
                    f"💰 Баланс: {new_balance}"
                )
            )

            send_message(
                target_id,
                (
                    "➖ СПИСАНИЕ\n\n"
                    f"Списано: {amount} ⭐\n\n"
                    f"Баланс: {new_balance} ⭐"
                )
            )

        del admin_states[user_id]

        return True

    return False


# ============================================================
# UPDATE
# ============================================================

def handle_update(update):

    # CALLBACK
    if "callback_query" in update:

        callback_handler(
            update["callback_query"]
        )

        return

    # MESSAGE
    if "message" not in update:
        return

    message = update["message"]

    if "from" not in message:
        return

    user = message["from"]

    create_user(user)

    user_id = user["id"]

    text = message.get(
        "text",
        ""
    ).strip()

    # ADMIN STATE
    if user_id in ADMIN_IDS:

        if handle_admin_message(message):
            return

    # START
    if text == "/start":

        start(message)

    # CASES
    elif text == "/cases":

        send_message(
            message["chat"]["id"],
            "🎁 ДОСТУПНЫЕ КЕЙСЫ",
            cases_keyboard()
        )

    # BALANCE
    elif text == "/balance":

        send_message(
            message["chat"]["id"],
            (
                f"⭐ Твой баланс: "
                f"{get_balance(user_id)}"
            )
        )

    # INVENTORY
    elif text == "/inventory":

        items = get_inventory(
            user_id
        )

        if not items:

            send_message(
                message["chat"]["id"],
                "🎒 Инвентарь пуст."
            )

        else:

            output = (
                "🎒 ИНВЕНТАРЬ\n\n"
            )

            for i, item in enumerate(
                items,
                1
            ):
                output += (
                    f"{i}. {item[0]}\n"
                )

            send_message(
                message["chat"]["id"],
                output
            )

    # ADMIN
    elif text == "/admin":

        if user_id not in ADMIN_IDS:

            send_message(
                message["chat"]["id"],
                "❌ Нет доступа."
            )

            return

        send_message(
            message["chat"]["id"],
            "⚙️ АДМИН-ПАНЕЛЬ",
            admin_keyboard()
        )


# ============================================================
# GET UPDATES
# ============================================================

def get_updates(offset=None):

    data = {
        "timeout": 30
    }

    if offset is not None:
        data["offset"] = offset

    result = api(
        "getUpdates",
        data
    )

    if not result:
        return []

    return result.get(
        "result",
        []
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 50)
    print("CASE BOT STARTING")
    print("=" * 50)

    print(
        "API SERVER:",
        API_SERVER
    )

    print(
        "ADMIN IDS:",
        ADMIN_IDS
    )

    # ИНИЦИАЛИЗАЦИЯ БД
    init_db()

    print(
        "DATABASE: OK"
    )

    # ПРОВЕРКА БОТА
    me = api("getMe")

    if me and me.get("ok"):

        bot_username = (
            me["result"].get(
                "username",
                ""
            )
        )

        print(
            "BOT:",
            f"@{bot_username}"
        )

    else:

        print(
            "WARNING: getMe failed"
        )

    print(
        "BOT STARTED"
    )

    offset = None

    while True:

        try:

            updates = get_updates(
                offset
            )

            for update in updates:

                offset = (
                    update["update_id"] + 1
                )

                try:

                    handle_update(
                        update
                    )

                except Exception as e:

                    print(
                        "UPDATE ERROR:",
                        repr(e)
                    )

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "MAIN ERROR:",
                repr(e)
            )

            time.sleep(3)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()