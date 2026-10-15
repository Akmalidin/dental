import json
from decimal import Decimal

from django.test import Client

from apps.tenancy import clear_current_clinic, set_current_clinic
from apps.treatments.models import Treatment
from apps.treatments.tests import _VisitWizardTestBase


class VisitCardGuardsTestCase(_VisitWizardTestBase):
    """Отчёт 3, п. 1–5: карта приёма после завершения, цена с клиента,
    связь заказов технику со строками, двойное «Завершить», списание материалов."""

    def _start(self):
        self.client.get(f"/new/visit/start/?appointment={self.appt.pk}")
        return Treatment.objects.get(appointment=self.appt)

    def _save(self, t, plan, client=None):
        return (client or self.client).post(f"/treatments/visit/{t.pk}/save/", data=json.dumps({"plan": plan}),
                                            content_type="application/json")

    def _commit(self, t, plan):
        return self.client.post(f"/treatments/visit/{t.pk}/commit/", data=json.dumps({"plan": plan}),
                                content_type="application/json")

    def test_bad_price_falls_back_to_price_list(self):
        t = self._start()
        self._save(t, [{"service_id": self.service.pk, "price": -5000, "done": True},
                       {"service_id": self.service.pk, "tooth": "11", "price": "abc", "qty": "x", "done": True}])
        prices = sorted(c.price for c in t.cures.all())
        self.assertEqual(prices, [Decimal("2500"), Decimal("2500")])
        t.refresh_from_db()
        self.assertGreaterEqual(t.total_amount, 0)

    def test_completed_visit_plan_locked_for_doctor(self):
        t = self._start()
        plan = [{"service_id": self.service.pk, "price": 2500, "done": True}]
        self.assertTrue(self._commit(t, plan).json()["ok"])
        doc = Client()
        doc.force_login(self.doctor)
        r = self._save(t, [{"service_id": self.service.pk, "price": 1, "done": True}], client=doc)
        self.assertTrue(r.json().get("plan_locked"))
        self.assertEqual([c.price for c in t.cures.all()], [Decimal("2500")])
        # директор (право правки платежей) может поправить, правка пишется в журнал
        from apps.users.models import AuditEvent
        r = self._save(t, [{"service_id": self.service.pk, "price": 2000, "done": True}])
        self.assertFalse(r.json().get("plan_locked"))
        self.assertEqual([c.price for c in t.cures.all()], [Decimal("2000")])
        self.assertTrue(AuditEvent.objects.filter(action="treatment_services_edit").exists())

    def test_second_commit_rejected(self):
        t = self._start()
        plan = [{"service_id": self.service.pk, "price": 2500, "done": True}]
        self.assertEqual(self._commit(t, plan).status_code, 200)
        self.assertEqual(self._commit(t, plan).status_code, 403)

    def test_writeoff_on_commit_after_autosave_and_lab_link_kept(self):
        from apps.services.models import Service, ServiceMaterialNorm
        from apps.technicians.models import Technician, TechnicianTask
        from apps.warehouse.models import Product, WarehouseDistribution
        set_current_clinic(self.clinic)
        product = Product.objects.create(name="Композит", unit="г", quantity=100, clinic=self.clinic)
        ServiceMaterialNorm.objects.create(service=self.service, product=product, quantity=Decimal("2"))
        crown = Service.objects.create(name="Коронка", price=20000, is_lab=True, clinic=self.clinic)
        tech = Technician.objects.create(name="Лаб", clinic=self.clinic)
        clear_current_clinic()
        t = self._start()
        plan = [{"service_id": self.service.pk, "price": 2500, "done": True},
                {"service_id": crown.pk, "tooth": "36", "price": 20000, "done": True, "technician_id": str(tech.pk)}]
        self._save(t, plan)   # автосохранение до «Завершить»
        self.assertTrue(self._commit(t, plan).json()["ok"])
        self.assertEqual(WarehouseDistribution.objects.filter(product=product).count(), 1)
        order = TechnicianTask.all_clinics.get(treatment=t)
        self.assertIsNotNone(order.cure_id)
        # пересохранение карты директором не отвязывает заказ
        self._save(t, plan)
        order.refresh_from_db()
        self.assertIsNotNone(order.cure_id)
        cure = t.cures.get(service=crown)
        self.assertEqual((order.cure_id, cure.lab_order_id), (cure.pk, order.pk))
        self.assertEqual(TechnicianTask.all_clinics.filter(treatment=t).count(), 1)
