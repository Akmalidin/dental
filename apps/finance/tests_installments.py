import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.finance import installments as inst
from apps.finance.models import InstallmentItem, InstallmentPlan, Payment
from apps.patients.models import Patient
from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Branch, Clinic, Role, User


class InstallmentTestCase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(slug="in-a", name="A")
        self.other = Clinic.objects.create(slug="in-b", name="B")
        set_current_clinic(self.clinic)
        self.branch = Branch.objects.create(clinic=self.clinic, name="A1", address="-", phone="0", is_main=True)
        self.admin = User.objects.create(login="in_admin", name="Админ", clinic=self.clinic,
                                         role=Role.objects.get(name="admin_main", clinic__isnull=True))
        self.p = Patient.objects.create(first_name="Анна", last_name="Рассрочка", phone="+996700002001",
                                        branch=self.branch, clinic=self.clinic)
        self.today = timezone.localdate()

    def tearDown(self):
        clear_current_clinic()

    def pay(self, amount, kind=Payment.TYPE_INCOME):
        return Payment.objects.create(patient=self.p, amount=amount, type=kind, method=Payment.METHOD_CASH,
                                      branch=self.branch, clinic=self.clinic, received_by=self.admin)

    def test_build_schedule(self):
        rows = inst.build_schedule(100000, 10000, 3, date(2026, 1, 31), today=date(2026, 1, 1))
        self.assertEqual([r[0] for r in rows], [date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)])
        self.assertEqual([int(r[1]) for r in rows], [10000, 30000, 30000, 30000])
        rows = inst.build_schedule(100, 0, 3, date(2026, 5, 10))
        self.assertEqual(sum(r[1] for r in rows), 100)   # остаток в последний платёж

    def test_payments_cover_items_in_order_overdue_and_done(self):
        plan = inst.create_plan(self.p, 30000, [
            (self.today - timedelta(days=10), Decimal(10000)),
            (self.today + timedelta(days=5), Decimal(10000)),
            (self.today + timedelta(days=35), Decimal(10000)),
        ])
        s = inst.state(plan)
        self.assertEqual([i["status"] for i in s["items"]], ["overdue", "upcoming", "upcoming"])
        self.assertEqual(s["overdue"], 10000)
        self.pay(15000)
        s = inst.state(plan)
        self.assertEqual([i["status"] for i in s["items"]], ["paid", "partial", "upcoming"])
        self.assertEqual((s["paid"], s["left"]), (15000, 15000))
        self.pay(15000)
        self.assertEqual(inst.refresh_status(plan), InstallmentPlan.STATUS_DONE)
        self.pay(5000, kind=Payment.TYPE_REFUND)          # вернули — снова действует
        self.assertEqual(inst.refresh_status(plan), InstallmentPlan.STATUS_ACTIVE)

    def test_payments_before_plan_not_counted(self):
        old = self.pay(10000)
        Payment.all_clinics.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        plan = inst.create_plan(self.p, 10000, [(self.today, Decimal(10000))])
        self.assertEqual(inst.state(plan)["paid"], 0)

    def _at(self, day, hour):
        from datetime import datetime
        return timezone.make_aware(datetime(day.year, day.month, day.day, hour, 5))

    def test_reminders_follow_settings_and_send_once(self):
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.get()
        cs.installment_reminders = {"before_days": [3, 1], "hour": 9, "overdue_after": 2,
                                    "overdue_repeat": 7, "overdue_max": 2}
        cs.save()
        plan = inst.create_plan(self.p, 30000, [
            (self.today + timedelta(days=3), Decimal(10000)),
            (self.today + timedelta(days=1), Decimal(10000)),
            (self.today - timedelta(days=2), Decimal(10000)),
        ])
        with patch("apps.notifications.whatsapp.wa_enabled", return_value=True), \
                patch("apps.notifications.whatsapp.wa_send_text", return_value=True) as send:
            self.assertEqual(inst.run_reminders(now=self._at(self.today, 15)), 0)   # не тот час
            self.assertEqual(inst.run_reminders(now=self._at(self.today, 9)), 3)    # за 3, за 1, просрочка
            self.assertEqual(inst.run_reminders(now=self._at(self.today, 9)), 0)    # один раз
            texts = [c[0][1] for c in send.call_args_list]
            self.assertTrue(any("через 3 дн." in t for t in texts))
            self.assertTrue(any("завтра" in t for t in texts))
            self.assertTrue(any("не поступил" in t for t in texts))
            # повтор о просрочке через 7 дней, но не больше 2 раз
            later = self.today + timedelta(days=7)
            send.reset_mock()
            inst.run_reminders(now=self._at(later, 9))
            self.assertTrue(any("не поступил" in c[0][1] for c in send.call_args_list))
            send.reset_mock()
            inst.run_reminders(now=self._at(self.today + timedelta(days=14), 9))
            self.assertFalse(any("не поступил" in c[0][1] and "%s" % (self.today - timedelta(days=2)).strftime("%d.%m.%Y") in c[0][1]
                                 for c in send.call_args_list))
        cs.installment_reminders = {"enabled": False}
        cs.save()
        self.assertEqual(inst.run_reminders(now=self._at(self.today + timedelta(days=20), 9)), 0)

    def test_settings_endpoint_admin_only_and_clamped(self):
        c = Client()
        c.force_login(self.admin)
        r = c.post("/new/installments/settings/", {"enabled": "1", "before_days": ["7", "1", "99"], "hour": "30",
                                                   "overdue_after": "3", "overdue_repeat": "30", "overdue_max": "50"})
        self.assertEqual(r.json()["settings"], {"enabled": True, "before_days": [7, 1], "hour": 22,
                                                "overdue_after": 3, "overdue_repeat": 30, "overdue_max": 12})
        doc = User.objects.create(login="in_doc", name="Врач", clinic=self.clinic,
                                  role=Role.objects.get(name="doctor", clinic__isnull=True))
        c2 = Client()
        c2.force_login(doc)
        self.assertNotEqual(c2.post("/new/installments/settings/", {"enabled": ""}).status_code, 200)

    def test_create_endpoint_validation_and_scope(self):
        c = Client()
        c.force_login(self.admin)
        rows = [{"due": (self.today + timedelta(days=30 * i)).isoformat(), "amount": 5000} for i in range(3)]
        r = c.post("/new/installments/create/", {"patient_id": self.p.pk, "total": "15000",
                                                 "rows": json.dumps(rows), "note": "<b>импланты</b>"})
        self.assertTrue(r.json()["ok"], r.content)
        plan = InstallmentPlan.objects.get(pk=r.json()["id"])
        self.assertEqual(plan.items.count(), 3)
        self.assertNotIn("<", plan.note)
        r = c.post("/new/installments/create/", {"patient_id": self.p.pk, "total": "15000", "rows": json.dumps(rows)})
        self.assertIn("уже есть", r.json()["error"])
        plan.status = InstallmentPlan.STATUS_CANCELLED
        plan.save()
        r = c.post("/new/installments/create/", {"patient_id": self.p.pk, "total": "16000", "rows": json.dumps(rows)})
        self.assertIn("не равна", r.json()["error"])
        past = [{"due": (self.today - timedelta(days=1)).isoformat(), "amount": 15000}]
        r = c.post("/new/installments/create/", {"patient_id": self.p.pk, "total": "15000", "rows": json.dumps(past)})
        self.assertIn("в прошлом", r.json()["error"])
        d = c.get(f"/new/installments/patient/{self.p.pk}/").json()
        self.assertEqual(d["plans"], [])        # отменённые не показываем
        page = c.get("/new/installments/")
        self.assertEqual(page.status_code, 200)
        # чужая клиника
        other_admin = User.objects.create(login="in_other", name="Б", clinic=self.other,
                                          role=Role.objects.get(name="admin_main", clinic__isnull=True))
        c2 = Client()
        c2.force_login(other_admin)
        self.assertEqual(c2.get(f"/new/installments/patient/{self.p.pk}/").status_code, 404)
        self.assertEqual(c2.post(f"/new/installments/{plan.pk}/cancel/").status_code, 404)
        r = c2.post("/new/installments/create/", {"patient_id": self.p.pk, "total": "15000", "rows": json.dumps(rows)})
        self.assertEqual(r.status_code, 404)
