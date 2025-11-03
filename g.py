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
            user_id INTEGER PRIMARY KEY,
            full_name TEXT
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS state (
            book TEXT,
            chapter INTEGER
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS reads (
            user_id INTEGER,
            full_name TEXT,
            book TEXT,
            chapter INTEGER,
            date TEXT
        )""")
        await db.commit()


# === ЗАГРУЗКА КНИГ ===
def load_chapters():
    chapters = {}
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                book, count = line.strip().split("=")
                chapters[book] = int(count)
    return chapters


# === ВЫБОР КНИГИ (АДМИН) ===
def get_books_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        rows = []
        for line in f:
            if "=" in line:
                book = line.strip().split("=")[0]
                rows.append([InlineKeyboardButton(text=book, callback_data=f"choose_{book}")])
        kb.inline_keyboard = rows
    return kb


# === СОСТОЯНИЕ ===
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


# === КНОПКА ПРОЧИТАЛ ===
def get_read_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Прочитал", callback_data="read")]
    ])


@dp.callback_query(lambda c: c.data == "read")
async def mark_read(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    full_name = callback.from_user.full_name
    book, chapter = await get_state()
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            INSERT INTO reads (user_id, full_name, book, chapter, date)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, full_name, book, chapter, today))
        await db.commit()

    await callback.answer("✅ Отмечено как прочитано")
    await callback.message.edit_reply_markup(None)


# === ОТПРАВКА ГЛАВЫ ВСЕМ ===
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

    text = f"📖 Сегодня читаем:\n<b>{book} {next_chapter}</b>"

    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=get_read_button())
        except Exception:
            pass


# === НАПОМИНАНИЕ ===
async def send_reminders(hour):
    book, chapter = await get_state()
    text = f"⏰ Напоминание {hour}:00!\nНе забудь прочитать <b>{book} {chapter}</b> 🙏"

    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=get_read_button())
        except Exception:
            pass


# === АДМИН-ПАНЕЛЬ ===
def admin_panel():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить главу сейчас", callback_data="admin_send")],
        [InlineKeyboardButton(text="🔁 Сменить книгу", callback_data="admin_change")],
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


# === КНОПКИ АДМИНА ===
@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_actions(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")

    action = callback.data.split("_", 1)[1]

    if action == "send":
        await send_chapter()
        await callback.answer("✅ Глава отправлена всем")
    elif action == "change":
        await callback.message.edit_text("📚 Выбери новую книгу:", reply_markup=get_books_keyboard())
    elif action == "stats":
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                total = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM reads WHERE date=?", (today,)) as cur:
                read_count = (await cur.fetchone())[0]
        text = f"📊 <b>Статистика за {today}</b>\n\n👥 Всего пользователей: {total}\n✅ Прочитали главу: {read_count}"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel())
    elif action == "readers":
        today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT full_name, book, chapter FROM reads WHERE date=?", (today,)) as cur:
                rows = await cur.fetchall()
        if not rows:
            text = "❌ Сегодня никто не прочитал."
        else:
            text = "<b>✅ Прочитали сегодня:</b>\n\n"
            for name, book, chapter in rows:
                text += f"📖 {book} {chapter} — {name}\n"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_panel())


# === ВЫБОР КНИГИ ===
@dp.callback_query(lambda c: c.data.startswith("choose_"))
async def choose_book(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")
    book = callback.data.split("_", 1)[1]
    await set_state(book, 0)
    await callback.message.edit_text(f"✅ Книга выбрана: <b>{book}</b>\nЗавтра начнётся глава 1.", parse_mode="HTML", reply_markup=admin_panel())


# === КОМАНДА /start ===
@dp.message(Command("start"))
async def start(message: types.Message):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?)", (message.from_user.id, message.from_user.full_name))
        await db.commit()
    book, chapter = await get_state()
    if book:
        await message.answer(f"📖 Сейчас идёт книга: <b>{book}</b>, глава {chapter + 1}", parse_mode="HTML", reply_markup=get_read_button())
    else:
        await message.answer("⚠️ Книга пока не выбрана. Ожидаем выбора администратора.")


# === ПЛАНИРОВЩИК ===
async def scheduler():
    while True:
        now = datetime.now(TIMEZONE)
        times = [now.replace(hour=9, minute=0, second=0), now.replace(hour=22, minute=0, second=0)]
        for target in times:
            if now < target:
                await asyncio.sleep((target - now).total_seconds())
                if target.hour == 9:
                    await send_chapter()
                else:
                    await send_reminders(target.hour)
        await asyncio.sleep(3600)


# === ЗАПУСК ===
async def main():
    await init_db()
    asyncio.create_task(scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
