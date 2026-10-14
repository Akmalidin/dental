from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, WaitlistEntry
from apps.appointments import waitlist as wl
from apps.notifications.models import Notification
from apps.patients.models import Patient
from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Branch, Clinic, Role, User


class WaitlistTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(slug="wl-a", name="A")
        self.other = Clinic.objects.create(slug="wl-b", name="B")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(clinic=self.clinic, name="A1", address="-", phone="0", is_main=True)
        self.admin = User.objects.create(login="wl_admin", name="Админ", clinic=self.clinic,
                                         role=Role.objects.get(name="admin_main", clinic__isnull=True))
        doc = Role.objects.get(name="doctor", clinic__isnull=True)
        self.doc = User.objects.create(login="wl_doc", name="Врач", clinic=self.clinic, role=doc)
        self.doc2 = User.objects.create(login="wl_doc2", name="Врач2", clinic=self.clinic, role=doc)
        self.p1 = Patient.objects.create(first_name="Анна", last_name="Ждёт", phone="+996700001001",
                                         branch=self.branch, clinic=self.clinic)
        self.p2 = Patient.objects.create(first_name="Борис", last_name="Занят", phone="+996700001002",
                                         branch=self.branch, clinic=self.clinic)
        # окно завтра в 10:00 (по местному времени)
        local = timezone.localtime() + timedelta(days=1)
        self.start = local.replace(hour=10, minute=0, second=0, microsecond=0)
        self.end = self.start + timedelta(minutes=60)

    def tearDown(self):
        clear_current_clinic()

    def _appt(self, **kw):
        return Appointment.objects.create(patient=self.p2, doctor=kw.pop("doctor", self.doc), branch=self.branch,
                                          start_at=kw.pop("start", self.start), end_at=kw.pop("end", self.end),
                                          clinic=self.clinic, **kw)

    def _entry(self, **kw):
        return WaitlistEntry.objects.create(patient=kw.pop("patient", self.p1), clinic=self.clinic, **kw)

    def test_match_rules(self):
        any_doc = self._entry()
        evening = self._entry(patient=self.p2, part_of_day="evening")
        other_doc = self._entry(patient=self.p2, doctor=self.doc2)
        too_long = self._entry(patient=self.p2, duration_min=90)
        later = self._entry(patient=self.p2, date_from=(self.start + timedelta(days=3)).date())
        urgent = self._entry(patient=self.p2, doctor=self.doc, urgent=True)
        got = wl.match(self.clinic.pk, self.doc.pk, self.branch.pk, self.start, self.end)
        self.assertEqual([e.pk for e in got], [urgent.pk, any_doc.pk])   # срочные первыми
        for e in (evening, other_doc, too_long, later):
            self.assertNotIn(e, got)

    def test_cancel_notifies_admins_only_when_match(self):
        a = self._appt()
        with self.captureOnCommitCallbacks(execute=True):
            a.status = Appointment.STATUS_CANCELLED
            a.save()
        self.assertFalse(Notification.objects.filter(user=self.admin).exists())   # лист пуст
        self._entry()
        b = self._appt(start=self.start + timedelta(hours=2), end=self.end + timedelta(hours=2))
        with self.captureOnCommitCallbacks(execute=True):
            b.status = Appointment.STATUS_CANCELLED
            b.save()
        n = Notification.objects.get(user=self.admin)
        self.assertIn("Освободилось окно", n.title)
        self.assertIn("Ждёт Анна", n.body)
        self.assertEqual(n.link, "/new/waitlist/")

    def test_reschedule_and_delete_free_slot(self):
        self._entry()
        a = self._appt()
        with self.captureOnCommitCallbacks(execute=True):
            a.start_at += timedelta(days=2)
            a.end_at += timedelta(days=2)
            a.save()
        self.assertEqual(Notification.objects.filter(user=self.admin).count(), 1)
        b = self._appt(start=self.start + timedelta(hours=3), end=self.end + timedelta(hours=3))
        with self.captureOnCommitCallbacks(execute=True):
            b.delete()
        self.assertEqual(Notification.objects.filter(user=self.admin).count(), 2)

    def test_no_notification_when_slot_taken_again_or_past(self):
        self._entry()
        a = self._appt()
        self._appt(status=Appointment.STATUS_SCHEDULED)   # то же время уже занято другим
        with self.captureOnCommitCallbacks(execute=True):
            a.status = Appointment.STATUS_CANCELLED
            a.save()
        self.assertFalse(Notification.objects.filter(user=self.admin).exists())

    def test_page_book_and_offer(self):
        e = self._entry()
        a = self._appt()
        a.status = Appointment.STATUS_CANCELLED
        a.save()
        c = Client()
        c.force_login(self.admin)
        r = c.get("/new/waitlist/")
        self.assertEqual(r.status_code, 200)
        data = r.context["real_data"]["waitlist"]
        self.assertEqual(len(data["slots"]), 1)
        self.assertEqual(data["slots"][0]["matches"], [e.pk])
        self.assertEqual(r.context["real_data"]["waitlistCount"], 1)
        with patch("apps.notifications.whatsapp.wa_enabled", return_value=True), \
                patch("apps.notifications.whatsapp.wa_send_text", return_value=True) as send:
            r = c.post(f"/new/waitlist/{e.pk}/offer/", {"start": self.start.isoformat(), "doctor_id": self.doc.pk})
        self.assertTrue(r.json()["ok"], r.content)
        self.assertIn("Освободилось время", send.call_args[0][1])
        e.refresh_from_db()
        self.assertEqual(e.status, WaitlistEntry.STATUS_OFFERED)
        r = c.post(f"/new/waitlist/{e.pk}/book/", {"start": self.start.isoformat(), "end": self.end.isoformat(),
                                                    "doctor_id": self.doc.pk})
        self.assertTrue(r.json()["ok"], r.content)
        e.refresh_from_db()
        self.assertEqual(e.status, WaitlistEntry.STATUS_BOOKED)
        appt = Appointment.objects.get(pk=e.appointment_id)
        self.assertEqual((appt.patient_id, appt.doctor_id, appt.start_at), (self.p1.pk, self.doc.pk, self.start))
        # второй раз в то же время — занято
        e2 = self._entry(patient=self.p2)
        r = c.post(f"/new/waitlist/{e2.pk}/book/", {"start": self.start.isoformat(), "doctor_id": self.doc.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIn("занято", r.json()["error"])

    def test_book_asks_to_move_existing_appointment(self):
        later = self._appt(start=self.start + timedelta(days=5), end=self.end + timedelta(days=5),
                           doctor=self.doc2, status=Appointment.STATUS_CONFIRMED)
        e = self._entry(patient=self.p2)
        c = Client()
        c.force_login(self.admin)
        url = f"/new/waitlist/{e.pk}/book/"
        slot = {"start": self.start.isoformat(), "end": self.end.isoformat(), "doctor_id": self.doc.pk}
        d = c.post(url, slot).json()
        self.assertTrue(d["needChoice"])
        self.assertEqual(d["existing"]["id"], later.pk)
        self.assertFalse(Appointment.objects.filter(patient=self.p2, start_at=self.start).exists())
        with patch("apps.notifications.whatsapp.wa_enabled", return_value=False):
            d = c.post(url, dict(slot, mode="move")).json()
        self.assertTrue(d["ok"] and d["moved"], d)
        later.refresh_from_db()
        self.assertEqual((later.start_at, later.doctor_id, later.status),
                         (self.start, self.doc.pk, Appointment.STATUS_SCHEDULED))
        self.assertEqual(Appointment.objects.filter(patient=self.p2).count(), 1)
        e.refresh_from_db()
        self.assertEqual((e.status, e.appointment_id), (WaitlistEntry.STATUS_BOOKED, later.pk))
        # «Новая запись» — вторая запись, старая остаётся
        e2 = self._entry(patient=self.p2, doctor=self.doc2)
        slot2 = dict(slot, start=(self.start + timedelta(hours=3)).isoformat(),
                     end=(self.end + timedelta(hours=3)).isoformat())
        with patch("apps.notifications.whatsapp.wa_enabled", return_value=False):
            d = c.post(f"/new/waitlist/{e2.pk}/book/", dict(slot2, mode="new")).json()
        self.assertTrue(d["ok"] and not d["moved"], d)
        self.assertEqual(Appointment.objects.filter(patient=self.p2).count(), 2)

    def test_add_validation_and_other_clinic(self):
        c = Client()
        c.force_login(self.admin)
        r = c.post("/new/waitlist/add/", {"patient_id": self.p1.pk, "doctor_id": self.doc.pk, "urgent": "1",
                                          "part": "morning", "duration": "45", "note": "<b>после работы</b>"})
        self.assertTrue(r.json()["ok"])
        e = WaitlistEntry.objects.get(pk=r.json()["id"])
        self.assertTrue(e.urgent)
        self.assertNotIn("<", e.note)
        r = c.post("/new/waitlist/add/", {"patient_id": self.p1.pk, "doctor_id": self.doc.pk})
        self.assertEqual(r.status_code, 400)   # дубль
        foreign = Patient.all_objects.create(first_name="Чужой", last_name="Б", phone="+996700001003",
                                             clinic=self.other)
        r = c.post("/new/waitlist/add/", {"patient_id": foreign.pk})
        self.assertEqual(r.status_code, 400)
        other_admin = User.objects.create(login="wl_other", name="Чужой админ", clinic=self.other,
                                          role=Role.objects.get(name="admin_main", clinic__isnull=True))
        c2 = Client()
        c2.force_login(other_admin)
        self.assertEqual(c2.post(f"/new/waitlist/{e.pk}/status/", {"status": "cancelled"}).status_code, 404)
        self.assertEqual(c2.post(f"/new/waitlist/{e.pk}/book/", {"start": self.start.isoformat(),
                                                                 "doctor_id": self.doc.pk}).status_code, 404)
        r = c2.get("/new/waitlist/patients/?q=Ждёт")
        self.assertEqual(r.json()["results"], [])
