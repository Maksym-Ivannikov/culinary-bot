from dotenv import load_dotenv
load_dotenv()

import os
import re
from datetime import datetime, timedelta, date
from typing import List, Tuple, Optional
from openai import AsyncOpenAI
from db import get_all_products_with_expiry, get_user_profile

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASIC_INGREDIENTS = [
    "сіль", "перець", "цукор", "борошно", "сода", "розпушувач", "оцет",
    "олія", "вершкове масло", "рослинне масло", "мед", "вода",
    "спеції", "часник сушений", "цибуля сушена", "паприка", "лавровий лист",
    "кориця", "імбир", "ваніль",
    "хліб", "батон", "сухарі", "гірчиця", "соєвий соус", "томатна паста", "кетчуп", "майонез",
    "крохмаль"
]
last_generated_ingredients = {}

def _parse_ddmmyyyy(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d, "%d.%m.%Y").date()
    except Exception:
        return None

async def suggest_recipe(user_id: int, meal_type: str) -> str:
    global last_generated_ingredients
    last_generated_ingredients.clear()

    products: List[Tuple[str, int, str, Optional[str]]] = await get_all_products_with_expiry(user_id)
    profile = await get_user_profile(user_id)

    if not products:
        return (
            "😕 У тебе зараз порожній холодильник. "
            "Додай кілька продуктів, щоб я міг запропонувати щось смачне!"
        )

    # Обробка профілю
    allergies = [x.strip().lower() for x in (profile.get("allergies") or "").split(",") if x.strip()]
    dislikes = [x.strip().lower() for x in (profile.get("dislikes") or "").split(",") if x.strip()]
    status = (profile.get("status") or "").strip().lower()

    today = datetime.today().date()
    tomorrow = today + timedelta(days=1)

    # Визначаємо пріоритетні продукти (термін до завтра)
    priority_products = []
    other_products = []

    for name, quantity, unit, expiry_str in products:
        name_lower = name.lower()
        if any(a in name_lower for a in allergies + dislikes):
            continue

        expiry_date = _parse_ddmmyyyy(expiry_str) if expiry_str else None

        # ігноруємо прострочені, інші беремо, у т.ч. без дати
        if expiry_date is not None and expiry_date < today:
            continue

        item_str = f"{name} {quantity} {unit}"
        if expiry_date is not None and expiry_date <= tomorrow:
            priority_products.append(item_str)
        else:
            other_products.append(item_str)

    if not (priority_products or other_products):
        return (
            "❌ Усі продукти в холодильнику входять до списку алергенів, нелюбимих або з вичерпаним терміном. "
            "Будь ласка, онови профіль або додай нові продукти."
        )

    filtered_products = priority_products + other_products
    available_ingredients = ", ".join(filtered_products)

    meal_names = {
        "breakfast": "сніданок",
        "lunch": "обід",
        "dinner": "вечерю",
        "snack": "перекус"
    }

    profile_note = ""
    if status == "веган":
        profile_note = "Користувач є веганом. Не включай жодних продуктів тваринного походження."
    elif status == "вегетаріанець":
        profile_note = "Користувач є вегетаріанцем. Не включай мʼяса, риби та морепродуктів."

    if allergies:
        profile_note += f"\nНе включай продукти: {', '.join(allergies)} — на них у користувача алергія."
    if dislikes:
        profile_note += f"\nНе включай продукти: {', '.join(dislikes)} — користувач їх не любить."

    prompt = (
        f"Ти кулінарний помічник. "
        f"Склади один рецепт для {meal_names.get(meal_type, 'прийому їжі')} з продуктів, які є в холодильнику користувача.\n\n"
        f"Ось список продуктів у холодильнику: {available_ingredients}.\n\n"
        f"{profile_note.strip()}\n\n"
        f"❗ Важливо:\n"
        f"- Не вигадуй продуктів, яких немає в цьому списку.\n"
        f"- Але можеш вільно використовувати базові інгредієнти: {', '.join(BASIC_INGREDIENTS)} — навіть якщо їх немає в холодильнику.\n"
        f"- Не змінюй назви продуктів! Якщо в списку є 'тестовий сир', використовуй саме таку назву. У блоці Інгредієнти: не змінюй назви продуктів. Навіть якщо назва виглядає як з помилкою — використовуй її в точності так, як у списку. Це важливо для коректного оновлення залишків у холодильнику.\n"
        f"- Не змінюй форму слова (однина/множина). Якщо у списку є 'Яйця', не пиши 'Яйце', і навпаки.\n"
        f"- Назви, кількість та одиниці виміру мають бути такими ж, як у списку інгредієнтів.\n"
        f"- Одиниця виміру має бути в точності такою, як у списку. Не замінюй 'шт' на 'кришки', 'г' на 'грами' тощо.\n"
        f"- Не змінюй масштаб одиниці виміру. Якщо в списку 'л', не використовуй 'мл'. Якщо 'кг', не пиши 'г'. Якщо потрібно — використовуй дробові значення, наприклад 0.1 л.\n"
        f"- Назви інгредієнтів повинні бути в точності такими ж, щоб бот міг оновити залишки у холодильнику.\n\n"
        f"📋 Формат відповіді (дотримуйся точно!):\n"
        f"1. 🔶 Назва страви (на окремому рядку)\n"
        f"2. Обов’язковий підзаголовок **Інгредієнти:** (саме так, з двокрапкою)\n"
        f"- Назва, Кількість Одиниця\n"
        f"- Назва, Кількість Одиниця\n"
        f"3. Обов’язковий підзаголовок **🔷 Рецепт:** (саме так, з іконкою та двокрапкою)\n"
        f"1. Крок 1\n"
        f"2. Крок 2\n"
        f"...\n"
        f"❗ Без жодних побажань, коментарів, пояснень. Лише чіткий рецепт у вказаному форматі."
    )

    print("PROMPT:\n", prompt)

    try:
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Ти кулінарний помічник."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=700,
            temperature=0.6
        )

        content = response.choices[0].message.content
        print("GPT RESPONSE:\n", content)

        if "Інгредієнти:" not in content or "🔷 Рецепт:" not in content:
            return "⚠️ Структура рецепту не відповідає очікуваному формату! Спробуй згенерувати інший рецепт."

        last_generated_ingredients = extract_ingredients(content)
        return content

    except Exception as e:
        print("GPT Error:", e)
        return "❌ Не вдалося згенерувати страву. Спробуй ще раз пізніше."


def extract_ingredients(text: str) -> dict:
    ingredients = {}
    match = re.search(r"Інгредієнти:(.*?)🔷 Рецепт:", text, re.DOTALL)
    if not match:
        return {}

    block = match.group(1)
    lines = block.strip().split("\n")
    for line in lines:
        if line.startswith("- "):
            line = line[2:]
        parts = line.strip().split(", ")
        if len(parts) != 2:
            continue
        name = parts[0].strip().lower()
        qty_unit = parts[1].strip().split(" ", 1)
        if len(qty_unit) != 2:
            continue
        try:
            quantity = float(qty_unit[0].replace(",", "."))
        except ValueError:
            continue
        unit = qty_unit[1]
        ingredients[(name, unit)] = quantity
    return ingredients


def filter_expired_batches_before_deduction(
    product_batches: List[Tuple[int, float, Optional[datetime]]]
) -> List[Tuple[int, float, Optional[datetime]]]:
    """Повертає лише не прострочені партії. None (без терміну) вважаємо придатними."""
    today = datetime.today().date()
    kept = []
    for batch in product_batches:
        exp_dt = batch[2]
        if exp_dt is None:
            kept.append(batch)
        else:
            try:
                if exp_dt.date() >= today:
                    kept.append(batch)
            except Exception:
                # якщо дата зіпсована — перестраховка: відкидаємо
                pass
    return kept