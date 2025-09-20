from aiogram import types, Dispatcher
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
import re

from db import (
    delete_product,
    get_all_products,
    get_fridge_view,
    add_product_to_db,
    get_all_products_with_ids,
    delete_product_by_id,
    update_product_quantity_by_id,
    get_user_profile,
    update_user_allergies,
    update_user_dislikes,
    update_user_status,
    clear_user_allergies,
    clear_user_dislikes,
)

from gpt import suggest_recipe, filter_expired_batches_before_deduction

from datetime import datetime

# --- СТАНИ ---
class AddProductState(StatesGroup):
    waiting_for_product = State()

class PartialDeleteState(StatesGroup):
    waiting_for_quantity = State()

class ProfileState(StatesGroup):
    waiting_for_allergies = State()
    waiting_for_dislikes = State()

# --- КНОПКИ ---
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📋 Холодильник", callback_data="fridge")]
    ])

def back_to_delete_list_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔙 Назад до списку продуктів", callback_data="delete_product")],
        [InlineKeyboardButton("📋 Холодильник", callback_data="fridge")]
    ])

def cancel_keyboard(from_profile: bool = False):
    target = "back_to_menu" if from_profile else "fridge"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("❌ Скасувати", callback_data=f"cancel_{target}")]
    ])

# --- ГОЛОВНЕ МЕНЮ ХОЛОДИЛЬНИКА ---
async def handle_main_menu_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    fridge_contents = await get_fridge_view(callback_query.from_user.id)
    await callback_query.message.answer(fridge_contents)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🟩 Додати продукт", callback_data="add_product")],
        [InlineKeyboardButton("🟥 Видалити продукт", callback_data="delete_product")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
    ])
    await callback_query.message.answer("Обери дію:", reply_markup=keyboard)

# --- ВСЕРЕДИНІ ХОЛОДИЛЬНИКА ---
async def handle_fridge_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    action = callback_query.data
    user_id = callback_query.from_user.id

    if action == "add_product":
        await callback_query.message.answer(
            "🧾 Введи продукт у форматі:\nНазва Кількість Одиниця Термін (дд.мм.рррр)\nНаприклад: яйця 10 шт 25.07.2025",
            reply_markup=cancel_keyboard()
        )
        await AddProductState.waiting_for_product.set()

    elif action == "delete_product":
        products = await get_all_products_with_ids(user_id)
        if not products:
            await callback_query.message.answer("❌ У холодильнику немає продуктів для видалення.", reply_markup=main_menu_keyboard())
            return

        keyboard = InlineKeyboardMarkup(row_width=1)
        for prod_id, name, quantity, unit, expiry in products:
            keyboard.add(InlineKeyboardButton(f"{name} ({quantity} {unit}) – {expiry}", callback_data=f"del_{prod_id}"))
        keyboard.add(InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu"))
        await callback_query.message.answer("Оберіть продукт для видалення:", reply_markup=keyboard)

    elif action.startswith("del_") and action.count("_") == 1:
        product_id = int(action.replace("del_", ""))
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton("❌ Видалити повністю", callback_data=f"del_full_{product_id}"),
                InlineKeyboardButton("➖ Видалити частково", callback_data=f"del_partial_{product_id}")
            ]
        ])
        await callback_query.message.answer("Оберіть тип видалення:", reply_markup=keyboard)

    elif action == "back_to_menu":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("📋 Холодильник", callback_data="fridge")],
            [InlineKeyboardButton("🍽 Страва дня", callback_data="daily_dish")],
            [InlineKeyboardButton("📅 Тижневе меню", callback_data="weekly_menu")],
            [InlineKeyboardButton("👤 Профіль", callback_data="profile")]
        ])
        await callback_query.message.answer("🏠 Головне меню:", reply_markup=keyboard)

# --- ОБРОБКА ВИДАЛЕННЯ ---
async def handle_delete_choice(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    action = callback_query.data

    if action.startswith("del_full_"):
        product_id = int(action.replace("del_full_", ""))
        await delete_product_by_id(product_id)
        await callback_query.message.answer("🗑️ Продукт повністю видалено.", reply_markup=back_to_delete_list_keyboard())

    elif action.startswith("del_partial_"):
        product_id = int(action.replace("del_partial_", ""))
        await state.update_data(product_id=product_id)
        await callback_query.message.answer("✂️ Введи кількість, яку хочеш видалити (наприклад: 1 або 250):", reply_markup=cancel_keyboard())
        await PartialDeleteState.waiting_for_quantity.set()

# --- ОБРОБКА КІЛЬКОСТІ ДЛЯ ЧАСТКОВОГО ВИДАЛЕННЯ ---
async def handle_partial_quantity_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("product_id")

    match = re.search(r"\d+([.,]\d+)?", message.text)
    if not match:
        await message.answer("❗ Будь ласка, введи коректну кількість (наприклад: 1 або 1.5)", reply_markup=main_menu_keyboard())
        return

    try:
        amount = float(match.group().replace(",", "."))
    except ValueError:
        await message.answer("❗ Не вдалося розпізнати число.", reply_markup=main_menu_keyboard())
        return

    if amount <= 0:
        await message.answer("❗ Кількість має бути більше нуля.", reply_markup=main_menu_keyboard())
        return

    products = await get_all_products_with_ids(message.from_user.id)
    product = next((p for p in products if p[0] == product_id), None)

    if not product:
        await message.answer("❌ Продукт не знайдено.", reply_markup=main_menu_keyboard())
        return

    _, name, old_quantity, unit, _ = product
    new_quantity = old_quantity - amount

    if new_quantity < 0:
        await message.answer(f"❗ У тебе лише {old_quantity} {unit}. Повернись назад та введи менше.", reply_markup=back_to_delete_list_keyboard())
    elif new_quantity == 0:
        await delete_product_by_id(product_id)
        await message.answer(f"✅ Продукт {name} повністю видалено.", reply_markup=back_to_delete_list_keyboard())
    else:
        await update_product_quantity_by_id(product_id, new_quantity)
        await message.answer(f"🔄 Залишилось {new_quantity} {unit} продукту {name}.", reply_markup=back_to_delete_list_keyboard())

    await state.finish()

# --- ОБРОБКА ВВОДУ ПРОДУКТІВ ---
async def handle_product_input(message: types.Message, state: FSMContext):
    await add_product_to_db(user_id=message.from_user.id, text=message.text)
    await message.reply("✅ Продукт(и) додано до холодильника!", reply_markup=main_menu_keyboard())
    await state.finish()

# --- ОБРОБКА КНОПКИ "СТРАВА ДНЯ" ---
async def handle_daily_dish(callback_query: types.CallbackQuery):
    await callback_query.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🍳 Сніданок", callback_data="daily_dish_breakfast")],
        [InlineKeyboardButton("🍝 Обід", callback_data="daily_dish_lunch")],
        [InlineKeyboardButton("🍲 Вечеря", callback_data="daily_dish_dinner")],
        [InlineKeyboardButton("🍩 Перекус", callback_data="daily_dish_snack")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
    ])
    await callback_query.message.answer("Оберіть тип прийому їжі:", reply_markup=keyboard)

# --- ОБРОБКА ВИБОРУ ТИПУ ПРИЙОМУ ЇЖІ ---
async def handle_meal_type_selection(callback_query: types.CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    meal_type = callback_query.data.replace("daily_dish_", "")  # breakfast / lunch / dinner / snack
    print(f"🍽️ CALLBACK: daily_dish → {meal_type}")

    await callback_query.message.answer("⏳ Генерую страву...")
    recipe = await suggest_recipe(user_id, meal_type)

    # --- Якщо немає доступних продуктів для генерації ---
    if recipe.startswith("❌ Усі продукти в холодильнику"):
        await callback_query.message.answer(
            "🚫 Не вдалося згенерувати страву, бо у холодильнику немає жодного продукту, який можна використати.\n"
            "Можливо, всі вони прострочені або входять до списку алергенів/нелюбимих.\n\n"
            "🧾 Додай нові продукти або зміни профіль, щоб отримати рецепти.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("📋 Холодильник", callback_data="fridge")],
                [InlineKeyboardButton("👤 Профіль", callback_data="profile")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )
        return

    # --- Перевірка структури рецепту ---
    if "Інгредієнти:" not in recipe:
        print("⚠️ Структура рецепту не відповідає очікуваному формату!")
        await callback_query.message.answer(
            "⚠️ Виникла помилка при генерації страви. Спробуй ще раз або натисни 🔁 Інша спроба.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("🔁 Інша спроба", callback_data=f"daily_dish_{meal_type}")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )
        return

    # --- Збереження інгредієнтів для списання ---
    global last_generated_ingredients
    last_generated_ingredients = {}

    try:
        ingredients_block = recipe.split("Інгредієнти:")[1].split("🔷")[0]
        lines = ingredients_block.strip().split("\n")
        for line in lines:
            if "-" not in line:
                continue
            parts = line.strip("- ").rsplit(",", 1)
            if len(parts) != 2:
                continue
            name = parts[0].strip().lower()
            quantity_unit = parts[1].strip()
            match = re.match(r"([\d.,]+)\s*(\w+)", quantity_unit)
            if match:
                quantity = float(match.group(1).replace(",", "."))
                unit = match.group(2)
                last_generated_ingredients[(name, unit)] = quantity
    except Exception as e:
        print("❌ Парсинг інгредієнтів не вдався:", e)
        await callback_query.message.answer(
            "⚠️ Не вдалося розпізнати інгредієнти. Спробуй ще раз або вибери іншу страву.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton("🔁 Інша спроба", callback_data=f"daily_dish_{meal_type}")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )
        return

    # --- Вивід рецепту з кнопками ---
    await callback_query.message.answer(recipe, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✅ Готую це!", callback_data="cook_confirm")],
        [InlineKeyboardButton("🔁 Інша страва", callback_data=f"daily_dish_{meal_type}")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
    ]))
    
# --- ОБРОБКА ПІДТВЕРДЖЕННЯ ГОТУВАННЯ ---
from datetime import datetime
from db import get_all_products_with_ids, update_product_quantity_by_id, delete_product_by_id
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# продукт_назва → (кількість, одиниця)
last_generated_ingredients = {}

async def handle_cook_confirm(callback_query: types.CallbackQuery):
    await callback_query.answer("🍳 Готуємо страву...")
    user_id = callback_query.from_user.id

    # Отримуємо продукти користувача
    fridge = await get_all_products_with_ids(user_id)

    # Групуємо по (назва, одиниця)
    fridge_dict = {}
    for prod_id, name, quantity, unit, expiry in fridge:
        key = (name.lower(), unit)
        expiry_date_obj = datetime.strptime(expiry, "%d.%m.%Y")
        fridge_dict.setdefault(key, []).append((prod_id, quantity, expiry_date_obj))

    print("📦 Списання продуктів:")
    for (ingredient, unit), needed_qty in last_generated_ingredients.items():
        key = (ingredient.lower(), unit)
        batches = fridge_dict.get(key, [])

        # ❗ Виключаємо прострочені партії
        batches = filter_expired_batches_before_deduction(batches)
        if not batches:
            print(f"⚠️ {ingredient} ({unit}) — всі партії прострочені або відсутні.")
            continue

        # Сортуємо партії за терміном придатності — від найстаршого
        batches.sort(key=lambda x: x[2])

        print(f"🔸 {ingredient} ({unit}) — потрібно {needed_qty}")

        for prod_id, available_qty, expiry_date in batches:
            if needed_qty <= 0:
                break
            used_qty = min(available_qty, needed_qty)
            needed_qty -= used_qty
            remaining = round(available_qty - used_qty, 3)

            print(f"  🧾 Партія до {expiry_date.strftime('%d.%m.%Y')}: було {available_qty}, списано {used_qty}, залишилось {remaining}")

            if remaining > 0:
                await update_product_quantity_by_id(prod_id, remaining)
            else:
                await delete_product_by_id(prod_id)

    await callback_query.message.answer("✅ Холодильник оновлено після приготування страви.")

# --- Вивід профілю ---
async def handle_profile_callback(callback_query: types.CallbackQuery):
    await callback_query.answer()
    user_id = callback_query.from_user.id
    profile = await get_user_profile(user_id)

    allergies = profile.get("allergies", "") or "не вказано"
    dislikes = profile.get("dislikes", "") or "не вказано"
    status = profile.get("status", "") or "звичайний"

    text = (
        "👤 Твій профіль:\n"
        f"• 🤧 Алергії: {allergies}\n"
        f"• 🙅‍♂️ Не люблю: {dislikes}\n"
        f"• 🌱 Статус: {status}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✏️ Змінити алергії", callback_data="edit_allergies")],
        [InlineKeyboardButton("🗑 Очистити алергії", callback_data="clear_allergies")],
        [InlineKeyboardButton("✏️ Змінити 'Не люблю'", callback_data="edit_dislikes")],
        [InlineKeyboardButton("🗑 Очистити 'Не люблю'", callback_data="clear_dislikes")],
        [InlineKeyboardButton("🌿 Вегетаріанець", callback_data="set_status_vegetarian")],
        [InlineKeyboardButton("🌱 Веган", callback_data="set_status_vegan")],
        [InlineKeyboardButton("🔄 Скинути статус", callback_data="set_status_none")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
    ])
    await callback_query.message.answer(text, reply_markup=keyboard)

# --- Обробка кнопок профілю ---
async def handle_profile_buttons(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    action = callback_query.data
    user_id = callback_query.from_user.id

    if action == "edit_allergies":
        await callback_query.message.answer("🤧 Введи алергії (через кому):", reply_markup=cancel_keyboard(from_profile=True))
        await ProfileState.waiting_for_allergies.set()

    elif action == "edit_dislikes":
        await callback_query.message.answer("🙅‍♂️ Введи продукти, які не любиш (через кому):", reply_markup=cancel_keyboard(from_profile=True))
        await ProfileState.waiting_for_dislikes.set()

    elif action == "set_status_vegan":
        await update_user_status(user_id, "веган")
        await callback_query.message.answer("🌿 Статус оновлено на: веган")
        await handle_profile_callback(callback_query)

    elif action == "set_status_vegetarian":
        await update_user_status(user_id, "вегетаріанець")
        await callback_query.message.answer("🥕 Статус оновлено на: вегетаріанець")
        await handle_profile_callback(callback_query)

    elif action == "set_status_none":
        await update_user_status(user_id, "")
        await callback_query.message.answer("🔄 Статус скинуто до звичайного")
        await handle_profile_callback(callback_query)

    elif action == "clear_allergies":
        await clear_user_allergies(user_id)
        await callback_query.message.answer("🧽 Алергії очищено.")
        await handle_profile_callback(callback_query)

    elif action == "clear_dislikes":
        await clear_user_dislikes(user_id)
        await callback_query.message.answer("🧽 'Не люблю' очищено.")
        await handle_profile_callback(callback_query)

# --- Обробка текстового вводу ---

async def handle_profile_text_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    current_state = await state.get_state()

    if current_state == ProfileState.waiting_for_allergies.state:
        await update_user_allergies(user_id, message.text.strip())
        await message.answer("✅ Алергії оновлено!")

    elif current_state == ProfileState.waiting_for_dislikes.state:
        await update_user_dislikes(user_id, message.text.strip())
        await message.answer("✅ Список 'Не люблю' оновлено!")

    await state.finish()

    # Повернення до профілю після оновлення
    profile = await get_user_profile(user_id)

    allergies = profile.get("allergies", "") or "не вказано"
    dislikes = profile.get("dislikes", "") or "не вказано"
    status = profile.get("status", "") or "звичайний"

    text = (
        "👤 Твій профіль:\n"
        f"• 🤧 Алергії: {allergies}\n"
        f"• 🙅‍♂️ Не люблю: {dislikes}\n"
        f"• 🌱 Статус: {status}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✏️ Змінити алергії", callback_data="edit_allergies")],
        [InlineKeyboardButton("🗑 Очистити алергії", callback_data="clear_allergies")],
        [InlineKeyboardButton("✏️ Змінити 'Не люблю'", callback_data="edit_dislikes")],
        [InlineKeyboardButton("🗑 Очистити 'Не люблю'", callback_data="clear_dislikes")],
        [InlineKeyboardButton("🌿 Вегетаріанець", callback_data="set_status_vegetarian")],
        [InlineKeyboardButton("🌱 Веган", callback_data="set_status_vegan")],
        [InlineKeyboardButton("🔄 Скинути статус", callback_data="set_status_none")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
    ])

    await message.answer(text, reply_markup=keyboard)
    
# --- Заглушка: Тижневе меню ---
async def handle_weekly_menu_placeholder(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.answer("📅 Ця функція ще в розробці. Скоро зʼявиться можливість планувати меню на тиждень!")

# --- Заглушка: Допомога / Про бота ---
async def handle_help_placeholder(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.answer(
        "ℹ️ Я — кулінарний бот, що допомагає готувати страви з того, що є у твоєму холодильнику.\n"
        "Мої можливості постійно оновлюються. Незабаром тут буде повна інструкція та FAQ. Смачного! 🍽"
    )

# --- КНОПКА СКАСУВАННЯ ---
async def handle_cancel(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer("❌ Дію скасовано.")
    await state.finish()
    target = callback_query.data.replace("cancel_", "")
    if target == "fridge":
        await handle_main_menu_callback(callback_query)
    elif target == "back_to_menu":
        await callback_query.message.answer("✅ Повернулись у головне меню.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("📋 Холодильник", callback_data="fridge")],
            [InlineKeyboardButton("🍽 Страва дня", callback_data="daily_dish")],
            [InlineKeyboardButton("📅 Тижневе меню", callback_data="weekly_menu")],
            [InlineKeyboardButton("👤 Профіль", callback_data="profile")]
        ]))

# --- РЕЄСТРАЦІЯ ---
def register_callback_handlers(dp: Dispatcher):
    # Холодильник
    dp.register_callback_query_handler(handle_main_menu_callback, lambda c: c.data == "fridge")
    dp.register_callback_query_handler(handle_cancel, lambda c: c.data.startswith("cancel_"), state="*")
    dp.register_callback_query_handler(handle_delete_choice, lambda c: c.data.startswith("del_full_") or c.data.startswith("del_partial_"))
    dp.register_callback_query_handler(handle_fridge_callback, lambda c: c.data.startswith("del_") or c.data in [
        "add_product", "delete_product", "back_to_menu"
    ])
    dp.register_message_handler(handle_product_input, state=AddProductState.waiting_for_product)
    dp.register_message_handler(handle_partial_quantity_input, state=PartialDeleteState.waiting_for_quantity)

    # Страва дня
    dp.register_callback_query_handler(handle_daily_dish, lambda c: c.data == "daily_dish")
    dp.register_callback_query_handler(handle_meal_type_selection, lambda c: c.data.startswith("daily_dish_"))
    dp.register_callback_query_handler(handle_cook_confirm, lambda c: c.data == "cook_confirm")  # ✅ Готую це!
    # Заглушки
    dp.register_callback_query_handler(handle_weekly_menu_placeholder, lambda c: c.data == "weekly_menu")
    dp.register_callback_query_handler(handle_help_placeholder, lambda c: c.data == "help")

    # Профіль
    dp.register_callback_query_handler(handle_profile_callback, lambda c: c.data == "profile")
    dp.register_callback_query_handler(
        handle_profile_buttons,
        lambda c: c.data.startswith("edit_") or c.data.startswith("set_status") or c.data.startswith("clear_")
    )
    dp.register_message_handler(handle_profile_text_input, state=ProfileState.waiting_for_allergies)
    dp.register_message_handler(handle_profile_text_input, state=ProfileState.waiting_for_dislikes)
