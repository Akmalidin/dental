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
         "full_name": {"type": "string"},
         "phone": {"type": "string", "description": "телефон, если пациент написал в Telegram без номера"}},
        ["start"]),
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


def _ensure_patient(ctx, full_name, phone=""):
    from apps.patients.models import Patient, normalize_phone
    name = (full_name or "").strip()
    if ctx.patient is not None and ctx.channel == "tg" and not ctx.patient.phone:
        # написал боту, не поделившись номером: для записи нужны ФИО и телефон
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())
        if len(name.split()) < 2 or len(digits) < 9:
            return None, ("Для записи нужны имя, фамилия и номер телефона пациента — спроси одним "
                          "сообщением (или пусть нажмёт в боте «Поделиться номером»), потом передай "
                          "full_name и phone")
        from apps.patients.models import normalize_phone
        other = Patient.objects.filter(phone_norm=normalize_phone(digits)).exclude(pk=ctx.patient.pk).first()
        if other is not None:
            ctx.patient = merge_tg_card(ctx.patient, other)
            return ctx.patient, None
        parts = name.split(None, 1)
        ctx.patient.last_name, ctx.patient.first_name = parts[0][:100], parts[1][:100]
        ctx.patient.phone = "+" + digits
        ctx.patient.save()
        return ctx.patient, None
    if ctx.patient is not None and not ctx.patient.last_name:
        # карточку завели автоматически по номеру WhatsApp — имя ещё не спрашивали
        if len(name.split()) < 2:
            return None, "Спроси у пациента имя и фамилию одним вопросом, потом сразу запиши (full_name)"
        parts = name.split(None, 1)
        ctx.patient.last_name, ctx.patient.first_name = parts[0][:100], parts[1][:100]
        ctx.patient.save(update_fields=["last_name", "first_name"])
    if ctx.patient is not None:
        return ctx.patient, None
    if ctx.channel != "wa":
        return None, "Сначала нужно подтвердить номер телефона в Telegram-боте клиники (/start)."
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


def _t_book(ctx, doctor_id=None, doctor_name="", start=None, duration_min=None, service_ids=None, full_name="",
            phone="", **_):
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
    patient, perr = _ensure_patient(ctx, full_name, phone)
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
    if ctx.patient and ctx.patient.last_name:
        who = "Пациент: %s (patient_id=%s)." % (ctx.patient.full_name, ctx.patient.pk)
    elif ctx.patient and ctx.channel == "tg" and not ctx.patient.phone:
        who = ("Новый пациент из Telegram (имя в профиле: %s), номер не известен. На вопросы отвечай как "
               "обычно; для записи спроси имя, фамилию и номер телефона одним сообщением и передай "
               "full_name и phone." % ctx.patient.first_name)
    elif ctx.patient:
        who = ("Новый пациент (имя в WhatsApp: %s) — для записи спроси имя и фамилию и передай их "
               "в full_name." % ctx.patient.first_name)
    else:
        who = "Пациент ещё не найден в базе клиники — для записи спроси имя и фамилию."
    doctors = "; ".join("id=%s %s" % (d.pk, d.name) for d in _clinic_doctors()) or "нет"
    cs = ClinicSettings.get()
    return (
        f"Ты — вежливый ассистент стоматологической клиники «{cs.name}» в "
        f"{'WhatsApp' if ctx.channel == 'wa' else 'Telegram'}. Сейчас {now.strftime('%Y-%m-%d %H:%M')}, "
        f"{core.WEEKDAYS[now.weekday()]} (время клиники). {who}\n"
        f"Врачи клиники: {doctors}. Используй именно эти id.\n"
        f"Валюта клиники: {cs.currency_label} ({cs.currency}). Все цены — только в этой валюте, "
        "никогда не пиши рубли, доллары и т.п., если валюта другая.\n"
        "Ты помогаешь записаться, перенести или отменить СВОЮ запись, рассказываешь об услугах, ценах, "
        "адресе и часах работы. Правила:\n"
        "- Все данные бери только из инструментов, ничего не выдумывай (время, цены, врачей).\n"        "- Прайс назван по-русски: в search_services всегда передавай русские слова (тиш олиш/sug'urish → "
        "удаление, пломба/plomba → пломба, тиш тозалаш → чистка, коронка, имплант, канал → канал). Если не "
        "нашлось — попробуй 1–2 других слова (удал, зуб мудр…), прежде чем говорить, что цены нет.\n"
        "- Цены — только из прайса клиники (search_services). Называй конкретные услуги с ценами "
        "(до 5 позиций, например «Установка импланта (Osstem) — 25 000 сом»), а не общий диапазон. Если "
        "в прайсе нет нужной услуги — скажи, что точную стоимость назовёт врач на консультации.\n"
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
        "- Пиши на языке пациента: русский, кыргызский, узбекский, казахский, английский и т.д. "
        "(если пациент пишет латиницей — латиницей). Никогда не отказывай из-за языка. "
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
    """Ассистент выключен в чате вручную или сам позвал администратора.
    Ответ менеджера паузой не считается (см. manager_active)."""
    from .models import ChatBotState
    return (ChatBotState.all_clinics.filter(clinic=clinic, channel=channel, address=address, paused=True)
            .exclude(reason=MANAGER_REASON).exists())


def manager_active(clinic, channel, address, now=None):
    """Менеджер недавно отвечал в этом чате (с телефона клиники или из CRM) —
    ассистент не отвечает сразу, а ждёт менеджера ClinicSettings.ai_patient_delay_min
    минут после каждого нового сообщения пациента."""
    from .models import ChatBotState, WaMessage
    now = now or timezone.now()
    hold = now - timedelta(hours=MANAGER_HOLD_HOURS)
    st = ChatBotState.all_clinics.filter(clinic=clinic, channel=channel, address=address).first()
    if st and st.paused and st.reason == MANAGER_REASON and st.updated_at > hold:
        return True
    after = st.updated_at if st and not st.paused and st.updated_at > hold else hold
    return WaMessage.objects.filter(channel=channel, phone=address, direction="out", by_ai=False,
                                    sent_by__isnull=False, created_at__gt=after).exists()


def manager_joined(clinic, channel, address):
    """Менеджер ответил пациенту (из CRM или с телефона клиники)."""
    if is_paused(clinic, channel, address):
        return      # ассистент выключен вручную — не превращаем это в мягкий режим
    set_paused(clinic, channel, address, True, reason=MANAGER_REASON)


def _norm_text(t):
    return " ".join((t or "").replace("*", "").replace("_", "").split()).lower()


def sent_by_system(channel, address, text, minutes=3):
    """Исходящее с номера клиники — это сообщение, которое только что отправила
    сама система (напоминание, уведомление, ответ ассистента или из CRM)?"""
    from apps.patients.models import normalize_phone
    from apps.tenancy import unscoped
    from .models import WaMessage
    norm = normalize_phone(address)
    if not norm:
        return False
    with unscoped():
        recent = list(WaMessage.objects.filter(channel=channel, phone__endswith=norm, direction="out",
                                               created_at__gte=timezone.now() - timedelta(minutes=minutes))
                      .values_list("body", flat=True)[:20])
    if not recent:
        return False
    t = _norm_text(text)
    if not t:
        return True     # медиа/пустой текст сразу после нашей отправки — считаем своим
    return any(t[:60] in _norm_text(b) or _norm_text(b)[:60] in t for b in recent if b)


def resume_chat(clinic, channel, address, hours=1):
    """Ассистента в чате снова включили: сообщения пациента за последний час,
    пропущенные на паузе (и после которых менеджер не отвечал), — ответить."""
    from apps.patients.models import normalize_phone
    from .models import WaMessage
    norm = normalize_phone(address)
    if not norm:
        return 0
    qs = WaMessage.all_clinics.filter(clinic=clinic, channel=channel, phone__endswith=norm)
    since = timezone.now() - timedelta(hours=hours)
    last_human = (qs.filter(direction="out", by_ai=False, sent_by__isnull=False)
                  .order_by("-created_at").values_list("created_at", flat=True).first())
    if last_human and last_human > since:
        since = last_human
    return qs.filter(direction="in", ai_status="skip", created_at__gt=since).update(ai_status="")


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


def _shared_number():
    """Номер WhatsApp общего (системного) инстанса Green-API — кэш на сутки."""
    from django.conf import settings
    from django.core.cache import cache
    if not (getattr(settings, "GREENAPI_ID_INSTANCE", "") and getattr(settings, "GREENAPI_TOKEN", "")):
        return ""
    num = cache.get("wa_shared_number")
    if num is None:
        num = ""
        try:
            import urllib.request
            base = (getattr(settings, "GREENAPI_API_URL", "") or "https://api.greenapi.com").rstrip("/")
            url = "%s/waInstance%s/getWaSettings/%s" % (base, settings.GREENAPI_ID_INSTANCE, settings.GREENAPI_TOKEN)
            with urllib.request.urlopen(url, timeout=10) as r:
                num = str(json.loads(r.read().decode("utf-8")).get("phone") or "")
        except Exception:  # noqa: BLE001
            log.warning("patient_assistant: не удалось узнать номер общего инстанса")
        cache.set("wa_shared_number", num, 86400 if num else 600)
    return num


def clinic_for_unknown_number(phone, id_instance=""):
    """Клиника для входящего с номера, которого нет среди пациентов.
    Без клиники сообщение никто не видит и ассистент на него не отвечает.
    1) свой инстанс клиники; 2) клиника, которая недавно писала на этот номер;
    3) сотрудник клиники с этим номером; 4) владелец общего номера WhatsApp
    (ClinicSettings.wa_phone), а если не указан — единственная клиника на общих
    ключах с включённым ассистентом."""
    from apps.patients.models import normalize_phone
    from apps.settings_clinic.models import ClinicSettings
    from apps.users.models import Clinic, User
    from .models import WaMessage
    if id_instance:
        cs = ClinicSettings.objects.filter(wa_id_instance=str(id_instance)).exclude(clinic=None).first()
        if cs:
            return cs.clinic
    norm = normalize_phone(phone)
    if not norm:
        return None
    last = (WaMessage.all_clinics.filter(channel="wa", phone__endswith=norm, direction="out", clinic__isnull=False,
                                         created_at__gte=timezone.now() - timedelta(days=60))
            .order_by("-created_at").first())
    if last:
        return last.clinic
    staff = [u for u in User.objects.filter(is_active=True, clinic__isnull=False).exclude(phone="")
             .only("phone", "clinic") if normalize_phone(u.phone) == norm]
    if staff:
        return Clinic.objects.filter(pk=staff[0].clinic_id).first()
    shared = ClinicSettings.objects.exclude(clinic=None).filter(wa_id_instance="")
    own = normalize_phone(_shared_number())
    if own:
        for cs in shared.exclude(wa_phone=""):
            if normalize_phone(cs.wa_phone) == own:
                return cs.clinic
    with_bot = list(shared.filter(ai_patient_bot=True)[:2])
    return with_bot[0].clinic if len(with_bot) == 1 else None


def ensure_chat_patient(clinic, phone, name=""):
    """Карточка пациента для переписки с нового номера WhatsApp.
    «Мессенджеры» строятся по карточкам: без неё чат нового клиента не виден
    и ответить ему из CRM нельзя. Имя — из профиля WhatsApp, фамилия пустая:
    так ассистент понимает, что настоящее имя ещё не спрашивали."""
    from apps.patients.models import LeadSource, Patient, normalize_phone
    from apps.tenancy import get_current_clinic, set_current_clinic
    from .models import WaMessage
    norm = normalize_phone(phone)
    if clinic is None or not norm:
        return None
    p = Patient.all_objects.filter(clinic=clinic, phone_norm=norm, is_deleted=False).order_by("-id").first()
    if p is None:
        prev = get_current_clinic()
        set_current_clinic(clinic)
        try:
            src = LeadSource.objects.filter(name__iexact="WhatsApp").first() or LeadSource.objects.create(name="WhatsApp")
            p = Patient(first_name=(name or "").strip()[:100] or "Новый клиент", last_name="",
                        phone="+" + "".join(ch for ch in str(phone) if ch.isdigit()), clinic=clinic, source=src)
            p.save()
        finally:
            set_current_clinic(prev)
    WaMessage.all_clinics.filter(clinic=clinic, channel="wa", phone=phone, patient__isnull=True).update(patient=p)
    return p


def _lead_source(name):
    from apps.patients.models import LeadSource
    return LeadSource.objects.filter(name__iexact=name).first() or LeadSource.objects.create(name=name)


def ensure_tg_patient(clinic, chat_id, from_user=None):
    """Карточка для человека, который пишет Telegram-боту, не поделившись номером.
    Без неё переписку не видно в «Мессенджерах» и ассистент не отвечает.
    Телефона нет, фамилия пустая — ассистент для записи спросит ФИО и номер,
    а «Поделиться номером» сольёт карточку с существующей (merge_tg_card)."""
    from apps.patients.models import Patient
    from apps.users.models import Branch
    p = Patient.objects.filter(telegram_chat_id=chat_id).first()
    if p is not None:
        return p
    u = from_user or {}
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip() or \
        (("@" + u["username"]) if u.get("username") else "Клиент Telegram")
    branch = (Branch.objects.filter(clinic=clinic, is_active=True, is_main=True).first()
              or Branch.objects.filter(clinic=clinic, is_active=True).first())
    p = Patient(first_name=name[:100], last_name="", phone="", telegram_chat_id=chat_id, branch=branch,
                clinic=clinic, source=_lead_source("Telegram"))
    p.save()
    return p


def merge_tg_card(auto, target):
    """Автокарточка Telegram (без телефона) → существующая карточка пациента:
    переписка и записи переезжают, автокарточка уходит в корзину."""
    from apps.appointments.models import Appointment
    from .models import WaMessage
    if auto is None or target is None or auto.pk == target.pk:
        return target
    WaMessage.all_clinics.filter(patient=auto).update(patient=target)
    Appointment.objects.filter(patient=auto).update(patient=target)
    chat_id = auto.telegram_chat_id
    type(auto).all_objects.filter(pk=auto.pk).update(telegram_chat_id=None)
    auto.refresh_from_db()
    auto.soft_delete()
    if chat_id and not target.telegram_chat_id:
        target.telegram_chat_id = chat_id
        target.save(update_fields=["telegram_chat_id"])
    return target


def assign_orphans(hours=2):
    """Недавние входящие WhatsApp без клиники или без карточки — привязать
    к клинике (clinic_for_unknown_number) и завести карточку (ensure_chat_patient)."""
    from .models import WaMessage
    since = timezone.now() - timedelta(hours=hours)
    for m in WaMessage.all_clinics.filter(direction="in", channel="wa", clinic__isnull=True, ai_status="",
                                          created_at__gte=since):
        clinic = clinic_for_unknown_number(m.phone)
        if clinic is not None:
            WaMessage.all_clinics.filter(pk=m.pk).update(clinic=clinic)
    # Telegram-бот: писали, не поделившись номером (раньше такие сообщения
    # пропускались) — карточка и ответ ассистента.
    from apps.users.models import Clinic
    for clinic_id, chat in set(WaMessage.all_clinics.filter(direction="in", channel="tg", clinic__isnull=False,
                                                            patient__isnull=True, created_at__gte=since)
                               .values_list("clinic_id", "phone")):
        clinic = Clinic.objects.filter(pk=clinic_id).first()
        if clinic is None or not str(chat).lstrip("-").isdigit() or str(chat).startswith("-"):
            continue
        from apps.tenancy import get_current_clinic, set_current_clinic
        prev = get_current_clinic()
        set_current_clinic(clinic)
        try:
            p = ensure_tg_patient(clinic, int(chat))
        finally:
            set_current_clinic(prev)
        WaMessage.all_clinics.filter(clinic=clinic, channel="tg", phone=chat, patient__isnull=True,
                                     created_at__gte=since).update(patient=p, ai_status="")
    seen = set()
    for clinic_id, phone in (WaMessage.all_clinics.filter(direction="in", channel="wa", clinic__isnull=False,
                                                          patient__isnull=True, created_at__gte=since)
                             .values_list("clinic_id", "phone")):
        if (clinic_id, phone) not in seen:
            seen.add((clinic_id, phone))
            from apps.users.models import Clinic
            ensure_chat_patient(Clinic.objects.filter(pk=clinic_id).first(), phone)


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
        # менеджер уже ответил на эти сообщения из CRM — ассистент не вмешивается
        if WaMessage.objects.filter(channel=channel, phone=address, direction="out", by_ai=False,
                                    sent_by__isnull=False, created_at__gt=msgs[0].created_at).exists():
            manager_joined(clinic, channel, address)
            WaMessage.objects.filter(pk__in=ids).update(ai_status="skip")
            continue
        # Менеджер ведёт чат — ждём его ответа обычную задержку (5 мин), и только
        # если он молчит, отвечает ассистент. Иначе ночью или в разговоре, который
        # ведёт ассистент, — сразу.
        fast = not manager_active(clinic, channel, address, now) and (night or _ai_leads_chat(channel, address, now))
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
