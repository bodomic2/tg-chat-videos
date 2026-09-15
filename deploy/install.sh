#!/usr/bin/env bash
# Установка на Ubuntu от root: bash deploy/install.sh videos.example.com [порт gunicorn, по умолчанию 8080]
# Проект должен лежать в /opt/tg-chat-videos вместе с .env и tgchannel.session.
set -euo pipefail

DOMAIN="${1:?Укажите домен: bash deploy/install.sh videos.example.com [порт]}"
PORT="${2:-8080}"
APP=/opt/tg-chat-videos

cd "$APP"
[ -f .env ] || { echo "Нет $APP/.env — скопируйте с рабочей машины"; exit 1; }
[ -f tgchannel.session ] || { echo "Нет $APP/tgchannel.session — скопируйте с рабочей машины (иначе fetch попросит вход)"; exit 1; }

apt-get install -y python3-venv nginx >/dev/null
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r deploy/requirements-server.txt

sed "s/PORT/$PORT/" deploy/tg-chat-videos.service > /etc/systemd/system/tg-chat-videos.service
cp deploy/tg-chat-videos-sync.service deploy/tg-chat-videos-sync.timer /etc/systemd/system/
sed "s/DOMAIN/$DOMAIN/; s/PORT/$PORT/" deploy/nginx.conf > /etc/nginx/sites-available/tg-chat-videos
ln -sf /etc/nginx/sites-available/tg-chat-videos /etc/nginx/sites-enabled/tg-chat-videos

systemctl daemon-reload
systemctl enable tg-chat-videos.service tg-chat-videos-sync.timer
systemctl restart tg-chat-videos.service
systemctl start tg-chat-videos-sync.timer
nginx -t && systemctl reload nginx

echo "Готово: http://$DOMAIN  (TLS: certbot --nginx -d $DOMAIN)"
echo "Первичная выкачка: cd $APP && .venv/bin/python -m tgchannel all"
