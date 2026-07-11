"""Standard dental services & warehouse materials for one-click seeding."""

# Категория → список (название, цена, длительность_мин)
DENTAL_SERVICES = {
    "Терапия": [
        ("Консультация и осмотр", 500, 20),
        ("Лечение кариеса (1 поверхность)", 2500, 40),
        ("Лечение среднего кариеса", 3000, 50),
        ("Лечение глубокого кариеса", 3500, 60),
        ("Лечение пульпита (1 канал)", 5000, 60),
        ("Лечение пульпита (2 канала)", 7000, 80),
        ("Лечение пульпита (3 канала)", 9000, 90),
        ("Лечение периодонтита", 6000, 70),
        ("Художественная реставрация", 5000, 70),
        ("Пломба световая", 3000, 45),
        ("Временная пломба", 800, 20),
        ("Распломбировка канала", 2000, 40),
    ],
    "Хирургия": [
        ("Удаление зуба (простое)", 2000, 30),
        ("Удаление зуба (сложное)", 4000, 50),
        ("Удаление зуба мудрости", 5000, 60),
        ("Резекция верхушки корня", 6000, 70),
        ("Вскрытие абсцесса", 2500, 30),
        ("Кюретаж лунки", 1500, 25),
    ],
    "Ортопедия": [
        ("Коронка металлокерамика", 12000, 60),
        ("Коронка циркониевая", 20000, 60),
        ("Коронка цельнолитая", 8000, 60),
        ("Винир керамический", 25000, 70),
        ("Вкладка культевая", 6000, 50),
        ("Съёмный протез (полный)", 30000, 90),
        ("Бюгельный протез", 35000, 90),
        ("Мостовидный протез (за единицу)", 12000, 60),
    ],
    "Ортодонтия": [
        ("Консультация ортодонта", 700, 30),
        ("Брекеты металлические (1 челюсть)", 45000, 90),
        ("Брекеты керамические (1 челюсть)", 70000, 90),
        ("Элайнеры (комплект)", 150000, 60),
        ("Ретейнер", 8000, 40),
        ("Активация брекетов", 2000, 30),
    ],
    "Имплантология": [
        ("Консультация имплантолога", 700, 30),
        ("Установка импланта", 45000, 90),
        ("Формирователь десны", 8000, 30),
        ("Абатмент", 12000, 40),
        ("Синус-лифтинг", 40000, 90),
        ("Костная пластика", 35000, 80),
    ],
    "Гигиена и профилактика": [
        ("Профессиональная чистка", 4000, 50),
        ("Ультразвуковая чистка", 3000, 40),
        ("Air Flow", 3500, 40),
        ("Фторирование", 1500, 20),
        ("Покрытие фторлаком", 1000, 20),
        ("Отбеливание ZOOM", 25000, 90),
        ("Герметизация фиссур (1 зуб)", 1500, 25),
    ],
}

# Категория материала → список (название, единица, мин_остаток)
DENTAL_MATERIALS = {
    "Анестезия": [
        ("Артикаин (Ультракаин) карпулы", "карпула", 50),
        ("Лидокаин 2%", "флакон", 10),
        ("Иглы карпульные", "шт", 100),
        ("Аппликационная анестезия (гель)", "шт", 5),
    ],
    "Пломбировочные материалы": [
        ("Композит светоотверждаемый", "шприц", 10),
        ("Бонд (адгезив)", "флакон", 5),
        ("Протравочный гель (37%)", "шприц", 5),
        ("Стеклоиономерный цемент", "набор", 5),
        ("Временная пломба (Дентин-паста)", "банка", 5),
        ("Прокладка (Кальцид)", "банка", 3),
    ],
    "Эндодонтия": [
        ("K-файлы (набор)", "набор", 10),
        ("ProTaper (набор)", "набор", 10),
        ("Гуттаперчевые штифты", "упак", 10),
        ("Силер (АН Plus)", "набор", 3),
        ("Бумажные штифты", "упак", 10),
        ("Гипохлорит натрия", "флакон", 5),
    ],
    "Инструменты и боры": [
        ("Боры алмазные", "шт", 50),
        ("Боры твердосплавные", "шт", 50),
        ("Полиры", "шт", 30),
        ("Матрицы металлические", "упак", 20),
        ("Клинья деревянные", "упак", 20),
    ],
    "Расходники": [
        ("Перчатки нитриловые", "пара", 200),
        ("Маски одноразовые", "шт", 200),
        ("Слюноотсосы", "шт", 200),
        ("Коффердам (платки)", "упак", 10),
        ("Салфетки нагрудные", "шт", 200),
        ("Стаканы одноразовые", "шт", 200),
    ],
    "Ортопедия (материалы)": [
        ("Оттискная масса А-силикон", "набор", 5),
        ("Оттискные ложки", "шт", 20),
        ("Гипс стоматологический", "кг", 10),
        ("Воск базисный", "упак", 5),
    ],
    "Профгигиена": [
        ("Паста для чистки", "банка", 5),
        ("Порошок Air Flow", "упак", 5),
        ("Штрипсы", "упак", 10),
        ("Фторлак", "флакон", 5),
    ],
}


# ── ЭМК шаблоны (стандартные диагнозы) ──────────────────────────────────────
EMR_TEMPLATES = [
    {
        "name": "Средний кариес",
        "complaints": "На наличие кариозной полости, попадание пищи в кариозную полость, кратковременные боли от температурных раздражителей.",
        "anamnesis": "Зуб ранее не лечен.",
        "external_exam": "Лицо симметричное, регионарные лимфатические узлы не пальпируются, слизистая оболочка полости рта бледно-розового цвета, влажная, без видимых патологических изменений.",
        "objective": "На жевательной поверхности зуба кариозная полость в пределах плащевого дентина. Зондирование болезненно по эмалево-дентинному соединению, перкуссия безболезненна, температурная реакция на холодную воду кратковременная.",
        "diagnosis": "Средний кариес, К02.1.",
        "treatment": "Под аппликационной анестезией препарирование кариозной полости, медикаментозная обработка, постановка пломбы из светоотверждаемого композита, шлифовка, полировка.",
        "recommendations": "Гигиена полости рта 2 раза в день, профосмотр через 6 месяцев.",
    },
    {
        "name": "Глубокий кариес",
        "complaints": "Боли от температурных и механических раздражителей, быстро проходящие после устранения раздражителя.",
        "anamnesis": "Зуб ранее не лечен.",
        "external_exam": "Без видимых патологических изменений.",
        "objective": "Глубокая кариозная полость, выполненная размягчённым дентином. Зондирование болезненно по дну, перкуссия безболезненна.",
        "diagnosis": "Глубокий кариес, К02.1.",
        "treatment": "Препарирование, лечебная прокладка, изолирующая прокладка, постановка пломбы из композита.",
        "recommendations": "Контроль через 6 месяцев.",
    },
    {
        "name": "Хронический пульпит",
        "complaints": "Ноющие боли, усиливающиеся от температурных раздражителей, длительно не проходящие.",
        "anamnesis": "Зуб ранее болел.",
        "external_exam": "Без особенностей.",
        "objective": "Глубокая кариозная полость, сообщающаяся с полостью зуба. Зондирование болезненно в одной точке.",
        "diagnosis": "Хронический пульпит, К04.0.",
        "treatment": "Под проводниковой анестезией эндодонтическое лечение: механическая и медикаментозная обработка каналов, пломбирование каналов, реставрация коронковой части.",
        "recommendations": "Рентген-контроль, ортопедическое лечение при необходимости.",
    },
    {
        "name": "Хронический периодонтит",
        "complaints": "Дискомфорт при накусывании, чувство «выросшего зуба».",
        "anamnesis": "Зуб ранее лечен/болел.",
        "external_exam": "Регионарные лимфоузлы могут быть слегка увеличены.",
        "objective": "Перкуссия слабоболезненна. На рентгенограмме разрежение костной ткани в области верхушки корня.",
        "diagnosis": "Хронический периодонтит, К04.5.",
        "treatment": "Эндодонтическое лечение, медикаментозная обработка каналов, временное и постоянное пломбирование каналов под рентген-контролем.",
        "recommendations": "Рентген-контроль через 3-6 месяцев.",
    },
]

# ── Шаблоны документов (договоры/согласия) ──────────────────────────────────
DOC_TEMPLATES = [
    {
        "name": "Информированное добровольное согласие",
        "doc_type": "consent",
        "content": ("Я, {{patient_name}}, дата рождения {{patient_dob}}, добровольно даю согласие на "
                    "медицинское вмешательство в клинике «{{clinic_name}}».\n\n"
                    "Мне разъяснены характер и план лечения ({{services}}), возможные осложнения и риски. "
                    "Я согласен(на) на проведение лечения врачом {{doctor_name}}.\n\n"
                    "Дата: {{date}}"),
    },
    {
        "name": "Договор на оказание стоматологических услуг",
        "doc_type": "contract",
        "content": ("ДОГОВОР на оказание платных стоматологических услуг\n\n"
                    "Клиника «{{clinic_name}}» ({{clinic_address}}, тел. {{clinic_phone}}), именуемая «Исполнитель», "
                    "и пациент {{patient_name}} (тел. {{patient_phone}}), именуемый «Заказчик», заключили договор "
                    "о нижеследующем:\n\n"
                    "1. Исполнитель оказывает услуги: {{services}}.\n"
                    "2. Заказчик обязуется оплатить услуги согласно прейскуранту.\n"
                    "3. Лечащий врач: {{doctor_name}}.\n\n"
                    "Дата: {{date}}\nПодписи сторон: _________________ / _________________"),
    },
    {
        "name": "Направление",
        "doc_type": "referral",
        "content": ("НАПРАВЛЕНИЕ\n\nПациент: {{patient_name}}, {{patient_dob}}\n"
                    "Направляется на: {{services}}\nВрач: {{doctor_name}}\nКлиника: {{clinic_name}}\nДата: {{date}}"),
    },
    {
        "name": "Гарантийный талон",
        "doc_type": "certificate",
        "content": ("ГАРАНТИЙНЫЙ ТАЛОН\n\nКлиника «{{clinic_name}}» гарантирует качество выполненных работ "
                    "для пациента {{patient_name}}.\nУслуги: {{services}}\nВрач: {{doctor_name}}\nДата: {{date}}\n\n"
                    "Гарантийный срок исчисляется с даты оказания услуги при соблюдении рекомендаций врача."),
    },
]


def seed_emr_and_docs():
    """Create standard EMR templates and document templates (idempotent).

    Uses exists()+create() instead of get_or_create() because some clinics
    already have duplicate-named rows from earlier, non-idempotent seed runs —
    get_or_create()'s get() raises MultipleObjectsReturned on those.
    """
    from apps.treatments.models_emr import MedicalRecordTemplate
    from apps.settings_clinic.models_documents import DocumentTemplate
    created = {"emr": 0, "docs": 0}
    for t in EMR_TEMPLATES:
        if not MedicalRecordTemplate.objects.filter(name=t["name"]).exists():
            MedicalRecordTemplate.objects.create(**t)
            created["emr"] += 1
    for d in DOC_TEMPLATES:
        if not DocumentTemplate.objects.filter(name=d["name"]).exists():
            DocumentTemplate.objects.create(**d)
            created["docs"] += 1
    return created


def seed_dental(get_user=None):
    """Idempotently create categories, services and warehouse materials (qty=0)."""
    from apps.services.models import ServiceCategory, Service
    from apps.warehouse.models import Product, ProductCategory

    created = {"service_cats": 0, "services": 0, "material_cats": 0, "materials": 0}

    for order, (cat_name, items) in enumerate(DENTAL_SERVICES.items()):
        cat, made = ServiceCategory.objects.get_or_create(
            name=cat_name, defaults={"sort_order": order}
        )
        if made:
            created["service_cats"] += 1
        for name, price, dur in items:
            obj, made = Service.objects.get_or_create(
                name=name, defaults={"category": cat, "price": price, "duration": dur, "is_active": True}
            )
            if made:
                created["services"] += 1

    for cat_name, items in DENTAL_MATERIALS.items():
        cat, made = ProductCategory.objects.get_or_create(name=cat_name)
        if made:
            created["material_cats"] += 1
        for name, unit, minq in items:
            obj, made = Product.objects.get_or_create(
                name=name, defaults={"category": cat, "unit": unit, "quantity": 0, "min_qty": minq, "is_active": True}
            )
            if made:
                created["materials"] += 1

    # also seed EMR templates and document templates
    extra = seed_emr_and_docs()
    created["emr"] = extra["emr"]
    created["docs"] = extra["docs"]

    return created


def seed_demo(reset=False):
    """Демо-данные для показа клиентам: врачи, пациенты, записи на эту неделю,
    приёмы с оплатами и долгами. Идемпотентно (по флагу demo в заметках/логине).
    Запускать в контексте нужной клиники (set_current_clinic)."""
    import random
    from datetime import timedelta, time as dtime, datetime as dt
    from decimal import Decimal
    from django.utils import timezone
    from apps.tenancy import get_current_clinic
    from apps.users.models import User, Role, Branch
    from apps.patients.models import Patient
    from apps.services.models import Service
    from apps.appointments.models import Appointment
    from apps.treatments.models import Treatment, TreatmentCure
    from apps.finance.models import Payment

    out = {"doctors": 0, "patients": 0, "appointments": 0, "treatments": 0, "payments": 0}
    branch = Branch.objects.filter(is_main=True).first() or Branch.objects.first()
    if not branch:
        branch = Branch.objects.create(name="Демо филиал", address="г. Бишкек", phone="+996", is_main=True)
    drole, _ = Role.objects.get_or_create(name=Role.DOCTOR)

    # Врачи
    doctor_names = ["Иванов Иван", "Петрова Анна", "Сидоров Пётр"]
    doctors = []
    for i, dn in enumerate(doctor_names):
        login = f"demo_doc{i+1}"
        u = User.objects.filter(login=login).first()
        if not u:
            u = User(login=login, name=dn, role=drole, clinic=get_current_clinic())
            u.set_password("demo12345")
            u.save()
            u.branches.add(branch)
            out["doctors"] += 1
        doctors.append(u)

    services = list(Service.objects.filter(is_active=True)[:20]) or []

    # Пациенты
    first = ["Алмаз", "Айгуль", "Бакыт", "Нурлан", "Жылдыз", "Эрмек", "Айдана", "Тимур",
             "Гульнара", "Данияр", "Асель", "Руслан", "Чолпон", "Максат", "Динара"]
    last = ["Кадыров", "Осмонова", "Турдубеков", "Сатыбалдиев", "Абдыкадырова", "Маматов",
            "Бекова", "Усенов", "Жээнбеков", "Алиева", "Токтосунов", "Исраилова"]
    patients = []
    for i in range(15):
        phone = f"+99670{random.randint(1000000,9999999)}"
        fn, ln = first[i % len(first)], last[i % len(last)]
        p = Patient.objects.filter(first_name=fn, last_name=ln, phone__startswith="+99670").first()
        if not p:
            p = Patient.objects.create(
                first_name=fn, last_name=ln, phone=phone, branch=branch,
                gender=random.choice(["male", "female"]),
                birth_date=timezone.now().date() - timedelta(days=random.randint(7000, 22000)),
            )
            out["patients"] += 1
        patients.append(p)

    if not doctors or not services or not patients:
        return out

    today = timezone.localdate()
    # Записи на эту неделю (±3 дня) для календаря
    for day_off in range(-2, 4):
        day = today + timedelta(days=day_off)
        for _ in range(random.randint(3, 6)):
            doc = random.choice(doctors)
            hour = random.randint(9, 18)
            start = timezone.make_aware(dt.combine(day, dtime(hour, random.choice([0, 30]))))
            svc = random.choice(services)
            end = start + timedelta(minutes=svc.duration or 30)
            # без грубых пересечений
            if Appointment.all_objects.filter(doctor=doc, start_at=start).exists():
                continue
            status = "completed" if day_off < 0 else random.choice(["scheduled", "confirmed", "scheduled"])
            a = Appointment(patient=random.choice(patients), doctor=doc, branch=branch,
                            service=svc, start_at=start, end_at=end, status=status,
                            clinic=get_current_clinic())
            a.save()
            out["appointments"] += 1

    # Приёмы с оплатами/долгами
    for _ in range(12):
        p = random.choice(patients)
        doc = random.choice(doctors)
        t = Treatment.objects.create(patient=p, doctor=doc, branch=branch,
                                     status=random.choice(["completed", "completed", "in_progress"]))
        total = Decimal(0)
        for _ in range(random.randint(1, 3)):
            svc = random.choice(services)
            qty = random.randint(1, 2)
            price = svc.price or Decimal(random.randint(500, 5000))
            TreatmentCure.objects.create(treatment=t, service=svc, doctor=doc,
                                         quantity=qty, price=price,
                                         tooth_number=str(random.randint(11, 48)))
            total += price * qty
        t.total_amount = total
        t.save(update_fields=["total_amount"])
        out["treatments"] += 1
        # оплата: полностью / частично / без оплаты (долг)
        roll = random.random()
        pay = total if roll < 0.5 else (total / 2 if roll < 0.8 else Decimal(0))
        if pay > 0:
            Payment.objects.create(patient=p, treatment=t, amount=pay, method="cash",
                                   type="income", branch=branch, received_by=doc)
            t.paid_amount = pay
            t.save(update_fields=["paid_amount"])
            out["payments"] += 1

    # демо-уведомления для всех админов/суперадминов
    try:
        from apps.notifications.models import Notification
        from apps.users.models import User as U3
        from django.db.models import Q
        admins = U3.objects.filter(is_active=True).filter(
            Q(is_superuser=True) | Q(role__name__in=["superadmin", "admin_main", "admin"])
        )
        demo_notifs = [
            ("Новая запись на приём", "Кадыров Алмаз — сегодня 14:30"),
            ("Оплата получена", "Осмонова Айгуль внесла 3 500 сом"),
            ("Низкий остаток материала", "Анестетик — осталось мало на складе"),
        ]
        for adm in admins:
            for title, body in demo_notifs:
                Notification.objects.get_or_create(user=adm, title=title, defaults={"body": body, "type": "system"})
    except Exception:
        pass

    return out


def seed_tooth_statuses():
    """Create default tooth-chart statuses (idempotent)."""
    from apps.treatments.models_teeth import ToothStatus, DEFAULT_TOOTH_STATUSES
    n = 0
    for order, (code, name, color) in enumerate(DEFAULT_TOOTH_STATUSES):
        _, made = ToothStatus.objects.get_or_create(
            code=code, defaults={"name": name, "color": color, "sort_order": order}
        )
        if made:
            n += 1
    return n
