import datetime as dt
import random

from django.utils import timezone

from apps.users.models import User, Role, Clinic, Branch
from apps.patients.models import Patient
from apps.services.models import Service
from apps.appointments.models import Appointment
from apps.finance.models import Payment
from apps.treatments.models import Treatment
from apps.warehouse.models import Supplier, ProductCategory, Product, WarehouseEntry
from apps.notifications.models import WaMessage

random.seed(7)

Clinic.objects.filter(slug="stom-demo").delete()
clinic = Clinic.objects.create(name="Стоматология «Асия»", slug="stom-demo")
branch = Branch.objects.create(name="Гл. филиал", address="г. Бишкек, ул. Чуй 120", phone="+996555000000", is_main=True, clinic=clinic)

admin_role = Role.objects.get(name="admin_main", clinic__isnull=True)
doctor_role = Role.objects.get(name="doctor", clinic__isnull=True)

director = User.objects.create(login="demo_director", name="Айгуль Асанова", email="demo_director@stom.asia", role=admin_role, clinic=clinic)
director.set_password("demo12345")
director.branches.add(branch)
director.save()

doctors_data = [
    ("Нурлан Беков", "Терапевт"),
    ("Динара Осмонова", "Ортодонт"),
]
doctors = []
for name, spec in doctors_data:
    d = User.objects.create(login=f"doc_{name.split()[0].lower()}", name=name, email=f"{name.split()[0].lower()}@stom.asia", role=doctor_role, clinic=clinic, specialty=spec)
    d.branches.add(branch)
    doctors.append(d)

services_data = [
    ("Консультация", 500), ("Пломбирование", 3200), ("Чистка зубов (Air Flow)", 2500),
    ("Удаление зуба", 1800), ("Установка брекетов", 45000), ("Отбеливание", 6000),
    ("Лечение кариеса", 2800), ("Имплантация", 35000),
]
services = [Service.objects.create(name=n, price=p, clinic=clinic) for n, p in services_data]

patients_data = [
    ("Мадина", "Джумабекова", "female", "+996700111222"),
    ("Азамат", "Токтогулов", "male", "+996555222333"),
    ("Гүлнара", "Абдырахманова", "female", "+996700333444"),
    ("Эркин", "Сатыбалдиев", "male", "+996555444555"),
    ("Айнура", "Молдогазиева", "female", "+996700555666"),
    ("Бакыт", "Орозов", "male", "+996555666777"),
    ("Жамиля", "Кайыпова", "female", "+996700777888"),
    ("Тимур", "Исаков", "male", "+996555888999"),
    ("Салтанат", "Нурланова", "female", "+996700999000"),
    ("Руслан", "Бекбоев", "male", "+996555000111"),
]
patients = []
for i, (fn, ln, g, phone) in enumerate(patients_data):
    p = Patient.objects.create(
        first_name=fn, last_name=ln, gender=g, phone=phone, clinic=clinic, branch=branch,
        birth_date=dt.date(1975 + i * 2, (i % 12) + 1, (i % 27) + 1),
    )
    patients.append(p)

# несколько правок карточки пациента разными сотрудниками — заполняет "Аудит-центр"
p0 = patients[0]
p0._history_user = director
p0.phone2 = "+996700111223"
p0.save()
p0._history_user = doctors[0]
p0.pin = "19850101" + str(random.randint(10000, 99999))[:6]
p0.save()

today = timezone.localdate()
start_hour = 9
statuses = [Appointment.STATUS_CONFIRMED, Appointment.STATUS_ARRIVED, Appointment.STATUS_COMPLETED,
            Appointment.STATUS_SCHEDULED, Appointment.STATUS_COMPLETED, Appointment.STATUS_CONFIRMED]
for i in range(10):
    doctor = doctors[i % 2]
    patient = patients[i % len(patients)]
    service = services[i % len(services)]
    hour = start_hour + (i * 45) // 60
    minute = (i * 45) % 60
    st = timezone.make_aware(dt.datetime.combine(today, dt.time(hour % 19 or 9, minute)))
    en = st + dt.timedelta(minutes=40)
    Appointment.objects.create(
        patient=patient, doctor=doctor, branch=branch, service=service,
        start_at=st, end_at=en, status=statuses[i % len(statuses)], clinic=clinic,
    )

for i in range(14):
    patient = patients[i % len(patients)]
    amount = random.choice([500, 1500, 2800, 3200, 6000, 12000])
    pay = Payment.objects.create(
        patient=patient, amount=amount, branch=branch, received_by=director,
        type=Payment.TYPE_INCOME, clinic=clinic,
    )
    Payment.objects.filter(pk=pay.pk).update(
        created_at=timezone.now() - dt.timedelta(days=i % 6, hours=i % 5)
    )

for i in range(4):
    Treatment.objects.create(patient=patients[i], doctor=doctors[i % 2], branch=branch, clinic=clinic)

supplier = Supplier.objects.create(name="ДентаСнаб ОсОО", phone="+996312000000", clinic=clinic)
cat_mat = ProductCategory.objects.create(name="Расходные материалы", clinic=clinic)
cat_anest = ProductCategory.objects.create(name="Анестетики", clinic=clinic)
products_data = [
    ("Композит светового отверждения", cat_mat, "уп.", 18, 5),
    ("Перчатки нитриловые M", cat_mat, "уп.", 40, 10),
    ("Анестетик Ультракаин", cat_anest, "уп.", 6, 8),
    ("Слюноотсосы", cat_mat, "уп.", 22, 5),
    ("Боры стоматологические", cat_mat, "шт.", 55, 15),
]
for name, cat, unit, qty, min_qty in products_data:
    prod = Product.objects.create(name=name, category=cat, unit=unit, quantity=qty, min_qty=min_qty, supplier=supplier, clinic=clinic)
    WarehouseEntry.objects.create(product=prod, quantity=qty, price=100, supplier=supplier, date=today, created_by=director)

wa_texts_out = [
    "Здравствуйте! Напоминаем о приёме завтра в 10:00.",
    "Ваша запись подтверждена на 15:30.",
    "Добрый день! Не забудьте про повторный визит.",
]
wa_texts_in = ["Да, буду", "Спасибо, подтверждаю", "Можно перенести на час позже?"]
for i, patient in enumerate(patients[:6]):
    channel = WaMessage.CH_WA if i % 2 == 0 else WaMessage.CH_TG
    m1 = WaMessage.objects.create(patient=patient, direction=WaMessage.DIR_OUT, channel=channel,
                                   phone=patient.phone, body=wa_texts_out[i % len(wa_texts_out)],
                                   sent_by=director, clinic=clinic)
    WaMessage.objects.filter(pk=m1.pk).update(created_at=timezone.now() - dt.timedelta(hours=i + 2))
    m2 = WaMessage.objects.create(patient=patient, direction=WaMessage.DIR_IN, channel=channel,
                                   phone=patient.phone, body=wa_texts_in[i % len(wa_texts_in)],
                                   read=(i % 3 != 0), clinic=clinic)
    WaMessage.objects.filter(pk=m2.pk).update(created_at=timezone.now() - dt.timedelta(hours=i + 1))

print("SEED_OK", "clinic_id=", clinic.id, "director_login=", director.login, "patient0_id=", patients[0].id)
