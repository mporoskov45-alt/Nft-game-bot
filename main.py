import os
import random
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    select,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Адрес твоего стороннего Telegram API
API_HOST = os.getenv("API_HOST", "http://31.76.20.193:8081")

ADMIN_IDS = {
    1780243345,
    1780243308,
    1780243378,
}

START_BALANCE = 0


# ============================================================
# DATABASE
# ============================================================

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан")

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
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


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
        default=START_BALANCE,
    )

    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
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
    )

    case_name: Mapped[str] = mapped_column(
        String(100),
    )

    reward_name: Mapped[str] = mapped_column(
        String(255),
    )

    reward_type: Mapped[str] = mapped_column(
        String(50),
    )

    reward_value: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ============================================================
# BOT
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

server = TelegramAPIServer.from_base(
    API_HOST
)

bot = Bot(
    token=BOT_TOKEN,
    session=None,
    server=server,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
    ),
)

dp = Dispatcher()


# ============================================================
# HELPERS
# ============================================================

async def get_user(
    session: AsyncSession,
    telegram_user,
) -> User:

    result = await session.execute(
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
            balance=START_BALANCE,
            is_admin=telegram_user.id in ADMIN_IDS,
        )

        session.add(user)
        await session.commit()
        await session.refresh(user)

    else:
        user.username = telegram_user.username
        user.first_name = telegram_user.first_name

        if telegram_user.id in ADMIN_IDS:
            user.is_admin = True

        await session.commit()

    return user


async def notify_admins(text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
            )
        except Exception as e:
            logging.error(
                "Ошибка отправки админу %s: %s",
                admin_id,
                e,
            )


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
            ],
        ]
    )


def cases_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎫 Билитер — 100 ⭐",
                    callback_data="case_bileter",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Лакшери — 2000 ⭐",
                    callback_data="case_luxury",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💊 Наркоман",
                    callback_data="case_narkoman",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔴🔵🟡 Красный / Синий / Жёлтый",
                    callback_data="case_color",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back",
                )
            ],
        ]
    )


# ============================================================
# CASE DATA
# ============================================================

# Никаких гарантированных наград.
#
# weight — относительный шанс.
#
# Например:
# 980 / 20 = 98% / 2%
#
# Значения можно изменять самостоятельно.

BILETER_REWARDS = [
    {
        "name": "Обычный билет",
        "type": "balance",
        "value": 50,
        "weight": 980,
    },
    {
        "name": "Золотой билет",
        "type": "item",
        "value": 0,
        "weight": 20,
    },
]


LUXURY_REWARDS = [
    {
        "name": "Wavegram Gift #1",
        "type": "gift",
        "value": 0,
        "weight": 300,
    },
    {
        "name": "Wavegram Gift #2",
        "type": "gift",
        "value": 0,
        "weight": 250,
    },
    {
        "name": "Wavegram Gift #3",
        "type": "gift",
        "value": 0,
        "weight": 200,
    },
    {
        "name": "Редкий Wavegram Gift",
        "type": "gift",
        "value": 0,
        "weight": 150,
    },
    {
        "name": "Очень редкий Wavegram Gift",
        "type": "gift",
        "value": 0,
        "weight": 100,
    },
]


NARKOMAN_REWARDS = [
    {
        "name": "50 игровых ⭐",
        "type": "balance",
        "value": 50,
        "weight": 970,
    },
    {
        "name": "NFT Глазик",
        "type": "nft",
        "value": 0,
        "weight": 30,
    },
]


def weighted_reward(rewards):

    return random.choices(
        rewards,
        weights=[
            reward["weight"]
            for reward in rewards
        ],
        k=1,
    )[0]


# ============================================================
# START
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):

    async with SessionLocal() as session:

        await get_user(
            session,
            message.from_user,
        )

    await message.answer(
        "🎰 <b>Добро пожаловать!</b>\n\n"
        "Это игровой бот с внутренними ⭐.\n"
        "Игровые звёзды являются только виртуальной валютой "
        "этого бота и не являются Telegram Stars.\n\n"
        "Выбирай действие:",
        reply_markup=main_menu(),
    )


# ============================================================
# PROFILE
# ============================================================

@dp.callback_query(F.data == "profile")
async def profile(
    callback: CallbackQuery,
):

    async with SessionLocal() as session:

        user = await get_user(
            session,
            callback.from_user,
        )

        username = (
            f"@{user.username}"
            if user.username
            else "не указан"
        )

        text = (
            "👤 <b>Профиль</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Username: {username}\n"
            f"💰 Баланс: <b>{user.balance} ⭐</b>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu(),
    )

    await callback.answer()


# ============================================================
# CASES MENU
# ============================================================

@dp.callback_query(F.data == "cases")
async def cases(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "🎁 <b>Кейсы</b>\n\n"
        "Все результаты определяются случайно.\n"
        "Гарантированных наград нет.",
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# DEPOSIT
# ============================================================

@dp.callback_query(F.data == "deposit")
async def deposit(
    callback: CallbackQuery,
):

    text = (
        "💰 <b>Пополнение</b>\n\n"
        "В этом боте используются только "
        "внутренние игровые ⭐.\n\n"
        "⚠️ Они не являются настоящими "
        "Telegram Stars и не имеют денежной стоимости.\n\n"
        "Для пополнения обратись к администратору "
        "бота."
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data="back",
                    )
                ]
            ]
        ),
    )

    await callback.answer()


# ============================================================
# BACK
# ============================================================

@dp.callback_query(F.data == "back")
async def back(
    callback: CallbackQuery,
):

    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu(),
    )

    await callback.answer()


# ============================================================
# BILETER
# ============================================================

@dp.callback_query(F.data == "case_bileter")
async def bileter(
    callback: CallbackQuery,
):

    price = 100

    async with SessionLocal() as session:

        user = await get_user(
            session,
            callback.from_user,
        )

        if user.balance < price:

            await callback.answer(
                "❌ Недостаточно игровых ⭐",
                show_alert=True,
            )
            return

        user.balance -= price

        reward = weighted_reward(
            BILETER_REWARDS
        )

        if reward["type"] == "balance":
            user.balance += reward["value"]

        opening = CaseOpen(
            user_id=user.id,
            case_name="Билитер",
            reward_name=reward["name"],
            reward_type=reward["type"],
            reward_value=reward["value"],
        )

        session.add(opening)
        await session.commit()

        new_balance = user.balance

    if reward["type"] == "balance":

        text = (
            "🎫 <b>Билитер открыт!</b>\n\n"
            f"🎁 Выпало: <b>{reward['name']}</b>\n"
            f"💰 Получено: +{reward['value']} ⭐\n\n"
            f"Баланс: {new_balance} ⭐"
        )

    else:

        text = (
            "🎫 <b>Билитер открыт!</b>\n\n"
            f"✨ Выпало: <b>{reward['name']}</b>\n\n"
            "Редкая награда!"
        )

        await notify_admins(
            "🚨 <b>Редкое выпадение</b>\n\n"
            f"Игрок: <code>{callback.from_user.id}</code>\n"
            f"Username: @{callback.from_user.username or 'нет'}\n"
            "Кейс: Билитер\n"
            f"Награда: <b>{reward['name']}</b>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# LUXURY
# ============================================================

@dp.callback_query(F.data == "case_luxury")
async def luxury(
    callback: CallbackQuery,
):

    price = 2000

    async with SessionLocal() as session:

        user = await get_user(
            session,
            callback.from_user,
        )

        if user.balance < price:

            await callback.answer(
                "❌ Недостаточно игровых ⭐",
                show_alert=True,
            )
            return

        user.balance -= price

        reward = weighted_reward(
            LUXURY_REWARDS
        )

        opening = CaseOpen(
            user_id=user.id,
            case_name="Лакшери",
            reward_name=reward["name"],
            reward_type=reward["type"],
            reward_value=reward["value"],
        )

        session.add(opening)

        await session.commit()

    text = (
        "💎 <b>Лакшери открыт!</b>\n\n"
        f"🎁 Выпало: <b>{reward['name']}</b>\n\n"
        "Лучшие подарки Wavegram."
    )

    await notify_admins(
        "🎁 <b>Открыт кейс Лакшери</b>\n\n"
        f"Игрок: <code>{callback.from_user.id}</code>\n"
        f"Username: @{callback.from_user.username or 'нет'}\n"
        f"Награда: <b>{reward['name']}</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# NARKOMAN
# ============================================================

@dp.callback_query(F.data == "case_narkoman")
async def narkoman(
    callback: CallbackQuery,
):

    # Бесплатный кейс по твоему описанию.
    price = 0

    async with SessionLocal() as session:

        user = await get_user(
            session,
            callback.from_user,
        )

        reward = weighted_reward(
            NARKOMAN_REWARDS
        )

        if reward["type"] == "balance":
            user.balance += reward["value"]

        opening = CaseOpen(
            user_id=user.id,
            case_name="Наркоман",
            reward_name=reward["name"],
            reward_type=reward["type"],
            reward_value=reward["value"],
        )

        session.add(opening)

        await session.commit()

        new_balance = user.balance

    text = (
        "💊 <b>Кейс Наркоман</b>\n\n"
        f"🎁 Выпало: <b>{reward['name']}</b>\n"
    )

    if reward["type"] == "balance":
        text += (
            f"\n💰 Баланс: {new_balance} ⭐"
        )
    else:
        text += "\n✨ Редкая награда!"

        await notify_admins(
            "🚨 <b>Редкое выпадение!</b>\n\n"
            f"Игрок: <code>{callback.from_user.id}</code>\n"
            f"Username: @{callback.from_user.username or 'нет'}\n"
            "Кейс: Наркоман\n"
            f"Награда: <b>{reward['name']}</b>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# COLOR CASE
# ============================================================

@dp.callback_query(F.data == "case_color")
async def color_case(
    callback: CallbackQuery,
):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 Красный",
                    callback_data="color_red",
                ),
                InlineKeyboardButton(
                    text="🔵 Синий",
                    callback_data="color_blue",
                ),
                InlineKeyboardButton(
                    text="🟡 Жёлтый",
                    callback_data="color_yellow",
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
        "🔴🔵🟡 <b>Выбери цвет</b>\n\n"
        "В одном из трёх цветов находится NFT.\n"
        "Если выберешь правильный цвет — получишь NFT.\n"
        "Если ошибёшься — проигрыш.\n\n"
        "Цвет определяется случайно.",
        reply_markup=keyboard,
    )

    await callback.answer()


@dp.callback_query(
    F.data.in_({
        "color_red",
        "color_blue",
        "color_yellow",
    })
)
async def color_result(
    callback: CallbackQuery,
):

    selected = callback.data.replace(
        "color_",
        "",
    )

    winning_color = random.choice(
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

    async with SessionLocal() as session:

        user = await get_user(
            session,
            callback.from_user,
        )

        if selected == winning_color:

            reward_name = "NFT"

            opening = CaseOpen(
                user_id=user.id,
                case_name="Красный / Синий / Жёлтый",
                reward_name=reward_name,
                reward_type="nft",
                reward_value=0,
            )

            session.add(opening)

            await session.commit()

            won = True

        else:

            reward_name = "Проигрыш"

            opening = CaseOpen(
                user_id=user.id,
                case_name="Красный / Синий / Жёлтый",
                reward_name=reward_name,
                reward_type="lose",
                reward_value=0,
            )

            session.add(opening)

            await session.commit()

            won = False

    if won:

        text = (
            "🎉 <b>ПОБЕДА!</b>\n\n"
            f"Твой цвет: {names[selected]}\n"
            f"Правильный цвет: {names[winning_color]}\n\n"
            "✨ Ты получил NFT!"
        )

        await notify_admins(
            "🚨 <b>Выпало NFT!</b>\n\n"
            f"Игрок: <code>{callback.from_user.id}</code>\n"
            f"Username: @{callback.from_user.username or 'нет'}\n"
            "Кейс: Красный / Синий / Жёлтый\n"
            f"Цвет: {names[winning_color]}"
        )

    else:

        text = (
            "😔 <b>Ты проиграл</b>\n\n"
            f"Твой цвет: {names[selected]}\n"
            f"Правильный цвет: {names[winning_color]}\n\n"
            "Попробуй ещё раз."
        )

    await callback.message.edit_text(
        text,
        reply_markup=cases_menu(),
    )

    await callback.answer()


# ============================================================
# ADMIN CHECK
# ============================================================

async def check_admin(
    message: Message,
):

    if message.from_user.id not in ADMIN_IDS:

        await message.answer(
            "❌ У тебя нет доступа к этой команде."
        )

        return False

    return True


# ============================================================
# ADMIN: STATS
# ============================================================

@dp.message(Command("stats"))
async def admin_stats(
    message: Message,
):

    if not await check_admin(message):
        return

    async with SessionLocal() as session:

        users_count = (
            await session.scalar(
                select(func.count(User.id))
            )
        )

        opens_count = (
            await session.scalar(
                select(func.count(CaseOpen.id))
            )
        )

        total_balance = (
            await session.scalar(
                select(func.coalesce(
                    func.sum(User.balance),
                    0,
                ))
            )
        )

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{users_count}</b>\n"
        f"🎁 Открытий: <b>{opens_count}</b>\n"
        f"💰 Всего игровых ⭐: <b>{total_balance}</b>"
    )


# ============================================================
# ADMIN: GIVE
# ============================================================

@dp.message(Command("give"))
async def admin_give(
    message: Message,
):

    if not await check_admin(message):
        return

    parts = message.text.split()

    if len(parts) != 3:

        await message.answer(
            "Использование:\n"
            "<code>/give ID КОЛИЧЕСТВО</code>"
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

    async with SessionLocal() as session:

        result = await session.execute(
            select(User).where(
                User.id == user_id
            )
        )

        user = result.scalar_one_or_none()

        if user is None:

            await message.answer(
                "❌ Пользователь не найден."
            )

            return

        user.balance += amount

        await session.commit()

        new_balance = user.balance

    await message.answer(
        "✅ <b>Звёзды выданы</b>\n\n"
        f"Игрок: <code>{user_id}</code>\n"
        f"Выдано: <b>{amount} ⭐</b>\n"
        f"Баланс: <b>{new_balance} ⭐</b>"
    )


# ============================================================
# ADMIN: TAKE
# ============================================================

@dp.message(Command("take"))
async def admin_take(
    message: Message,
):

    if not await check_admin(message):
        return

    parts = message.text.split()

    if len(parts) != 3:

        await message.answer(
            "Использование:\n"
            "<code>/take ID КОЛИЧЕСТВО</code>"
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

    async with SessionLocal() as session:

        result = await session.execute(
            select(User).where(
                User.id == user_id
            )
        )

        user = result.scalar_one_or_none()

        if user is None:

            await message.answer(
                "❌ Пользователь не найден."
            )

            return

        user.balance = max(
            0,
            user.balance - amount,
        )

        await session.commit()

        new_balance = user.balance

    await message.answer(
        "✅ <b>Звёзды сняты</b>\n\n"
        f"Игрок: <code>{user_id}</code>\n"
        f"Снято: <b>{amount} ⭐</b>\n"
        f"Баланс: <b>{new_balance} ⭐</b>"
    )


# ============================================================
# ADMIN: HELP
# ============================================================

@dp.message(Command("admin"))
async def admin_help(
    message: Message,
):

    if not await check_admin(message):
        return

    await message.answer(
        "🛠 <b>Админ-панель</b>\n\n"
        "/stats — статистика\n"
        "/give ID СУММА — выдать ⭐\n"
        "/take ID СУММА — снять ⭐\n"
        "/admin — эта справка"
    )


# ============================================================
# ERROR HANDLER
# ============================================================

@dp.errors()
async def errors_handler(event):

    logging.exception(
        "Ошибка обработки обновления: %s",
        event.exception,
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

    await init_db()

    logging.info(
        "Bot started"
    )

    await dp.start_polling(
        bot,
    )


if __name__ == "__main__":

    asyncio.run(
        main()
                )
