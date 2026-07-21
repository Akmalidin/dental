"""Отправка Telegram через Bot API (https://core.telegram.org/bots/api).

У каждой клиники — свой бот (создаётся один раз через @BotFather, токен
вставляется в Настройки клиники). В отличие от WhatsApp/Green-API, Telegram
не может писать пациенту первым — пациент должен один раз нажать Start у
бота клиники (и поделиться номером телефона) — тогда мы знаем его chat_id.

Безопасно-выключено: если токен не задан или клиника отключила Telegram —
просто логирует и возвращает False, ничего не падает.
"""
import json
import logging
import urllib.request
import urllib.error
from django.conf import settings

log = logging.getLogger("apps")


def _tg_config():
    """(enabled, token) для ТЕКУЩЕЙ клиники — учитывает и мастер-переключатель
    суперадмина (Clinic.telegram_master_enabled), и переключатель самой клиники
    (ClinicSettings.telegram_enabled)."""
    cs = None
    try:
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.get()
    except Exception:
        cs = None
    if cs is None:
        return (False, "")
    token = (getattr(cs, "telegram_bot_token", "") or "").strip()
    c_enabled = bool(getattr(cs, "telegram_enabled", True))
    master_enabled = True
    try:
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        if clinic is not None:
            master_enabled = bool(getattr(clinic, "telegram_master_enabled", True))
    except Exception:
        pass
    return (c_enabled and master_enabled, token)


def tg_enabled():
    enabled, token = _tg_config()
    return bool(enabled and token)


def _api_url(method, token=None):
    _enabled, tok = (True, token) if token else _tg_config()
    return "https://api.telegram.org/bot%s/%s" % (tok, method)


def _call(method, payload, token=None):
    req = urllib.request.Request(
        _api_url(method, token), data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read()[:400]
        log.warning("Telegram API %s не удался (%s): %s", method, e.code, body)
        return {"ok": False, "error": body}
    except Exception as e:  # noqa: BLE001
        log.warning("Telegram API %s ошибка: %s", method, e)
        return {"ok": False, "error": str(e)}


def _inline_keyboard(buttons):
    """buttons: список кнопок или список строк (по одной кнопке в ряд).
    Кнопка — (текст, callback_data) или (текст, callback_data, url).
    Каждый вложенный список — отдельный ряд кнопок."""
    if not buttons:
        return None
    rows = []
    for row in buttons:
        if isinstance(row, tuple):
            row = [row]
        line = []
        for b in row:
            text, data = b[0], b[1]
            btn = {"text": text}
            if len(b) > 2 and b[2]:
                btn["url"] = b[2]
            else:
                btn["callback_data"] = data
            line.append(btn)
        rows.append(line)
    return {"inline_keyboard": rows}


def tg_send_chat(chat_id, text, buttons=None, token=None):
    """Отправить текст в chat_id, опционально с инлайн-кнопками.
    buttons — см. _inline_keyboard. Возвращает message_id при успехе, иначе False."""
    if not token and not tg_enabled():
        log.info("Telegram выключен — пропуск отправки в %s", chat_id)
        return False
    if not chat_id:
        return False
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    kb = _inline_keyboard(buttons)
    if kb:
        payload["reply_markup"] = kb
    res = _call("sendMessage", payload, token=token)
    if res.get("ok"):
        return res["result"]["message_id"]
    return False


def tg_send_text(chat_id, text, buttons=None):
    return bool(tg_send_chat(chat_id, text, buttons=buttons))


def tg_edit_message(chat_id, message_id, text, buttons=None, token=None):
    """Отредактировать уже отправленное сообщение (например, после нажатия
    кнопки «Подтвердить» — убрать кнопки и показать «✅ Подтверждено»)."""
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    kb = _inline_keyboard(buttons)
    payload["reply_markup"] = kb or {"inline_keyboard": []}
    return _call("editMessageText", payload, token=token).get("ok", False)


def tg_answer_callback(callback_query_id, text="", token=None):
    """Убрать «часики» с кнопки после нажатия (и опционально показать всплывающее уведомление)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _call("answerCallbackQuery", payload, token=token).get("ok", False)


def tg_request_contact_keyboard():
    """Обычная (не инлайн) клавиатура с одной кнопкой «Поделиться номером» —
    только так Telegram разрешает запрашивать контакт пользователя."""
    return {
        "keyboard": [[{"text": "📱 Поделиться номером телефона", "request_contact": True}]],
        "resize_keyboard": True, "one_time_keyboard": True,
    }


def tg_send_contact_request(chat_id, text, token=None):
    payload = {
        "chat_id": chat_id, "text": text,
        "reply_markup": tg_request_contact_keyboard(),
    }
    res = _call("sendMessage", payload, token=token)
    return res.get("ok", False)


def tg_set_webhook(token, url):
    return _call("setWebhook", {"url": url, "allowed_updates": ["message", "callback_query"]}, token=token)


def tg_get_webhook_info(token):
    return _call("getWebhookInfo", {}, token=token)


def tg_get_me(token):
    return _call("getMe", {}, token=token)


def tg_delete_webhook(token):
    return _call("deleteWebhook", {}, token=token)
