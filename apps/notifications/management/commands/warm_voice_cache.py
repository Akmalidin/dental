"""Прогрев кэша модели Whisper — скачивает/загружает модель ОДИН раз, одним
процессом, до старта gunicorn. Без этого шага несколько воркеров gunicorn
(--workers 2) лезут в лениво инициализируемый apps.notifications.voice.
_get_whisper_model() одновременно на первом же голосовом запросе после
рестарта и мешают друг другу блокировками файлов при скачивании — поймано
в проде как "I/O error: Permission denied (os error 13)" (гонка, не
реальная проблема с правами — сами права на whisper_cache/ в порядке).

Вызывается из deploy/update.sh перед systemctl restart, только если
OPENAI_ENABLED=1 (не тратить время/трафик деплоя, если голосовой ввод не
используется). Безопасно завершается без ошибки, если фича выключена или
пакет faster-whisper не установлен — деплой не должен падать из-за этого
прогрева."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Скачать и закешировать модель Whisper (один раз, до старта воркеров gunicorn)"

    def handle(self, *args, **options):
        from apps.notifications.voice import voice_enabled, _get_whisper_model

        if not voice_enabled():
            self.stdout.write("Голосовой ввод выключен (OPENAI_ENABLED != 1) — пропускаю прогрев.")
            return
        try:
            self.stdout.write("Прогрев кэша модели Whisper...")
            _get_whisper_model()
            self.stdout.write(self.style.SUCCESS("Модель Whisper готова и закеширована."))
        except Exception as e:
            # Не роняем деплой из-за прогрева — если тут что-то пошло не так
            # (например, huggingface.co недоступен), голосовой ввод просто не
            # заработает до ручного разбора, но сайт должен продолжить деплоиться.
            self.stderr.write(self.style.WARNING(f"Прогрев кэша Whisper не удался: {e}"))
