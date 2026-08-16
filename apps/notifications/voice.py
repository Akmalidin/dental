"""Голосовой ввод для врачей (Whisper — транскрипция, GPT — разбор команды
по расписанию). Безопасно выключено, если OPENAI_ENABLED!=1 или нет ключа —
вызывающий код (apps/notifications/views.py::voice_command) должен сам
проверить voice_enabled() ДО вызова, эти функции при выключенном флаге не
вызываются вообще (а не тихо возвращают пустоту), чтобы ошибка была видна
на этапе разработки, а не терялась в проде.

Ключ — только из env (OPENAI_API_KEY, см. config/settings/development.py),
никогда не в репозитории. Записи не сохраняются: аудио транскрибируется и
отбрасывается, TreatmentFile не создаётся."""
import json
import logging

from django.conf import settings

log = logging.getLogger("apps")


def voice_enabled():
    return bool(getattr(settings, "OPENAI_ENABLED", False) and getattr(settings, "OPENAI_API_KEY", ""))


def _client():
    from openai import OpenAI  # импорт лениво — пакет не обязателен, если фича выключена
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def transcribe_audio(file_obj, filename="voice.webm"):
    """file_obj — Django UploadedFile (request.FILES['audio']). Возвращает
    (text, error) — error=None при успехе, иначе text=''.

    Django UploadedFile — не то же самое, что io.IOBase (openai-python
    принимает bytes/io.IOBase/PathLike/(filename, content, content_type) —
    именно последний вариант нужен здесь, иначе SDK отказывается его
    принимать, см. openai-python#file-uploads)."""
    try:
        content = file_obj.read()
        resp = _client().audio.transcriptions.create(
            model="whisper-1",
            file=(filename, content, file_obj.content_type or "audio/webm"),
        )
        return (resp.text or "").strip(), None
    except Exception as e:
        log.warning("voice: transcribe failed: %s", e)
        return "", "Не удалось распознать речь"


SCHEDULE_INTENT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "schedule_intent",
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["show_date", "mark_status", "unknown"]},
                "date": {"type": ["string", "null"], "description": "ISO YYYY-MM-DD, только для show_date"},
                "patient_name": {"type": ["string", "null"], "description": "Имя/фамилия пациента, если названы, для mark_status"},
                "status": {"type": ["string", "null"], "enum": ["arrived", "confirmed", "cancelled", None], "description": "Только для mark_status"},
            },
            "required": ["intent", "date", "patient_name", "status"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def parse_schedule_command(transcript, today_iso):
    """Возвращает dict {intent, date, patient_name, status} — intent='unknown',
    если команда не распознана как одно из поддерживаемых действий."""
    system = (
        f"Сегодня {today_iso}. Ты разбираешь голосовую команду врача на русском/"
        "кыргызском/английском по расписанию стоматологической клиники. "
        "Поддерживаемые намерения: show_date (показать расписание на дату — "
        "верни абсолютную ISO-дату, вычисленную от сегодняшней), mark_status "
        "(изменить статус записи пациента — arrived/confirmed/cancelled). "
        "Если команда не про это — intent='unknown'."
    )
    try:
        resp = _client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": transcript}],
            response_format=SCHEDULE_INTENT_SCHEMA,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        log.warning("voice: intent parse failed: %s", e)
        return {"intent": "unknown", "date": None, "patient_name": None, "status": None}


# ---- Карта приёма: «зуб 26, композитная пломба, скидка 10%» ----
# Само распознавание номеров зубов/названия услуги/скидки — на сервере (GPT),
# но сопоставление названия услуги с конкретной услугой клиники (по
# servicesList, уже загруженному на странице) и сам вызов
# toggleToothSelect/vwToothServicePick/vwSetDiscountForTooth — на клиенте,
# теми же функциями, что и обычный клик мышью по зубу/поиску услуги. Здесь
# только разбор речи, ни одна БД-запись отсюда не создаётся.
VISIT_INTENT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "visit_intent",
        "schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["add_tooth_service", "unknown"]},
                "teeth": {"type": "array", "items": {"type": "integer"}, "description": "Номера зубов по FDI (11-18,21-28,31-38,41-48)"},
                "service_query": {"type": ["string", "null"], "description": "Как врач назвал услугу — сырой текст, сопоставление с каталогом на клиенте"},
                "discount_pct": {"type": ["number", "null"], "description": "Скидка в процентах, если названа"},
            },
            "required": ["intent", "teeth", "service_query", "discount_pct"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def parse_visit_command(transcript):
    """Возвращает dict {intent, teeth, service_query, discount_pct} —
    intent='unknown', если команда не про зуб/услугу приёма."""
    system = (
        "Ты разбираешь голосовую команду врача-стоматолога во время приёма, на "
        "русском/кыргызском/английском. Врач диктует, какой зуб(ы) лечил, какой "
        "услугой и с какой скидкой (в процентах, если названа). Номера зубов — "
        "по международной системе FDI (11-18, 21-28, 31-38, 41-48), двузначные "
        "числа. Если несколько зубов — верни все. Если это не про зуб/услугу — "
        "intent='unknown'."
    )
    try:
        resp = _client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": transcript}],
            response_format=VISIT_INTENT_SCHEMA,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        log.warning("voice: visit intent parse failed: %s", e)
        return {"intent": "unknown", "teeth": [], "service_query": None, "discount_pct": None}
