import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен бота (получите у @BotFather)
TOKEN = os.getenv('BOT_TOKEN')

# Инициализация
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()


# Создание базы данных
def init_db():
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  chat_id INTEGER,
                  text TEXT,
                  remind_time TIMESTAMP,
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()


init_db()


# Функция отправки напоминания
async def send_reminder(chat_id: int, text: str, reminder_id: int):
    try:
        await bot.send_message(
            chat_id,
            f"🔔 **НАПОМИНАНИЕ!** 🔔\n\n{text}",
            parse_mode="Markdown"
        )
        # Удаляем из базы после отправки
        conn = sqlite3.connect('reminders.db')
        c = conn.cursor()
        c.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")


# Загрузка сохраненных напоминаний при старте
async def load_reminders_from_db():
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("SELECT id, chat_id, text, remind_time FROM reminders")
    reminders = c.fetchall()
    conn.close()

    for reminder in reminders:
        reminder_id, chat_id, text, remind_time_str = reminder
        remind_time = datetime.fromisoformat(remind_time_str)

        if remind_time > datetime.now():
            scheduler.add_job(
                send_reminder,
                trigger=DateTrigger(run_date=remind_time),
                args=[chat_id, text, reminder_id],
                id=str(reminder_id)
            )
            logging.info(f"Загружено напоминание {reminder_id} на {remind_time}")


# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот-напоминальщик.\n\n"
        "📝 **Как пользоваться:**\n"
        "• Отправь мне дату и текст, и я напомню\n"
        "• Формат: `25.12.2024 15:30 Купить подарок`\n"
        "• /list - показать все напоминания\n"
        "• /cancel [ID] - отменить напоминание\n\n"
        "✨ **Примеры:**\n"
        "`завтра 09:00 Позвонить маме`\n"
        "`через 2 часа Выключить духовку`",
        parse_mode="Markdown"
    )


# Обработка текстовых сообщений (создание напоминания)
@dp.message()
async def create_reminder(message: Message):
    text = message.text

    # Простой парсинг (можно улучшить)
    try:
        if text.lower().startswith('завтра'):
            time_part = text[7:].strip().split(' ', 1)
            if len(time_part) == 2:
                time_str, reminder_text = time_part
                remind_time = datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)
                hour, minute = map(int, time_str.split(':'))
                remind_time = remind_time.replace(hour=hour, minute=minute)
            else:
                await message.answer("❌ Неправильный формат. Используй: `завтра 09:00 Текст`", parse_mode="Markdown")
                return

        elif text.lower().startswith('через'):
            # Парсинг "через X часов Y минут"
            parts = text[6:].strip().split(' ', 2)
            if len(parts) >= 2:
                delay_str = parts[0] + ' ' + parts[1]
                reminder_text = parts[2] if len(parts) > 2 else "Напоминание"

                # Простой парсинг времени (можно улучшить)
                hours = 0
                minutes = 0
                if 'час' in delay_str:
                    hours = int(delay_str.split('час')[0].strip())
                if 'мин' in delay_str:
                    minutes = int(delay_str.split('мин')[0].split()[-1])

                remind_time = datetime.now() + timedelta(hours=hours, minutes=minutes)
            else:
                await message.answer("❌ Неправильный формат. Используй: `через 2 часа 30 минут Текст`",
                                     parse_mode="Markdown")
                return
        else:
            # Формат: "ДД.ММ.ГГГГ ЧЧ:ММ Текст"
            parts = text.split(' ', 2)
            if len(parts) < 3:
                await message.answer("❌ Неправильный формат. Используй: `25.12.2024 15:30 Текст напоминания`")
                return

            date_str, time_str, reminder_text = parts
            day, month, year = map(int, date_str.split('.'))
            hour, minute = map(int, time_str.split(':'))
            remind_time = datetime(year, month, day, hour, minute)

        # Проверка на прошлое время
        if remind_time < datetime.now():
            await message.answer("❌ Нельзя создать напоминание в прошлом!")
            return

        # Сохраняем в БД
        conn = sqlite3.connect('reminders.db')
        c = conn.cursor()
        c.execute('''INSERT INTO reminders (user_id, chat_id, text, remind_time, created_at)
                     VALUES (?, ?, ?, ?, ?)''',
                  (message.from_user.id, message.chat.id, reminder_text,
                   remind_time.isoformat(), datetime.now().isoformat()))
        reminder_id = c.lastrowid
        conn.commit()
        conn.close()

        # Добавляем в планировщик
        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=remind_time),
            args=[message.chat.id, reminder_text, reminder_id],
            id=str(reminder_id)
        )

        await message.answer(
            f"✅ **Напоминание создано!**\n\n"
            f"📝 {reminder_text}\n"
            f"⏰ {remind_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"🆔 ID: `{reminder_id}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}\nПроверь формат ввода.")


# Команда /list - показать все напоминания
@dp.message(Command("list"))
async def list_reminders(message: Message):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute('''SELECT id, text, remind_time FROM reminders 
                 WHERE chat_id = ? ORDER BY remind_time''',
              (message.chat.id,))
    reminders = c.fetchall()
    conn.close()

    if not reminders:
        await message.answer("📭 У тебя нет активных напоминаний.")
        return

    text = "📋 **Твои напоминания:**\n\n"
    for r in reminders:
        remind_time = datetime.fromisoformat(r[2])
        text += f"🔹 `{r[0]}`: {r[1]}\n   ⏰ {remind_time.strftime('%d.%m.%Y %H:%M')}\n\n"

    await message.answer(text, parse_mode="Markdown")


# Команда /cancel - отменить напоминание
@dp.message(Command("cancel"))
async def cancel_reminder(message: Message):
    try:
        reminder_id = int(message.text.split()[1])

        # Удаляем из БД
        conn = sqlite3.connect('reminders.db')
        c = conn.cursor()
        c.execute("DELETE FROM reminders WHERE id = ? AND chat_id = ?",
                  (reminder_id, message.chat.id))
        deleted = c.rowcount
        conn.commit()
        conn.close()

        if deleted:
            # Удаляем из планировщика
            try:
                scheduler.remove_job(str(reminder_id))
            except:
                pass
            await message.answer(f"✅ Напоминание {reminder_id} отменено.")
        else:
            await message.answer("❌ Напоминание не найдено или принадлежит другому чату.")
    except (IndexError, ValueError):
        await message.answer("❌ Используй: `/cancel ID`", parse_mode="Markdown")


# Запуск бота
async def main():
    # Загружаем сохраненные напоминания
    await load_reminders_from_db()

    # Запускаем планировщик
    scheduler.start()

    # Запускаем бота
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())