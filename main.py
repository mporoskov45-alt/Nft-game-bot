import os
import random
import logging
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
import telebot
from telebot import types
import telebot.apihelper


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# API приватного Wavegram
API_URL = os.getenv(
    "API_URL",
    "http://31.76.20.193:8081/bot{0}/{1}"
).strip()

# ============================================================
# АДМИНИ
# ============================================================

ADMIN_IDS = {
    1780243378,
    1780243308,
    1780243345,
}

ADMIN_USERNAMES = {
    "doxme",
    "bogkm",
    "modeevil",
}


# ============================================================
# НАСТРОЙКИ КЕЙСОВ
# ============================================================

# Билитер
BILITER_PRICE = int(os.getenv("BILITER_PRICE", "100"))
BILITER_NORMAL_REWARD = int(
    os.getenv("BILITER_NORMAL_REWARD", "50")
)

# 0.01 = 1%
BILITER_GOLD_CHANCE = float(
    os.getenv("BILITER_GOLD_CHANCE", "0.01")
)

# Ириски риски
IRISKI_MIN_BET = int(
    os.getenv("IRISKI_MIN_BET", "1")
)

IRISKI_MAX_BET = int(
    os.getenv("IRISKI_MAX_BET", "1000000")
)

# 0.50 = 50%
IRISKI_WIN_CHANCE = float(
    os.getenv("IRISKI_WIN_CHANCE", "0.50")
)

IRISKI_MULTIPLIER = int(
    os.getenv("IRISKI_MULTIPLIER", "2")
)

# Лакшери
LUXURY_PRICE = int(
    os.getenv("LUXURY_PRICE", "2000")
)

# Пока список можно заменить на реальные GIFTS
# после получения API их ID.
LUXURY_GIFTS = [
    "Luxury Gift #1",
    "Luxury Gift #2",
    "Luxury Gift #3",
    "Luxury Gift #4",
    "Luxury Gift #5",
]

# Наркоман
NARKOMAN_PRICE = int(
    os.getenv("NARKOMAN_PRICE", "100")
)

NARKOMAN_REWARD = int(
    os.getenv("NARKOMAN_REWARD", "50")
)

# 0.01 = 1%
NARKOMAN_NFT_CHANCE = float(
    os.getenv("NARKOMAN_NFT_CHANCE", "0.01")
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# ПРОВЕРКА CONFIG
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан в Railway Variables"
    )

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL не задан в Railway Variables"
    )


# ============================================================
# TELEGRAM API
# ============================================================

telebot.apihelper.API_URL = API_URL

bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)


# ============================================================
# DATABASE
# ============================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,

    balance BIGINT NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS nft_inventory (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,

    nft_name TEXT NOT NULL,

    source_case TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    delivered_at TIMESTAMPTZ
);


CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,

    amount BIGINT NOT NULL,

    balance_after BIGINT NOT NULL,

    kind TEXT NOT NULL,

    description TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS case_opens (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL
        REFERENCES users(id)
        ON DELETE CASCADE,

    case_name TEXT NOT NULL,

    price BIGINT NOT NULL,

    result TEXT NOT NULL,

    reward_stars BIGINT NOT NULL DEFAULT 0,

    nft_inventory_id BIGINT
        REFERENCES nft_inventory(id)
        ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS pending_iriski (
    user_id BIGINT PRIMARY KEY,

    bet BIGINT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS idx_nft_user_status
ON nft_inventory(user_id, status);


CREATE INDEX IF NOT EXISTS idx_nft_pending
ON nft_inventory(status, created_at DESC);


CREATE INDEX IF NOT EXISTS idx_case_user
ON case_opens(user_id, created_at DESC);
"""


@contextmanager
def db():
    conn = psycopg2.connect(DATABASE_URL)

    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:

        with conn.cursor() as cur:
            cur.execute(SCHEMA)

        conn.commit()

    logging.info("Database initialized")


# ============================================================
# USERS
# ============================================================

def ensure_user(user):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO users(
                    id,
                    username,
                    first_name
                )
                VALUES (%s, %s, %s)

                ON CONFLICT(id)
                DO UPDATE SET
                    username=EXCLUDED.username,
                    first_name=EXCLUDED.first_name,
                    updated_at=NOW()
                """,
                (
                    user.id,
                    user.username,
                    user.first_name
                )
            )

        conn.commit()


def get_user(user_id):

    with db() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT *
                FROM users
                WHERE id=%s
                """,
                (user_id,)
            )

            return cur.fetchone()


def get_balance(user_id):

    row = get_user(user_id)

    if not row:
        return 0

    return int(row["balance"])


# ============================================================
# BALANCE
# ============================================================

def add_balance(
    user_id,
    amount,
    kind,
    description=""
):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT balance
                FROM users
                WHERE id=%s
                FOR UPDATE
                """,
                (user_id,)
            )

            row = cur.fetchone()

            if not row:
                raise ValueError(
                    "Пользователь не найден"
                )

            old_balance = int(row[0])

            new_balance = old_balance + amount

            if new_balance < 0:
                raise ValueError(
                    "Недостаточно звёзд"
                )

            cur.execute(
                """
                UPDATE users

                SET
                    balance=%s,
                    updated_at=NOW()

                WHERE id=%s
                """,
                (
                    new_balance,
                    user_id
                )
            )

            cur.execute(
                """
                INSERT INTO transactions(
                    user_id,
                    amount,
                    balance_after,
                    kind,
                    description
                )

                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    user_id,
                    amount,
                    new_balance,
                    kind,
                    description
                )
            )

        conn.commit()

        return new_balance


def charge_case(
    user_id,
    case_name,
    price
):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT balance

                FROM users

                WHERE id=%s

                FOR UPDATE
                """,
                (user_id,)
            )

            row = cur.fetchone()

            if not row:
                raise ValueError(
                    "Пользователь не найден"
                )

            balance = int(row[0])

            if balance < price:
                raise ValueError(
                    "Недостаточно звёзд"
                )

            new_balance = balance - price

            cur.execute(
                """
                UPDATE users

                SET
                    balance=%s,
                    updated_at=NOW()

                WHERE id=%s
                """,
                (
                    new_balance,
                    user_id
                )
            )

            cur.execute(
                """
                INSERT INTO transactions(
                    user_id,
                    amount,
                    balance_after,
                    kind,
                    description
                )

                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    user_id,
                    -price,
                    new_balance,
                    "case",
                    case_name
                )
            )

        conn.commit()

        return new_balance


# ============================================================
# CASE HISTORY
# ============================================================

def record_case(
    user_id,
    case_name,
    price,
    result,
    reward_stars=0,
    nft_inventory_id=None
):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO case_opens(
                    user_id,
                    case_name,
                    price,
                    result,
                    reward_stars,
                    nft_inventory_id
                )

                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    user_id,
                    case_name,
                    price,
                    result,
                    reward_stars,
                    nft_inventory_id
                )
            )

        conn.commit()


# ============================================================
# NFT
# ============================================================

def create_nft(
    user_id,
    nft_name,
    source_case
):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO nft_inventory(
                    user_id,
                    nft_name,
                    source_case
                )

                VALUES(
                    %s,
                    %s,
                    %s
                )

                RETURNING id
                """,
                (
                    user_id,
                    nft_name,
                    source_case
                )
            )

            nft_id = cur.fetchone()[0]

        conn.commit()

        return int(nft_id)


def get_inventory(user_id):

    with db() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    id,
                    nft_name,
                    source_case,
                    status,
                    created_at

                FROM nft_inventory

                WHERE
                    user_id=%s
                    AND status='pending'

                ORDER BY id DESC
                """,
                (user_id,)
            )

            return cur.fetchall()


def get_pending_nfts():

    with db() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT
                    n.id,
                    n.user_id,
                    n.nft_name,
                    n.source_case,
                    n.created_at,

                    u.username,
                    u.first_name

                FROM nft_inventory n

                JOIN users u
                ON u.id=n.user_id

                WHERE n.status='pending'

                ORDER BY n.id ASC
                """
            )

            return cur.fetchall()


def deliver_nft(nft_id):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE nft_inventory

                SET
                    status='delivered',
                    delivered_at=NOW()

                WHERE
                    id=%s
                    AND status='pending'

                RETURNING
                    user_id,
                    nft_name
                """,
                (nft_id,)
            )

            row = cur.fetchone()

        conn.commit()

        return row


# ============================================================
# STATISTICS
# ============================================================

def get_stats():

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                "SELECT COUNT(*) FROM users"
            )

            users = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COALESCE(
                    SUM(balance),
                    0
                )

                FROM users
                """
            )

            stars = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)

                FROM nft_inventory

                WHERE status='pending'
                """
            )

            pending = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM case_opens
                """
            )

            opens = cur.fetchone()[0]

            return (
                users,
                stars,
                pending,
                opens
            )


# ============================================================
# HELPERS
# ============================================================

def money(number):

    return f"{int(number):,}".replace(
        ",",
        " "
    )


def is_admin(user):

    if user.id in ADMIN_IDS:
        return True

    username = (
        user.username or ""
    ).lower().lstrip("@")

    return username in ADMIN_USERNAMES


def admin_list_text():

    return (
        "• @doxme\n"
        "• @bogkm\n"
        "• @modeevil"
    )


def user_display(user):

    if user.username:
        return f"@{user.username}"

    return (
        user.first_name
        or str(user.id)
    )


def user_label(row):

    if row.get("username"):
        return f"@{row['username']}"

    return (
        row.get("first_name")
        or str(row.get("id"))
    )


# ============================================================
# ADMIN NOTIFICATIONS
# ============================================================

def notify_admins(text):

    sent = 0

    for admin_id in ADMIN_IDS:

        try:

            bot.send_message(
                admin_id,
                text
            )

            sent += 1

        except Exception as error:

            logging.warning(
                "Не удалось отправить уведомление "
                "админу %s: %s",
                admin_id,
                error
            )

    return sent


# ============================================================
# KEYBOARDS
# ============================================================

def main_keyboard():

    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    keyboard.add(
        types.KeyboardButton(
            "🎁 Кейсы"
        ),
        types.KeyboardButton(
            "💰 Баланс"
        )
    )

    keyboard.add(
        types.KeyboardButton(
            "🎒 Инвентарь"
        ),
        types.KeyboardButton(
            "💳 Пополнить ⭐"
        )
    )

    keyboard.add(
        types.KeyboardButton(
            "ℹ️ Помощь"
        )
    )

    return keyboard


def cases_keyboard():

    keyboard = types.InlineKeyboardMarkup(
        row_width=1
    )

    keyboard.add(
        types.InlineKeyboardButton(
            f"🎟 Билитер — {BILITER_PRICE} ⭐",
            callback_data="case:biliter"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "🍬 Ириски риски",
            callback_data="case:iriski"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            f"💎 Лакшери — {LUXURY_PRICE} ⭐",
            callback_data="case:luxury"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            f"👁 Наркоман — {NARKOMAN_PRICE} ⭐",
            callback_data="case:narkoman"
        )
    )

    return keyboard


# ============================================================
# START
# ============================================================

@bot.message_handler(
    commands=["start"]
)
def start(message):

    ensure_user(
        message.from_user
    )

    bot.send_message(
        message.chat.id,

        "👋 <b>Добро пожаловать "
        "в Wavegram Cases!</b>\n\n"

        "Здесь ты можешь покупать "
        "игровые ⭐ и открывать кейсы.\n\n"

        "🎁 Кейсы\n"
        "💰 Баланс\n"
        "🎒 Инвентарь\n"
        "💳 Пополнение\n\n"

        "Удачи! 🍀",

        reply_markup=main_keyboard()
    )


# ============================================================
# ID
# ============================================================

@bot.message_handler(
    commands=["id"]
)
def show_id(message):

    ensure_user(
        message.from_user
    )

    bot.reply_to(
        message,

        f"🆔 Telegram ID: "
        f"<code>{message.from_user.id}</code>\n"

        f"👤 Username: "
        f"<code>@"
        f"{message.from_user.username or 'нет'}"
        f"</code>"
    )


# ============================================================
# BALANCE
# ============================================================

@bot.message_handler(
    func=lambda m: m.text == "💰 Баланс"
)
def balance(message):

    ensure_user(
        message.from_user
    )

    amount = get_balance(
        message.from_user.id
    )

    bot.send_message(
        message.chat.id,

        f"💰 <b>Твой баланс:</b>\n\n"
        f"⭐ <b>{money(amount)}</b>",

        reply_markup=main_keyboard()
    )


# ============================================================
# CASES
# ============================================================

@bot.message_handler(
    func=lambda m: m.text == "🎁 Кейсы"
)
def cases(message):

    ensure_user(
        message.from_user
    )

    bot.send_message(
        message.chat.id,

        "🎁 <b>Кейсы</b>\n\n"

        f"🎟 <b>Билитер</b>\n"
        f"Цена: {BILITER_PRICE} ⭐\n"
        f"Обычный билет: +{BILITER_NORMAL_REWARD} ⭐\n"
        "Редко выпадает 🏆 Золотой билет NFT.\n\n"

        "🍬 <b>Ириски риски</b>\n"
        "Сам выбираешь размер ставки.\n"
        f"При победе выплата x{IRISKI_MULTIPLIER}.\n\n"

        f"💎 <b>Лакшери</b>\n"
        f"Цена: {LUXURY_PRICE} ⭐\n"
        "Лучшие GIFTS сервера.\n\n"

        f"👁 <b>Наркоман</b>\n"
        f"Цена: {NARKOMAN_PRICE} ⭐\n"
        f"Награда: {NARKOMAN_REWARD} ⭐ "
        "или NFT «Глазик».",

        reply_markup=cases_keyboard()
    )


# ============================================================
# INVENTORY
# ============================================================

@bot.message_handler(
    func=lambda m: m.text == "🎒 Инвентарь"
)
def inventory(message):

    ensure_user(
        message.from_user
    )

    items = get_inventory(
        message.from_user.id
    )

    if not items:

        bot.send_message(
            message.chat.id,

            "🎒 <b>Инвентарь пуст.</b>",

            reply_markup=main_keyboard()
        )

        return

    text = (
        "🎒 <b>Твой инвентарь:</b>\n\n"
    )

    for item in items:

        text += (
            f"🆔 #{item['id']}\n"
            f"🎁 <b>{item['nft_name']}</b>\n"
            f"📦 Кейс: {item['source_case']}\n"
            "⏳ Статус: ожидает выдачи\n\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        reply_markup=main_keyboard()
    )


# ============================================================
# TOP UP
# ============================================================

@bot.message_handler(
    func=lambda m: m.text == "💳 Пополнить ⭐"
)
def topup(message):

    ensure_user(
        message.from_user
    )

    bot.send_message(
        message.chat.id,

        "💳 <b>Пополнение баланса</b>\n\n"

        "Для пополнения обратись к одному "
        "из администраторов:\n\n"

        f"{admin_list_text()}\n\n"

        "Обязательно отправь админу:\n"
        "• сумму\n"
        "• свой Telegram ID\n\n"

        "Получить ID можно командой "
        "<code>/id</code>.\n\n"

        "После проверки администратор "
        "зачислит ⭐ на баланс.",

        reply_markup=main_keyboard()
    )


# ============================================================
# HELP
# ============================================================

@bot.message_handler(
    func=lambda m: m.text == "ℹ️ Помощь"
)
def help_menu(message):

    ensure_user(
        message.from_user
    )

    bot.send_message(
        message.chat.id,

        "ℹ️ <b>Помощь</b>\n\n"

        "⭐ — игровая валюта.\n"
        "🎁 Кейсы — открытие кейсов.\n"
        "🎒 Инвентарь — полученные NFT.\n"
        "💳 Пополнить — инструкция.\n\n"

        "Если тебе выпал NFT, он появится "
        "в инвентаре со статусом "
        "«ожидает выдачи».\n\n"

        "После фактической выдачи администратор "
        "подтвердит его через админ-панель.",

        reply_markup=main_keyboard()
    )


# ============================================================
# БИЛИТЕР
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "case:biliter"
)
def open_biliter(call):

    ensure_user(
        call.from_user
    )

    try:

        charge_case(
            call.from_user.id,
            "Билитер",
            BILITER_PRICE
        )

    except ValueError:

        bot.answer_callback_query(
            call.id,
            "❌ Недостаточно ⭐",
            show_alert=True
        )

        return

    # ЗОЛОТОЙ БИЛЕТ

    if random.random() < BILITER_GOLD_CHANCE:

        nft_id = create_nft(
            call.from_user.id,
            "Золотой билет",
            "Билитер"
        )

        record_case(
            call.from_user.id,
            "Билитер",
            BILITER_PRICE,
            "Золотой билет NFT",
            0,
            nft_id
        )

        bot.answer_callback_query(
            call.id,
            "🏆 ЗОЛОТОЙ БИЛЕТ!",
            show_alert=True
        )

        bot.send_message(
            call.message.chat.id,

            "🎉 <b>НЕВЕРОЯТНО!</b>\n\n"

            "🏆 Тебе выпал "
            "<b>Золотой билет NFT!</b>\n\n"

            f"🆔 Inventory ID: "
            f"<code>#{nft_id}</code>\n\n"

            "NFT добавлен в инвентарь.\n"
            "Ожидай выдачу администратора."
        )

        notify_admins(

            "🚨 <b>ВЫПАЛ NFT!</b>\n\n"

            f"👤 Игрок: "
            f"<b>{user_display(call.from_user)}</b>\n"

            f"🆔 ID: "
            f"<code>{call.from_user.id}</code>\n\n"

            "🎁 Кейс: Билитер\n"
            "🏆 NFT: Золотой билет\n"

            f"🆔 Inventory ID: "
            f"<code>#{nft_id}</code>"
        )

        return

    # ОБЫЧНЫЙ БИЛЕТ

    reward = BILITER_NORMAL_REWARD

    add_balance(
        call.from_user.id,
        reward,
        "case_reward",
        "Билитер: обычный билет"
    )

    record_case(
        call.from_user.id,
        "Билитер",
        BILITER_PRICE,
        "Обычный билет",
        reward
    )

    bot.answer_callback_query(
        call.id,
        "🎟 Обычный билет!",
        show_alert=True
    )

    bot.send_message(
        call.message.chat.id,

        "🎟 <b>Выпал обычный билет!</b>\n\n"

        f"💰 Награда: "
        f"<b>+{reward} ⭐</b>\n\n"

        f"💰 Баланс: "
        f"<b>{money(get_balance(call.from_user.id))} ⭐</b>"
    )


# ============================================================
# ИРИСКИ РИСКИ
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "case:iriski"
)
def iriski_menu(call):

    ensure_user(
        call.from_user
    )

    bot.answer_callback_query(
        call.id
    )

    bot.send_message(
        call.message.chat.id,

        "🍬 <b>Ириски риски</b>\n\n"

        f"Минимум: "
        f"<b>{IRISKI_MIN_BET} ⭐</b>\n"

        f"Максимум: "
        f"<b>{money(IRISKI_MAX_BET)} ⭐</b>\n"

        f"Шанс победы: "
        f"<b>{IRISKI_WIN_CHANCE * 100:.2f}%</b>\n"

        f"Победа: "
        f"<b>x{IRISKI_MULTIPLIER}</b>\n\n"

        "Для игры напиши:\n"
        "<code>/risk 100</code>"
    )


@bot.message_handler(
    commands=["risk"]
)
def risk(message):

    ensure_user(
        message.from_user
    )

    parts = message.text.split()

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "❌ Использование:\n"
            "<code>/risk 100</code>"
        )

        return

    bet = int(parts[1])

    if (
        bet < IRISKI_MIN_BET
        or bet > IRISKI_MAX_BET
    ):

        bot.reply_to(
            message,

            f"❌ Ставка от "
            f"{IRISKI_MIN_BET} "
            f"до "
            f"{money(IRISKI_MAX_BET)} ⭐."
        )

        return

    if get_balance(
        message.from_user.id
    ) < bet:

        bot.reply_to(
            message,
            "❌ Недостаточно ⭐."
        )

        return

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO pending_iriski(
                    user_id,
                    bet
                )

                VALUES(
                    %s,
                    %s
                )

                ON CONFLICT(user_id)

                DO UPDATE SET
                    bet=EXCLUDED.bet,
                    created_at=NOW()
                """,
                (
                    message.from_user.id,
                    bet
                )
            )

        conn.commit()

    keyboard = types.InlineKeyboardMarkup(
        row_width=2
    )

    keyboard.add(

        types.InlineKeyboardButton(
            "🍬 ИРИСКА",
            callback_data=(
                f"risk:play:"
                f"{message.from_user.id}"
            )
        ),

        types.InlineKeyboardButton(
            "💀 РИСК",
            callback_data=(
                f"risk:play:"
                f"{message.from_user.id}"
            )
        )
    )

    bot.send_message(
        message.chat.id,

        f"🎲 Ставка: "
        f"<b>{money(bet)} ⭐</b>\n\n"

        "Нажми кнопку и узнай результат:",

        reply_markup=keyboard
    )


@bot.callback_query_handler(
    func=lambda call:
        call.data.startswith(
            "risk:play:"
        )
)
def risk_play(call):

    ensure_user(
        call.from_user
    )

    try:

        target_id = int(
            call.data.split(":")[2]
        )

    except Exception:

        bot.answer_callback_query(
            call.id,
            "Ошибка ставки",
            show_alert=True
        )

        return

    if target_id != call.from_user.id:

        bot.answer_callback_query(
            call.id,
            "Это не твоя ставка.",
            show_alert=True
        )

        return

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT bet

                FROM pending_iriski

                WHERE user_id=%s

                FOR UPDATE
                """,
                (target_id,)
            )

            row = cur.fetchone()

            if not row:

                bot.answer_callback_query(
                    call.id,
                    "Ставка уже сыграна.",
                    show_alert=True
                )

                return

            bet = int(row[0])

            cur.execute(
                """
                DELETE FROM pending_iriski

                WHERE user_id=%s
                """,
                (target_id,)
            )

        conn.commit()

    try:

        charge_case(
            target_id,
            "Ириски риски",
            bet
        )

    except ValueError:

        bot.answer_callback_query(
            call.id,
            "Недостаточно ⭐",
            show_alert=True
        )

        return

    win = (
        random.random()
        < IRISKI_WIN_CHANCE
    )

    if win:

        reward = (
            bet
            * IRISKI_MULTIPLIER
        )

        add_balance(
            target_id,
            reward,
            "risk_reward",
            "Ириски риски: победа"
        )

        record_case(
            target_id,
            "Ириски риски",
            bet,
            "Победа",
            reward
        )

        bot.answer_callback_query(
            call.id,
            "🍬 ИРИСКА! ПОБЕДА!",
            show_alert=True
        )

        bot.send_message(
            call.message.chat.id,

            "🍬 <b>ИРИСКА!</b>\n\n"

            f"🎲 Ставка: "
            f"{money(bet)} ⭐\n"

            f"💰 Выигрыш: "
            f"<b>+{money(reward)} ⭐</b>\n\n"

            f"💰 Баланс: "
            f"<b>{money(get_balance(target_id))} ⭐</b>"
        )

    else:

        record_case(
            target_id,
            "Ириски риски",
            bet,
            "Проигрыш",
            0
        )

        bot.answer_callback_query(
            call.id,
            "💀 ПРОИГРЫШ!",
            show_alert=True
        )

        bot.send_message(
            call.message.chat.id,

            "💀 <b>ПРОИГРАННЫЙ РИСК</b>\n\n"

            f"Потеряно: "
            f"<b>{money(bet)} ⭐</b>\n\n"

            f"Баланс: "
            f"<b>{money(get_balance(target_id))} ⭐</b>"
        )


# ============================================================
# ЛАКШЕРИ
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "case:luxury"
)
def open_luxury(call):

    ensure_user(
        call.from_user
    )

    try:

        charge_case(
            call.from_user.id,
            "Лакшери",
            LUXURY_PRICE
        )

    except ValueError:

        bot.answer_callback_query(
            call.id,
            "❌ Недостаточно ⭐",
            show_alert=True
        )

        return

    gift = random.choice(
        LUXURY_GIFTS
    )

    nft_id = create_nft(
        call.from_user.id,
        gift,
        "Лакшери"
    )

    record_case(
        call.from_user.id,
        "Лакшери",
        LUXURY_PRICE,
        gift,
        0,
        nft_id
    )

    bot.answer_callback_query(
        call.id,
        "💎 LUXURY!",
        show_alert=True
    )

    bot.send_message(
        call.message.chat.id,

        "💎 <b>ЛАКШЕРИ!</b>\n\n"

        f"🎁 Выпал: "
        f"<b>{gift}</b>\n\n"

        f"🆔 Inventory ID: "
        f"<code>#{nft_id}</code>\n\n"

        "Предмет добавлен в инвентарь.\n"
        "Ожидай выдачу администратора."
    )

    notify_admins(

        "🚨 <b>ВЫПАЛ LUXURY NFT!</b>\n\n"

        f"👤 Игрок: "
        f"<b>{user_display(call.from_user)}</b>\n"

        f"🆔 ID: "
        f"<code>{call.from_user.id}</code>\n\n"

        f"🎁 Gift: <b>{gift}</b>\n"

        f"🆔 Inventory ID: "
        f"<code>{nft_id}</code>"
    )


# ============================================================
# НАРКОМАН
# ============================================================

@bot.callback_query_handler(
    func=lambda call:
        call.data == "case:narkoman"
)
def open_narkoman(call):

    ensure_user(
        call.from_user
    )

    try:

        charge_case(
            call.from_user.id,
            "Наркоман",
            NARKOMAN_PRICE
        )

    except ValueError:

        bot.answer_callback_query(
            call.id,
            "❌ Недостаточно ⭐",
            show_alert=True
        )

        return

    # ГЛАЗИК

    if random.random() < NARKOMAN_NFT_CHANCE:

        nft_id = create_nft(
            call.from_user.id,
            "Глазик",
            "Наркоман"
        )

        record_case(
            call.from_user.id,
            "Наркоман",
            NARKOMAN_PRICE,
            "Глазик NFT",
            0,
            nft_id
        )

        bot.answer_callback_query(
            call.id,
            "👁 ГЛАЗИК!",
            show_alert=True
        )

        bot.send_message(
            call.message.chat.id,

            "👁 <b>ТЕБЕ ВЫПАЛ ГЛАЗИК!</b>\n\n"

            f"🆔 Inventory ID: "
            f"<code>#{nft_id}</code>\n\n"

            "NFT добавлен в инвентарь.\n"
            "Ожидай выдачу администратора."
        )

        notify_admins(

            "🚨 <b>ВЫПАЛ NFT!</b>\n\n"

            f"👤 Игрок: "
            f"<b>{user_display(call.from_user)}</b>\n"

            f"🆔 ID: "
            f"<code>{call.from_user.id}</code>\n\n"

            "🎁 Кейс: Наркоман\n"
            "👁 NFT: Глазик\n"

            f"🆔 Inventory ID: "
            f"<code>{nft_id}</code>"
        )

        return

    # ЗВЁЗДЫ

    reward = NARKOMAN_REWARD

    add_balance(
        call.from_user.id,
        reward,
        "case_reward",
        "Наркоман: звёзды"
    )

    record_case(
        call.from_user.id,
        "Наркоман",
        NARKOMAN_PRICE,
        "Звёзды",
        reward
    )

    bot.answer_callback_query(
        call.id,
        f"+{reward} ⭐",
        show_alert=True
    )

    bot.send_message(
        call.message.chat.id,

        f"💰 Выпало "
        f"<b>+{reward} ⭐</b>!\n\n"

        f"Баланс: "
        f"<b>{money(get_balance(call.from_user.id))} ⭐</b>"
    )


# ============================================================
# ADMIN PANEL
# ============================================================

@bot.message_handler(
    commands=["admin"]
)
def admin_panel(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ У тебя нет доступа."
        )

        return

    bot.send_message(
        message.chat.id,

        "🛠 <b>Админ-панель</b>\n\n"

        "💰 <code>/give ID СУММА</code>\n"
        "Сделать игроку начисление ⭐.\n\n"

        "💸 <code>/take ID СУММА</code>\n"
        "Снять ⭐.\n\n"

        "👤 <code>/user ID</code>\n"
        "Информация об игроке.\n\n"

        "🎒 <code>/nft_pending</code>\n"
        "NFT, ожидающие выдачи.\n\n"

        "✅ <code>/nft_done ID</code>\n"
        "Подтвердить выдачу NFT.\n\n"

        "📊 <code>/stats</code>\n"
        "Статистика.\n\n"

        "📢 <code>/broadcast ТЕКСТ</code>\n"
        "Рассылка игрокам."
    )


# ============================================================
# GIVE
# ============================================================

@bot.message_handler(
    commands=["give"]
)
def admin_give(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "Использование:\n"
            "<code>/give 123456789 500</code>"
        )

        return

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

        if amount <= 0:
            raise ValueError

    except ValueError:

        bot.reply_to(
            message,
            "❌ Неверный ID или сумма."
        )

        return

    if not get_user(user_id):

        bot.reply_to(
            message,
            "❌ Игрок не найден.\n"
            "Он должен сначала нажать /start."
        )

        return

    new_balance = add_balance(
        user_id,
        amount,
        "admin_give",
        f"Админ {message.from_user.id}"
    )

    bot.reply_to(
        message,

        f"✅ Игроку начислено "
        f"<b>+{money(amount)} ⭐</b>\n\n"

        f"Новый баланс: "
        f"<b>{money(new_balance)} ⭐</b>"
    )

    try:

        bot.send_message(
            user_id,

            "💰 <b>Пополнение</b>\n\n"

            f"Тебе начислено "
            f"<b>+{money(amount)} ⭐</b>\n\n"

            f"Баланс: "
            f"<b>{money(new_balance)} ⭐</b>"
        )

    except Exception:
        pass


# ============================================================
# TAKE
# ============================================================

@bot.message_handler(
    commands=["take"]
)
def admin_take(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    parts = message.text.split()

    if len(parts) != 3:

        bot.reply_to(
            message,
            "Использование:\n"
            "<code>/take 123456789 500</code>"
        )

        return

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

        if amount <= 0:
            raise ValueError

    except ValueError:

        bot.reply_to(
            message,
            "❌ Неверный ID или сумма."
        )

        return

    try:

        new_balance = add_balance(
            user_id,
            -amount,
            "admin_take",
            f"Админ {message.from_user.id}"
        )

    except ValueError:

        bot.reply_to(
            message,
            "❌ Недостаточно ⭐."
        )

        return

    bot.reply_to(
        message,

        f"✅ Списано "
        f"<b>{money(amount)} ⭐</b>\n\n"

        f"Баланс: "
        f"<b>{money(new_balance)} ⭐</b>"
    )

    try:

        bot.send_message(
            user_id,

            "⚠️ <b>Списание</b>\n\n"

            f"Списано: "
            f"<b>{money(amount)} ⭐</b>\n\n"

            f"Баланс: "
            f"<b>{money(new_balance)} ⭐</b>"
        )

    except Exception:
        pass


# ============================================================
# USER INFO
# ============================================================

@bot.message_handler(
    commands=["user"]
)
def admin_user(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    parts = message.text.split()

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,
            "Использование:\n"
            "<code>/user ID</code>"
        )

        return

    user_id = int(parts[1])

    row = get_user(user_id)

    if not row:

        bot.reply_to(
            message,
            "❌ Игрок не найден."
        )

        return

    items = get_inventory(
        user_id
    )

    bot.reply_to(
        message,

        "👤 <b>Игрок</b>\n\n"

        f"🆔 ID: "
        f"<code>{row['id']}</code>\n"

        f"👤 Username: "
        f"@{row['username'] or 'нет'}\n"

        f"📛 Имя: "
        f"{row['first_name'] or 'нет'}\n\n"

        f"💰 Баланс: "
        f"<b>{money(row['balance'])} ⭐</b>\n"

        f"🎒 NFT ожидают выдачи: "
        f"<b>{len(items)}</b>"
    )


# ============================================================
# PENDING NFT
# ============================================================

@bot.message_handler(
    commands=["nft_pending"]
)
def nft_pending(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    rows = get_pending_nfts()

    if not rows:

        bot.reply_to(
            message,
            "✅ NFT, ожидающих выдачи, нет."
        )

        return

    text = (
        "🎒 <b>NFT ожидают выдачи:</b>\n\n"
    )

    for row in rows:

        text += (
            f"🆔 <code>#{row['id']}</code>\n"

            f"👤 Игрок: "
            f"{user_label(row)}\n"

            f"🆔 User ID: "
            f"<code>{row['user_id']}</code>\n"

            f"🎁 NFT: "
            f"<b>{row['nft_name']}</b>\n"

            f"📦 Кейс: "
            f"{row['source_case']}\n\n"

            f"Для подтверждения:\n"
            f"<code>/nft_done {row['id']}</code>\n"

            "━━━━━━━━━━━━\n"
        )

    bot.send_message(
        message.chat.id,
        text
    )


# ============================================================
# NFT DONE
# ============================================================

@bot.message_handler(
    commands=["nft_done"]
)
def nft_done(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    parts = message.text.split()

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "Использование:\n"
            "<code>/nft_done ID</code>"
        )

        return

    nft_id = int(parts[1])

    row = deliver_nft(
        nft_id
    )

    if not row:

        bot.reply_to(
            message,

            "❌ NFT не найден "
            "или уже выдан."
        )

        return

    user_id, nft_name = row

    bot.reply_to(
        message,

        "✅ <b>NFT отмечен как выданный.</b>\n\n"

        f"🎁 {nft_name}\n"
        f"🆔 #{nft_id}"
    )

    try:

        bot.send_message(
            user_id,

            "🎉 <b>NFT выдан!</b>\n\n"

            f"🎁 Предмет: "
            f"<b>{nft_name}</b>\n"

            f"🆔 Inventory ID: "
            f"<code>#{nft_id}</code>\n\n"

            "Администратор подтвердил "
            "фактическую выдачу NFT."
        )

    except Exception:
        pass


# ============================================================
# STATS
# ============================================================

@bot.message_handler(
    commands=["stats"]
)
def stats(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    users, stars, pending, opens = get_stats()

    bot.reply_to(
        message,

        "📊 <b>Статистика</b>\n\n"

        f"👥 Игроков: "
        f"<b>{users}</b>\n"

        f"⭐ Всего на балансах: "
        f"<b>{money(stars)}</b>\n"

        f"🎒 NFT ожидают выдачи: "
        f"<b>{pending}</b>\n"

        f"🎁 Всего открытий: "
        f"<b>{opens}</b>"
    )


# ============================================================
# BROADCAST
# ============================================================

@bot.message_handler(
    commands=["broadcast"]
)
def broadcast(message):

    if not is_admin(
        message.from_user
    ):

        bot.reply_to(
            message,
            "⛔ Нет доступа."
        )

        return

    text = message.text.partition(
        " "
    )[2].strip()

    if not text:

        bot.reply_to(
            message,

            "Использование:\n"
            "<code>/broadcast Ваш текст</code>"
        )

        return

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT id
                FROM users
                """
            )

            user_ids = [
                row[0]
                for row in cur.fetchall()
            ]

    sent = 0
    failed = 0

    for user_id in user_ids:

        try:

            bot.send_message(
                user_id,
                text
            )

            sent += 1

        except Exception:

            failed += 1

    bot.reply_to(
        message,

        "📢 <b>Рассылка завершена.</b>\n\n"

        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}"
    )


# ============================================================
# FALLBACK
# ============================================================

@bot.message_handler(
    func=lambda message: True
)
def fallback(message):

    ensure_user(
        message.from_user
    )

    bot.send_message(
        message.chat.id,

        "Используй кнопки меню 👇",

        reply_markup=main_keyboard()
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    init_db()

    logging.info(
        "================================="
    )

    logging.info(
        "Wavegram Cases Bot started"
    )

    logging.info(
        "API: %s",
        API_URL
    )

    logging.info(
        "Admins: %s",
        sorted(ADMIN_IDS)
    )

    logging.info(
        "================================="
    )

    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30,
        allowed_updates=[
            "message",
            "callback_query"
        ]
    )
