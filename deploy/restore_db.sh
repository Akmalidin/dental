#!/usr/bin/env bash
# Восстановить базу из бэкапа, сделанного перед деплоем (backups/predeploy/)
# или ночного (backups/). ТОЛЬКО ВРУЧНУЮ, осознанно:
#   bash deploy/restore_db.sh backups/predeploy/predeploy_2026-10-14_0912.sql.gz --yes
# Перед восстановлением снимает ещё одну копию текущей базы (backups/predeploy/
# before_restore_*), на время восстановления останавливает сайт.
# Всё, что записали в базу после бэкапа, будет потеряно (записи, оплаты…).
set -euo pipefail
APP=/var/www/sadaf
cd "$APP"
FILE=${1:-}
if [ -z "$FILE" ] || [ ! -f "$FILE" ] || [ "${2:-}" != "--yes" ]; then
  echo "Использование: bash deploy/restore_db.sh <файл .sql.gz> --yes"
  echo "Доступные копии:"; ls -lt backups/predeploy/ backups/ 2>/dev/null | grep -E "sql.gz" | head -15
  exit 2
fi
set -a; . ./.env; set +a
export PGPASSWORD="${DB_PASSWORD:-}"
DBH=${DB_HOST:-localhost}; DBP=${DB_PORT:-5432}; DBU=${DB_USER:-sadaf}; DBN=${DB_NAME:-sadaf_clinic}

echo ">>> копия текущей базы на всякий случай"
mkdir -p backups/predeploy
./venv/bin/python manage.py backup_database --dir backups/predeploy --prefix before_restore_ --keep 3

echo ">>> останавливаю сайт"
systemctl stop sadaf.service
trap 'systemctl start sadaf.service' EXIT

echo ">>> очищаю схему и загружаю $FILE"
psql -v ON_ERROR_STOP=1 -h "$DBH" -p "$DBP" -U "$DBU" -d "$DBN" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
gunzip -c "$FILE" | psql -v ON_ERROR_STOP=1 -q -h "$DBH" -p "$DBP" -U "$DBU" -d "$DBN"
echo ">>> база восстановлена из $FILE; сайт запускается"
