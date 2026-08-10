"""Лёгкая асинхронная обёртка над SQLite (без сторонних зависимостей).

Через asyncio.to_thread выполняем синхронные вызовы sqlite3, чтобы не
блокировать event loop бота.
"""
import asyncio
import sqlite3
import time

from config import DATABASE_PATH

_lock = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username    TEXT,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ad_views (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    viewed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    url        TEXT NOT NULL,
    platform   TEXT,
    title      TEXT,
    filesize   INTEGER,
    status     TEXT NOT NULL DEFAULT 'pending',
    error      TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_downloads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    url        TEXT NOT NULL,
    platform   TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    message  TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ad_views_user  ON ad_views (user_id);
CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads (user_id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


async def init_db() -> None:
    await asyncio.to_thread(_init_schema)


async def _run(sql: str, params: tuple = ()) -> int:
    async with _lock:
        def job() -> int:
            conn = _connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()
        return await asyncio.to_thread(job)


async def _query_one(sql: str, params: tuple = ()):
    def job():
        conn = _connect()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()
    return await asyncio.to_thread(job)


async def _query_all(sql: str, params: tuple = ()):
    def job():
        conn = _connect()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    return await asyncio.to_thread(job)


# --- Пользователи ---
async def register_user(telegram_id: int, username: str | None) -> None:
    now = time.time()
    await _run(
        """
        INSERT INTO users (telegram_id, username, first_seen, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            last_seen = excluded.last_seen,
            username  = COALESCE(excluded.username, users.username)
        """,
        (telegram_id, username or None, now, now),
    )


# --- Реклама ---
async def last_ad_view(user_id: int) -> float | None:
    row = await _query_one(
        "SELECT viewed_at FROM ad_views WHERE user_id=? ORDER BY viewed_at DESC LIMIT 1",
        (user_id,),
    )
    return row["viewed_at"] if row else None


async def record_ad_view(user_id: int) -> None:
    await _run("INSERT INTO ad_views (user_id, viewed_at) VALUES (?, ?)", (user_id, time.time()))


# --- Ожидающие загрузки (для callback-кнопки) ---
async def create_pending(user_id: int, url: str, platform: str) -> int:
    return await _run(
        "INSERT INTO pending_downloads (user_id, url, platform, created_at) VALUES (?, ?, ?, ?)",
        (user_id, url, platform, time.time()),
    )


async def pop_pending(pending_id: int) -> dict | None:
    async with _lock:
        def job():
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT * FROM pending_downloads WHERE id=?", (pending_id,)
                ).fetchone()
                if row:
                    conn.execute("DELETE FROM pending_downloads WHERE id=?", (pending_id,))
                    conn.commit()
                return dict(row) if row else None
            finally:
                conn.close()
        return await asyncio.to_thread(job)


# --- Логирование скачиваний ---
async def log_download(user_id: int, url: str, platform: str, title: str,
                       filesize: int | None = None) -> int:
    return await _run(
        """
        INSERT INTO downloads (user_id, url, platform, title, filesize, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'downloading', ?)
        """,
        (user_id, url, platform, title, filesize, time.time()),
    )


async def update_download(download_id: int, status: str,
                          error: str | None = None, filesize: int | None = None) -> None:
    if filesize is not None:
        await _run(
            "UPDATE downloads SET status=?, error=?, filesize=? WHERE id=?",
            (status, error, filesize, download_id),
        )
    else:
        await _run(
            "UPDATE downloads SET status=?, error=? WHERE id=?",
            (status, error, download_id),
        )


# --- Статистика для админов ---
async def stats() -> dict:
    def job():
        conn = _connect()
        try:
            day_ago = time.time() - 86400
            return {
                "users": conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
                "downloads": conn.execute("SELECT COUNT(*) c FROM downloads").fetchone()["c"],
                "today": conn.execute(
                    "SELECT COUNT(*) c FROM downloads WHERE created_at>=?", (day_ago,)
                ).fetchone()["c"],
                "done": conn.execute(
                    "SELECT COUNT(*) c FROM downloads WHERE status='done'"
                ).fetchone()["c"],
                "errors": conn.execute(
                    "SELECT COUNT(*) c FROM downloads WHERE status='error'"
                ).fetchone()["c"],
                "ad_views": conn.execute("SELECT COUNT(*) c FROM ad_views").fetchone()["c"],
            }
        finally:
            conn.close()
    return await asyncio.to_thread(job)


# --- Feedback (демонстрация FSM) ---
async def save_feedback(user_id: int, message: str) -> None:
    await _run(
        "INSERT INTO feedback (user_id, message, created_at) VALUES (?, ?, ?)",
        (user_id, message, time.time()),
    )

