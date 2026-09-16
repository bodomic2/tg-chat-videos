#!/usr/bin/env bash
# Залить код на сервер и перезапустить сервис. База, сессия и .env НЕ трогаются:
# серверная база содержит ручные правки из чата, копировать поверх неё локальную нельзя.
# Первичный перенос базы/сессии — отдельно, руками (см. README).
set -euo pipefail

HOST="${1:-root@bodomi.com}"
APP=/opt/tg-chat-videos

cd "$(dirname "$0")/.."
rsync -avz --delete \
  --exclude .venv-win --exclude .venv --exclude .git --exclude __pycache__ --exclude .claude \
  --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' --exclude '*.session*' --exclude .env \
  ./ "$HOST:$APP/"
ssh "$HOST" "systemctl restart tg-chat-videos && systemctl status tg-chat-videos --no-pager -n 3"
