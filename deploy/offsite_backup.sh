#!/usr/bin/env bash
# Копия вне сервера: база + media/ → Backblaze B2, зашифровано паролем владельца.
#
#   bash deploy/offsite_backup.sh          — отправить свежий дамп базы и новые файлы media/
#   bash deploy/offsite_backup.sh verify   — скачать последний дамп из облака и проверить, что он читается
#
# Ключи — в $APP/.backup.env (пишет workflow backup-setup.yml из секретов GitHub):
#   B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT, BACKUP_PASSWORD
# Шифрование — rclone crypt (содержимое и имена файлов). Без BACKUP_PASSWORD
# копии не расшифровать — он хранится у владельца, не только на сервере.
#
# Восстановление вручную (на любом компьютере с rclone и тем же .backup.env):
#   rclone copy enc:db/<файл> .            — дамп базы (gzip pg_dump) → deploy/restore_db.sh
#   rclone copy enc:media/ ./media/        — все файлы
set -euo pipefail
APP=${APP:-/var/www/sadaf}
ENVF="$APP/.backup.env"
STATUS="$APP/backups/offsite_status.txt"
KEEP_DAYS=30

if [ ! -f "$ENVF" ]; then
  echo "$(date -u +%FT%TZ) нет $ENVF — копия в облако не настроена" | tee -a "$APP/backups/offsite.log"
  exit 0
fi
set -a; . "$ENVF"; set +a
command -v rclone >/dev/null || { echo "rclone не установлен"; exit 1; }

export RCLONE_CACHE_DIR=/tmp/sadaf-rclone-cache
export RCLONE_CONFIG_B2_TYPE=s3
export RCLONE_CONFIG_B2_PROVIDER=Other
export RCLONE_CONFIG_B2_ACCESS_KEY_ID="$B2_KEY_ID"
export RCLONE_CONFIG_B2_SECRET_ACCESS_KEY="$B2_APP_KEY"
export RCLONE_CONFIG_B2_ENDPOINT="https://${B2_ENDPOINT#https://}"
export RCLONE_CONFIG_ENC_TYPE=crypt
export RCLONE_CONFIG_ENC_REMOTE="b2:$B2_BUCKET/sadaf"
RCLONE_CONFIG_ENC_PASSWORD=$(rclone obscure "$BACKUP_PASSWORD")
export RCLONE_CONFIG_ENC_PASSWORD
RC="rclone --config /dev/null --retries 5 --low-level-retries 10 --stats 0"

if [ "${1:-}" = "verify" ]; then
  latest=$($RC lsf enc:db/ --files-only | sort | tail -n 1)
  [ -n "$latest" ] || { echo "VERIFY FAIL: в облаке нет ни одного дампа"; exit 1; }
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  $RC copy "enc:db/$latest" "$tmp/"
  gzip -t "$tmp/$latest"
  tables=$(zcat "$tmp/$latest" | grep -c '^COPY ' || true)
  size=$(du -h "$tmp/$latest" | cut -f1)
  [ "$tables" -ge 20 ] || { echo "VERIFY FAIL: $latest — таблиц в дампе $tables"; exit 1; }
  media_local=$(find "$APP/media" -type f 2>/dev/null | wc -l)
  media_remote=$($RC size enc:media/ --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])')
  echo "VERIFY OK: $latest ($size), таблиц: $tables; файлов media: на сервере $media_local, в облаке $media_remote"
  exit 0
fi

latest=$(ls -1t "$APP"/backups/sadaf_backup_*.gz 2>/dev/null | head -n 1 || true)
[ -n "$latest" ] || { echo "нет локального дампа в $APP/backups"; exit 1; }
start=$(date +%s)
$RC copy "$latest" enc:db/
# Старые дампы в облаке — только за последние $KEEP_DAYS дней.
$RC delete enc:db/ --min-age "${KEEP_DAYS}d" || true
# media/ — только новые/изменённые файлы; удалённые на сервере в облаке остаются.
$RC copy "$APP/media" enc:media/ --transfers 4 --exclude "*.tmp"
msg="$(date -u +%FT%TZ) OK: $(basename "$latest") + media/ за $(( $(date +%s) - start )) с"
echo "$msg" | tee "$STATUS"
