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
import os
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


_MAX_HISTORY_TURNS = 12  # ~6 пар вопрос-ответ — держит контекст разговора, не раздувая запрос без предела

# Платформа/продукт — озвучивается ассистентом на вопрос «кто ты»/«на какой
# платформе ты работаешь» и т.п. ODONTIS — название самого продукта (видно на
# логотипе в сайдбаре, templates/newui/base.html), AKM SOFT CLINIC — вендор/
# разработчик платформы. Раньше система-промпт вообще не упоминал ни то, ни
# другое — ассистент не мог сказать, кто он и на чём работает (баг с прода).
PLATFORM_PRODUCT_NAME = "ODONTIS"
PLATFORM_VENDOR_NAME = "AKM SOFT CLINIC"
DEFAULT_ASSISTANT_NAME = "ODONTIS"


def ask_ai(question, history=None, assistant_name=None):
    """Возвращает (answer, error). Безопасно выключено, если ключ/folder_id
    не заданы — вызывающий код должен сам проверить ai_enabled() ДО вызова.

    history — список прошлых реплик [{role:'user'|'assistant', text:'...'}]
    (хранится и передаётся клиентом, base.html::voiceChatHistory — «помнить
    разговор» реализовано так, без серверной сессии/БД под это, сознательно
    просто: список растёт в JS-памяти вкладки, живёт до перезагрузки
    страницы). Обрезается до последних _MAX_HISTORY_TURNS реплик.

    assistant_name — как пользователь назвал ассистента (клиентская настройка,
    localStorage — см. base.html::getAssistantName; сервер её не хранит).
    Если не передано — представляется именем продукта по умолчанию."""
    import json as _json
    import urllib.request
    import urllib.error

    name = (assistant_name or "").strip() or DEFAULT_ASSISTANT_NAME
    folder_id = settings.YANDEX_FOLDER_ID
    model = getattr(settings, "YANDEX_MODEL", "") or "yandexgpt-lite"
    messages = [{"role": "system", "text": (
        f"Тебя зовут «{name}». Ты — голосовой ИИ-ассистент стоматологической "
        f"клиники, работаешь на платформе {PLATFORM_VENDOR_NAME}, в приложении "
        f"{PLATFORM_PRODUCT_NAME} (CRM для стоматологических клиник). Если "
        f"спросят, кто ты, как тебя зовут или на какой платформе ты работаешь — "
        f"так прямо и отвечай, не уклоняйся и не говори, что у тебя нет имени. "
        "Разговариваешь с врачами и администраторами клиники. Отвечай на ЛЮБЫЕ "
        "вопросы — и о работе клиники, и общие (медицина, повседневные темы, что "
        "угодно ещё), как обычный ИИ-помощник, а не узкий бот с фиксированным "
        "набором тем. Если чего-то не знаешь — так и скажи, не выдумывай. Отвечай "
        "кратко и по делу, разговорным тоном, на том же языке, на котором задан "
        "вопрос (русский, кыргызский, узбекский или английский). Ответ будет "
        "озвучен вслух — избегай списков, таблиц и markdown-разметки, формулируй "
        "обычными предложениями."
    )}]
    for turn in (history or [])[-_MAX_HISTORY_TURNS:]:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        text = (turn.get("text") or "").strip()
        if text:
            messages.append({"role": role, "text": text})
    messages.append({"role": "user", "text": question})
    body = {
        "modelUri": f"gpt://{folder_id}/{model}/latest",
        "completionOptions": {"stream": False, "temperature": 0.3, "maxTokens": "800"},
        "messages": messages,
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


def synthesize_speech(text):
    """Озвучивание ответа — Yandex SpeechKit TTS (тот же аккаунт/ключ, что и
    у YandexGPT — scope speechkit уже выдан). Возвращает (audio_bytes, error);
    audio_bytes — сырой OggOpus (совместим с HTML5 <audio> в Chrome/Firefox
    без доп. библиотек). Ограничение по длине текста (SpeechKit режет очень
    длинные) — обрезаем до разумного, озвучка не более пары абзацев не имеет
    смысла для голосового ассистента."""
    import urllib.request
    import urllib.error
    import urllib.parse

    folder_id = settings.YANDEX_FOLDER_ID
    voice = getattr(settings, "YANDEX_TTS_VOICE", "") or "alena"
    text = (text or "").strip()[:2000]
    if not text:
        return None, "Пустой текст для озвучки"
    params = urllib.parse.urlencode({
        "text": text,
        "lang": "ru-RU",
        "voice": voice,
        "format": "oggopus",
        "folderId": folder_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
        data=params,
        headers={"Authorization": f"Api-Key {settings.YANDEX_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read(), None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        log.warning("voice: YandexTTS HTTP %s: %s", e.code, detail)
        return None, "Не удалось озвучить ответ"
    except Exception as e:
        log.warning("voice: YandexTTS request failed: %s", e)
        return None, "Не удалось озвучить ответ"


_whisper_model = None


def _get_whisper_model():
    """Ленивая инициализация + кэш на весь процесс (per-worker gunicorn).
    WHISPER_MODEL_SIZE (по умолчанию "small") — компромисс скорость/качество
    для CPU-инференса на обычном сервере без GPU; можно уменьшить до "base"
    или "tiny", если сервер слабый, через env, без правки кода.
    WHISPER_MODEL_PATH — если указан, грузит модель из локальной папки
    (уже скачанные веса) вместо обращения к Hugging Face Hub — на случай,
    если и huggingface.co недоступен с сервера.

    Кэш-пути huggingface_hub по умолчанию — в домашней папке пользователя
    (~/.cache/huggingface), а systemd-сервис запущен от www-data, чья "домашняя"
    /var/www принадлежит root и недоступна на запись. Одного download_root
    (передаётся в WhisperModel — влияет только на путь основного снапшота
    модели) НЕДОСТАТОЧНО: у huggingface_hub есть отдельный ускоритель загрузки
    "hf_xet" (xet-core), который пишет СВОИ логи в $HF_HOME/xet/logs/ в обход
    download_root — поймано в проде: "Permission denied:
    '/var/www/.cache/huggingface/xet/logs/...'", хотя WhisperModel уже
    вызывался с explicit download_root. Поэтому переменная окружения HF_HOME
    выставляется явно, ДО первого импорта huggingface_hub/faster_whisper —
    так весь кэш (и основной, и вспомогательные вроде xet) остаётся внутри
    settings.BASE_DIR/whisper_cache, которая уже принадлежит www-data
    (deploy/update.sh делает chown -R на весь проект)."""
    global _whisper_model
    if _whisper_model is None:
        cache_dir = str(settings.BASE_DIR / "whisper_cache")
        os.environ.setdefault("HF_HOME", cache_dir)
        from faster_whisper import WhisperModel
        model_path = getattr(settings, "WHISPER_MODEL_PATH", "")
        model_size = getattr(settings, "WHISPER_MODEL_SIZE", "small")
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
_FIND_PATIENT_KEYWORDS = ("найди", "найти", "поиск", "ищи", "искать")
# «Открой»/«покажи» сами по себе слишком общие (используются и для команды
# расписания, "покажи/открой расписание") — как триггер открытия пациента
# засчитываются, только когда РЯДОМ есть слово-предмет "про пациента"
# (карточка/визит/история и т.п., см. _PATIENT_SUBJECT_WORDS ниже). Без такого
# слова-предмета "найди"/"найти"/"поиск"/"ищи"/"искать" по-прежнему достаточно
# самих по себе (однозначно про поиск, не про расписание).
_OPEN_PATIENT_ACTION_WORDS = ("найди", "найти", "поиск", "ищи", "искать", "открой", "открыть", "покажи", "показать")
_PATIENT_SUBJECT_WORDS = ("пациент", "карточк", "карту", "визит", "истори")
_FIND_PATIENT_STOPWORDS = {
    "найди", "найти", "поиск", "ищи", "искать", "открой", "открыть", "покажи", "показать",
    "пациента", "пациент", "пациенту", "мне", "карточку", "карточка", "карты", "карту",
    "визиты", "визит", "визита", "визитов", "историю", "истории", "у",
}
_DOCTOR_COUNT_KEYWORDS = ("сколько",)
_DOCTOR_COUNT_TOPIC_WORDS = ("приём", "прием", "записи", "запись", "записей", "пациентов", "визит")
_DOCTOR_COUNT_STOPWORDS = {
    "сколько", "приёмов", "приемов", "приём", "прием", "записи", "запись", "записей",
    "пациентов", "визитов", "визит", "визита", "у", "врача", "доктора", "сегодня", "завтра",
}
# «Открой список пациентов»/«покажи всех пациентов» — раньше не было отдельного
# намерения: "открой"/"покажи" (_OPEN_PATIENT_ACTION_WORDS) + "пациентов"
# (подстрока "пациент" из _PATIENT_SUBJECT_WORDS входит и в "пациентов") уже
# засчитывались как find_patient, а "пациентов"/"список" не входили в
# _FIND_PATIENT_STOPWORDS — команда без единого настоящего имени превращалась
# в поиск несуществующего пациента "список пациентов" → «Пациент не найден»
# (баг с прода). Эти слова добавлены в стоп-лист ИМЕННО для случая "имени нет
# вообще" — после их вычитания из фразы пустой остаток означает "открыть
# список", а не "найти пациента по имени «список»".
_PATIENT_LIST_STOPWORDS = {"список", "списки", "всех", "пациентов", "весь"}

_MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
# «Расписание на 21 августа» — конкретная дата словами (родительный падеж
# названия месяца — единственная форма, которую реально говорят в этой
# конструкции, "21 август"/"21 августе" не встречается на практике).
_DATE_WORD_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_MONTHS_RU.keys()) + r")\b"
)
# «3 дня вперёд» / «на 3 дня вперёд» / «через 3 дня» / «через неделю».
_DAYS_FORWARD_RE = re.compile(r"(\d+)\s*дн\w*\s*впер(?:ё|е)д")
_THROUGH_DAYS_RE = re.compile(r"через\s+(\d+)\s*дн\w*")
_THROUGH_WEEK_RE = re.compile(r"через\s+недел\w*")

# «Как тебя зовут»/«кто ты»/«представься» — узнаваемая фраза-идентичность
# обрабатывается правилом, а не только общим ИИ-чатом (ask_ai) — так ответ
# гарантированно верный (платформа/имя) даже если YandexGPT не настроен
# (ai_enabled()==False) или просто ответит расплывчато. Порядок проверки в
# parse_schedule_command — САМЫЙ первый, чтобы не быть перехваченным другими
# намерениями (например «кто ты» само по себе не пересекается ни с чем
# другим, но лучше не рисковать).
_IDENTITY_PHRASES = (
    "как тебя зовут", "как тебя называть", "твоё имя", "твое имя", "кто ты",
    "что ты за", "представься", "расскажи о себе", "на какой платформе",
    "чей ты", "кто тебя сделал", "кто тебя создал",
)


def _extract_relative_date(text, today):
    if "послезавтра" in text:
        return today + datetime.timedelta(days=2)
    if "завтра" in text:
        return today + datetime.timedelta(days=1)
    if "сегодня" in text:
        return today
    m = _DATE_WORD_RE.search(text)
    if m:
        day, month = int(m.group(1)), _MONTHS_RU[m.group(2)]
        year = today.year
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            return None  # «31 февраля» и т.п. — невалидная дата, не гадаем
        if d < today:
            d = datetime.date(year + 1, month, day)  # «на 1 января», сказанное в декабре — про следующий год
        return d
    m = _DAYS_FORWARD_RE.search(text) or _THROUGH_DAYS_RE.search(text)
    if m:
        return today + datetime.timedelta(days=int(m.group(1)))
    if _THROUGH_WEEK_RE.search(text):
        return today + datetime.timedelta(days=7)
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


def _strip_words(transcript, stopwords):
    kept = [w for w in transcript.split() if w.lower().strip(",.") not in stopwords]
    return " ".join(kept).strip(" ,.") or None


def parse_schedule_command(transcript, today_iso):
    """Возвращает dict {intent, date, patient_name, status, doctor_name} —
    intent='unknown', если команда не распознана как одно из поддерживаемых
    действий. Единый разбор для расписания, поиска пациента и подсчёта
    приёмов врача — используется и на странице расписания, и на любой другой
    (виджет вызывает его же, если ни диктовка, ни специфичная для страницы
    команда не подошли, см. handleAssistantCommand в base.html)."""
    text = transcript.lower()
    today = datetime.date.fromisoformat(today_iso)
    empty = {"intent": "unknown", "date": None, "patient_name": None, "status": None, "doctor_name": None}

    # «Как тебя зовут»/«кто ты» — проверяется первой, до всех остальных
    # намерений (см. комментарий у _IDENTITY_PHRASES выше).
    if any(p in text for p in _IDENTITY_PHRASES):
        return {**empty, "intent": "identity"}

    # «найди пациента Иванова» / «открой визиты у Мадакимова Акмалидина» /
    # «покажи карточку Петровой» — раньше без реального поиска команда просто
    # уходила в общий вопрос к ИИ, который не видит базу пациентов клиники и
    # ничего не находил. Реальный поиск — на клиенте (patientsList уже
    # загружен), здесь только вычленяем имя. "Открой"/"покажи" сами по себе
    # слишком общие (см. show_date ниже — та же пара слов означает "открой
    # расписание"), поэтому засчитываются как триггер открытия ИМЕННО
    # пациента только вместе со словом-предметом (карточка/визит/история и
    # т.п.) — проверяется ПЕРЕД show_date, чтобы не давать более общей ветке
    # перехватить команду. "Найди"/"найти"/"поиск"/"ищи"/"искать" однозначны
    # сами по себе — сохранена и старая форма без слова-предмета.
    has_open_action = any(kw in text for kw in _OPEN_PATIENT_ACTION_WORDS)
    has_patient_subject = any(kw in text for kw in _PATIENT_SUBJECT_WORDS)
    if (has_open_action and has_patient_subject) or any(kw in text for kw in _FIND_PATIENT_KEYWORDS):
        name = _strip_words(transcript, _FIND_PATIENT_STOPWORDS | _PATIENT_LIST_STOPWORDS)
        if name:
            return {**empty, "intent": "find_patient", "patient_name": name}
        # Осталось пусто после вычитания служебных слов (включая «список»/
        # «всех») — не было названо ни одного имени, команда была про список
        # целиком: «открой список пациентов», «покажи всех пациентов».
        if has_open_action:
            return {**empty, "intent": "open_patients_list"}

    # «сколько приёмов у Ивановой сегодня» — тоже реальные данные на клиенте
    # (scheduleRealData), не вопрос к ИИ.
    if any(kw in text for kw in _DOCTOR_COUNT_KEYWORDS) and any(w in text for w in _DOCTOR_COUNT_TOPIC_WORDS):
        doctor_name = _strip_words(transcript, _DOCTOR_COUNT_STOPWORDS)
        date = _extract_relative_date(text, today) or today
        if doctor_name:
            return {**empty, "intent": "doctor_appointments", "doctor_name": doctor_name, "date": date.isoformat()}

    if "расписан" in text or "покажи" in text or "открой" in text:
        # Дата не названа явно («покажи расписание») — раньше это тоже
        # уходило в unknown → общий вопрос к ИИ, хотя разумный дефолт
        # очевиден: сегодняшний день.
        date = _extract_relative_date(text, today) or today
        return {**empty, "intent": "show_date", "date": date.isoformat()}

    for keywords, status in _STATUS_KEYWORDS:
        matched = [kw for kw in keywords if kw in text]
        if matched:
            name = _extract_patient_name(transcript, matched)
            return {**empty, "intent": "mark_status", "patient_name": name, "status": status}

    return empty


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
