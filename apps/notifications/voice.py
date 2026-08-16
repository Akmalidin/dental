"""Голосовой ввод для врачей — распознавание речи и разбор команд.

Изначально использовал OpenAI Whisper API + GPT для разбора команд, но
OpenAI полностью блокирует API-доступ из России (403
unsupported_country_region_territory — санкционное ограничение на стороне
OpenAI, не лечится ни ключом, ни кодом). Сервер клиники — российский IP,
поэтому транскрипция переведена на локальный self-hosted Whisper
(faster-whisper, работает на CPU, ничего никуда не отправляет), а разбор
команд по расписанию/карте приёма — на простые правила (regex/ключевые
слова) вместо GPT, тоже полностью офлайн.

Переменная `OPENAI_ENABLED` в settings оставлена как есть (просто общий
тумблер «голосовой ввод включён») — переименовывать её и просить
пользователя ещё раз лезть в серверный .env смысла не было. `OPENAI_API_KEY`
больше нигде не используется.

Модель Whisper грузится лениво (при первом запросе) и кэшируется в памяти
процесса — иначе каждая транскрипция заново грузила бы веса модели (заметно
дольше самой распознавания). Первый запрос после перезапуска сервиса будет
медленнее обычного — сначала модель либо скачивается с Hugging Face Hub
(нужен исходящий доступ к huggingface.co — он НЕ входит в тот же санкционный
список, что и OpenAI, но если и он заблокирован, см. WHISPER_MODEL_PATH
ниже), либо просто загружается с диска, если уже скачана раньше."""
import logging
import re
import datetime
from io import BytesIO

from django.conf import settings

log = logging.getLogger("apps")


def voice_enabled():
    return bool(getattr(settings, "OPENAI_ENABLED", False))


# ---- Свободный вопрос-ответ (ИИ-помощник) — YandexGPT ----
# OpenAI/большинство западных LLM недоступны из России (см. voice_enabled
# выше и историю в git log) — для «отвечай на любые вопросы» используется
# YandexGPT (Yandex Cloud Foundation Models), доступен из РФ без ограничений.
# Используется и голосовым виджетом (свободный вопрос, когда ни диктовка, ни
# команда по расписанию/приёму не подошли), и текстовым чатом «ИИ-помощник»
# в Отчётах (apps/notifications/views.py::voice_command, mode=chat).
# Простой urllib, как и apps/notifications/whatsapp.py — без лишней
# HTTP-библиотеки в зависимостях ради одного эндпоинта.
def ai_enabled():
    return bool(getattr(settings, "YANDEX_API_KEY", "") and getattr(settings, "YANDEX_FOLDER_ID", ""))


def ask_ai(question):
    """Возвращает (answer, error). Безопасно выключено, если ключ/folder_id
    не заданы — вызывающий код должен сам проверить ai_enabled() ДО вызова."""
    import json as _json
    import urllib.request
    import urllib.error

    folder_id = settings.YANDEX_FOLDER_ID
    model = getattr(settings, "YANDEX_MODEL", "") or "yandexgpt-lite"
    body = {
        "modelUri": f"gpt://{folder_id}/{model}/latest",
        "completionOptions": {"stream": False, "temperature": 0.3, "maxTokens": "800"},
        "messages": [
            {"role": "system", "text": (
                "Ты — ассистент стоматологической клиники. Отвечай кратко и по делу "
                "на вопросы врачей и администраторов о работе клиники. Отвечай на том "
                "же языке, на котором задан вопрос (русский, кыргызский или узбекский)."
            )},
            {"role": "user", "text": question},
        ],
    }
    req = urllib.request.Request(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        data=_json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {settings.YANDEX_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        answer = data["result"]["alternatives"][0]["message"]["text"]
        return answer.strip(), None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        log.warning("voice: YandexGPT HTTP %s: %s", e.code, detail)
        return None, "Не удалось получить ответ от ИИ"
    except Exception as e:
        log.warning("voice: YandexGPT request failed: %s", e)
        return None, "Не удалось получить ответ от ИИ"


_whisper_model = None


def _get_whisper_model():
    """Ленивая инициализация + кэш на весь процесс (per-worker gunicorn).
    WHISPER_MODEL_SIZE (по умолчанию "small") — компромисс скорость/качество
    для CPU-инференса на обычном сервере без GPU; можно уменьшить до "base"
    или "tiny", если сервер слабый, через env, без правки кода.
    WHISPER_MODEL_PATH — если указан, грузит модель из локальной папки
    (уже скачанные веса) вместо обращения к Hugging Face Hub — на случай,
    если и huggingface.co недоступен с сервера.

    download_root указан явно (settings.BASE_DIR/whisper_cache) — иначе
    huggingface_hub по умолчанию кэширует в домашнюю папку пользователя
    (~/.cache), а systemd-сервис обычно запущен от www-data без прав на
    запись туда (поймано в проде: "Permission denied: '/var/www/sadaf/.cache'").
    Папка внутри WorkingDirectory уже принадлежит www-data (deploy/update.sh
    делает chown -R на весь проект), поэтому создаётся без проблем с правами."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_path = getattr(settings, "WHISPER_MODEL_PATH", "")
        model_size = getattr(settings, "WHISPER_MODEL_SIZE", "small")
        cache_dir = str(settings.BASE_DIR / "whisper_cache")
        log.info("voice: loading Whisper model %r (первый запуск — может занять время)", model_path or model_size)
        if model_path:
            _whisper_model = WhisperModel(model_path, device="cpu", compute_type="int8")
        else:
            _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=cache_dir)
    return _whisper_model


def transcribe_audio(file_obj, filename="voice.webm"):
    """file_obj — Django UploadedFile (request.FILES['audio']). Возвращает
    (text, error) — error=None при успехе, иначе text=''."""
    try:
        content = file_obj.read()
        model = _get_whisper_model()
        # vad_filter — обрезает тишину по краям записи (voice activity
        # detection), без него faster-whisper иногда «галлюцинирует» текст
        # на пустом/шумном звуке. language=None — автоопределение (ru/ky/en).
        segments, _info = model.transcribe(BytesIO(content), vad_filter=True, language=None)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, None
    except Exception as e:
        log.warning("voice: transcribe failed: %s", e)
        return "", "Не удалось распознать речь"


# ---- Расписание: «покажи расписание на завтра», «отметь Иванова пришедшим» ----
# Простой разбор по ключевым словам вместо GPT (офлайн, без внешних вызовов).
# Менее гибко, чем LLM, но для этих двух конкретных сценариев — рабочий
# минимум; при желании легко заменить эту функцию на вызов любой доступной
# в регионе LLM (YandexGPT/GigaChat и т.п.), сигнатура (transcript, today_iso)
# → dict останется той же, вызывающий код (apps/notifications/views.py) не
# меняется.
_WEEKDAYS_RU = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2,
    "четверг": 3, "пятница": 4, "пятницу": 4,
    "суббота": 5, "субботу": 5, "воскресенье": 6,
}
_STATUS_KEYWORDS = [
    (("приш",), "arrived"),          # пришёл/пришел/пришла/пришли/пришедший/пришедшим/...
    (("подтверд", "подтвержд"), "confirmed"),  # подтверди(ть) — подтверждён (д/жд чередование)
    (("отмен",), "cancelled"),       # отмени(ть)/отмена/отменён/отменена — общий корень
]
_SCHEDULE_STOPWORDS = {
    "отметь", "отметить", "пациента", "пациент", "запись", "как", "что", "его", "её", "ее",
    "статус", "визит", "приём", "прием",
}


def _extract_relative_date(text, today):
    if "послезавтра" in text:
        return today + datetime.timedelta(days=2)
    if "завтра" in text:
        return today + datetime.timedelta(days=1)
    if "сегодня" in text:
        return today
    for name, weekday in _WEEKDAYS_RU.items():
        if name in text:
            delta = (weekday - today.weekday()) % 7
            delta = delta or 7  # «на понедельник», сказанное в понедельник — про следующий, не про сегодня
            return today + datetime.timedelta(days=delta)
    return None


def _extract_patient_name(transcript, matched_stems):
    """matched_stems — корни слов ("приш", "отмен" и т.п.), а не целые формы,
    поэтому здесь проверка на вхождение подстроки, а не точное совпадение
    (иначе "пришедшим" не отфильтровался бы, т.к. не равен корню "приш")."""
    kept = []
    for w in transcript.split():
        wl = w.lower().strip(",.")
        if wl in _SCHEDULE_STOPWORDS or any(stem in wl for stem in matched_stems):
            continue
        kept.append(w)
    name = " ".join(kept).strip(" ,.")
    return name or None


def parse_schedule_command(transcript, today_iso):
    """Возвращает dict {intent, date, patient_name, status} — intent='unknown',
    если команда не распознана как одно из поддерживаемых действий."""
    text = transcript.lower()
    today = datetime.date.fromisoformat(today_iso)

    if "расписан" in text or "покажи" in text or "открой" in text:
        date = _extract_relative_date(text, today)
        if date:
            return {"intent": "show_date", "date": date.isoformat(), "patient_name": None, "status": None}

    for keywords, status in _STATUS_KEYWORDS:
        matched = [kw for kw in keywords if kw in text]
        if matched:
            name = _extract_patient_name(transcript, matched)
            return {"intent": "mark_status", "date": None, "patient_name": name, "status": status}

    return {"intent": "unknown", "date": None, "patient_name": None, "status": None}


# ---- Карта приёма: «зуб 26, композитная пломба, скидка 10%» ----
# Тот же офлайн-подход: номера зубов и скидка — регуляркой, название услуги —
# то, что осталось после вычитания распознанных чисел/служебных слов (само
# сопоставление с конкретной услугой клиники — на клиенте, по servicesList,
# см. handleVoiceVisitIntent в base.html).
_FDI_TEETH = set(range(11, 19)) | set(range(21, 29)) | set(range(31, 39)) | set(range(41, 49))
_DISCOUNT_RE = re.compile(r"скидк\w*\s*(\d+(?:[.,]\d+)?)\s*(?:процент\w*|%)?")
_TOOTH_RE = re.compile(r"\b(\d{2})\b")


def parse_visit_command(transcript):
    """Возвращает dict {intent, teeth, service_query, discount_pct} —
    intent='unknown', если в фразе не нашлось ни одного номера зуба по FDI."""
    text = transcript.lower()

    # Скидку вырезаем ИЗ ТЕКСТА ПЕРВЫМ ДЕЛОМ, до поиска номеров зубов — иначе
    # "скидка 15%" сама попадает в диапазон FDI (11-18) и ложно распознаётся
    # как ещё один зуб.
    discount_pct = None
    discount_match = _DISCOUNT_RE.search(text)
    text_wo_discount = text
    if discount_match:
        discount_pct = float(discount_match.group(1).replace(",", "."))
        text_wo_discount = text[:discount_match.start()] + text[discount_match.end():]

    teeth = []
    for m in _TOOTH_RE.finditer(text_wo_discount):
        n = int(m.group(1))
        if n in _FDI_TEETH and n not in teeth:
            teeth.append(n)

    if not teeth:
        return {"intent": "unknown", "teeth": [], "service_query": None, "discount_pct": None}

    cleaned = text_wo_discount
    cleaned = re.sub(r"\bзуб\w*\b", " ", cleaned)
    cleaned = _TOOTH_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:и|а|но|или)\b", " ", cleaned)  # союзы — не часть названия услуги
    cleaned = re.sub(r"[,.]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    service_query = cleaned or None

    return {"intent": "add_tooth_service", "teeth": teeth, "service_query": service_query, "discount_pct": discount_pct}
