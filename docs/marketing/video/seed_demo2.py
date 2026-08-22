import datetime as dt
from django.utils import timezone

from apps.users.models import User, Clinic, Branch
from apps.patients.models import Patient, Lead, LeadSource
from apps.tasks.models import Task
from apps.treatments.models_plan import TreatmentPlan, TreatmentPlanStage, TreatmentPlanItem
from apps.services.models import Service
from apps.technicians.models import Technician, TechnicianTask
from apps.treatments.models import Treatment

clinic = Clinic.objects.get(slug="stom-demo")
branch = Branch.objects.get(clinic=clinic)
director = User.objects.get(login="demo_director")
doctors = list(User.objects.filter(clinic=clinic, role__name="doctor"))
patients = list(Patient.objects.filter(clinic=clinic).order_by("id"))
services = list(Service.objects.filter(clinic=clinic))

src_inst = LeadSource.objects.create(name="Instagram")
src_ref = LeadSource.objects.create(name="Рекомендация")
src_site = LeadSource.objects.create(name="Сайт stom.asia")

leads_data = [
    ("Мээрим Careева", "+996700123456", src_inst, Lead.STAGE_NEW),
    ("Данияр Уулу", "+996555234567", src_site, Lead.STAGE_THINKING),
    ("Айжан Токтосунова", "+996700345678", src_ref, Lead.STAGE_BOOKED),
    ("Бекзат Асанов", "+996555456789", src_inst, Lead.STAGE_NOTREACHED),
    ("Нурай Жумалиева", "+996700567890", src_site, Lead.STAGE_CAME),
]
for name, phone, src, stage in leads_data:
    Lead.objects.create(name=name, phone=phone, source=src, stage=stage, clinic=clinic, assigned_to=director)

tasks_data = [
    ("Позвонить пациенту Токтогулов А. — подтвердить приём", Task.PRIORITY_HIGH, Task.STATUS_PENDING),
    ("Заказать анестетик у поставщика", Task.PRIORITY_MEDIUM, Task.STATUS_PENDING),
    ("Обновить прайс-лист услуг", Task.PRIORITY_LOW, Task.STATUS_IN_PROGRESS),
    ("Провести инструктаж нового администратора", Task.PRIORITY_MEDIUM, Task.STATUS_DONE),
]
for title, prio, status in tasks_data:
    t = Task.objects.create(title=title, priority=prio, status=status, clinic=clinic, created_by=director)
    t.assigned_to.add(director)

plan = TreatmentPlan.objects.create(
    patient=patients[0], doctor=doctors[0], title="План лечения — санация полости рта",
    status=TreatmentPlan.STATUS_IN_PROGRESS,
)
stage1 = TreatmentPlanStage.objects.create(plan=plan, title="Этап 1 — лечение кариеса", sort_order=1)
TreatmentPlanItem.objects.create(plan=plan, stage=stage1, service=services[6], quantity=2, price=services[6].price, status=TreatmentPlanItem.STATUS_DONE)
stage2 = TreatmentPlanStage.objects.create(plan=plan, title="Этап 2 — протезирование", sort_order=2)
TreatmentPlanItem.objects.create(plan=plan, stage=stage2, service=services[7], quantity=1, price=services[7].price, status=TreatmentPlanItem.STATUS_PENDING)

technician = Technician.objects.create(name="Марат Джолдошев", clinic=clinic)
today = timezone.localdate()
for i in range(3):
    treatment = Treatment.objects.create(patient=patients[i], doctor=doctors[i % 2], branch=branch, clinic=clinic)
    TechnicianTask.objects.create(
        technician=technician, treatment=treatment, service=services[7],
        status=[TechnicianTask.STATUS_IN_PROGRESS, TechnicianTask.STATUS_TRANSFERRED, TechnicianTask.STATUS_INSTALLED][i],
        clinic=clinic,
    )

print("SEED2_OK")
