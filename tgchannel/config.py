"""Пути и доступы. Читаются из .env в корне проекта или из переменных окружения."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
SCHEMA = ROOT / "schema.sql"
OUT_DIR = ROOT / "out"
SESSION = str(ROOT / "tgchannel")  # telethon сам добавит .session


def load_env():
    """Подтягивает .env, не перетирая уже выставленное окружение."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def db_path():
    load_env()
    return Path(os.environ.get("TG_DB") or ROOT / "tg_chat_videos.db")


def _require(name, hint):
    load_env()
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Не задан {name}. {hint}\nСкопируйте .env.example в .env и заполните.")
    return value


def api_id():
    return int(_require("TG_API_ID", "Возьмите api_id на https://my.telegram.org."))


def api_hash():
    return _require("TG_API_HASH", "Возьмите api_hash на https://my.telegram.org.")


def channel():
    value = _require("TG_CHANNEL", "Укажите @username канала или его -100... id.")
    if value.startswith("https://t.me/") or value.startswith("t.me/"):
        value = "@" + value.split("t.me/", 1)[1].strip("/")
    try:
        return int(value)
    except ValueError:
        return value
