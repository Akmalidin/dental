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
