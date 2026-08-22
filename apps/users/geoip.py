"""Геолокация по IP для Аудит-центра (макет: «Алматы, KZ») — best-effort,
без платного сервиса/ключа (ip-api.com, бесплатный лимит без регистрации).

Две функции:
- `get_ip_geolocation(ip)` — один IP, вызывается ТОЛЬКО когда открыта
  карточка конкретного события (apps.users.newui_views.
  newui_superadmin_event_detail).
- `get_ip_geolocations_batch(ips)` — набор IP ОДНИМ HTTP-запросом (батч-
  эндпоинт ip-api.com, до 100 IP за раз) — для колонки «Локация» в самой
  таблице ленты (apps.users.newui_views.newui_superadmin_feed): по IP на
  каждую из ~50 строк страницы поштучными запросами было бы неприемлемо
  медленно, а тот же бесплатный лимит запросов/минуту у батч-эндпоинта,
  что и у одиночного — один батч-запрос стоит как один обычный.

Как и остальные внешние HTTP-интеграции в проекте (apps/notifications/
whatsapp.py, telegram.py, apps/appointments/gcal.py) — стандартный
urllib, без requests. Любая ошибка/таймаут — тихо возвращает None
(поштучно) или пропускает недостающие IP (батч), вызывающая сторона
рисует «—», страница никогда не падает из-за недоступности стороннего
сервиса (в песочнице/офлайн-развёртывании интернета может не быть вовсе
— это ожидаемо, не баг)."""
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


_BATCH_CHUNK = 100  # лимит ip-api.com/batch за один запрос


def get_ip_geolocations_batch(ips):
    """{ip: "Город, CC" | None} для набора IP — сначала отдаёт то, что уже
    в кэше, для остальных публичных IP делает МИНИМУМ HTTP-запросов (по
    одному на каждые 100 некэшированных IP, не по одному на IP)."""
    result = {}
    to_fetch = []
    seen = set()
    for ip in ips:
        if not ip or ip in seen:
            continue
        seen.add(ip)
        if not _is_public(ip):
            result[ip] = None
            continue
        cache_key = f"geoip:{ip}"
        cached = cache.get(cache_key, "__miss__")
        if cached != "__miss__":
            result[ip] = cached or None
        else:
            to_fetch.append(ip)

    for i in range(0, len(to_fetch), _BATCH_CHUNK):
        chunk = to_fetch[i:i + _BATCH_CHUNK]
        try:
            payload = json.dumps(chunk).encode("utf-8")
            req = urllib.request.Request(
                "http://ip-api.com/batch?fields=status,city,countryCode,query",
                data=payload, method="POST", headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                items = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as e:
            log.info("geoip: батч-запрос не удался (%s IP): %s", len(chunk), e)
            for ip in chunk:
                result[ip] = None
                cache.set(f"geoip:{ip}", "", _CACHE_TTL_MISS)
            continue

        got = {}
        for item in items if isinstance(items, list) else []:
            ip = item.get("query")
            if not ip:
                continue
            value = None
            if item.get("status") == "success":
                city = (item.get("city") or "").strip()
                country = (item.get("countryCode") or "").strip()
                value = ", ".join(p for p in (city, country) if p) or None
            got[ip] = value
        for ip in chunk:
            value = got.get(ip)
            result[ip] = value
            cache.set(f"geoip:{ip}", value or "", _CACHE_TTL_HIT if value else _CACHE_TTL_MISS)

    return result
