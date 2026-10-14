"""/healthz/ — проверка, что сайт жив, для безопасного деплоя (deploy/update.sh).

Стоит первым в MIDDLEWARE: отвечает до редиректа на https, маршрутизации по
доменам и входа. Проверяет базу (SELECT 1). Версию кода (REVISION, её пишет
деплой) показывает только запросу с самого сервера напрямую в gunicorn —
по ней деплой видит, что запросы обслуживают уже новые воркеры."""
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def _read_revision():
    try:
        return (Path(settings.BASE_DIR) / "REVISION").read_text().strip()[:64]
    except OSError:
        return ""


class HealthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # читается при старте воркера: новый воркер — новая версия
        self.revision = _read_revision()

    def __call__(self, request):
        if request.path != "/healthz/":
            return self.get_response(request)
        ok = True
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except Exception:  # noqa: BLE001
            ok = False
        data = {"ok": ok}
        local = (request.META.get("REMOTE_ADDR") in ("127.0.0.1", "::1")
                 and "HTTP_X_REAL_IP" not in request.META and "HTTP_X_FORWARDED_FOR" not in request.META)
        if local:
            data["rev"] = self.revision
        resp = JsonResponse(data, status=200 if ok else 503)
        resp["Cache-Control"] = "no-store"
        return resp
