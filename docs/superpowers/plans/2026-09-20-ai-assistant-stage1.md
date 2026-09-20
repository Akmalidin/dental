# ИИ-помощник, первый этап — реализация

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ассистент отвечает на вопросы о данных своей клиники и помнит разговор при переходе между страницами.

**Architecture:** Новое приложение `apps/assistant/`. Модель вызывает инструменты (function calling), инструменты читают данные через clinic-scoped менеджеры Django — идентификатор клиники модели не доверяется. История разговора переезжает из переменной в `app.js` в таблицы БД. OpenAI основной, существующий YandexGPT остаётся запасным.

**Tech Stack:** Django 5.1, PostgreSQL 16, OpenAI Chat Completions через `urllib` — в проекте намеренно не тянут HTTP-библиотеки ради одного эндпоинта, см. `apps/notifications/whatsapp.py` и `voice.py`.

**Spec:** `docs/superpowers/specs/2026-09-20-ai-assistant-design.md`

## Global Constraints

- Приложение регистрируется в `INSTALLED_APPS` в `config/settings/development.py` — именно эти настройки используют и `manage.py test`, и прод (`server.py` делает `from .development import *`; `base.py` с django_tenants там сознательно не используется, см. докстринг `server.py`). Для единообразия с остальными приложениями добавить и в `TENANT_APPS` в `config/settings/base.py`.
- Модели с данными клиники наследуют `ClinicScopedModel` из `apps/tenancy.py`.
- Инструменты читают только через менеджеры `.objects`, которые скоупятся `ClinicManager`. Использование `.all_objects` и `.all_clinics` в инструментах запрещено.
- Модель никогда не получает и не передаёт идентификатор клиники — он берётся из запроса через `get_current_clinic()`.
- Никаких записей в БД от имени модели: только чтение. Писать разрешено лишь в `Conversation` и `Message`.
- HTTP к OpenAI через `urllib.request`, без пакета `openai` в зависимостях.
- Тесты запускаются `venv/bin/python manage.py test <label>`, настройки `config.settings.development` — значение по умолчанию в `manage.py`.
- Тесты не ходят в сеть: HTTP провайдера мокается.
- Комментарии и строки интерфейса на русском, как в остальном проекте.

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `apps/assistant/apps.py` | `AssistantConfig` |
| `apps/assistant/models.py` | `Conversation`, `Message` — память и журнал |
| `apps/assistant/tools.py` | реестр инструментов: схемы для модели и функции чтения |
| `apps/assistant/provider.py` | вызов OpenAI, разбор ответа, запасной путь на YandexGPT |
| `apps/assistant/service.py` | оркестрация: история, провайдер, инструмент, сохранение |
| `apps/assistant/urls.py` и `views.py` | GET активной беседы, POST очистки |
| `apps/assistant/tests.py` | тесты, главный — межклиниковая изоляция |
| `config/settings/base.py` | регистрация приложения |
| `config/urls.py` | подключение `apps.assistant.urls` |
| `apps/notifications/views.py` | `voice_command(mode=chat)` делегирует в `service.answer()` |
| `static/newui/app.js` | история берётся с сервера, а не из памяти вкладки |

Порядок задач: память (1) — инструменты (2, 3) — провайдер (4) — оркестрация (5) — интеграция (6) — фронтенд (7). Каждая задача заканчивается проходящими тестами и коммитом.

---
### Task 1: Модели памяти разговора

**Files:**
- Create: `apps/assistant/__init__.py`, `apps/assistant/apps.py`, `apps/assistant/models.py`, `apps/assistant/migrations/__init__.py`, `apps/assistant/tests.py`
- Modify: `config/settings/base.py` — список `TENANT_APPS`

**Interfaces:**
- Consumes: `ClinicScopedModel` из `apps.tenancy`
- Produces: `Conversation.active_for(user)` -> `Conversation`; `Conversation.add(role, text, tool_name="", tool_args=None, rows_count=None)` -> `Message`; `Conversation.recent(limit=12)` -> список `Message` в хронологическом порядке

- [ ] **Step 1: Создать каркас приложения**

```bash
mkdir -p apps/assistant/migrations
touch apps/assistant/__init__.py apps/assistant/migrations/__init__.py
```

Файл `apps/assistant/apps.py`:

```python
from django.apps import AppConfig


class AssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.assistant"
    verbose_name = "ИИ-помощник"
```

- [ ] **Step 2: Зарегистрировать приложение**

В `config/settings/base.py`, в списке `TENANT_APPS`, сразу после строки с `"apps.reports",` добавить строку `    "apps.assistant",`

- [ ] **Step 3: Написать падающий тест памяти**

Файл `apps/assistant/tests.py`:

```python
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.assistant.models import Conversation
from apps.tenancy import set_current_clinic, clear_current_clinic
from apps.users.models import Clinic, User


class ConversationMemoryTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника П", slug="clinic-memory")
        set_current_clinic(self.clinic)
        self.user = User.objects.create(login="memo", name="Мемо", clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    def test_active_for_creates_one_conversation(self):
        first = Conversation.active_for(self.user)
        second = Conversation.active_for(self.user)
        self.assertEqual(first.pk, second.pk)

    def test_stale_conversation_is_replaced(self):
        old = Conversation.active_for(self.user)
        old.add("user", "давний вопрос")
        Conversation.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - datetime.timedelta(hours=13)
        )
        fresh = Conversation.active_for(self.user)
        self.assertNotEqual(old.pk, fresh.pk)

    def test_recent_returns_chronological_tail(self):
        conv = Conversation.active_for(self.user)
        for i in range(15):
            conv.add("user", "вопрос %d" % i)
        recent = conv.recent(limit=12)
        self.assertEqual(len(recent), 12)
        self.assertEqual(recent[0].text, "вопрос 3")
        self.assertEqual(recent[-1].text, "вопрос 14")

    def test_add_records_tool_call(self):
        conv = Conversation.active_for(self.user)
        msg = conv.add("assistant", "нашёл 3", tool_name="find_patient",
                       tool_args={"query": "Иван"}, rows_count=3)
        self.assertEqual(msg.tool_name, "find_patient")
        self.assertEqual(msg.tool_args["query"], "Иван")
        self.assertEqual(msg.rows_count, 3)
```

- [ ] **Step 4: Запустить тест и убедиться, что он падает**

Run: `venv/bin/python manage.py test apps.assistant -v 2`
Expected: FAIL, ModuleNotFoundError про `apps.assistant.models`

- [ ] **Step 5: Написать модели**

Файл `apps/assistant/models.py`:

```python
import datetime

from django.db import models
from django.utils import timezone

from apps.tenancy import ClinicScopedModel

# Через сколько без новых реплик разговор считается завершённым. 12 часов —
# это «в пределах смены»: вернувшись после обеда, сотрудник продолжает тот
# же разговор, а на следующее утро начинает с чистого листа, и история не
# превращается в одну бесконечную ленту.
STALE_AFTER = datetime.timedelta(hours=12)


class Conversation(ClinicScopedModel):
    """Беседа сотрудника с ассистентом. Одна активная на пользователя."""

    user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="assistant_conversations",
        verbose_name="Сотрудник",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="Закрыта")

    class Meta:
        verbose_name = "Беседа с ассистентом"
        verbose_name_plural = "Беседы с ассистентом"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return "Беседа %s от %s" % (self.user_id, self.created_at)

    @classmethod
    def active_for(cls, user):
        """Текущая беседа сотрудника. Создаёт новую, если прошлая устарела
        или была закрыта кнопкой «Очистить»."""
        conv = (cls.objects.filter(user=user, closed_at__isnull=True)
                .order_by("-updated_at").first())
        if conv is not None and timezone.now() - conv.updated_at < STALE_AFTER:
            return conv
        return cls.objects.create(user=user)

    def add(self, role, text, tool_name="", tool_args=None, rows_count=None):
        msg = Message.objects.create(
            conversation=self, role=role, text=text,
            tool_name=tool_name, tool_args=tool_args or {}, rows_count=rows_count,
        )
        # updated_at двигаем явно: auto_now срабатывает на save() самой
        # беседы, а пишем мы в дочернюю таблицу.
        Conversation.objects.filter(pk=self.pk).update(updated_at=timezone.now())
        self.refresh_from_db(fields=["updated_at"])
        return msg

    def recent(self, limit=12):
        """Последние реплики в хронологическом порядке — как их ждёт модель."""
        tail = list(self.messages.order_by("-created_at", "-pk")[:limit])
        return list(reversed(tail))


class Message(models.Model):
    """Реплика беседы. Поля tool_* это журнал: видно, какой инструмент
    отработал и сколько строк ушло во внешнюю модель."""

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "Сотрудник"), (ROLE_ASSISTANT, "Ассистент")]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    text = models.TextField(blank=True)
    tool_name = models.CharField(max_length=64, blank=True, verbose_name="Инструмент")
    tool_args = models.JSONField(default=dict, blank=True, verbose_name="Параметры")
    rows_count = models.IntegerField(null=True, blank=True, verbose_name="Строк возвращено")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Реплика"
        verbose_name_plural = "Реплики"
        ordering = ["created_at", "pk"]

    def __str__(self):
        return "%s: %s" % (self.role, self.text[:50])
```

- [ ] **Step 6: Создать миграцию**

Run: `venv/bin/python manage.py makemigrations assistant`
Expected: создан `apps/assistant/migrations/0001_initial.py`

- [ ] **Step 7: Прогнать тесты**

Run: `venv/bin/python manage.py test apps.assistant -v 2`
Expected: PASS, 4 теста

- [ ] **Step 8: Коммит**

```bash
git add apps/assistant config/settings/base.py
git commit -m "Ассистент: серверная память разговора"
```

---
### Task 2: Реестр инструментов и поиск пациента

Самая важная задача плана: здесь закладывается механизм, который не даёт данным одной клиники утечь в другую. Инструмент получает от модели только прикладные параметры и никогда — идентификатор клиники.

**Files:**
- Create: `apps/assistant/tools.py`
- Modify: `apps/assistant/tests.py` — добавить класс тестов

**Interfaces:**
- Consumes: `Patient` из `apps.patients.models`
- Produces:
  - `TOOLS` — словарь `{имя: Tool}`
  - `Tool` — namedtuple `(name, description, parameters, fn)`, где `parameters` это JSON Schema для function calling, а `fn(user, **kwargs)` возвращает `list[dict]`
  - `run_tool(name, user, args)` -> `(rows, error)`; `rows` это `list[dict]`, `error` это строка или `None`
  - `openai_schemas()` -> `list[dict]` в формате поля `tools` запроса OpenAI

- [ ] **Step 1: Написать падающий тест изоляции**

Дописать в `apps/assistant/tests.py`:

```python
from apps.assistant.tools import run_tool, openai_schemas
from apps.patients.models import Patient
from apps.users.models import Branch


class ToolClinicIsolationTestCase(TestCase):
    """Главный тест безопасности: инструмент, вызванный сотрудником одной
    клиники, не должен возвращать ничего из другой — даже если пациенты
    названы одинаково."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника А", slug="tool-clinic-a")
        self.clinic_b = Clinic.objects.create(name="Клиника Б", slug="tool-clinic-b")
        self.branch_a = Branch.objects.create(
            name="А", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(
            name="Б", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.user_a = User.objects.create(login="tool-a", name="А", clinic=self.clinic_a)
        set_current_clinic(self.clinic_a)
        Patient.objects.create(first_name="Иван", last_name="Тестов", phone="111",
                               branch=self.branch_a, clinic=self.clinic_a)
        set_current_clinic(self.clinic_b)
        Patient.objects.create(first_name="Иван", last_name="Тестов", phone="222",
                               branch=self.branch_b, clinic=self.clinic_b)

    def tearDown(self):
        clear_current_clinic()

    def test_find_patient_returns_only_own_clinic(self):
        set_current_clinic(self.clinic_a)
        rows, error = run_tool("find_patient", self.user_a, {"query": "Иван"})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phone"], "111")

    def test_find_patient_by_phone(self):
        set_current_clinic(self.clinic_a)
        rows, error = run_tool("find_patient", self.user_a, {"query": "111"})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)

    def test_unknown_tool_returns_error(self):
        set_current_clinic(self.clinic_a)
        rows, error = run_tool("drop_everything", self.user_a, {})
        self.assertEqual(rows, [])
        self.assertIsNotNone(error)

    def test_schemas_are_wellformed(self):
        schemas = openai_schemas()
        self.assertTrue(schemas)
        for s in schemas:
            self.assertEqual(s["type"], "function")
            self.assertIn("name", s["function"])
            self.assertIn("parameters", s["function"])
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `venv/bin/python manage.py test apps.assistant.tests.ToolClinicIsolationTestCase -v 2`
Expected: FAIL, ModuleNotFoundError про `apps.assistant.tools`

- [ ] **Step 3: Написать реестр и первый инструмент**

Файл `apps/assistant/tools.py`:

```python
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
```

- [ ] **Step 4: Прогнать тесты**

Run: `venv/bin/python manage.py test apps.assistant -v 2`
Expected: PASS, 8 тестов

- [ ] **Step 5: Коммит**

```bash
git add apps/assistant/tools.py apps/assistant/tests.py
git commit -m "Ассистент: реестр инструментов и поиск пациента"
```

---
### Task 3: Остальные инструменты первого этапа

**Files:**
- Modify: `apps/assistant/tools.py` — четыре функции и четыре записи в `TOOLS`
- Modify: `apps/assistant/tests.py` — тесты на них

**Interfaces:**
- Consumes: `Appointment` из `apps.appointments.models`, `Payment` из `apps.finance.models`, `Patient` из `apps.patients.models`
- Produces: инструменты `appointments_on_date`, `patients_with_debt`, `revenue_for_period`, `doctor_workload` — все вызываются через тот же `run_tool`

- [ ] **Step 1: Написать падающий тест**

Дописать в `apps/assistant/tests.py`:

```python
import datetime as dt
from decimal import Decimal

from apps.appointments.models import Appointment


class AssistantToolsTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника И", slug="tools-clinic")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(
            name="Главный", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.doctor = User.objects.create(login="doc-tools", name="Доктор", clinic=self.clinic)
        self.user = User.objects.create(login="adm-tools", name="Админ", clinic=self.clinic)
        self.patient = Patient.objects.create(
            first_name="Пётр", last_name="Должников", phone="777",
            branch=self.branch, clinic=self.clinic)
        self.today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(self.today, dt.time(10, 0)))
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch,
            start_at=start, end_at=start + dt.timedelta(minutes=30),
            status=Appointment.STATUS_SCHEDULED, clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    def test_appointments_on_date(self):
        rows, error = run_tool("appointments_on_date", self.user,
                               {"date": self.today.isoformat()})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["patient"], self.patient.full_name)
        self.assertEqual(rows[0]["time"], "10:00")

    def test_appointments_on_bad_date_returns_error(self):
        rows, error = run_tool("appointments_on_date", self.user, {"date": "31.02.2026"})
        self.assertEqual(rows, [])
        self.assertIsNotNone(error)

    def test_patients_with_debt(self):
        Patient.all_objects.filter(pk=self.patient.pk).update(balance=Decimal("-500"))
        rows, error = run_tool("patients_with_debt", self.user, {})
        self.assertIsNone(error)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["debt"], 500.0)

    def test_doctor_workload_counts_appointments(self):
        rows, error = run_tool("doctor_workload", self.user,
                               {"date_from": self.today.isoformat(),
                                "date_to": self.today.isoformat()})
        self.assertIsNone(error)
        by_doctor = {r["doctor"]: r["appointments"] for r in rows}
        self.assertEqual(by_doctor.get("Доктор"), 1)

    def test_revenue_for_period_empty(self):
        rows, error = run_tool("revenue_for_period", self.user,
                               {"date_from": self.today.isoformat(),
                                "date_to": self.today.isoformat()})
        self.assertIsNone(error)
        self.assertEqual(rows[0]["total"], 0.0)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `venv/bin/python manage.py test apps.assistant.tests.AssistantToolsTestCase -v 2`
Expected: FAIL, ошибки про неизвестный инструмент

- [ ] **Step 3: Добавить разбор даты и четыре функции**

Дописать в `apps/assistant/tools.py` перед словарём `TOOLS`:

```python
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
```

- [ ] **Step 4: Зарегистрировать инструменты в TOOLS**

Дописать в словарь `TOOLS` четыре записи:

```python
    "appointments_on_date": Tool(
        name="appointments_on_date",
        description="Записи на приём за конкретный день. Отменённые не включаются.",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата в формате ГГГГ-ММ-ДД"},
                "doctor_name": {"type": "string", "description": "Фильтр по имени врача, необязательно"},
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
                "limit": {"type": "integer", "description": "Сколько вернуть, по умолчанию 20"},
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
                "date_to": {"type": "string", "description": "Конец периода включительно, ГГГГ-ММ-ДД"},
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
                "date_to": {"type": "string", "description": "Конец периода включительно, ГГГГ-ММ-ДД"},
            },
            "required": ["date_from", "date_to"],
        },
        fn=_doctor_workload,
    ),
```

- [ ] **Step 5: Прогнать все тесты приложения**

Run: `venv/bin/python manage.py test apps.assistant -v 2`
Expected: PASS, 13 тестов

- [ ] **Step 6: Коммит**

```bash
git add apps/assistant/tools.py apps/assistant/tests.py
git commit -m "Ассистент: записи на дату, должники, выручка, загрузка врачей"
```

---
### Task 4: Провайдер OpenAI с запасным YandexGPT

**Files:**
- Create: `apps/assistant/provider.py`
- Modify: `config/settings/development.py` — добавить `OPENAI_MODEL`, поправить устаревший комментарий
- Modify: `apps/assistant/tests.py`

**Interfaces:**
- Consumes: `openai_schemas()` из `apps.assistant.tools`; `ask_ai` и `ai_enabled` из `apps.notifications.voice`
- Produces:
  - `openai_available()` -> `bool`
  - `complete(messages, tools=None)` -> `(result, error)`, где `result` это `{"kind": "text", "text": str}` либо `{"kind": "tool", "name": str, "args": dict}`
  - `fallback_answer(question, history)` -> `(text, error)` — ответ через YandexGPT, когда OpenAI недоступен

`OPENAI_MODEL` добавляется в `development.py`: прод (`server.py`) делает `from .development import *`, поэтому настройка доезжает до него сама. `base.py` в этой цепочке не участвует — `development.py` его не наследует.

- [ ] **Step 1: Добавить настройку модели**

В `config/settings/development.py`, в блоке OpenAI, заменить устаревший комментарий (он утверждает, что `OPENAI_API_KEY` не используется — с появлением ассистента это перестало быть правдой) и добавить строку:

```python
# ─── OpenAI ──────────────────────────────────────────────────────────────────
# OPENAI_ENABLED — общий тумблер голосового ввода; распознавание речи идёт
# локальным Whisper (apps/notifications/voice.py), ключ для него не нужен.
# OPENAI_API_KEY используется ассистентом (apps/assistant/provider.py) для
# function calling: он читает данные клиники через инструменты. Пустой ключ =
# ассистент работает на запасном YandexGPT, без доступа к данным.
OPENAI_ENABLED = os.environ.get("OPENAI_ENABLED", "") == "1"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
```

- [ ] **Step 2: Написать падающий тест провайдера**

Дописать в `apps/assistant/tests.py`:

```python
import json
from unittest import mock

from django.test import override_settings

from apps.assistant import provider


class ProviderTestCase(TestCase):
    """HTTP наружу не ходим: подменяем _post_openai — единственное место,
    где провайдер обращается в сеть."""

    @override_settings(OPENAI_API_KEY="")
    def test_not_available_without_key(self):
        self.assertFalse(provider.openai_available())

    @override_settings(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini")
    def test_text_answer_parsed(self):
        payload = {"choices": [{"message": {"content": "Готово"}}]}
        with mock.patch.object(provider, "_post_openai", return_value=(payload, None)):
            result, error = provider.complete([{"role": "user", "content": "привет"}])
        self.assertIsNone(error)
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], "Готово")

    @override_settings(OPENAI_API_KEY="k", OPENAI_MODEL="gpt-4o-mini")
    def test_tool_call_parsed(self):
        payload = {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "find_patient",
                          "arguments": json.dumps({"query": "Иван"})}}
        ]}}]}
        with mock.patch.object(provider, "_post_openai", return_value=(payload, None)):
            result, error = provider.complete([{"role": "user", "content": "найди Ивана"}])
        self.assertIsNone(error)
        self.assertEqual(result["kind"], "tool")
        self.assertEqual(result["name"], "find_patient")
        self.assertEqual(result["args"]["query"], "Иван")

    @override_settings(OPENAI_API_KEY="k")
    def test_broken_tool_arguments_reported(self):
        payload = {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "find_patient", "arguments": "{не json"}}
        ]}}]}
        with mock.patch.object(provider, "_post_openai", return_value=(payload, None)):
            result, error = provider.complete([{"role": "user", "content": "x"}])
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    @override_settings(OPENAI_API_KEY="k")
    def test_http_error_propagated(self):
        with mock.patch.object(provider, "_post_openai", return_value=(None, "таймаут")):
            result, error = provider.complete([{"role": "user", "content": "x"}])
        self.assertIsNone(result)
        self.assertEqual(error, "таймаут")
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run: `venv/bin/python manage.py test apps.assistant.tests.ProviderTestCase -v 2`
Expected: FAIL, ModuleNotFoundError про `apps.assistant.provider`

- [ ] **Step 4: Написать провайдер**

Файл `apps/assistant/provider.py`:

```python
"""Провайдер ответов ассистента.

OpenAI основной: только он умеет function calling, то есть сам решает,
каким инструментом прочитать данные клиники. Запасной — уже работающий
YandexGPT (apps/notifications/voice.py::ask_ai): он отвечает на общие
вопросы, но данных клиники не видит. Такой запас важен: без него любой сбой
у OpenAI превращал бы ассистента в неработающую кнопку.

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
```

- [ ] **Step 5: Прогнать тесты**

Run: `venv/bin/python manage.py test apps.assistant -v 2`
Expected: PASS, 18 тестов

- [ ] **Step 6: Коммит**

```bash
git add apps/assistant/provider.py apps/assistant/tests.py config/settings/development.py
git commit -m "Ассистент: провайдер OpenAI с запасным YandexGPT"
```

---
### Task 5: Оркестрация — service.answer()

Связывает память, провайдера и инструменты. Здесь же ограничение на число обращений к модели: один вопрос это максимум два вызова (первый выбирает инструмент, второй формулирует ответ по его данным). Без этого зациклившаяся модель может перебирать инструменты бесконечно и сжечь бюджет.

**Files:**
- Create: `apps/assistant/service.py`
- Modify: `apps/assistant/tests.py`

**Interfaces:**
- Consumes: `Conversation` из `apps.assistant.models`; `openai_schemas`, `run_tool` из `apps.assistant.tools`; `complete`, `fallback_answer`, `openai_available` из `apps.assistant.provider`
- Produces: `answer(user, question)` -> `(text, error)`. При успехе `error` это `None`, при неудаче `text` это `None`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `apps/assistant/tests.py`:

```python
from apps.assistant import service


class ServiceAnswerTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника С", slug="svc-clinic")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(
            name="Главный", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.user = User.objects.create(login="svc", name="Сотрудник", clinic=self.clinic)
        Patient.objects.create(first_name="Анна", last_name="Петрова", phone="555",
                               branch=self.branch, clinic=self.clinic)

    def tearDown(self):
        clear_current_clinic()

    @override_settings(OPENAI_API_KEY="k")
    def test_plain_answer_is_saved(self):
        with mock.patch.object(service.provider, "complete",
                               return_value=({"kind": "text", "text": "Привет"}, None)):
            text, error = service.answer(self.user, "здравствуй")
        self.assertIsNone(error)
        self.assertEqual(text, "Привет")
        conv = Conversation.active_for(self.user)
        roles = [m.role for m in conv.recent()]
        self.assertEqual(roles, ["user", "assistant"])

    @override_settings(OPENAI_API_KEY="k")
    def test_tool_call_then_answer(self):
        replies = [
            ({"kind": "tool", "name": "find_patient", "args": {"query": "Анна"}}, None),
            ({"kind": "text", "text": "Нашёл: Петрова Анна"}, None),
        ]
        with mock.patch.object(service.provider, "complete", side_effect=replies):
            text, error = service.answer(self.user, "найди Анну")
        self.assertIsNone(error)
        self.assertIn("Анна", text)
        conv = Conversation.active_for(self.user)
        last = conv.recent()[-1]
        self.assertEqual(last.tool_name, "find_patient")
        self.assertEqual(last.rows_count, 1)

    @override_settings(OPENAI_API_KEY="")
    def test_falls_back_when_no_key(self):
        with mock.patch.object(service.provider, "fallback_answer",
                               return_value=("Общий ответ", None)) as fb:
            text, error = service.answer(self.user, "что такое кариес")
        self.assertIsNone(error)
        self.assertEqual(text, "Общий ответ")
        self.assertTrue(fb.called)

    @override_settings(OPENAI_API_KEY="k")
    def test_openai_error_falls_back(self):
        with mock.patch.object(service.provider, "complete", return_value=(None, "недоступен")):
            with mock.patch.object(service.provider, "fallback_answer",
                                   return_value=("Запасной", None)):
                text, error = service.answer(self.user, "вопрос")
        self.assertIsNone(error)
        self.assertEqual(text, "Запасной")

    @override_settings(OPENAI_API_KEY="k")
    def test_empty_question_rejected(self):
        text, error = service.answer(self.user, "   ")
        self.assertIsNone(text)
        self.assertIsNotNone(error)
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `venv/bin/python manage.py test apps.assistant.tests.ServiceAnswerTestCase -v 2`
Expected: FAIL, ModuleNotFoundError про `apps.assistant.service`

- [ ] **Step 3: Написать service.py**

Файл `apps/assistant/service.py`:

```python
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
# перебирала бы инструменты бесконечно.
MAX_ROUNDS = 2

SYSTEM_PROMPT = (
    "Ты — помощник сотрудников стоматологической клиники в системе ODONTIS. "
    "Отвечай кратко и по-русски. Данные о пациентах, записях и финансах бери "
    "ТОЛЬКО через инструменты — ничего не придумывай и не оценивай на глаз. "
    "Если инструмент вернул пусто, так и скажи. Ты работаешь только с данными "
    "своей клиники. Сегодня %s."
)


def _history_for_model(conv):
    """Историю беседы переводим в формат сообщений OpenAI."""
    return [
        {"role": m.role, "content": m.text}
        for m in conv.recent()
        if m.text
    ]


def _history_for_fallback(conv):
    """ask_ai ждёт другой формат: [{"role": ..., "text": ...}]."""
    return [{"role": m.role, "text": m.text} for m in conv.recent() if m.text]


def answer(user, question):
    """Ответ на вопрос сотрудника. Возвращает (текст, ошибка)."""
    question = (question or "").strip()
    if not question:
        return None, "Пустой вопрос"

    conv = Conversation.active_for(user)
    conv.add("user", question)

    if not provider.openai_available():
        return _fallback(conv, question)

    messages = [{"role": "system", "content": SYSTEM_PROMPT % timezone.localdate()}]
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
```

- [ ] **Step 4: Прогнать тесты**

Run: `venv/bin/python manage.py test apps.assistant -v 2`
Expected: PASS, 23 теста

- [ ] **Step 5: Коммит**

```bash
git add apps/assistant/service.py apps/assistant/tests.py
git commit -m "Ассистент: оркестрация ответа с инструментами и запасным путём"
```

---
### Task 6: Интеграция с существующим чатом

**Files:**
- Create: `apps/assistant/views.py`, `apps/assistant/urls.py`
- Modify: `config/urls.py` — один `path(...)`
- Modify: `apps/assistant/service.py` — расширить сигнатуру `answer()`
- Modify: `apps/notifications/views.py` — ветка `mode == "chat"` в `voice_command`
- Modify: `apps/assistant/tests.py`

**Interfaces:**
- Produces:
  - `GET /assistant/conversation/` -> `{"messages": [{"role": ..., "text": ...}, ...]}`
  - `POST /assistant/conversation/clear/` -> `{"ok": true}`
  - `answer(user, question, assistant_name="")` — сигнатура расширяется третьим необязательным параметром

Расширение сигнатуры обязательно: существующая ветка `mode=chat` пробрасывает в `ask_ai` имя ассистента из клиентской настройки, и без него перестанет работать ответ на вопрос «как тебя зовут».

- [ ] **Step 1: Расширить answer() именем ассистента**

В `apps/assistant/service.py` заменить системный промпт и сигнатуру:

```python
SYSTEM_PROMPT = (
    "Тебя зовут %s. Ты — помощник сотрудников стоматологической клиники в "
    "системе ODONTIS. Отвечай кратко и по-русски. Данные о пациентах, записях "
    "и финансах бери ТОЛЬКО через инструменты — ничего не придумывай и не "
    "оценивай на глаз. Если инструмент вернул пусто, так и скажи. Ты работаешь "
    "только с данными своей клиники. Сегодня %s."
)

DEFAULT_ASSISTANT_NAME = "ODONTIS"


def answer(user, question, assistant_name=""):
```

и строку сборки промпта внутри `answer()`:

```python
    name = (assistant_name or "").strip() or DEFAULT_ASSISTANT_NAME
    messages = [{"role": "system",
                 "content": SYSTEM_PROMPT % (name, timezone.localdate())}]
```

- [ ] **Step 2: Написать падающий тест эндпоинтов**

Дописать в `apps/assistant/tests.py`:

```python
from django.test import Client


class ConversationEndpointsTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Э", slug="ep-clinic")
        set_current_clinic(self.clinic)
        self.user = User.objects.create(login="ep", name="Сотрудник", clinic=self.clinic)
        self.client = Client()
        self.client.force_login(self.user)

    def tearDown(self):
        clear_current_clinic()

    def test_conversation_returns_saved_messages(self):
        conv = Conversation.active_for(self.user)
        conv.add("user", "первый вопрос")
        conv.add("assistant", "первый ответ")
        resp = self.client.get("/assistant/conversation/")
        self.assertEqual(resp.status_code, 200)
        messages = resp.json()["messages"]
        self.assertEqual([m["text"] for m in messages],
                         ["первый вопрос", "первый ответ"])

    def test_clear_starts_new_conversation(self):
        conv = Conversation.active_for(self.user)
        conv.add("user", "старое")
        resp = self.client.post("/assistant/conversation/clear/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        messages = self.client.get("/assistant/conversation/").json()["messages"]
        self.assertEqual(messages, [])

    def test_anonymous_is_redirected(self):
        self.client.logout()
        resp = self.client.get("/assistant/conversation/")
        self.assertIn(resp.status_code, (302, 403))
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run: `venv/bin/python manage.py test apps.assistant.tests.ConversationEndpointsTestCase -v 2`
Expected: FAIL, 404 вместо 200

- [ ] **Step 4: Написать вью и маршруты**

Файл `apps/assistant/views.py`:

```python
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assistant.models import Conversation


@login_required
def conversation(request):
    """Реплики активной беседы — панель подгружает их при открытии, поэтому
    история переживает переход между страницами."""
    conv = Conversation.active_for(request.user)
    return JsonResponse({
        "messages": [
            {"role": m.role, "text": m.text}
            for m in conv.recent(limit=50)
        ],
    })


@login_required
@require_POST
def conversation_clear(request):
    """Кнопка «Очистить»: закрываем текущую беседу, следующий вопрос начнёт
    новую. Реплики не удаляем — они остаются журналом."""
    conv = Conversation.active_for(request.user)
    conv.closed_at = timezone.now()
    conv.save(update_fields=["closed_at"])
    return JsonResponse({"ok": True})
```

Файл `apps/assistant/urls.py`:

```python
from django.urls import path

from apps.assistant import views

urlpatterns = [
    path("conversation/", views.conversation, name="assistant_conversation"),
    path("conversation/clear/", views.conversation_clear, name="assistant_conversation_clear"),
]
```

В `config/urls.py`, рядом с остальными include-ами приложений (после строки с `apps.notifications.urls`), добавить:

```python
    path("assistant/", include("apps.assistant.urls")),
```

- [ ] **Step 5: Переключить mode=chat на новый сервис**

В `apps/notifications/views.py`, в `voice_command`, заменить ветку `if mode == "chat":` целиком на:

```python
    if mode == "chat":
        # Ответ собирает apps.assistant: он держит память разговора в БД и
        # умеет читать данные клиники через инструменты. Прежний прямой
        # вызов ask_ai остался там же, но уже как запасной путь — см.
        # apps.assistant.provider.fallback_answer.
        from apps.assistant.service import answer as assistant_answer

        assistant_name = (request.POST.get("assistant_name") or "").strip()
        text, err = assistant_answer(request.user, transcript, assistant_name=assistant_name)
        if err:
            return JsonResponse({"error": err, "transcript": transcript}, status=502)
        return JsonResponse({"transcript": transcript, "answer": text})
```

Поле `history` из запроса больше не используется: историю держит сервер. Разбор `history` в начале `voice_command` оставить как есть — он безвреден и используется другими режимами.

- [ ] **Step 6: Прогнать тесты приложения и смежных**

Run: `venv/bin/python manage.py test apps.assistant apps.notifications -v 2`
Expected: PASS, все тесты обоих приложений

- [ ] **Step 7: Коммит**

```bash
git add apps/assistant config/urls.py apps/notifications/views.py
git commit -m "Ассистент: эндпоинты беседы и переключение чата на новый сервис"
```

---
### Task 7: Фронтенд — история с сервера

Последний шаг: панель перестаёт быть источником истины. Сейчас `voiceChatHistory` это массив в памяти вкладки, и он обнуляется при каждом переходе между страницами, потому что страницы серверные, а не SPA.

**Files:**
- Modify: `static/newui/app.js` — блок панели ассистента (искать по `voiceChatHistory`, около строки 7275)

**Interfaces:**
- Consumes: `GET /assistant/conversation/`, `POST /assistant/conversation/clear/` из Task 6

Автотестов на этот шаг нет: в проекте нет инфраструктуры для JS-тестов, заводить её ради одного файла несоразмерно. Поэтому проверка ручная, по чек-листу в Step 4.

- [ ] **Step 1: Заменить комментарий и объявление истории**

Найти в `static/newui/app.js` блок с комментарием, который начинается со слов «Панель ассистента: чат с памятью» и объявление `let voiceChatHistory=[];`. Заменить комментарий и объявление на:

```javascript
/* ===== Панель ассистента: чат с памятью, текст+голос, озвучка =====
   История живёт на сервере (apps/assistant, таблицы Conversation/Message) и
   подгружается при открытии панели — поэтому переход на другую /new/*
   страницу её больше не теряет. voiceChatHistory здесь только зеркало для
   отрисовки: источник истины на сервере, на него же опирается модель. */
let voiceChatHistory=[];
let voiceChatLoaded=false;
```

- [ ] **Step 2: Подгружать историю при открытии панели**

В функции `openVoiceChatPanel()` после `panel.classList.remove('hidden');` добавить:

```javascript
  if(!voiceChatLoaded){
    fetch('/assistant/conversation/', {credentials:'same-origin'})
      .then(r=>r.ok?r.json():null)
      .then(d=>{
        if(d && Array.isArray(d.messages)){
          voiceChatHistory = d.messages.map(m=>({role:m.role, text:m.text}));
          voiceChatLoaded = true;
          renderVoiceChatPanel();
        }
      })
      .catch(()=>{ /* сеть недоступна — панель просто откроется пустой */ });
  }
```

- [ ] **Step 3: Перестать отправлять историю на сервер**

Найти строку, где история добавляется в запрос:

```javascript
  if(withHistory) fd.append('history', JSON.stringify(voiceChatHistory.slice(-12)));
```

Заменить на:

```javascript
  // history больше не отправляем: сервер держит беседу сам (apps/assistant).
  // Параметр withHistory сохранён — им пользуются режимы schedule/visit.
```

Если после правки переменная `withHistory` нигде не читается, удалить и её объявление, и передачу в вызовах — мёртвый код оставлять не нужно.

- [ ] **Step 4: Проверить вручную**

Запустить сервер и пройти по шагам:

1. Открыть панель ассистента, задать вопрос, получить ответ.
2. Перейти на другую страницу `/new/*` и снова открыть панель — **прошлая переписка должна быть на месте**. Это и есть главная проверка задачи.
3. Нажать «Очистить» — панель пустеет; после перехода на другую страницу она по-прежнему пуста.
4. Задать вопрос про данные: «сколько записей на сегодня» — ответ должен опираться на реальные записи, а не быть общими словами.
5. Открыть панель под сотрудником другой клиники — чужой переписки быть не должно.

- [ ] **Step 5: Коммит**

```bash
git add static/newui/app.js
git commit -m "Ассистент: история подгружается с сервера и переживает переход между страницами"
```

---

## Проверка плана относительно спеки

Пройдено после написания плана.

**Покрытие спеки.** Память разговора — Task 1 и 7. Модуль `apps/assistant/` — Tasks 1–6. Инструменты поверх clinic-scoped менеджеров — Tasks 2 и 3. Провайдер OpenAI с запасным YandexGPT — Task 4. Оркестрация и журнал — Task 5. Интеграция с существующим чатом — Task 6.

**Что сознательно отложено на второй этап** (в спеке это отдельный этап, не пропуск): SQL-песочница со схемой `ai` и ролью БД, management-команда очистки бесед старше 30 дней, потолок расходов на клинику.

**Согласованность имён.** `Conversation.add()` и `Conversation.recent()` объявлены в Task 1 и используются в Tasks 5–7 с теми же параметрами. `run_tool(name, user, args)` объявлен в Task 2, используется в Tasks 3 и 5. `complete()` и `fallback_answer()` объявлены в Task 4, используются в Task 5. Сигнатура `answer()` расширяется в Task 6 осознанно — это отмечено прямо в задаче, чтобы расхождение не выглядело ошибкой.
