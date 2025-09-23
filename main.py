from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from dotenv import load_dotenv
import aiocron
from datetime import datetime
import os

from handlers import register_handlers
from db import init_db, get_all_products_grouped_by_user
from callback_handlers import register_callback_handlers

load_dotenv()

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN"))
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# читаємо ID каналу для фідбеку
FEEDBACK_CHAT_ID = os.getenv("FEEDBACK_CHAT_ID")

# Ініціалізація БД при старті
init_db()

# Реєстрація хендлерів
register_handlers(dp)
register_callback_handlers(dp, bot, FEEDBACK_CHAT_ID)

@aiocron.crontab('0 9 * * *')  # Щодня о 09:00
async def daily_expiry_check():
    print("⏰ Запуск щоденної перевірки терміну придатності")
    users_products = await get_all_products_grouped_by_user()
    today_str = datetime.today().strftime("%d.%m.%Y")

    for user_id, products in users_products.items():
        expiring = []
        for name, date_str in products:
            if not date_str:
                continue
            if date_str == today_str:
                expiring.append(f"{name} (до {date_str})")

        if expiring:
            text = (
                "🔔 Продукти, у яких сьогодні спливає термін придатності:\n"
                + "\n".join(expiring)
                + "\n\nСпробуй приготувати щось із них або з’їсти сьогодні 🧑‍🍳🥗"
            )
            await bot.send_message(user_id, text)

@aiocron.crontab('0 9 * * 6')  # Щосуботи о 9:00
async def weekly_expired_check():
    print("🔁 Щотижнева перевірка прострочених продуктів")
    users_products = await get_all_products_grouped_by_user()
    today = datetime.today()

    for user_id, products in users_products.items():
        expired = []
        for name, date_str in products:
            if not date_str:
                continue
            try:
                exp = datetime.strptime(date_str, "%d.%m.%Y")
            except ValueError:
                continue
            if exp < today:
                expired.append(f"{name} (до {date_str})")

        if expired:
            text = (
                "❗ У тебе є продукти з простроченим терміном придатності:\n"
                + "\n".join(expired)
                + "\n\nРекомендуємо видалити їх з бота та з холодильника 🗑"
            )
            await bot.send_message(user_id, text)

if __name__ == "__main__":
    print("🛠 Бот запускається...")
    executor.start_polling(dp, skip_updates=True)