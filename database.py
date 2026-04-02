import os
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payables (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            supplier TEXT NOT NULL,
            original_amount REAL NOT NULL,
            remaining_amount REAL NOT NULL,
            due_date TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS receivables (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            customer TEXT NOT NULL,
            original_amount REAL NOT NULL,
            remaining_amount REAL NOT NULL,
            due_date TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            item_name TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit_cost REAL NOT NULL DEFAULT 0.0,
            selling_price REAL DEFAULT 0.0,
            UNIQUE(user_id, item_name)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            payable_id INTEGER REFERENCES payables(id) ON DELETE CASCADE,
            receivable_id INTEGER REFERENCES receivables(id) ON DELETE CASCADE,
            amount REAL NOT NULL,
            transaction_date DATE NOT NULL,
            description TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            total_amount REAL NOT NULL,
            sale_date TEXT NOT NULL,
            items_sold TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            expense_date TEXT NOT NULL,
            amount REAL NOT NULL
        )
    ''')

    hashed_password = generate_password_hash('password')
    cursor.execute('INSERT INTO users (username, password) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING', ('admin', hashed_password))

    conn.commit()
    cursor.close()
    conn.close()
    print("Database initialized successfully.")

if __name__ == '__main__':
    init_db()