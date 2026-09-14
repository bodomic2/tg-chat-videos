"""Выгрузка сообщений с видео из чата через Telethon в таблицу videos.

Только чтение: get_entity, iter_messages, get_messages. Ничего в чат не пишется
и не удаляется. Бот-токен не годится — Bot API не отдаёт историю, поэтому нужна
пользовательская сессия (api_id/api_hash с my.telegram.org + вход по номеру).

Фильтр по видео серверный (InputMessagesFilterVideo), так что текстовая история
чата не выкачивается. Для видео-ответов дотягивается текст того сообщения, на
которое отвечали, — там часто написано, что за песня.
"""

import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.tl.types import InputMessagesFilterVideo

from . import config, db

BATCH = 200  # как часто коммитить прогресс
REPLY_BATCH = 100  # get_messages по id — не больше 100 за запрос


def message_link(msg_id, username, channel_id):
    if username:
        return f"https://t.me/{username}/{msg_id}"
    return f"https://t.me/c/{channel_id}/{msg_id}"


def video_duration(message):
    video = getattr(message, "video", None)
    for attr in getattr(video, "attributes", None) or ():
        if hasattr(attr, "duration"):
            return int(attr.duration)
    return None


def utc_iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


async def _open(client):
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit(
            "Сессия не авторизована. Войдите один раз интерактивно: "
            ".venv-win/Scripts/python -m tgchannel login"
        )


async def _fetch_videos(client, conn, entity, username, internal_id, min_id, limit):
    """Сохраняет видео-сообщения с id > min_id. Возвращает число сохранённых."""
    saved = 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    async for m in client.iter_messages(
        entity, reverse=True, min_id=min_id, limit=limit, filter=InputMessagesFilterVideo
    ):
        conn.execute(
            "INSERT INTO videos(msg_id, date_utc, caption, link, grouped_id, reply_to_msg_id, "
            "duration, fetched_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(msg_id) DO UPDATE SET date_utc = excluded.date_utc, "
            "caption = excluded.caption, link = excluded.link, grouped_id = excluded.grouped_id, "
            "reply_to_msg_id = excluded.reply_to_msg_id, duration = excluded.duration, "
            "fetched_at = excluded.fetched_at",
            (
                m.id, utc_iso(m.date), m.message or "",
                message_link(m.id, username, internal_id),
                m.grouped_id, m.reply_to_msg_id, video_duration(m), now,
            ),
        )
        db.set_meta(conn, "last_msg_id", m.id)
        saved += 1
        if saved % BATCH == 0:
            conn.commit()
            print(f"  ...{saved} видео, дошли до {m.date:%Y-%m-%d}")
    conn.commit()
    return saved


async def _fetch_reply_texts(client, conn, entity):
    """Текст сообщений, на которые отвечают видео (кроме тех, что сами видео)."""
    ids = [
        r["reply_to_msg_id"] for r in conn.execute(
            "SELECT DISTINCT reply_to_msg_id FROM videos "
            "WHERE reply_to_msg_id IS NOT NULL AND reply_text IS NULL "
            "AND reply_to_msg_id NOT IN (SELECT msg_id FROM videos)"
        )
    ]
    for i in range(0, len(ids), REPLY_BATCH):
        chunk = ids[i:i + REPLY_BATCH]
        found = {m.id: (m.message or "") for m in await client.get_messages(entity, ids=chunk) if m}
        # удалённые сообщения приходят None — пишем пустую строку, чтобы не спрашивать снова
        conn.executemany(
            "UPDATE videos SET reply_text = ? WHERE reply_to_msg_id = ?",
            [(found.get(mid, ""), mid) for mid in chunk],
        )
        conn.commit()
    return len(ids)


async def _run(conn, limit=None, full=False):
    client = TelegramClient(config.SESSION, config.api_id(), config.api_hash())
    await _open(client)
    try:
        entity = await client.get_entity(config.channel())
        username = getattr(entity, "username", None)
        internal_id = abs(entity.id) % 10**10  # id для ссылок t.me/c/<id>/<msg>
        title = getattr(entity, "title", str(entity.id))
        db.set_meta(conn, "channel_id", entity.id)
        db.set_meta(conn, "channel_title", title)
        db.set_meta(conn, "channel_username", username or "")

        min_id = 0 if full else int(db.get_meta(conn, "last_msg_id", 0) or 0)
        print(f"Чат: {title}" + (f" (@{username})" if username else " (приватный)"))
        print(f"Качаю видео с msg_id > {min_id}" + (f", не больше {limit}" if limit else ""))
        saved = await _fetch_videos(client, conn, entity, username, internal_id, min_id, limit)
        print(f"Сохранено видео: {saved}.")
        replies = await _fetch_reply_texts(client, conn, entity)
        print(f"Подтянуты тексты для {replies} сообщений, на которые отвечали.")
        return saved
    finally:
        await client.disconnect()


def run(conn, limit=None, full=False):
    if full:
        db.set_meta(conn, "last_msg_id", 0)
    return asyncio.run(_run(conn, limit=limit, full=full))


async def _login():
    client = TelegramClient(config.SESSION, config.api_id(), config.api_hash())
    async with client:  # интерактивно спросит номер и код, если сессии нет
        me = await client.get_me()
        print(f"Вошли как @{me.username or me.id}. Сессия: {config.SESSION}.session")


def login():
    asyncio.run(_login())
