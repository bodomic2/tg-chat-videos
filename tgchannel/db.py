"""Тонкая обёртка над sqlite3: подключение, схема, meta-ключи."""

import sqlite3

from . import config


def connect(path=None):
    conn = sqlite3.connect(path or config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(config.SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    return conn


def _migrate(conn):
    """Дотягивает старую базу до текущей схемы, чтобы не перекачивать канал."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(appearances)")}
    if "confidence" not in columns:
        conn.execute(
            "ALTER TABLE appearances ADD COLUMN confidence TEXT NOT NULL DEFAULT 'ok'"
        )
        conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def counts(conn):
    """Сводка для человека: сколько постов, песен, исполнений."""
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "messages": q("SELECT count(*) FROM messages"),
        "catalog_posts": q("SELECT count(*) FROM messages WHERE parse_status = 'ok'"),
        "maybe_posts": q("SELECT count(*) FROM messages WHERE parse_status = 'maybe'"),
        "other_posts": q("SELECT count(*) FROM messages WHERE parse_status NOT IN ('ok','maybe')"),
        "artists": q("SELECT count(DISTINCT t.artist_key) FROM tracks t "
                     "JOIN appearances a ON a.track_id = t.id WHERE a.confidence = 'ok'"),
        "tracks": q("SELECT count(DISTINCT t.id) FROM tracks t "
                    "JOIN appearances a ON a.track_id = t.id WHERE a.confidence = 'ok'"),
        "appearances": q("SELECT count(*) FROM appearances WHERE confidence = 'ok'"),
    }
