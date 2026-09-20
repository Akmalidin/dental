"""Инструменты ассистента — то, чем модель читает данные клиники.

Изоляция обеспечивается здесь, а не доверием к модели: каждый инструмент
ходит через обычные менеджеры (Patient.objects и т.п.), которые уже
скоупятся ClinicManager по текущей клинике (apps/tenancy.py). Модель
передаёт только прикладные параметры — дату, строку поиска, период — и
физически не может попросить чужую клинику.

Никаких .all_objects и .all_clinics: они обходят скоупинг.
"""
import collections

Tool = collections.namedtuple("Tool", "name description parameters fn")

# Сколько строк максимум уходит во внешнюю модель за один вызов. Ограничение
# и по деньгам (каждая строка это токены), и по здравому смыслу: ответ
# «нашлось 400 пациентов» бесполезен, надо уточнять запрос.
MAX_ROWS = 50


def _find_patient(user, query="", limit=20):
    from django.db.models import Q
    from apps.patients.models import Patient

    query = (query or "").strip()
    if not query:
        return []
    limit = min(int(limit or 20), MAX_ROWS)
    qs = Patient.objects.filter(
        Q(first_name__icontains=query)
        | Q(last_name__icontains=query)
        | Q(phone__icontains=query)
    ).order_by("last_name", "first_name")[:limit]
    return [
        {
            "id": p.pk,
            "name": p.full_name,
            "phone": p.phone,
            "birth_date": p.birth_date.isoformat() if p.birth_date else None,
            "debt": float(p.debt),
        }
        for p in qs
    ]


def _parse_date(value, field="date"):
    """ISO-дата от модели. Кидает ValueError с понятным текстом — run_tool
    превратит его в сообщение, которое модель объяснит пользователю."""
    import datetime

    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("Параметр %s должен быть датой в формате ГГГГ-ММ-ДД" % field)


def _appointments_on_date(user, date=None, doctor_name=""):
    from django.utils import timezone
    from apps.appointments.models import Appointment

    day = _parse_date(date, "date")
    qs = (Appointment.objects
          .filter(start_at__date=day)
          .exclude(status=Appointment.STATUS_CANCELLED)
          .select_related("patient", "doctor", "branch")
          .order_by("start_at"))
    if doctor_name:
        qs = qs.filter(doctor__name__icontains=doctor_name)
    return [
        {
            "id": a.pk,
            "time": timezone.localtime(a.start_at).strftime("%H:%M"),
            "patient": a.patient.full_name if a.patient else "",
            "doctor": a.doctor.name if a.doctor else "",
            "branch": a.branch.name if a.branch else "",
            "status": a.get_status_display(),
        }
        for a in qs[:MAX_ROWS]
    ]


def _patients_with_debt(user, limit=20):
    from apps.patients.models import Patient

    limit = min(int(limit or 20), MAX_ROWS)
    # Долг это отрицательный баланс (см. Patient.debt). Поле поддерживается
    # свежим через recalc_balance() из всех точек мутации — пересчитывать
    # здесь не нужно.
    qs = Patient.objects.filter(balance__lt=0).order_by("balance")[:limit]
    return [
        {"id": p.pk, "name": p.full_name, "phone": p.phone, "debt": float(p.debt)}
        for p in qs
    ]


def _revenue_for_period(user, date_from=None, date_to=None):
    from django.db.models import Sum
    from apps.finance.models import Payment

    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    qs = Payment.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    rows = (qs.values("branch__name", "type")
              .annotate(total=Sum("amount")).order_by("branch__name"))
    by_branch = {}
    for r in rows:
        branch = r["branch__name"] or "Без филиала"
        amount = float(r["total"] or 0)
        if r["type"] == Payment.TYPE_REFUND:
            amount = -amount
        by_branch[branch] = by_branch.get(branch, 0.0) + amount
    result = [{"branch": b, "total": round(v, 2)} for b, v in sorted(by_branch.items())]
    if not result:
        result = [{"branch": "Все филиалы", "total": 0.0}]
    return result


def _doctor_workload(user, date_from=None, date_to=None):
    from django.db.models import Count
    from apps.appointments.models import Appointment

    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    rows = (Appointment.objects
            .filter(start_at__date__gte=start, start_at__date__lte=end)
            .exclude(status=Appointment.STATUS_CANCELLED)
            .values("doctor__name")
            .annotate(appointments=Count("id"))
            .order_by("-appointments"))
    return [
        {"doctor": r["doctor__name"] or "Без врача", "appointments": r["appointments"]}
        for r in rows[:MAX_ROWS]
    ]


TOOLS = {
    "find_patient": Tool(
        name="find_patient",
        description="Найти пациента по имени, фамилии или телефону. "
                    "Возвращает id, имя, телефон, дату рождения и текущий долг.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Имя, фамилия или часть телефона",
                },
                "limit": {
                    "type": "integer",
                    "description": "Сколько записей вернуть, по умолчанию 20",
                },
            },
            "required": ["query"],
        },
        fn=_find_patient,
    ),
    "appointments_on_date": Tool(
        name="appointments_on_date",
        description="Записи на приём за конкретный день. Отменённые не включаются.",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата в формате ГГГГ-ММ-ДД"},
                "doctor_name": {"type": "string",
                                "description": "Фильтр по имени врача, необязательно"},
            },
            "required": ["date"],
        },
        fn=_appointments_on_date,
    ),
    "patients_with_debt": Tool(
        name="patients_with_debt",
        description="Пациенты с долгом, от большего к меньшему.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer",
                          "description": "Сколько вернуть, по умолчанию 20"},
            },
        },
        fn=_patients_with_debt,
    ),
    "revenue_for_period": Tool(
        name="revenue_for_period",
        description="Выручка за период в разрезе филиалов. Возвраты вычитаются.",
        parameters={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Начало периода, ГГГГ-ММ-ДД"},
                "date_to": {"type": "string",
                            "description": "Конец периода включительно, ГГГГ-ММ-ДД"},
            },
            "required": ["date_from", "date_to"],
        },
        fn=_revenue_for_period,
    ),
    "doctor_workload": Tool(
        name="doctor_workload",
        description="Сколько приёмов у каждого врача за период.",
        parameters={
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Начало периода, ГГГГ-ММ-ДД"},
                "date_to": {"type": "string",
                            "description": "Конец периода включительно, ГГГГ-ММ-ДД"},
            },
            "required": ["date_from", "date_to"],
        },
        fn=_doctor_workload,
    ),
}


def openai_schemas():
    """Описания инструментов в формате поля tools запроса OpenAI."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]


def run_tool(name, user, args):
    """Выполнить инструмент. Возвращает (строки, ошибка).

    Ошибка не выбрасывается наружу: она отдаётся модели текстом, чтобы та
    объяснила пользователю словами, а не уронила весь ответ."""
    tool = TOOLS.get(name)
    if tool is None:
        return [], "Неизвестный инструмент: %s" % name
    try:
        rows = tool.fn(user, **(args or {}))
    except TypeError as exc:
        return [], "Неверные параметры инструмента %s: %s" % (name, exc)
    except Exception as exc:
        return [], "Инструмент %s не отработал: %s" % (name, exc)
    return list(rows)[:MAX_ROWS], None
