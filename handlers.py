from aiogram import Dispatcher, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from gpt import suggest_recipe
from db import add_product_to_db

# 🔘 Постійна клавіатура з однією кнопкою "/start"
start_reply_keyboard = ReplyKeyboardMarkup(
    resize_keyboard=True,
    keyboard=[[KeyboardButton("/start")]]
)

# Головне меню
async def cmd_start(message: types.Message):
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📋 Холодильник", callback_data="fridge")],
        [InlineKeyboardButton("🍽 Страва дня", callback_data="daily_dish")],
        [InlineKeyboardButton("📅 Тижневе меню", callback_data="weekly_menu")],
        [InlineKeyboardButton("👤 Профіль", callback_data="profile")],
        [InlineKeyboardButton("ℹ️ Допомога / Про бота", callback_data="help")],
        [InlineKeyboardButton("📝 Пропозиції та ідеї", callback_data="feedback")]  # 🔥 нова кнопка
    ])

    await message.answer(
        "👋 Привіт! Обери, що хочеш зробити:",
        reply_markup=inline_kb
    )

    # Окремим повідомленням скидаємо стару клаву та показуємо лише /start
    await message.answer(
        "📲 Якщо хочеш повернутись у головне меню — натисни /start.",
        reply_markup=start_reply_keyboard
    )

# Альтернативне додавання продукту
async def cmd_add(message: types.Message):
    args = message.get_args()
    if not args:
        await message.reply(
            "❗️ Введи продукт після команди /add, наприклад:\n"
            "/add помідори чері 300 г 14.07.2025, яйця 6 шт\n\n"
            "• Назва може містити ПРОБІЛИ\n"
            "• Кількість і одиниця — обовʼязково\n"
            "• Термін придатності у форматі дд.мм.рррр — опційно"
        )
        return
    await add_product_to_db(user_id=message.from_user.id, text=args)
    await message.reply(f"✅ Додав продукт(и): {args}")

# Страва дня (через команду, необов’язково)
async def cmd_menu(message: types.Message):
    response = await suggest_recipe(user_id=message.from_user.id, meal_type="lunch")
    await message.reply(response)

# Реєстрація хендлерів
def register_handlers(dp: Dispatcher):
    dp.register_message_handler(cmd_start, commands="start")
    dp.register_message_handler(cmd_add, commands="add")
    dp.register_message_handler(cmd_menu, commands="menu")