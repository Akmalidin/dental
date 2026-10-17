#!/usr/bin/env bash
# Безопасное обновление SADAF Clinic на сервере.
# Запуск: deploy.yml берёт этот файл прямо из origin/main и выполняет его,
# так что изменения в нём действуют с того же деплоя.
#
#  1. Запоминаем текущую версию (PREV) — на неё откатываемся при любой беде.
#  2. Новый код + зависимости, затем `manage.py check` ДО переключения:
#     не собирается — возвращаем прежний код, сайт этого даже не заметил.
#  3. Пробный запуск новой версии рядом (порт 8022, один воркер) и проверка
#     /healthz/: не запускается — возвращаем прежний код, ни сайт, ни база не тронуты.
#  4. Есть новые миграции — сначала бэкап базы (backups/predeploy/, 5 последних);
#     migrate, collectstatic.
#  5. Плавный перезапуск: HUP мастеру gunicorn — новые воркеры стартуют,
#     старые дорабатывают свои запросы, 502 нет. Не подхватилось — обычный restart.
#  6. Проверка /healthz/: отвечает, база доступна, отвечает НОВАЯ версия.
#     Нет — автоматический откат кода на PREV и restart; деплой помечается
#     проваленным (GitHub заводит issue). Миграции сами не откатываются —
#     для этого есть бэкап из шага 4 и deploy/restore_db.sh.
set -euo pipefail
APP=/var/www/sadaf
cd "$APP"
HEALTH_URL="http://127.0.0.1:8021/healthz/"
PREDEPLOY_DIR="$APP/backups/predeploy"

PREV=$(git rev-parse HEAD)
echo ">>> сейчас работает: $PREV"

echo ">>> git fetch"
# fetch + reset --hard вместо "git pull --ff-only": сервер — чистое зеркало
# origin/main, разошедшиеся ветки тут — всегда повреждённое состояние
# (оборванный деплой, ручная правка), reset --hard самовосстанавливается.
git fetch origin main
NEW=$(git rev-parse origin/main)
echo ">>> новая версия: $NEW"

set_code() {   # $1 — коммит
  git reset --hard "$1"
  echo "$1" > REVISION
  ./venv/bin/pip install -r requirements_server.txt -q
}

health_ok() {  # $1 — ожидаемая версия, $2 — сколько секунд ждать, $3 — адрес; нужно 3 удачных ответа подряд
  local want=$1 limit=$2 url=${3:-$HEALTH_URL} hits=0 waited=0 body=""
  while [ "$waited" -lt "$limit" ]; do
    body=$(curl -s --max-time 5 "$url" || true)
    if echo "$body" | grep -q '"ok": true' && echo "$body" | grep -q "\"rev\": \"$want\""; then
      hits=$((hits + 1))
      [ "$hits" -ge 3 ] && return 0
    else
      hits=0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  echo "    последний ответ /healthz/: ${body:-нет ответа}"
  return 1
}

canary_ok() {   # $1 — версия: пробный запуск рядом (порт 8022, 1 воркер), рабочий сайт не трогаем
  local pidf=/tmp/sadaf_canary.pid ok=0 runas=""
  rm -f "$pidf"
  if id www-data >/dev/null 2>&1 && command -v runuser >/dev/null 2>&1; then runas="runuser -u www-data --"; fi
  if $runas ./venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8022 --workers 1 --timeout 60 \
      --pid "$pidf" --daemon --error-logfile /tmp/sadaf_canary.log; then
    health_ok "$1" 40 "http://127.0.0.1:8022/healthz/" && ok=1
  fi
  [ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null || true
  if [ "$ok" != 1 ]; then
    echo "    ошибки пробного запуска:"; tail -n 30 /tmp/sadaf_canary.log 2>/dev/null | sed 's/^/    /' || true
    return 1
  fi
}

restart_and_check() {   # $1 — ожидаемая версия
  echo ">>> плавный перезапуск (HUP: новые воркеры стартуют, старые дорабатывают запросы)"
  if systemctl is-active --quiet sadaf.service; then
    kill -HUP "$(systemctl show -p MainPID --value sadaf.service)"
    health_ok "$1" 45 && return 0
    echo ">>> плавный перезапуск не подхватил новую версию — обычный restart"
  fi
  systemctl restart sadaf.service
  health_ok "$1" 90
}

rollback() {   # $1 — причина
  echo "!!! $1"
  echo "!!! ОТКАТ на прежнюю версию $PREV"
  set_code "$PREV"
  ./venv/bin/python manage.py collectstatic --noinput >/dev/null || true
  chown -R www-data:www-data "$APP"
  if restart_and_check "$PREV"; then
    echo "!!! откат выполнен: сайт работает на прежней версии $PREV"
  else
    echo "!!! и прежняя версия не отвечает — нужна ручная проверка (journalctl -u sadaf -n 100)"
  fi
  if [ -n "${BACKUP_FILE:-}" ]; then
    echo "!!! миграции новой версии уже применены. Если прежняя версия с ними работает неправильно —"
    echo "!!! восстановить базу на момент до деплоя: bash deploy/restore_db.sh $BACKUP_FILE --yes"
  fi
  exit 1
}

set_code "$NEW"
set -a; . ./.env; set +a

echo ">>> проверка нового кода до переключения (manage.py check)"
if ! ./venv/bin/python manage.py check --fail-level ERROR; then
  echo "!!! новый код не проходит проверку — возвращаю прежний, сайт не тронут"
  set_code "$PREV"
  exit 1
fi

echo ">>> пробный запуск новой версии рядом с рабочей (порт 8022, база не меняется)"
if ! canary_ok "$NEW"; then
  echo "!!! новая версия не запускается — возвращаю прежний код, рабочий сайт и база не тронуты"
  set_code "$PREV"
  exit 1
fi

BACKUP_FILE=""
if ! ./venv/bin/python manage.py migrate --check >/dev/null 2>&1; then
  echo ">>> есть новые миграции — сначала бэкап базы ($PREDEPLOY_DIR)"
  mkdir -p "$PREDEPLOY_DIR"
  if ! out=$(./venv/bin/python manage.py backup_database --dir "$PREDEPLOY_DIR" --prefix predeploy_ --keep 5); then
    echo "$out"
    echo "!!! бэкап не удался — деплой остановлен до миграций, сайт работает на прежней версии"
    set_code "$PREV"
    exit 1
  fi
  echo "$out"
  BACKUP_FILE=$(ls -t "$PREDEPLOY_DIR"/predeploy_* | head -1)
fi

echo ">>> migrate"
if ! ./venv/bin/python manage.py migrate --noinput; then
  rollback "миграция не прошла"
fi

echo ">>> collectstatic"
./venv/bin/python manage.py collectstatic --noinput

echo ">>> прогрев кэша Whisper (один раз, до старта воркеров — иначе гонка)"
./venv/bin/python manage.py warm_voice_cache || true

echo ">>> ретрофит секрета вебхука Telegram для уже подключённых клиник (аудит безопасности)"
./venv/bin/python manage.py backfill_telegram_webhook_secrets || true

# Ответ ИИ-помощника (OpenAI) идёт 3–15 с — на 3 обычных воркерах gunicorn
# несколько одновременных вопросов подвешивали бы сайт остальным. Потоки
# (gthread) дают 12 одновременных запросов почти без лишней памяти. gunicorn
# сам читает GUNICORN_CMD_ARGS из окружения (EnvironmentFile=.env).
if ! grep -q '^GUNICORN_CMD_ARGS=' .env; then
  echo ">>> gunicorn: 4 потока на воркер"
  printf '\nGUNICORN_CMD_ARGS="--threads 4"\n' >> .env
fi

chown -R www-data:www-data "$APP"
if ! restart_and_check "$NEW"; then
  rollback "новая версия не отвечает на /healthz/"
fi
echo ">>> новая версия $NEW работает"

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
  # ИИ-ассистент для пациентов (WhatsApp/Telegram): раз в минуту отвечает в
  # чатах, где администратор не ответил вовремя. .env подгружаем сами —
  # cron его не видит; flock не даёт запускам наложиться.
  TICK_CMD="cd $APP && set -a && . ./.env && set +a && DJANGO_SETTINGS_MODULE=config.settings.server flock -n /tmp/sadaf_patient_ai.lock $APP/venv/bin/python manage.py patient_assistant_tick >> $APP/backups/patient_ai.log 2>&1"
  ( crontab -l -u www-data 2>/dev/null | grep -vF "manage.py patient_assistant_tick" || true; echo "* * * * * $TICK_CMD" ) | crontab -u www-data -
  echo ">>> cron ИИ-ассистента для пациентов установлен"
  # Кассовая смена: закрытие в 02:00 и открытие в 08:00 по времени клиники.
  SHIFT_CMD="cd $APP && set -a && . ./.env && set +a && DJANGO_SETTINGS_MODULE=config.settings.server flock -n /tmp/sadaf_cashshift.lock $APP/venv/bin/python manage.py cashshift_auto >> $APP/backups/cashshift.log 2>&1"
  ( crontab -l -u www-data 2>/dev/null | grep -vF "manage.py cashshift_auto" || true; echo "*/5 * * * * $SHIFT_CMD" ) | crontab -u www-data -
  echo ">>> cron кассовой смены установлен"
  # Рассрочки: напоминания пациентам о платежах — проверка каждый час,
  # отправка в час, выбранный клиникой («Деньги → Рассрочки» → ⚙), по её времени.
  INST_CMD="cd $APP && set -a && . ./.env && set +a && DJANGO_SETTINGS_MODULE=config.settings.server flock -n /tmp/sadaf_installments.lock $APP/venv/bin/python manage.py installment_reminders >> $APP/backups/installments.log 2>&1"
  ( crontab -l -u www-data 2>/dev/null | grep -vF "manage.py installment_reminders" || true; echo "7 * * * * $INST_CMD" ) | crontab -u www-data -
  echo ">>> cron напоминаний по рассрочкам установлен"
  # Копия вне сервера (Backblaze, зашифровано): через 40 минут после ночного
  # дампа. Пока workflow backup-setup.yml не записал .backup.env — скрипт
  # просто пишет в лог «не настроено» и выходит.
  OFFSITE_CMD="cd $APP && flock -n /tmp/sadaf_offsite.lock bash $APP/deploy/offsite_backup.sh >> $APP/backups/offsite.log 2>&1"
  ( crontab -l -u www-data 2>/dev/null | grep -vF "offsite_backup.sh" || true; echo "40 18 * * * $OFFSITE_CMD" ) | crontab -u www-data -
  echo ">>> cron копии в облако установлен"
  echo ">>> cron бэкапа установлен"
) || echo "!!! не удалось установить cron бэкапа (см. вывод выше) — деплой продолжается, это не критично для работы сайта"
echo ">>> pg_dump: $(command -v pg_dump || echo 'НЕ НАЙДЕН — бэкап Postgres не сработает, поставьте пакет postgresql-client на сервере')"

echo ">>> done"
