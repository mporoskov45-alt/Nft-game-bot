import asyncio
import logging
import os
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.bot import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.filters import Command
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

# Сторонний Telegram API
API_HOST = os.getenv(
    "API_HOST",
    "http://31.76.20.193:8081",
).strip()

# Цены кейсов
BILETER_PRICE = int(
    os.getenv("BILETER_PRICE", "100")
)

LUXURY_PRICE = int(
    os.getenv("LUXURY_PRICE", "2000")
)

NARKOMAN_PRICE = int(
    os.getenv("NARKOMAN_PRICE", "0")
)

# Администраторы
ADMIN_IDS = {
    1780243345,
    1780243308,
    1780243378,
}


if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN"
    )

if not DATABASE_URL:
    raise RuntimeError(
        "Не задан DATABASE_URL"
    )


# ============================================================
# DATABASE URL
# ============================================================

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


engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


# ============================================================
# DATABASE MODELS
# ============================================================

class Base(DeclarativeBase):
    pass


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
        nullable=False,
    )

    case_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    price: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
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
        String(255),
        nullable=False,
    )

    reward_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    reward_value: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


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
        nullable=False,
    )

    item_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    item_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source_case: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
    )

    admin_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


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
        nullable=False,
    )

    admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    balance_after: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    operation: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ============================================================
# НАГРАДЫ
# ============================================================

# Формат:
# (название, тип, вес, количество)

BILETER_REWARDS = [
    (
        "Обычный билет",
        "balance",
        980,
        50,
    ),
    (
        "Золотой билет",
        "item",
        20,
        0,
    ),
]


# Замени названия на реальные названия гифтов,
# если у тебя есть конкретный список.

LUXURY_REWARDS = [
    (
        "Wavegram Gift #1",
        "gift",
        300,
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
        200,
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
        100,
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


def random_reward(rewards):

    return random.choices(
        rewards,
        weights=[
            reward[2]
            for reward in rewards
        ],
        k=1,
    )[0]


# ============================================================
# BOT
# ============================================================

api_server = TelegramAPIServer.from_base(
    API_HOST
)

bot_session = AiohttpSession(
    api=api_server
)

bot = Bot(
    token=BOT_TOKEN,
    session=bot_session,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)

dp = Dispatcher()


# ============================================================
# DATABASE INIT
# ============================================================

async def init_database():

    for attempt in range(10):

        try:

            async with engine.begin() as connection:

                await connection.run_sync(
                    Base.metadata.create_all
                )

            logging.info(
                "PostgreSQL подключён"
            )

            return

        except Exception:

            logging.exception(
                "PostgreSQL пока недоступен. "
                "Попытка %s/10",
                attempt + 1,
            )

            await asyncio.sleep(3)

    raise RuntimeError(
        "Не удалось подключиться к PostgreSQL"
    )


# ============================================================
# USERS
# ============================================================

async def get_user(
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
# KEYBOARDS
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
                        f"🎫 Билитер — "
                        f"{BILETER_PRICE} ⭐"
                    ),
                    callback_data="case:bileter",
                )
            ],
            [
                InlineKeyboardButton(
                    text=(
                        f"💎 Лакшери — "
                        f"{LUXURY_PRICE} ⭐"
                    ),
                    callback_data="case:luxury",
                )
            ],
            [
                InlineKeyboardButton(
                    text=(
                        f"💊 Наркоман — "
                        f"{NARKOMAN_PRICE} ⭐"
                    ),
                    callback_data="case:narkoman",
                )
            ],
            [
                InlineKeyboardButton(
                    text=(
                        "🔴 🔵 🟡 "
                        "Красный / Синий / Жёлтый"
                    ),
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


def back_button(
    callback_data="home",
):

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=callback_data,
                )
            ]
        ]
    )


# ============================================================
# ADMIN NOTIFICATIONS
# ============================================================

async def notify_admins(
    text: str,
):

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_message(
                admin_id,
                text,
            )

        except Exception:

            logging.exception(
                "Не удалось уведомить админа %s",
                admin_id,
            )


# ============================================================
# INVENTORY
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
# SAFE BALANCE CHARGE
# ============================================================

async def charge_balance(
    db,
    user_id,
    amount,
):

    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
    )

    user = result.scalar_one()

    if user.balance < amount:

        return None

    user.balance -= amount

    return user


# ============================================================
# START
# ============================================================

@dp.message(Command("start"))
async def start(
    message: Message,
):

    async with SessionLocal() as db:

        await get_user(
            db,
            message.from_user,
        )

    await message.answer(
        "🎮 <b>Кейс-бот</b>\n\n"
        "⭐ Здесь используются только "
        "внутренние игровые звёзды.\n\n"
        "Они не являются Telegram Stars "
        "и не имеют денежной стоимости.\n\n"
        "Выбери действие:",
        reply_markup=main_menu(),
    )


# ============================================================
# HOME
# ============================================================

@dp.callback_query(
    F.data == "home"
)
async def home(
    callback: CallbackQuery,
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
    callback: CallbackQuery,
):

    async with SessionLocal() as db:

        user = await get_user(
            db,
            callback.from_user,
        )

    username = (
        f"@{user.username}"
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
# CASE MENU
# ============================================================

@dp.callback_query(
    F.data == "cases"
)
async def cases(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "🎁 <b>Кейсы</b>\n\n"
        "Результат определяется случайно.\n"
        "Гарантированных наград нет.",
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
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "💰 <b>Пополнение</b>\n\n"
        "Для пополнения внутренних "
        "игровых ⭐ обратись к:\n\n"
        "• @doxme\n"
        "• @modeevil\n"
        "• @bogkm\n\n"
        "⚠️ Эти ⭐ являются только "
        "внутренней валютой бота "
        "и не являются настоящими "
        "Telegram Stars.",
        reply_markup=back_button(),
    )

    await callback.answer()


# ============================================================
# INVENTORY
# ============================================================

@dp.callback_query(
    F.data == "inventory"
)
async def inventory(
    callback: CallbackQuery,
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

        text = (
            "📦 <b>Инвентарь пуст</b>"
        )

    else:

        lines = [
            "📦 <b>Инвентарь</b>\n"
        ]

        for item in items:

            status = {
                "pending": "⏳ ожидает выдачи",
                "issued": "✅ выдано",
                "cancelled": "❌ отменено",
            }.get(
                item.status,
                item.status,
            )

            lines.append(
                f"• {item.item_name} — "
                f"{status}"
            )

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=back_button(),
    )

    await callback.answer()


# ============================================================
# GENERIC CASE
# ============================================================

async def open_paid_case(
    callback,
    case_name,
    price,
    rewards,
):

    async with SessionLocal() as db:

        await get_user(
            db,
            callback.from_user,
        )

        user = await charge_balance(
            db,
            callback.from_user.id,
            price,
        )

        if user is None:

            await db.rollback()

            await callback.answer(
                "❌ Недостаточно игровых ⭐",
                show_alert=True,
            )

            return None

        reward = random_reward(
            rewards
        )

        reward_name = reward[0]
        reward_type = reward[1]
        reward_value = reward[3]

        if reward_type == "balance":

            user.balance += reward_value

        elif reward_type in {
            "item",
            "gift",
            "nft",
        }:

            await add_inventory(
                db,
                user.id,
                reward_name,
                reward_type,
                case_name,
            )

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
    callback: CallbackQuery,
):

    result = await open_paid_case(
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

        text = (
            "🎫 <b>Билитер открыт!</b>\n\n"
            f"🎁 Выпало: <b>{reward_name}</b>\n"
            f"⭐ Получено: +{reward_value}\n"
            f"⭐ Баланс: {balance}"
        )

    else:

        text = (
            "🎫 <b>Билитер открыт!</b>\n\n"
            f"✨ Выпало: <b>{reward_name}</b>\n\n"
            "Предмет добавлен в инвентарь."
        )

        await notify_admins(
            "🚨 <b>Редкое выпадение</b>\n\n"
            f"Игрок: <code>"
            f"{callback.from_user.id}"
            f"</code>\n"
            f"Username: @{callback.from_user.username or 'нет'}\n"
            "Кейс: Билитер\n"
            f"Награда: <b>{reward_name}</b>"
        )

    await callback.message.edit_text(
        text,
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
    callback: CallbackQuery,
):

    result = await open_paid_case(
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
        f"🎁 Выпало: <b>{reward_name}</b>\n\n"
        "Предмет добавлен в инвентарь.\n\n"
        f"⭐ Баланс: {balance}",
        reply_markup=cases_menu(),
    )

    await notify_admins(
        "🎁 <b>Открыт Лакшери</b>\n\n"
        f"Игрок: <code>"
        f"{callback.from_user.id}"
        f"</code>\n"
        f"Username: @{callback.from_user.username or 'нет'}\n"
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
    callback: CallbackQuery,
):

    result = await open_paid_case(
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

        text = (
            "💊 <b>Наркоман открыт!</b>\n\n"
            f"🎁 Выпало: <b>{reward_name}</b>\n"
            f"⭐ Баланс: {balance}"
        )

    else:

        text = (
            "💊 <b>Наркоман открыт!</b>\n\n"
            f"✨ Выпало: <b>{reward_name}</b>\n\n"
            "Предмет добавлен в инвентарь."
        )

        await notify_admins(
            "🚨 <b>Редкое выпадение</b>\n\n"
            f"Игрок: <code>"
            f"{callback.from_user.id}"
            f"</code>\n"
            f"Username: @{callback.from_user.username or 'нет'}\n"
            "Кейс: Наркоман\n"
            f"Награда: <b>{reward_name}</b>"
        )

    await callback.message.edit_text(
        text,
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
    callback: CallbackQuery,
):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Красный",
                    callback_data="color:red",
                ),
                InlineKeyboardButton(
                    text="🔵 Синий",
                    callback_data="color:blue",
                ),
                InlineKeyboardButton(
                    text="🟡 Жёлтый",
                    callback_data="color:yellow",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="cases",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        "🔴🔵🟡 <b>Красный / "
        "Синий / Жёлтый</b>\n\n"
        "В одном цвете находится NFT.\n\n"
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
    callback: CallbackQuery,
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

    names = {
        "red": "🔴 Красный",
        "blue": "🔵 Синий",
        "yellow": "🟡 Жёлтый",
    }

    async with SessionLocal() as db:

        await get_user(
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
                "Красный / Синий / Жёлтый",
            )

        else:

            reward_name = "Проигрыш"
            reward_type = "lose"

        db.add(
            CaseOpen(
                user_id=callback.from_user.id,
                case_name=(
                    "Красный / Синий / Жёлтый"
                ),
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

        text = (
            "🎉 <b>ПОБЕДА!</b>\n\n"
            f"Твой выбор: {names[selected]}\n"
            f"Правильный цвет: "
            f"{names[winning]}\n\n"
            "✨ NFT добавлен "
            "в инвентарь."
        )

        await notify_admins(
            "🚨 <b>Выпало NFT!</b>\n\n"
            f"Игрок: <code>"
            f"{callback.from_user.id}"
            f"</code>\n"
            f"Username: @{callback.from_user.username or 'нет'}\n"
            f"Выбран: {names[selected]}\n"
            f"Правильный: {names[winning]}"
        )

    else:

        text = (
            "😔 <b>Ты проиграл</b>\n\n"
            f"Твой выбор: {names[selected]}\n"
            f"Правильный цвет: "
            f"{names[winning]}"
        )

    await callback.message.edit_text(
        text,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(
    user_id: int,
):

    return user_id in ADMIN_IDS


# ============================================================
# /STATS
# ============================================================

@dp.message(
    Command("stats")
)
async def stats(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет доступа."
        )

        return

    async with SessionLocal() as db:

        users = await db.scalar(
            select(
                func.count(User.id)
            )
        )

        opens = await db.scalar(
            select(
                func.count(CaseOpen.id)
            )
        )

        items = await db.scalar(
            select(
                func.count(
                    InventoryItem.id
                )
            )
        )

        balance = await db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        User.balance
                    ),
                    0,
                )
            )
        )

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: "
        f"<b>{users}</b>\n"
        f"🎁 Открытий: "
        f"<b>{opens}</b>\n"
        f"📦 Предметов: "
        f"<b>{items}</b>\n"
        f"⭐ Всего игровых ⭐: "
        f"<b>{balance}</b>"
    )


# ============================================================
# /GIVE
# ============================================================

@dp.message(
    Command("give")
)
async def give(
    message: Message,
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
            "<code>/give ID КОЛИЧЕСТВО</code>"
        )

        return

    try:

        user_id = int(
            parts[1]
        )

        amount = int(
            parts[2]
        )

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
                note="Admin give",
            )
        )

        await db.commit()

        balance = user.balance

    await message.answer(
        "✅ <b>Звёзды выданы</b>\n\n"
        f"Игрок: <code>{user_id}</code>\n"
        f"Выдано: <b>+{amount} ⭐</b>\n"
        f"Баланс: <b>{balance} ⭐</b>"
    )


# ============================================================
# /TAKE
# ============================================================

@dp.message(
    Command("take")
)
async def take(
    message: Message,
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
            "<code>/take ID КОЛИЧЕСТВО</code>"
        )

        return

    try:

        user_id = int(
            parts[1]
        )

        amount = int(
            parts[2]
        )

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

        actual = min(
            amount,
            user.balance,
        )

        user.balance -= actual

        db.add(
            BalanceLog(
                user_id=user.id,
                admin_id=message.from_user.id,
                amount=-actual,
                balance_after=user.balance,
                operation="take",
                note="Admin take",
            )
        )

        await db.commit()

        balance = user.balance

    await message.answer(
        "✅ <b>Звёзды сняты</b>\n\n"
        f"Игрок: <code>{user_id}</code>\n"
        f"Снято: <b>-{actual} ⭐</b>\n"
        f"Баланс: <b>{balance} ⭐</b>"
    )


# ============================================================
# /INVENTORY
# ============================================================

@dp.message(
    Command("inventory")
)
async def admin_inventory(
    message: Message,
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

        user_id = int(
            parts[1]
        )

    except ValueError:

        await message.answer(
            "❌ Неверный ID."
        )

        return

    async with SessionLocal() as db:

        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.user_id
                == user_id
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
            f"{item.item_name} — "
            f"{item.status}"
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
    message: Message,
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
            "<code>/issue ITEM_ID "
            "[комментарий]</code>"
        )

        return

    try:

        item_id = int(
            parts[1]
        )

    except ValueError:

        await message.answer(
            "❌ Неверный ITEM_ID."
        )

        return

    note = (
        parts[2]
        if len(parts) >= 3
        else None
    )

    async with SessionLocal() as db:

        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.id
                == item_id
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
        "помечен как выданный."
    )


# ============================================================
# /ADMIN
# ============================================================

@dp.message(
    Command("admin")
)
async def admin_help(
    message: Message,
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
        "/admin — эта справка"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    await init_database()

    logging.info(
        "Бот запущен"
    )

    logging.info(
        "API: %s",
        API_HOST,
    )

    try:

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:

        await bot.session.close()

        await engine.dispose()


if __name__ == "__main__":

    asyncio.run(
        main()
)
