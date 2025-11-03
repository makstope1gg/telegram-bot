import asyncio
import aiosqlite
import pytz
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

# === НАСТРОЙКИ ===
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
TIMEZONE = pytz.timezone("Asia/Almaty")

bot = Bot(token=TOKEN)
dp = Dispatcher()


# === ИНИЦИАЛИЗАЦИЯ БД ===
async def init_db():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_read TEXT
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS state (
            book TEXT,
            chapter INTEGER
        )""")
        await db.commit()


# === ФУНКЦИИ ===
def load_chapters():
    chapters = {}
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                book, count = line.strip().split("=")
                chapters[book] = int(count)
    return chapters


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


def admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить главу сейчас", callback_data="admin_send")],
        [InlineKeyboardButton(text="🔁 Сменить книгу", callback_data="admin_change")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📖 Кто прочитал", callback_data="admin_readers")],
        [InlineKeyboardButton(text="📕 Кто не прочитал", callback_data="admin_notread")]
    ])
    return kb


def get_books_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    with open("bible_chapters.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                book = line.strip().split("=")[0]
                kb.inline_keyboard.append([InlineKeyboardButton(text=book, callback_data=f"choose_{book}")])
    return kb


# === КОМАНДЫ ===
@dp.message(Command("start"))
async def start(message: types.Message):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, last_read) VALUES (?, ?)", (message.from_user.id, ""))
        await db.commit()
    book, chapter = await get_state()
    if book:
        await message.answer(f"📖 Сейчас читаем: <b>{book} {chapter + 1}</b>", parse_mode="HTML")
    else:
        await message.answer("⚠️ Книга пока не выбрана. Ожидаем выбора администратора.")


@dp.message(Command("admin"))
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ Нет доступа")
    await message.answer("⚙️ Админ-панель:", reply_markup=admin_keyboard())


# === ОБРАБОТКА КНОПОК АДМИНА ===
@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_actions(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")

    action = callback.data.split("_", 1)[1]

    if action == "change":
        await callback.message.edit_text("📚 Выбери книгу:", reply_markup=get_books_keyboard())

    elif action == "send":
        await send_chapter()
        await callback.answer("Глава отправлена ✅")

    elif action == "stats":
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                total = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM users WHERE last_read = (SELECT book || ' ' || chapter FROM state LIMIT 1)") as cur:
                readed = (await cur.fetchone())[0]
        await callback.message.answer(f"📊 Прочитали: {readed}/{total}")

    elif action == "readers":
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT user_id FROM users WHERE last_read = (SELECT book || ' ' || chapter FROM state LIMIT 1)") as cur:
                readers = await cur.fetchall()
        if not readers:
            await callback.message.answer("❌ Никто не прочитал.")
        else:
            text = "\n".join([f"• {user_id}" for (user_id,) in readers])
            await callback.message.answer(f"📖 Прочитали:\n{text}")

    elif action == "notread":
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT user_id FROM users WHERE last_read != (SELECT book || ' ' || chapter FROM state LIMIT 1)") as cur:
                not_readers = await cur.fetchall()
        if not not_readers:
            await callback.message.answer("✅ Все прочитали!")
        else:
            text = "\n".join([f"• {user_id}" for (user_id,) in not_readers])
            await callback.message.answer(f"📕 Не прочитали:\n{text}")


# === ВЫБОР КНИГИ ===
@dp.callback_query(lambda c: c.data.startswith("choose_"))
async def choose_book(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа")
    book = callback.data.split("_", 1)[1]
    await set_state(book, 0)
    await callback.message.edit_text(f"✅ Книга выбрана: <b>{book}</b>", parse_mode="HTML")


# === КНОПКА "ПРОЧИТАЛ" ===
@dp.callback_query(lambda c: c.data == "read_done")
async def read_done(callback: types.CallbackQuery):
    book, chapter = await get_state()
    read_label = f"{book} {chapter}"
    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE users SET last_read = ? WHERE user_id = ?", (read_label, callback.from_user.id))
        await db.commit()
    await callback.answer("✅ Отлично! Отмечено как прочитано 🙏")


# === ОТПРАВКА ГЛАВЫ ВСЕМ ===
async def send_chapter():
    book, chapter = await get_state()
    if not book:
        await bot.send_message(ADMIN_ID, "⚠️ Книга не выбрана.")
        return

    all_books = load_chapters()
    total = all_books.get(book, 0)
    if chapter >= total:
        await bot.send_message(ADMIN_ID, f"✅ Книга '{book}' закончилась!")
        return

    next_chapter = chapter + 1
    await set_state(book, next_chapter)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Прочитал", callback_data="read_done")]
    ])

    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(user_id, f"📖 Сегодня читаем:\n<b>{book} {next_chapter}</b>", parse_mode="HTML", reply_markup=kb)
        except:
            pass


# === НАПОМИНАНИЯ ===
async def reminders():
    while True:
        now = datetime.now(TIMEZONE)
        if now.hour in [9, 22] and now.minute == 0:
            book, chapter = await get_state()
            async with aiosqlite.connect("database.db") as db:
                async with db.execute("SELECT user_id FROM users") as cur:
                    users = await cur.fetchall()
            for (user_id,) in users:
                try:
                    await bot.send_message(user_id, f"⏰ Напоминание! Не забудь прочитать {book} {chapter} 🙏")
                except:
                    pass
            await asyncio.sleep(60)
        await asyncio.sleep(30)


# === ЗАПУСК ===
async def main():
    await init_db()
    asyncio.create_task(reminders())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
