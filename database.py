import sqlite3

DB_PATH = "app.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL
        )
    """)
    # Insert sample data if table is empty
    count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    if count == 0:
        conn.executemany(
            "INSERT INTO items (name, description, price) VALUES (?, ?, ?)",
            [
                ("Apple", "Fresh red apple", 10.0),
                ("Banana", "Ripe yellow banana", 5.0),
                ("Orange", "Juicy orange", 8.0),
            ],
        )
        conn.commit()
    conn.close()
