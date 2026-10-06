"""ИИ-ассистент для ПАЦИЕНТОВ в WhatsApp и Telegram.

Пациент пишет клинике (текстом или голосом, по-русски или по-узбекски) —
если администратор не ответил за ClinicSettings.ai_patient_delay_min минут
(в нерабочее время клиники — сразу), отвечает ассистент: рассказывает об
услугах и ценах, подбирает свободное время, записывает, переносит и отменяет
ЗАПИСИ САМОГО ПАЦИЕНТА (по номеру телефона / привязке Telegram). Чужие
данные и финансы клиники ему недоступны. Запись создаётся только после
явного «да» пациента; администратор получает уведомление и видит всю
переписку в «Мессенджерах» (сообщения ассистента помечены 🤖), может
выключить ассистента в чате или ответить сам — тогда ассистент молчит.

Команда patient_assistant_tick (cron раз в минуту) проверяет чаты каждые
несколько секунд в течение минуты — ответ приходит через ~10–15 секунд.
"""
import html
import json
import logging
from datetime import timedelta

from django.utils import timezone

from . import assistant as core

log = logging.getLogger("apps")

WINDOW_HOURS = 6          # старше — не отвечаем (человек уже не ждёт)
HISTORY = 16              # сколько последних сообщений чата видит модель


def _fn(name, description, props=None, required=()):
    return core._fn(name, description, props, required)


TOOLS = [
    _fn("clinic_info", "Название, адрес, телефон, часы работы и филиалы клиники."),
    _fn("list_doctors", "Врачи клиники (id, имя, специальность)."),
    _fn("search_services", "Услуги и цены по ключевым словам (пломба, удаление, чистка, имплант…).",
        {"query": {"type": "string"}}, ["query"]),
    _fn("free_slots", "Свободное время врача на дату.",
        {"doctor_id": {"type": "integer", "description": "id врача из списка в инструкции"},
         "doctor_name": {"type": "string", "description": "имя врача, если не уверен в id"},
         "date": {"type": "string", "description": "YYYY-MM-DD"},
         "duration_min": {"type": "integer"}}, ["date"]),
    _fn("my_appointments", "Предстоящие записи этого пациента (id, дата, время, врач)."),
    _fn("book_appointment",
        "Записать пациента. Вызывай ТОЛЬКО после того, как пациент явно согласился на конкретные "
        "врача, дату и время. Если пациент новый — нужно его имя и фамилия (full_name).",
        {"doctor_id": {"type": "integer", "description": "id врача из списка в инструкции"},
         "doctor_name": {"type": "string", "description": "имя врача, если не уверен в id"},
         "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM"},
         "duration_min": {"type": "integer"}, "service_ids": {"type": "array", "items": {"type": "integer"}},
         "full_name": {"type": "string"}}, ["start"]),
    _fn("reschedule_appointment", "Перенести запись пациента (после его согласия на новое время).",
        {"appointment_id": {"type": "integer"}, "new_start": {"type": "string", "description": "YYYY-MM-DDTHH:MM"}},
        ["appointment_id", "new_start"]),
    _fn("cancel_appointment", "Отменить запись пациента (после его подтверждения).",
        {"appointment_id": {"type": "integer"}}, ["appointment_id"]),
    _fn("call_admin", "Позвать администратора: жалоба, сложный медицинский вопрос, оплата, просьба "
        "поговорить с человеком или ты не можешь помочь. После этого ты больше не отвечаешь в этом чате.",
        {"reason": {"type": "string"}}, ["reason"]),
]


class PCtx:
    def __init__(self, clinic, channel, address, patient):
        self.clinic, self.channel, self.address, self.patient = clinic, channel, address, patient
        self.events = []      # что сделал ассистент — для уведомления администраторам
        self.trace = []       # вызовы инструментов — в журнал команды (разбор «почему не записал»)
        self.paused = False


def _admins(clinic):
    from django.db.models import Q
    from apps.users.models import Role, User
    return (User.objects.filter(clinic=clinic, is_active=True)
            .filter(Q(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN]) | Q(roles__name__in=[Role.ADMIN, Role.ADMIN_MAIN]))
            .distinct())


def _notify_admins(ctx, title, body):
    try:
        from .models import Notification
        for u in _admins(ctx.clinic):
            Notification.send(u, title, body, type="appointment", link="/new/messages/")
    except Exception:  # noqa: BLE001
        log.exception("patient_assistant: уведомление администраторам не отправлено")


def _t_clinic_info(ctx, **_):
    from apps.settings_clinic.models import ClinicSettings
    from apps.users.models import Branch
    cs = ClinicSettings.get()
    return {"name": cs.name, "phone": cs.phone, "address": cs.address, "working_hours": cs.working_hours,
            "branches": [{"name": b.name, "address": b.address, "phone": b.phone}
                         for b in Branch.objects.filter(is_active=True)]}


def _t_list_doctors(ctx, **_):
    return core._tool_list_doctors(None)


def _t_search_services(ctx, query="", **_):
    return core._search_services(query)


def _clinic_doctors():
    from apps.users.models import clinic_doctors
    return list(clinic_doctors(core._clinic()).order_by("name"))


def _pdoctor(doctor_id=None, doctor_name=""):
    """Врач по id, а если id неверный — по имени. Модель не помнит id между
    сообщениями (в истории только тексты), поэтому имя — надёжная подстраховка."""
    doc = core._doctor(doctor_id)
    if doc is None and (doctor_name or "").strip():
        words = [w for w in doctor_name.lower().replace("ё", "е").split() if len(w) >= 3]
        found = [d for d in _clinic_doctors()
                 if words and all(w[:max(4, len(w) - 2)] in d.name.lower().replace("ё", "е") for w in words)]
        if len(found) == 1:
            doc = found[0]
    return doc


DOCTOR_ERR = {"error": "Врач не найден: возьми id из списка врачей в инструкции или укажи doctor_name"}


def _t_free_slots(ctx, doctor_id=None, doctor_name="", date=None, duration_min=60, **_):
    doc = _pdoctor(doctor_id, doctor_name)
    if doc is None:
        return DOCTOR_ERR
    return core._tool_free_slots(None, doctor_id=doc.pk, date=date, duration_min=duration_min)


def _own_appts(ctx):
    from apps.appointments.models import Appointment
    if ctx.patient is None:
        return Appointment.objects.none()
    return (Appointment.objects.filter(patient=ctx.patient, start_at__gte=timezone.now())
            .exclude(status__in=["cancelled", "no_show", "completed"])
            .select_related("doctor", "service", "patient").prefetch_related("services").order_by("start_at"))


def _t_my_appointments(ctx, **_):
    if ctx.patient is None:
        return {"appointments": [], "note": "Пациент ещё не найден в базе клиники по этому номеру"}
    return {"patient": ctx.patient.full_name, "appointments": [core._appt_brief(a) for a in _own_appts(ctx)[:10]]}


def _ensure_patient(ctx, full_name):
    from apps.patients.models import Patient, normalize_phone
    if ctx.patient is not None:
        return ctx.patient, None
    if ctx.channel != "wa":
        return None, "Сначала нужно подтвердить номер телефона в Telegram-боте клиники (/start)."
    name = (full_name or "").strip()
    p = Patient.objects.filter(phone_norm=normalize_phone(ctx.address)).first()
    if p is None:
        if len(name) < 2:
            return None, "Пациент новый: спроси имя и фамилию одним вопросом, потом сразу запиши"
        parts = name.split(None, 1)
        p = Patient(last_name=parts[0], first_name=parts[1] if len(parts) > 1 else "", phone="+" + ctx.address.lstrip("+"))
        p.save()
    ctx.patient = p
    from .models import WaMessage
    WaMessage.objects.filter(channel="wa", phone=ctx.address, patient__isnull=True).update(patient=p)
    return p, None


def _t_book(ctx, doctor_id=None, doctor_name="", start=None, duration_min=None, service_ids=None, full_name="", **_):
    from apps.appointments.models import Appointment
    from apps.appointments.views import _default_visit_service, notify_appointment_created
    from apps.services.models import Service
    from apps.users.models import Branch
    doc, st = _pdoctor(doctor_id, doctor_name), core._parse_start(start)
    if doc is None:
        return DOCTOR_ERR
    if st is None:
        return {"error": "Неверное время: нужен формат YYYY-MM-DDTHH:MM"}
    services = list(Service.objects.filter(pk__in=service_ids or [], is_active=True))
    duration = int(duration_min or sum(s.duration for s in services) or 60)
    err = core.validate_appointment(doc, st, duration)
    if err:
        return {"error": err, "hint": "Предложи другое свободное время (free_slots)"}
    patient, perr = _ensure_patient(ctx, full_name)
    if perr:
        return {"error": perr}
    branch = doc.branches.filter(is_active=True).first() or Branch.objects.filter(is_active=True).first()
    if branch is None:
        return {"error": "Запись сейчас невозможна — позови администратора"}
    services = services or [_default_visit_service()]
    appt = Appointment.objects.create(
        patient=patient, doctor=doc, branch=branch, service=services[0], start_at=st,
        end_at=st + timedelta(minutes=duration), status=Appointment.STATUS_SCHEDULED,
        source="whatsapp" if ctx.channel == "wa" else "telegram",
        notes="Записан ИИ-ассистентом в %s" % ("WhatsApp" if ctx.channel == "wa" else "Telegram"))
    appt.services.set(services)
    notify_appointment_created(appt, notify_patient=False)
    loc = timezone.localtime(st)
    ctx.events.append("записал %s к %s на %s" % (patient.full_name, doc.name, loc.strftime("%d.%m %H:%M")))
    return {"ok": True, "appointment_id": appt.pk, "doctor": doc.name, "date": loc.strftime("%d.%m.%Y"),
            "time": loc.strftime("%H:%M"), "branch": branch.name, "address": branch.address}


def _t_reschedule(ctx, appointment_id=None, new_start=None, **_):
    a = _own_appts(ctx).filter(pk=appointment_id).first()
    st = core._parse_start(new_start)
    if a is None or st is None:
        return {"error": "Запись не найдена среди записей этого пациента"}
    duration = int((a.end_at - a.start_at).total_seconds() // 60) or 60
    old = (a.start_at, a.end_at)
    err = core.validate_appointment(a.doctor, st, duration, exclude_pk=a.pk)
    if err:
        return {"error": err, "hint": "Предложи другое свободное время"}
    a.start_at, a.end_at = st, st + timedelta(minutes=duration)
    a.save(update_fields=["start_at", "end_at"])
    loc_old, loc = timezone.localtime(old[0]), timezone.localtime(st)
    ctx.events.append("перенёс запись %s: %s → %s" % (a.patient.full_name, loc_old.strftime("%d.%m %H:%M"),
                                                     loc.strftime("%d.%m %H:%M")))
    return {"ok": True, "doctor": a.doctor.name, "date": loc.strftime("%d.%m.%Y"), "time": loc.strftime("%H:%M")}


def _t_cancel(ctx, appointment_id=None, **_):
    from apps.appointments.views import notify_appointment_cancelled
    a = _own_appts(ctx).filter(pk=appointment_id).first()
    if a is None:
        return {"error": "Запись не найдена среди записей этого пациента"}
    a.status = "cancelled"
    a.save(update_fields=["status"])
    notify_appointment_cancelled(a, notify_patient=False)
    ctx.events.append("отменил запись %s на %s" % (a.patient.full_name,
                                                   timezone.localtime(a.start_at).strftime("%d.%m %H:%M")))
    return {"ok": True}


def _t_call_admin(ctx, reason="", **_):
    set_paused(ctx.clinic, ctx.channel, ctx.address, True, reason="Ассистент позвал администратора: %s" % reason[:150])
    ctx.paused = True
    ctx.events.append("просит администратора: %s" % reason[:200])
    return {"ok": True, "note": "Администратор получил уведомление и ответит сам. Скажи пациенту об этом."}


HANDLERS = {"clinic_info": _t_clinic_info, "list_doctors": _t_list_doctors, "search_services": _t_search_services,
            "free_slots": _t_free_slots, "my_appointments": _t_my_appointments, "book_appointment": _t_book,
            "reschedule_appointment": _t_reschedule, "cancel_appointment": _t_cancel, "call_admin": _t_call_admin}


def system_prompt(ctx):
    from apps.settings_clinic.models import ClinicSettings
    now = timezone.localtime()
    who = ("Пациент: %s (patient_id=%s)." % (ctx.patient.full_name, ctx.patient.pk) if ctx.patient
           else "Пациент ещё не найден в базе клиники — для записи спроси имя и фамилию.")
    doctors = "; ".join("id=%s %s" % (d.pk, d.name) for d in _clinic_doctors()) or "нет"
    return (
        f"Ты — вежливый ассистент стоматологической клиники «{ClinicSettings.get().name}» в "
        f"{'WhatsApp' if ctx.channel == 'wa' else 'Telegram'}. Сейчас {now.strftime('%Y-%m-%d %H:%M')}, "
        f"{core.WEEKDAYS[now.weekday()]} (время клиники). {who}\n"
        f"Врачи клиники: {doctors}. Используй именно эти id.\n"
        "Ты помогаешь записаться, перенести или отменить СВОЮ запись, рассказываешь об услугах, ценах, "
        "адресе и часах работы. Правила:\n"
        "- Все данные бери только из инструментов, ничего не выдумывай (время, цены, врачей).\n"
        "- Перед записью/переносом/отменой один раз назови врача, дату и время и спроси подтверждение. "
        "Если пациент согласился (да, ха, хоп, ок, давайте, запишите, сойдёт, mayli, bo'ladi, yozing…) — "
        "СРАЗУ вызывай book_appointment / reschedule_appointment / cancel_appointment. НИКОГДА не "
        "переспрашивай подтверждение второй раз и не перечисляй время заново.\n"
        "- Если инструмент вернул ошибку — честно скажи пациенту причину простыми словами и предложи, "
        "что делать (другое время или имя и фамилию для новой карточки).\n"
        "- Запись создаётся только вызовом book_appointment: не говори «записал», пока он не вернул ok.\n"
        "- Предлагай 2–4 ближайших свободных времени, а не весь список.\n"
        "- Не ставь диагнозы и не назначай лечение — предложи консультацию врача. При боли, отёке, "
        "температуре — посоветуй прийти как можно скорее и предложи ближайшее время.\n"
        "- Жалобы, оплата, скидки, сложные вопросы или просьба поговорить с человеком — call_admin.\n"
        "- Не рассказывай о других пациентах, сотрудниках (кроме имён врачей) и финансах клиники.\n"
        "- Пиши на языке пациента: русский или узбекский (если пациент пишет латиницей — латиницей). "
        "Коротко и тепло, 1–4 предложения, без markdown; время как 14:30."
    )


def run(ctx, history):
    """history — [{"role": user|assistant, "text": ...}] последних сообщений чата.
    Возвращает текст ответа или None (ошибка — тогда не отвечаем)."""
    messages = [{"role": "system", "content": system_prompt(ctx)}]
    for turn in history[-HISTORY:]:
        if turn["text"]:
            messages.append({"role": turn["role"], "content": turn["text"][:2000]})
    for _round in range(core.MAX_TOOL_ROUNDS):
        data, err = core._chat(messages, tools=TOOLS)
        if err:
            return None
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip() or None
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            handler = HANDLERS.get(fn.get("name"))
            try:
                args = json.loads(fn.get("arguments") or "{}")
                result = handler(ctx, **args) if handler else {"error": "Нет такого инструмента"}
            except Exception as e:  # noqa: BLE001
                log.exception("patient_assistant: tool %s failed", fn.get("name"))
                result = {"error": "Ошибка: %s" % e}
            ctx.trace.append("%s(%s) -> %s" % (fn.get("name"), fn.get("arguments") or "",
                                               json.dumps(result, ensure_ascii=False, default=str)[:300]))
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": json.dumps(result, ensure_ascii=False, default=str)[:8000]})
    return None


# ── Состояние чатов и отправка ───────────────────────────────────────────

MANAGER_REASON = "Менеджер ведёт чат"
MANAGER_HOLD_HOURS = 12   # после последнего ответа менеджера ассистент молчит в этом чате столько часов


def is_paused(clinic, channel, address, now=None):
    from .models import ChatBotState
    st = ChatBotState.all_clinics.filter(clinic=clinic, channel=channel, address=address, paused=True).first()
    if not st:
        return False
    if st.reason == MANAGER_REASON:   # пауза «менеджер подключился» сама снимается через MANAGER_HOLD_HOURS
        return (now or timezone.now()) - st.updated_at < timedelta(hours=MANAGER_HOLD_HOURS)
    return True


def manager_joined(clinic, channel, address):
    """Менеджер ответил пациенту (из CRM или с телефона клиники) — ассистент в этом чате замолкает."""
    set_paused(clinic, channel, address, True, reason=MANAGER_REASON)


def _manager_replied_in_crm(clinic, channel, address, now):
    """Ответ менеджера из CRM после последнего ручного включения ассистента в этом чате."""
    from .models import ChatBotState, WaMessage
    after = now - timedelta(hours=MANAGER_HOLD_HOURS)
    st = ChatBotState.all_clinics.filter(clinic=clinic, channel=channel, address=address, paused=False).first()
    if st and st.updated_at > after:
        after = st.updated_at
    return WaMessage.objects.filter(channel=channel, phone=address, direction="out", by_ai=False,
                                    sent_by__isnull=False, created_at__gt=after).exists()


def _ai_leads_chat(channel, address, now):
    """Ассистент уже ведёт этот разговор (недавно отвечал сам) — следующие ответы без задержки."""
    from .models import WaMessage
    return WaMessage.objects.filter(channel=channel, phone=address, direction="out", by_ai=True,
                                    created_at__gte=now - timedelta(hours=WINDOW_HOURS)).exists()


def set_paused(clinic, channel, address, paused, reason=""):
    from .models import ChatBotState
    ChatBotState.all_clinics.update_or_create(clinic=clinic, channel=channel, address=address,
                                              defaults={"paused": paused, "reason": reason[:200]})


def _send(ctx, text):
    from .models import WaMessage
    if ctx.channel == "wa":
        from .whatsapp import wa_send_text
        ok = bool(wa_send_text(ctx.address, text))
    else:
        from .telegram import tg_send_text
        ok = bool(tg_send_text(ctx.address, html.escape(text)))
    WaMessage.objects.create(patient=ctx.patient, direction="out", channel=ctx.channel, phone=ctx.address,
                             body=text, by_ai=True, ok=ok, clinic=ctx.clinic)
    return ok


def _in_work_hours(now):
    from apps.appointments.views import _clinic_work_window
    ws, we, _a, _b = _clinic_work_window()
    return ws <= now.time() <= we


def _message_text(m):
    if m.body and not m.media_type:
        return m.body
    if m.media_type in ("voice", "audio") and m.media_file:
        if not m.transcript:
            try:
                with m.media_file.open("rb") as f:
                    text, _err = core.transcribe(f, m.media_file.name.rsplit("/", 1)[-1])
                m.transcript = text or "(неразборчиво)"
                m.save(update_fields=["transcript"])
            except Exception:  # noqa: BLE001
                log.exception("patient_assistant: голосовое не распознано")
                m.transcript = "(голосовое сообщение — не удалось распознать)"
        return "🎤 " + m.transcript
    return m.body or "(%s)" % (m.get_media_type_display() or "сообщение")


FAST_WAIT_SECONDS = 5   # ночью / в разговоре, который ведёт ассистент: пауза, чтобы собрать 2–3 сообщения подряд


def _find_patient(channel, address):
    if channel != "wa":
        return None
    from apps.patients.models import Patient, normalize_phone
    return Patient.objects.filter(phone_norm=normalize_phone(address)).first()


def tick_clinic(clinic, now=None, out=None):
    """Ответить в чатах этой клиники, где пациент ждёт. Возвращает число ответов.
    out — функция для журнала (вызовы инструментов ассистента)."""
    from apps.settings_clinic.models import ClinicSettings
    from apps.tenancy import set_current_clinic
    from .models import WaMessage
    set_current_clinic(clinic)
    cs = ClinicSettings.get()
    if not (cs.ai_patient_bot and core.openai_enabled()):
        return 0
    now = now or timezone.now()
    since = max(now - timedelta(hours=WINDOW_HOURS), cs.ai_patient_since or now - timedelta(hours=WINDOW_HOURS))
    pending = list(WaMessage.objects.filter(direction="in", ai_status="", created_at__gte=since)
                   .select_related("patient").order_by("created_at"))
    WaMessage.objects.filter(direction="in", ai_status="", created_at__lt=since).update(ai_status="skip")
    chats = {}
    for m in pending:
        chats.setdefault((m.channel, m.phone), []).append(m)
    delay = timedelta(minutes=cs.ai_patient_delay_min or 5)
    night = not _in_work_hours(timezone.localtime(now))
    answered = 0
    for (channel, address), msgs in chats.items():
        ids = [m.pk for m in msgs]
        if channel == "tg" and not msgs[-1].patient_id:
            WaMessage.objects.filter(pk__in=ids).update(ai_status="skip")   # Telegram без привязки — ведёт бот с кнопками
            continue
        if is_paused(clinic, channel, address, now):
            WaMessage.objects.filter(pk__in=ids).update(ai_status="skip")
            continue
        # менеджер подключился к чату из CRM — ассистент замолкает
        if _manager_replied_in_crm(clinic, channel, address, now):
            manager_joined(clinic, channel, address)
            WaMessage.objects.filter(pk__in=ids).update(ai_status="skip")
            continue
        # ночью или если разговор уже ведёт ассистент — отвечаем сразу, иначе ждём менеджера
        fast = night or _ai_leads_chat(channel, address, now)
        wait = timedelta(seconds=FAST_WAIT_SECONDS) if fast else delay
        if now - msgs[-1].created_at < wait:
            continue
        patient = next((m.patient for m in reversed(msgs) if m.patient_id), None) or _find_patient(channel, address)
        ctx = PCtx(clinic, channel, address, patient)
        hist_qs = WaMessage.objects.filter(channel=channel, phone=address).order_by("-created_at")[:HISTORY]
        history = [{"role": "user" if m.direction == "in" else "assistant", "text": _message_text(m)}
                   for m in reversed(list(hist_qs))]
        reply = run(ctx, history)
        if out:
            stamp = timezone.localtime(now).strftime("%d.%m %H:%M:%S")
            for line in ctx.trace:
                out("%s clinic=%s ..%s %s" % (stamp, clinic.pk, address[-4:], line))
            out("%s clinic=%s ..%s ответ: %s" % (stamp, clinic.pk, address[-4:], (reply or "—")[:200].replace("\n", " ")))
        WaMessage.objects.filter(pk__in=ids).update(ai_status="done" if reply else "skip")
        if not reply:
            continue
        _send(ctx, reply)
        answered += 1
        if ctx.events:
            who = ctx.patient.full_name if ctx.patient else address
            _notify_admins(ctx, "🤖 Ассистент: %s" % who, "; ".join(ctx.events))
    return answered
