"""Тонкая обёртка над sqlite3: подключение, схема, meta-ключи."""

import sqlite3

from . import config


def connect(path=None):
    conn = sqlite3.connect(path or config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)  # до схемы: она создаёт индексы по новым колонкам
    conn.executescript(config.SCHEMA.read_text(encoding="utf-8"))
    return conn


def _migrate(conn):
    """Дотягивает старую базу до текущей схемы, чтобы не перекачивать чат."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(videos)")}
    if columns and "concert_id" not in columns:
        conn.execute("ALTER TABLE videos ADD COLUMN concert_id TEXT REFERENCES concerts(id) ON DELETE SET NULL")
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
    """Сводка для человека: концерты, песни, видео и привязки."""
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "concerts": q("SELECT count(*) FROM concerts"),
        "setlist": q("SELECT count(*) FROM setlist"),
        "videos": q("SELECT count(*) FROM videos"),
        "matched_ok": q("SELECT count(DISTINCT msg_id) FROM matches WHERE confidence = 'ok'"),
        "matched_maybe": q("SELECT count(DISTINCT msg_id) FROM matches WHERE confidence = 'maybe'"),
        "matched_manual": q("SELECT count(DISTINCT msg_id) FROM matches WHERE confidence = 'manual'"),
        "songs_with_video": q("SELECT count(DISTINCT track_id) FROM matches"),
    }
