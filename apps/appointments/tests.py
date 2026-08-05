from django.test import TestCase, Client
from apps.users.models import User, Branch, Clinic, Role
from apps.patients.models import Patient
from apps.appointments.forms import AppointmentForm
from apps.appointments.models import Appointment
from apps.tenancy import set_current_clinic, clear_current_clinic


class AppointmentFormClinicIsolationTestCase(TestCase):
    """Regression test: patient field must never leak patients from other clinics
    into the appointment form's dropdown (was previously frozen, unfiltered, at
    module-import time — see apps/appointments/forms.py AppointmentForm.__init__)."""

    def setUp(self):
        self.clinic_a = Clinic.objects.create(name="Клиника A", slug="clinic-a-appt")
        self.clinic_b = Clinic.objects.create(name="Клиника B", slug="clinic-b-appt")
        self.branch_a = Branch.objects.create(name="A", address="-", phone="0", is_main=True, clinic=self.clinic_a)
        self.branch_b = Branch.objects.create(name="B", address="-", phone="0", is_main=True, clinic=self.clinic_b)
        self.patient_a = Patient.objects.create(
            first_name="Пац", last_name="A", phone="1", branch=self.branch_a, clinic=self.clinic_a
        )
        self.patient_b = Patient.objects.create(
            first_name="Пац", last_name="B", phone="2", branch=self.branch_b, clinic=self.clinic_b
        )

    def tearDown(self):
        clear_current_clinic()

    def test_patient_field_scoped_to_current_clinic(self):
        set_current_clinic(self.clinic_a)
        form = AppointmentForm()
        patient_ids = set(form.fields["patient"].queryset.values_list("pk", flat=True))
        self.assertIn(self.patient_a.pk, patient_ids)
        self.assertNotIn(self.patient_b.pk, patient_ids)


class AppointmentCreateBranchDefaultTestCase(TestCase):
    """Regression test: opening the "new appointment" page must pre-select the
    branch (was previously blank — default only applied on submit, not on the
    initial GET render — see apps/appointments/views.py appointment_create)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника E", slug="clinic-e-branch")
        self.branch = Branch.objects.create(
            name="Главный", address="-", phone="0", is_main=True, clinic=self.clinic
        )
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(
            login="admin_branch", name="Админ", email="admin_branch@test.local",
            role=admin_role, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def tearDown(self):
        clear_current_clinic()

    def test_branch_preselected_on_get(self):
        resp = self.client.get("/appointments/create/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial.get("branch"), self.branch)


class DayGridBookingModalTestCase(TestCase):
    """«Расписание по врачам» — клик по пустой ячейке открывает модалку записи
    (не переходит на отдельную страницу), для чего нужны реальные patients_json/
    services_json в контексте, как у /calendar/."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Клиника DG", slug="clinic-daygrid")
        self.branch = Branch.objects.create(name="Филиал DG", address="-", phone="0", is_main=True, clinic=self.clinic)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(
            login="dg_admin", name="Админ DG", email="dgadmin@test.local",
            role=admin_role, clinic=self.clinic,
        )
        self.patient = Patient.objects.create(
            first_name="Гриджан", last_name="Тестова", phone="+996700444555", branch=self.branch, clinic=self.clinic,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def tearDown(self):
        clear_current_clinic()

    def test_day_grid_provides_patients_and_services_for_booking_modal(self):
        resp = self.client.get("/appointments/day/")
        self.assertEqual(resp.status_code, 200)
        patient_names = [p["name"] for p in resp.context["patients_json"]]
        self.assertIn("Тестова Гриджан", patient_names)

    def test_day_grid_renders_booking_modal_markup(self):
        resp = self.client.get("/appointments/day/")
        self.assertContains(resp, "dayGridPage")
        self.assertContains(resp, "dgEmptyClick")


class AppointmentMoveTestCase(TestCase):
    """Перетаскивание записи в «Расписание по врачам»: смена времени (как раньше)
    и смена врача (новое — перенос между колонками)."""

    def setUp(self):
        from datetime import datetime, time, timedelta
        from django.utils import timezone
        from apps.services.models import Service

        self.clinic = Clinic.objects.create(name="Клиника MV", slug="clinic-move")
        self.branch = Branch.objects.create(name="Филиал MV", address="-", phone="0", is_main=True, clinic=self.clinic)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        doctor_role, _ = Role.objects.get_or_create(name=Role.DOCTOR)
        self.admin = User.objects.create(
            login="mv_admin", name="Админ MV", email="mvadmin@test.local", role=admin_role, clinic=self.clinic,
        )
        self.doctor1 = User.objects.create(
            login="mv_doc1", name="Врач Один", email="mvdoc1@test.local", role=doctor_role, clinic=self.clinic,
        )
        self.doctor2 = User.objects.create(
            login="mv_doc2", name="Врач Два", email="mvdoc2@test.local", role=doctor_role, clinic=self.clinic,
        )
        self.patient = Patient.objects.create(
            first_name="Тест", last_name="Пациентов", phone="+996700333222", branch=self.branch, clinic=self.clinic,
        )
        self.service = Service.objects.create(name="Приём", price=100, clinic=self.clinic)
        self.client = Client()
        self.client.force_login(self.admin)

        today = timezone.localdate()
        self.start = timezone.make_aware(datetime.combine(today, time(11, 0)))
        self.end = self.start + timedelta(minutes=30)
        self.appt = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor1, branch=self.branch, service=self.service,
            start_at=self.start, end_at=self.end, status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )

    def tearDown(self):
        clear_current_clinic()

    def _iso(self, dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    def test_move_same_doctor_changes_time_only(self):
        import json
        new_start = self.start.replace(hour=13, minute=0)
        new_end = new_start + (self.end - self.start)
        resp = self.client.post(
            f"/appointments/{self.appt.pk}/move/",
            data=json.dumps({"start": self._iso(new_start), "end": self._iso(new_end)}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.doctor_id, self.doctor1.pk)
        from django.utils import timezone
        self.assertEqual(timezone.localtime(self.appt.start_at).hour, 13)

    def test_move_to_different_doctor_reassigns(self):
        import json
        resp = self.client.post(
            f"/appointments/{self.appt.pk}/move/",
            data=json.dumps({"start": self._iso(self.start), "end": self._iso(self.end), "doctor_id": self.doctor2.pk}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.doctor_id, self.doctor2.pk)

    def test_move_rejects_overlap_with_target_doctor(self):
        import json
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor2, branch=self.branch, service=self.service,
            start_at=self.start, end_at=self.end, status=Appointment.STATUS_SCHEDULED, clinic=self.clinic,
        )
        resp = self.client.post(
            f"/appointments/{self.appt.pk}/move/",
            data=json.dumps({"start": self._iso(self.start), "end": self._iso(self.end), "doctor_id": self.doctor2.pk}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.doctor_id, self.doctor1.pk)  # не изменилось
