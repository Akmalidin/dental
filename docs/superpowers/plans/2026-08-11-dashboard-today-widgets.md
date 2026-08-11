# Дашборд «Сегодня»: касса / загрузка врачей / новые заявки — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить на дашборд нового интерфейса (`/new/`) три read-only виджета: статус кассовой смены, % загрузки врачей сегодня, последние необработанные заявки (CRM-воронка).

**Architecture:** Три новых приватных Python-хелпера в `apps/users/views.py`, вызываемые из уже существующей `_newui_dashboard_data()` и мержащиеся в её возвращаемый dict. Тот же dict уже прокидывается в шаблон через `real_data` → `{{ real_data|json_script:"newui-real-data" }}` → глобальную JS-переменную `dashboardData` (обе части — уже существующий, неизменяемый код в `templates/newui/base.html`). Рендер новых виджетов — только в `templates/newui/dashboard.html`, через собственный `{% block extra_js %}` этого шаблона (сейчас пустой). Ноль новых моделей/миграций/URL.

**Tech Stack:** Django 5.1 (server-rendered), стандартный Django `TestCase` + `Client` (в проекте нет pytest/pytest-django — тесты гоняются через `manage.py test`), ванильный JS (без сборки/фреймворка) в `templates/newui/`.

## Global Constraints

- `templates/newui/base.html` **не редактируется** ни в одном task — параллельно с ним прямо сейчас работает другая сессия Claude Code (перевод строк на русский); весь новый CSS/JS живёт только в `dashboard.html`.
- Новые заголовки виджетов на дашборде — статичный русский текст без `data-i18n` (без правки base.html подключить переводы для новых строк нельзя — таблица переводов там). Явное, осознанное ограничение этой итерации, не случайный пропуск.
- Никаких новых моделей, миграций, URL, DRF-эндпоинтов. Используются только существующие: `apps.finance.models.CashShift`, `apps.users.models_salary.DoctorSchedule`, `apps.patients.models.Lead`.
- Никаких inline-действий (оплатить/взять в работу/открыть смену) на дашборде — виджеты read-only, со ссылкой-переходом на профильную страницу (`/new/cashdesk/`, `/new/schedule/`, `/new/funnel/`), как и остальные карточки на этой странице уже делают («Финансы →» и т.п.).
- Денежные суммы — `float(...)` при выходе из Decimal в JSON, как везде в `_newui_dashboard_data()`.
- Все тесты — в `apps/users/tests.py`, расширяют существующий `NewUIDashboardTestCase` (не создают новый класс), тем же паттерном: HTTP GET на `/new/`, парсинг `_extract_newui_real_data(resp.content.decode())`.

Референс: `docs/superpowers/specs/2026-08-11-dashboard-today-widgets-design.md`.

---

## Task 1: Backend — виджет «Касса»

**Files:**
- Modify: `apps/users/views.py` (новая функция `_dashboard_cash_summary`, добавляется сразу после `_newui_dashboard_data` — сейчас заканчивается на строке 163 пустой строкой перед `def _newui_patients_data():`; плюс один новый ключ в `return` самой `_newui_dashboard_data`)
- Test: `apps/users/tests.py` (расширить `NewUIDashboardTestCase`, класс начинается на строке 96)

**Interfaces:**
- Produces: `_dashboard_cash_summary(clinic) -> dict` с ключами `opened: bool, openedAt: str|None, openedBy: str|None, incomeTotal: float, refundTotal: float, balance: float`. Используется в Task 4 как `dashboardData.cashSummary` на фронте.

- [ ] **Step 1: Написать падающий тест**

Открыть `apps/users/tests.py`, в классе `NewUIDashboardTestCase` (строка 96) добавить два теста сразу после `test_dashboard_new_patients_counts_real_patient` (строка 174-177):

```python
    def test_dashboard_cash_summary_closed_by_default(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["dashboard"]["cashSummary"]["opened"], False)

    def test_dashboard_cash_summary_reflects_open_shift(self):
        from apps.finance.models import CashShift, Payment
        CashShift.objects.create(branch=self.branch, opened_by=self.director, opening_cash=1000, clinic=self.clinic)
        Payment.objects.create(
            patient=self.patient, amount=300, branch=self.branch, received_by=self.director,
            type=Payment.TYPE_INCOME, method=Payment.METHOD_CASH, clinic=self.clinic,
        )
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        cash = data["dashboard"]["cashSummary"]
        self.assertTrue(cash["opened"])
        self.assertEqual(cash["incomeTotal"], 300.0)
        self.assertEqual(cash["balance"], 1300.0)  # 1000 opening + 300 cash income
```

- [ ] **Step 2: Прогнать тесты, убедиться, что падают**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase -v 2`
Expected: `FAIL` — `KeyError: 'cashSummary'` (ключа ещё нет в `dashboard`).

- [ ] **Step 3: Реализовать `_dashboard_cash_summary`**

В `apps/users/views.py` сразу после конца функции `_newui_dashboard_data` (после строки `}` закрывающей `return {...}`, перед `def _newui_patients_data():`) добавить:

```python
def _dashboard_cash_summary(clinic):
    """Касса на дашборде: статус текущей смены главного филиала клиники +
    приход/возврат/баланс с момента открытия (та же логика, что
    _newui_cashdesk_data/CashShift.z_report, но сжато для карточки)."""
    from django.utils import timezone
    from apps.finance.models import CashShift
    from apps.users.models import Branch

    closed = {"opened": False, "openedAt": None, "openedBy": None,
              "incomeTotal": 0.0, "refundTotal": 0.0, "balance": 0.0}
    if not clinic:
        return closed

    branch = Branch.objects.filter(clinic=clinic, is_main=True).first() or Branch.objects.filter(clinic=clinic).first()
    shift = CashShift.objects.filter(branch=branch, status=CashShift.STATUS_OPEN).first() if branch else None
    if not shift:
        return closed

    z = shift.z_report()
    return {
        "opened": True,
        "openedAt": timezone.localtime(shift.opened_at).strftime("%d.%m.%Y %H:%M"),
        "openedBy": shift.opened_by.name if shift.opened_by else "—",
        "incomeTotal": float(z["incomeTotal"]),
        "refundTotal": float(z["refundTotal"]),
        "balance": float(z["expectedCash"]),
    }
```

Затем в `_newui_dashboard_data()` найти конец функции — блок:

```python
    return {
        "revenueToday": revenue_today,
        "revenueYesterday": revenue_yesterday,
        "revenueDeltaPct": revenue_delta_pct,
        "patientsToday": len(patients_today_ids),
        "newPatientsToday": new_patients_today,
        "newPatientsMonth": new_patients_month,
        "labOpenCount": lab_open_count,
        "labOverdueCount": lab_overdue_count,
        "weekBars": week_bars,
        "upcoming": upcoming,
        "recentPatients": recent_patients,
    }
```

и заменить на (добавлена одна строка `"cashSummary"`, плюс получение клиники в начале функции — сейчас `_newui_dashboard_data()` не принимает `clinic`, нужно получить его через `get_current_clinic()`, так же как это делает `_newui_cashdesk_data` косвенно через параметр; здесь проще взять текущую клинику из thread-local, т.к. функция вызывается без аргументов из `newui_dashboard(request)`):

Добавить в самое начало тела `_newui_dashboard_data()` (сразу после docstring, перед `from datetime import timedelta`):

```python
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
```

И заменить `return {...}` на:

```python
    return {
        "revenueToday": revenue_today,
        "revenueYesterday": revenue_yesterday,
        "revenueDeltaPct": revenue_delta_pct,
        "patientsToday": len(patients_today_ids),
        "newPatientsToday": new_patients_today,
        "newPatientsMonth": new_patients_month,
        "labOpenCount": lab_open_count,
        "labOverdueCount": lab_overdue_count,
        "weekBars": week_bars,
        "upcoming": upcoming,
        "recentPatients": recent_patients,
        "cashSummary": _dashboard_cash_summary(clinic),
    }
```

- [ ] **Step 4: Прогнать тесты снова, убедиться, что проходят**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase -v 2`
Expected: `OK` (6 тестов: 4 старых + 2 новых).

- [ ] **Step 5: Коммит**

```bash
git add apps/users/views.py apps/users/tests.py
git commit -m "Дашборд: виджет кассовой смены (cashSummary)"
```

---

## Task 2: Backend — виджет «Загрузка врачей»

**Files:**
- Modify: `apps/users/views.py` (новые функции `_dashboard_minutes_between`, `_dashboard_doctors_load`; ещё один ключ в `return` `_newui_dashboard_data`)
- Test: `apps/users/tests.py` (тот же `NewUIDashboardTestCase`)

**Interfaces:**
- Consumes: ничего из Task 1 напрямую (независимая функция), но правит тот же `return {...}` блок — писать поверх результата Task 1.
- Produces: `_dashboard_doctors_load(clinic) -> list[dict]`, каждый элемент `{doctorId: int, name: str, occupancyPct: int}`. Используется в Task 4 как `dashboardData.doctorsLoad`.

- [ ] **Step 1: Написать падающий тест**

Добавить в `NewUIDashboardTestCase`, после тестов из Task 1:

```python
    def test_dashboard_doctors_load_excludes_doctor_without_schedule_today(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["dashboard"]["doctorsLoad"], [])

    def test_dashboard_doctors_load_reflects_todays_appointments(self):
        from apps.users.models_salary import DoctorSchedule
        import datetime as dt
        from django.utils import timezone
        DoctorSchedule.objects.create(
            doctor=self.doctor, branch=self.branch,
            day_of_week=timezone.localdate().weekday(),
            start_time=dt.time(9, 0), end_time=dt.time(18, 0), is_working=True,
        )
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        load = data["dashboard"]["doctorsLoad"]
        self.assertEqual(len(load), 1)
        self.assertEqual(load[0]["doctorId"], self.doctor.pk)
        self.assertEqual(load[0]["name"], "Врач DB")
        self.assertEqual(load[0]["occupancyPct"], 11)  # 60 занятых мин / 540 доступных (09:00–18:00)
```

Примечание: приём на 60 минут (12:00–13:00) для `self.doctor` уже создан в `setUp()` — см. `apps/users/tests.py:139-143`.

- [ ] **Step 2: Прогнать тесты, убедиться, что падают**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase -v 2`
Expected: `FAIL` — `KeyError: 'doctorsLoad'`.

- [ ] **Step 3: Реализовать `_dashboard_doctors_load`**

В `apps/users/views.py`, сразу после `_dashboard_cash_summary` (перед `def _newui_patients_data():`), добавить:

```python
def _dashboard_minutes_between(start_time, end_time):
    """Разница между двумя datetime.time в минутах (time сам по себе
    вычитать нельзя — комбинируем с фиктивной датой)."""
    import datetime as dt
    start_dt = dt.datetime.combine(dt.date.min, start_time)
    end_dt = dt.datetime.combine(dt.date.min, end_time)
    return int((end_dt - start_dt).total_seconds() // 60)


def _dashboard_doctors_load(clinic):
    """Загрузка врачей сегодня: % занятых минут от рабочего графика
    (apps.users.models_salary.DoctorSchedule). Показываются только врачи,
    у которых есть рабочий график на сегодняшний день недели — отсутствие в
    списке означает выходной, а не 0% загрузки."""
    from django.utils import timezone
    from apps.appointments.models import Appointment
    from apps.users.models import clinic_doctors
    from apps.users.models_salary import DoctorSchedule

    if not clinic:
        return []

    today = timezone.localdate()
    doctors = list(clinic_doctors(clinic))
    doctor_ids = [d.pk for d in doctors]

    available_minutes = {}
    schedules = DoctorSchedule.objects.filter(
        doctor_id__in=doctor_ids, day_of_week=today.weekday(), is_working=True,
    )
    for s in schedules:
        minutes = _dashboard_minutes_between(s.start_time, s.end_time)
        available_minutes[s.doctor_id] = available_minutes.get(s.doctor_id, 0) + minutes

    booked_minutes = {}
    appts = (Appointment.objects
             .filter(doctor_id__in=list(available_minutes.keys()), start_at__date=today)
             .exclude(status=Appointment.STATUS_CANCELLED))
    for a in appts:
        minutes = max(int((a.end_at - a.start_at).total_seconds() // 60), 0)
        booked_minutes[a.doctor_id] = booked_minutes.get(a.doctor_id, 0) + minutes

    by_id = {d.pk: d for d in doctors}
    result = []
    for doctor_id, avail in available_minutes.items():
        doctor = by_id.get(doctor_id)
        if doctor is None or avail <= 0:
            continue
        booked = booked_minutes.get(doctor_id, 0)
        result.append({
            "doctorId": doctor_id,
            "name": doctor.name,
            "occupancyPct": round(booked / avail * 100),
        })
    result.sort(key=lambda r: r["occupancyPct"], reverse=True)
    return result
```

Затем в `_newui_dashboard_data()` добавить в `return {...}` ещё одну строку (после `"cashSummary": ...,` из Task 1):

```python
        "doctorsLoad": _dashboard_doctors_load(clinic),
```

- [ ] **Step 4: Прогнать тесты снова, убедиться, что проходят**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase -v 2`
Expected: `OK` (8 тестов).

- [ ] **Step 5: Коммит**

```bash
git add apps/users/views.py apps/users/tests.py
git commit -m "Дашборд: виджет загрузки врачей (doctorsLoad)"
```

---

## Task 3: Backend — виджет «Новые заявки»

**Files:**
- Modify: `apps/users/views.py` (новая функция `_dashboard_funnel_new`; ещё один ключ в `return` `_newui_dashboard_data`)
- Test: `apps/users/tests.py` (тот же `NewUIDashboardTestCase`)

**Interfaces:**
- Produces: `_dashboard_funnel_new(clinic, limit=10) -> list[dict]`, каждый элемент `{id: int, name: str, phone: str, createdAt: str}`. Используется в Task 4 как `dashboardData.funnelNew`.

- [ ] **Step 1: Написать падающий тест**

Добавить в `NewUIDashboardTestCase`, после тестов из Task 2:

```python
    def test_dashboard_funnel_new_empty_by_default(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["dashboard"]["funnelNew"], [])

    def test_dashboard_funnel_new_lists_unprocessed_leads(self):
        from apps.patients.models import Lead
        Lead.objects.create(name="Азизбекова М.", phone="+996555221109", stage=Lead.STAGE_NEW, clinic=self.clinic)
        Lead.objects.create(name="Обработанная", phone="+996555000000", stage=Lead.STAGE_COMPLETED, clinic=self.clinic)
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        funnel = data["dashboard"]["funnelNew"]
        self.assertEqual(len(funnel), 1)
        self.assertEqual(funnel[0]["name"], "Азизбекова М.")
        self.assertEqual(funnel[0]["phone"], "+996555221109")
```

- [ ] **Step 2: Прогнать тесты, убедиться, что падают**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase -v 2`
Expected: `FAIL` — `KeyError: 'funnelNew'`.

- [ ] **Step 3: Реализовать `_dashboard_funnel_new`**

В `apps/users/views.py`, сразу после `_dashboard_doctors_load` (перед `def _newui_patients_data():`), добавить:

```python
def _dashboard_funnel_new(clinic, limit=10):
    """Последние необработанные заявки (CRM-воронка, apps.patients.models.Lead,
    stage="new") для карточки на дашборде."""
    from django.utils import timezone
    from apps.patients.models import Lead

    if not clinic:
        return []
    leads = (Lead.objects.filter(clinic=clinic, stage=Lead.STAGE_NEW)
             .order_by("-created_at")[:limit])
    return [{
        "id": lead.pk, "name": lead.name, "phone": lead.phone,
        "createdAt": timezone.localtime(lead.created_at).strftime("%d.%m %H:%M"),
    } for lead in leads]
```

Затем в `_newui_dashboard_data()` добавить в `return {...}` ещё одну строку (после `"doctorsLoad": ...,` из Task 2):

```python
        "funnelNew": _dashboard_funnel_new(clinic),
```

- [ ] **Step 4: Прогнать тесты снова, убедиться, что проходят**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase -v 2`
Expected: `OK` (10 тестов).

- [ ] **Step 5: Коммит**

```bash
git add apps/users/views.py apps/users/tests.py
git commit -m "Дашборд: виджет новых заявок (funnelNew)"
```

---

## Task 4: Frontend — рендер трёх виджетов в dashboard.html

**Files:**
- Modify: `templates/newui/dashboard.html` (весь файл, сейчас 38 строк — добавляется новая строка карточек + `{% block extra_js %}`)
- Test: `apps/users/tests.py` (тот же `NewUIDashboardTestCase`)
- Do NOT modify: `templates/newui/base.html`

**Interfaces:**
- Consumes: `dashboardData.cashSummary`, `dashboardData.doctorsLoad`, `dashboardData.funnelNew` — глобальная JS-переменная `dashboardData`, уже заполняемая в `base.html` из `data.dashboard` (см. IIFE `loadRealStaffData`, `templates/newui/base.html:3782-3828`), и глобальная функция `fmtSom(n)` (`templates/newui/base.html:3835`). Обе уже существуют и не редактируются в этом task.

- [ ] **Step 1: Написать падающий тест на разметку**

Добавить в `NewUIDashboardTestCase`, после тестов из Task 3:

```python
    def test_dashboard_page_has_new_widget_containers(self):
        resp = self.client.get("/new/")
        html = resp.content.decode()
        self.assertIn('id="dash-cash-summary"', html)
        self.assertIn('id="dash-doctors-load"', html)
        self.assertIn('id="dash-funnel-new"', html)
```

- [ ] **Step 2: Прогнать тест, убедиться, что падает**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase.test_dashboard_page_has_new_widget_containers -v 2`
Expected: `FAIL` — контейнеров ещё нет в шаблоне.

- [ ] **Step 3: Добавить разметку и extra_js в dashboard.html**

Текущий `templates/newui/dashboard.html` (38 строк) целиком:

```html
{% extends "newui/base.html" %}
{% block page_title %}Дашборд{% endblock %}
{% block content %}
      <div class="topbar">
        <div><h1 data-i18n="title_dashboard">Дашборд</h1><div class="topbar-sub"><span class="dot-live"></span> <span data-i18n="w_updated_now">обновлено только что</span></div></div>
        <div class="topbar-right">
          <div class="search-box">⌕ <span data-i18n="w_search_hint_dash">Пациент, запись, заявка…</span></div>
          <button class="icon-btn">🔔<span class="badge-dot"></span></button>
          <button class="btn btn-cobalt" onclick="openNewAppt()">+ <span data-i18n="w_new_appt">Новая запись</span></button>
        </div>
      </div>
      <div class="page">
        <div class="kpi-grid">
          <div class="card kpi b-cobalt"><div class="kpi-top"><span data-i18n="w_revenue_today">Выручка сегодня</span><span class="kpi-delta" id="kpi-revenue-delta"></span></div><b id="kpi-revenue-today">—</b><span class="lbl" id="kpi-revenue-sub"></span></div>
          <div class="card kpi b-teal"><div class="kpi-top"><span data-i18n="w_patients_today">Пациентов сегодня</span></div><b id="kpi-patients-today">—</b><span class="lbl" id="kpi-patients-sub"></span></div>
          <div class="card kpi b-amber"><div class="kpi-top"><span data-i18n="w_new_patients_month">Новых пациентов (месяц)</span></div><b id="kpi-new-patients-month">—</b><span class="lbl" id="kpi-new-patients-sub"></span></div>
          <div class="card kpi b-coral"><div class="kpi-top"><span data-i18n="w_lab_orders">Заказы лаборатории</span><span class="kpi-delta down" id="kpi-lab-delta"></span></div><b id="kpi-lab-open">—</b><span class="lbl" data-i18n="w_open_orders">открытых заказов</span></div>
        </div>

        <div class="grid-2">
          <div class="card">
            <div class="card-head"><h3 data-i18n="w_revenue_week">Выручка за неделю</h3><span class="link-btn" onclick="location.href='/new/finance/'" data-i18n="w_link_finance">Финансы →</span></div>
            <div class="card-body">
              <div class="bars" id="week-revenue-bars"></div>
            </div>
          </div>
          <div class="card">
            <div class="card-head"><h3 data-i18n="w_new_patients">Новые пациенты</h3><span class="link-btn" onclick="location.href='/new/patients/'" data-i18n="w_link_patients">Пациенты →</span></div>
            <div class="card-body" id="recent-patients-list"></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h3 data-i18n="w_upcoming_today">Ближайшие приёмы сегодня</h3><span class="link-btn" onclick="location.href='/new/schedule/'" data-i18n="w_link_schedule">Расписание →</span></div>
          <div class="card-body" id="upcoming-appts-list"></div>
        </div>
      </div>
{% endblock %}
```

Заменить целиком на:

```html
{% extends "newui/base.html" %}
{% block page_title %}Дашборд{% endblock %}
{% block content %}
      <div class="topbar">
        <div><h1 data-i18n="title_dashboard">Дашборд</h1><div class="topbar-sub"><span class="dot-live"></span> <span data-i18n="w_updated_now">обновлено только что</span></div></div>
        <div class="topbar-right">
          <div class="search-box">⌕ <span data-i18n="w_search_hint_dash">Пациент, запись, заявка…</span></div>
          <button class="icon-btn">🔔<span class="badge-dot"></span></button>
          <button class="btn btn-cobalt" onclick="openNewAppt()">+ <span data-i18n="w_new_appt">Новая запись</span></button>
        </div>
      </div>
      <div class="page">
        <div class="kpi-grid">
          <div class="card kpi b-cobalt"><div class="kpi-top"><span data-i18n="w_revenue_today">Выручка сегодня</span><span class="kpi-delta" id="kpi-revenue-delta"></span></div><b id="kpi-revenue-today">—</b><span class="lbl" id="kpi-revenue-sub"></span></div>
          <div class="card kpi b-teal"><div class="kpi-top"><span data-i18n="w_patients_today">Пациентов сегодня</span></div><b id="kpi-patients-today">—</b><span class="lbl" id="kpi-patients-sub"></span></div>
          <div class="card kpi b-amber"><div class="kpi-top"><span data-i18n="w_new_patients_month">Новых пациентов (месяц)</span></div><b id="kpi-new-patients-month">—</b><span class="lbl" id="kpi-new-patients-sub"></span></div>
          <div class="card kpi b-coral"><div class="kpi-top"><span data-i18n="w_lab_orders">Заказы лаборатории</span><span class="kpi-delta down" id="kpi-lab-delta"></span></div><b id="kpi-lab-open">—</b><span class="lbl" data-i18n="w_open_orders">открытых заказов</span></div>
        </div>

        <div class="grid-2">
          <div class="card">
            <div class="card-head"><h3 data-i18n="w_revenue_week">Выручка за неделю</h3><span class="link-btn" onclick="location.href='/new/finance/'" data-i18n="w_link_finance">Финансы →</span></div>
            <div class="card-body">
              <div class="bars" id="week-revenue-bars"></div>
            </div>
          </div>
          <div class="card">
            <div class="card-head"><h3 data-i18n="w_new_patients">Новые пациенты</h3><span class="link-btn" onclick="location.href='/new/patients/'" data-i18n="w_link_patients">Пациенты →</span></div>
            <div class="card-body" id="recent-patients-list"></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h3 data-i18n="w_upcoming_today">Ближайшие приёмы сегодня</h3><span class="link-btn" onclick="location.href='/new/schedule/'" data-i18n="w_link_schedule">Расписание →</span></div>
          <div class="card-body" id="upcoming-appts-list"></div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:14px;">
          <div class="card">
            <div class="card-head"><h3>Касса</h3><span class="link-btn" onclick="location.href='/new/cashdesk/'">Касса →</span></div>
            <div class="card-body" id="dash-cash-summary"></div>
          </div>
          <div class="card">
            <div class="card-head"><h3>Загрузка врачей</h3><span class="link-btn" onclick="location.href='/new/schedule/'">Расписание →</span></div>
            <div class="card-body" id="dash-doctors-load"></div>
          </div>
          <div class="card">
            <div class="card-head"><h3>Новые заявки</h3><span class="link-btn" onclick="location.href='/new/funnel/'">Заявки →</span></div>
            <div class="card-body" id="dash-funnel-new"></div>
          </div>
        </div>
      </div>
{% endblock %}

{% block extra_js %}
<style>
.docload-row{display:flex;align-items:center;gap:10px;padding:7px 0;}
.docload-name{width:96px;flex-shrink:0;font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.docload-track{flex:1;height:8px;border-radius:4px;background:var(--mist);overflow:hidden;}
.docload-fill{height:100%;border-radius:4px;}
.docload-pct{width:36px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink-soft);flex-shrink:0;}
</style>
<script>
(function(){
  if(!dashboardData) return;
  const d=dashboardData;

  const cash=d.cashSummary || {opened:false};
  const cashEl=document.getElementById('dash-cash-summary');
  if(cashEl){
    if(!cash.opened){
      cashEl.innerHTML='<div style="font-size:12.5px;color:var(--ink-soft);padding:10px 2px;">Смена не открыта</div>';
    } else {
      cashEl.innerHTML=`
        <div class="row"><div class="row-main"><b>Приход</b><span>с открытия смены</span></div><span class="pill teal">${fmtSom(cash.incomeTotal)}</span></div>
        <div class="row"><div class="row-main"><b>Возврат</b><span>с открытия смены</span></div><span class="pill coral">${fmtSom(cash.refundTotal)}</span></div>
        <div class="row" style="border-bottom:none;"><div class="row-main"><b>Баланс</b><span>${cash.openedBy||'—'} · ${cash.openedAt||''}</span></div><span class="pill cobalt">${fmtSom(cash.balance)}</span></div>
      `;
    }
  }

  const load=d.doctorsLoad || [];
  const loadEl=document.getElementById('dash-doctors-load');
  if(loadEl){
    loadEl.innerHTML = load.length===0
      ? '<div style="font-size:12.5px;color:var(--ink-soft);padding:10px 2px;">Сегодня никто не работает по графику</div>'
      : load.map(doc=>{
          const color = doc.occupancyPct>=90?'var(--coral)':(doc.occupancyPct>=60?'var(--amber)':'var(--cobalt)');
          return `<div class="docload-row"><span class="docload-name" title="${doc.name}">${doc.name}</span><div class="docload-track"><div class="docload-fill" style="width:${Math.min(doc.occupancyPct,100)}%;background:${color}"></div></div><span class="docload-pct">${doc.occupancyPct}%</span></div>`;
        }).join('');
  }

  const funnel=d.funnelNew || [];
  const funnelEl=document.getElementById('dash-funnel-new');
  if(funnelEl){
    funnelEl.innerHTML = funnel.length===0
      ? '<div style="font-size:12.5px;color:var(--ink-soft);padding:10px 2px;">Новых заявок нет</div>'
      : funnel.map(l=>`<div class="row"><div class="row-avatar">${(l.name[0]||'?')}</div><div class="row-main"><b>${l.name}</b><span>${l.phone||''} · ${l.createdAt}</span></div></div>`).join('');
  }
})();
</script>
{% endblock %}
```

- [ ] **Step 4: Прогнать тест снова, убедиться, что проходит**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase.test_dashboard_page_has_new_widget_containers -v 2`
Expected: `PASS`.

- [ ] **Step 5: Прогнать весь класс дашборда и общий смоук-тест**

Run: `.venv/Scripts/python manage.py test apps.users.tests.NewUIDashboardTestCase apps.users.test_newui_smoke -v 2`
Expected: `OK`, все 11 тестов `NewUIDashboardTestCase` + оба теста `NewUISmokeTestCase` проходят.

- [ ] **Step 6: Коммит**

```bash
git add templates/newui/dashboard.html apps/users/tests.py
git commit -m "Дашборд: рендер виджетов кассы/загрузки врачей/заявок"
```

---

## Task 5: Финальная проверка

**Files:** нет изменений — только верификация.

- [ ] **Step 1: Прогнать полный тестовый набор `apps.users`**

Run: `.venv/Scripts/python manage.py test apps.users -v 1`
Expected: `OK`, без ошибок и провалов (регрессия по всем существующим тестам `apps/users/tests.py`, включая не связанные с дашбордом).

- [ ] **Step 2: Прогнать полный тестовый набор проекта**

Run: `.venv/Scripts/python manage.py test -v 1`
Expected: `OK`. Если что-то падает вне `apps.users` и не связано с этими изменениями (например, из-за параллельной сессии, редактирующей `templates/newui/*`) — зафиксировать это отдельно, не чинить в рамках этого плана.

- [ ] **Step 3: Ручная проверка глазами (опционально, если есть запущенный dev-сервер)**

Открыть `/new/` в браузере под пользователем клиники — убедиться, что три новые карточки отображаются внизу страницы, без JS-ошибок в консоли, без наезда на существующую вёрстку.
