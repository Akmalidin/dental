"""Голосовой ИИ-помощник клиники на OpenAI (сервер в Германии — API доступен).

Что умеет (врач/администратор говорит или пишет в панели ассистента):
- записать пациента: найдёт пациента (или заведёт нового по имени и
  телефону), врача и свободное время, и предложит запись — создаётся она
  только после подтверждения (кнопка «Записать» или ответ «да»);
- ответить на вопросы: приёмы врача на день, свободное время, карточка
  пациента (долг, прошлые и будущие визиты, аллергии), услуги и цены,
  финансы клиники (только тем, у кого есть доступ к разделу «Финансы»),
  и любые общие вопросы;
- на карте приёма: «зуб 36 композитная пломба, 47 удаление» — сам находит
  услуги в прайсе и добавляет строки в план лечения (те же функции, что и
  клик мышью, врач сразу видит и может поправить).

Модель сама ничего не пишет в БД: инструменты чтения выполняются здесь,
а изменения — либо через подтверждение (assistant_confirm), либо на
клиенте уже существующими функциями карты приёма. Ключ — только из env
(OPENAI_API_KEY), модели настраиваются переменными OPENAI_MODEL,
OPENAI_TRANSCRIBE_MODEL, OPENAI_TTS_MODEL, OPENAI_TTS_VOICE.
"""
import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

log = logging.getLogger("apps")

API = "https://api.openai.com/v1"
CHAT_FALLBACKS = ("gpt-4.1-mini", "gpt-4o-mini")
MAX_TOOL_ROUNDS = 6
CONFIRM_SALT = "assistant-appointment"
CONFIRM_MAX_AGE = 30 * 60
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def ensure_clinic(request):
    """Ассистент всегда работает в одной клинике — той же, что видна в
    интерфейсе (apps.users.newui_views._render: текущая клиника или клиника
    пользователя). У супер-админа без выбранной клиники текущей клиники нет,
    и менеджеры моделей отдавали бы данные ВСЕХ клиник платформы (баг: «в
    клинике 21 врач», хотя в SADAF их двое). Сбрасывает CurrentClinicMiddleware
    в конце запроса."""
    from apps.tenancy import get_current_clinic, set_current_clinic
    clinic = get_current_clinic()
    if clinic is None and getattr(request.user, "clinic", None) is not None:
        clinic = request.user.clinic
        set_current_clinic(clinic)
    return clinic


def _clinic():
    from apps.tenancy import get_current_clinic
    return get_current_clinic()


def openai_enabled():
    return bool(getattr(settings, "OPENAI_API_KEY", ""))


def _key():
    return settings.OPENAI_API_KEY


def _request(path, data, content_type="application/json", timeout=45, raw=False):
    """POST к OpenAI. Возвращает (ответ, ошибка): dict (или bytes при raw)."""
    if content_type == "application/json":
        data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method="POST", headers={
        "Authorization": "Bearer %s" % _key(), "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return (body if raw else json.loads(body.decode("utf-8"))), None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        log.warning("assistant: OpenAI %s HTTP %s: %s", path, e.code, detail)
        return None, (e.code, detail)
    except Exception as e:  # noqa: BLE001
        log.warning("assistant: OpenAI %s failed: %s", path, e)
        return None, (0, str(e))


def _model_missing(err):
    return err and err[0] in (400, 404) and "model" in (err[1] or "").lower()


# ── Распознавание речи и озвучка ─────────────────────────────────────────

def transcription_prompt():
    """Подсказка распознаванию: стоматологические слова, врачи и услуги
    клиники — так «композитная пломба», «эндодонтия» и фамилии врачей
    распознаются заметно точнее."""
    words = ["зуб", "пломба", "композит", "удаление", "кариес", "пульпит", "каналы", "коронка",
             "имплант", "чистка", "снимок", "запиши", "пациент", "tish", "plomba"]
    try:
        from apps.users.models import clinic_doctors
        from apps.services.models import Service
        words += [d.name for d in clinic_doctors(_clinic())[:20]]
        words += list(Service.objects.filter(is_active=True).values_list("name", flat=True)[:60])
    except Exception:  # noqa: BLE001
        pass
    return ", ".join(words)[:900]


def transcribe(file_obj, filename="voice.webm"):
    """Аудио → текст через OpenAI. Возвращает (text, error)."""
    boundary = uuid.uuid4().hex
    audio = file_obj.read()
    # Голосовые WhatsApp/Telegram приходят как .oga/.opus — это ogg, но OpenAI
    # принимает только расширение .ogg («Unsupported file format oga»).
    base, _dot, ext = (filename or "voice.ogg").rpartition(".")
    if ext.lower() in ("oga", "opus"):
        filename = (base or "voice") + ".ogg"
    model = getattr(settings, "OPENAI_TRANSCRIBE_MODEL", "") or "gpt-4o-mini-transcribe"

    def body_for(m):
        parts = []
        for name, value in (("model", m), ("prompt", transcription_prompt()), ("response_format", "json")):
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                          % (boundary, name, value)).encode("utf-8"))
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                      "Content-Type: application/octet-stream\r\n\r\n" % (boundary, filename)).encode("utf-8"))
        parts.append(audio + b"\r\n")
        parts.append(("--%s--\r\n" % boundary).encode("utf-8"))
        return b"".join(parts)

    ctype = "multipart/form-data; boundary=%s" % boundary
    data, err = _request("/audio/transcriptions", body_for(model), content_type=ctype, timeout=60)
    if err and _model_missing(err) and model != "whisper-1":
        data, err = _request("/audio/transcriptions", body_for("whisper-1"), content_type=ctype, timeout=60)
    if err:
        return None, "Не удалось распознать речь"
    text = (data.get("text") or "").strip()
    if looks_like_prompt_echo(text, transcription_prompt()):
        return "", None
    return text, None


def looks_like_prompt_echo(text, prompt):
    """На тишине модель распознавания иногда возвращает саму подсказку
    (список услуг и врачей) вместо пустого текста. Если почти все слова
    ответа есть в подсказке и это перечень через запятую — считаем, что
    речи не было."""
    words = re.findall(r"\w+", (text or "").lower())
    if len(words) < 4:
        return False
    vocab = set(re.findall(r"\w+", (prompt or "").lower()))
    share = sum(1 for w in words if w in vocab) / len(words)
    return share >= 0.85 and text.count(",") >= 2


def speak(text):
    """Текст → голос (OggOpus). Возвращает (bytes, error). Говорит и
    по-русски, и по-узбекски — язык определяется по самому тексту."""
    text = (text or "").strip()[:3000]
    if not text:
        return None, "Пустой текст для озвучки"
    model = getattr(settings, "OPENAI_TTS_MODEL", "") or "gpt-4o-mini-tts"
    voice = getattr(settings, "OPENAI_TTS_VOICE", "") or "nova"
    body = {"model": model, "voice": voice, "input": text, "response_format": "opus"}
    if model.startswith("gpt-"):
        body["instructions"] = "Говори спокойно, дружелюбно и чётко, как вежливый ассистент клиники."
    audio, err = _request("/audio/speech", body, raw=True, timeout=45)
    if err and _model_missing(err):
        body.pop("instructions", None)
        body["model"] = "tts-1"
        audio, err = _request("/audio/speech", body, raw=True, timeout=45)
    if err:
        return None, "Не удалось озвучить ответ"
    return audio, None


# ── Инструменты (что модель может узнать и сделать) ──────────────────────

def _fn(name, description, props=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props or {}, "required": list(required)}}}


TOOLS = [
    _fn("search_patients", "Найти пациентов клиники по имени, фамилии или телефону.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("patient_details", "Карточка пациента: телефон, долг/баланс, аллергии, заметки, "
        "последние визиты с услугами и зубами, будущие записи.",
        {"patient_id": {"type": "integer"}}, ["patient_id"]),
    _fn("list_doctors", "Список врачей клиники с id."),
    _fn("doctor_day", "Записи на день: у одного врача (doctor_id) или у всех врачей клиники.",
        {"date": {"type": "string", "description": "YYYY-MM-DD"},
         "doctor_id": {"type": "integer"}}, ["date"]),
    _fn("free_slots", "Свободное время врача на дату с учётом графика и уже занятых записей.",
        {"doctor_id": {"type": "integer"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
         "duration_min": {"type": "integer", "description": "длительность приёма, по умолчанию 60"}},
        ["doctor_id", "date"]),
    _fn("search_services", "Найти услуги в прайсе клиники (название, цена, длительность, id). "
        "Ищи по ключевым словам: «пломба композит», «удаление», «чистка».",
        {"query": {"type": "string"}}, ["query"]),
    _fn("clinic_finance", "Финансы клиники за текущий месяц: выручка, расходы, прибыль, долги пациентов."),
    _fn("propose_appointment",
        "Подготовить запись пациента к врачу. Запись НЕ создаётся сразу — пользователь увидит "
        "кнопку «Записать» и подтвердит. Укажи patient_id найденного пациента, либо new_patient_name "
        "и new_patient_phone для нового.",
        {"patient_id": {"type": "integer"},
         "new_patient_name": {"type": "string", "description": "Фамилия Имя"},
         "new_patient_phone": {"type": "string"},
         "doctor_id": {"type": "integer"},
         "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM по времени клиники"},
         "duration_min": {"type": "integer"},
         "service_ids": {"type": "array", "items": {"type": "integer"}},
         "note": {"type": "string"}},
        ["doctor_id", "start"]),
    _fn("add_to_visit",
        "Только на открытой карте приёма: добавить в план лечения услуги по зубам. "
        "Зубы — в международной нумерации FDI (11–48 постоянные, 51–85 молочные). "
        "service_id — из search_services.",
        {"items": {"type": "array", "items": {"type": "object", "properties": {
            "teeth": {"type": "array", "items": {"type": "integer"}},
            "service_id": {"type": "integer"},
            "discount_pct": {"type": "number"}}, "required": ["teeth", "service_id"]}}},
        ["items"]),
    _fn("visit_note", "Только на открытой карте приёма: записать текст в поле карты — жалобы (complaints), "
        "диагноз (diagnosis), рекомендации (recommendations) или комментарий к визиту (notes). "
        "Пиши грамотно, кратко, медицинским языком, но без выдумок — только то, что сказал врач.",
        {"field": {"type": "string", "enum": ["complaints", "diagnosis", "recommendations", "notes"]},
         "text": {"type": "string"}}, ["field", "text"]),
    _fn("start_visit", "Начать (или продолжить) приём пациента — откроет карту приёма. Укажи "
        "appointment_id сегодняшней записи пациента (из doctor_day или patient_details), а если записи "
        "нет — patient_id. После открытия ты продолжишь разговор уже в карте приёма.",
        {"appointment_id": {"type": "integer"}, "patient_id": {"type": "integer"}}),
    _fn("open_page", "Открыть страницу CRM: карточку пациента или расписание на дату.",
        {"page": {"type": "string", "enum": ["patient", "schedule", "patients"]},
         "patient_id": {"type": "integer"}, "date": {"type": "string", "description": "YYYY-MM-DD"}},
        ["page"]),
]


def _money(v):
    try:
        return "{:,.0f}".format(float(v or 0)).replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def _parse_date(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_start(s):
    s = (s or "").strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s[:16])
    except ValueError:
        return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _patient_brief(p):
    return {"id": p.pk, "name": p.full_name, "phone": p.phone,
            "birth_date": p.birth_date.isoformat() if p.birth_date else None,
            "balance": float(p.balance or 0)}


def _doctor(doctor_id):
    from apps.users.models import clinic_doctors
    return clinic_doctors(_clinic()).filter(pk=doctor_id).first() if doctor_id else None


def _appt_brief(a):
    st = timezone.localtime(a.start_at)
    services = [s.name for s in a.services.all()] or ([a.service.name] if a.service_id else [])
    return {"id": a.pk, "date": st.date().isoformat(), "time": st.strftime("%H:%M"),
            "end": timezone.localtime(a.end_at).strftime("%H:%M"),
            "patient": a.patient.full_name if a.patient_id else None, "patient_id": a.patient_id,
            "doctor": a.doctor.name if a.doctor_id else None, "status": a.get_status_display(),
            "services": services}


def _work_window(doctor, day):
    """(start, end) рабочего дня врача: по графику, иначе — окно клиники."""
    from apps.appointments.views import _clinic_work_window
    from apps.users.models_salary import DoctorSchedule
    if DoctorSchedule.objects.filter(doctor=doctor).exists():
        sched = DoctorSchedule.objects.filter(doctor=doctor, day_of_week=day.weekday()).first()
        if not sched or not sched.is_working:
            return None
        return sched.start_time, sched.end_time
    ws, we, _a, _b = _clinic_work_window()
    return ws, we


def free_slots(doctor, day, duration=60, step=30):
    from apps.appointments.models import Appointment
    win = _work_window(doctor, day)
    if not win:
        return []
    start = timezone.make_aware(datetime.combine(day, win[0]))
    end = timezone.make_aware(datetime.combine(day, win[1]))
    busy = [(a.start_at, a.end_at) for a in Appointment.objects.filter(
        doctor=doctor, start_at__lt=end, end_at__gt=start).exclude(status__in=["cancelled", "no_show"])]
    now = timezone.now()
    out, t = [], start
    while t + timedelta(minutes=duration) <= end:
        t_end = t + timedelta(minutes=duration)
        if t > now and not any(b0 < t_end and b1 > t for b0, b1 in busy):
            out.append(timezone.localtime(t).strftime("%H:%M"))
        t += timedelta(minutes=step)
    return out


def _search_services(query):
    from django.db.models import Q
    from apps.services.models import Service
    qs = Service.objects.filter(is_active=True)
    words = [w for w in re.split(r"[\s,.;]+", (query or "").lower()) if len(w) >= 3]
    found = []
    if words:
        q_all = qs
        for w in words:
            q_all = q_all.filter(Q(name__icontains=w[:max(4, len(w) - 2)]) | Q(code__iexact=w))
        found = list(q_all[:15])
        if not found:
            q_any = Q()
            for w in words:
                q_any |= Q(name__icontains=w[:max(4, len(w) - 2)])
            found = list(qs.filter(q_any)[:20])
    from apps.settings_clinic.models import ClinicSettings
    cur = ClinicSettings.get().currency_label
    # Цена сразу с валютой клиники: без неё модель дописывала «рублей».
    return [{"id": s.pk, "name": s.name, "price": "%s %s" % (format(int(s.price), ",").replace(",", " "), cur),
             "duration_min": s.duration, "category": s.category.name if s.category_id else None} for s in found]


class Ctx:
    """Состояние одного обращения: кто спрашивает, на какой странице, что
    уже подготовлено для клиента (кнопки подтверждения, действия)."""

    def __init__(self, request, page=None):
        self.request = request
        self.user = request.user
        self.page = page or {}
        self.actions = []
        self.trace = []   # какие инструменты вызывались — сохраняется в истории для разбора


def _tool_search_patients(ctx, query="", **_):
    from apps.notifications.views import _voice_search_patients
    return [_patient_brief(p) for p in _voice_search_patients(query, limit=8)]


def _tool_patient_details(ctx, patient_id=None, **_):
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    p = Patient.objects.filter(pk=patient_id).first()
    if p is None:
        return {"error": "Пациент не найден"}
    info = _patient_brief(p)
    info.update({"allergy": p.allergy or "", "notes": (p.notes or "")[:500]})
    visits = []
    for tr in (Treatment.objects.filter(patient=p).select_related("doctor")
               .prefetch_related("cures__service").order_by("-created_at")[:5]):
        visits.append({"date": timezone.localtime(tr.created_at).date().isoformat(),
                       "doctor": tr.doctor.name if tr.doctor_id else None, "status": tr.get_status_display(),
                       "total": float(tr.total_amount or 0),
                       "work": ["%s%s" % (c.service.name, (" (зуб %s)" % c.tooth_number) if c.tooth_number else "")
                                for c in tr.cures.all()][:12]})
    info["recent_visits"] = visits
    info["upcoming"] = [_appt_brief(a) for a in Appointment.objects.filter(
        patient=p, start_at__gte=timezone.now()).exclude(status="cancelled")
        .select_related("doctor", "service", "patient").prefetch_related("services").order_by("start_at")[:5]]
    return info


def _tool_list_doctors(ctx, **_):
    from apps.users.models import clinic_doctors
    return [{"id": d.pk, "name": d.name, "specialty": getattr(d, "doctor_types_display", "")}
            for d in clinic_doctors(_clinic()).order_by("name")]


def _tool_doctor_day(ctx, date=None, doctor_id=None, **_):
    from apps.appointments.models import Appointment
    day = _parse_date(date)
    if day is None:
        return {"error": "Неверная дата"}
    qs = Appointment.objects.filter(start_at__date=day).exclude(status="cancelled")
    if doctor_id:
        qs = qs.filter(doctor_id=doctor_id)
    qs = qs.select_related("patient", "doctor", "service").prefetch_related("services").order_by("start_at")
    return {"date": day.isoformat(), "appointments": [_appt_brief(a) for a in qs[:60]]}


def _tool_free_slots(ctx, doctor_id=None, date=None, duration_min=60, **_):
    doc, day = _doctor(doctor_id), _parse_date(date)
    if doc is None or day is None:
        return {"error": "Неверный врач или дата"}
    slots = free_slots(doc, day, int(duration_min or 60))
    return {"doctor": doc.name, "date": day.isoformat(), "free": slots,
            "note": "" if slots else "Свободного времени нет или врач не работает в этот день"}


def _tool_search_services(ctx, query="", **_):
    return _search_services(query)


def _tool_clinic_finance(ctx, **_):
    if not (ctx.user.can_access("finance") and (ctx.user.is_admin or ctx.user.is_superadmin)):
        return {"error": "Нет доступа к финансам — скажи пользователю, что эти данные ему недоступны"}
    from decimal import Decimal
    from django.db.models import Sum
    from apps.patients.models import Patient
    from apps.tenancy import get_current_clinic
    from apps.users.views import _newui_accounting_data
    acct = _newui_accounting_data(get_current_clinic() or ctx.user.clinic)
    debt = -(Patient.objects.filter(balance__lt=0).aggregate(s=Sum("balance"))["s"] or Decimal(0))
    return {"month": acct["monthLabel"], "revenue": round(acct["revenue"]), "expenses": round(acct["expensesTotal"]),
            "profit": round(acct["profit"]), "patients_debt": round(debt),
            "debtors": Patient.objects.filter(balance__lt=0).count()}


def validate_appointment(doctor, start, duration, exclude_pk=None):
    """Те же проверки, что у «Новой записи» в расписании. Ошибка или None.
    exclude_pk — переносимая запись (не конфликтует сама с собой)."""
    from apps.appointments.models import Appointment
    from apps.appointments.views import _duration_sanity_error, _overlap_error_message, schedule_violation
    end = start + timedelta(minutes=duration)
    err = _duration_sanity_error(start, end)
    if err:
        return err
    if start < timezone.now() - timedelta(minutes=5):
        return "Это время уже прошло"
    overlap = (Appointment.objects.select_related("branch", "patient")
               .filter(doctor=doctor, start_at__lt=end, end_at__gt=start)
               .exclude(status__in=["cancelled", "no_show"]).exclude(pk=exclude_pk).first())
    if overlap:
        return _overlap_error_message(overlap)
    return schedule_violation(doctor, start, end)


def _tool_propose_appointment(ctx, doctor_id=None, start=None, duration_min=None, patient_id=None,
                              new_patient_name="", new_patient_phone="", service_ids=None, note="", **_):
    from apps.patients.models import Patient
    from apps.services.models import Service
    if not (ctx.user.can_access("calendar") or ctx.user.can_access("appointments")):
        return {"error": "У пользователя нет доступа к расписанию"}
    doc = _doctor(doctor_id)
    st = _parse_start(start)
    if doc is None or st is None:
        return {"error": "Неверный врач или время"}
    patient = Patient.objects.filter(pk=patient_id).first() if patient_id else None
    new_name = (new_patient_name or "").strip()
    new_phone = (new_patient_phone or "").strip()
    if patient is None and not (new_name and len(re.sub(r"\D", "", new_phone)) >= 9):
        return {"error": "Нужен найденный пациент (patient_id) или имя и телефон нового пациента"}
    services = list(Service.objects.filter(pk__in=service_ids or [], is_active=True))
    duration = int(duration_min or sum(s.duration for s in services) or 60)
    err = validate_appointment(doc, st, duration)
    if err:
        return {"error": err, "hint": "Предложи другое время — посмотри free_slots"}
    payload = {"u": ctx.user.pk, "d": doc.pk, "s": timezone.localtime(st).strftime("%Y-%m-%dT%H:%M"),
               "m": duration, "p": patient.pk if patient else None, "n": new_name, "ph": new_phone,
               "sv": [s.pk for s in services], "no": (note or "")[:300]}
    who = patient.full_name if patient else "%s (новый пациент, %s)" % (new_name, new_phone)
    local = timezone.localtime(st)
    summary = "%s → %s, %s %s, %s мин%s" % (
        who, doc.name, local.strftime("%d.%m.%Y"), local.strftime("%H:%M"), duration,
        (", " + ", ".join(s.name for s in services)) if services else "")
    ctx.actions = [a for a in ctx.actions if a.get("type") != "confirm_appointment"]
    ctx.actions.append({"type": "confirm_appointment", "summary": summary,
                        "token": signing.dumps(payload, salt=CONFIRM_SALT)})
    return {"ok": True, "status": "Ждёт подтверждения пользователем (кнопка «Записать» или ответ «да»)",
            "summary": summary}


FDI = re.compile(r"^(1[1-8]|2[1-8]|3[1-8]|4[1-8]|5[1-5]|6[1-5]|7[1-5]|8[1-5])$")


def _tool_add_to_visit(ctx, items=None, **_):
    from apps.services.models import Service
    if ctx.page.get("type") != "visit":
        return {"error": "Карта приёма не открыта — попроси врача открыть приём пациента"}
    added, problems = [], []
    for it in items or []:
        svc = Service.objects.filter(pk=it.get("service_id"), is_active=True).first()
        teeth = [int(t) for t in (it.get("teeth") or []) if FDI.match(str(t))]
        if svc is None:
            problems.append("услуга %s не найдена" % it.get("service_id"))
            continue
        if not teeth:
            problems.append("для «%s» не указан правильный номер зуба" % svc.name)
            continue
        pct = it.get("discount_pct")
        added.append({"teeth": teeth, "service_id": svc.pk, "service": svc.name,
                      "discount_pct": max(0, min(100, float(pct))) if pct else 0})
    if added:
        ctx.actions.append({"type": "visit_add", "items": added})
    return {"added": [{"teeth": a["teeth"], "service": a["service"]} for a in added], "problems": problems}


def _tool_visit_note(ctx, field="", text="", **_):
    if ctx.page.get("type") != "visit":
        return {"error": "Карта приёма не открыта — попроси врача открыть приём пациента"}
    if field not in ("complaints", "diagnosis", "recommendations", "notes") or not (text or "").strip():
        return {"error": "Укажи поле и текст"}
    ctx.actions.append({"type": "visit_field", "field": field, "text": text.strip()[:2000]})
    return {"ok": True, "field": field}


def _tool_start_visit(ctx, appointment_id=None, patient_id=None, **_):
    from apps.appointments.models import Appointment
    from apps.patients.models import Patient
    appt = (Appointment.objects.select_related("patient", "doctor").filter(pk=appointment_id).first()
            if appointment_id else None)
    if appt is not None and appt.status in ("cancelled", "no_show"):
        return {"error": "Эта запись отменена или пациент не пришёл"}
    if appt is None and patient_id:
        p = Patient.objects.filter(pk=patient_id).first()
        if p is None:
            return {"error": "Пациент не найден"}
        today = timezone.localdate()
        appt = (Appointment.objects.select_related("patient", "doctor")
                .filter(patient=p, start_at__date=today).exclude(status__in=["cancelled", "no_show"])
                .order_by("start_at").first())
        if appt is None:
            ctx.actions.append({"type": "open", "url": "/new/visit/start/?patient=%s" % p.pk})
            return {"opened": True, "patient": p.full_name, "note": "Записи на сегодня нет — открыт новый приём"}
    if appt is None:
        return {"error": "Укажи запись или пациента"}
    ctx.actions.append({"type": "open", "url": "/new/visit/start/?appointment=%s" % appt.pk})
    st = timezone.localtime(appt.start_at)
    return {"opened": True, "patient": appt.patient.full_name if appt.patient_id else "—",
            "time": st.strftime("%H:%M"), "doctor": appt.doctor.name if appt.doctor_id else "—"}


def _tool_open_page(ctx, page="", patient_id=None, date=None, **_):
    if page == "patient" and patient_id:
        url = "/new/patients/%s/" % int(patient_id)
    elif page == "schedule":
        day = _parse_date(date)
        url = "/new/schedule/" + ("?date=%s" % day.isoformat() if day else "")
    elif page == "patients":
        url = "/new/patients/"
    else:
        return {"error": "Неизвестная страница"}
    ctx.actions.append({"type": "open", "url": url})
    return {"ok": True}


HANDLERS = {
    "search_patients": _tool_search_patients, "patient_details": _tool_patient_details,
    "list_doctors": _tool_list_doctors, "doctor_day": _tool_doctor_day, "free_slots": _tool_free_slots,
    "search_services": _tool_search_services, "clinic_finance": _tool_clinic_finance,
    "propose_appointment": _tool_propose_appointment, "add_to_visit": _tool_add_to_visit,
    "open_page": _tool_open_page, "start_visit": _tool_start_visit, "visit_note": _tool_visit_note,
}


# ── Разговор ─────────────────────────────────────────────────────────────

def _page_context(page):
    """Что сейчас открыто у пользователя (для подсказки модели)."""
    if page.get("type") == "visit" and page.get("treatment_id"):
        from apps.treatments.models import Treatment
        tr = Treatment.objects.select_related("patient", "doctor").filter(pk=page["treatment_id"]).first()
        if tr is not None:
            return ("Открыта КАРТА ПРИЁМА пациента %s (patient_id=%s), врач %s. Если врач называет зубы и "
                    "лечение — найди услуги (search_services) и добавь их add_to_visit, не переспрашивая "
                    "по мелочам; если услуга неоднозначна — уточни коротко. Жалобы, диагноз, рекомендации и "
                    "комментарии врача записывай в карту через visit_note."
                    % (tr.patient.full_name, tr.patient_id, tr.doctor.name if tr.doctor_id else "—"))
    if page.get("type") == "patient" and page.get("patient_id"):
        return "Открыта карточка пациента patient_id=%s." % page["patient_id"]
    if page.get("type") == "schedule":
        return "Открыто расписание%s." % (" на %s" % page["date"] if page.get("date") else "")
    return "Пользователь на странице %s." % (page.get("path") or "CRM")


def _today_snapshot():
    """Короткая сводка расписания на сегодня — в системный промпт, чтобы на
    «сколько записей сегодня» модель не отвечала по памяти разговора (баг:
    «сегодня записей нет», хотя в расписании их две)."""
    from apps.appointments.models import Appointment
    today = timezone.localdate()
    qs = (Appointment.objects.filter(start_at__date=today).exclude(status="cancelled")
          .select_related("doctor", "patient").order_by("start_at"))
    items = list(qs[:40])
    if not items:
        return "Сегодня (%s) в расписании клиники записей нет." % today.isoformat()
    by_doc = {}
    for a in items:
        by_doc.setdefault(a.doctor.name if a.doctor_id else "без врача", []).append(
            "%s %s" % (timezone.localtime(a.start_at).strftime("%H:%M"),
                       a.patient.full_name if a.patient_id else "без пациента"))
    parts = ["%s: %s" % (d, ", ".join(v)) for d, v in by_doc.items()]
    return "Сегодня (%s) в расписании клиники записей: %s. %s." % (today.isoformat(), len(items), "; ".join(parts))


def system_prompt(ctx, assistant_name=""):
    from apps.settings_clinic.models import ClinicSettings
    now = timezone.localtime()
    role = ("директор" if ctx.user.is_admin_main or ctx.user.is_superadmin else
            "администратор" if ctx.user.is_admin else "врач" if ctx.user.is_doctor else "сотрудник")
    name = (assistant_name or "").strip() or "ODONTIS"
    return (
        f"Ты — «{name}», голосовой ИИ-ассистент стоматологической клиники «{ClinicSettings.get().name}» "
        f"в CRM ODONTIS (разработчик AKM SOFT CLINIC). Сейчас {now.strftime('%Y-%m-%d %H:%M')}, "
        f"{WEEKDAYS[now.weekday()]} (время клиники). С тобой говорит {ctx.user.name}, {role}"
        f"{' (id врача ' + str(ctx.user.pk) + ')' if ctx.user.is_doctor else ''}. {_page_context(ctx.page)}\n"
        f"{_today_snapshot()}\n\n"
        "Правила:\n"
        "- На вопросы о записях, расписании и пациентах ВСЕГДА смотри свежие данные (сводка выше, "
        "doctor_day, patient_details), а не прошлые ответы в разговоре — данные могли измениться.\n"
        "- Данные клиники бери ТОЛЬКО из инструментов, ничего не выдумывай (пациентов, время, цены).\n"
        "- Запись: найди пациента (search_patients), врача (list_doctors), проверь free_slots и вызови "
        "propose_appointment. Если «к себе» говорит врач — врач это он сам. Если пациентов несколько или "
        "не хватает данных (кто, к кому, когда) — коротко уточни. Нового пациента записывай только с "
        "именем и телефоном. После propose_appointment скажи, что подготовил запись и ждёшь подтверждения.\n"
        "- «Сегодня», «завтра», «в пятницу» переводи в даты сам от текущей даты.\n"
        "- «Начни приём …» — найди сегодняшнюю запись пациента и вызови start_visit; ответь: «Открыл "
        "приём: <пациент>, <время>. Слушаю вас» — дальше врач диктует уже в карте приёма.\n"
        "- Номера зубов — система FDI: «тридцать шесть» = 36, «верхний правый шестой» = 16.\n"
        "- Отвечай на языке пользователя (русский или узбекский), коротко, 1–3 предложения: ответ "
        "озвучивается вслух — без списков, таблиц и markdown. Время пиши как 14:30, суммы — числом.\n"
        "- На общие вопросы (медицина, препараты, как пользоваться CRM) отвечай как обычный помощник; "
        "диагноз и лечение решает врач."
    )


def _chat(messages, tools=True):
    """tools: True — инструменты сотрудника (TOOLS), список — свои, False — без."""
    model = getattr(settings, "OPENAI_MODEL", "") or CHAT_FALLBACKS[0]
    tried = []
    for m in (model,) + tuple(x for x in CHAT_FALLBACKS if x != model):
        body = {"model": m, "messages": messages}
        if tools:
            body["tools"] = TOOLS if tools is True else tools
        data, err = _request("/chat/completions", body, timeout=60)
        if err and _model_missing(err):
            tried.append(m)
            continue
        if err:
            return None, err
        return data, None
    return None, (404, "models not available: %s" % ", ".join(tried))


def run(request, text, history=None, page=None, assistant_name=""):
    """Один ход разговора. Возвращает {"answer": str, "actions": [...]}
    или {"error": str}."""
    ensure_clinic(request)
    ctx = Ctx(request, page)
    messages = [{"role": "system", "content": system_prompt(ctx, assistant_name)}]
    for turn in (history or [])[-12:]:
        t = (turn.get("text") or "").strip()
        if t:
            messages.append({"role": "assistant" if turn.get("role") == "assistant" else "user", "content": t[:2000]})
    messages.append({"role": "user", "content": text[:4000]})

    for _round in range(MAX_TOOL_ROUNDS):
        data, err = _chat(messages)
        if err:
            return {"error": "ИИ-помощник сейчас недоступен"}
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"answer": (msg.get("content") or "").strip() or "Готово.", "actions": ctx.actions,
                    "trace": ctx.trace}
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            handler = HANDLERS.get(fn.get("name"))
            try:
                args = json.loads(fn.get("arguments") or "{}")
                result = handler(ctx, **args) if handler else {"error": "Нет такого инструмента"}
            except Exception as e:  # noqa: BLE001
                log.exception("assistant: tool %s failed", fn.get("name"))
                result = {"error": "Ошибка инструмента: %s" % e}
            ctx.trace.append({"tool": fn.get("name"), "args": (fn.get("arguments") or "")[:300],
                              "result": json.dumps(result, ensure_ascii=False, default=str)[:300]})
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": json.dumps(result, ensure_ascii=False, default=str)[:12000]})
    return {"answer": "Не получилось довести запрос до конца — уточните, пожалуйста.", "actions": ctx.actions,
            "trace": ctx.trace}


def simple_answer(question, history=None, assistant_name=""):
    """Свободный вопрос без инструментов (замена YandexGPT, если OpenAI есть)."""
    name = (assistant_name or "").strip() or "ODONTIS"
    messages = [{"role": "system", "content": (
        f"Ты — «{name}», ИИ-ассистент стоматологической клиники в CRM ODONTIS (AKM SOFT CLINIC). "
        "Отвечай кратко, разговорным тоном, на языке вопроса, без markdown — ответ озвучивается.")}]
    for turn in (history or [])[-12:]:
        t = (turn.get("text") or "").strip()
        if t:
            messages.append({"role": "assistant" if turn.get("role") == "assistant" else "user", "content": t})
    messages.append({"role": "user", "content": question})
    data, err = _chat(messages, tools=False)
    if err:
        return None, "Не удалось получить ответ от ИИ"
    return (data["choices"][0]["message"].get("content") or "").strip(), None


def confirm_appointment(request, token):
    """Создать подготовленную ассистентом запись. Возвращает (dict, error)."""
    from apps.appointments.models import Appointment
    from apps.appointments.views import (
        _default_visit_service, _quick_appt_branch, gcal_push, notify_appointment_created)
    from apps.patients.models import Patient, normalize_phone
    from apps.services.models import Service
    ensure_clinic(request)
    try:
        data = signing.loads(token, salt=CONFIRM_SALT, max_age=CONFIRM_MAX_AGE)
    except signing.SignatureExpired:
        return None, "Подтверждение устарело — попросите ассистента ещё раз"
    except signing.BadSignature:
        return None, "Неверное подтверждение"
    if data.get("u") != request.user.pk:
        return None, "Это подтверждение другого пользователя"
    doc = _doctor(data.get("d"))
    start = _parse_start(data.get("s"))
    if doc is None or start is None:
        return None, "Врач или время больше недоступны"
    err = validate_appointment(doc, start, int(data.get("m") or 60))
    if err:
        return None, err
    branch = _quick_appt_branch(request, doc)
    if branch is None:
        return None, "Филиал этого врача заблокирован — запись невозможна"
    patient = Patient.objects.filter(pk=data["p"]).first() if data.get("p") else None
    if patient is None:
        phone = data.get("ph") or ""
        patient = Patient.objects.filter(phone_norm=normalize_phone(phone)).first()
        if patient is None:
            parts = (data.get("n") or "").split(None, 1)
            patient = Patient(last_name=parts[0] if parts else "", first_name=parts[1] if len(parts) > 1 else "",
                              phone=phone, branch=branch)
            patient.save()
    services = list(Service.objects.filter(pk__in=data.get("sv") or [])) or [_default_visit_service()]
    appt = Appointment.objects.create(
        patient=patient, doctor=doc, branch=branch, service=services[0], start_at=start,
        end_at=start + timedelta(minutes=int(data.get("m") or 60)), status=Appointment.STATUS_SCHEDULED,
        notes=("Записан через ИИ-ассистента. " + (data.get("no") or "")).strip(), created_by=request.user)
    appt.services.set(services)
    notify_appointment_created(appt, created_by=request.user)
    try:
        gcal_push(appt)
    except Exception:  # noqa: BLE001
        pass
    local = timezone.localtime(start)
    return {"id": appt.pk, "message": "✅ Записал: %s к врачу %s на %s в %s." % (
        patient.full_name, doc.name, local.strftime("%d.%m.%Y"), local.strftime("%H:%M")),
        "url": "/new/schedule/?date=%s" % local.date().isoformat()}, None
