from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from database import get_db_connection, init_db
from rate_limiter import rate_limiter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/items")
def get_items(_: None = rate_limiter(algorithm="fixed_window", limit=10, window=1)):
    conn = get_db_connection()
    items = conn.execute("SELECT * FROM items").fetchall()
    conn.close()
    return [dict(item) for item in items]


@app.get("/items/{item_id}")
def get_item(
    item_id: int, _: None = rate_limiter(algorithm="sliding_window", limit=10, window=1)
):
    conn = get_db_connection()
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return dict(item)
