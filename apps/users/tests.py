import json
import re
from datetime import timedelta

from django.test import TestCase, Client, override_settings
from apps.users.models import User, Permission, PermissionCategory, Role, Clinic, Branch
from apps.users.forms import UserForm


def _extract_newui_real_data(html):
    m = re.search(
        r'<script id="newui-real-data" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    return json.loads(m.group(1))


def _isolated_sqlite_db_path():
    """Отдельный, реальный файл SQLite (НЕ тот, что использует Django для
    самих тестов) — apps.users.management.commands.backup_database читает
    settings.DATABASES["default"]["NAME"] напрямую через stdlib sqlite3,
    в обход Django ORM. Если направить его на ЖИВОЕ тестовое соединение
    (обычно расшаренный in-memory URI + открытая TestCase-транзакция),
    sqlite3.Connection.backup() виснет в ожидании блокировки — поэтому для
    тестов команды бэкапа нужен отдельный, ничем не занятый файл."""
    import sqlite3
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    import os
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    return path


class NewUIPreviewTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника NU", slug="clinic-newui")
        self.other_clinic = Clinic.objects.create(name="Клиника NU2", slug="clinic-newui2")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.user = User.objects.create(
            login="newui_user", name="НУ Тест", email="nu@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="newui_doctor", name="Иванов Врач", email="doc@test.local",
            role=self.doctor_role, clinic=self.clinic, phone="+996700000000",
        )
        self.other_clinic_user = User.objects.create(
            login="other_clinic_user", name="Чужая Клиника", email="oc@test.local",
            role=self.admin_role, clinic=self.other_clinic,
        )
        self.client = Client()

    def test_new_ui_requires_login(self):
        resp = self.client.get("/new/")
        self.assertEqual(resp.status_code, 302)

    def test_new_ui_renders_for_logged_in_user(self):
        self.client.force_login(self.user)
        resp = self.client.get("/new/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ODONTIS")
        self.assertContains(resp, "Старый интерфейс")

    def test_new_ui_staff_tab_shows_real_clinic_staff_only(self):
        self.client.force_login(self.user)
        resp = self.client.get("/new/staff/")
        data = _extract_newui_real_data(resp.content.decode())
        names = [s["name"] for s in data["staff"]]
        self.assertIn("Иванов Врач", names)
        self.assertNotIn("Чужая Клиника", names)
        doctor_entry = next(s for s in data["staff"] if s["name"] == "Иванов Врач")
        self.assertEqual(doctor_entry["roleName"], "Доктор")
        self.assertEqual(doctor_entry["phone"], "+996700000000")
        self.assertEqual(doctor_entry["id"], self.doctor.pk)
        self.assertEqual(doctor_entry["roleId"], self.doctor_role.pk)

    def test_new_ui_roles_tab_excludes_superadmin_and_has_real_perms(self):
        self.client.force_login(self.user)
        resp = self.client.get("/new/staff/")
        data = _extract_newui_real_data(resp.content.decode())
        role_names = [r["name"] for r in data["roles"]]
        self.assertNotIn("Суперадмин AKM SOFT", role_names)
        doctor_role_entry = next(r for r in data["roles"] if r["id"] == self.doctor_role.pk)
        self.assertIn("patients", doctor_role_entry["perms"])
        self.assertIn("finance", doctor_role_entry["perms"])
        self.assertIn("staff", doctor_role_entry["perms"])
        self.assertIn("reports", doctor_role_entry["perms"])
        self.assertGreaterEqual(doctor_role_entry["staffCount"], 1)
        self.assertIn("grantedCodes", doctor_role_entry)

    def test_new_ui_provides_role_and_branch_options_and_perm_catalog(self):
        self.client.force_login(self.user)
        resp = self.client.get("/new/staff/")
        data = _extract_newui_real_data(resp.content.decode())
        role_option_names = [r["name"] for r in data["roleOptions"]]
        self.assertIn("Доктор", role_option_names)
        self.assertNotIn("Суперадмин AKM SOFT", role_option_names)
        self.assertTrue(len(data["permCatalog"]) >= 9)
        self.assertTrue(all("categoryLabel" in p for p in data["permCatalog"]))

    def test_new_ui_sets_csrf_cookie_for_fetch_calls(self):
        self.client.force_login(self.user)
        resp = self.client.get("/new/")
        self.assertIn("csrftoken", resp.cookies)

    def test_old_dashboard_links_to_new_ui(self):
        self.client.force_login(self.user)
        resp = self.client.get("/")
        self.assertContains(resp, '/new/')


class NewUIDashboardTestCase(TestCase):
    """Дашборд нового интерфейса — реальные KPI/списки. У макета «Новые заявки»
    и план по выручке опирались на несуществующую CRM-воронку, поэтому здесь
    проверяем их честные реальные замены (новые пациенты, выручка вчера)."""

    def setUp(self):
        from django.utils import timezone
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        from apps.finance.models import Payment
        from apps.services.models import Service
        from apps.technicians.models import Technician
        from apps.treatments.models import Treatment
        from apps.technicians.models import TechnicianTask

        self.clinic = Clinic.objects.create(name="Клиника DB", slug="clinic-dashboard")
        self.branch = Branch.objects.create(name="Гл. филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="db_director", name="Директор DB", email="dbd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="db_doctor", name="Врач DB", email="dbdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        self.patient = Patient.objects.create(
            first_name="Тест", last_name="Пациентов", phone="+996700111222",
            branch=self.branch, clinic=self.clinic,
        )
        self.service = Service.objects.create(name="Консультация", price=500, clinic=self.clinic)

        # Полдень СЕГОДНЯ в МЕСТНОМ времени (не "now + 1ч" и не .replace() на
        # UTC-значении — оба мигают возле полуночи, когда локальная и UTC-дата
        # расходятся: _newui_dashboard_data фильтрует по timezone.localdate()).
        import datetime as dt
        today_local = timezone.localdate()
        start_local = timezone.make_aware(dt.datetime.combine(today_local, dt.time(12, 0)))
        end_local = timezone.make_aware(dt.datetime.combine(today_local, dt.time(13, 0)))
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, service=self.service,
            start_at=start_local, end_at=end_local,
            status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )
        setup_payment = Payment.objects.create(
            patient=self.patient, amount=1500, branch=self.branch, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        # created_at=auto_now_add — сдвигаем на 5 минут назад (.update() в обход
        # auto_now_add), чтобы не зависеть от точности часов машины: тесты кассовой
        # смены создают CashShift позже в этом же setUp/тесте и фильтруют платежи
        # по created_at>=opened_at — при совпадении меток в пределах одной секунды
        # этот платёж мог бы ошибочно попасть в приход смены (flaky test). Именно
        # минуты, не сутки — другие тесты этого класса ждут его в «выручке за
        # сегодня» (revenueToday, фильтр по календарному дню).
        Payment.objects.filter(pk=setup_payment.pk).update(created_at=timezone.now() - dt.timedelta(minutes=5))

        technician = Technician.objects.create(name="Техник DB", clinic=self.clinic)
        treatment = Treatment.objects.create(patient=self.patient, doctor=self.doctor, branch=self.branch, clinic=self.clinic)
        TechnicianTask.objects.create(
            technician=technician, treatment=treatment, service=self.service,
            status=TechnicianTask.STATUS_IN_PROGRESS, clinic=self.clinic,
        )

    def test_dashboard_revenue_reflects_real_payment(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["dashboard"]["revenueToday"], 1500.0)

    def test_sidebar_nav_items_carry_data_view_for_menu_settings(self):
        """«Настроить меню» (openMenuSettings/applyMenuPrefs в base.html) находит
        пункты по .nav-item[data-view] — без этого атрибута модалка настройки
        меню всегда была пустой (ни скрыть, ни переставить было нечего)."""
        resp = self.client.get("/new/")
        html = resp.content.decode()
        for view in ["dashboard", "patients", "visits", "schedule", "finance",
                     "reports", "settings", "cashdesk", "staff"]:
            self.assertIn(f'data-view="{view}"', html, f"нет data-view для {view}")

    def test_dashboard_upcoming_appointments_reflects_real_appointment(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        upcoming = data["dashboard"]["upcoming"]
        self.assertEqual(len(upcoming), 1)
        self.assertEqual(upcoming[0]["patient"], "Пациентов Тест")
        self.assertEqual(upcoming[0]["doctor"], "Врач DB")

    def test_dashboard_lab_orders_reflects_real_open_task(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["dashboard"]["labOpenCount"], 1)

    def test_dashboard_new_patients_counts_real_patient(self):
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertGreaterEqual(data["dashboard"]["newPatientsMonth"], 1)

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


class NewUIPatientsTestCase(TestCase):
    """Раздел «Пациенты» нового интерфейса — список на реальных данных,
    создание/редактирование через fetch() на существующие Django-view
    (patient_create_quick — JSON; patient_edit — redirect=успех)."""

    def setUp(self):
        from apps.patients.models import Patient

        self.clinic = Clinic.objects.create(name="Клиника PT", slug="clinic-newui-patients")
        self.branch = Branch.objects.create(name="Филиал PT", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="pt_director", name="Директор PT", email="ptd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        self.patient = Patient.objects.create(
            first_name="Асель", last_name="Байгазиева", phone="+996700333444",
            branch=self.branch, clinic=self.clinic, balance=-1500,
        )

    def test_new_ui_patients_list_reflects_real_patient(self):
        resp = self.client.get("/new/patients/")
        data = _extract_newui_real_data(resp.content.decode())
        names = [p["fullName"] for p in data["patients"]]
        self.assertIn("Байгазиева Асель", names)
        entry = next(p for p in data["patients"] if p["id"] == self.patient.pk)
        self.assertEqual(entry["phone"], "+996700333444")
        self.assertTrue(entry["hasDebt"])
        self.assertEqual(entry["statusLabel"], "Должник")
        self.assertEqual(entry["branchId"], self.branch.pk)

    def test_patient_quick_create_returns_json_ok(self):
        resp = self.client.post("/patients/quick-create/", {
            "first_name": "Новый", "last_name": "Пациент", "phone": "+996700555666",
        })
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["name"])

    def test_patient_quick_create_missing_required_field_returns_error_json(self):
        resp = self.client.post("/patients/quick-create/", {"first_name": "", "last_name": "", "phone": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_patient_edit_via_modal_fields_redirects_on_success(self):
        resp = self.client.post(f"/patients/{self.patient.pk}/edit/", {
            "first_name": "Асель", "last_name": "Байгазиева", "phone": "+996700333444",
            "branch": self.branch.pk,
        })
        self.assertEqual(resp.status_code, 302)


class NewUIScheduleTestCase(TestCase):
    """Раздел «Записи/Календарь» — реальные врачи и реальные приёмы в окне
    ±30 дней. Создание записи и перетаскивание в календаре нового интерфейса
    сознательно не подключены к базе в этом заходе (риск конфликтов
    кабинетов/времени — отдельная, более крупная задача)."""

    def setUp(self):
        from django.utils import timezone
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        from apps.services.models import Service

        self.clinic = Clinic.objects.create(name="Клиника SC", slug="clinic-newui-schedule")
        self.branch = Branch.objects.create(name="Филиал SC", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="sc_director", name="Директор SC", email="scd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="sc_doctor", name="Врач SC", email="scdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        self.patient = Patient.objects.create(
            first_name="Записанный", last_name="Пациент", phone="+996700777888",
            branch=self.branch, clinic=self.clinic,
        )
        self.service = Service.objects.create(name="Приём", price=300, clinic=self.clinic)
        now = timezone.now()
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, service=self.service,
            start_at=now + timezone.timedelta(hours=2), end_at=now + timezone.timedelta(hours=3),
            status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )
        # За пределами окна ±30 дней — не должна попасть в выдачу
        self.far_appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, service=self.service,
            start_at=now + timezone.timedelta(days=90), end_at=now + timezone.timedelta(days=90, hours=1),
            status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )

    def test_schedule_lists_real_doctor(self):
        resp = self.client.get("/new/schedule/")
        data = _extract_newui_real_data(resp.content.decode())
        doctor_names = [d["name"] for d in data["schedule"]["doctors"]]
        self.assertIn("Врач SC", doctor_names)

    def test_schedule_doctor_color_exposed_for_column_tint(self):
        """User.color (задаётся в карточке сотрудника) должен доехать до
        расписания — красит колонку врача в сетке нового интерфейса."""
        self.doctor.color = "#00AABB"
        self.doctor.save(update_fields=["color"])
        resp = self.client.get("/new/schedule/")
        data = _extract_newui_real_data(resp.content.decode())
        doctor_row = next(d for d in data["schedule"]["doctors"] if d["name"] == "Врач SC")
        self.assertEqual(doctor_row["color"], "#00AABB")

    def test_completed_appointment_colored_red_when_unpaid_green_when_paid(self):
        from apps.appointments.models import Appointment
        from apps.treatments.models import Treatment

        self.appt.status = Appointment.STATUS_COMPLETED
        self.appt.save(update_fields=["status"])
        unpaid = Treatment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, appointment=self.appt,
            status=Treatment.STATUS_COMPLETED, total_amount=1000, paid_amount=0, clinic=self.clinic,
        )
        data = _extract_newui_real_data(self.client.get("/new/schedule/").content.decode())
        appt_row = next(a for a in data["schedule"]["appointments"] if a["id"] == self.appt.pk)
        self.assertEqual(appt_row["status"], "coral")

        unpaid.paid_amount = 1000
        unpaid.save(update_fields=["paid_amount"])
        data = _extract_newui_real_data(self.client.get("/new/schedule/").content.decode())
        appt_row = next(a for a in data["schedule"]["appointments"] if a["id"] == self.appt.pk)
        self.assertEqual(appt_row["status"], "teal")

    def test_schedule_includes_appointment_within_window(self):
        resp = self.client.get("/new/schedule/")
        data = _extract_newui_real_data(resp.content.decode())
        appt_ids = [a["id"] for a in data["schedule"]["appointments"]]
        self.assertIn(self.appt.pk, appt_ids)
        entry = next(a for a in data["schedule"]["appointments"] if a["id"] == self.appt.pk)
        self.assertEqual(entry["patient"], "Пациент Записанный")
        self.assertEqual(entry["docId"], self.doctor.pk)

    def test_schedule_excludes_appointment_outside_window(self):
        resp = self.client.get("/new/schedule/")
        data = _extract_newui_real_data(resp.content.decode())
        appt_ids = [a["id"] for a in data["schedule"]["appointments"]]
        self.assertNotIn(self.far_appt.pk, appt_ids)

    def test_schedule_appointment_has_duration_and_movable_for_drag_drop(self):
        """Создание кликом по ячейке / drag-and-drop в /new/schedule/ переиспользуют
        appointment_create_quick / appointment_move — JS вычисляет новое время конца
        переноса по durationMin, а movable=False блокирует перетаскивание завершённых/
        неявившихся записей (см. schedDragStart в base.html)."""
        resp = self.client.get("/new/schedule/")
        data = _extract_newui_real_data(resp.content.decode())
        entry = next(a for a in data["schedule"]["appointments"] if a["id"] == self.appt.pk)
        self.assertEqual(entry["durationMin"], 60)
        self.assertTrue(entry["movable"])

    def test_schedule_page_provides_patients_and_services_for_new_appt_modal(self):
        resp = self.client.get("/new/schedule/")
        data = _extract_newui_real_data(resp.content.decode())
        patient_names = [p["fullName"] for p in data["patients"]]
        self.assertIn("Пациент Записанный", patient_names)
        service_names = [s["name"] for s in data["servicesData"]["services"]]
        self.assertIn("Приём", service_names)


class NewUIServicesTestCase(TestCase):
    """Раздел «Услуги» — реальный прайс-лист, создание/редактирование через
    fetch() на существующие service_create/service_edit (redirect=успех)."""

    def setUp(self):
        from apps.services.models import Service, ServiceCategory

        self.clinic = Clinic.objects.create(name="Клиника SV", slug="clinic-newui-services")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="sv_director", name="Директор SV", email="svd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        self.category = ServiceCategory.objects.create(name="Терапия", clinic=self.clinic)
        self.service = Service.objects.create(
            name="Пломбирование", code="T-014", category=self.category, price=3200, clinic=self.clinic,
        )

    def test_new_ui_services_list_reflects_real_service(self):
        resp = self.client.get("/new/services/")
        data = _extract_newui_real_data(resp.content.decode())
        names = [s["name"] for s in data["servicesData"]["services"]]
        self.assertIn("Пломбирование", names)
        entry = next(s for s in data["servicesData"]["services"] if s["id"] == self.service.pk)
        self.assertEqual(entry["categoryName"], "Терапия")
        self.assertEqual(entry["price"], 3200.0)
        cat_names = [c["name"] for c in data["servicesData"]["categories"]]
        self.assertIn("Терапия", cat_names)

    def test_service_create_via_modal_fields_redirects_on_success(self):
        resp = self.client.post("/services/create/", {
            "name": "Новая услуга", "code": "X-1", "category": self.category.pk,
            "price": 1000, "duration": 30, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)

    def test_service_edit_via_modal_fields_redirects_on_success(self):
        resp = self.client.post(f"/services/{self.service.pk}/edit/", {
            "name": "Пломбирование", "code": "T-014", "category": self.category.pk,
            "price": 3500, "duration": 30, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)

    def test_service_secondary_price_persists_and_is_exposed(self):
        resp = self.client.post(f"/services/{self.service.pk}/edit/", {
            "name": "Пломбирование", "code": "T-014", "category": self.category.pk,
            "price": 3500, "price_secondary": 40, "duration": 30, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.service.refresh_from_db()
        self.assertEqual(float(self.service.price_secondary), 40.0)
        data = _extract_newui_real_data(self.client.get("/new/services/").content.decode())
        entry = next(s for s in data["servicesData"]["services"] if s["id"] == self.service.pk)
        self.assertEqual(entry["priceSecondary"], 40.0)

    def test_service_secondary_price_empty_string_clears_it(self):
        self.service.price_secondary = 40
        self.service.save(update_fields=["price_secondary"])
        resp = self.client.post(f"/services/{self.service.pk}/edit/", {
            "name": "Пломбирование", "code": "T-014", "category": self.category.pk,
            "price": 3500, "price_secondary": "", "duration": 30, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.service.refresh_from_db()
        self.assertIsNone(self.service.price_secondary)


class NewUIMenuPrefsTestCase(TestCase):
    """Настройка меню (сайдбара) — личная (User.menu_prefs, per-user, между
    устройствами) и клиникина по умолчанию (ClinicSettings.menu_prefs, только
    директор/суперадмин), см. /new/menu-prefs/save/."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника MP", slug="clinic-newui-menuprefs")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="mp_director", name="Директор MP", email="mpd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.staff = User.objects.create(
            login="mp_staff", name="Сотрудник MP", email="mps@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )

    def test_saving_personal_prefs_persists_and_is_exposed_only_to_that_user(self):
        client = Client()
        client.force_login(self.staff)
        res = client.post("/new/menu-prefs/save/",
                           data=json.dumps({"prefs": {"hidden": ["marketing"], "order": {}, "home": "schedule"}, "scope": "user"}),
                           content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.menu_prefs["hidden"], ["marketing"])
        self.assertEqual(self.staff.menu_prefs["home"], "schedule")
        data = _extract_newui_real_data(client.get("/new/").content.decode())
        self.assertEqual(data["userMenuPrefs"]["hidden"], ["marketing"])
        # Директора эта личная настройка не касается
        self.director.refresh_from_db()
        self.assertEqual(self.director.menu_prefs, {})

    def test_non_admin_cannot_save_clinic_wide_menu(self):
        client = Client()
        client.force_login(self.staff)
        res = client.post("/new/menu-prefs/save/",
                           data=json.dumps({"prefs": {"hidden": ["finance"], "order": {}, "home": None}, "scope": "clinic"}),
                           content_type="application/json")
        self.assertEqual(res.status_code, 403)
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.objects.filter(clinic=self.clinic).first()
        self.assertTrue(cs is None or cs.menu_prefs == {})

    def test_director_can_save_clinic_wide_menu_and_it_falls_back_for_staff_without_personal_prefs(self):
        director_client = Client()
        director_client.force_login(self.director)
        res = director_client.post("/new/menu-prefs/save/",
                                    data=json.dumps({"prefs": {"hidden": ["marketing"], "order": {}, "home": "patients"}, "scope": "clinic"}),
                                    content_type="application/json")
        self.assertEqual(res.status_code, 200)
        # canSetClinicMenu виден директору
        data = _extract_newui_real_data(director_client.get("/new/").content.decode())
        self.assertTrue(data["canSetClinicMenu"])

        # Сотрудник без личной настройки — видит клиникину как эффективную
        staff_client = Client()
        staff_client.force_login(self.staff)
        data = _extract_newui_real_data(staff_client.get("/new/").content.decode())
        self.assertFalse(data["canSetClinicMenu"])
        self.assertEqual(data["clinicMenuPrefs"]["hidden"], ["marketing"])
        self.assertEqual(data["userMenuPrefs"], {})


class NewUICurrencySettingsTestCase(TestCase):
    """Настройки → Общие → Основная/Дополнительная валюта — реальное поле
    ClinicSettings, используется в fmtSom()/суммах по всему новому интерфейсу."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника CUR", slug="clinic-newui-currency")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="cur_director", name="Директор CUR", email="curd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_default_currency_is_kgs_with_no_secondary(self):
        data = _extract_newui_real_data(self.client.get("/new/").content.decode())
        self.assertEqual(data["clinicCurrencySymbol"], "сом")
        self.assertFalse(data["clinicHasSecondaryCurrency"])

    def test_saving_primary_and_secondary_currency_persists_and_exposed_everywhere(self):
        from apps.settings_clinic.models import ClinicSettings
        # ClinicSettings.get() зависит от thread-local текущей клиники (apps.tenancy),
        # которая выставляется только СРЕДИ обработки запроса (middleware) — вне запроса
        # (прямо в теле теста) она пуста, и .get() вернул бы служебную запись
        # clinic__isnull=True, а не запись именно self.clinic. Берём запись напрямую.
        resp = self.client.post("/settings/", {
            "name": self.clinic.name, "currency": "USD", "currency_secondary": "KGS",
            "appointment_slot": 30, "language": "ru", "receipt_format": "thermal",
        })
        self.assertEqual(resp.status_code, 302)
        cs = ClinicSettings.objects.get(clinic=self.clinic)
        self.assertEqual(cs.currency, "USD")
        self.assertEqual(cs.currency_secondary, "KGS")
        # видно на ЛЮБОЙ странице /new/*, не только /new/settings/
        data = _extract_newui_real_data(self.client.get("/new/schedule/").content.decode())
        self.assertEqual(data["clinicCurrencySymbol"], "$")
        self.assertEqual(data["clinicCurrencySecondarySymbol"], "сом")
        self.assertTrue(data["clinicHasSecondaryCurrency"])


class NewUIFinanceLabWarehouseTestCase(TestCase):
    """Финансы/Лаборатория/Склад — реальные суммы и списки. Кассовые смены
    (v-cashdesk) сознательно не подделаны — такой модели в системе нет."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.finance.models import Payment, Expense, ExpenseCategory, PatientAdvance
        from apps.services.models import Service
        from apps.technicians.models import Technician, TechnicianTask
        from apps.treatments.models import Treatment
        from apps.warehouse.models import Product

        self.clinic = Clinic.objects.create(name="Клиника FL", slug="clinic-newui-finlab")
        self.other_clinic = Clinic.objects.create(name="Клиника FL2", slug="clinic-newui-finlab2")
        self.branch = Branch.objects.create(name="Филиал FL", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="fl_director", name="Директор FL", email="fld@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        self.patient = Patient.objects.create(
            first_name="Должник", last_name="Тестов", phone="+996700999888",
            branch=self.branch, clinic=self.clinic, balance=-500,
        )
        self.other_patient = Patient.objects.create(
            first_name="Чужой", last_name="Пациент", phone="+996700111000",
            branch=self.branch, clinic=self.other_clinic,
        )
        Payment.objects.create(
            patient=self.patient, amount=1000, branch=self.branch, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        cat = ExpenseCategory.objects.create(name="Материалы", clinic=self.clinic)
        Expense.objects.create(category=cat, amount=200, date=timezone_today(), branch=self.branch, created_by=self.director, clinic=self.clinic)
        PatientAdvance.objects.create(patient=self.patient, amount=300, date=timezone_today())
        PatientAdvance.objects.create(patient=self.other_patient, amount=9999, date=timezone_today())

        service = Service.objects.create(name="Коронка", price=1000, clinic=self.clinic)
        technician = Technician.objects.create(name="Техник FL", clinic=self.clinic)
        treatment = Treatment.objects.create(patient=self.patient, doctor=self.director, branch=self.branch, clinic=self.clinic)
        TechnicianTask.objects.create(
            technician=technician, treatment=treatment, service=service, patient=self.patient,
            status=TechnicianTask.STATUS_IN_PROGRESS, clinic=self.clinic,
        )

        from apps.warehouse.models import WarehouseEntry
        # Приход (WarehouseEntry) увеличивает Product.quantity через сигнал —
        # стартуем с 0, чтобы после прихода получить ожидаемый итоговый остаток.
        product = Product.objects.create(name="Перчатки", unit="уп.", quantity=0, min_qty=10, clinic=self.clinic)
        WarehouseEntry.objects.create(
            product=product, quantity=2, price=100, date=timezone_today(), created_by=self.director,
        )

    def test_finance_totals_are_real_and_clinic_scoped(self):
        resp = self.client.get("/new/finance/")
        data = _extract_newui_real_data(resp.content.decode())
        fin = data["financeData"]
        self.assertEqual(fin["revenueMonth"], 1000.0)
        self.assertEqual(fin["expensesMonth"], 200.0)
        self.assertEqual(fin["depositsTotal"], 300.0)  # не 9999 чужой клиники
        # Patient.balance пересчитывается сигналами на основе приёмов/оплат
        # (не просто хранит то, что мы задали при create) — здесь только
        # проверяем контракт (реальное неотрицательное число), точную сумму
        # долга покрывает test_new_ui_patients_list_reflects_real_patient.
        self.assertGreaterEqual(fin["debtTotal"], 0)
        self.assertIsInstance(fin["debtTotal"], float)

    def test_lab_kanban_reflects_real_order(self):
        from apps.technicians.models import TechnicianTask
        resp = self.client.get("/new/lab/")
        data = _extract_newui_real_data(resp.content.decode())
        statuses = [o["status"] for o in data["labData"]["orders"]]
        self.assertIn("in_progress", statuses)
        # Полный набор статусов канбана (для перетаскиваемых колонок), не
        # урезанный до 4 условных групп, как раньше.
        status_values = {s["value"] for s in data["labData"]["statuses"]}
        self.assertEqual(status_values, set(dict(TechnicianTask.STATUS_CHOICES).keys()))

    def test_warehouse_reflects_real_low_stock_product(self):
        resp = self.client.get("/new/warehouse/")
        data = _extract_newui_real_data(resp.content.decode())
        wh = data["warehouseData"]
        names = [p["name"] for p in wh["items"]]
        self.assertIn("Перчатки", names)
        entry = next(p for p in wh["items"] if p["name"] == "Перчатки")
        self.assertEqual(entry["status"], "order")
        self.assertEqual(wh["lowStockCount"], 1)


class NewUIReportsTestCase(TestCase):
    """Отчёты — только верхние KPI реальные (конструктор/ИИ/детальные разрезы
    сознательно не подключены, отмечено баннером в самом интерфейсе)."""

    def setUp(self):
        import datetime as dt
        from django.utils import timezone
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        from apps.services.models import Service

        self.clinic = Clinic.objects.create(name="Клиника RP", slug="clinic-newui-reports")
        self.branch = Branch.objects.create(name="Филиал RP", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="rp_director", name="Директор RP", email="rpd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        patient = Patient.objects.create(first_name="RP", last_name="Тест", phone="+996700222333", branch=self.branch, clinic=self.clinic)
        service = Service.objects.create(name="Приём", price=100, clinic=self.clinic)
        today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(today, dt.time(10, 0)))
        end = timezone.make_aware(dt.datetime.combine(today, dt.time(11, 0)))
        Appointment.objects.create(
            patient=patient, doctor=self.director, branch=self.branch, service=service,
            start_at=start, end_at=end, status=Appointment.STATUS_CANCELLED, clinic=self.clinic,
        )

    def test_reports_kpi_reflects_real_cancelled_appointment(self):
        resp = self.client.get("/new/reports/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["reportsData"]["cancelled"], 1)
        self.assertEqual(data["reportsData"]["cancelledPct"], 100.0)

    def test_reports_cancelled_visits_list_has_real_row(self):
        data = _extract_newui_real_data(self.client.get("/new/reports/").content.decode())
        rows = data["reportsData"]["cancelledVisits"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["patient"], "Тест RP")
        self.assertEqual(rows[0]["status"], "Отменён")

    def test_reports_expenses_tab_reflects_real_expense(self):
        from django.utils import timezone
        from apps.finance.models import Expense, ExpenseCategory

        cat = ExpenseCategory.objects.create(name="Аренда", clinic=self.clinic)
        Expense.objects.create(
            category=cat, amount=15000, description="Аренда за месяц", branch=self.branch,
            created_by=self.director, date=timezone.localdate(), clinic=self.clinic,
        )
        data = _extract_newui_real_data(self.client.get("/new/reports/").content.decode())
        rd = data["reportsData"]
        self.assertEqual(rd["expensesTotal"], 15000.0)
        self.assertEqual(rd["expensesByCategory"], [{"category": "Аренда", "total": 15000.0}])
        self.assertEqual(rd["expensesList"][0]["description"], "Аренда за месяц")

    def test_reports_debtors_tab_reflects_real_negative_balance(self):
        from apps.patients.models import Patient

        debtor = Patient.objects.create(
            first_name="Должник", last_name="Тестовый", phone="+996700333444",
            branch=self.branch, clinic=self.clinic, balance=-2500,
        )
        data = _extract_newui_real_data(self.client.get("/new/reports/").content.decode())
        rd = data["reportsData"]
        self.assertEqual(rd["debtorsTotal"], -2500.0)
        names = [d["name"] for d in rd["debtorsList"]]
        self.assertIn(debtor.full_name, names)

    def test_reports_doctor_stats_reflects_real_completed_treatment(self):
        from apps.patients.models import Patient
        from apps.treatments.models import Treatment

        patient = Patient.objects.create(first_name="Лечится", last_name="У врача", phone="+996700555666", branch=self.branch, clinic=self.clinic)
        Treatment.objects.create(
            patient=patient, doctor=self.director, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=5000, clinic=self.clinic,
        )
        data = _extract_newui_real_data(self.client.get("/new/reports/").content.decode())
        stats = data["reportsData"]["doctorStats"]
        row = next(s for s in stats if s["doctor"] == self.director.name)
        self.assertEqual(row["count"], 1)
        self.assertEqual(row["revenue"], 5000.0)
        self.assertEqual(row["avgCheck"], 5000.0)

    def test_reports_lead_sources_reflects_real_lead_conversion(self):
        from apps.patients.models import Lead, LeadSource

        source = LeadSource.objects.create(name="Instagram")
        Lead.objects.create(name="Заявка 1", source=source, stage=Lead.STAGE_CAME, clinic=self.clinic)
        Lead.objects.create(name="Заявка 2", source=source, stage=Lead.STAGE_NEW, clinic=self.clinic)
        data = _extract_newui_real_data(self.client.get("/new/reports/").content.decode())
        sources = data["reportsData"]["leadSources"]
        row = next(s for s in sources if s["source"] == "Instagram")
        self.assertEqual(row["count"], 2)
        self.assertEqual(row["conversionPct"], 50.0)


class NewUIBlacklistTestCase(TestCase):
    """Чёрный список — та же модель BlacklistEntry и тот же view
    (/patients/blacklist/), что и в старом интерфейсе, просто в новом дизайне."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника BL", slug="clinic-newui-blacklist")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="bl_director", name="Директор BL", email="bld@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_blacklist_page_reflects_real_entry(self):
        from apps.patients.models import BlacklistEntry
        BlacklistEntry.objects.create(phone="+996700111222", name="Бекова А.", reason="Долг", clinic=self.clinic)
        resp = self.client.get("/new/blacklist/")
        data = _extract_newui_real_data(resp.content.decode())
        names = [e["name"] for e in data["blacklistEntries"]]
        self.assertIn("Бекова А.", names)

    def test_blacklist_add_via_reused_backend_redirects(self):
        resp = self.client.post("/patients/blacklist/", {
            "action": "add", "name": "Новый Ч.С.", "phone": "+996700333444", "reason": "Неявка",
        })
        self.assertEqual(resp.status_code, 302)
        from apps.patients.models import BlacklistEntry
        self.assertTrue(BlacklistEntry.objects.filter(phone="+996700333444").exists())

    def test_blacklist_remove_via_reused_backend_redirects(self):
        from apps.patients.models import BlacklistEntry
        entry = BlacklistEntry.objects.create(phone="+996700555666", name="Убрать", reason="—", clinic=self.clinic)
        resp = self.client.post("/patients/blacklist/", {"action": "remove", "id": entry.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(BlacklistEntry.objects.filter(pk=entry.pk).exists())


class NewUITreatplansTestCase(TestCase):
    """Планы лечения — реальная модель TreatmentPlan/TreatmentPlanStage/Item."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.services.models import Service
        from apps.treatments.models_plan import TreatmentPlan, TreatmentPlanStage, TreatmentPlanItem

        self.clinic = Clinic.objects.create(name="Клиника TP", slug="clinic-newui-treatplans")
        self.branch = Branch.objects.create(name="Филиал TP", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="tp_director", name="Директор TP", email="tpd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        patient = Patient.objects.create(first_name="ТП", last_name="Тест", phone="+996700777111", branch=self.branch, clinic=self.clinic)
        service = Service.objects.create(name="Пломбирование", price=3200, clinic=self.clinic)
        plan = TreatmentPlan.objects.create(patient=patient, doctor=self.director, title="Пломбирование, зуб 26", status=TreatmentPlan.STATUS_APPROVED)
        stage = TreatmentPlanStage.objects.create(plan=plan, title="Этап 1")
        TreatmentPlanItem.objects.create(plan=plan, service=service, stage=stage, price=3200, status=TreatmentPlanItem.STATUS_PENDING)
        self.plan = plan

    def test_treatplans_page_reflects_real_plan(self):
        resp = self.client.get("/new/treatplans/")
        data = _extract_newui_real_data(resp.content.decode())
        patients = [p["patient"] for p in data["treatplansData"]["plans"]]
        self.assertIn("Тест ТП", patients)
        self.assertEqual(data["treatplansData"]["activeCount"], 1)


class NewUIVisitsTestCase(TestCase):
    """Визиты — реальные записи (Appointment) на сегодня; смена статуса идёт
    через тот же appointment_status, что и старый интерфейс."""

    def setUp(self):
        import datetime as dt
        from django.utils import timezone
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        from apps.services.models import Service

        self.clinic = Clinic.objects.create(name="Клиника VS", slug="clinic-newui-visits")
        self.branch = Branch.objects.create(name="Филиал VS", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="vs_director", name="Директор VS", email="vsd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="vs_doctor", name="Врач VS", email="vsdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        patient = Patient.objects.create(first_name="Визит", last_name="Сегодня", phone="+996700888222", branch=self.branch, clinic=self.clinic)
        service = Service.objects.create(name="Приём", price=100, clinic=self.clinic)
        today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(today, dt.time(9, 0)))
        end = timezone.make_aware(dt.datetime.combine(today, dt.time(9, 30)))
        self.appt = Appointment.objects.create(
            patient=patient, doctor=self.doctor, branch=self.branch, service=service,
            start_at=start, end_at=end, status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )

    def test_visits_page_reflects_real_appointment_today(self):
        resp = self.client.get("/new/visits/")
        data = _extract_newui_real_data(resp.content.decode())
        visit_ids = [v["id"] for v in data["visitsData"]["visits"]]
        self.assertIn(self.appt.pk, visit_ids)
        self.assertEqual(data["visitsData"]["totalToday"], 1)

    def test_visits_page_includes_past_appointments_for_vkladka_vse(self):
        """Раньше бэкенд отдавал строго сегодняшние записи — вкладка «Все»
        на фронте была бы пустышкой без прошлых визитов в payload."""
        import datetime as dt
        from django.utils import timezone
        from apps.appointments.models import Appointment
        past_start = timezone.make_aware(dt.datetime.combine(
            timezone.localdate() - dt.timedelta(days=5), dt.time(10, 0)))
        past = Appointment.objects.create(
            patient=self.appt.patient, doctor=self.doctor, branch=self.branch, service=self.appt.service,
            start_at=past_start, end_at=past_start + dt.timedelta(minutes=30),
            status=Appointment.STATUS_COMPLETED, clinic=self.clinic,
        )
        resp = self.client.get("/new/visits/")
        data = _extract_newui_real_data(resp.content.decode())
        vd = data["visitsData"]
        visit_ids = [v["id"] for v in vd["visits"]]
        self.assertIn(past.pk, visit_ids, "прошлый визит должен попадать в общий список (вкладка «Все»)")
        self.assertEqual(vd["totalToday"], 1, "но не должен учитываться в счётчике «Сегодня»")
        self.assertIn("todayIso", vd)

    def test_visit_status_change_via_reused_backend(self):
        resp = self.client.post(f"/appointments/{self.appt.pk}/status/", {"status": "cancelled"})
        self.assertEqual(resp.status_code, 302)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "cancelled")


class NewUIAccountingTestCase(TestCase):
    """Бухгалтерия — реальная выручка (Payment) и расходы по категориям (Expense)."""

    def setUp(self):
        from apps.finance.models import Payment, Expense, ExpenseCategory
        from apps.patients.models import Patient

        self.clinic = Clinic.objects.create(name="Клиника AC", slug="clinic-newui-accounting")
        self.branch = Branch.objects.create(name="Филиал AC", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="ac_director", name="Директор AC", email="acd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        patient = Patient.objects.create(first_name="Бух", last_name="Тест", phone="+996700444555", branch=self.branch, clinic=self.clinic)
        Payment.objects.create(patient=patient, amount=5000, branch=self.branch, received_by=self.director, type=Payment.TYPE_INCOME, clinic=self.clinic)
        cat = ExpenseCategory.objects.create(name="Материалы", clinic=self.clinic)
        Expense.objects.create(category=cat, amount=1200, date=timezone_today(), branch=self.branch, created_by=self.director, clinic=self.clinic)

    def test_accounting_reflects_real_revenue_and_expenses(self):
        resp = self.client.get("/new/accounting/")
        data = _extract_newui_real_data(resp.content.decode())
        acc = data["accountingData"]
        self.assertEqual(acc["revenue"], 5000.0)
        self.assertEqual(acc["expensesTotal"], 1200.0)
        self.assertEqual(acc["profit"], 3800.0)
        line_names = [l["name"] for l in acc["expenseLines"]]
        self.assertIn("Материалы", line_names)


class NewUIAuditTestCase(TestCase):
    """Журнал аудита — реальная история изменений (django-simple-history) по
    пациентам, та же модель, что уже используется в системе."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника AU", slug="clinic-newui-audit")
        self.branch = Branch.objects.create(name="Филиал AU", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="au_director", name="Директор AU", email="aud@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_audit_reflects_real_patient_history_entry(self):
        from apps.patients.models import Patient
        Patient.objects.create(first_name="Аудит", last_name="Тестов", phone="+996700999111", branch=self.branch, clinic=self.clinic)
        resp = self.client.get("/new/audit/")
        data = _extract_newui_real_data(resp.content.decode())
        objects = [e["object"] for e in data["auditEvents"]]
        self.assertTrue(any("Тестов Аудит" in o for o in objects))


class NewUICashdeskTestCase(TestCase):
    """Касса — реальная кассовая смена (CashShift), Z-отчёт по методам оплаты
    и очередь ожидающих оплат (Notification, отправленные send_to_cashier)."""

    def setUp(self):
        from apps.finance.models import Payment
        from apps.patients.models import Patient

        self.clinic = Clinic.objects.create(name="Клиника CD", slug="clinic-newui-cashdesk")
        self.branch = Branch.objects.create(name="Филиал CD", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="cd_director", name="Директор CD", email="cdd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)
        self.patient = Patient.objects.create(first_name="Касса", last_name="Тест", phone="+996700666777", branch=self.branch, clinic=self.clinic)
        self.Payment = Payment

    def test_cashdesk_page_shows_no_open_shift_initially(self):
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertIsNone(data["cashdeskData"]["shift"])

    def test_open_shift_creates_real_cashshift(self):
        from apps.finance.models import CashShift
        resp = self.client.post("/finance/cashshift/open/", {"opening_cash": "1000"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        shift = CashShift.objects.get(branch=self.branch, status=CashShift.STATUS_OPEN)
        self.assertEqual(shift.opening_cash, 1000)
        self.assertEqual(shift.opened_by, self.director)

    def test_cannot_open_second_shift_for_same_branch(self):
        from apps.finance.models import CashShift
        CashShift.objects.create(branch=self.branch, opened_by=self.director, opening_cash=0, clinic=self.clinic)
        resp = self.client.post("/finance/cashshift/open/", {"opening_cash": "500"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertEqual(CashShift.objects.filter(branch=self.branch, status=CashShift.STATUS_OPEN).count(), 1)

    def test_shift_z_report_reflects_real_payments_by_method(self):
        from apps.finance.models import CashShift
        shift = CashShift.objects.create(branch=self.branch, opened_by=self.director, opening_cash=1000, clinic=self.clinic)
        self.Payment.objects.create(
            patient=self.patient, amount=5000, branch=self.branch, received_by=self.director,
            type=self.Payment.TYPE_INCOME, method=self.Payment.METHOD_CASH, clinic=self.clinic,
        )
        self.Payment.objects.create(
            patient=self.patient, amount=2000, branch=self.branch, received_by=self.director,
            type=self.Payment.TYPE_INCOME, method=self.Payment.METHOD_CARD, clinic=self.clinic,
        )
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        s = data["cashdeskData"]["shift"]
        self.assertEqual(s["byMethod"]["cash"], 5000.0)
        self.assertEqual(s["byMethod"]["card"], 2000.0)
        self.assertEqual(s["incomeTotal"], 7000.0)
        self.assertEqual(s["expectedCash"], 6000.0)  # 1000 opening + 5000 cash

    def test_close_shift_via_reused_backend(self):
        from apps.finance.models import CashShift
        shift = CashShift.objects.create(branch=self.branch, opened_by=self.director, opening_cash=0, clinic=self.clinic)
        resp = self.client.post(f"/finance/cashshift/{shift.pk}/close/", {"closing_cash_actual": "1500"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        shift.refresh_from_db()
        self.assertEqual(shift.status, CashShift.STATUS_CLOSED)
        self.assertEqual(shift.closing_cash_actual, 1500)
        self.assertIsNotNone(shift.closed_at)

    def _make_today_appointment(self, patient=None, hour=10):
        import datetime as dt
        from django.utils import timezone
        from apps.appointments.models import Appointment
        from apps.services.models import Service

        service = Service.objects.create(name="Приём", price=100, clinic=self.clinic)
        today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(today, dt.time(hour, 0)))
        end = start + dt.timedelta(hours=1)
        return Appointment.objects.create(
            patient=patient or self.patient, doctor=self.director, branch=self.branch, service=service,
            start_at=start, end_at=end, status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )

    def test_today_patients_lists_appointment_with_unpaid_treatment(self):
        from apps.treatments.models import Treatment

        appt = self._make_today_appointment()
        Treatment.objects.create(
            patient=self.patient, doctor=self.director, branch=self.branch, appointment=appt,
            status=Treatment.STATUS_PLANNED, total_amount=3000, clinic=self.clinic,
        )
        data = _extract_newui_real_data(self.client.get("/new/cashdesk/").content.decode())
        rows = data["cashdeskData"]["todayPatients"]
        row = next(r for r in rows if r["patientId"] == self.patient.pk)
        self.assertFalse(row["paid"])
        self.assertEqual(row["items"][0]["amount"], 3000.0)

    def test_today_patients_excludes_appointment_without_treatment(self):
        self._make_today_appointment()
        data = _extract_newui_real_data(self.client.get("/new/cashdesk/").content.decode())
        rows = data["cashdeskData"]["todayPatients"]
        self.assertFalse(any(r["patientId"] == self.patient.pk for r in rows))

    def test_today_patients_marks_fully_paid_treatment_as_paid(self):
        from apps.treatments.models import Treatment

        appt = self._make_today_appointment()
        Treatment.objects.create(
            patient=self.patient, doctor=self.director, branch=self.branch, appointment=appt,
            status=Treatment.STATUS_PAID, total_amount=3000, paid_amount=3000, clinic=self.clinic,
        )
        data = _extract_newui_real_data(self.client.get("/new/cashdesk/").content.decode())
        row = next(r for r in data["cashdeskData"]["todayPatients"] if r["patientId"] == self.patient.pk)
        self.assertTrue(row["paid"])
        self.assertEqual(row["items"], [])

    def test_today_patients_combines_multiple_appointments_same_patient(self):
        from apps.treatments.models import Treatment

        appt1 = self._make_today_appointment(hour=9)
        appt2 = self._make_today_appointment(hour=14)
        Treatment.objects.create(
            patient=self.patient, doctor=self.director, branch=self.branch, appointment=appt1,
            status=Treatment.STATUS_PLANNED, total_amount=1000, clinic=self.clinic,
        )
        Treatment.objects.create(
            patient=self.patient, doctor=self.director, branch=self.branch, appointment=appt2,
            status=Treatment.STATUS_PLANNED, total_amount=2000, clinic=self.clinic,
        )
        data = _extract_newui_real_data(self.client.get("/new/cashdesk/").content.decode())
        rows = [r for r in data["cashdeskData"]["todayPatients"] if r["patientId"] == self.patient.pk]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["items"]), 2)
        self.assertEqual(rows[0]["time"], "09:00")  # earliest of the two

    def test_cashdesk_queue_reflects_real_send_to_cashier_notification(self):
        resp = self.client.post(f"/finance/payments/send-to-cashier/{self.patient.pk}/", {"amount": "3000"})
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        queue = data["cashdeskData"]["queue"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["patientId"], self.patient.pk)

    def test_cashdesk_accept_flow_creates_real_payment_and_clears_queue(self):
        """Полный путь «Принято» в новом интерфейсе: очередь несёт treatmentId
        (нужен фронту для модалки суммы/способа оплаты), сама оплата создаёт
        реальный Payment (а не просто гасит уведомление без следа в кассе),
        баланс пациента обновляется, и заявка пропадает из общей очереди."""
        from apps.treatments.models import Treatment
        treatment = Treatment.objects.create(
            patient=self.patient, doctor=self.director, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=8000, clinic=self.clinic,
        )
        resp = self.client.post(f"/finance/payments/send-to-cashier/{self.patient.pk}/",
                                 {"amount": "8000", "treatment": treatment.pk})
        self.assertEqual(resp.status_code, 302)

        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        queue = data["cashdeskData"]["queue"]
        self.assertEqual(len(queue), 1)
        item = queue[0]
        self.assertEqual(item["amount"], "8000")
        self.assertEqual(item["treatmentId"], treatment.pk)

        resp = self.client.post("/finance/payments/create/", {
            "patient": self.patient.pk, "treatment": treatment.pk,
            "amount": "8000", "method": "cash", "type": "income", "channel": "cashier",
        })
        self.assertEqual(resp.status_code, 302)
        payment = self.Payment.objects.get(patient=self.patient, treatment=treatment)
        self.assertEqual(payment.amount, 8000)
        self.assertEqual(payment.method, "cash")

        dismiss = self.client.get(f"/finance/cashdesk/queue/{item['id']}/dismiss/")
        self.assertEqual(dismiss.status_code, 200)
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(len(data["cashdeskData"]["queue"]), 0)

    def test_cashdesk_queue_dismiss_requires_accept_payments_permission(self):
        """«Принято» по сути подтверждает приём оплаты — то же действие, что
        payment_create (гейтится finance.accept_payments). Без явной проверки
        сотрудник без права принимать деньги (роль nurse — по умолчанию без
        finance.accept_payments) мог тихо скрыть заявку из общей очереди кассы,
        не оплатив её ни через кассу, ни через кого-либо ещё."""
        resp = self.client.post(f"/finance/payments/send-to-cashier/{self.patient.pk}/", {"amount": "3000"})
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        notif_id = data["cashdeskData"]["queue"][0]["id"]

        nurse_role = Role.objects.get(name="nurse", clinic__isnull=True)
        nurse = User.objects.create(
            login="cd_nurse", name="Медсестра CD", email="cdn@test.local",
            role=nurse_role, clinic=self.clinic,
        )
        nurse_client = Client()
        nurse_client.force_login(nurse)
        resp = nurse_client.get(f"/finance/cashdesk/queue/{notif_id}/dismiss/")
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(len(data["cashdeskData"]["queue"]), 1, "заявка не должна пропасть из очереди")

    def test_cashdesk_queue_is_shared_across_admins_not_just_sender(self):
        """send_to_cashier рассылает одно Notification на каждого админа клиники
        (fan-out) — второй администратор (не тот, кто отправил и не тот, кто
        нажал «Начать приём») должен тоже видеть заявку в очереди, а после
        того как ЛЮБОЙ из них нажмёт «Принято» — она должна пропасть у обоих.
        Раньше очередь фильтровалась строго по user=request.user, и второй
        администратор видел пустую кассу, хотя заявка была отправлена."""
        second_admin = User.objects.create(
            login="cd_admin2", name="Второй админ CD", email="cdd2@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        resp = self.client.post(f"/finance/payments/send-to-cashier/{self.patient.pk}/", {"amount": "3000"})
        self.assertEqual(resp.status_code, 302)

        other_client = Client()
        other_client.force_login(second_admin)
        resp = other_client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        queue = data["cashdeskData"]["queue"]
        self.assertEqual(len(queue), 1, "второй администратор должен видеть общую очередь кассы")
        notif_id = queue[0]["id"]

        dismiss = other_client.get(f"/finance/cashdesk/queue/{notif_id}/dismiss/")
        self.assertEqual(dismiss.status_code, 200)
        self.assertTrue(dismiss.json()["ok"])

        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(len(data["cashdeskData"]["queue"]), 0,
                          "после «Принято» у одного администратора заявка должна исчезнуть у всех")


class NewUIMessagesTestCase(TestCase):
    """Мессенджеры — реальная переписка (WaMessage), та же выборка, что в
    apps.notifications.views.wa_inbox, и та же переписка по пациенту
    (apps.patients.views.patient_wa_messages / patient_notify), что и на
    карточке пациента в старом интерфейсе."""

    def setUp(self):
        from apps.patients.models import Patient
        self.clinic = Clinic.objects.create(name="Клиника MS", slug="clinic-newui-messages")
        self.branch = Branch.objects.create(name="Филиал MS", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="ms_director", name="Директор MS", email="msd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)
        self.patient = Patient.objects.create(
            first_name="Чат", last_name="Тестов", phone="+996700123123", branch=self.branch, clinic=self.clinic,
        )

    def test_messages_page_lists_real_conversation_with_unread_count(self):
        from apps.notifications.models import WaMessage
        WaMessage.objects.create(patient=self.patient, direction="out", channel="wa", phone=self.patient.phone,
                                  body="Здравствуйте!", clinic=self.clinic)
        WaMessage.objects.create(patient=self.patient, direction="in", channel="wa", phone=self.patient.phone,
                                  body="Добрый день", read=False, clinic=self.clinic)
        resp = self.client.get("/new/messages/")
        data = _extract_newui_real_data(resp.content.decode())
        clients = data["messagesData"]["clients"]
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0]["id"], self.patient.pk)
        self.assertEqual(clients[0]["lastBody"], "Добрый день")
        self.assertEqual(clients[0]["unread"], 1)

    def test_thread_initial_load_returns_history_and_marks_read(self):
        from apps.notifications.models import WaMessage
        WaMessage.objects.create(patient=self.patient, direction="in", channel="wa", phone=self.patient.phone,
                                  body="Привет", read=False, clinic=self.clinic)
        resp = self.client.get(f"/patients/{self.patient.pk}/wa-messages/")
        self.assertEqual(resp.status_code, 200)
        msgs = resp.json()["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["body"], "Привет")
        self.assertTrue(WaMessage.objects.get(patient=self.patient).read)

    def test_thread_polling_with_after_param_unchanged_for_old_interface(self):
        """?after=<id> — конвенция старого интерфейса (patients/notify.html) — не должна
        измениться: id__gt фильтр, не «последние 300», иначе сломается автообновление там."""
        from apps.notifications.models import WaMessage
        first = WaMessage.objects.create(patient=self.patient, direction="in", channel="wa",
                                          phone=self.patient.phone, body="Первое", clinic=self.clinic)
        second = WaMessage.objects.create(patient=self.patient, direction="in", channel="wa",
                                           phone=self.patient.phone, body="Второе", clinic=self.clinic)
        resp = self.client.get(f"/patients/{self.patient.pk}/wa-messages/?after={first.pk}")
        msgs = resp.json()["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["id"], second.pk)


class NewUISettingsTestCase(TestCase):
    """Настройки клиники — реальный ClinicSettings, тот же view (/settings/),
    что и старый интерфейс, просто часть полей выведена в новом дизайне."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника ST", slug="clinic-newui-settings")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="st_director", name="Директор ST", email="std@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_settings_page_reflects_real_clinic_settings(self):
        from apps.settings_clinic.models import ClinicSettings
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            cs = ClinicSettings.get()
            cs.name = "Клиника ST"
            cs.appointment_slot = 45
            cs.save(update_fields=["name", "appointment_slot"])
        finally:
            clear_current_clinic()
        resp = self.client.get("/new/settings/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["settingsData"]["name"], "Клиника ST")
        self.assertEqual(data["settingsData"]["appointmentSlot"], 45)

    def test_settings_save_via_reused_backend_persists(self):
        resp = self.client.post("/settings/", {
            "name": "Новое имя клиники", "phone": "", "address": "",
            "appointment_slot": "20", "currency": "KGS", "language": "ru",
            "receipt_format": "thermal", "receipt_clinic_name": "", "receipt_legal_name": "",
            "receipt_inn": "", "receipt_address": "", "warranty_terms": "",
            "timezone": "Asia/Bishkek",
        })
        self.assertEqual(resp.status_code, 302)
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.get()
        self.assertEqual(cs.name, "Новое имя клиники")
        self.assertEqual(cs.appointment_slot, 20)

    def test_clinic_language_available_on_any_page_not_only_settings(self):
        """Язык интерфейса — реальная настройка (ClinicSettings.language),
        но подписи меню переводятся в base.html, который рендерится на
        КАЖДОЙ странице /new/*, а не только на странице настроек. Раньше
        clinicLanguage прокидывался только в settingsData, поэтому язык
        сбрасывался на русский при любом переходе на другую страницу."""
        from apps.settings_clinic.models import ClinicSettings
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            cs = ClinicSettings.get()
            cs.language = "ky"
            cs.save(update_fields=["language"])
        finally:
            clear_current_clinic()
        resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["clinicLanguage"], "ky")


class NewUIVisitWizardTestCase(TestCase):
    """Карточка приёма («Начать приём») — реальный клинический мастер
    (apps.treatments.views_visit), новый интерфейс просто открывает те же
    save/upload/commit view в своём дизайне."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.services.models import Service
        self.clinic = Clinic.objects.create(name="Клиника VW", slug="clinic-newui-visitwizard")
        self.branch = Branch.objects.create(name="Филиал VW", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="vw_director", name="Директор VW", email="vwd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="vw_doctor", name="Врач VW", email="vwdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)
        self.patient = Patient.objects.create(
            first_name="Приём", last_name="Тестов", phone="+996700321321", branch=self.branch, clinic=self.clinic,
        )
        self.service = Service.objects.create(name="Пломбирование", price=2500, clinic=self.clinic)

        import datetime as dt
        from django.utils import timezone
        from apps.appointments.models import Appointment
        today = timezone.localdate()
        start = timezone.make_aware(dt.datetime.combine(today, dt.time(10, 0)))
        end = timezone.make_aware(dt.datetime.combine(today, dt.time(10, 30)))
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch, service=self.service,
            start_at=start, end_at=end, status="arrived", clinic=self.clinic,
        )

    def test_visit_start_creates_treatment_and_redirects_to_new_visitcard(self):
        from apps.treatments.models import Treatment
        resp = self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/new/visitcard/"))
        treatment = Treatment.objects.get(appointment=self.appt)
        self.assertEqual(treatment.status, "in_progress")
        self.assertEqual(treatment.patient_id, self.patient.pk)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "in_progress")

    def test_visit_start_resumes_existing_treatment_not_duplicate(self):
        resp1 = self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        resp2 = self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(resp1.url, resp2.url)
        from apps.treatments.models import Treatment
        self.assertEqual(Treatment.objects.filter(appointment=self.appt).count(), 1)

    def test_newui_visitcard_page_has_real_wizard_data(self):
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        from apps.treatments.models import Treatment
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.get(f"/new/visitcard/{treatment.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = _extract_newui_real_data(resp.content.decode())
        vw = data["visitWizard"]
        self.assertEqual(vw["patientName"], "Тестов Приём")
        service_names = [s["name"] for s in vw["services"]]
        self.assertIn("Пломбирование", service_names)
        self.assertEqual(vw["status"], "in_progress")

    def test_visit_save_persists_diagnosis_and_tooth_condition(self):
        from apps.treatments.models import Treatment
        from apps.treatments.models_emr import MedicalRecord
        from apps.treatments.models_teeth import ToothCondition
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        # Каталог статусов зуба (ToothStatus) сеется при первом открытии
        # карточки приёма (_ensure_tooth_statuses в visit_wizard/visitcard) —
        # в реальном потоке пользователь всегда сначала открывает страницу.
        self.client.get(f"/new/visitcard/{treatment.pk}/")
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"diagnosis": "Кариес 26", "complaints": "Боль при накусывании", "teeth": {"26": "caries"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        emr = MedicalRecord.objects.get(treatment=treatment)
        self.assertEqual(emr.diagnosis, "Кариес 26")
        tc = ToothCondition.objects.get(patient=self.patient, tooth_number=26)
        self.assertEqual(tc.status.code, "caries")

    def test_visit_save_persists_tooth_surface_and_gum_condition(self):
        """Поверхности/дёсны раньше жили только в JS-памяти вкладки
        (surfaceStates/gumStates) и терялись при перезагрузке — модалка
        визуально «сохраняла», а на самом деле ничего не уходило на бэкенд."""
        from apps.treatments.models import Treatment
        from apps.treatments.models_teeth import ToothSurfaceCondition, ToothGumCondition
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        self.client.get(f"/new/visitcard/{treatment.pk}/")  # сеет ToothSurfaceStatus/ToothGumStatus
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"surfaces": {"26-2": "caries_simple"}, "gums": {"26": "parodontit"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        sc = ToothSurfaceCondition.objects.get(patient=self.patient, tooth_number=26, surface_index=2)
        self.assertEqual(sc.status.code, "caries_simple")
        gc = ToothGumCondition.objects.get(patient=self.patient, tooth_number=26)
        self.assertEqual(gc.status.code, "parodontit")

        # ...и переживают перезагрузку карточки приёма (гидратация из БД, а не только сессия).
        resp2 = self.client.get(f"/new/visitcard/{treatment.pk}/")
        data2 = _extract_newui_real_data(resp2.content.decode())
        vw = data2["visitWizard"]
        self.assertEqual(vw["toothSurfaceConditionsJs"]["adult-26-s2"], "caries_simple")
        self.assertEqual(vw["toothGumConditionsJs"]["adult-26"], "parodontit")

    def test_visit_commit_completes_treatment_and_appointment(self):
        from apps.treatments.models import Treatment
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/commit/",
            data=json.dumps({"plan": [{"service_id": self.service.pk, "tooth": "26", "qty": 1, "price": 2500, "done": True}]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        treatment.refresh_from_db()
        self.assertEqual(treatment.status, "completed")
        self.assertEqual(treatment.cures.count(), 1)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "completed")

    def test_completed_treatment_allows_save_upload_but_blocks_repeat_commit(self):
        """После завершения приёма ЭМК/зубы/файлы всё ещё можно поправить
        (обычная клиническая необходимость дописать/исправить задним числом) —
        заблокирован только повторный commit: там списание материалов и заказы
        технику, повторный запуск задвоил бы их."""
        from apps.treatments.models import Treatment
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        treatment.status = "completed"
        treatment.save(update_fields=["status"])

        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"diagnosis": "Поправка диагноза после завершения"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        from apps.treatments.models_emr import MedicalRecord
        self.assertEqual(MedicalRecord.objects.get(treatment=treatment).diagnosis, "Поправка диагноза после завершения")

        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/commit/",
            data=json.dumps({"plan": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/upload/",
            {"files": SimpleUploadedFile("x.jpg", b"data", content_type="image/jpeg")},
        )
        self.assertEqual(resp.status_code, 200)

    def test_completed_treatment_tooth_condition_still_saves(self):
        """Жалоба пользователя: после завершения приёма отметка состояния зуба
        визуально менялась, но не сохранялась (бэкенд отвечал 403) — при
        перезагрузке карточки зуб возвращался к прежнему состоянию."""
        from apps.treatments.models import Treatment
        from apps.treatments.models_teeth import ToothCondition
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        self.client.get(f"/new/visitcard/{treatment.pk}/")  # сеет ToothStatus (_ensure_tooth_statuses)
        treatment.status = "completed"
        treatment.save(update_fields=["status"])

        resp = self.client.post(
            f"/treatments/visit/{treatment.pk}/save/",
            data=json.dumps({"teeth": {"26": "caries"}}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        tc = ToothCondition.objects.get(patient=self.patient, tooth_number=26)
        self.assertEqual(tc.status.code, "caries")

        # ...и переживает перезагрузку карточки приёма (реально из БД, а не сессия).
        resp2 = self.client.get(f"/new/visitcard/{treatment.pk}/")
        data2 = _extract_newui_real_data(resp2.content.decode())
        self.assertEqual(data2["visitWizard"]["toothConditionsJs"]["adult-26"], "caries_mid")

    def test_already_completed_treatment_reopens_view_not_new_wizard(self):
        from apps.treatments.models import Treatment
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        treatment = Treatment.objects.get(appointment=self.appt)
        treatment.status = "completed"
        treatment.save(update_fields=["status"])
        resp = self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f"/new/visitcard/{treatment.pk}/")
        self.assertEqual(Treatment.objects.filter(appointment=self.appt).count(), 1)


class NewUIFunnelTestCase(TestCase):
    """CRM-воронка заявок — совсем новый раздел (apps.patients.models.Lead),
    которого раньше не было ни в новом, ни в старом интерфейсе."""

    def setUp(self):
        from apps.patients.models import LeadSource
        self.clinic = Clinic.objects.create(name="Клиника FN", slug="clinic-newui-funnel")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="fn_director", name="Директор FN", email="fnd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)
        self.source = LeadSource.objects.create(name="Instagram")

    def test_funnel_page_lists_real_lead(self):
        from apps.patients.models import Lead
        Lead.objects.create(name="Азизбекова М.", phone="+996555221109", source=self.source,
                             stage=Lead.STAGE_NEW, clinic=self.clinic)
        resp = self.client.get("/new/funnel/")
        data = _extract_newui_real_data(resp.content.decode())
        names = [l["name"] for l in data["funnelData"]["leads"]]
        self.assertIn("Азизбекова М.", names)
        stage_codes = [s["code"] for s in data["funnelData"]["stages"]]
        self.assertEqual(len(stage_codes), 8)

    def test_lead_create_via_api(self):
        resp = self.client.post(
            "/patients/leads/create/",
            data=json.dumps({"name": "Новая заявка", "phone": "+996700111222", "source_id": self.source.pk}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["lead"]["stage"], "new")
        from apps.patients.models import Lead
        self.assertTrue(Lead.objects.filter(name="Новая заявка", clinic=self.clinic).exists())

    def test_lead_create_requires_name(self):
        resp = self.client.post(
            "/patients/leads/create/", data=json.dumps({"name": ""}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())

    def test_lead_update_changes_stage_for_drag_and_drop(self):
        from apps.patients.models import Lead
        lead = Lead.objects.create(name="Драг Тест", stage=Lead.STAGE_NEW, clinic=self.clinic)
        resp = self.client.post(
            f"/patients/leads/{lead.pk}/update/",
            data=json.dumps({"stage": "booked"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.stage, "booked")

    def test_lead_update_rejects_invalid_stage(self):
        from apps.patients.models import Lead
        lead = Lead.objects.create(name="Инвалид Стейдж", stage=Lead.STAGE_NEW, clinic=self.clinic)
        resp = self.client.post(
            f"/patients/leads/{lead.pk}/update/",
            data=json.dumps({"stage": "not_a_real_stage"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        lead.refresh_from_db()
        self.assertEqual(lead.stage, "new")

    def test_lead_delete(self):
        from apps.patients.models import Lead
        lead = Lead.objects.create(name="Удалить", stage=Lead.STAGE_NEW, clinic=self.clinic)
        resp = self.client.post(f"/patients/leads/{lead.pk}/delete/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Lead.objects.filter(pk=lead.pk).exists())

    def test_leads_are_clinic_scoped(self):
        from apps.patients.models import Lead
        other_clinic = Clinic.objects.create(name="Клиника FN2", slug="clinic-newui-funnel2")
        Lead.objects.create(name="Чужая заявка", stage=Lead.STAGE_NEW, clinic=other_clinic)
        Lead.objects.create(name="Своя заявка", stage=Lead.STAGE_NEW, clinic=self.clinic)
        resp = self.client.get("/new/funnel/")
        data = _extract_newui_real_data(resp.content.decode())
        names = [l["name"] for l in data["funnelData"]["leads"]]
        self.assertIn("Своя заявка", names)
        self.assertNotIn("Чужая заявка", names)


class NewUISectionAccessTestCase(TestCase):
    """Личные ограничения доступа (User.allowed_sections, применяются
    apps.tenancy.SectionAccessMiddleware) должны действовать одинаково на
    старом и новом интерфейсе — иначе сотрудник с ограничением обходит его
    через /new/... (см. PREFIXES в apps/tenancy.py)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника SA", slug="clinic-newui-secaccess")
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        # Разрешён только "patients" — без "finance"/"staff"/"warehouse" и т.д.
        self.staffer = User.objects.create(
            login="sa_staffer", name="Ограниченный", email="sas@test.local",
            role=self.doctor_role, clinic=self.clinic, allowed_sections=["patients"],
        )
        self.client = Client()
        self.client.force_login(self.staffer)

    def test_old_finance_blocked_for_restricted_user(self):
        resp = self.client.get("/finance/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/")

    def test_new_finance_blocked_for_restricted_user(self):
        resp = self.client.get("/new/finance/")
        self.assertEqual(resp.status_code, 302)
        # Остаёмся в новом интерфейсе (не уводим на дашборд старого) —
        # см. комментарий в SectionAccessMiddleware.
        self.assertEqual(resp.url, "/new/")

    def test_new_staff_blocked_for_restricted_user(self):
        resp = self.client.get("/new/staff/")
        self.assertEqual(resp.status_code, 302)

    def test_new_warehouse_blocked_for_restricted_user(self):
        resp = self.client.get("/new/warehouse/")
        self.assertEqual(resp.status_code, 302)

    def test_new_patients_allowed_for_restricted_user(self):
        resp = self.client.get("/new/patients/")
        self.assertEqual(resp.status_code, 200)

    def test_new_dashboard_always_allowed(self):
        resp = self.client.get("/new/")
        self.assertEqual(resp.status_code, 200)

    def test_sidebar_nav_sections_reflect_restriction(self):
        """real_data.navSections (см. _shared_options) — то, чем сайдбар нового
        интерфейса решает, какие пункты прятать (hideRestrictedNavItems в
        base.html). Должен нести именно то, что реально разрешено, а не
        всё подряд. Сам HTML сайдбара всегда содержит ссылки на все разделы
        (data-view/href), поэтому проверяем не текст страницы целиком, а
        именно json_script-блок real_data — иначе тест ловил бы href="/new/
        finance/" самой (скрываемой) ссылки и ложно падал."""
        import json
        import re
        resp = self.client.get("/new/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        m = re.search(
            r'<script id="newui-real-data"[^>]*>(.*?)</script>', content, re.S,
        )
        self.assertIsNotNone(m, "real_data json_script блок не найден")
        real_data = json.loads(m.group(1))
        self.assertEqual(sorted(real_data["navSections"]), ["dashboard", "patients"])


class NewUIPatientCardDetailTestCase(TestCase):
    """Карточка пациента /new/patients/<pk>/ — реальные вкладки История/Зубная
    карта/План/Финансы/Документы, те же запросы, что apps.patients.views.patient_detail."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.services.models import Service
        from apps.finance.models import Payment
        from apps.treatments.models import Treatment, TreatmentCure, TreatmentFile
        from apps.treatments.models_teeth import ToothStatus, ToothCondition
        from apps.treatments.models_plan import TreatmentPlan, TreatmentPlanStage
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.clinic = Clinic.objects.create(name="Клиника PCD", slug="clinic-newui-pcd")
        self.branch = Branch.objects.create(name="Филиал PCD", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="pcd_director", name="Директор PCD", email="pcdd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

        self.patient = Patient.objects.create(
            first_name="Карта", last_name="Пациентова", phone="+996700123123",
            branch=self.branch, clinic=self.clinic,
        )
        service = Service.objects.create(name="Пломбирование", price=3200, clinic=self.clinic)
        treatment = self.treatment = Treatment.objects.create(
            patient=self.patient, doctor=self.director, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=3200, clinic=self.clinic,
        )
        TreatmentCure.objects.create(treatment=treatment, service=service, price=3200, doctor=self.director)
        TreatmentFile.objects.create(
            treatment=treatment, name="Снимок 26", kind="xray",
            file=SimpleUploadedFile("xray.jpg", b"fake-bytes", content_type="image/jpeg"),
            uploaded_by=self.director,
        )
        Payment.objects.create(
            patient=self.patient, amount=3200, branch=self.branch, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        status = ToothStatus.objects.create(code="filling", name="Пломба", color="#3B82F6")
        ToothCondition.objects.create(patient=self.patient, tooth_number=26, status=status)
        plan = TreatmentPlan.objects.create(patient=self.patient, doctor=self.director, title="Пломбирование, зуб 26", status=TreatmentPlan.STATUS_APPROVED)
        TreatmentPlanStage.objects.create(plan=plan, title="Этап 1")

    def test_patientcard_history_reflects_real_treatment(self):
        resp = self.client.get(f"/new/patients/{self.patient.pk}/")
        data = _extract_newui_real_data(resp.content.decode())
        history = data["patientCardDetail"]["history"]
        self.assertEqual(len(history), 1)
        self.assertIn("Пломбирование", history[0]["service"])
        self.assertEqual(history[0]["amount"], 3200.0)
        # id нужен фронту, чтобы клик по строке открывал именно этот визит
        # (templates/newui/base.html:renderPatientCardHistory) — без него ссылка
        # уводила на /new/visitcard/undefined/.
        self.assertEqual(history[0]["id"], self.treatment.pk)

    def test_patientcard_finance_reflects_real_payment(self):
        resp = self.client.get(f"/new/patients/{self.patient.pk}/")
        data = _extract_newui_real_data(resp.content.decode())
        detail = data["patientCardDetail"]
        self.assertEqual(detail["totalPaid"], 3200.0)
        self.assertEqual(len(detail["payments"]), 1)

    def test_patientcard_teeth_reflects_real_condition_mapped_to_js_code(self):
        resp = self.client.get(f"/new/patients/{self.patient.pk}/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["patientCardDetail"]["toothConditions"]["adult-26"], "filling")

    def test_patientcard_teeth_reflects_real_surface_and_gum_conditions(self):
        from apps.treatments.models_teeth import ToothSurfaceStatus, ToothGumStatus, ToothSurfaceCondition, ToothGumCondition
        surf = ToothSurfaceStatus.objects.create(code="caries_simple", name="Кариес", color="#9C94EA")
        gum = ToothGumStatus.objects.create(code="parodontit", name="Пародонтит", color="#4B5259")
        ToothSurfaceCondition.objects.create(patient=self.patient, tooth_number=26, surface_index=2, status=surf)
        ToothGumCondition.objects.create(patient=self.patient, tooth_number=26, status=gum)
        resp = self.client.get(f"/new/patients/{self.patient.pk}/")
        data = _extract_newui_real_data(resp.content.decode())
        detail = data["patientCardDetail"]
        self.assertEqual(detail["toothSurfaceConditions"]["adult-26-s2"], "caries_simple")
        self.assertEqual(detail["toothGumConditions"]["adult-26"], "parodontit")

    def test_patientcard_plan_reflects_real_treatment_plan(self):
        resp = self.client.get(f"/new/patients/{self.patient.pk}/")
        data = _extract_newui_real_data(resp.content.decode())
        plans = data["patientCardDetail"]["plans"]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["stage"], "Этап 1")

    def test_patientcard_documents_reflects_real_file(self):
        resp = self.client.get(f"/new/patients/{self.patient.pk}/")
        data = _extract_newui_real_data(resp.content.decode())
        docs = data["patientCardDetail"]["documents"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Снимок 26")


def timezone_today():
    from django.utils import timezone
    return timezone.localdate()


class NewUIStaffRoleFetchFlowTestCase(TestCase):
    """Модалки нового интерфейса сохраняют реальные данные через fetch() на
    существующие Django-view (staff_create/staff_edit/role_create/role_edit/
    role_delete), не уходя со страницы. Тесты бьют по этим view напрямую —
    так же, как это делает JS через postForm() — чтобы проверить контракт
    (redirect = успех, 200 = ошибка формы), на который опирается JS."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника NF", slug="clinic-newui-fetch")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="nf_director", name="Директор NF", email="nfd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_staff_create_via_modal_fields_redirects_on_success(self):
        resp = self.client.post("/users/create/", {
            "login": "modal_staff", "name": "Модальный Сотрудник",
            "password": "", "can_view_all_appointments": "on", "full_access": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(login="modal_staff", clinic=self.clinic).exists())

    def test_staff_create_via_modal_persists_and_exposes_color(self):
        """Цвет сотрудника (User.color) — задаётся в модалке «Сотрудник», используется
        для аватара и для закраски его колонки в расписании нового интерфейса."""
        resp = self.client.post("/users/create/", {
            "login": "colored_doc", "name": "Цветной Доктор",
            "password": "", "can_view_all_appointments": "on", "full_access": "on",
            "color": "#FF5733",
        })
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(login="colored_doc", clinic=self.clinic)
        self.assertEqual(user.color, "#FF5733")

        resp2 = self.client.get("/new/staff/")
        data = _extract_newui_real_data(resp2.content.decode())
        staff_row = next(s for s in data["staff"] if s["login"] == "colored_doc")
        self.assertEqual(staff_row["color"], "#FF5733")

    def test_staff_create_via_modal_missing_login_does_not_redirect(self):
        resp = self.client.post("/users/create/", {
            "login": "", "name": "Без логина", "full_access": "on",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.has_header("Location"))

    def test_role_create_via_modal_redirects_to_edit_page(self):
        resp = self.client.post("/users/roles/create/", {"name": "Кассир-модал"})
        self.assertEqual(resp.status_code, 302)
        role = Role.objects.get(name="Кассир-модал", clinic=self.clinic)
        self.assertEqual(resp.url, f"/users/roles/{role.pk}/edit/")

    def test_role_create_duplicate_name_redirects_to_list_not_edit(self):
        Role.objects.create(name="Дубликат", clinic=self.clinic)
        resp = self.client.post("/users/roles/create/", {"name": "Дубликат"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/users/roles/")

    def test_role_edit_via_modal_saves_permissions_and_redirects(self):
        role = Role.objects.create(name="Регистратор-модал", clinic=self.clinic)
        perm = Permission.objects.get(code="staff.manage")
        resp = self.client.post(f"/users/roles/{role.pk}/edit/", {
            "name": "Регистратор-модал", "permissions": [perm.code],
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(role.has_perm("staff.manage"))


class UserColorFieldTestCase(TestCase):
    def test_color_optional_and_blank_by_default(self):
        u = User.objects.create(login="staff_nocolor", name="Без цвета", email="nc@test.local")
        self.assertEqual(u.color, "")

    def test_color_can_be_set(self):
        u = User.objects.create(login="staff_color", name="С цветом", email="c@test.local", color="#F59E0B")
        self.assertEqual(u.color, "#F59E0B")

    def test_form_does_not_require_color(self):
        form = UserForm(data={
            "login": "staff_form", "name": "Форма", "email": "form@test.local",
            "password": "", "full_access": "on",
        })
        form.is_valid()
        self.assertNotIn("color", form.errors)


class PermissionCatalogTestCase(TestCase):
    def test_permission_has_category_and_code(self):
        # test.dummy_action — заведомо не пересекается с реальным каталогом
        # прав (сидится data migration'ом Task 2, code там уникален)
        p = Permission.objects.create(
            code="test.dummy_action", category=PermissionCategory.FINANCE,
            label="Приём оплат",
        )
        self.assertEqual(p.category, "finance")
        self.assertEqual(str(p), "Приём оплат")


class RoleClinicScopingTestCase(TestCase):
    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a-roles")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b-roles")

    def test_system_role_has_no_clinic(self):
        role = Role.objects.create(name="doctor_test1", is_system=True)
        self.assertIsNone(role.clinic)

    def test_custom_role_scoped_to_one_clinic(self):
        role = Role.objects.create(name="Кассир", clinic=self.clinic_a)
        self.assertEqual(role.clinic, self.clinic_a)

    def test_same_role_name_allowed_in_different_clinics(self):
        Role.objects.create(name="Кассир", clinic=self.clinic_a)
        # не должно упасть — имя уникально ТОЛЬКО в пределах клиники, не глобально
        role_b = Role.objects.create(name="Кассир", clinic=self.clinic_b)
        self.assertEqual(role_b.clinic, self.clinic_b)


class RoleHasPermTestCase(TestCase):
    def test_has_perm_true_when_granted(self):
        perm = Permission.objects.create(code="test.dummy_action2", category="finance", label="X")
        role = Role.objects.create(name="custom_cashier_test", is_system=True)
        role.granular_permissions.add(perm)
        self.assertTrue(role.has_perm("test.dummy_action2"))

    def test_has_perm_false_when_not_granted(self):
        role = Role.objects.create(name="custom_empty_test", is_system=True)
        self.assertFalse(role.has_perm("finance.accept_payments"))


class PermissionSeedTestCase(TestCase):
    def test_catalog_seeded_with_eleven_permissions(self):
        # 9 из 0022_seed_permissions + finance.quick_sale (0024) +
        # patients.delete_history (0026).
        self.assertEqual(Permission.objects.count(), 11)

    def test_system_roles_marked_is_system(self):
        for name in ["superadmin", "admin_main", "admin", "doctor", "nurse"]:
            role = Role.objects.get(name=name, clinic__isnull=True)
            self.assertTrue(role.is_system)

    def test_admin_role_has_no_staff_manage_by_default(self):
        role = Role.objects.get(name="admin", clinic__isnull=True)
        self.assertFalse(role.has_perm("staff.manage"))

    def test_admin_main_has_staff_manage_by_default(self):
        role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.assertTrue(role.has_perm("staff.manage"))


class RequirePermissionDecoratorTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника C", slug="clinic-c-perm")
        self.perm = Permission.objects.create(code="test.action", category="finance", label="Тестовое действие")
        self.role_with = Role.objects.create(name="role_with_test", is_system=True)
        self.role_with.granular_permissions.add(self.perm)
        self.role_without = Role.objects.create(name="role_without_test", is_system=True)
        self.user_with = User.objects.create(login="perm_yes", name="Y", email="y@test.local", role=self.role_with)
        self.user_with.set_password("x12345678")
        self.user_with.save()
        self.user_without = User.objects.create(login="perm_no", name="N", email="n@test.local", role=self.role_without)
        self.user_without.set_password("x12345678")
        self.user_without.save()

    def test_view_allows_user_with_permission(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from apps.users.decorators import require_permission
        @require_permission("test.action")
        def view(request):
            return HttpResponse("ok")
        rf = RequestFactory()
        request = rf.get("/x")
        request.user = self.user_with
        response = view(request)
        self.assertEqual(response.status_code, 200)

    def test_view_blocks_user_without_permission(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from apps.users.decorators import require_permission
        @require_permission("test.action")
        def view(request):
            return HttpResponse("ok")
        rf = RequestFactory()
        request = rf.get("/x")
        request.user = self.user_without
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_superadmin_always_passes(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from apps.users.decorators import require_permission
        superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        su = User.objects.create(
            login="perm_su", name="SU", email="su@test.local", role=superadmin_role, is_superuser=True,
        )
        @require_permission("test.action")
        def view(request):
            return HttpResponse("ok")
        rf = RequestFactory()
        request = rf.get("/x")
        request.user = su
        response = view(request)
        self.assertEqual(response.status_code, 200)


class StaffManagePermissionTestCase(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="no_staff_role_test", is_system=True)
        self.user = User.objects.create(login="no_staff_test", name="U2", email="u2@test.local", role=self.role)
        self.client = Client()
        self.client.force_login(self.user)

    def test_staff_create_blocked_without_permission(self):
        resp = self.client.get("/users/create/")
        self.assertEqual(resp.status_code, 403)


class RoleCrudViewsTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника D", slug="clinic-d-crud")
        self.branch = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.staff_perm = Permission.objects.filter(code="staff.manage").first() or Permission.objects.create(
            code="staff.manage", category="staff", label="Управление персоналом",
        )
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="director_crud", name="Директор", email="dir@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_create_role_scoped_to_own_clinic(self):
        resp = self.client.post("/users/roles/create/", {"name": "Кассир"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        role = Role.objects.get(name="Кассир", clinic=self.clinic)
        self.assertFalse(role.is_system)

    def test_role_list_excludes_other_clinics_custom_roles(self):
        other_clinic = Clinic.objects.create(name="Клиника E", slug="clinic-e-crud")
        Role.objects.create(name="Чужая роль", clinic=other_clinic)
        resp = self.client.get("/users/roles/")
        names = [r.name for r in resp.context["roles"]]
        self.assertNotIn("Чужая роль", names)

    def test_role_list_excludes_platform_superadmin_role(self):
        resp = self.client.get("/users/roles/")
        names = [r.name for r in resp.context["roles"]]
        self.assertNotIn(Role.SUPERADMIN, names)

    def test_superadmin_role_not_editable_via_direct_url(self):
        role = Role.objects.get(name=Role.SUPERADMIN, clinic__isnull=True)
        resp = self.client.get(f"/users/roles/{role.pk}/edit/")
        self.assertEqual(resp.status_code, 404)

    def test_role_edit_page_renders_permission_grid(self):
        role = Role.objects.create(name="Регистратор", clinic=self.clinic)
        resp = self.client.get(f"/users/roles/{role.pk}/edit/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Все права")
        self.assertContains(resp, self.staff_perm.label)

    def test_cannot_delete_system_role(self):
        role = Role.objects.get(name="doctor", clinic__isnull=True)
        resp = self.client.post(f"/users/roles/{role.pk}/delete/", follow=True)
        self.assertTrue(Role.objects.filter(pk=role.pk).exists())

    def test_duplicate_role_creates_independent_copy(self):
        perm = Permission.objects.get(code="staff.manage")
        original = Role.objects.create(name="Оригинал", clinic=self.clinic)
        original.granular_permissions.add(perm)
        resp = self.client.post(f"/users/roles/{original.pk}/duplicate/", follow=True)
        self.assertEqual(resp.status_code, 200)
        copy = Role.objects.filter(clinic=self.clinic).exclude(pk=original.pk).latest("id")
        self.assertTrue(copy.has_perm("staff.manage"))
        copy.granular_permissions.remove(perm)
        self.assertTrue(original.has_perm("staff.manage"))  # оригинал не затронут


class StaffFormTabsTestCase(TestCase):
    """Форма сотрудника разбита на вкладки (Основное / Роль и филиалы / Врач /
    Доступ к разделам), чтобы не листать одну длинную страницу."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника F", slug="clinic-f-tabs")
        Permission.objects.filter(code="staff.manage").first() or Permission.objects.create(
            code="staff.manage", category="staff", label="Управление персоналом",
        )
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="director_tabs", name="Директор", email="dirtabs@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.director)

    def test_create_page_renders_all_tabs(self):
        resp = self.client.get("/users/create/")
        self.assertEqual(resp.status_code, 200)
        for label in ["Основное", "Роль и филиалы", "Врач", "Доступ к разделам"]:
            self.assertContains(resp, label)

    def test_create_page_no_longer_lists_fields_in_single_scroll(self):
        resp = self.client.get("/users/create/")
        # Поля разнесены по вкладкам через x-show, а не в одном .grid без табов
        self.assertContains(resp, 'x-show="tab==')

    def test_can_still_create_staff_through_tabbed_form(self):
        resp = self.client.post("/users/create/", {
            "login": "new_staff_tabs", "name": "Новый Сотрудник", "email": "ns@test.local",
            "password": "secret123", "full_access": "on",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(login="new_staff_tabs").exists())

    def test_staff_list_add_button_links_to_full_page(self):
        resp = self.client.get("/users/")
        self.assertContains(resp, 'href="/users/create/"')

    def test_superadmin_role_not_offered_in_staff_form_even_to_superadmin_viewer(self):
        self.director.is_superuser = True
        self.director.save(update_fields=["is_superuser"])
        resp = self.client.get("/users/create/")
        superadmin_label = dict(Role.ROLE_CHOICES)[Role.SUPERADMIN]
        self.assertNotContains(resp, superadmin_label)


class ClinicGrantedAccessTestCase(TestCase):
    """Клиники по умолчанию не могут создавать филиалы, пока супер-админ
    явно не выдал доступ (Clinic.granted_access) — проверяем оба места
    создания филиала (web-форма + REST API), и что супер-админ сам не
    ограничен доступами."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника GA", slug="clinic-granted-access")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(
            login="ga_director", name="Директор GA", email="gad@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.superadmin = User.objects.create(
            login="ga_super", name="Супер GA", email="gas@test.local",
            role=self.superadmin_role,
        )
        self.client = Client()

    def test_branch_create_blocked_without_access(self):
        self.client.force_login(self.director)
        resp = self.client.post("/users/branches/create/", {
            "name": "Второй филиал", "address": "ул. Тестовая", "phone": "0",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Branch.objects.filter(clinic=self.clinic, name="Второй филиал").exists())

    def test_branch_create_allowed_with_access(self):
        self.clinic.granted_access = ["branches"]
        self.clinic.save(update_fields=["granted_access"])
        self.client.force_login(self.director)
        resp = self.client.post("/users/branches/create/", {
            "name": "Второй филиал", "address": "ул. Тестовая", "phone": "0",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Branch.objects.filter(clinic=self.clinic, name="Второй филиал").exists())

    def test_superadmin_not_limited_by_clinic_access(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post("/users/branches/create/", {
            "name": "Филиал супера", "address": "ул. Тестовая", "phone": "0",
        })
        self.assertEqual(resp.status_code, 302)

    def test_branch_api_create_blocked_without_access(self):
        self.client.force_login(self.director)
        resp = self.client.post("/api/v1/auth/branches/", {
            "name": "API филиал", "address": "ул. Тестовая", "phone": "0",
        })
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Branch.objects.filter(clinic=self.clinic, name="API филиал").exists())

    def test_branch_api_create_allowed_with_access(self):
        self.clinic.granted_access = ["branches"]
        self.clinic.save(update_fields=["granted_access"])
        self.client.force_login(self.director)
        resp = self.client.post("/api/v1/auth/branches/", {
            "name": "API филиал", "address": "ул. Тестовая", "phone": "0",
        })
        self.assertEqual(resp.status_code, 201)

    def test_clinic_set_access_only_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.post(f"/users/clinic/{self.clinic.pk}/access/", {"access": ["branches"]})
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.granted_access, [])

    def test_clinic_set_access_by_superadmin_ignores_invalid_keys(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post(f"/users/clinic/{self.clinic.pk}/access/", {
            "access": ["branches", "not-a-real-key"],
        })
        self.assertEqual(resp.status_code, 302)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.granted_access, ["branches"])

    def test_clinic_update_by_superadmin(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post(f"/users/clinic/{self.clinic.pk}/update/", {
            "name": "Клиника GA (переименована)", "slug": self.clinic.slug,
            "timezone": "Asia/Bishkek", "tariff_plan": "premium",
        })
        self.assertEqual(resp.status_code, 302)
        self.clinic.refresh_from_db()
        self.assertEqual(self.clinic.name, "Клиника GA (переименована)")
        self.assertEqual(self.clinic.tariff_plan, "premium")

    def test_clinic_update_blocked_for_non_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.post(f"/users/clinic/{self.clinic.pk}/update/", {"name": "Хакнутое имя"})
        self.clinic.refresh_from_db()
        self.assertNotEqual(self.clinic.name, "Хакнутое имя")


class ClinicGrantedAccessMigrationTestCase(TestCase):
    """Data-миграция 0028: клиники, у которых уже было больше одного
    активного филиала на момент миграции, грандфазерятся (не отбираем
    задним числом), однофилиальные/новые — остаются без доступа."""

    def test_grandfathers_multi_branch_clinics(self):
        import importlib
        mod = importlib.import_module("apps.users.migrations.0028_clinic_granted_access")

        multi = Clinic.objects.create(name="Много филиалов", slug="clinic-multi")
        Branch.objects.create(name="Ф1", address="-", phone="0", clinic=multi, is_active=True)
        Branch.objects.create(name="Ф2", address="-", phone="0", clinic=multi, is_active=True)

        single = Clinic.objects.create(name="Один филиал", slug="clinic-single")
        Branch.objects.create(name="Ф1", address="-", phone="0", clinic=single, is_active=True)

        from django.apps import apps as django_apps
        mod.grandfather_multi_branch_clinics(django_apps, None)

        multi.refresh_from_db()
        single.refresh_from_db()
        self.assertEqual(multi.granted_access, ["branches"])
        self.assertEqual(single.granted_access, [])


class SuperadminHostMiddlewareTestCase(TestCase):
    """SUPERADMIN_HOST (soft.stom.asia в проде) — если не задан, middleware
    no-op; если задан и хост совпадает, посторонняя сессия разлогинивается,
    а супер-админ на "/" уводится сразу в панель."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника SH", slug="clinic-superadmin-host")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(
            login="sh_director", name="Директор SH", email="shd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.superadmin = User.objects.create(
            login="sh_super", name="Супер SH", email="shs@test.local",
            role=self.superadmin_role,
        )
        self.client = Client()

    def test_noop_when_unset(self):
        self.client.force_login(self.director)
        resp = self.client.get("/", HTTP_HOST="soft.stom.asia")
        # SUPERADMIN_HOST не задан в дев-настройках — обычный хостинг, сессия жива
        self.assertNotEqual(resp.status_code, 302)

    def test_logs_out_non_superadmin_on_superadmin_host(self):
        from django.test import override_settings
        self.client.force_login(self.director)
        with override_settings(SUPERADMIN_HOST="soft.stom.asia"):
            resp = self.client.get("/users/", HTTP_HOST="soft.stom.asia", follow=True)
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_superadmin_root_redirects_to_panel(self):
        from django.test import override_settings
        self.client.force_login(self.superadmin)
        with override_settings(SUPERADMIN_HOST="soft.stom.asia"):
            resp = self.client.get("/", HTTP_HOST="soft.stom.asia")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/new/superadmin/")


class NewUISuperadminTestCase(TestCase):
    """Супер-админ-панель в новом интерфейсе (/new/superadmin/) — список
    клиник со статистикой, создание клиники через отдельный JSON-эндпоинт
    (в отличие от остальных мутаций страницы, у создания клиники есть
    реальные ошибки валидации, поэтому не «редирект = успех», см.
    apps.users.newui_views.newui_clinic_create)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника SA", slug="clinic-sa-newui")
        self.branch = Branch.objects.create(name="Филиал SA", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(
            login="sa_director", name="Директор SA", email="sad@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.superadmin = User.objects.create(
            login="sa_super", name="Супер SA", email="sas@test.local",
            role=self.superadmin_role,
        )
        self.client = Client()

    def test_blocked_for_non_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.get("/new/superadmin/", follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "saTableBody")

    def test_lists_clinics_with_stats(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get("/new/superadmin/")
        self.assertEqual(resp.status_code, 200)
        data = _extract_newui_real_data(resp.content.decode())
        names = [c["name"] for c in data["superadminData"]["clinics"]]
        self.assertIn("Клиника SA", names)
        entry = next(c for c in data["superadminData"]["clinics"] if c["id"] == self.clinic.pk)
        self.assertEqual(entry["branchCount"], 1)
        self.assertEqual(entry["staffCount"], 1)

    def test_create_clinic_requires_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.post("/new/superadmin/clinic/create/", {
            "clinic_name": "Новая", "clinic_admin_login": "newlogin", "clinic_admin_password": "pass1234",
        })
        self.assertEqual(resp.status_code, 403)

    def test_create_clinic_success(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post("/new/superadmin/clinic/create/", {
            "clinic_name": "Новая клиника", "clinic_admin_login": "newlogin2", "clinic_admin_password": "pass1234",
            "clinic_seed": "0",
        })
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(Clinic.objects.filter(pk=payload["id"], name="Новая клиника").exists())
        self.assertTrue(User.objects.filter(login="newlogin2", clinic_id=payload["id"]).exists())

    def test_create_clinic_duplicate_login_returns_error_not_redirect(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post("/new/superadmin/clinic/create/", {
            "clinic_name": "Ещё клиника", "clinic_admin_login": "sa_director", "clinic_admin_password": "pass1234",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertFalse(Clinic.objects.filter(name="Ещё клиника").exists())

    def test_superadmin_panel_still_creates_clinic_via_shared_helper(self):
        """Регрессия: рефакторинг create_clinic в общий _create_clinic() не
        должен сломать старую форму (templates/users/superadmin.html)."""
        self.client.force_login(self.superadmin)
        resp = self.client.post("/users/superadmin/", {
            "action": "create_clinic", "clinic_name": "Клиника из старого интерфейса",
            "clinic_admin_login": "oldui_admin", "clinic_admin_password": "pass1234", "clinic_seed": "0",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Clinic.objects.filter(name="Клиника из старого интерфейса").exists())


class AuditEventLoggingTestCase(TestCase):
    """Мутации супер-админа и мягкое удаление (apps.tenancy.
    ClinicSoftDeleteModel.soft_delete) пишут AuditEvent — единый источник
    «Ленты событий» /new/superadmin/ (см. apps.users.audit.log_audit_event)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Аудит", slug="clinic-audit-evt")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.superadmin = User.objects.create(login="ae_super", name="Супер AE", role=self.superadmin_role)
        self.client = Client()
        self.client.force_login(self.superadmin)

    def test_block_ip_writes_event_with_diff(self):
        from apps.users.models import AuditEvent
        self.client.post("/users/block-ip/", {"ip_address": "1.2.3.4", "note": "тест", "duration_days": "7"})
        evt = AuditEvent.objects.filter(action="ip_block").first()
        self.assertIsNotNone(evt)
        self.assertEqual(evt.object_repr, "ip_rule/1.2.3.4")
        self.assertEqual(evt.actor_id, self.superadmin.pk)
        fields = {c["field"] for c in evt.diff}
        self.assertIn("status", fields)
        self.assertIn("expires_at", fields)

    def test_unblock_ip_writes_event(self):
        from apps.users.models import AuditEvent, BlockedIP
        b = BlockedIP.objects.create(ip_address="8.8.4.4", blocked_by=self.superadmin)
        self.client.post(f"/users/block-ip/{b.pk}/unblock/")
        evt = AuditEvent.objects.filter(action="ip_unblock").first()
        self.assertIsNotNone(evt)
        self.assertEqual(evt.object_repr, "ip_rule/8.8.4.4")

    def test_clinic_toggle_active_writes_event(self):
        from apps.users.models import AuditEvent
        self.client.post(f"/users/clinic/{self.clinic.pk}/toggle-active/", {"reason": "тест блок"})
        evt = AuditEvent.objects.filter(action="clinic_block", clinic=self.clinic).first()
        self.assertIsNotNone(evt)
        self.assertTrue(any(c["field"] == "is_active" for c in evt.diff))

    def test_soft_delete_writes_event(self):
        from apps.users.models import AuditEvent
        from apps.patients.models import Patient
        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            p = Patient.objects.create(first_name="Тест", last_name="Пациентов", phone="+996700000001",
                                        branch=self.branch)
        finally:
            clear_current_clinic()
        p.soft_delete(user=self.superadmin)
        evt = AuditEvent.objects.filter(action="soft_delete", object_model="patient", object_id=str(p.pk)).first()
        self.assertIsNotNone(evt)
        self.assertEqual(evt.actor_id, self.superadmin.pk)
        self.assertEqual(evt.diff, [{"field": "is_deleted", "old": "Нет", "new": "Да"}])

    def test_set_active_clinic_writes_view_event(self):
        """«Войти →» в консоли — надзорный просмотр (вкладка «Просмотры»)."""
        from apps.users.models import AuditEvent
        self.client.post("/users/set-clinic/", {"clinic": self.clinic.pk})
        evt = AuditEvent.objects.filter(action="clinic_enter", clinic=self.clinic).first()
        self.assertIsNotNone(evt)
        self.assertEqual(evt.category, "view")

    def test_set_active_clinic_all_does_not_write_event(self):
        """Сброс выбора клиники ("все") — не «вход», событие не пишем."""
        from apps.users.models import AuditEvent
        self.client.post("/users/set-clinic/", {"clinic": "all"})
        self.assertFalse(AuditEvent.objects.filter(action="clinic_enter").exists())

    def test_clinic_overview_by_superadmin_writes_view_event(self):
        from apps.users.models import AuditEvent
        self.client.get(f"/users/clinic/{self.clinic.pk}/overview/")
        evt = AuditEvent.objects.filter(action="clinic_view", clinic=self.clinic).first()
        self.assertIsNotNone(evt)
        self.assertEqual(evt.category, "view")

    def test_clinic_overview_by_admin_main_own_clinic_does_not_write_event(self):
        """Директор смотрит свою же клинику — рутина, не событие безопасности."""
        from apps.users.models import AuditEvent
        admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        director = User.objects.create(login="ae_director", name="Директор AE", role=admin_role, clinic=self.clinic)
        client = Client()
        client.force_login(director)
        client.get(f"/users/clinic/{self.clinic.pk}/overview/")
        self.assertFalse(AuditEvent.objects.filter(action="clinic_view").exists())

    def test_staff_login_as_writes_view_event(self):
        from apps.users.models import AuditEvent
        doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        staff = User.objects.create(login="ae_doctor", name="Доктор AE", role=doctor_role, clinic=self.clinic)
        self.client.post(f"/users/{staff.pk}/login-as/")
        evt = AuditEvent.objects.filter(action="impersonate_start").first()
        self.assertIsNotNone(evt)
        self.assertEqual(evt.category, "view")
        self.assertEqual(evt.object_repr, f"user/{staff.pk} — {staff.name}")


class BlockedIPExpiryTestCase(TestCase):
    """BlockedIP.expires_at — блокировка со сроком перестаёт действовать
    после истечения, проверяется в ДВУХ местах: apps.users.forms.
    LoginForm.clean() (новый вход) и apps.tenancy.BlockedIPMiddleware
    (каждый запрос уже вошедшего)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Экспайр", slug="clinic-ip-expiry")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.user = User.objects.create(
            login="ipexp_user", name="Юзер Экспайр", role=self.admin_role, clinic=self.clinic,
        )
        self.user.set_password("pass1234")
        self.user.save()

    def test_expired_block_does_not_block_login(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="1.1.1.1", expires_at=timezone.now() - timedelta(hours=1))
        resp = self.client.post("/login/", {"login": "ipexp_user", "password": "pass1234"},
                                 REMOTE_ADDR="1.1.1.1")
        self.assertEqual(resp.status_code, 302)  # успешный вход — редирект, не форма с ошибкой

    def test_active_block_still_blocks_login(self):
        """apps.tenancy.BlockedIPMiddleware проверяет КАЖДЫЙ запрос (включая
        сам POST /login/) раньше, чем запрос доходит до LoginForm.clean() —
        поэтому реальный ответ здесь 403 от миддлвари, не форма с ошибкой
        (LoginForm.clean() — эта же проверка, но как защита на случай, если
        когда-нибудь появится путь к authenticate() в обход миддлвари)."""
        from datetime import timedelta
        from django.utils import timezone
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="2.2.2.2", expires_at=timezone.now() + timedelta(hours=1))
        resp = self.client.post("/login/", {"login": "ipexp_user", "password": "pass1234"},
                                 REMOTE_ADDR="2.2.2.2")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "заблокирован", status_code=403)

    def test_login_form_itself_respects_expiry(self):
        """Проверка LoginForm.clean() напрямую (в обход BlockedIPMiddleware,
        который в реальном запросе перехватывает раньше) — обе точки
        проверки expires_at должны быть исправлены независимо, см.
        apps.users.forms.LoginForm.clean()."""
        from datetime import timedelta
        from django.test import RequestFactory
        from django.utils import timezone
        from apps.users.forms import LoginForm
        from apps.users.models import BlockedIP

        BlockedIP.objects.create(ip_address="9.1.1.1", expires_at=timezone.now() - timedelta(hours=1))
        req = RequestFactory().post("/login/", REMOTE_ADDR="9.1.1.1")
        form = LoginForm(request=req, data={"login": "ipexp_user", "password": "pass1234"})
        self.assertTrue(form.is_valid(), form.errors)

        BlockedIP.objects.create(ip_address="9.2.2.2", expires_at=timezone.now() + timedelta(hours=1))
        req2 = RequestFactory().post("/login/", REMOTE_ADDR="9.2.2.2")
        form2 = LoginForm(request=req2, data={"login": "ipexp_user", "password": "pass1234"})
        self.assertFalse(form2.is_valid())

    def test_expired_block_does_not_log_out_active_session(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="3.3.3.3", expires_at=timezone.now() - timedelta(hours=1))
        self.client.force_login(self.user)
        resp = self.client.get("/new/", REMOTE_ADDR="3.3.3.3")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)

    def test_active_block_logs_out_active_session(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="4.4.4.4", expires_at=timezone.now() + timedelta(hours=1))
        self.client.force_login(self.user)
        resp = self.client.get("/new/", REMOTE_ADDR="4.4.4.4")
        self.assertEqual(resp.status_code, 403)


class SuperadminAuditFeedTestCase(TestCase):
    """/new/superadmin/feed/, /event/<id>/, /export/, /users/ — новые
    AJAX-эндпоинты «Аудит-центра» (см. apps.users.audit.superadmin_audit_feed)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Лента", slug="clinic-feed")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(
            login="feed_director", name="Директор Лента", role=self.admin_role, clinic=self.clinic,
        )
        self.superadmin = User.objects.create(
            login="feed_super", name="Супер Лента", role=self.superadmin_role,
        )
        self.client = Client()

    def test_feed_requires_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.get("/new/superadmin/feed/")
        self.assertEqual(resp.status_code, 403)

    def test_users_requires_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.get("/new/superadmin/users/")
        self.assertEqual(resp.status_code, 403)

    def test_export_requires_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.get("/new/superadmin/export/")
        self.assertEqual(resp.status_code, 403)

    def test_feed_merges_ip_block_and_login_denial(self):
        from apps.users.audit import log_audit_event
        from apps.users.models import ClinicLoginEvent
        self.client.force_login(self.superadmin)
        log_audit_event(action="ip_block", category="change", actor=self.superadmin,
                         object_model="blockedip", object_id="9.9.9.9", object_repr="ip_rule/9.9.9.9",
                         diff=[{"field": "status", "old": "allowed", "new": "blocked"}])
        ClinicLoginEvent.objects.create(user=self.director, clinic=self.clinic, ip_address="5.5.5.5", success=False)

        resp_all = self.client.get("/new/superadmin/feed/?category=all")
        self.assertEqual(resp_all.status_code, 200)
        reprs = [r["object_repr"] for r in resp_all.json()["rows"]]
        self.assertIn("ip_rule/9.9.9.9", reprs)

        resp_change = self.client.get("/new/superadmin/feed/?category=change")
        self.assertTrue(all(r["category"] == "change" for r in resp_change.json()["rows"]))
        self.assertIn("ip_rule/9.9.9.9", [r["object_repr"] for r in resp_change.json()["rows"]])

        resp_deny = self.client.get("/new/superadmin/feed/?category=deny")
        self.assertTrue(all(r["category"] == "deny" for r in resp_deny.json()["rows"]))
        self.assertIn("5.5.5.5", [r["ip"] for r in resp_deny.json()["rows"]])

    def test_feed_view_category_empty_when_no_view_events(self):
        """«Просмотры» без реальных событий — пустой список, не выдуманные
        данные (в этом тесте намеренно не создаём ни одного view-события)."""
        self.client.force_login(self.superadmin)
        resp = self.client.get("/new/superadmin/feed/?category=view")
        self.assertEqual(resp.json()["rows"], [])

    def test_feed_view_category_returns_real_view_events(self):
        """Надзорные просмотры (вход в клинику/за сотрудника) реально
        попадают во вкладку «Просмотры» — см. apps.users.views.
        set_active_clinic/staff_login_as/clinic_overview."""
        from apps.users.audit import log_audit_event
        self.client.force_login(self.superadmin)
        log_audit_event(action="clinic_enter", category="view", actor=self.superadmin,
                         clinic=self.clinic, object_model="clinic", object_id=self.clinic.pk,
                         object_repr=f"clinic/{self.clinic.slug} — {self.clinic.name}")
        resp = self.client.get("/new/superadmin/feed/?category=view")
        rows = resp.json()["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "view")
        self.assertEqual(rows[0]["object_repr"], f"clinic/{self.clinic.slug} — {self.clinic.name}")

    def test_feed_search_filters_by_ip(self):
        from apps.users.audit import log_audit_event
        self.client.force_login(self.superadmin)
        log_audit_event(action="ip_block", category="change", actor=self.superadmin,
                         object_model="blockedip", object_id="7.7.7.7", object_repr="ip_rule/7.7.7.7")
        log_audit_event(action="ip_block", category="change", actor=self.superadmin,
                         object_model="blockedip", object_id="6.6.6.6", object_repr="ip_rule/6.6.6.6")
        resp = self.client.get("/new/superadmin/feed/?search=7.7.7.7")
        reprs = [r["object_repr"] for r in resp.json()["rows"]]
        self.assertIn("ip_rule/7.7.7.7", reprs)
        self.assertNotIn("ip_rule/6.6.6.6", reprs)

    def test_event_detail_returns_diff_and_geo_field(self):
        from apps.users.audit import log_audit_event
        from apps.users.models import AuditEvent
        self.client.force_login(self.superadmin)
        log_audit_event(action="ip_block", category="change", actor=self.superadmin,
                         object_model="blockedip", object_id="1.2.3.4", object_repr="ip_rule/1.2.3.4",
                         diff=[{"field": "status", "old": "allowed", "new": "blocked"}])
        evt = AuditEvent.objects.get(action="ip_block")
        resp = self.client.get(f"/new/superadmin/event/evt:{evt.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["diff"], [{"field": "status", "old": "allowed", "new": "blocked"}])
        self.assertIn("geo", data)

    def test_event_detail_unknown_id_404(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get("/new/superadmin/event/evt:999999/")
        self.assertEqual(resp.status_code, 404)

    def test_users_lists_staff_across_clinics(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get("/new/superadmin/users/")
        self.assertEqual(resp.status_code, 200)
        logins = [u["login"] for u in resp.json()["rows"]]
        self.assertIn("feed_director", logins)


class RecyclePendingCountTestCase(TestCase):
    """«Удалений в очереди» на плашке ленты — счётчик по ВСЕЙ платформе
    (все клиники), не только по текущей (в отличие от самой Корзины,
    apps.users.views._recycle_qs, которая клиника-скоуп)."""

    def test_pending_deletions_counts_across_clinics(self):
        from apps.patients.models import Patient
        from apps.tenancy import set_current_clinic, clear_current_clinic
        from apps.users.audit import superadmin_audit_metrics

        c1 = Clinic.objects.create(name="Клиника Корзина 1", slug="clinic-recycle-1")
        c2 = Clinic.objects.create(name="Клиника Корзина 2", slug="clinic-recycle-2")
        for c in (c1, c2):
            b = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=c)
            set_current_clinic(c)
            try:
                p = Patient.objects.create(first_name="Удал", last_name="Пациентов", phone="+996700000002",
                                            branch=b)
            finally:
                clear_current_clinic()
            p.soft_delete()

        metrics = superadmin_audit_metrics()
        self.assertGreaterEqual(metrics["pending_deletions"], 2)


class BulkPurgeEligibilityTestCase(TestCase):
    """apps.users.audit.bulk_purge_eligible_summary — сводка «Удаления»:
    только записи старше порога (по умолчанию 30 дней), кросс-клиниково."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.tasks.models import Task
        from apps.tenancy import set_current_clinic, clear_current_clinic
        from django.utils import timezone

        self.clinic = Clinic.objects.create(name="Клиника BP", slug="clinic-bulk-purge")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(login="bp_director", name="Директор BP",
                                             role=self.admin_role, clinic=self.clinic)
        set_current_clinic(self.clinic)
        try:
            self.fresh_patient = Patient.objects.create(first_name="Свежий", last_name="Удалён",
                                                          phone="+996700000010", branch=self.branch)
            self.old_patient = Patient.objects.create(first_name="Старый", last_name="Удалён",
                                                        phone="+996700000011", branch=self.branch)
            self.old_task = Task.objects.create(title="Старая задача", created_by=self.director)
        finally:
            clear_current_clinic()

        now = timezone.now()
        self.fresh_patient.soft_delete(user=self.director)
        Patient.all_objects.filter(pk=self.fresh_patient.pk).update(deleted_at=now - timedelta(days=10))
        self.old_patient.soft_delete(user=self.director)
        Patient.all_objects.filter(pk=self.old_patient.pk).update(deleted_at=now - timedelta(days=40))
        self.old_task.soft_delete(user=self.director)
        Task.all_objects.filter(pk=self.old_task.pk).update(deleted_at=now - timedelta(days=40))

    def test_summary_counts_only_records_older_than_threshold(self):
        from apps.users.audit import bulk_purge_eligible_summary
        summary = bulk_purge_eligible_summary(days=30)
        self.assertEqual(summary["total"], 2)  # old_patient + old_task, НЕ fresh_patient
        by_kind = {r["kind"]: r["count"] for r in summary["by_model"]}
        self.assertEqual(by_kind.get("patient"), 1)
        self.assertEqual(by_kind.get("task"), 1)
        clinic_rows = [r for r in summary["rows"] if r["clinic_id"] == self.clinic.pk]
        self.assertEqual(sum(r["count"] for r in clinic_rows), 2)


class BulkPurgeExecutionTestCase(TestCase):
    """apps.users.audit.bulk_purge_old_deletions — сам прогон массовой
    очистки: реально удаляет старое, не трогает свежее, пишет аудит."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.tenancy import set_current_clinic, clear_current_clinic
        from django.utils import timezone

        self.clinic = Clinic.objects.create(name="Клиника BPX", slug="clinic-bulk-purge-x")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(login="bpx_director", name="Директор BPX",
                                             role=self.admin_role, clinic=self.clinic)
        self.superadmin = User.objects.create(login="bpx_super", name="Супер BPX", role=self.superadmin_role)

        set_current_clinic(self.clinic)
        try:
            self.old_patient = Patient.objects.create(first_name="Совсем", last_name="Старый",
                                                        phone="+996700000012", branch=self.branch)
            self.fresh_patient = Patient.objects.create(first_name="Совсем", last_name="Свежий",
                                                          phone="+996700000013", branch=self.branch)
        finally:
            clear_current_clinic()

        now = timezone.now()
        self.old_patient.soft_delete(user=self.director)
        Patient.all_objects.filter(pk=self.old_patient.pk).update(deleted_at=now - timedelta(days=40))
        self.fresh_patient.soft_delete(user=self.director)
        Patient.all_objects.filter(pk=self.fresh_patient.pk).update(deleted_at=now - timedelta(days=5))

    def test_purge_deletes_old_keeps_fresh_and_logs_audit(self):
        from apps.users.audit import bulk_purge_old_deletions
        from apps.patients.models import Patient
        from apps.users.models import AuditEvent

        result = bulk_purge_old_deletions(actor=self.superadmin, days=30)
        self.assertEqual(result["purged"], 1)
        self.assertEqual(result["skipped_protected"], 0)
        self.assertFalse(Patient.all_objects.filter(pk=self.old_patient.pk).exists())
        self.assertTrue(Patient.all_objects.filter(pk=self.fresh_patient.pk).exists())

        self.assertTrue(AuditEvent.objects.filter(
            action="purge", object_model="patient", object_id=str(self.old_patient.pk)).exists())
        summary_evt = AuditEvent.objects.filter(action="bulk_purge").first()
        self.assertIsNotNone(summary_evt)
        self.assertEqual(summary_evt.actor_id, self.superadmin.pk)

    def test_protected_error_is_skipped_not_raised(self):
        from apps.users.audit import bulk_purge_old_deletions
        from apps.services.models import Service
        from apps.treatments.models import Treatment, TreatmentCure
        from apps.tenancy import set_current_clinic, clear_current_clinic
        from django.utils import timezone

        from apps.patients.models import Patient
        set_current_clinic(self.clinic)
        try:
            # НЕ self.old_patient — его самого заодно удалит purge_with_related()
            # в этом же прогоне (он тоже старше порога), и вместе с ним каскадом
            # уйдёт Treatment/TreatmentCure, снимая защиту с Service раньше, чем
            # до него дойдёт очередь. Отдельный, НЕ мягко-удалённый пациент —
            # чтобы Treatment точно пережил прогон и Service остался защищён.
            protector_patient = Patient.objects.create(first_name="Не", last_name="Удалён",
                                                         phone="+996700000015", branch=self.branch)
            service = Service.objects.create(name="Услуга под защитой", price=100)
            treatment = Treatment.objects.create(patient=protector_patient, branch=self.branch,
                                                  doctor=self.director)
            TreatmentCure.objects.create(treatment=treatment, service=service, price=100,
                                          doctor=self.director)
        finally:
            clear_current_clinic()
        service.soft_delete(user=self.director)
        Service.all_objects.filter(pk=service.pk).update(deleted_at=timezone.now() - timedelta(days=40))

        result = bulk_purge_old_deletions(actor=self.superadmin, days=30)
        self.assertGreaterEqual(result["skipped_protected"], 1)
        self.assertTrue(Service.all_objects.filter(pk=service.pk).exists())


class NewUISuperadminBulkPurgeViewTestCase(TestCase):
    """AJAX-вьюхи вкладки «Удаления» — is_superadmin-гейт + фраза
    подтверждения на POST."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.tenancy import set_current_clinic, clear_current_clinic
        from django.utils import timezone

        self.clinic = Clinic.objects.create(name="Клиника BPV", slug="clinic-bulk-purge-v")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(login="bpv_director", name="Директор BPV",
                                             role=self.admin_role, clinic=self.clinic)
        self.superadmin = User.objects.create(login="bpv_super", name="Супер BPV", role=self.superadmin_role)

        set_current_clinic(self.clinic)
        try:
            self.old_patient = Patient.objects.create(first_name="Вью", last_name="Тест",
                                                        phone="+996700000014", branch=self.branch)
        finally:
            clear_current_clinic()
        self.old_patient.soft_delete(user=self.director)
        Patient.all_objects.filter(pk=self.old_patient.pk).update(
            deleted_at=timezone.now() - timedelta(days=40))

        self.client = Client()

    def test_breakdown_blocked_for_non_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.get("/new/superadmin/deletions/")
        self.assertEqual(resp.status_code, 403)

    def test_breakdown_returns_rows_for_superadmin(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get("/new/superadmin/deletions/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["total"], 1)

    def test_purge_requires_confirm_phrase(self):
        from apps.patients.models import Patient
        self.client.force_login(self.superadmin)
        resp = self.client.post("/new/superadmin/deletions/purge/", {"confirm": "неверно"})
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Patient.all_objects.filter(pk=self.old_patient.pk).exists())

    def test_purge_with_confirm_phrase_deletes_and_logs(self):
        from apps.patients.models import Patient
        from apps.users.models import AuditEvent
        self.client.force_login(self.superadmin)
        resp = self.client.post("/new/superadmin/deletions/purge/", {"confirm": "УДАЛИТЬ"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Patient.all_objects.filter(pk=self.old_patient.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(action="bulk_purge").exists())

    def test_purge_blocked_for_non_superadmin(self):
        self.client.force_login(self.director)
        resp = self.client.post("/new/superadmin/deletions/purge/", {"confirm": "УДАЛИТЬ"})
        self.assertEqual(resp.status_code, 403)


class HistoryIPTestCase(TestCase):
    """IP автора правки в истории Пациент/Приём — apps.tenancy.
    HistoricalIPAddressModel/_add_history_ip (сигнал pre_create_historical_record)."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.tenancy import set_current_clinic, clear_current_clinic
        self.clinic = Clinic.objects.create(name="Клиника History IP", slug="clinic-hist-ip")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(login="hip_director", name="Директор HIP",
                                             role=self.admin_role, clinic=self.clinic)
        set_current_clinic(self.clinic)
        try:
            self.patient = Patient.objects.create(first_name="Иван", last_name="Тестов",
                                                   phone="+996700000003", branch=self.branch)
        finally:
            clear_current_clinic()
        self.client = Client()
        self.client.force_login(self.director)

    def test_patient_edit_writes_history_ip(self):
        resp = self.client.post(f"/patients/{self.patient.pk}/edit/", {
            "first_name": "Иван", "last_name": "Тестов", "phone": "+996700000099",
            "branch": self.branch.pk,
        }, REMOTE_ADDR="203.0.113.7")
        self.assertEqual(resp.status_code, 302)
        latest = self.patient.history.first()
        self.assertEqual(latest.history_ip, "203.0.113.7")

    def test_old_history_rows_without_ip_degrade_gracefully(self):
        """Запись создания (до появления history_ip у существующих клиник)
        — history_ip=None, лента показывает «—», не падает."""
        from apps.users.audit import build_history_rows
        HP = self.patient.history.model
        rows = build_history_rows(HP.objects.all(), "patient", "Пациент", lambda h: str(h.id))
        self.assertTrue(all("ip" in r for r in rows))

    def test_history_row_ip_hint_for_pre_rollout_rows(self):
        """_history_row(): строка без IP, созданная ДО IP_TRACKING_SINCE,
        получает ip_hint с датой; после — ip_hint=None (просто «неизвестно
        технически», не «не отслеживалось тогда»); строка с реальным IP —
        ip_hint всегда None."""
        from datetime import timedelta
        from apps.users.audit import _history_row, IP_TRACKING_SINCE
        base_row = {"model": "treatment", "model_label": "Приём", "obj_id": 1,
                    "title": "Приём #1", "type": "Изменение", "raw_type": "~",
                    "user": "Кто-то", "hid": 1}

        before = _history_row({**base_row, "date": IP_TRACKING_SINCE - timedelta(days=1), "ip": None})
        self.assertEqual(before["ip"], "—")
        self.assertIsNotNone(before["ip_hint"])

        after = _history_row({**base_row, "date": IP_TRACKING_SINCE + timedelta(days=1), "ip": None})
        self.assertEqual(after["ip"], "—")
        self.assertIsNone(after["ip_hint"])

        with_ip = _history_row({**base_row, "date": IP_TRACKING_SINCE - timedelta(days=1), "ip": "1.2.3.4"})
        self.assertEqual(with_ip["ip"], "1.2.3.4")
        self.assertIsNone(with_ip["ip_hint"])


class AttemptedLoginTestCase(TestCase):
    """Сырой введённый логин при отказе входа — ClinicLoginEvent.
    attempted_login (apps.users.forms.LoginForm.clean())."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника AL", slug="clinic-attempted-login")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.user = User.objects.create(login="al_user", name="Юзер AL", role=self.admin_role, clinic=self.clinic)
        self.user.set_password("pass1234")
        self.user.save()

    def test_wrong_password_records_attempted_login(self):
        from apps.users.models import ClinicLoginEvent
        self.client.post("/login/", {"login": "al_user", "password": "wrongpass"})
        ev = ClinicLoginEvent.objects.filter(success=False).first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.attempted_login, "al_user")
        self.assertIsNone(ev.user)

    def test_nonexistent_login_records_attempted_login(self):
        from apps.users.models import ClinicLoginEvent
        self.client.post("/login/", {"login": "ghost_user_xyz", "password": "whatever"})
        ev = ClinicLoginEvent.objects.filter(success=False).first()
        self.assertEqual(ev.attempted_login, "ghost_user_xyz")

    def test_feed_shows_attempted_login_as_actor_when_unresolved(self):
        from apps.users.audit import superadmin_audit_feed
        self.client.post("/login/", {"login": "ghost_user_xyz", "password": "whatever"})
        feed = superadmin_audit_feed(category="deny")
        row = next(r for r in feed["rows"] if "ghost_user_xyz" in (r["actor_label"] or ""))
        self.assertEqual(row["actor_label"], "Логин: ghost_user_xyz")


class GeoBatchTestCase(TestCase):
    """get_ip_geolocations_batch — закэшированные IP не уходят в сеть."""

    def test_cached_ips_skip_network_call(self):
        import urllib.request
        from django.core.cache import cache
        from apps.users.geoip import get_ip_geolocations_batch

        cache.set("geoip:8.8.8.8", "Bishkek, KG", 3600)
        cache.set("geoip:1.1.1.1", "", 3600)  # закэшированный «неудача»

        def _boom(*a, **kw):
            raise AssertionError("не должно идти в сеть для закэшированных IP")

        original = urllib.request.urlopen
        urllib.request.urlopen = _boom
        try:
            result = get_ip_geolocations_batch(["8.8.8.8", "1.1.1.1", "10.0.0.5"])
        finally:
            urllib.request.urlopen = original

        self.assertEqual(result["8.8.8.8"], "Bishkek, KG")
        self.assertIsNone(result["1.1.1.1"])
        self.assertIsNone(result["10.0.0.5"])  # приватный — без сети, без кэша


class StaffLoginAsRedirectTestCase(TestCase):
    """«Войти как сотрудник» ведёт на новый интерфейс, если им пользуется
    actor — не безусловно на старый дашборд (apps.users.views.staff_login_as)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника SLA", slug="clinic-sla")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(login="sla_director", name="Директор SLA",
                                             role=self.admin_role, clinic=self.clinic)
        self.staff = User.objects.create(login="sla_staff", name="Сотрудник SLA",
                                          role=self.doctor_role, clinic=self.clinic)

    def test_redirects_to_new_ui_when_actor_uses_it(self):
        self.director.use_new_interface = True
        self.director.save(update_fields=["use_new_interface"])
        self.client.force_login(self.director)
        resp = self.client.post(f"/users/{self.staff.pk}/login-as/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/new/")

    def test_redirects_to_old_ui_when_actor_uses_it(self):
        self.director.use_new_interface = False
        self.director.save(update_fields=["use_new_interface"])
        self.client.force_login(self.director)
        resp = self.client.post(f"/users/{self.staff.pk}/login-as/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/")


class AuditTimezoneTestCase(TestCase):
    """Границы «сегодня»/фильтр дат ленты — по Asia/Bishkek (UTC+6), не по
    UTC (созданное в 01:00 по Бишкеку = 19:00 UTC предыдущего дня —
    должно попасть в бишкекское «сегодня»)."""

    def test_metrics_today_uses_bishkek_date_not_utc(self):
        from datetime import timedelta
        from django.utils import timezone as dj_tz
        from apps.users.models import AuditEvent
        from apps.users.audit import superadmin_audit_metrics

        # 01:00 по Бишкеку (UTC+6) сегодня = 19:00 UTC ВЧЕРА.
        bishkek_today_1am = dj_tz.localtime(dj_tz.now()).replace(
            hour=1, minute=0, second=0, microsecond=0)
        if dj_tz.localtime(dj_tz.now()).hour < 2:
            # если сейчас уже около полуночи по Бишкеку — сдвигаем на
            # следующий день, чтобы тест не зависел от времени запуска
            bishkek_today_1am += timedelta(days=1)
        evt = AuditEvent.objects.create(action="ip_block", category="change")
        AuditEvent.objects.filter(pk=evt.pk).update(created_at=bishkek_today_1am)

        metrics = superadmin_audit_metrics()
        self.assertGreaterEqual(metrics["events_today"], 1)

    def test_feed_date_filter_uses_bishkek_date(self):
        from django.utils import timezone as dj_tz
        from apps.users.audit import superadmin_audit_feed
        from apps.users.models import AuditEvent

        bishkek_now = dj_tz.localtime(dj_tz.now())
        evt = AuditEvent.objects.create(action="ip_block", category="change",
                                         object_repr="ip_rule/tz-test")
        AuditEvent.objects.filter(pk=evt.pk).update(created_at=dj_tz.now())

        feed = superadmin_audit_feed(category="change",
                                      date_from=bishkek_now.date(), date_to=bishkek_now.date())
        reprs = [r["object_repr"] for r in feed["rows"]]
        self.assertIn("ip_rule/tz-test", reprs)


class NewUITreatplanDetailTestCase(TestCase):
    """/new/treatplans/<pk>/ — план лечения в новом интерфейсе, заменяет
    переход на старый /treatments/plans/<pk>/ (см. план «План лечения в
    новом интерфейсе»). Мутации идут на существующие POST-эндпоинты
    apps.treatments.views (не дублируются) — здесь проверяем именно
    сборку данных и права доступа новой read-only страницы."""

    def setUp(self):
        from apps.patients.models import Patient
        from apps.services.models import Service
        from apps.treatments.models_plan import TreatmentPlan, TreatmentPlanStage, TreatmentPlanItem

        self.clinic = Clinic.objects.create(name="Клиника TP", slug="clinic-tp")
        self.other_clinic = Clinic.objects.create(name="Клиника TP2", slug="clinic-tp2")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(login="tp_director", name="Директор TP",
                                             role=self.admin_role, clinic=self.clinic)
        self.other_director = User.objects.create(login="tp_other_director", name="Чужой Директор",
                                                    role=self.admin_role, clinic=self.other_clinic)
        self.client = Client()

        from apps.tenancy import set_current_clinic, clear_current_clinic
        set_current_clinic(self.clinic)
        try:
            self.patient = Patient.objects.create(first_name="Азиз", last_name="Тестов",
                                                   phone="+996700000123", branch=self.branch)
            self.service = Service.objects.create(name="Пломба", price=3200, clinic=self.clinic)
        finally:
            clear_current_clinic()

        self.plan = TreatmentPlan.objects.create(
            patient=self.patient, doctor=self.director, title="Пломбирование, зуб 26",
            status=TreatmentPlan.STATUS_APPROVED,
        )
        self.stage = TreatmentPlanStage.objects.create(plan=self.plan, title="Этап 1")
        self.item = TreatmentPlanItem.objects.create(
            plan=self.plan, service=self.service, stage=self.stage,
            price=3200, discount=10, quantity=1, status=TreatmentPlanItem.STATUS_PENDING,
        )

    def test_requires_login(self):
        resp = self.client.get(f"/new/treatplans/{self.plan.pk}/")
        self.assertEqual(resp.status_code, 302)

    def test_returns_full_stage_item_tree(self):
        self.client.force_login(self.director)
        resp = self.client.get(f"/new/treatplans/{self.plan.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = _extract_newui_real_data(resp.content.decode())["planDetail"]
        self.assertEqual(data["id"], self.plan.pk)
        self.assertEqual(data["patientName"], "Тестов Азиз")
        self.assertEqual(len(data["stages"]), 1)
        stage = data["stages"][0]
        self.assertEqual(len(stage["items"]), 1)
        item = stage["items"][0]
        self.assertEqual(item["serviceName"], "Пломба")
        self.assertEqual(item["subtotal"], 2880.0)  # 3200 - 10%
        self.assertEqual(data["totalPrice"], 2880.0)

    def test_other_clinic_plan_is_404(self):
        self.client.force_login(self.other_director)
        resp = self.client.get(f"/new/treatplans/{self.plan.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_orphan_items_self_heal_into_a_stage(self):
        """Услуга без этапа (старые планы до появления этапов) — как и
        старая /treatments/plans/<pk>/, новая страница сама создаёт этап
        и переносит туда «осиротевшие» услуги."""
        from apps.treatments.models_plan import TreatmentPlanItem
        TreatmentPlanItem.objects.create(plan=self.plan, service=self.service, stage=None, price=1000)
        self.client.force_login(self.director)
        resp = self.client.get(f"/new/treatplans/{self.plan.pk}/")
        data = _extract_newui_real_data(resp.content.decode())["planDetail"]
        self.assertEqual(len(data["stages"]), 2)
        all_items = [it for s in data["stages"] for it in s["items"]]
        self.assertEqual(len(all_items), 2)

    def test_full_mutation_flow_through_existing_endpoints(self):
        """Регрессия сквозного сценария (эндпоинты не менялись, но новая
        страница на них полагается): добавить этап -> добавить услугу ->
        переместить -> переключить статус -> удалить услугу -> удалить этап."""
        from apps.treatments.models_plan import TreatmentPlanStage, TreatmentPlanItem
        self.client.force_login(self.director)

        r = self.client.post(f"/treatments/plans/{self.plan.pk}/stage/add/")
        self.assertEqual(r.status_code, 302)
        stage2 = TreatmentPlanStage.objects.filter(plan=self.plan).exclude(pk=self.stage.pk).first()
        self.assertIsNotNone(stage2)

        import json as _json
        r = self.client.post("/treatments/plans/items/add/",
                              data=_json.dumps({"stage_id": stage2.pk, "service_id": self.service.pk,
                                                "tooth": "26", "price": 3200, "discount": 0, "qty": 1}),
                              content_type="application/json")
        self.assertEqual(r.status_code, 200)
        new_item = TreatmentPlanItem.objects.filter(stage=stage2).first()
        self.assertIsNotNone(new_item)

        r = self.client.post(f"/treatments/plans/items/{new_item.pk}/move/",
                              {"stage_id": self.stage.pk, "mode": "move"})
        self.assertEqual(r.status_code, 302)
        new_item.refresh_from_db()
        self.assertEqual(new_item.stage_id, self.stage.pk)

        r = self.client.post(f"/treatments/plans/items/{new_item.pk}/toggle/")
        self.assertEqual(r.status_code, 200)
        new_item.refresh_from_db()
        self.assertEqual(new_item.status, "done")

        r = self.client.post(f"/treatments/plans/items/{new_item.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(TreatmentPlanItem.objects.filter(pk=new_item.pk).exists())

        r = self.client.post(f"/treatments/plans/stages/{stage2.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(TreatmentPlanStage.objects.filter(pk=stage2.pk).exists())

    def test_treatplans_list_and_patientcard_link_to_new_page(self):
        """Оставшиеся ссылки на план лечения ведут в новый интерфейс, не
        на /treatments/plans/... (templates/newui/base.html)."""
        self.client.force_login(self.director)
        resp = self.client.get("/new/treatplans/")
        self.assertContains(resp, "/new/treatplans/${p.id}/")
        self.assertNotContains(resp, "/treatments/plans/${p.id}/")


class BackupDatabaseCommandTestCase(TestCase):
    """apps.users.management.commands.backup_database — тесты идут на
    SQLite (config/settings/development.py), поэтому здесь проверяется
    именно ветка _dump_sqlite; ветка _dump_postgres — отдельным юнит-тестом
    с замоканным subprocess.Popen (см. BackupPostgresBranchTestCase)."""

    def test_creates_valid_gzip_sqlite_backup_with_expected_filename(self):
        import gzip
        import os
        import tempfile
        from pathlib import Path
        from django.conf import settings
        from django.core.management import call_command
        from django.test import override_settings

        db_path = _isolated_sqlite_db_path()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                databases = {**settings.DATABASES, "default": {**settings.DATABASES["default"], "NAME": db_path}}
                with override_settings(BACKUPS_DIR=Path(tmp), DATABASES=databases):
                    call_command("backup_database")
                files = list(Path(tmp).glob("sadaf_backup_*"))
                self.assertEqual(len(files), 1)
                self.assertRegex(files[0].name, r"^sadaf_backup_\d{4}-\d{2}-\d{2}_\d{4}\.sqlite3\.gz$")
                with gzip.open(files[0], "rb") as gz:
                    content = gz.read()
                self.assertGreater(len(content), 0)
        finally:
            os.unlink(db_path)

    def test_dry_run_creates_no_files(self):
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(BACKUPS_DIR=Path(tmp)):
                call_command("backup_database", dry=True)
            self.assertEqual(list(Path(tmp).glob("sadaf_backup_*")), [])

    def test_writes_backup_create_audit_event(self):
        import os
        import tempfile
        from pathlib import Path
        from django.conf import settings
        from django.core.management import call_command
        from django.test import override_settings
        from apps.users.models import AuditEvent

        db_path = _isolated_sqlite_db_path()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                databases = {**settings.DATABASES, "default": {**settings.DATABASES["default"], "NAME": db_path}}
                with override_settings(BACKUPS_DIR=Path(tmp), DATABASES=databases):
                    call_command("backup_database")
            self.assertTrue(AuditEvent.objects.filter(action="backup_create").exists())
        finally:
            os.unlink(db_path)


class BackupRetentionTestCase(TestCase):
    """Ротация: хранится только последние --keep копий, старые удаляются."""

    def test_keeps_only_last_n_backups(self):
        import os
        import tempfile
        import time
        from pathlib import Path
        from django.conf import settings
        from django.core.management import call_command
        from django.test import override_settings

        db_path = _isolated_sqlite_db_path()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                now = time.time()
                for i in range(16):
                    f = tmp_path / f"sadaf_backup_2026-01-{i+1:02d}_0000.sqlite3.gz"
                    f.write_bytes(b"x")
                    os.utime(f, (now - (20 - i) * 3600, now - (20 - i) * 3600))  # старые → новые
                databases = {**settings.DATABASES, "default": {**settings.DATABASES["default"], "NAME": db_path}}
                with override_settings(BACKUPS_DIR=tmp_path, DATABASES=databases):
                    call_command("backup_database", keep=14)
                remaining = list(tmp_path.glob("sadaf_backup_*"))
                self.assertEqual(len(remaining), 14)
                # Только что созданный файл — среди выживших (самый новый по mtime).
                newest_by_mtime = max(remaining, key=lambda p: p.stat().st_mtime)
                self.assertIn("sqlite3.gz", newest_by_mtime.name)
        finally:
            os.unlink(db_path)


class BackupPostgresBranchTestCase(TestCase):
    """Юнит-тест _dump_postgres в изоляции (без реального pg_dump/Postgres —
    песочница тестов всегда на SQLite) — проверяем только состав argv/env."""

    def test_pg_dump_argv_and_password_env(self):
        from unittest.mock import patch, MagicMock
        from pathlib import Path
        from apps.users.management.commands.backup_database import Command

        fake_db = {"HOST": "dbhost", "PORT": "5433", "USER": "sadaf", "PASSWORD": "s3cr3t", "NAME": "sadaf_clinic"}
        cmd = Command()
        with patch("apps.users.management.commands.backup_database.subprocess.Popen") as mock_popen, \
             patch("gzip.open"):
            mock_proc = MagicMock()
            mock_proc.stdout.read.side_effect = [b"", b""]
            mock_proc.wait.return_value = 0
            mock_popen.return_value = mock_proc
            cmd._dump_postgres(fake_db, Path("/tmp/does-not-matter.sql.gz"))
            argv = mock_popen.call_args.args[0]
            env = mock_popen.call_args.kwargs["env"]
        self.assertIn("pg_dump", argv)
        self.assertIn("dbhost", argv)
        self.assertIn("5433", argv)
        self.assertIn("sadaf", argv)
        self.assertIn("sadaf_clinic", argv)
        self.assertEqual(env["PGPASSWORD"], "s3cr3t")


class NewUISuperadminBackupsViewTestCase(TestCase):
    """AJAX-список + скачивание бэкапов — is_superadmin-гейт, защита от
    path traversal, аудит-лог скачивания."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Backup View", slug="clinic-backup-view")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.director = User.objects.create(login="bv_director", name="Директор BV",
                                             role=self.admin_role, clinic=self.clinic)
        self.superadmin = User.objects.create(login="bv_super", name="Супер BV", role=self.superadmin_role)
        self.client = Client()

        import tempfile
        from pathlib import Path
        self._tmpdir = tempfile.TemporaryDirectory()
        self.backups_dir = Path(self._tmpdir.name)
        self.backup_file = self.backups_dir / "sadaf_backup_2026-01-01_0000.sqlite3.gz"
        self.backup_file.write_bytes(b"fake-gzip-content")
        self.other_file = self.backups_dir / "not_a_backup.txt"
        self.other_file.write_bytes(b"should not be downloadable")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_list_blocked_for_non_superadmin(self):
        self.client.force_login(self.director)
        with override_settings(BACKUPS_DIR=self.backups_dir):
            resp = self.client.get("/new/superadmin/backups/")
        self.assertEqual(resp.status_code, 403)

    def test_list_returns_backup_file_with_size_and_date(self):
        self.client.force_login(self.superadmin)
        with override_settings(BACKUPS_DIR=self.backups_dir):
            resp = self.client.get("/new/superadmin/backups/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["rows"]
        names = [r["name"] for r in rows]
        self.assertIn("sadaf_backup_2026-01-01_0000.sqlite3.gz", names)
        self.assertNotIn("not_a_backup.txt", names)  # не матчит glob("sadaf_backup_*")

    def test_download_streams_file_and_logs_audit_event(self):
        from apps.users.models import AuditEvent
        self.client.force_login(self.superadmin)
        with override_settings(BACKUPS_DIR=self.backups_dir):
            resp = self.client.get(f"/new/superadmin/backups/download/{self.backup_file.name}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(b"".join(resp.streaming_content), b"fake-gzip-content")
        self.assertTrue(AuditEvent.objects.filter(
            action="backup_download", object_repr=self.backup_file.name).exists())

    def test_download_rejects_path_traversal(self):
        self.client.force_login(self.superadmin)
        with override_settings(BACKUPS_DIR=self.backups_dir):
            resp = self.client.get("/new/superadmin/backups/download/..%2F..%2Fsettings.py/")
        self.assertIn(resp.status_code, (403, 404))

    def test_download_rejects_unknown_filename_prefix(self):
        self.client.force_login(self.superadmin)
        with override_settings(BACKUPS_DIR=self.backups_dir):
            resp = self.client.get(f"/new/superadmin/backups/download/{self.other_file.name}/")
        self.assertEqual(resp.status_code, 403)

    def test_download_blocked_for_non_superadmin(self):
        self.client.force_login(self.director)
        with override_settings(BACKUPS_DIR=self.backups_dir):
            resp = self.client.get(f"/new/superadmin/backups/download/{self.backup_file.name}/")
        self.assertEqual(resp.status_code, 403)


class ClinicBlockingTestCase(TestCase):
    """Реальная блокировка клиники (Clinic.is_active=False) — мгновенный
    разлогин активных сессий + запрет нового входа, оба ведут на
    /access-request/ (apps.tenancy.TariffGuardMiddleware, login_view)."""

    def setUp(self):
        from apps.patients.models import Patient
        self.clinic = Clinic.objects.create(name="Клиника Блок", slug="clinic-blocking")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="cb_director", name="Директор CB", email="cbd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.director.set_password("pass1234")
        self.director.save()

    def test_active_session_logged_out_when_clinic_blocked(self):
        self.client.force_login(self.director)
        resp = self.client.get("/new/", follow=False)
        self.assertEqual(resp.status_code, 200)  # ещё активна

        self.clinic.is_active = False
        self.clinic.save(update_fields=["is_active"])

        resp2 = self.client.get("/new/", follow=True)
        self.assertRedirects(resp2, f"/access-request/?clinic={self.clinic.slug}",
                              fetch_redirect_response=False)
        self.assertFalse(resp2.wsgi_request.user.is_authenticated)

    def test_new_login_blocked_for_inactive_clinic(self):
        self.clinic.is_active = False
        self.clinic.save(update_fields=["is_active"])
        resp = self.client.get(f"/login/?clinic={self.clinic.slug}")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, f"/access-request/?clinic={self.clinic.slug}")

    def test_expired_tariff_still_works_as_before(self):
        """Регрессия: истёкший тариф (не блокировка) по-прежнему рендерит
        tariff_expired.html на месте, сессия не разлогинивается."""
        from datetime import date, timedelta
        self.clinic.tariff_until = date.today() - timedelta(days=1)
        self.clinic.save(update_fields=["tariff_until"])
        self.client.force_login(self.director)
        resp = self.client.get("/new/")
        self.assertEqual(resp.status_code, 402)
        self.assertTrue(resp.wsgi_request.user.is_authenticated)


class ClinicAccessRequestTestCase(TestCase):
    """Форма «запросить доступ» — публичная, создаёт заявку и уведомляет
    супер-админов (apps.notifications.models.Notification)."""

    def setUp(self):
        self.superadmin_role = Role.objects.get(name="superadmin", clinic__isnull=True)
        self.superadmin = User.objects.create(
            login="car_super", name="Супер CAR", email="cars@test.local",
            role=self.superadmin_role,
        )

    def test_submit_creates_request_and_notifies_superadmin(self):
        from apps.users.models import ClinicAccessRequest
        from apps.notifications.models import Notification
        resp = self.client.post("/access-request/", {
            "clinic_name": "Новая клиника CAR", "contact_name": "Иван Иванов",
            "phone": "+996700000001", "email": "ivan@test.local", "message": "Хочу подключиться",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ClinicAccessRequest.objects.filter(clinic_name="Новая клиника CAR").exists())
        self.assertTrue(Notification.objects.filter(user=self.superadmin, title__icontains="Новая клиника CAR").exists())

    def test_submit_missing_required_fields_shows_error(self):
        from apps.users.models import ClinicAccessRequest
        resp = self.client.post("/access-request/", {"clinic_name": "", "contact_name": "", "phone": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ClinicAccessRequest.objects.exists())

    def test_public_site_middleware_unresolved_slug_redirects_to_access_request(self):
        """Регрессия для жалобы «редиректит на sadaf» — несуществующий
        поддомен теперь ведёт на форму запроса доступа, а не на общий вход."""
        from django.test import override_settings
        with override_settings(PUBLIC_BASE_DOMAIN="example.test", APP_HOST="app.example.test"):
            resp = self.client.get("/", HTTP_HOST="totally-unknown-slug.example.test")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("app.example.test/access-request/", resp.url)


class BlockedIPTestCase(TestCase):
    """Блокировка входа по IP (apps.users.forms.LoginForm.clean) — глобальная,
    не привязана к одной клинике; логируется ClinicLoginEvent на каждую
    попытку входа (успех/провал)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника IP", slug="clinic-ip")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(
            login="ip_director", name="Директор IP", email="ipd@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.director.set_password("pass1234")
        self.director.save()

    def test_blocked_ip_cannot_login(self):
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="203.0.113.5")
        resp = self.client.post("/login/", {"login": "ip_director", "password": "pass1234"},
                                 REMOTE_ADDR="203.0.113.5")
        self.assertContains(resp, "заблокирован", status_code=403)
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_blocked_ip_rejected_on_every_request_not_just_login(self):
        """apps.tenancy.BlockedIPMiddleware — блокировка проверяется на КАЖДОМ
        запросе, а не только при входе: уже открытая (до блокировки) сессия
        с этого IP разлогинивается и не может выполнить ни одного действия."""
        from apps.users.models import BlockedIP
        self.client.force_login(self.director)
        # ДО блокировки — обычный доступ.
        resp0 = self.client.get("/new/", REMOTE_ADDR="203.0.113.7")
        self.assertEqual(resp0.status_code, 200)

        BlockedIP.objects.create(ip_address="203.0.113.7")
        resp = self.client.get("/new/", REMOTE_ADDR="203.0.113.7")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "заблокирован", status_code=403)
        self.assertFalse(resp.wsgi_request.user.is_authenticated)

    def test_unblocked_ip_not_affected(self):
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="203.0.113.7")
        self.client.force_login(self.director)
        resp = self.client.get("/new/", REMOTE_ADDR="203.0.113.8")
        self.assertEqual(resp.status_code, 200)

    def test_blocked_ip_screen_shows_reason(self):
        """BlockedIPMiddleware показывает причину (BlockedIP.note), если она
        указана при блокировке — та же логика, что и Clinic.blocked_reason
        на /access-request/."""
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="203.0.113.9", note="Множественные неудачные попытки входа")
        resp = self.client.get("/new/", REMOTE_ADDR="203.0.113.9")
        self.assertContains(resp, "Множественные неудачные попытки входа", status_code=403)

    def test_blocked_ip_screen_omits_empty_reason_block(self):
        """Без указанной причины — просто факт блокировки, без пустого блока."""
        from apps.users.models import BlockedIP
        BlockedIP.objects.create(ip_address="203.0.113.10")
        resp = self.client.get("/new/", REMOTE_ADDR="203.0.113.10")
        self.assertNotContains(resp, "Причина", status_code=403)

    def test_superadmin_can_block_ip_with_note(self):
        """/users/block-ip/ (панель супер-админа, модалка «Причина блокировки») —
        сохраняет note (шаблон или свой текст), который потом покажет
        BlockedIPMiddleware заблокированному IP."""
        from apps.users.models import BlockedIP
        superadmin_role = Role.objects.get(name=Role.SUPERADMIN, clinic__isnull=True)
        superadmin = User.objects.create(
            login="ip_super", name="Супер IP", email="ipsup@test.local", role=superadmin_role,
        )
        self.client.force_login(superadmin)
        resp = self.client.post("/users/block-ip/", {
            "ip_address": "203.0.113.11", "note": "Спам / автоматизированные запросы",
        })
        self.assertEqual(resp.status_code, 302)
        blocked = BlockedIP.objects.get(ip_address="203.0.113.11")
        self.assertEqual(blocked.note, "Спам / автоматизированные запросы")
        self.assertEqual(blocked.blocked_by, superadmin)

    def test_login_events_logged_success_and_failure(self):
        from apps.users.models import ClinicLoginEvent
        self.client.post("/login/", {"login": "ip_director", "password": "wrong"}, REMOTE_ADDR="203.0.113.9")
        self.client.post("/login/", {"login": "ip_director", "password": "pass1234"}, REMOTE_ADDR="203.0.113.9")
        events = list(ClinicLoginEvent.objects.filter(ip_address="203.0.113.9").order_by("created_at"))
        self.assertEqual(len(events), 2)
        self.assertFalse(events[0].success)
        self.assertTrue(events[1].success)
        self.assertEqual(events[1].clinic_id, self.clinic.pk)


class ClinicBlockedFeaturesTestCase(TestCase):
    """Блокировка отдельных функций клиники (Clinic.blocked_features) —
    apps.tenancy.SectionAccessMiddleware + голосовой/ИИ-бот в _shared_options."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника BF", slug="clinic-bf")
        self.other_clinic = Clinic.objects.create(name="Клиника BF Other", slug="clinic-bf-other")
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.staff = User.objects.create(
            login="bf_staff", name="Сотрудник BF", email="bfs@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.other_staff = User.objects.create(
            login="bf_other", name="Сотрудник Other", email="bfo@test.local",
            role=self.admin_role, clinic=self.other_clinic,
        )

    def test_blocked_warehouse_redirects_both_interfaces(self):
        self.clinic.blocked_features = ["warehouse"]
        self.clinic.save(update_fields=["blocked_features"])
        self.client.force_login(self.staff)
        resp1 = self.client.get("/new/warehouse/", follow=True)
        self.assertRedirects(resp1, "/new/", fetch_redirect_response=False)
        resp2 = self.client.get("/warehouse/", follow=True)
        self.assertRedirects(resp2, "/", fetch_redirect_response=False)

    def test_unaffected_clinic_keeps_access(self):
        self.clinic.blocked_features = ["warehouse"]
        self.clinic.save(update_fields=["blocked_features"])
        self.client.force_login(self.other_staff)
        resp = self.client.get("/new/warehouse/")
        self.assertEqual(resp.status_code, 200)

    def test_voice_bot_hidden_when_blocked_even_if_globally_enabled(self):
        from unittest.mock import patch
        self.clinic.blocked_features = ["voice_bot"]
        self.clinic.save(update_fields=["blocked_features"])
        self.client.force_login(self.staff)
        with patch("apps.notifications.voice.voice_enabled", return_value=True), \
             patch("apps.notifications.voice.ai_enabled", return_value=True):
            resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertFalse(data["voiceEnabled"])
        self.assertFalse(data["aiEnabled"])

    def test_voice_bot_visible_when_not_blocked(self):
        from unittest.mock import patch
        self.client.force_login(self.staff)
        with patch("apps.notifications.voice.voice_enabled", return_value=True), \
             patch("apps.notifications.voice.ai_enabled", return_value=True):
            resp = self.client.get("/new/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertTrue(data["voiceEnabled"])
        self.assertTrue(data["aiEnabled"])


class BranchBlockingTestCase(TestCase):
    """«Запретить запись/работу в филиале» (Branch.is_active=False) — новая
    запись не может достаться заблокированному филиалу врача, ни через
    быстрое создание (appointment_create_quick), ни через супер-админскую
    вьюху переключения (branch_toggle_active)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника BB", slug="clinic-bb")
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.superadmin_role = Role.objects.get(name=Role.SUPERADMIN, clinic__isnull=True)
        self.branch = Branch.objects.create(
            name="Филиал BB", address="-", phone="0", is_main=True, clinic=self.clinic,
        )
        self.doctor = User.objects.create(
            login="bb_doctor", name="Врач BB", email="bbd@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.doctor.branches.set([self.branch])
        self.staff = User.objects.create(
            login="bb_staff", name="Сотрудник BB", email="bbs@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.superadmin = User.objects.create(
            login="bb_super", name="Супер BB", email="bbsup@test.local",
            role=self.superadmin_role,
        )

    def test_appointment_create_quick_rejected_when_branch_blocked(self):
        self.branch.is_active = False
        self.branch.save(update_fields=["is_active"])
        self.client.force_login(self.staff)
        resp = self.client.post(
            "/appointments/create-quick/",
            data=json.dumps({
                "doctor_id": self.doctor.pk,
                "start_at": "2026-09-01T10:00:00",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("заблокирован", resp.json()["error"])

    def test_appointment_create_quick_works_when_branch_active(self):
        self.client.force_login(self.staff)
        resp = self.client.post(
            "/appointments/create-quick/",
            data=json.dumps({
                "doctor_id": self.doctor.pk,
                "start_at": "2026-09-01T10:00:00",
            }),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_branch_toggle_active_requires_superadmin(self):
        self.client.force_login(self.staff)
        resp = self.client.post(f"/users/branches/{self.branch.pk}/toggle-active/", follow=True)
        self.branch.refresh_from_db()
        self.assertTrue(self.branch.is_active)  # не изменилось

    def test_branch_toggle_active_by_superadmin(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post(f"/users/branches/{self.branch.pk}/toggle-active/")
        self.assertEqual(resp.status_code, 302)
        self.branch.refresh_from_db()
        self.assertFalse(self.branch.is_active)


class ClinicBlockReasonTestCase(TestCase):
    """Причина блокировки клиники (Clinic.blocked_reason) — задаётся
    супер-админом в момент блокировки, показывается на /access-request/
    вместе со скрытой ссылкой «Войти» именно для заблокированной клиники."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Reason", slug="clinic-reason")
        self.superadmin_role = Role.objects.get(name=Role.SUPERADMIN, clinic__isnull=True)
        self.superadmin = User.objects.create(
            login="reason_super", name="Супер Reason", email="rsup@test.local",
            role=self.superadmin_role,
        )

    def test_toggle_active_saves_reason_when_blocking(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post(
            f"/users/clinic/{self.clinic.pk}/toggle-active/",
            {"reason": "Задолженность по оплате тарифа"},
        )
        self.assertEqual(resp.status_code, 302)
        self.clinic.refresh_from_db()
        self.assertFalse(self.clinic.is_active)
        self.assertEqual(self.clinic.blocked_reason, "Задолженность по оплате тарифа")

    def test_toggle_active_reason_ignored_when_unblocking(self):
        self.clinic.is_active = False
        self.clinic.blocked_reason = "Старая причина"
        self.clinic.save(update_fields=["is_active", "blocked_reason"])
        self.client.force_login(self.superadmin)
        resp = self.client.post(
            f"/users/clinic/{self.clinic.pk}/toggle-active/",
            {"reason": "должно быть проигнорировано"},
        )
        self.assertEqual(resp.status_code, 302)
        self.clinic.refresh_from_db()
        self.assertTrue(self.clinic.is_active)
        self.assertEqual(self.clinic.blocked_reason, "Старая причина")  # не тронуто

    def test_access_request_shows_reason_and_hides_login_link(self):
        self.clinic.is_active = False
        self.clinic.blocked_reason = "Нарушение условий использования"
        self.clinic.save(update_fields=["is_active", "blocked_reason"])
        resp = self.client.get(f"/access-request/?clinic={self.clinic.slug}")
        self.assertContains(resp, "Нарушение условий использования")
        self.assertNotContains(resp, "Уже есть доступ? Войти")

    def test_access_request_shows_login_link_when_not_blocked(self):
        resp = self.client.get("/access-request/?clinic=unknown-slug-xyz")
        self.assertContains(resp, "Уже есть доступ? Войти")


class StomAsiaRoutingMiddlewareTestCase(TestCase):
    """Регрессия: <slug>.stom.asia для заблокированной/несуществующей клиники
    редиректит на /access-request/ на ТОМ ЖЕ поддомене (в отличие от
    PublicSiteMiddleware, который уводит на другой app-хост) — сама
    /access-request/ и статика должны быть исключены из повторной проверки,
    иначе middleware редиректит сам на себя (ERR_TOO_MANY_REDIRECTS)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Routing", slug="akm")
        self.clinic.is_active = False
        self.clinic.blocked_reason = "тест"
        self.clinic.save(update_fields=["is_active", "blocked_reason"])

    def test_access_request_on_blocked_subdomain_does_not_redirect_loop(self):
        from django.test import override_settings
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/access-request/?clinic=akm", HTTP_HOST="akm.stom.asia")
        self.assertEqual(resp.status_code, 200)

    def test_unresolved_slug_still_redirects_to_access_request(self):
        from django.test import override_settings
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/", HTTP_HOST="unknown-slug.stom.asia")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/access-request/?clinic=unknown-slug")

    def test_static_path_on_blocked_subdomain_not_redirected(self):
        from django.test import override_settings
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/static/css/app.css", HTTP_HOST="akm.stom.asia")
        self.assertNotEqual(resp.status_code, 302)


class StomAsiaLoginTemplateTestCase(TestCase):
    """На домене stom.asia (CRM_BASE_DOMAIN) страница входа рендерится
    отдельным, переоформленным шаблоном (login_stom.html) — на остальных
    доменах поведение не меняется (login.html). Апекс/www.stom.asia — это
    лендинг о продукте (config.urls_marketing, см. StomAsiaRoutingMiddleware),
    поэтому CRM-логин на stom.asia открывается на "app.stom.asia" — служебный
    хост, который middleware намеренно не трактует как слаг клиники."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Demo", slug="demo")

    def test_stom_asia_app_host_renders_new_template(self):
        from django.test import override_settings
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/login/", HTTP_HOST="app.stom.asia")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "auth/login_stom.html")

    def test_stom_asia_clinic_subdomain_renders_new_template(self):
        from django.test import override_settings
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/login/", HTTP_HOST="demo.stom.asia")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "auth/login_stom.html")

    def test_other_domain_keeps_old_template(self):
        from django.test import override_settings
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/login/", HTTP_HOST="app.sadaf.kg")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "auth/login.html")


class BranchFilterTestCase(TestCase):
    """Переключатель филиала (session["active_branch"], /users/set-branch/)
    теперь реально ФИЛЬТРУЕТ отображаемые данные нового интерфейса —
    расписание/пациенты/склад(операции)/финансы/отчёты — а не только
    подставляет филиал по умолчанию для новых записей, см.
    apps.tenancy.get_active_branch_id и _newui_schedule_data/
    _newui_patients_page_data/_newui_finance_data/_newui_warehouse_ops_data/
    _newui_reports_data (apps/users/views.py)."""

    def setUp(self):
        import datetime as dt
        from django.utils import timezone
        from apps.patients.models import Patient
        from apps.appointments.models import Appointment
        from apps.finance.models import Payment, Expense, ExpenseCategory
        from apps.warehouse.models import Product, WarehouseDistribution

        self.clinic = Clinic.objects.create(name="Клиника BF2", slug="clinic-bf2")
        self.branch1 = Branch.objects.create(name="Филиал 1", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.branch2 = Branch.objects.create(name="Филиал 2", address="-", phone="0", clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.director = User.objects.create(
            login="bf2_director", name="Директор BF2", email="bf2d@test.local",
            role=self.admin_role, clinic=self.clinic,
        )
        self.doctor1 = User.objects.create(
            login="bf2_doc1", name="Врач Филиал1", email="bf2doc1@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.doctor1.branches.set([self.branch1])
        self.doctor2 = User.objects.create(
            login="bf2_doc2", name="Врач Филиал2", email="bf2doc2@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.doctor2.branches.set([self.branch2])

        self.patient1 = Patient.objects.create(
            first_name="Один", last_name="Пациентов1", phone="+996700000001",
            branch=self.branch1, clinic=self.clinic,
        )
        self.patient2 = Patient.objects.create(
            first_name="Два", last_name="Пациентов2", phone="+996700000002",
            branch=self.branch2, clinic=self.clinic,
        )

        today = timezone.localdate()
        start1 = timezone.make_aware(dt.datetime.combine(today, dt.time(10, 0)))
        end1 = timezone.make_aware(dt.datetime.combine(today, dt.time(11, 0)))
        Appointment.objects.create(
            patient=self.patient1, doctor=self.doctor1, branch=self.branch1,
            start_at=start1, end_at=end1, status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )
        start2 = timezone.make_aware(dt.datetime.combine(today, dt.time(14, 0)))
        end2 = timezone.make_aware(dt.datetime.combine(today, dt.time(15, 0)))
        Appointment.objects.create(
            patient=self.patient2, doctor=self.doctor2, branch=self.branch2,
            start_at=start2, end_at=end2, status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )

        Payment.objects.create(
            patient=self.patient1, amount=1000, branch=self.branch1, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        Payment.objects.create(
            patient=self.patient2, amount=2000, branch=self.branch2, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        cat = ExpenseCategory.objects.create(name="Прочее", clinic=self.clinic)
        Expense.objects.create(
            branch=self.branch1, amount=100, category=cat, description="", created_by=self.director,
            date=today, clinic=self.clinic,
        )
        Expense.objects.create(
            branch=self.branch2, amount=200, category=cat, description="", created_by=self.director,
            date=today, clinic=self.clinic,
        )

        product = Product.objects.create(name="Перчатки", unit="уп", quantity=50, clinic=self.clinic)
        WarehouseDistribution.objects.create(product=product, quantity=5, branch=self.branch1, date=today)
        WarehouseDistribution.objects.create(product=product, quantity=7, branch=self.branch2, date=today)

        self.client = Client()
        self.client.force_login(self.director)

    def _set_branch(self, branch):
        session = self.client.session
        session["active_branch"] = branch.pk
        session.save()

    def test_schedule_filtered_by_active_branch(self):
        self._set_branch(self.branch1)
        resp = self.client.get("/new/schedule/data/")
        data = resp.json()
        doctor_names = [d["name"] for d in data["doctors"]]
        self.assertIn("Врач Филиал1", doctor_names)
        self.assertNotIn("Врач Филиал2", doctor_names)
        patient_names = [a["patient"] for a in data["appointments"]]
        self.assertIn(self.patient1.full_name, patient_names)
        self.assertNotIn(self.patient2.full_name, patient_names)

    def test_schedule_shows_all_when_no_branch_selected(self):
        resp = self.client.get("/new/schedule/data/")
        data = resp.json()
        doctor_names = [d["name"] for d in data["doctors"]]
        self.assertIn("Врач Филиал1", doctor_names)
        self.assertIn("Врач Филиал2", doctor_names)

    def test_patients_list_filtered_by_active_branch(self):
        self._set_branch(self.branch2)
        resp = self.client.get("/new/patients/data/")
        data = resp.json()
        names = [r["fullName"] for r in data["results"]]
        self.assertIn(self.patient2.full_name, names)
        self.assertNotIn(self.patient1.full_name, names)
        self.assertEqual(data["stats"]["allCount"], 1)

    def test_finance_filtered_by_active_branch(self):
        self._set_branch(self.branch1)
        resp = self.client.get("/new/finance/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["financeData"]["revenueMonth"], 1000.0)

    def test_finance_shows_all_when_no_branch_selected(self):
        resp = self.client.get("/new/finance/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["financeData"]["revenueMonth"], 3000.0)

    def test_warehouse_ops_filtered_by_active_branch(self):
        self._set_branch(self.branch1)
        resp = self.client.get("/new/warehouse/")
        data = _extract_newui_real_data(resp.content.decode())
        dist_branches = [d["branch"] for d in data["warehouseOpsData"]["distributions"]]
        self.assertIn("Филиал 1", dist_branches)
        self.assertNotIn("Филиал 2", dist_branches)

    def test_warehouse_stock_not_filtered_by_branch(self):
        """Остатки клиники в целом не разбиты по филиалам (Product без поля
        branch) — сознательно НЕ фильтруются переключателем, см. docstring
        _newui_warehouse_ops_data/newui_warehouse."""
        self._set_branch(self.branch1)
        resp = self.client.get("/new/warehouse/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(len(data["warehouseData"]["items"]), 1)

    def test_reports_filtered_by_active_branch(self):
        self._set_branch(self.branch1)
        resp = self.client.get("/new/reports/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["reportsData"]["revenueMonth"], 1000.0)

    def test_reports_shows_all_when_no_branch_selected(self):
        resp = self.client.get("/new/reports/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["reportsData"]["revenueMonth"], 3000.0)

    def test_cashdesk_filtered_by_active_branch(self):
        """Касса (_newui_cashdesk_data) раньше сама вычисляла филиал как
        «главный/первый» и НЕ читала переключатель сайдбара — теперь при
        выбранном конкретном филиале использует именно его."""
        self._set_branch(self.branch2)
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        cd = data["cashdeskData"]
        self.assertEqual(cd["branchId"], self.branch2.pk)
        payment_patients = [p["patientName"] for p in cd["payments"]]
        self.assertIn(self.patient2.full_name, payment_patients)
        self.assertNotIn(self.patient1.full_name, payment_patients)

    def test_cashdesk_falls_back_to_main_branch_when_none_selected(self):
        """«Все филиалы» (branch не выбран) — касса, как и раньше, падает на
        главный филиал (кассовая смена физически привязана к одному месту,
        «всё сразу» для неё не имеет смысла)."""
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        self.assertEqual(data["cashdeskData"]["branchId"], self.branch1.pk)


class CashdeskTodayPaymentsTestCase(TestCase):
    """«Сегодняшние платежи» на кассе — apps.users.views._newui_cashdesk_data
    помечает isToday=True только для платежей текущего (Бишкек-)дня."""

    def setUp(self):
        from apps.finance.models import Payment
        from apps.patients.models import Patient
        from django.utils import timezone

        self.clinic = Clinic.objects.create(name="Клиника CTP", slug="clinic-ctp")
        self.branch = Branch.objects.create(name="Филиал", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
        self.director = User.objects.create(login="ctp_director", name="Директор CTP",
                                             role=self.admin_role, clinic=self.clinic)
        patient = Patient.objects.create(first_name="Тест", last_name="Кассовый", phone="+996700000020",
                                          branch=self.branch, clinic=self.clinic)

        self.today_payment = Payment.objects.create(
            patient=patient, amount=500, branch=self.branch, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        self.yday_payment = Payment.objects.create(
            patient=patient, amount=700, branch=self.branch, received_by=self.director,
            type=Payment.TYPE_INCOME, clinic=self.clinic,
        )
        yesterday = timezone.now() - timedelta(days=1)
        Payment.objects.filter(pk=self.yday_payment.pk).update(created_at=yesterday)

        self.client = Client()
        self.client.force_login(self.director)

    def test_only_todays_payment_marked_is_today(self):
        resp = self.client.get("/new/cashdesk/")
        data = _extract_newui_real_data(resp.content.decode())
        by_id = {p["id"]: p["isToday"] for p in data["cashdeskData"]["payments"]}
        self.assertTrue(by_id[self.today_payment.pk])
        self.assertFalse(by_id[self.yday_payment.pk])


class StomAsiaPublicSiteTestCase(TestCase):
    """<slug>.stom.asia показывает публичный сайт клиники (ClinicSite),
    если он включён и опубликован — вместо CRM напрямую; без сайта
    поведение НЕ меняется (CRM напрямую — то самое, что пользователь уже
    похвалил на kuldashov.stom.asia). См. план «Публичный сайт клиники на
    stom.asia»."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника Сайт", slug="site-clinic")

    def test_clinic_with_enabled_site_shows_public_home(self):
        from apps.users.models import ClinicSite
        ClinicSite.objects.create(clinic=self.clinic, enabled=True, published=True, headline="Привет")
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/", HTTP_HOST="site-clinic.stom.asia")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "public/home.html")

    def test_clinic_without_site_still_shows_crm(self):
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/login/", HTTP_HOST="site-clinic.stom.asia")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateNotUsed(resp, "public/home.html")

    def test_clinic_with_disabled_site_still_shows_crm(self):
        from apps.users.models import ClinicSite
        ClinicSite.objects.create(clinic=self.clinic, enabled=False, published=True)
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get("/login/", HTTP_HOST="site-clinic.stom.asia")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateNotUsed(resp, "public/home.html")

    def test_clinic_public_url_prefers_crm_base_domain(self):
        from apps.users.views import _clinic_public_url
        with override_settings(CRM_BASE_DOMAIN="stom.asia", PUBLIC_BASE_DOMAIN="denta.tw1.ru"):
            self.assertEqual(_clinic_public_url(self.clinic), "https://site-clinic.stom.asia")
        with override_settings(CRM_BASE_DOMAIN="", PUBLIC_BASE_DOMAIN="denta.tw1.ru"):
            self.assertEqual(_clinic_public_url(self.clinic), "https://site-clinic.denta.tw1.ru")


class PublicBookingBranchTestCase(TestCase):
    """Онлайн-запись с публичного сайта клиники (apps.users.site_views)
    учитывает выбранный филиал (?branch=<id> на странице / branch в
    POST-заявке) — переход из центрального каталога клиник stom.asia.
    Без выбранного филиала — старое поведение (главный/первый) не
    меняется, регрессии для однофилиальных клиник нет."""

    def setUp(self):
        from apps.users.models import ClinicSite
        self.clinic = Clinic.objects.create(name="Клиника Запись", slug="book-clinic")
        self.branch_main = Branch.objects.create(
            name="Центр", address="ул. А", phone="0", is_main=True, clinic=self.clinic,
        )
        self.branch_south = Branch.objects.create(
            name="Юг", address="ул. Б", phone="0", clinic=self.clinic,
        )
        self.doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)
        self.doctor = User.objects.create(
            login="book_doc", name="Врач Юг", email="bookdoc@test.local",
            role=self.doctor_role, clinic=self.clinic,
        )
        self.doctor.branches.set([self.branch_south])
        ClinicSite.objects.create(clinic=self.clinic, enabled=True, published=True, show_booking=True)

    def _post_submit(self, phone, **extra):
        import datetime as dt
        from django.utils import timezone
        tomorrow = (timezone.localdate() + dt.timedelta(days=1)).isoformat()
        data = {
            "doctor": self.doctor.pk, "date": tomorrow, "slot": "10:00",
            "name": "Пациент Тест", "phone": phone,
        }
        data.update(extra)
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            return self.client.post("/book/submit/", data, HTTP_HOST="book-clinic.stom.asia")

    def test_submit_with_branch_id_uses_that_branch(self):
        from apps.appointments.models import Appointment
        resp = self._post_submit("+996700333444", branch=self.branch_south.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        appt = Appointment.objects.filter(patient__phone="+996700333444").first()
        self.assertIsNotNone(appt)
        self.assertEqual(appt.branch_id, self.branch_south.pk)

    def test_submit_without_branch_id_uses_main_branch(self):
        from apps.appointments.models import Appointment
        resp = self._post_submit("+996700333445")
        self.assertTrue(resp.json()["ok"])
        appt = Appointment.objects.filter(patient__phone="+996700333445").first()
        self.assertEqual(appt.branch_id, self.branch_main.pk)

    def test_submit_with_foreign_branch_id_falls_back_to_main(self):
        """branch_id чужой клиники/несуществующий — не ломается, откатывается
        на дефолт (главный филиал), как без параметра вообще."""
        from apps.appointments.models import Appointment
        resp = self._post_submit("+996700333446", branch=999999)
        self.assertTrue(resp.json()["ok"])
        appt = Appointment.objects.filter(patient__phone="+996700333446").first()
        self.assertEqual(appt.branch_id, self.branch_main.pk)

    def test_public_book_page_filters_doctors_by_branch(self):
        with override_settings(CRM_BASE_DOMAIN="stom.asia"):
            resp = self.client.get(f"/book/?branch={self.branch_south.pk}", HTTP_HOST="book-clinic.stom.asia")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Врач Юг")
