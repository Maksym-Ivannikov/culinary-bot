import os
import sqlite3
import re
from datetime import datetime
from typing import List, Tuple, Optional

# ====== Налаштування шляху до БД ======
# Підтримуємо обидві змінні на всякий випадок:
DB_PATH = os.getenv("PRODUCTS_DB_PATH") or os.getenv("DB_PATH") or "products.db"

# створимо папку, якщо це щось типу /data/products.db
db_dir = os.path.dirname(DB_PATH)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

print("📢 Використовується база:", os.path.abspath(DB_PATH))

def _connect():
    # окремий хелпер щоб не повторюватись
    return sqlite3.connect(DB_PATH)

# ====== Ініціалізація ======
def init_db():
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            quantity REAL,
            unit TEXT,
            expiry_date TEXT NULL
        )
    """)

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

# --- Допоміжні парсери ---

DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")

def _extract_optional_date(s: str) -> tuple[str, Optional[str]]:
    m = DATE_RE.search(s)
    if not m:
        return s.strip(), None
    date_str = m.group(0)
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        return s.strip(), None
    s_wo = (s[:m.start()] + s[m.end():]).strip()
    s_wo = re.sub(r"[\(\)\-–—]*\s*$", "", s_wo).strip()
    s_wo = re.sub(r"\s{2,}", " ", s_wo)
    return s_wo, date_str

def _parse_one_item(raw: str) -> Optional[tuple[str, float, str, Optional[str]]]:
    s = raw.strip()
    if not s:
        return None
    s_no_date, date_str = _extract_optional_date(s)
    parts = s_no_date.split()
    if len(parts) < 3:
        return None
    unit = parts[-1]
    qty_str = parts[-2]
    name = " ".join(parts[:-2]).strip().lower()
    if not name:
        return None
    try:
        quantity = float(qty_str.replace(",", "."))
    except ValueError:
        return None
    return (normalize_name(name), quantity, unit, date_str)

# --- Продукти ---

async def add_product_to_db(user_id: int, text: str):
    items = [it for it in (x.strip() for x in text.split(",")) if it]
    parsed = []
    for raw in items:
        p = _parse_one_item(raw)
        if p:
            parsed.append((user_id, *p))

    print("🔍 Отримано продукти:", items)
    print("✅ Parsed продукти:", parsed)
    if not parsed:
        return

    conn = _connect()
    cursor = conn.cursor()
    for entry in parsed:
        uid, name, qty, unit, expiry = entry

        if expiry is None:
            cursor.execute("""
                SELECT id, quantity FROM products
                WHERE user_id = ? AND name = ? AND unit = ? AND expiry_date IS NULL
            """, (uid, name, unit))
        else:
            cursor.execute("""
                SELECT id, quantity FROM products
                WHERE user_id = ? AND name = ? AND unit = ? AND expiry_date = ?
            """, (uid, name, unit, expiry))

        row = cursor.fetchone()
        if row:
            existing_id, existing_qty = row
            new_qty = float(existing_qty) + float(qty)
            cursor.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, existing_id))
        else:
            cursor.execute("""
                INSERT INTO products (user_id, name, quantity, unit, expiry_date)
                VALUES (?, ?, ?, ?, ?)
            """, (uid, name, qty, unit, expiry))

    conn.commit()
    conn.close()

async def get_all_products(user_id: int) -> List[str]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    view = []
    for name, quantity, unit, expiry in rows:
        if expiry:
            view.append(f"{name} ({quantity} {unit}) – до {expiry}")
        else:
            view.append(f"{name} ({quantity} {unit})")
    return view

async def get_all_products_with_expiry(user_id: int) -> List[Tuple[str, float, str, Optional[str]]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

async def get_all_products_grouped_by_user() -> dict:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, expiry_date FROM products")
    rows = cursor.fetchall()
    conn.close()

    users = {}
    for user_id, name, expiry in rows:
        users.setdefault(user_id, []).append((name, expiry))
    return users

async def get_all_products_with_ids(user_id: int) -> List[Tuple[int, str, float, str, Optional[str]]]:
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

async def delete_product_by_id(product_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

async def delete_product(user_id: int, name: str):
    name = normalize_name(name)
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE user_id = ? AND name = ?", (user_id, name))
    conn.commit()
    conn.close()

async def update_product_quantity_by_id(product_id: int, new_quantity: float):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_quantity, product_id))
    conn.commit()
    conn.close()

async def get_expiring_products(user_id: int, days_threshold: int = 2) -> List[str]:
    today = datetime.now()
    result = []

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("SELECT name, quantity, unit, expiry_date FROM products WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    for name, quantity, unit, expiry_date in rows:
        if not expiry_date:
            continue
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
    conn = _connect()
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
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("SELECT allergies FROM profile WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current = set()
    if row and row[0]:
        current = set(a.strip() for a in row[0].split(",") if a.strip())

    additions = set(a.strip() for a in new_allergies.split(",") if a.strip())
    updated = current.union(additions)
    final = ", ".join(sorted(updated))

    cursor.execute("""
        INSERT INTO profile (user_id, allergies) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET allergies=excluded.allergies
    """, (user_id, final))
    conn.commit()
    conn.close()

async def update_user_dislikes(user_id: int, new_dislikes: str):
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("SELECT dislikes FROM profile WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current = set()
    if row and row[0]:
        current = set(d.strip() for d in row[0].split(",") if d.strip())

    additions = set(d.strip() for d in new_dislikes.split(",") if d.strip())
    updated = current.union(additions)
    final = ", ".join(sorted(updated))

    cursor.execute("""
        INSERT INTO profile (user_id, dislikes) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET dislikes=excluded.dislikes
    """, (user_id, final))
    conn.commit()
    conn.close()

async def update_user_status(user_id: int, status: str):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO profile (user_id, status) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET status=excluded.status
    """, (user_id, status))
    conn.commit()
    conn.close()

async def clear_user_allergies(user_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE profile SET allergies = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def clear_user_dislikes(user_id: int):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE profile SET dislikes = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
