"""Геолокация по IP для карточки события в Аудит-центре (макет: «Алматы,
KZ») — best-effort, без платного сервиса/ключа (ip-api.com, бесплатный
лимит без регистрации). Вызывается ТОЛЬКО когда открыта карточка
конкретного события (apps.users.newui_views.newui_superadmin_event_detail),
не на каждой строке списка — сетевой вызов не должен тормозить ленту.

Как и остальные внешние HTTP-интеграции в проекте (apps/notifications/
whatsapp.py, telegram.py, apps/appointments/gcal.py) — стандартный
urllib, без requests. Любая ошибка/таймаут — тихо возвращает None,
вызывающая сторона рисует «—», страница никогда не падает из-за
недоступности стороннего сервиса (в песочнице/офлайн-развёртывании
интернета может не быть вовсе — это ожидаемо, не баг)."""
import ipaddress
import json
import logging
import urllib.error
import urllib.request

from django.core.cache import cache

log = logging.getLogger("apps")

_CACHE_TTL_HIT = 60 * 60 * 24 * 30   # 30 дней — гео IP почти не меняется
_CACHE_TTL_MISS = 60 * 60 * 6        # неудачу перепроверяем раньше, но не сразу
_TIMEOUT = 3


def _is_public(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved)


def get_ip_geolocation(ip):
    """"Город, CC" (например "Алматы, KZ") или None, если определить не
    удалось (приватный/локальный IP, сервис недоступен, таймаут, лимит)."""
    if not ip or not _is_public(ip):
        return None
    cache_key = f"geoip:{ip}"
    cached = cache.get(cache_key, "__miss__")
    if cached != "__miss__":
        return cached or None

    result = None
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,message,city,countryCode"
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") == "success":
            city = (data.get("city") or "").strip()
            country = (data.get("countryCode") or "").strip()
            result = ", ".join(p for p in (city, country) if p) or None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as e:
        log.info("geoip: не удалось определить геолокацию %s: %s", ip, e)
        result = None

    cache.set(cache_key, result or "", _CACHE_TTL_HIT if result else _CACHE_TTL_MISS)
    return result
