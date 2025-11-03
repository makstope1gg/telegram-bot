import asyncio
import aiosqlite
import random
import pytz
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

# === НАСТРОЙКИ ===
TOKEN = os.getenv("TOKEN")  # 🔹 токен
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # 🔹 Telegram ID админа
TIMEZONE = pytz.timezone("Asia/Almaty")

bot = Bot(token=TOKEN)
dp = Dispatcher()


# === СОЗДАНИЕ БД ===
async def init_db():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS state (
            book TEXT,
            chapter INTEGER
        )""")
        await db.commit()


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def load_chapters():
    chapters = {}
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                book, count = line.strip().split("=")
                chapters[book] = int(count)
    return chapters


def get_books_keyboard():
    kb = InlineKeyboardMarkup()
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                book = line.strip().split("=")[0]
                kb.add(InlineKeyboardButton(text=book, callback_data=f"choose_{book}"))
    return kb


async def get_state():
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT book, chapter FROM state LIMIT 1") as cur:
            row = await cur.fetchone()
            return row if row else (None, 0)


async def set_state(book, chapter):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("DELETE FROM state")
        await db.execute("INSERT INTO state (book, chapter) VALUES (?, ?)", (book, chapter))
        await db.commit()


async def send_chapter():
    book, chapter = await get_state()
    if not book:
        await bot.send_message(ADMIN_ID, "⚠️ Книга не выбрана. Выбери новую через /admin")
        return

    all_books = load_chapters()
    total = all_books.get(book, 0)

    if chapter >= total:
        await bot.send_message(ADMIN_ID, f"✅ Книга '{book}' закончилась!\nВыбери новую через /admin")
        return

    next_chapter = chapter + 1
    await set_state(book, next_chapter)

    # Рассылаем пользователям
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(
                user_id,
                f"📖 Сегодня читаем:\n<b>{book} {next_chapter}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass


# === КОМАНДА /start ===
@dp.message(Command("start"))
async def start(message: types.Message):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    book, chapter = await get_state()
    if book:
        await message.answer(f"📖 Сейчас идёт книга: <b>{book}</b>, глава {chapter + 1}", parse_mode="HTML")
    else:
        await message.answer("⚠️ Книга пока не выбрана. Ожидаем выбора администратора.")


# === КОМАНДА /admin ===
@dp.message(Command("admin"))
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ Нет доступа")
    await message.answer("📚 Выбери книгу для чтения:", reply_markup=get_books_keyboard())


# === ОБРАБОТКА ВЫБОРА КНИГИ ===
@dp.callback_query(lambda c: c.data.startswith("choose_"))
async def choose_book(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")

    book = callback.data.split("_", 1)[1]
    await set_state(book, 0)
    await callback.message.edit_text(f"✅ Книга выбрана: <b>{book}</b>\nЗавтра начнётся глава 1.", parse_mode="HTML")


# === ПЛАНИРОВЩИК ===
async def scheduler():
    while True:
        now = datetime.now(TIMEZONE)
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await send_chapter()


# === ЗАПУСК ===
async def main():
    await init_db()
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
