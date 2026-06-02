#!/usr/bin/env bash
# Обновление SADAF Clinic на сервере: git pull + deps + migrate + static + restart.
# Запуск на сервере:  bash /var/www/sadaf/deploy/update.sh
set -euo pipefail
APP=/var/www/sadaf
cd "$APP"

echo ">>> git pull"
git pull --ff-only

echo ">>> deps"
./venv/bin/pip install -r requirements_server.txt -q

set -a; . ./.env; set +a
echo ">>> migrate"
./venv/bin/python manage.py migrate --noinput

echo ">>> collectstatic"
./venv/bin/python manage.py collectstatic --noinput

echo ">>> chown + restart"
chown -R www-data:www-data "$APP"
systemctl restart sadaf.service
sleep 2
systemctl is-active sadaf.service
echo ">>> done"
