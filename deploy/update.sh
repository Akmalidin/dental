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

echo ">>> прогрев кэша Whisper (один раз, до старта воркеров — иначе гонка)"
./venv/bin/python manage.py warm_voice_cache || true

echo ">>> chown + restart"
chown -R www-data:www-data "$APP"
systemctl restart sadaf.service
sleep 2
systemctl is-active sadaf.service

# Ночной авто-бэкап БД (apps/users/management/commands/backup_database.py) —
# сама команда написана и покрыта тестами, но раньше требовала РУЧНОЙ
# установки crontab на сервере (см. докстринг команды) — этот шаг никогда
# не был сделан, поэтому бэкапы никогда не запускались. Ставим строку
# ЗДЕСЬ, при каждом деплое — идемпотентно (grep -vF убирает прежнюю
# версию строки перед добавлением новой, повторный деплой не плодит
# дубликаты), больше не зависит от отдельного ручного шага на сервере.
#
# Важно: весь блок обёрнут в подоболочку с "|| true" — это ВСПОМОГАТЕЛЬНЫЙ
# шаг, а не критический путь деплоя. Дважды подряд падал именно здесь
# (сначала grep без совпадений на пустом crontab, потом — уже после
# фикса grep — где-то дальше, вероятная причина: crontab/cron не
# установлен на сервере или www-data не может им пользоваться, но точно
# диагностировать без SSH-доступа с этой стороны нельзя) и оба раза
# заваливал ВЕСЬ деплой в CI, хотя само приложение (git pull/migrate/
# collectstatic/restart выше) к этому моменту уже успешно развёрнуто и
# перезапущено. Реальная причина теперь печатается в лог деплоя явно —
# следующий деплой покажет её без гадания.
echo ">>> резервные копии: папка + ночной cron (00:00 Бишкек = 18:00 UTC)"
(
  set -e
  mkdir -p "$APP/backups"
  chown www-data:www-data "$APP/backups"
  if ! command -v crontab >/dev/null 2>&1; then
    echo "!!! crontab не найден на сервере — cron бэкапа не установлен (поставьте пакет cron)"
    exit 0
  fi
  CRON_CMD="cd $APP && DJANGO_SETTINGS_MODULE=config.settings.server $APP/venv/bin/python manage.py backup_database >> $APP/backups/cron.log 2>&1"
  ( crontab -l -u www-data 2>/dev/null | grep -vF "manage.py backup_database" || true; echo "0 18 * * * $CRON_CMD" ) | crontab -u www-data -
  echo ">>> cron бэкапа установлен"
) || echo "!!! не удалось установить cron бэкапа (см. вывод выше) — деплой продолжается, это не критично для работы сайта"
echo ">>> pg_dump: $(command -v pg_dump || echo 'НЕ НАЙДЕН — бэкап Postgres не сработает, поставьте пакет postgresql-client на сервере')"

echo ">>> done"
