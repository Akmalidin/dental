"""Ретрофит секрета вебхука Telegram для уже подключённых клиник.

До этой команды `tg_webhook` (apps/notifications/views.py) не проверял, что
POST на /notifications/tg-webhook/<slug>/ реально пришёл от Telegram —
clinic_slug в адресе публичный (виден на <slug>.stom.asia), сам по себе
секретом не является. Фикс добавил ClinicSettings.telegram_webhook_secret +
проверку заголовка X-Telegram-Bot-Api-Secret-Token, но для клиник, которые
подключили бота ДО этого фикса, секрет пустой — новый код в tg_webhook
намеренно «открыт» (не блокирует), пока секрет пуст, чтобы не разорвать уже
работающих ботов сразу после деплоя. Эта команда закрывает разрыв: для
каждой клиники с токеном, но без секрета — генерирует секрет и переставляет
вебхук в Telegram (setWebhook с secret_token), взяв текущий URL вебхука из
самого Telegram (getWebhookInfo), а не угадывая домен по настройкам — так
подходит для любого из нескольких доменов, под которыми развёрнут проект.

Вызывается из deploy/update.sh перед restart (тот же паттерн, что и
warm_voice_cache) — best-effort, ошибка на одной клинике не должна ронять
весь деплой и не мешает остальным клиникам."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ретрофит: выпустить секрет вебхука Telegram для уже подключённых клиник"

    def handle(self, *args, **options):
        from apps.settings_clinic.models import ClinicSettings
        from apps.notifications.telegram import tg_get_webhook_info, tg_set_webhook
        import secrets

        qs = (ClinicSettings.objects
              .exclude(clinic__isnull=True)
              .exclude(telegram_bot_token="")
              .filter(telegram_webhook_secret=""))
        if not qs.exists():
            self.stdout.write("Все подключённые клиники уже с секретом вебхука — нечего делать.")
            return

        ok, failed = 0, 0
        for cs in qs.select_related("clinic"):
            token = cs.telegram_bot_token
            try:
                info = tg_get_webhook_info(token)
                url = (info.get("result") or {}).get("url") or ""
                if not url:
                    self.stderr.write(self.style.WARNING(
                        f"{cs.clinic.slug}: у бота нет зарегистрированного webhook URL — пропуск"))
                    failed += 1
                    continue
                new_secret = secrets.token_urlsafe(32)
                res = tg_set_webhook(token, url, secret_token=new_secret)
                if not res.get("ok"):
                    self.stderr.write(self.style.WARNING(
                        f"{cs.clinic.slug}: setWebhook не удался: {res.get('description', '')}"))
                    failed += 1
                    continue
                cs.telegram_webhook_secret = new_secret
                cs.save(update_fields=["telegram_webhook_secret"])
                ok += 1
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"{cs.clinic.slug}: ошибка — {e}"))
                failed += 1

        self.stdout.write(self.style.SUCCESS(f"Готово: секрет выпущен для {ok} клиник, ошибок: {failed}."))
