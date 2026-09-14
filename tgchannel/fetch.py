"""Выгрузка истории канала через Telethon в таблицу messages.

Бот-токен здесь не годится: Bot API не отдаёт прошлые сообщения канала.
Нужна пользовательская сессия — api_id/api_hash с my.telegram.org и вход по номеру.
"""

import asyncio
import json
from datetime import datetime, timezone

from telethon import TelegramClient

from . import config, db

BATCH = 200  # как часто коммитить прогресс


def entities_to_json(message):
    """Форматирование поста в компактный JSON. Смещения — в UTF-16, как их даёт Telegram."""
    entities = getattr(message, "entities", None)
    if not entities:
        return None
    return json.dumps(
        [
            {"type": type(e).__name__, "offset": e.offset, "length": e.length}
            for e in entities
        ],
        ensure_ascii=False,
    )


def message_link(msg_id, username, channel_id):
    if username:
        return f"https://t.me/{username}/{msg_id}"
    return f"https://t.me/c/{channel_id}/{msg_id}"


async def _run(conn, limit=None, full=False):
    client = TelegramClient(config.SESSION, config.api_id(), config.api_hash())
    async with client:
        entity = await client.get_entity(config.channel())
        username = getattr(entity, "username", None)
        internal_id = abs(entity.id) % 10**10  # id для ссылок t.me/c/<id>/<msg>
        title = getattr(entity, "title", str(entity.id))
        db.set_meta(conn, "channel_id", entity.id)
        db.set_meta(conn, "channel_title", title)
        db.set_meta(conn, "channel_username", username or "")
        db.set_meta(conn, "channel_internal_id", internal_id)

        min_id = 0 if full else int(db.get_meta(conn, "last_msg_id", 0) or 0)
        print(f"Канал: {title}" + (f" (@{username})" if username else " (приватный)"))
        print(f"Качаю с msg_id > {min_id}" + (f", не больше {limit} постов" if limit else ""))

        saved = skipped = 0
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async for message in client.iter_messages(
            entity, reverse=True, min_id=min_id, limit=limit
        ):
            text = message.message or ""
            if not text.strip():
                skipped += 1  # медиа без подписи, служебные сообщения
            else:
                conn.execute(
                    "INSERT INTO messages(msg_id, date_utc, text, entities, link, "
                    "parse_status, fetched_at) VALUES(?,?,?,?,?,'new',?) "
                    "ON CONFLICT(msg_id) DO UPDATE SET "
                    "date_utc = excluded.date_utc, text = excluded.text, "
                    "entities = excluded.entities, link = excluded.link, "
                    "parse_status = 'new', fetched_at = excluded.fetched_at",
                    (
                        message.id,
                        message.date.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        text,
                        entities_to_json(message),
                        message_link(message.id, username, internal_id),
                        now,
                    ),
                )
                saved += 1

            db.set_meta(conn, "last_msg_id", message.id)
            if (saved + skipped) % BATCH == 0:
                conn.commit()
                print(f"  ...{saved} постов (пропущено без текста: {skipped})")
        conn.commit()
        print(f"Готово: сохранено {saved}, пропущено без текста {skipped}.")
        return saved


def run(conn, limit=None, full=False):
    if full:
        db.set_meta(conn, "last_msg_id", 0)
    return asyncio.run(_run(conn, limit=limit, full=full))
