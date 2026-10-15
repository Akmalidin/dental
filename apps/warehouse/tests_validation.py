from types import SimpleNamespace

from django.test import Client, TestCase

from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.users.models import Branch, Clinic, Role, User
from apps.warehouse.models import Product, WarehouseEntry


class WarehouseValidationTestCase(TestCase):
    """Отчёт 3, п. 10: поступление/списание — количество > 0, цена ≥ 0, материал своей клиники."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name="Склад", slug="wh-val")
        other = Clinic.objects.create(name="Чужая", slug="wh-oth")
        set_current_clinic(self.clinic)
        Branch.objects.create(name="Ф", address="-", phone="0", is_main=True, clinic=self.clinic)
        self.u = User.objects.create(login="wh_dir", name="Дир", clinic=self.clinic,
                                     role=Role.objects.get(name="admin_main", clinic__isnull=True))
        self.p = Product.objects.create(name="Композит", unit="г", quantity=10, clinic=self.clinic)
        self.foreign = Product.all_objects.create(name="Чужой", unit="г", quantity=10, clinic=other) \
            if hasattr(Product, "all_objects") else Product._base_manager.create(name="Чужой", unit="г",
                                                                                 quantity=10, clinic=other)
        clear_current_clinic()
        self.c = Client()
        self.c.force_login(self.u)

    def _entry(self, pid, qty, price):
        return self.c.post("/warehouse/entries/create/", {"product": [pid], "quantity": [qty], "price": [price]})

    def test_bad_values_rejected(self):
        for pid, qty, price in ((self.p.pk, "-5", "10"), (self.p.pk, "abc", "10"), (self.p.pk, "5", "-1"),
                                (self.foreign.pk, "5", "10")):
            r = self._entry(pid, qty, price)
            self.assertEqual(r.status_code, 200, (qty, price))
        self.assertEqual(WarehouseEntry._base_manager.count(), 0)
        r = self._entry(self.p.pk, "2,5", "100")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(WarehouseEntry._base_manager.count(), 1)

    def test_distribution_quantity_positive(self):
        from apps.warehouse.forms import WarehouseDistributionForm
        set_current_clinic(self.clinic)
        try:
            f = WarehouseDistributionForm({"product": self.p.pk, "quantity": "-1", "date": "2026-10-01"})
            self.assertFalse(f.is_valid())
            self.assertIn("quantity", f.errors)
        finally:
            clear_current_clinic()


class AssistantSectionAccessTestCase(TestCase):
    """Отчёт 3, п. 6: ИИ-помощник не показывает пациентов/расписание без доступа к разделу."""

    def test_patient_tools_respect_sections(self):
        from apps.notifications import assistant
        clinic = Clinic.objects.create(name="ИИ", slug="ai-sec")
        u = User.objects.create(login="ai_nurse", name="М", clinic=clinic, allowed_sections=["tasks"],
                                role=Role.objects.get(name="nurse", clinic__isnull=True))
        ctx = SimpleNamespace(user=u)
        self.assertIn("error", assistant._tool_search_patients(ctx, query="Ив"))
        self.assertIn("error", assistant._tool_patient_details(ctx, patient_id=1))
        self.assertIn("error", assistant._tool_doctor_day(ctx, date="2026-10-15"))
