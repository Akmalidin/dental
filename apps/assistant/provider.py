"""Провайдер ответов ассистента.

OpenAI основной: только он умеет function calling, то есть сам решает,
каким инструментом прочитать данные клиники. Запасной — уже работающий
YandexGPT (apps/notifications/voice.py::ask_ai): он отвечает на общие
вопросы, но данных клиники не видит. Такой запас важен: без него любой
сбой у OpenAI превращал бы ассистента в неработающую кнопку.

HTTP через urllib, как в apps/notifications/whatsapp.py и voice.py — в
проекте намеренно не тянут HTTP-библиотеку ради одного эндпоинта.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger("apps")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT = 30


def openai_available():
    return bool(getattr(settings, "OPENAI_API_KEY", ""))


def _post_openai(body):
    """Единственное место, где провайдер ходит в сеть — в тестах мокается."""
    req = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % settings.OPENAI_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        log.warning("assistant: OpenAI ответил %s", exc.code)
        return None, "ИИ-сервис вернул ошибку %s" % exc.code
    except Exception as exc:
        log.warning("assistant: OpenAI недоступен: %s", exc)
        return None, "ИИ-сервис недоступен"


def complete(messages, tools=None):
    """Один обмен с моделью. Возвращает (результат, ошибка).

    Результат это либо готовый текст, либо просьба вызвать инструмент:
    {"kind": "text", "text": ...} или {"kind": "tool", "name": ..., "args": {...}}
    """
    if not openai_available():
        return None, "Ключ OpenAI не задан"
    body = {
        "model": getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    payload, error = _post_openai(body)
    if error:
        return None, error
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None, "Неожиданный ответ ИИ-сервиса"
    calls = message.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            return None, "ИИ вернул неразборчивые параметры инструмента"
        return {"kind": "tool", "name": fn.get("name") or "", "args": args}, None
    return {"kind": "text", "text": (message.get("content") or "").strip()}, None


def fallback_answer(question, history):
    """Ответ без доступа к данным — через уже работающий YandexGPT.

    history в формате, который ждёт ask_ai: [{"role": ..., "text": ...}].
    """
    from apps.notifications.voice import ai_enabled, ask_ai

    if not ai_enabled():
        return None, "ИИ-помощник не настроен"
    return ask_ai(question, history=history)
