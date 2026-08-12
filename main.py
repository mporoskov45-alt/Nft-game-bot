import asyncio
import logging
import os
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

API_HOST = os.getenv(
    "API_HOST",
    "http://31.76.20.193:8081",
).strip()


# Цены кейсов
BILETER_PRICE = 100
LUXURY_PRICE = 2000

# Укажи цену Наркомана через Railway Variables:
# NARKOMAN_PRICE=100
NARKOMAN_PRICE = int(
    os.getenv("NARKOMAN_PRICE", "100")
)


# ============================================================
# АДМИНЫ
# ============================================================

ADMIN_IDS = {
    1780243345,
    1780243308,
    1780243378,
}


# ============================================================
# ПРОВЕРКА НАСТРОЕК
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN"
    )

if not DATABASE_URL:
    raise RuntimeError(
        "Не задан DATABASE_URL"
    )


# Railway иногда отдаёт postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+asyncpg://",
        1,
    )

elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+asyncpg://",
        1,
    )


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
)


# ============================================================
# DATABASE
# ============================================================

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# ============================================================
# USER
# ============================================================

class User(Base):

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    first_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    balance: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ============================================================
# CASE OPEN
# ============================================================

class CaseOpen(Base):

    __tablename__ = "case_opens"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )

    case_name: Mapped[str] = mapped_column(
        String(100)
    )

    price: Mapped[int] = mapped_column(
        Integer
    )

    selected_color: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    winning_color: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    reward_name: Mapped[str] = mapped_column(
        String(255)
    )

    reward_type: Mapped[str] = mapped_column(
        String(50)
    )

    reward_value: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


# ============================================================
# INVENTORY
# ============================================================

class InventoryItem(Base):

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )

    item_name: Mapped[str] = mapped_column(
        String(255)
    )

    item_type: Mapped[str] = mapped_column(
        String(50)
    )

    source_case: Mapped[str] = mapped_column(
        String(100)
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
    )

    admin_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


# ============================================================
# BALANCE LOG
# ============================================================

class BalanceLog(Base):

    __tablename__ = "balance_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )

    admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    amount: Mapped[int] = mapped_column(
        BigInteger
    )

    balance_after: Mapped[int] = mapped_column(
        BigInteger
    )

    operation: Mapped[str] = mapped_column(
        String(30)
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


# ============================================================
# НАГРАДЫ
# ============================================================

# Вес = вероятность.
# Никаких гарантированных наград нет.

BILETER_REWARDS = [
    (
        "Обычный билет",
        "balance",
        980,
        50,
    ),
    (
        "Золотой билет",
        "nft",
        20,
        0,
    ),
]


LUXURY_REWARDS = [
    (
        "Wavegram Gift #1",
        "gift",
        350,
        0,
    ),
    (
        "Wavegram Gift #2",
        "gift",
        250,
        0,
    ),
    (
        "Wavegram Gift #3",
        "gift",
        180,
        0,
    ),
    (
        "Редкий Wavegram Gift",
        "gift",
        150,
        0,
    ),
    (
        "Очень редкий Wavegram Gift",
        "gift",
        70,
        0,
    ),
]


NARKOMAN_REWARDS = [
    (
        "50 игровых ⭐",
        "balance",
        970,
        50,
    ),
    (
        "NFT Глазик",
        "nft",
        30,
        0,
    ),
]


def choose_reward(rewards):

    return random.choices(
        rewards,
        weights=[
            reward[2]
            for reward in rewards
        ],
        k=1,
    )[0]


# ============================================================
# TELEGRAM API
# ============================================================

telegram_api = TelegramAPIServer.from_base(
    API_HOST
)

telegram_session = AiohttpSession(
    api=telegram_api
)

bot = Bot(
    token=BOT_TOKEN,
    session=telegram_session,
)

dp = Dispatcher()


# ============================================================
# DATABASE MIGRATION
# ============================================================

async def migrate_database():

    """
    Исправляет старую таблицу users.

    Основная проблема из логов:
    users существует, но users.id отсутствует.

    Эта функция:
    - проверяет users;
    - переименовывает user_id/telegram_id в id;
    - либо создаёт id;
    - добавляет отсутствующие колонки;
    - создаёт остальные таблицы.
    """

    async with engine.begin() as conn:

        # --------------------------------------------------------
        # Список таблиц
        # --------------------------------------------------------

        result = await conn.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
        )

        tables = {
            row[0]
            for row in result.fetchall()
        }

        # --------------------------------------------------------
        # USERS
        # --------------------------------------------------------

        if "users" in tables:

            result = await conn.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'users'
                """)
            )

            columns = {
                row[0]
                for row in result.fetchall()
            }

            logging.info(
                "Существующие колонки users: %s",
                sorted(columns),
            )

            # ----------------------------------------------------
            # user_id -> id
            # ----------------------------------------------------

            if (
                "id" not in columns
                and "user_id" in columns
            ):

                logging.warning(
                    "Миграция users.user_id -> users.id"
                )

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        RENAME COLUMN user_id TO id
                    """)
                )

                columns.remove("user_id")
                columns.add("id")

            # ----------------------------------------------------
            # telegram_id -> id
            # ----------------------------------------------------

            elif (
                "id" not in columns
                and "telegram_id" in columns
            ):

                logging.warning(
                    "Миграция users.telegram_id -> users.id"
                )

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        RENAME COLUMN telegram_id TO id
                    """)
                )

                columns.remove("telegram_id")
                columns.add("id")

            # ----------------------------------------------------
            # Если вообще нет ID
            # ----------------------------------------------------

            elif "id" not in columns:

                logging.warning(
                    "В users отсутствует ID."
                )

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ADD COLUMN id BIGINT
                    """)
                )

                # Получаем существующие строки
                result = await conn.execute(
                    text("""
                        SELECT ctid
                        FROM users
                        WHERE id IS NULL
                    """)
                )

                rows = result.fetchall()

                next_id = 1

                for row in rows:

                    await conn.execute(
                        text("""
                            UPDATE users
                            SET id = :id
                            WHERE ctid = :ctid
                        """),
                        {
                            "id": next_id,
                            "ctid": row[0],
                        },
                    )

                    next_id += 1

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ALTER COLUMN id SET NOT NULL
                    """)
                )

                # Проверяем primary key
                result = await conn.execute(
                    text("""
                        SELECT constraint_name
                        FROM information_schema.table_constraints
                        WHERE table_schema = 'public'
                          AND table_name = 'users'
                          AND constraint_type = 'PRIMARY KEY'
                    """)
                )

                has_pk = (
                    result.first()
                    is not None
                )

                if not has_pk:

                    await conn.execute(
                        text("""
                            ALTER TABLE users
                            ADD PRIMARY KEY (id)
                        """)
                    )

            # ----------------------------------------------------
            # Остальные колонки
            # ----------------------------------------------------

            if "username" not in columns:

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ADD COLUMN username VARCHAR(255)
                    """)
                )

            if "first_name" not in columns:

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ADD COLUMN first_name VARCHAR(255)
                    """)
                )

            if "balance" not in columns:

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ADD COLUMN balance BIGINT
                        NOT NULL DEFAULT 0
                    """)
                )

            if "is_admin" not in columns:

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ADD COLUMN is_admin BOOLEAN
                        NOT NULL DEFAULT FALSE
                    """)
                )

            if "created_at" not in columns:

                await conn.execute(
                    text("""
                        ALTER TABLE users
                        ADD COLUMN created_at TIMESTAMP
                        NOT NULL DEFAULT CURRENT_TIMESTAMP
                    """)
                )

        # --------------------------------------------------------
        # Остальные таблицы
        # --------------------------------------------------------

        await conn.run_sync(
            Base.metadata.create_all
        )

    logging.info(
        "PostgreSQL migration: OK"
    )


async def init_database():

    for attempt in range(15):

        try:

            await migrate_database()

            # ----------------------------------------------------
            # Проверяем администраторов
            # ----------------------------------------------------

            async with SessionLocal() as db:

                for admin_id in ADMIN_IDS:

                    result = await db.execute(
                        select(User).where(
                            User.id == admin_id
                        )
                    )

                    user = (
                        result.scalar_one_or_none()
                    )

                    if user:

                        user.is_admin = True

                await db.commit()

            logging.info(
                "Администраторы проверены."
            )

            return True

        except Exception as error:

            logging.exception(
                "Ошибка PostgreSQL: %s",
                error,
            )

            if attempt == 14:

                return False

            await asyncio.sleep(3)

    return False


# ============================================================
# USER
# ============================================================

async def get_or_create_user(
    db: AsyncSession,
    telegram_user,
):

    result = await db.execute(
        select(User).where(
            User.id == telegram_user.id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:

        user = User(
            id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            balance=0,
            is_admin=(
                telegram_user.id
                in ADMIN_IDS
            ),
        )

        db.add(user)

    else:

        user.username = (
            telegram_user.username
        )

        user.first_name = (
            telegram_user.first_name
        )

        if telegram_user.id in ADMIN_IDS:

            user.is_admin = True

    await db.commit()

    await db.refresh(user)

    return user


# ============================================================
# MENUS
# ============================================================

def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎁 Кейсы",
                    callback_data="cases",
                ),
                InlineKeyboardButton(
                    text="👤 Профиль",
                    callback_data="profile",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Пополнение",
                    callback_data="deposit",
                ),
                InlineKeyboardButton(
                    text="📦 Инвентарь",
                    callback_data="inventory",
                ),
            ],
        ]
    )


def cases_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        f"🎫 Билитер "
                        f"— {BILETER_PRICE} ⭐"
                    ),
                    callback_data="case:bileter",
                )
            ],
            [
                InlineKeyboardButton(
                    text=(
                        f"💎 Лакшери "
                        f"— {LUXURY_PRICE} ⭐"
                    ),
                    callback_data="case:luxury",
                )
            ],
            [
                InlineKeyboardButton(
                    text=(
                        f"💊 Наркоман "
                        f"— {NARKOMAN_PRICE} ⭐"
                    ),
                    callback_data="case:narkoman",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔴🔵🟡 Красный / Синий / Жёлтый",
                    callback_data="case:color",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="home",
                )
            ],
        ]
    )


def back_menu(
    callback="home"
):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=callback,
                )
            ]
        ]
    )


# ============================================================
# ADMIN NOTIFICATIONS
# ============================================================

async def notify_admins(
    message_text
):

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_message(
                chat_id=admin_id,
                text=message_text,
            )

        except Exception as error:

            logging.error(
                "Ошибка отправки админу %s: %s",
                admin_id,
                error,
            )


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start_command(
    message: Message
):

    logging.info(
        "Получен /start от %s",
        message.from_user.id,
    )

    try:

        async with SessionLocal() as db:

            await get_or_create_user(
                db,
                message.from_user,
            )

        await message.answer(
            "🎮 <b>Кейс-бот</b>\n\n"
            "⭐ Здесь используются "
            "внутренние игровые звёзды.\n\n"
            "Они не являются настоящими "
            "Telegram Stars.\n\n"
            "Выбери действие:",
            reply_markup=main_menu(),
            parse_mode=ParseMode.HTML,
        )

    except Exception as error:

        logging.exception(
            "Ошибка /start: %s",
            error,
        )

        await message.answer(
            "⚠️ Произошла ошибка.\n\n"
            "Попробуй ещё раз через несколько секунд."
        )


# ============================================================
# HOME
# ============================================================

@dp.callback_query(
    F.data == "home"
)
async def home(
    callback: CallbackQuery
):

    await callback.message.edit_text(
        "🎮 <b>Главное меню</b>",
        reply_markup=main_menu(),
    )

    await callback.answer()


# ============================================================
# PROFILE
# ============================================================

@dp.callback_query(
    F.data == "profile"
)
async def profile(
    callback: CallbackQuery
):

    async with SessionLocal() as db:

        user = await get_or_create_user(
            db,
            callback.from_user,
        )

    username = (
        "@" + user.username
        if user.username
        else "не указан"
    )

    await callback.message.edit_text(
        "👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Username: {username}\n"
        f"⭐ Баланс: <b>{user.balance}</b>",
        reply_markup=main_menu(),
    )

    await callback.answer()


# ============================================================
# CASES
# ============================================================

@dp.callback_query(
    F.data == "cases"
)
async def cases(
    callback: CallbackQuery
):

    await callback.message.edit_text(
        "🎁 <b>Кейсы</b>\n\n"
        "Награда определяется случайно.\n"
        "❗ Гарантированных наград нет.",
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# DEPOSIT
# ============================================================

@dp.callback_query(
    F.data == "deposit"
)
async def deposit(
    callback: CallbackQuery
):

    await callback.message.edit_text(
        "💰 <b>Пополнение</b>\n\n"
        "Валюту для кейсов можно приобрести "
        "за настоящие Telegram Stars у:\n\n"
        "• @doxme\n"
        "• @modeevil\n"
        "• @bogkm\n\n"
        "После покупки игровые ⭐ выдаются "
        "администратором.\n\n"
        "⚠️ ⭐ внутри бота — игровая валюта "
        "и не являются настоящими Telegram Stars.",
        reply_markup=back_menu(),
    )

    await callback.answer()


# ============================================================
# INVENTORY
# ============================================================

@dp.callback_query(
    F.data == "inventory"
)
async def inventory(
    callback: CallbackQuery
):

    async with SessionLocal() as db:

        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.user_id
                == callback.from_user.id
            )
            .order_by(
                InventoryItem.id.desc()
            )
            .limit(50)
        )

        items = result.scalars().all()

    if not items:

        await callback.message.edit_text(
            "📦 <b>Инвентарь пуст.</b>",
            reply_markup=back_menu(),
        )

        await callback.answer()

        return

    lines = [
        "📦 <b>Инвентарь</b>\n"
    ]

    for item in items:

        if item.status == "pending":

            status = "⏳ Ожидает выдачи"

        elif item.status == "issued":

            status = "✅ Выдано"

        else:

            status = item.status

        lines.append(
            f"#{item.id} — "
            f"{item.item_name}\n"
            f"Статус: {status}"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_menu(),
    )

    await callback.answer()


# ============================================================
# ADD INVENTORY
# ============================================================

async def add_inventory(
    db,
    user_id,
    item_name,
    item_type,
    source_case,
):

    db.add(
        InventoryItem(
            user_id=user_id,
            item_name=item_name,
            item_type=item_type,
            source_case=source_case,
            status="pending",
        )
    )


# ============================================================
# CHARGE BALANCE
# ============================================================

async def charge_balance(
    db,
    user_id,
    amount,
):

    result = await db.execute(
        select(User)
        .where(
            User.id == user_id
        )
        .with_for_update()
    )

    user = result.scalar_one()

    if user.balance < amount:

        return None

    user.balance -= amount

    return user


# ============================================================
# OPEN CASE
# ============================================================

async def open_case(
    callback,
    case_name,
    price,
    rewards,
):

    async with SessionLocal() as db:

        user = await charge_balance(
            db,
            callback.from_user.id,
            price,
        )

        if user is None:

            await db.rollback()

            await callback.answer(
                "❌ Недостаточно ⭐",
                show_alert=True,
            )

            return None

        reward = choose_reward(
            rewards
        )

        reward_name = reward[0]
        reward_type = reward[1]
        reward_value = reward[3]

        # ----------------------------------------------------
        # Денежная игровая награда
        # ----------------------------------------------------

        if reward_type == "balance":

            user.balance += reward_value

        # ----------------------------------------------------
        # NFT / Gift / редкий предмет
        # ----------------------------------------------------

        elif reward_type in {
            "nft",
            "gift",
        }:

            await add_inventory(
                db,
                user.id,
                reward_name,
                reward_type,
                case_name,
            )

        # ----------------------------------------------------
        # История открытия
        # ----------------------------------------------------

        db.add(
            CaseOpen(
                user_id=user.id,
                case_name=case_name,
                price=price,
                reward_name=reward_name,
                reward_type=reward_type,
                reward_value=reward_value,
            )
        )

        await db.commit()

        return (
            reward_name,
            reward_type,
            reward_value,
            user.balance,
        )


# ============================================================
# BILETER
# ============================================================

@dp.callback_query(
    F.data == "case:bileter"
)
async def bileter(
    callback: CallbackQuery
):

    result = await open_case(
        callback,
        "Билитер",
        BILETER_PRICE,
        BILETER_REWARDS,
    )

    if result is None:
        return

    (
        reward_name,
        reward_type,
        reward_value,
        balance,
    ) = result

    if reward_type == "balance":

        text_result = (
            "🎫 <b>Билитер открыт!</b>\n\n"
            f"🎁 {reward_name}\n"
            f"⭐ +{reward_value}\n\n"
            f"Баланс: <b>{balance} ⭐</b>"
        )

    else:

        text_result = (
            "🎫 <b>Билитер открыт!</b>\n\n"
            f"✨ <b>{reward_name}</b>\n\n"
            "Предмет добавлен в инвентарь."
        )

        await notify_admins(
            "🚨 <b>Редкая награда!</b>\n\n"
            f"ID: <code>"
            f"{callback.from_user.id}"
            f"</code>\n"
            f"Username: "
            f"@{callback.from_user.username or 'нет'}\n"
            "Кейс: Билитер\n"
            f"Награда: <b>{reward_name}</b>"
        )

    await callback.message.edit_text(
        text_result,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# LUXURY
# ============================================================

@dp.callback_query(
    F.data == "case:luxury"
)
async def luxury(
    callback: CallbackQuery
):

    result = await open_case(
        callback,
        "Лакшери",
        LUXURY_PRICE,
        LUXURY_REWARDS,
    )

    if result is None:
        return

    (
        reward_name,
        reward_type,
        reward_value,
        balance,
    ) = result

    await callback.message.edit_text(
        "💎 <b>Лакшери открыт!</b>\n\n"
        f"🎁 <b>{reward_name}</b>\n\n"
        "Предмет добавлен в инвентарь.",
        reply_markup=cases_menu(),
    )

    await notify_admins(
        "💎 <b>Выпала награда из Лакшери</b>\n\n"
        f"ID: <code>"
        f"{callback.from_user.id}"
        f"</code>\n"
        f"Username: "
        f"@{callback.from_user.username or 'нет'}\n"
        f"Награда: <b>{reward_name}</b>"
    )

    await callback.answer()


# ============================================================
# NARKOMAN
# ============================================================

@dp.callback_query(
    F.data == "case:narkoman"
)
async def narkoman(
    callback: CallbackQuery
):

    result = await open_case(
        callback,
        "Наркоман",
        NARKOMAN_PRICE,
        NARKOMAN_REWARDS,
    )

    if result is None:
        return

    (
        reward_name,
        reward_type,
        reward_value,
        balance,
    ) = result

    if reward_type == "balance":

        text_result = (
            "💊 <b>Наркоман открыт!</b>\n\n"
            f"🎁 {reward_name}\n\n"
            f"Баланс: <b>{balance} ⭐</b>"
        )

    else:

        text_result = (
            "💊 <b>Наркоман открыт!</b>\n\n"
            f"✨ <b>{reward_name}</b>\n\n"
            "Предмет добавлен в инвентарь."
        )

        await notify_admins(
            "🚨 <b>Выпал NFT!</b>\n\n"
            f"ID: <code>"
            f"{callback.from_user.id}"
            f"</code>\n"
            f"Username: "
            f"@{callback.from_user.username or 'нет'}\n"
            "Кейс: Наркоман\n"
            f"Награда: <b>{reward_name}</b>"
        )

    await callback.message.edit_text(
        text_result,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# COLOR CASE
# ============================================================

@dp.callback_query(
    F.data == "case:color"
)
async def color_case(
    callback: CallbackQuery
):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Красный",
                    callback_data="color:red",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔵 Синий",
                    callback_data="color:blue",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🟡 Жёлтый",
                    callback_data="color:yellow",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="cases",
                ),
            ],
        ]
    )

    await callback.message.edit_text(
        "🔴🔵🟡 <b>Красный / "
        "Синий / Жёлтый</b>\n\n"
        "В одном из цветов находится NFT.\n\n"
        "Выбери цвет:",
        reply_markup=keyboard,
    )

    await callback.answer()


# ============================================================
# COLOR RESULT
# ============================================================

@dp.callback_query(
    F.data.startswith("color:")
)
async def color_result(
    callback: CallbackQuery
):

    selected = callback.data.split(
        ":",
        1,
    )[1]

    winning = random.choice(
        [
            "red",
            "blue",
            "yellow",
        ]
    )

    color_names = {
        "red": "🔴 Красный",
        "blue": "🔵 Синий",
        "yellow": "🟡 Жёлтый",
    }

    async with SessionLocal() as db:

        await get_or_create_user(
            db,
            callback.from_user,
        )

        if selected == winning:

            reward_name = "NFT"
            reward_type = "nft"

            await add_inventory(
                db,
                callback.from_user.id,
                reward_name,
                reward_type,
                "Цвет",
            )

        else:

            reward_name = "Проигрыш"
            reward_type = "lose"

        db.add(
            CaseOpen(
                user_id=callback.from_user.id,
                case_name="Цвет",
                price=0,
                selected_color=selected,
                winning_color=winning,
                reward_name=reward_name,
                reward_type=reward_type,
                reward_value=0,
            )
        )

        await db.commit()

    if selected == winning:

        result_text = (
            "🎉 <b>ПОБЕДА!</b>\n\n"
            f"Твой цвет: "
            f"{color_names[selected]}\n"
            f"Выигрышный: "
            f"{color_names[winning]}\n\n"
            "✨ NFT добавлен в инвентарь."
        )

        await notify_admins(
            "🚨 <b>Выпал NFT!</b>\n\n"
            f"ID: <code>"
            f"{callback.from_user.id}"
            f"</code>\n"
            f"Username: "
            f"@{callback.from_user.username or 'нет'}\n"
            f"Цвет: {color_names[winning]}"
        )

    else:

        result_text = (
            "😔 <b>Проигрыш</b>\n\n"
            f"Твой цвет: "
            f"{color_names[selected]}\n"
            f"Выигрышный цвет: "
            f"{color_names[winning]}"
        )

    await callback.message.edit_text(
        result_text,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(user_id):

    return user_id in ADMIN_IDS


# ============================================================
# /STATS
# ============================================================

@dp.message(
    Command("stats")
)
async def stats(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    async with SessionLocal() as db:

        users_count = await db.scalar(
            select(
                func.count(User.id)
            )
        )

        cases_count = await db.scalar(
            select(
                func.count(CaseOpen.id)
            )
        )

        items_count = await db.scalar(
            select(
                func.count(InventoryItem.id)
            )
        )

        total_balance = await db.scalar(
            select(
                func.coalesce(
                    func.sum(User.balance),
                    0,
                )
            )
        )

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: "
        f"<b>{users_count}</b>\n"
        f"🎁 Открытий: "
        f"<b>{cases_count}</b>\n"
        f"📦 Предметов: "
        f"<b>{items_count}</b>\n"
        f"⭐ Общий баланс: "
        f"<b>{total_balance}</b>"
    )


# ============================================================
# /GIVE
# ============================================================

@dp.message(
    Command("give")
)
async def give(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    parts = message.text.split()

    if len(parts) != 3:

        await message.answer(
            "Использование:\n"
            "<code>/give ID СУММА</code>"
        )

        return

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

        if amount <= 0:
            raise ValueError

    except ValueError:

        await message.answer(
            "❌ Неверные данные."
        )

        return

    async with SessionLocal() as db:

        result = await db.execute(
            select(User)
            .where(
                User.id == user_id
            )
            .with_for_update()
        )

        user = result.scalar_one_or_none()

        if user is None:

            await message.answer(
                "❌ Пользователь не найден."
            )

            return

        user.balance += amount

        db.add(
            BalanceLog(
                user_id=user.id,
                admin_id=message.from_user.id,
                amount=amount,
                balance_after=user.balance,
                operation="give",
            )
        )

        await db.commit()

    await message.answer(
        "✅ <b>Звёзды выданы</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Выдано: <b>+{amount} ⭐</b>\n"
        f"Баланс: <b>{user.balance} ⭐</b>"
    )


# ============================================================
# /TAKE
# ============================================================

@dp.message(
    Command("take")
)
async def take(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    parts = message.text.split()

    if len(parts) != 3:

        await message.answer(
            "Использование:\n"
            "<code>/take ID СУММА</code>"
        )

        return

    try:

        user_id = int(parts[1])
        amount = int(parts[2])

        if amount <= 0:
            raise ValueError

    except ValueError:

        await message.answer(
            "❌ Неверные данные."
        )

        return

    async with SessionLocal() as db:

        result = await db.execute(
            select(User)
            .where(
                User.id == user_id
            )
            .with_for_update()
        )

        user = result.scalar_one_or_none()

        if user is None:

            await message.answer(
                "❌ Пользователь не найден."
            )

            return

        if user.balance < amount:

            await message.answer(
                f"❌ У игрока только "
                f"<b>{user.balance} ⭐</b>."
            )

            return

        user.balance -= amount

        db.add(
            BalanceLog(
                user_id=user.id,
                admin_id=message.from_user.id,
                amount=-amount,
                balance_after=user.balance,
                operation="take",
            )
        )

        await db.commit()

    await message.answer(
        "✅ <b>Звёзды сняты</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Снято: <b>-{amount} ⭐</b>\n"
        f"Баланс: <b>{user.balance} ⭐</b>"
    )


# ============================================================
# /INVENTORY
# ============================================================

@dp.message(
    Command("inventory")
)
async def admin_inventory(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "Использование:\n"
            "<code>/inventory ID</code>"
        )

        return

    try:

        user_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Неверный ID."
        )

        return

    async with SessionLocal() as db:

        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.user_id == user_id
            )
            .order_by(
                InventoryItem.id.desc()
            )
            .limit(50)
        )

        items = result.scalars().all()

    if not items:

        await message.answer(
            "📦 Инвентарь пуст."
        )

        return

    lines = [
        "📦 <b>Инвентарь игрока</b>\n"
    ]

    for item in items:

        lines.append(
            f"#{item.id} — "
            f"{item.item_name}\n"
            f"Тип: {item.item_type}\n"
            f"Статус: {item.status}\n"
        )

    await message.answer(
        "\n".join(lines)
    )


# ============================================================
# /ISSUE
# ============================================================

@dp.message(
    Command("issue")
)
async def issue(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    parts = message.text.split(
        maxsplit=2
    )

    if len(parts) < 2:

        await message.answer(
            "Использование:\n"
            "<code>/issue ITEM_ID"
            "</code>"
        )

        return

    try:

        item_id = int(parts[1])

    except ValueError:

        await message.answer(
            "❌ Неверный ID предмета."
        )

        return

    note = (
        parts[2]
        if len(parts) == 3
        else None
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.id == item_id
            )
            .with_for_update()
        )

        item = result.scalar_one_or_none()

        if item is None:

            await message.answer(
                "❌ Предмет не найден."
            )

            return

        item.status = "issued"
        item.admin_note = note

        await db.commit()

    await message.answer(
        f"✅ Предмет #{item_id} "
        "отмечен как выданный."
    )


# ============================================================
# /ADMIN
# ============================================================

@dp.message(
    Command("admin")
)
async def admin_help(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    await message.answer(
        "🛠 <b>Админ-команды</b>\n\n"
        "/stats — статистика\n"
        "/give ID СУММА — выдать ⭐\n"
        "/take ID СУММА — снять ⭐\n"
        "/inventory ID — инвентарь игрока\n"
        "/issue ITEM_ID — отметить предмет выданным\n"
        "/admin — список команд"
    )


# ============================================================
# ОБРАБОТЧИК ОШИБОК
# ============================================================

@dp.errors()
async def error_handler(
    event
):

    logging.exception(
        "Ошибка обработки update: %s",
        event,
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    logging.info(
        "===================================="
    )

    logging.info(
        "Запуск бота..."
    )

    logging.info(
        "API_HOST: %s",
        API_HOST,
    )

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    database_ok = await init_database()

    if not database_ok:

        raise RuntimeError(
            "Не удалось подключиться "
            "к PostgreSQL"
        )

    # --------------------------------------------------------
    # TELEGRAM API
    # --------------------------------------------------------

    try:

        me = await bot.get_me()

        logging.info(
            "Telegram API: OK"
        )

        logging.info(
            "Бот: @%s",
            me.username,
        )

        logging.info(
            "Bot ID: %s",
            me.id,
        )

    except Exception as error:

        logging.exception(
            "Telegram API error: %s",
            error,
        )

        raise

    # --------------------------------------------------------
    # POLLING
    # --------------------------------------------------------

    try:

        logging.info(
            "Polling запущен."
        )

        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
            ],
        )

    finally:

        await bot.session.close()

        await engine.dispose()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logging.info(
            "Бот остановлен."
        )

    except Exception as error:

        logging.exception(
            "Критическая ошибка: %s",
            error,
        )

        raise
