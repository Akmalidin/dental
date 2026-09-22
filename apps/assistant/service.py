"""Оркестрация ответа ассистента: память, модель, инструменты.

Модель не получает идентификатор клиники и не может его подставить —
инструменты сами читают текущую клинику из запроса (apps/assistant/tools.py).
"""
import json
import logging

from django.utils import timezone

from apps.assistant import provider
from apps.assistant.models import Conversation
from apps.assistant.tools import openai_schemas, run_tool

log = logging.getLogger("apps")

# Максимум обращений к модели на один вопрос: первое выбирает инструмент,
# второе формулирует ответ по его данным. Без потолка зациклившаяся модель
# перебирала бы инструменты бесконечно и жгла бюджет.
MAX_ROUNDS = 2

DEFAULT_ASSISTANT_NAME = "ODONTIS"

SYSTEM_PROMPT = (
    "Тебя зовут %s. Ты — помощник сотрудников стоматологической клиники в "
    "системе ODONTIS. Отвечай кратко и по-русски. Данные о пациентах, записях "
    "и финансах бери ТОЛЬКО через инструменты — ничего не придумывай и не "
    "оценивай на глаз. Если инструмент вернул пусто, так и скажи. Ты работаешь "
    "только с данными своей клиники. Сегодня %s."
)


def _history_for_model(conv):
    """Историю беседы переводим в формат сообщений OpenAI."""
    return [{"role": m.role, "content": m.text} for m in conv.recent() if m.text]


def _history_for_fallback(conv):
    """ask_ai ждёт другой формат: [{"role": ..., "text": ...}]."""
    return [{"role": m.role, "text": m.text} for m in conv.recent() if m.text]


def answer(user, question, assistant_name=""):
    """Ответ на вопрос сотрудника. Возвращает (текст, ошибка)."""
    question = (question or "").strip()
    if not question:
        return None, "Пустой вопрос"

    conv = Conversation.active_for(user)
    conv.add("user", question)

    if not provider.openai_available():
        return _fallback(conv, question)

    name = (assistant_name or "").strip() or DEFAULT_ASSISTANT_NAME
    messages = [{"role": "system",
                 "content": SYSTEM_PROMPT % (name, timezone.localdate())}]
    messages.extend(_history_for_model(conv))

    used_tool, used_args, used_rows = "", None, None

    for _ in range(MAX_ROUNDS):
        result, error = provider.complete(messages, tools=openai_schemas())
        if error:
            log.warning("assistant: OpenAI не ответил (%s), уходим на запасной", error)
            return _fallback(conv, question)

        if result["kind"] == "text":
            text = result["text"]
            conv.add("assistant", text, tool_name=used_tool,
                     tool_args=used_args, rows_count=used_rows)
            return text, None

        # Модель попросила инструмент — выполняем и отдаём ей результат.
        rows, tool_error = run_tool(result["name"], user, result["args"])
        used_tool, used_args = result["name"], result["args"]
        used_rows = None if tool_error else len(rows)
        payload = tool_error if tool_error else json.dumps(rows, ensure_ascii=False, default=str)
        messages.append({
            "role": "user",
            "content": "Результат инструмента %s: %s" % (result["name"], payload),
        })

    # Круги кончились, а текста модель так и не дала.
    return _fallback(conv, question)


def _fallback(conv, question):
    """Запасной путь: отвечаем без доступа к данным клиники."""
    text, error = provider.fallback_answer(question, _history_for_fallback(conv))
    if error:
        return None, error
    conv.add("assistant", text)
    return text, None
