"""Простой лимит запросов для публичных форм (онлайн-запись, заявки).

Счётчики лежат в отдельном кэше "ratelimit" (файловый — общий для всех
воркеров gunicorn, в отличие от LocMem). Сбой кэша не мешает работе формы.
"""
import hashlib
import logging

log = logging.getLogger(__name__)


def _cache():
    from django.core.cache import caches
    from django.core.cache.backends.base import InvalidCacheBackendError
    try:
        return caches["ratelimit"]
    except InvalidCacheBackendError:
        return caches["default"]


def allow(scope, ident, limit, window):
    """Засчитать попытку; False — лимит (limit за window секунд) исчерпан."""
    from django.conf import settings
    if not ident or not getattr(settings, "RATELIMIT_ENABLED", True):
        return True
    key = "rl:%s:%s" % (scope, hashlib.sha1(str(ident).encode()).hexdigest())
    try:
        c = _cache()
        if c.add(key, 1, window):
            return True
        n = c.incr(key)
        return n <= limit
    except Exception:  # noqa: BLE001 — лимит не должен ронять форму
        log.exception("ratelimit: кэш недоступен")
        return True


def allow_request(request, scope, limits):
    """limits: [(limit, window_seconds), ...] по IP посетителя."""
    from apps.tenancy import get_client_ip
    ip = get_client_ip(request)
    return all(allow("%s:%d" % (scope, window), ip, limit, window) for limit, window in limits)
