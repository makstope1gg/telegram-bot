import asyncio
import random
import aiosqlite
import pytz
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

# === НАСТРОЙКИ ===
TOKEN = os.getenv("TOKEN") # 🔹 токен
ADMIN_ID = int(os.getenv("ADMIN_ID")) # 🔹 твой Telegram ID
TIMEZONE = pytz.timezone("Asia/Almaty")  # Казахстанское время

bot = Bot(token=TOKEN)
dp = Dispatcher()

# === СОЗДАНИЕ БД ===
async def init_db():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER,
            date TEXT,
            chapter TEXT,
            read INTEGER DEFAULT 0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS daily (
            date TEXT PRIMARY KEY,
            chapter TEXT
        )""")
        await db.commit()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_random_chapter():
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        chapters = [line.strip() for line in f.readlines() if line.strip()]
    return random.choice(chapters)


async def get_today_chapter():
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT chapter FROM daily WHERE date=?", (today,)) as cur:
            row = await cur.fetchone()
            if row:
                return row[0]
        chapter = get_random_chapter()
        await db.execute("INSERT INTO daily (date, chapter) VALUES (?, ?)", (today, chapter))
        await db.commit()
        return chapter


def get_read_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Прочитал", callback_data="read")]
    ])


# === КОМАНДА /start ===
@dp.message(Command("start"))
async def start(message: types.Message):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    chapter = await get_today_chapter()
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"📖 Глава на сегодня:\n<b>{chapter}</b>",
        reply_markup=get_read_button(),
        parse_mode="HTML"
    )


# === КНОПКА 'ПРОЧИТАЛ' ===
@dp.callback_query(lambda c: c.data == "read")
async def mark_read(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    chapter = await get_today_chapter()

    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            INSERT OR REPLACE INTO progress (user_id, date, chapter, read)
            VALUES (?, ?, ?, 1)
        """, (user_id, today, chapter))
        await db.commit()

    await callback.answer("Отмечено ✅")
    await callback.message.edit_reply_markup(None)


# === ОТПРАВКА ГЛАВЫ ВСЕМ ===
async def send_daily_chapter():
    chapter = await get_today_chapter()
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(
                user_id,
                f"📖 Глава на сегодня:\n<b>{chapter}</b>",
                reply_markup=get_read_button(),
                parse_mode="HTML"
            )
        except Exception:
            pass


# === НАПОМИНАНИЯ (9:00, 10:00) ===
async def send_reminders(hour):
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("""
            SELECT user_id FROM users
            WHERE user_id NOT IN (
                SELECT user_id FROM progress WHERE date=? AND read=1
            )
        """, (today,)) as cur:
            users = await cur.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(
                user_id,
                f"⏰ Напоминание {hour}:00!\n"
                f"Не забудь прочитать сегодняшнюю главу 🙏",
                reply_markup=get_read_button()
            )
        except Exception:
            pass


# === АДМИН-ПАНЕЛЬ ===
def admin_panel():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить главу сейчас", callback_data="admin_send")],
        [InlineKeyboardButton(text="🔁 Сменить главу", callback_data="admin_change")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📖 Кто прочитал", callback_data="admin_readers")],
        [InlineKeyboardButton(text="📕 Кто не прочитал", callback_data="admin_notread")]
    ])
    return kb


@dp.message(Command("admin"))
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ Нет доступа")
    await message.answer("⚙️ Админ-панель:", reply_markup=admin_panel())


# === ОБРАБОТКА КНОПОК АДМИНА ===
@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_actions(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")

    action = callback.data.split("_")[1]

    # 📤 Отправить главу сейчас
    if action == "send":
        await send_daily_chapter()
        await callback.answer("✅ Глава отправлена всем")
        await callback.message.edit_text("📤 Глава отправлена всем пользователям.", reply_markup=admin_panel())

    # 🔁 Сменить главу
    elif action == "change":
        chapter = get_random_chapter()
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        async with aiosqlite.connect("database.db") as db:
            await db.execute("INSERT OR REPLACE INTO daily (date, chapter) VALUES (?, ?)", (today, chapter))
            await db.commit()
        await callback.answer("🔁 Глава изменена")
        await callback.message.edit_text(f"🔁 Новая глава на сегодня: <b>{chapter}</b>", parse_mode="HTML", reply_markup=admin_panel())

    # 📊 Статистика
    elif action == "stats":
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                total = (await cur.fetchone())[0]
            async with db.execute("SELECT user_id FROM progress WHERE date=? AND read=1", (today,)) as cur:
                readers = await cur.fetchall()

        read_count = len(readers)
        text = f"📊 <b>Статистика за {today}</b>\n\n" \
               f"👥 Всего пользователей: {total}\n" \
               f"✅ Прочитали главу: {read_count}\n\n"

        if readers:
            text += "<b>Список прочитавших:</b>\n"
            for (user_id,) in readers:
                try:
                    user = await bot.get_chat(user_id)
                    name = user.full_name
                    username = f"(@{user.username})" if user.username else ""
                    text += f"• {name} {username}\n"
                except Exception:
                    text += f"• ID: {user_id}\n"
        else:
            text += "❌ Сегодня пока никто не прочитал главу."

        await callback.answer()
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel())

    # 📖 Кто прочитал
    elif action == "readers":
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT user_id FROM progress WHERE date=? AND read=1", (today,)) as cur:
                users = await cur.fetchall()

        text = "✅ Прочитали главу сегодня:\n\n" if users else "❌ Сегодня никто не прочитал."
        for (user_id,) in users:
            try:
                user = await bot.get_chat(user_id)
                name = user.full_name
                username = f"(@{user.username})" if user.username else ""
                text += f"• {name} {username}\n"
            except Exception:
                text += f"• ID: {user_id}\n"

        await callback.answer()
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel())

    # 📕 Кто не прочитал
    elif action == "notread":
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("""
                SELECT user_id FROM users
                WHERE user_id NOT IN (
                    SELECT user_id FROM progress WHERE date=? AND read=1
                )
            """, (today,)) as cur:
                users = await cur.fetchall()

        text = "📕 Не прочитали главу сегодня:\n\n" if users else "🎉 Все сегодня прочитали!"
        for (user_id,) in users:
            try:
                user = await bot.get_chat(user_id)
                name = user.full_name
                username = f"(@{user.username})" if user.username else ""
                text += f"• {name} {username}\n"
            except Exception:
                text += f"• ID: {user_id}\n"

        await callback.answer()
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel())


# === ПЛАНИРОВЩИК ===
async def scheduler():
    while True:
        now = datetime.now(TIMEZONE)
        times = [
            now.replace(hour=8, minute=0, second=0, microsecond=0),
            now.replace(hour=9, minute=0, second=0, microsecond=0),
            now.replace(hour=10, minute=0, second=0, microsecond=0),
        ]

        if now > times[-1]:
            next_run = times[0] + timedelta(days=1)
            await asyncio.sleep((next_run - now).total_seconds())
            continue

        for i, target in enumerate(times):
            if now < target:
                await asyncio.sleep((target - datetime.now(TIMEZONE)).total_seconds())
                if i == 0:
                    await send_daily_chapter()
                else:
                    await send_reminders(hour=target.hour)


# === ЗАПУСК ===
async def main():
    await init_db()
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
