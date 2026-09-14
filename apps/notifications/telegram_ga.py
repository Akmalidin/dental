"""Telegram через Green-API — ОБЫЧНЫЙ аккаунт, подключаемый сканированием QR.

Это не бот. Бот (apps/notifications/telegram.py, Bot API) остаётся и дальше
обслуживает входящие, кнопки и меню самообслуживания — у обычного аккаунта
Bot API нет, инлайн-клавиатуру он отправить не может.

Инстанс ОДИН на всю систему (не на клинику), поэтому ключи живут в настройках
из .env, а не в ClinicSettings: подключение здесь — системное действие, оно
затрагивает все клиники сразу.

Важно про apiUrl: у телеграм-инстанса он свой, вида https://4100.api.green-api.com,
а не общий api.greenapi.com. Его обязательно задавать явно — иначе запросы
уйдут не туда.

Методы совпадают с WhatsApp по форме (waInstance{id}/{method}/{token}), но у
Telegram свои типы ответа QR: qrCode, already_registered, error (подвиды
timeout / not_ready / connection_closed). Если на аккаунте включён облачный
пароль, инстанс уходит в состояние pendingPassword и ждёт sendAuthorizationPassword.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger("apps")


def _tga_config():
    """(enabled, id_instance, token, api_url) телеграм-инстанса Green-API."""
    return (
        bool(getattr(settings, "TELEGRAM_GA_ENABLED", False)),
        (getattr(settings, "TELEGRAM_GA_ID_INSTANCE", "") or "").strip(),
        (getattr(settings, "TELEGRAM_GA_TOKEN", "") or "").strip(),
        (getattr(settings, "TELEGRAM_GA_API_URL", "") or "").strip(),
    )


def tga_configured():
    """Ключи заданы — можно обращаться к API (даже если отправка выключена)."""
    _enabled, idi, token, url = _tga_config()
    return bool(idi and token and url)


def tga_enabled():
    """Отправка через аккаунт включена И ключи заданы."""
    enabled, idi, token, url = _tga_config()
    return bool(enabled and idi and token and url)


def _api_url(method):
    _enabled, idi, token, url = _tga_config()
    return "%s/waInstance%s/%s/%s" % (url.rstrip("/"), idi, method, token)


def _request(method, payload=None, timeout=30):
    """GET, либо POST если передан payload. Возвращает (ok, данные_или_причина)."""
    if not tga_configured():
        return (False, "keys")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        _api_url(method), data=data,
        method="POST" if data else "GET",
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (True, json.loads(r.read().decode("utf-8", "replace")))
    except urllib.error.HTTPError as e:
        log.warning("Telegram(Green-API) %s (%s): %s", method, e.code, e.read()[:400])
        return (False, "http")
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram(Green-API) %s ошибка: %s", method, e)
        return (False, "error")


def tga_state():
    """'notAuthorized' | 'authorized' | 'starting' | 'pendingPassword' | '' (ошибка)."""
    ok, data = _request("getStateInstance")
    return data.get("stateInstance", "") if ok and isinstance(data, dict) else ""


def tga_qr():
    """QR для привязки аккаунта: (type, message).

    type='qrCode' → message это base64-PNG; 'already_registered' → уже привязан;
    'error' → message содержит подвид (timeout / not_ready / connection_closed).
    QR живёт недолго, документация советует опрашивать раз в 5 секунд.
    """
    ok, data = _request("qr")
    if not ok or not isinstance(data, dict):
        return ("", "")
    return (data.get("type", ""), data.get("message", ""))


def tga_send_password(password):
    """Облачный пароль Telegram — когда инстанс перешёл в pendingPassword."""
    if not (password or "").strip():
        return (False, "password")
    ok, data = _request("sendAuthorizationPassword", {"password": password})
    if not ok:
        return (False, data)
    return (True, data)


def tga_logout():
    """Отвязать аккаунт. Действие системное — затрагивает все клиники."""
    ok, data = _request("logout", {})
    return (ok, data)


def _chat_id(phone):
    """Номер телефона → chatId Green-API: '996XXXXXXXXX@c.us'.

    Только для НОМЕРОВ. Угадывать по цифрам, номер это или id пользователя
    Telegram, нельзя: локальный '0700123456' и id вида '10000000' — оба
    десятизначные. Поэтому id передаётся отдельной функцией tga_send_chat(),
    а здесь всё трактуется как телефон.
    """
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "996" + digits[1:]
    if not digits:
        return None
    return digits + "@c.us"


def tga_send_chat(chat, text):
    """Отправить в готовый chatId.

    chat уже в нужной форме: '996...@c.us' для номера, '10000000' для
    пользователя Telegram, '-100...' для группы.
    """
    if not tga_enabled():
        log.info("Telegram(Green-API) выключен — пропуск отправки в %s", chat)
        return False
    if not chat:
        return False
    ok, _data = _request("sendMessage", {"chatId": str(chat), "message": text})
    return bool(ok)


def tga_send_text(phone, text):
    """Отправить текст на НОМЕР телефона. True/False."""
    chat = _chat_id(phone)
    if not chat:
        return False
    return tga_send_chat(chat, text)
