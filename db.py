import os
print("📢 Використовується база:", os.path.abspath("products.db"))

import sqlite3
from datetime import datetime
from typing import List, Tuple

def init_db():
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    # Таблиця продуктів
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            quantity INTEGER,
            unit TEXT,
            expiry_date TEXT
        )
    """)

    # Таблиця профілю користувача
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            user_id INTEGER PRIMARY KEY,
            allergies TEXT,
            dislikes TEXT,
            status TEXT
        )
    """)

    conn.commit()
    conn.close()

def normalize_name(name: str) -> str:
    name = name.lower()
    synonyms = {
        "помідор": "томат",
        "помідори": "томат",
        "огірки": "огірок",
        "огурець": "огірок",
        "яйце": "яйця"
    }
    return synonyms.get(name, name)

# --- Продукти ---

async def add_product_to_db(user_id: int, text: str):
    products = text.split(",")
    parsed = []

    for product in products:
        parts = product.strip().split(" ")
        if len(parts) < 4:
            continue
        name = normalize_name(parts[0])
        try:
            quantity = int(parts[1])
        except ValueError:
            continue
        unit = parts[2]
        expiry_date = parts[3]

        try:
            datetime.strptime(expiry_date, "%d.%m.%Y")
        except ValueError:
            continue

        parsed.append((user_id, name, quantity, unit, expiry_date))
    print("🔍 Отримано продукти:", products)
    print("✅ Parsed продукти:", parsed)
    if not parsed:
        return

    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    for entry in parsed:
        uid, name, qty, unit, expiry = entry
        # Перевірка чи є такий самий продукт з тим же терміном
        cursor.execute("""
            SELECT id, quantity FROM products
            WHERE user_id = ? AND name = ? AND unit = ? AND expiry_date = ?
        """, (uid, name, unit, expiry))
        row = cursor.fetchone()
        if row:
            existing_id, existing_qty = row
            new_qty = existing_qty + qty
            cursor.execute("""
                UPDATE products SET quantity = ? WHERE id = ?
            """, (new_qty, existing_id))
        else:
            cursor.execute("""
                INSERT INTO products (user_id, name, quantity, unit, expiry_date)
                VALUES (?, ?, ?, ?, ?)
            """, entry)

    conn.commit()
    conn.close()

async def get_all_products(user_id: int) -> List[str]:
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [f"{name} ({quantity} {unit}) – до {expiry}" for name, quantity, unit, expiry in rows]

async def get_all_products_with_expiry(user_id: int) -> List[Tuple[str, int, str, str]]:
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

async def get_all_products_grouped_by_user() -> dict:
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, expiry_date FROM products")
    rows = cursor.fetchall()
    conn.close()

    users = {}
    for user_id, name, expiry in rows:
        users.setdefault(user_id, []).append((name, expiry))
    return users

async def get_all_products_with_ids(user_id: int) -> List[Tuple[int, str, int, str, str]]:
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

async def delete_product_by_id(product_id: int):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

async def delete_product(user_id: int, name: str):
    name = normalize_name(name)
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE user_id = ? AND name = ?", (user_id, name))
    conn.commit()
    conn.close()

async def update_product_quantity_by_id(product_id: int, new_quantity: float):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_quantity, product_id))
    conn.commit()
    conn.close()

async def get_expiring_products(user_id: int, days_threshold: int = 2) -> List[str]:
    today = datetime.now()
    result = []

    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    for name, quantity, unit, expiry_date in rows:
        try:
            expiry = datetime.strptime(expiry_date, "%d.%m.%Y")
            delta = (expiry - today).days
            if delta <= days_threshold:
                result.append(f"{name} ({quantity} {unit}) – термін до {expiry_date}")
        except ValueError:
            continue

    return result

async def get_fridge_view(user_id: int) -> str:
    products = await get_all_products(user_id)
    if not products:
        return "❌ У холодильнику поки порожньо."
    return "🧊 Вміст холодильника:\n" + "\n".join(products)

# --- Профіль користувача ---

async def get_user_profile(user_id: int) -> dict:
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT allergies, dislikes, status FROM profile WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "allergies": row[0] or "",
            "dislikes": row[1] or "",
            "status": row[2] or ""
        }
    else:
        return {
            "allergies": "",
            "dislikes": "",
            "status": ""
        }

async def update_user_allergies(user_id: int, new_allergies: str):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    # Отримуємо поточні алергії
    cursor.execute("SELECT allergies FROM profile WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current = set()
    if row and row[0]:
        current = set(a.strip() for a in row[0].split(",") if a.strip())

    # Додаємо нові
    additions = set(a.strip() for a in new_allergies.split(",") if a.strip())
    updated = current.union(additions)
    final = ", ".join(sorted(updated))

    # Зберігаємо
    cursor.execute("""
        INSERT INTO profile (user_id, allergies) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET allergies=excluded.allergies
    """, (user_id, final))
    conn.commit()
    conn.close()


async def update_user_dislikes(user_id: int, new_dislikes: str):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    # Отримуємо поточні dislike-и
    cursor.execute("SELECT dislikes FROM profile WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current = set()
    if row and row[0]:
        current = set(d.strip() for d in row[0].split(",") if d.strip())

    # Додаємо нові
    additions = set(d.strip() for d in new_dislikes.split(",") if d.strip())
    updated = current.union(additions)
    final = ", ".join(sorted(updated))

    # Зберігаємо
    cursor.execute("""
        INSERT INTO profile (user_id, dislikes) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET dislikes=excluded.dislikes
    """, (user_id, final))
    conn.commit()
    conn.close()

async def update_user_status(user_id: int, status: str):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO profile (user_id, status) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET status=excluded.status
    """, (user_id, status))
    conn.commit()
    conn.close()
    
async def clear_user_allergies(user_id: int):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE profile SET allergies = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


async def clear_user_dislikes(user_id: int):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE profile SET dislikes = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

