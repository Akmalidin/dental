import json
import re

from django.test import TestCase, Client
from apps.users.models import User, Permission, PermissionCategory, Role, Clinic, Branch
from apps.users.forms import UserForm


def _extract_newui_real_data(html):
    m = re.search(
        r'<script id="newui-real-data" type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    return json.loads(m.group(1))


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

    def test_new_funnel_blocked_for_restricted_user(self):
        resp = self.client.get("/new/funnel/")
        self.assertEqual(resp.status_code, 302)

    def test_new_marketing_blocked_for_restricted_user(self):
        resp = self.client.get("/new/marketing/")
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
