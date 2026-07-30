# Модуль 1: Касса как POS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать администратору/кассиру SADAF полноценную кассу: открытие/закрытие смены с подсчётом остатка, продажа товаров со склада (в т.ч. разовым клиентам), выдача авансов сотрудникам, кассовый отчёт (с экспортом в Excel) и быстрый доступ к оплате долгов из списка должников.

**Architecture:** Классические Django views + forms + server-rendered templates (Alpine.js для интерактивности) — НЕ DRF/Vue SPA. Это осознанное отклонение от исходного ТЗ (которое предполагало DRF+Vue3): в проекте вся боевая бизнес-логика (см. `apps/finance/views.py`) реализована через Django views/templates, а параллельная Vue-SPA в `frontend/` примитивна и не подключена к этой логике (уведомления, QR-чеки, распределение платежей). Пользователь подтвердил решение придерживаться существующей архитектуры.

**Tech Stack:** Django 5.1, Alpine.js (уже подключен в `base.html` через CDN), существующая CSS-дизайн-система `static/css/app.css` (фиолетовая тема, CSS custom properties, light+dark), openpyxl (уже в requirements.txt) для экспорта.

## Global Constraints

- **Мультитенантность:** реальная изоляция в проекте — НЕ django-tenants schema-per-tenant (несмотря на то, что пакет установлен и модель `apps.tenants.Tenant` существует). Настоящая изоляция — через `clinic` FK и `apps.tenancy.ClinicScopedModel` / `ClinicSoftDeleteModel` (thread-local текущая клиника). Все новые модели наследуются от них, а не пишут собственный `clinic` FK вручную.
- **Дизайн-система:** используем существующую тему `static/css/app.css` (переменные `--primary`, `--text`, `--surface`, классы `.card`, `.btn-success`, `.btn-ghost`, `.tbl`, `.badge-*`, `.modal-overlay`/`.modal-box`, `.pill-tabs`/`.pill-tab`). Палитра/шрифты из исходного ТЗ (mint/navy/amber, Fraunces/IBM Plex Mono) НЕ вводятся — пользователь подтвердил использовать существующую тему для консистентности.
- **StockItem → Product:** в ТЗ упоминается модель `StockItem` — в реальном коде это `apps.warehouse.models.Product`. Все ссылки ниже используют `Product`.
- **Валюта:** отображается через `clinic_settings.currency_label` в шаблонах (см. `payments.html`), не хардкодить «сом».
- **Не трогать:** интейк-визард, зубную формулу, `apps/users/views.py::audit_center` (жёстко привязан к Patient/Treatment — расширение не входит в Модуль 1), существующие модели `Payment`/`Expense`/`PatientAdvance` (только читаем/агрегируем, не меняем их поведение).
- **Продажа товара НЕ создаёт `Payment`:** `Payment.save()` вызывает `patient.recalc_balance()`, которая считает баланс как `оплаты − (приёмы − скидки)`. Продажа товара — не приём (Treatment), поэтому создание `Payment` для неё исказило бы баланс пациента (сделало бы вид, что у него огромная переплата). `ProductSale` — самостоятельная финансовая сущность, агрегируется в кассовом отчёте отдельной строкой, в `Payment`/баланс пациента не пишется.
- **Миграции через `makemigrations`:** `Patient` и `Treatment` используют `django-simple-history` (`HistoricalRecords()`) — при добавлении поля в `Patient` нужно зеркальное поле в `HistoricalPatient`. Не писать миграции руками — генерировать через `python manage.py makemigrations <app>` и проверять сгенерированный файл.
- **Venv:** `.venv/Scripts/python.exe` (не `venv/` — тот устаревший, судя по дате модификации).
- **Тесты:** `django.test.TestCase`, запуск `python manage.py test apps.finance apps.patients apps.warehouse apps.users`.
- **Модуль отключается по клинике (пользовательское требование, применимо ко ВСЕМ будущим модулям 1-9, не только к Кассе):** в проекте уже есть готовый механизм — `ClinicSettings.ALL_MODULES` (`apps/settings_clinic/models.py`) — список `(ключ, подпись)`, `Clinic.enabled_modules` (JSONField на клинике, пусто = все модули включены) и суперадминская форма-переключатель в `templates/users/superadmin.html` (она уже рендерит `ALL_MODULES` в цикле — новых полей формы добавлять не нужно, чекбокс появится сам). Пункт сайдбара для КАЖДОГО нового модуля должен быть обёрнут в `{% if '<ключ>' in enabled_modules and '<секция>' in user_sections %}`, как уже сделано для «Финансы»/«Склад»/«Техники» и т.д. **Важно:** это только UI-скрытие (существующая конвенция во всём проекте — `module_enabled()` на `ClinicSettings` определён, но нигде не вызывается для блокировки самих views/urls) — серверная блокировка доступа к `/finance/cash/` при отключённом модуле в проект пока не добавлена нигде и намеренно не добавляется здесь, чтобы не расходиться с поведением всех остальных модулей.

---

## Task 1: Поля-предпосылки — Patient.type, Product.available_for_sale/sale_price, User.cash_shift_today_only

**Files:**
- Modify: `apps/patients/models.py` (класс `Patient`)
- Modify: `apps/warehouse/models.py` (класс `Product`)
- Modify: `apps/users/models.py` (класс `User`)
- Test: `apps/patients/tests.py`, `apps/warehouse/tests.py` (создать, файла нет), `apps/users/tests.py` (**уже существует** — создан отдельной срочной правкой межклиничной утечки/цвета сотрудника, содержит `UserColorFieldTestCase`; здесь только ДОПОЛНИТЬ новым классом, не перезаписывать файл)

**Interfaces:**
- Produces: `Patient.TYPE_REGULAR`, `Patient.TYPE_WALK_IN`, `Patient.type` (str) — используется в Task 5 (создание разового клиента).
- Produces: `Product.available_for_sale` (bool), `Product.sale_price` (Decimal|None) — используется в Task 3, 5, 9.
- Produces: `User.cash_shift_today_only` (bool, default False) — используется в Task 4.

- [ ] **Step 1: Добавить тип пациента в `apps/patients/models.py`**

В классе `Patient`, сразу после `GENDER_CHOICES` (строка 73):

```python
    TYPE_REGULAR = "regular"
    TYPE_WALK_IN = "walk_in"
    TYPE_CHOICES = [
        (TYPE_REGULAR, "Обычный"),
        (TYPE_WALK_IN, "Разовый клиент"),
    ]
```

И добавить поле после `notes` (строка 138):

```python
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_REGULAR, verbose_name="Тип пациента")
```

- [ ] **Step 2: Добавить поля продажи в `apps/warehouse/models.py`, класс `Product`**

После `is_active` (строка 49):

```python
    available_for_sale = models.BooleanField(default=False, verbose_name="Доступен для продажи")
    sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Цена продажи"
    )
```

- [ ] **Step 3: Добавить флаг ограничения в `apps/users/models.py`, класс `User`**

После `can_view_all_appointments` (строка 175):

```python
    cash_shift_today_only = models.BooleanField(
        default=False, verbose_name="Кассовые операции только за сегодня",
        help_text="Если включено — закрытие смены и кассовые операции с прошлой датой запрещены",
    )
```

- [ ] **Step 4: Сгенерировать и применить миграции**

```bash
.venv/Scripts/python.exe manage.py makemigrations patients warehouse users
.venv/Scripts/python.exe manage.py migrate
```

Проверить, что для `patients` сгенерировались поля и в `Patient`, и в `HistoricalPatient` (зеркало simple_history) в одном файле `apps/patients/migrations/0016_*.py`.

- [ ] **Step 5: Написать тесты**

`apps/warehouse/tests.py` (новый файл):

```python
from decimal import Decimal
from django.test import TestCase
from apps.warehouse.models import Product, ProductCategory


class ProductSaleFieldsTestCase(TestCase):
    def test_defaults(self):
        p = Product.objects.create(name="Щётка", unit="шт")
        self.assertFalse(p.available_for_sale)
        self.assertIsNone(p.sale_price)

    def test_can_mark_available_for_sale(self):
        p = Product.objects.create(name="Паста", unit="шт", available_for_sale=True, sale_price=Decimal("350.00"))
        self.assertTrue(p.available_for_sale)
        self.assertEqual(p.sale_price, Decimal("350.00"))
```

Добавить в конец `apps/users/tests.py` (файл уже существует — только добавить этот класс, не трогая уже имеющийся `UserColorFieldTestCase`):

```python
class CashShiftPermissionFieldTestCase(TestCase):
    def test_default_false(self):
        u = User.objects.create(login="cashier1", name="Кассир", email="c1@test.local")
        self.assertFalse(u.cash_shift_today_only)
```

(`TestCase`/`User` уже импортированы в начале файла — повторно не добавлять.)

В `apps/patients/tests.py` добавить (в конец файла) новый класс:

```python
class PatientTypeTestCase(TestCase):
    def test_default_type_is_regular(self):
        branch = Branch.objects.create(name="M", address="-", phone="0", is_main=True)
        p = Patient.objects.create(first_name="A", last_name="B", phone="1", branch=branch)
        self.assertEqual(p.type, Patient.TYPE_REGULAR)

    def test_walk_in_type(self):
        branch = Branch.objects.create(name="M2", address="-", phone="0", is_main=True)
        p = Patient.objects.create(first_name="Разовый", last_name="", phone="", branch=branch, type=Patient.TYPE_WALK_IN)
        self.assertEqual(p.type, Patient.TYPE_WALK_IN)
```

- [ ] **Step 6: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.patients apps.warehouse apps.users -v 2
```
Expected: все новые тесты PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/patients/models.py apps/patients/migrations apps/patients/tests.py \
        apps/warehouse/models.py apps/warehouse/migrations apps/warehouse/tests.py \
        apps/users/models.py apps/users/migrations apps/users/tests.py
git commit -m "Модуль 1 (Касса): поля-предпосылки — тип пациента, товары для продажи, флаг кассовых прав"
```

---

## Task 2: Модели `CashShift` и `StaffAdvance`

**Files:**
- Modify: `apps/finance/models.py`
- Test: `apps/finance/tests.py` (**уже существует** — создан отдельной срочной правкой межклиничной утечки пациентов, содержит `PaymentFormClinicIsolationTestCase` и её импорты `User, Branch, Clinic, Patient, PaymentForm, set_current_clinic, clear_current_clinic`; здесь только ДОПОЛНИТЬ новыми классами/импортами, не перезаписывать файл)

**Interfaces:**
- Consumes: `Branch` (`apps.users.models`), `settings.AUTH_USER_MODEL`, `ClinicScopedModel` (`apps.tenancy`), `Payment` (уже в файле).
- Produces: `CashShift` (поля: `branch`, `opened_by`, `opened_at`, `closed_at`, `closed_by`, `opening_balance`, `closing_balance`, `status`, метод `compute_expected_closing()`), `StaffAdvance` (поля: `employee`, `amount`, `shift`, `comment`, `created_by`, `created_at`). Используются в Task 3, 4, 5, 6, 7, 8.

- [ ] **Step 1: Написать падающий тест**

`apps/finance/tests.py` уже существует — добавить в начало файла недостающий импорт `from apps.finance.models import CashShift, StaffAdvance, Payment` (объединить с уже существующим импортом моделей, если он там появится; `Patient`/`User`/`Branch` уже импортированы), и добавить в конец файла:

```python
class CashShiftTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="-", phone="0", is_main=True)
        self.cashier = User.objects.create(login="cashier", name="Кассир", email="cashier@test.local")

    def test_open_shift_defaults_to_open_status(self):
        shift = CashShift.objects.create(branch=self.branch, opened_by=self.cashier, opening_balance=Decimal("1000"))
        self.assertEqual(shift.status, CashShift.STATUS_OPEN)
        self.assertIsNone(shift.closed_at)


class StaffAdvanceTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main1b", address="-", phone="0", is_main=True)
        self.cashier = User.objects.create(login="cashier1b", name="Кассир1b", email="cashier1b@test.local")
        self.shift = CashShift.objects.create(branch=self.branch, opened_by=self.cashier, opening_balance=Decimal("0"))

    def test_advance_created_against_shift(self):
        adv = StaffAdvance.objects.create(
            employee=self.cashier, amount=Decimal("200"), shift=self.shift, created_by=self.cashier
        )
        self.assertEqual(adv.amount, Decimal("200"))
        self.assertEqual(adv.shift, self.shift)
```

Обратите внимание: `CashShift.compute_expected_closing()` (добавляется в Step 3 ниже) внутри обращается к модели `ProductSale`, которая появится только в Task 3. Это нормально — Python не вычисляет тело метода при определении класса, только при вызове. Поэтому здесь, в Task 2, тесты `compute_expected_closing()` **не вызывают** — это будет сделано в Task 3, когда `ProductSale` уже существует в модуле (иначе — `NameError: name 'ProductSale' is not defined`).

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance -v 2
```
Expected: FAIL — `ImportError: cannot import name 'CashShift'` (модели ещё нет).

- [ ] **Step 3: Добавить модели в `apps/finance/models.py`**

В начало файла добавить импорт `F` (нужен в Task 3, но добавим сразу):

```python
from django.db.models import F
```

В конец файла (после `PatientAdvance`):

```python
class CashShift(ClinicScopedModel):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Открыта"),
        (STATUS_CLOSED, "Закрыта"),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="cash_shifts", verbose_name="Филиал")
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opened_shifts", verbose_name="Открыл"
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closed_shifts", verbose_name="Закрыл",
    )
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Остаток на начало")
    closing_balance = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Остаток на конец"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN, verbose_name="Статус")

    class Meta:
        verbose_name = "Кассовая смена"
        verbose_name_plural = "Кассовые смены"
        ordering = ["-opened_at"]
        base_manager_name = "all_clinics"

    def __str__(self):
        return f"Смена {self.branch} — {self.opened_at:%d.%m.%Y %H:%M}"

    def compute_expected_closing(self):
        """Ожидаемый остаток наличных на конец смены: начальный остаток + наличный
        приход (платежи + продажи товаров) − наличные возвраты − авансы сотрудникам.
        Безналичные операции (карта/перевод/онлайн) на физическую кассу не влияют."""
        from django.db.models import Sum
        income = (Payment.objects.filter(
            branch=self.branch, method=Payment.METHOD_CASH, type=Payment.TYPE_INCOME,
            created_at__gte=self.opened_at,
        ).aggregate(s=Sum("amount"))["s"] or Decimal(0))
        refund = (Payment.objects.filter(
            branch=self.branch, method=Payment.METHOD_CASH, type=Payment.TYPE_REFUND,
            created_at__gte=self.opened_at,
        ).aggregate(s=Sum("amount"))["s"] or Decimal(0))
        sales = (ProductSale.objects.filter(
            shift=self, payment_method=Payment.METHOD_CASH,
        ).aggregate(s=Sum("total"))["s"] or Decimal(0))
        advances = (StaffAdvance.objects.filter(shift=self).aggregate(s=Sum("amount"))["s"] or Decimal(0))
        return self.opening_balance + income - refund + sales - advances


class StaffAdvance(models.Model):
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="advances_received", verbose_name="Сотрудник"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Сумма")
    shift = models.ForeignKey(CashShift, on_delete=models.PROTECT, related_name="advances", verbose_name="Смена")
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_advances", verbose_name="Выдал"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Аванс сотруднику"
        verbose_name_plural = "Авансы сотрудникам"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee} — аванс {self.amount} [{self.created_at:%d.%m.%Y}]"
```

Обратите внимание: `compute_expected_closing` ссылается на `ProductSale`, которая появится в Task 3 (тот же модуль, порядок определения класса в файле не важен для Python на уровне метода — вызывается в рантайме, когда обе модели уже определены).

- [ ] **Step 4: Сгенерировать и применить миграцию**

```bash
.venv/Scripts/python.exe manage.py makemigrations finance
.venv/Scripts/python.exe manage.py migrate
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

```bash
.venv/Scripts/python.exe manage.py test apps.finance -v 2
```
Expected: PASS (все 3 теста из Step 1).

- [ ] **Step 6: Commit**

```bash
git add apps/finance/models.py apps/finance/migrations apps/finance/tests.py
git commit -m "Модуль 1 (Касса): модели CashShift и StaffAdvance"
```

---

## Task 3: Модели `ProductSale` и `ProductSaleItem` + автосписание со склада

**Files:**
- Modify: `apps/finance/models.py`
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `CashShift` (Task 2), `Product` (`apps.warehouse.models`, с `available_for_sale`/`sale_price` из Task 1).
- Produces: `ProductSale` (поля: `patient`, `shift`, `branch`, `discount`, `total`, `payment_method`, `responsible_staff`, `created_at`, метод `recalc_total()`), `ProductSaleItem` (поля: `sale`, `product`, `quantity`, `unit_price`, свойство `subtotal`). Используется в Task 5, 7, 8.

- [ ] **Step 1: Написать падающий тест**

Добавить в `apps/finance/tests.py`:

```python
from apps.warehouse.models import Product


class ProductSaleTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main2", address="-", phone="0", is_main=True)
        self.cashier = User.objects.create(login="cashier2", name="Кассир2", email="cashier2@test.local")
        self.patient = Patient.objects.create(first_name="Клиент", last_name="Тестов", phone="701", branch=self.branch)
        self.shift = CashShift.objects.create(branch=self.branch, opened_by=self.cashier, opening_balance=Decimal("0"))
        self.product = Product.objects.create(
            name="Щётка", unit="шт", quantity=Decimal("10"),
            available_for_sale=True, sale_price=Decimal("300"),
        )

    def test_sale_item_writes_off_stock(self):
        sale = ProductSale.objects.create(
            patient=self.patient, shift=self.shift, branch=self.branch,
            payment_method=Payment.METHOD_CASH, responsible_staff=self.cashier,
        )
        ProductSaleItem.objects.create(sale=sale, product=self.product, quantity=Decimal("3"), unit_price=Decimal("300"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal("7"))

    def test_recalc_total_applies_discount(self):
        sale = ProductSale.objects.create(
            patient=self.patient, shift=self.shift, branch=self.branch,
            discount=Decimal("50"), payment_method=Payment.METHOD_CASH, responsible_staff=self.cashier,
        )
        ProductSaleItem.objects.create(sale=sale, product=self.product, quantity=Decimal("2"), unit_price=Decimal("300"))
        sale.recalc_total()
        self.assertEqual(sale.total, Decimal("550"))  # 600 - 50

    def test_sale_does_not_create_payment(self):
        sale = ProductSale.objects.create(
            patient=self.patient, shift=self.shift, branch=self.branch,
            payment_method=Payment.METHOD_CASH, responsible_staff=self.cashier,
        )
        ProductSaleItem.objects.create(sale=sale, product=self.product, quantity=Decimal("1"), unit_price=Decimal("300"))
        self.assertEqual(Payment.objects.filter(patient=self.patient).count(), 0)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.ProductSaleTestCase -v 2
```
Expected: FAIL — `ImportError: cannot import name 'ProductSale'`.

- [ ] **Step 3: Добавить модели в `apps/finance/models.py`** (после `StaffAdvance`)

```python
class ProductSale(ClinicScopedModel):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="product_sales", verbose_name="Пациент"
    )
    shift = models.ForeignKey(CashShift, on_delete=models.PROTECT, related_name="sales", verbose_name="Смена")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="product_sales", verbose_name="Филиал")
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Скидка")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Итого")
    payment_method = models.CharField(
        max_length=20, choices=Payment.METHOD_CHOICES, default=Payment.METHOD_CASH, verbose_name="Способ оплаты"
    )
    responsible_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="product_sales", verbose_name="Ответственный"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Продажа товара"
        verbose_name_plural = "Продажи товаров"
        ordering = ["-created_at"]
        base_manager_name = "all_clinics"

    def __str__(self):
        return f"Продажа #{self.pk} — {self.patient} — {self.total}"

    def recalc_total(self):
        from django.db.models import Sum
        subtotal = self.items.aggregate(s=Sum(F("quantity") * F("unit_price")))["s"] or Decimal(0)
        self.total = max(Decimal(0), subtotal - self.discount)
        self.save(update_fields=["total"])


class ProductSaleItem(models.Model):
    sale = models.ForeignKey(ProductSale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "warehouse.Product", on_delete=models.PROTECT, related_name="sale_items", verbose_name="Товар"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Количество")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Цена за единицу")

    class Meta:
        verbose_name = "Позиция продажи"
        verbose_name_plural = "Позиции продажи"

    def __str__(self):
        return f"{self.product} × {self.quantity}"

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            from apps.warehouse.models import Product
            Product.objects.filter(pk=self.product_id).update(quantity=F("quantity") - self.quantity)
```

Списание сделано через override `save()` (как `WarehouseEntry.save()`/`WarehouseDistribution.save()` в `apps/warehouse/models.py`), а не через отдельный `@receiver(post_save)` — это существующая конвенция проекта для этого рода побочных эффектов.

- [ ] **Step 4: Сгенерировать и применить миграцию**

```bash
.venv/Scripts/python.exe manage.py makemigrations finance
.venv/Scripts/python.exe manage.py migrate
```

- [ ] **Step 5: Запустить все тесты finance**

```bash
.venv/Scripts/python.exe manage.py test apps.finance -v 2
```
Expected: PASS (все тесты Task 2 и Task 3).

- [ ] **Step 6: Commit**

```bash
git add apps/finance/models.py apps/finance/migrations apps/finance/tests.py
git commit -m "Модуль 1 (Касса): модели ProductSale/ProductSaleItem с автосписанием склада"
```

---

## Task 4: Открытие/закрытие кассовой смены — views + urls

**Files:**
- Modify: `apps/finance/views.py`
- Modify: `apps/finance/urls.py`
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `CashShift` (Task 2), `role_required` (`apps.users.decorators`), `User.cash_shift_today_only` (Task 1).
- Produces: view-функции `shift_open(request)`, `shift_close(request, pk)`; URL-имена `cash_shift_open`, `cash_shift_close`. Используются в Task 9 (шаблон).

- [ ] **Step 1: Написать падающий тест**

Добавить в `apps/finance/tests.py`:

```python
from django.test import Client
from apps.users.models import Role


class ShiftViewsTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main3", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(login="admin3", name="Админ3", email="admin3@test.local", role=admin_role, branch=None)
        self.admin.set_password("pass12345")
        self.admin.save()
        self.admin.branches.add(self.branch)
        self.client = Client()
        self.client.force_login(self.admin)

    def test_open_shift_creates_open_record(self):
        resp = self.client.post("/finance/cash/shifts/open/", {"opening_balance": "500"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        shift = CashShift.objects.get(opened_by=self.admin)
        self.assertEqual(shift.status, CashShift.STATUS_OPEN)
        self.assertEqual(shift.opening_balance, Decimal("500"))

    def test_cannot_open_second_shift_while_one_open(self):
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "0"})
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "0"})
        self.assertEqual(CashShift.objects.filter(opened_by=self.admin).count(), 1)

    def test_close_shift_sets_closed_status_and_balance(self):
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "1000"})
        shift = CashShift.objects.get(opened_by=self.admin)
        resp = self.client.post(f"/finance/cash/shifts/{shift.pk}/close/", follow=True)
        shift.refresh_from_db()
        self.assertEqual(shift.status, CashShift.STATUS_CLOSED)
        self.assertEqual(shift.closing_balance, Decimal("1000"))
        self.assertIsNotNone(shift.closed_at)

    def test_current_day_only_blocks_closing_old_shift(self):
        from django.utils import timezone
        from datetime import timedelta
        self.admin.cash_shift_today_only = True
        self.admin.save(update_fields=["cash_shift_today_only"])
        shift = CashShift.objects.create(branch=self.branch, opened_by=self.admin, opening_balance=Decimal("0"))
        CashShift.objects.filter(pk=shift.pk).update(opened_at=timezone.now() - timedelta(days=2))
        shift.refresh_from_db()
        self.client.post(f"/finance/cash/shifts/{shift.pk}/close/")
        shift.refresh_from_db()
        self.assertEqual(shift.status, CashShift.STATUS_OPEN)  # не закрылась
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.ShiftViewsTestCase -v 2
```
Expected: FAIL — 404 (урлов ещё нет).

- [ ] **Step 3: Добавить хелпер и views в `apps/finance/views.py`**

Добавить импорт вверху файла (рядом с существующими):

```python
from django.views.decorators.http import require_POST  # уже импортирован — проверить, не дублировать
from apps.users.decorators import role_required
from .models import CashShift, ProductSale, ProductSaleItem, StaffAdvance
```

(`require_POST` уже импортирован в файле — Step 3 просто отмечает, что он нужен; не добавлять повторно, если уже есть в шапке файла.)

Добавить хелпер (например, сразу после `_get_own_payment_or_404`):

```python
def _default_branch(request):
    from apps.users.models import Branch
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic()
    qs = Branch.all_clinics.filter(is_active=True)
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return (qs.filter(pk=request.session.get("active_branch")).first()
            or qs.filter(is_main=True).first()
            or request.user.branches.first()
            or qs.first())
```

Добавить views (в конец файла):

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
def shift_open(request):
    branch = _default_branch(request)
    existing = CashShift.objects.filter(opened_by=request.user, status=CashShift.STATUS_OPEN).first()
    if existing:
        messages.error(request, _("У вас уже есть открытая смена"))
        return redirect("cash_dashboard")
    if request.method == "POST":
        from decimal import Decimal as _D, InvalidOperation
        try:
            opening_balance = _D(request.POST.get("opening_balance") or "0")
        except InvalidOperation:
            opening_balance = Decimal(0)
        CashShift.objects.create(branch=branch, opened_by=request.user, opening_balance=opening_balance)
        messages.success(request, _("Смена открыта"))
    return redirect("cash_dashboard")


@login_required
@role_required("superadmin", "admin_main", "admin")
@require_POST
def shift_close(request, pk):
    shift = get_object_or_404(CashShift.all_clinics, pk=pk, status=CashShift.STATUS_OPEN)
    if (getattr(request.user, "cash_shift_today_only", False)
            and shift.opened_at.date() != timezone.localdate()):
        messages.error(request, _("Вам разрешено работать только с сегодняшними кассовыми операциями"))
        return redirect("cash_dashboard")
    shift.closing_balance = shift.compute_expected_closing()
    shift.status = CashShift.STATUS_CLOSED
    shift.closed_at = timezone.now()
    shift.closed_by = request.user
    shift.save(update_fields=["closing_balance", "status", "closed_at", "closed_by"])
    messages.success(request, _("Смена закрыта. Остаток: %(b)s") % {"b": f"{shift.closing_balance:.0f}"})
    return redirect("cash_dashboard")
```

- [ ] **Step 4: Добавить временную заглушку `cash_dashboard` (полноценно — в Task 7) и URL-маршруты**

Чтобы `redirect("cash_dashboard")` не падал уже сейчас, добавить минимальную view в конец `apps/finance/views.py` (будет заменена/расширена в Task 7 — не дублировать определение, а просто дополнить её там):

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
def cash_dashboard(request):
    current_shift = CashShift.objects.filter(opened_by=request.user, status=CashShift.STATUS_OPEN).first()
    return render(request, "finance/cash_dashboard.html", {"current_shift": current_shift})
```

В `apps/finance/urls.py` добавить в конец `urlpatterns`:

```python
    path("cash/", views.cash_dashboard, name="cash_dashboard"),
    path("cash/shifts/open/", views.shift_open, name="cash_shift_open"),
    path("cash/shifts/<int:pk>/close/", views.shift_close, name="cash_shift_close"),
```

Создать пустой шаблон-заглушку `templates/finance/cash_dashboard.html` (будет полностью написан в Task 9):

```html
{% extends "base.html" %}
{% block page_title %}Касса{% endblock %}
{% block content %}
<div class="space-y-4">
  {% if current_shift %}<p>Смена открыта</p>{% else %}<p>Смена не открыта</p>{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.ShiftViewsTestCase -v 2
```
Expected: PASS (все 4 теста).

- [ ] **Step 6: Commit**

```bash
git add apps/finance/views.py apps/finance/urls.py apps/finance/tests.py templates/finance/cash_dashboard.html
git commit -m "Модуль 1 (Касса): открытие/закрытие кассовой смены"
```

---

## Task 5: Продажа товаров — view + url (включая создание разового пациента)

**Files:**
- Modify: `apps/finance/views.py`
- Modify: `apps/finance/urls.py`
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `ProductSale`/`ProductSaleItem` (Task 3), `Patient.TYPE_WALK_IN` (Task 1), `Product.available_for_sale`/`sale_price` (Task 1), текущая открытая смена (Task 4).
- Produces: view `product_sale_create(request)`, URL-имя `cash_sale_create`. Используется в Task 9.

- [ ] **Step 1: Написать падающий тест**

Добавить в `apps/finance/tests.py`:

```python
class ProductSaleViewTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main4", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(login="admin4", name="Админ4", email="admin4@test.local", role=admin_role)
        self.admin.branches.add(self.branch)
        self.client = Client()
        self.client.force_login(self.admin)
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "0"})
        self.shift = CashShift.objects.get(opened_by=self.admin, status=CashShift.STATUS_OPEN)
        self.product = Product.objects.create(
            name="Щётка", unit="шт", quantity=Decimal("10"),
            available_for_sale=True, sale_price=Decimal("300"),
        )
        self.patient = Patient.objects.create(first_name="Клиент", last_name="Существующий", phone="702", branch=self.branch)

    def test_sale_to_existing_patient(self):
        import json
        resp = self.client.post("/finance/cash/sales/create/", {
            "patient": self.patient.pk,
            "items_json": json.dumps([{"product_id": self.product.pk, "quantity": "2"}]),
            "discount": "0",
            "payment_method": "cash",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        sale = ProductSale.objects.get(patient=self.patient)
        self.assertEqual(sale.total, Decimal("600"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, Decimal("8"))

    def test_sale_without_patient_creates_walk_in(self):
        import json
        before = Patient.objects.count()
        resp = self.client.post("/finance/cash/sales/create/", {
            "items_json": json.dumps([{"product_id": self.product.pk, "quantity": "1"}]),
            "discount": "0",
            "payment_method": "cash",
        }, follow=True)
        self.assertEqual(Patient.objects.count(), before + 1)
        walk_in = Patient.objects.filter(type=Patient.TYPE_WALK_IN).latest("created_at")
        sale = ProductSale.objects.get(patient=walk_in)
        self.assertEqual(sale.total, Decimal("300"))

    def test_sale_does_not_touch_patient_balance(self):
        import json
        self.client.post("/finance/cash/sales/create/", {
            "patient": self.patient.pk,
            "items_json": json.dumps([{"product_id": self.product.pk, "quantity": "1"}]),
            "discount": "0",
            "payment_method": "cash",
        })
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.balance, Decimal("0"))

    def test_sale_blocked_without_open_shift(self):
        import json
        self.client.post(f"/finance/cash/shifts/{self.shift.pk}/close/")
        resp = self.client.post("/finance/cash/sales/create/", {
            "items_json": json.dumps([{"product_id": self.product.pk, "quantity": "1"}]),
        }, follow=True)
        self.assertEqual(ProductSale.objects.count(), 0)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.ProductSaleViewTestCase -v 2
```
Expected: FAIL — 404.

- [ ] **Step 3: Добавить view в `apps/finance/views.py`**

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
@require_POST
def product_sale_create(request):
    import json
    from decimal import Decimal as _D, InvalidOperation
    from apps.warehouse.models import Product

    shift = CashShift.objects.filter(opened_by=request.user, status=CashShift.STATUS_OPEN).first()
    if not shift:
        messages.error(request, _("Сначала откройте кассовую смену"))
        return redirect("cash_dashboard")

    patient_id = request.POST.get("patient")
    if patient_id:
        patient = get_object_or_404(Patient, pk=patient_id)
    else:
        patient = Patient.objects.create(
            first_name=_("Разовый клиент"), last_name="", phone="",
            branch=shift.branch, type=Patient.TYPE_WALK_IN, created_by=request.user,
        )

    try:
        items_data = json.loads(request.POST.get("items_json") or "[]")
    except (ValueError, TypeError):
        items_data = []
    if not items_data:
        messages.error(request, _("Добавьте хотя бы один товар"))
        return redirect("cash_dashboard")

    try:
        discount = _D(request.POST.get("discount") or "0")
    except InvalidOperation:
        discount = Decimal(0)
    payment_method = request.POST.get("payment_method") or Payment.METHOD_CASH

    sale = ProductSale.objects.create(
        patient=patient, shift=shift, branch=shift.branch, discount=discount,
        payment_method=payment_method, responsible_staff=request.user,
    )
    for row in items_data:
        product = Product.objects.filter(pk=row.get("product_id"), available_for_sale=True).first()
        if not product:
            continue
        try:
            qty = _D(str(row.get("quantity") or "0"))
        except InvalidOperation:
            continue
        if qty <= 0:
            continue
        ProductSaleItem.objects.create(
            sale=sale, product=product, quantity=qty, unit_price=product.sale_price or Decimal(0),
        )
    sale.recalc_total()
    messages.success(request, _("Продажа оформлена: %(t)s") % {"t": f"{sale.total:.0f}"})
    return redirect("cash_dashboard")
```

- [ ] **Step 4: Добавить URL**

В `apps/finance/urls.py`, после `cash_shift_close`:

```python
    path("cash/sales/create/", views.product_sale_create, name="cash_sale_create"),
```

- [ ] **Step 5: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.ProductSaleViewTestCase -v 2
```
Expected: PASS (все 4 теста).

- [ ] **Step 6: Commit**

```bash
git add apps/finance/views.py apps/finance/urls.py apps/finance/tests.py
git commit -m "Модуль 1 (Касса): продажа товаров с автосозданием разового клиента"
```

---

## Task 6: Аванс сотруднику — view + url

**Files:**
- Modify: `apps/finance/views.py`
- Modify: `apps/finance/urls.py`
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `StaffAdvance` (Task 2), текущая открытая смена (Task 4), `User` (`apps.users.models`).
- Produces: view `staff_advance_create(request)`, URL-имя `cash_advance_create`. Используется в Task 9.

- [ ] **Step 1: Написать падающий тест**

```python
class StaffAdvanceViewTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main5", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(login="admin5", name="Админ5", email="admin5@test.local", role=admin_role)
        self.admin.branches.add(self.branch)
        self.employee = User.objects.create(login="doc5", name="Врач5", email="doc5@test.local")
        self.client = Client()
        self.client.force_login(self.admin)
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "0"})

    def test_advance_created_and_reduces_expected_closing(self):
        shift = CashShift.objects.get(opened_by=self.admin, status=CashShift.STATUS_OPEN)
        resp = self.client.post("/finance/cash/advances/create/", {
            "employee": self.employee.pk, "amount": "500", "comment": "на бензин",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        advance = StaffAdvance.objects.get(employee=self.employee)
        self.assertEqual(advance.amount, Decimal("500"))
        self.assertEqual(advance.shift, shift)

    def test_advance_requires_positive_amount(self):
        self.client.post("/finance/cash/advances/create/", {"employee": self.employee.pk, "amount": "0"})
        self.assertEqual(StaffAdvance.objects.count(), 0)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.StaffAdvanceViewTestCase -v 2
```
Expected: FAIL — 404.

- [ ] **Step 3: Добавить view**

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
@require_POST
def staff_advance_create(request):
    from decimal import Decimal as _D, InvalidOperation
    from apps.users.models import User

    shift = CashShift.objects.filter(opened_by=request.user, status=CashShift.STATUS_OPEN).first()
    if not shift:
        messages.error(request, _("Сначала откройте кассовую смену"))
        return redirect("cash_dashboard")
    employee = get_object_or_404(User, pk=request.POST.get("employee"))
    try:
        amount = _D(request.POST.get("amount") or "0")
    except InvalidOperation:
        amount = Decimal(0)
    if amount <= 0:
        messages.error(request, _("Укажите сумму аванса"))
        return redirect("cash_dashboard")
    StaffAdvance.objects.create(
        employee=employee, amount=amount, shift=shift,
        comment=request.POST.get("comment", ""), created_by=request.user,
    )
    messages.success(request, _("Аванс выдан"))
    return redirect("cash_dashboard")
```

- [ ] **Step 4: Добавить URL**

В `apps/finance/urls.py`:

```python
    path("cash/advances/create/", views.staff_advance_create, name="cash_advance_create"),
```

- [ ] **Step 5: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.StaffAdvanceViewTestCase -v 2
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/finance/views.py apps/finance/urls.py apps/finance/tests.py
git commit -m "Модуль 1 (Касса): выдача аванса сотруднику из кассы"
```

---

## Task 7: Вкладки «Выставленные/Оплаченные/Неоплаченные» на странице Кассы

**Files:**
- Modify: `apps/finance/views.py` (расширить `cash_dashboard`, добавленную в Task 4)
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `Treatment` (`apps.treatments.models`, поле `debt` — уже существует), `Product.available_for_sale` (Task 1), `clinic_staff` (`apps.users.models`).
- Produces: контекст `cash_dashboard` дополняется `tab`, `treatments`, `products`, `staff` — потребляется шаблоном в Task 9.

- [ ] **Step 1: Написать падающий тест**

```python
class CashDashboardTabsTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main6", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(login="admin6", name="Админ6", email="admin6@test.local", role=admin_role)
        self.admin.branches.add(self.branch)
        self.client = Client()
        self.client.force_login(self.admin)
        self.doctor = User.objects.create(login="doc6", name="Врач6", email="doc6@test.local")
        self.patient = Patient.objects.create(first_name="П6", last_name="Т", phone="706", branch=self.branch)

    def test_unpaid_tab_shows_only_treatments_with_debt(self):
        from apps.treatments.models import Treatment
        paid = Treatment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=Decimal("1000"), paid_amount=Decimal("1000"),
        )
        unpaid = Treatment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_COMPLETED, total_amount=Decimal("1000"), paid_amount=Decimal("0"),
        )
        resp = self.client.get("/finance/cash/?tab=unpaid")
        ids = [t.pk for t in resp.context["treatments"]]
        self.assertIn(unpaid.pk, ids)
        self.assertNotIn(paid.pk, ids)

    def test_products_list_only_available_for_sale(self):
        Product.objects.create(name="Продаваемый", unit="шт", available_for_sale=True, sale_price=Decimal("100"))
        Product.objects.create(name="Материал", unit="шт", available_for_sale=False)
        resp = self.client.get("/finance/cash/")
        names = [p.name for p in resp.context["products"]]
        self.assertIn("Продаваемый", names)
        self.assertNotIn("Материал", names)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.CashDashboardTabsTestCase -v 2
```
Expected: FAIL — `KeyError: 'treatments'` (текущая `cash_dashboard` из Task 4 их не передаёт).

- [ ] **Step 3: Расширить `cash_dashboard` в `apps/finance/views.py`**

Заменить временную реализацию из Task 4 на полную:

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
def cash_dashboard(request):
    from apps.treatments.models import Treatment
    from apps.warehouse.models import Product
    from apps.users.models import clinic_staff
    from apps.tenancy import get_current_clinic

    tab = request.GET.get("tab", "unpaid")
    all_treatments = list(
        Treatment.objects.exclude(status__in=["draft", "cancelled"])
        .select_related("patient").order_by("-created_at")[:500]
    )
    if tab == "paid":
        treatments = [t for t in all_treatments if t.debt == 0][:200]
    elif tab == "unpaid":
        treatments = [t for t in all_treatments if t.debt > 0][:200]
    else:
        tab = "issued"
        treatments = all_treatments[:200]

    current_shift = CashShift.objects.filter(opened_by=request.user, status=CashShift.STATUS_OPEN).first()
    products = Product.objects.filter(available_for_sale=True, is_active=True).order_by("name")
    staff = clinic_staff(get_current_clinic())
    return render(request, "finance/cash_dashboard.html", {
        "tab": tab, "treatments": treatments, "current_shift": current_shift,
        "products": products, "staff": staff,
    })
```

- [ ] **Step 4: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.CashDashboardTabsTestCase -v 2
```
Expected: PASS.

Также перезапустить `ShiftViewsTestCase` — они используют `redirect("cash_dashboard")`, которая теперь рендерит полноценный шаблон:

```bash
.venv/Scripts/python.exe manage.py test apps.finance -v 2
```
Expected: все тесты Task 2–7 PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/finance/views.py apps/finance/tests.py
git commit -m "Модуль 1 (Касса): вкладки Выставленные/Оплаченные/Неоплаченные на странице кассы"
```

---

## Task 8: Кассовый отчёт + экспорт в Excel

**Files:**
- Modify: `apps/finance/views.py`
- Modify: `apps/finance/urls.py`
- Create: `templates/finance/cash_report.html`
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `Payment`, `Expense` (существующие), `ProductSale`, `StaffAdvance`, `CashShift` (Task 2–3).
- Produces: views `cash_report(request)`, `cash_report_export(request)`; URL-имена `cash_report`, `cash_report_export`.

- [ ] **Step 1: Написать падающий тест**

```python
class CashReportTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main7", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(login="admin7", name="Админ7", email="admin7@test.local", role=admin_role)
        self.admin.branches.add(self.branch)
        self.client = Client()
        self.client.force_login(self.admin)
        self.patient = Patient.objects.create(first_name="П7", last_name="Т", phone="707", branch=self.branch)

    def test_report_aggregates_income_and_advances(self):
        from django.utils import timezone
        Payment.objects.create(
            patient=self.patient, amount=Decimal("1000"), method=Payment.METHOD_CASH,
            type=Payment.TYPE_INCOME, branch=self.branch, received_by=self.admin,
        )
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "0"})
        shift = CashShift.objects.get(opened_by=self.admin, status=CashShift.STATUS_OPEN)
        StaffAdvance.objects.create(employee=self.admin, amount=Decimal("200"), shift=shift, created_by=self.admin)
        today = timezone.localdate().isoformat()
        resp = self.client.get(f"/finance/cash/report/?date={today}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["income_total"], Decimal("1000"))
        self.assertEqual(resp.context["advances_total"], Decimal("200"))

    def test_export_returns_xlsx(self):
        resp = self.client.get("/finance/cash/report/export/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.CashReportTestCase -v 2
```
Expected: FAIL — 404.

- [ ] **Step 3: Добавить views в `apps/finance/views.py`**

Добавить импорт в шапку файла (если ещё не импортирован):

```python
from django.http import HttpResponse
```

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
def cash_report(request):
    from django.db.models import Sum
    from datetime import date as _date

    date_str = request.GET.get("date") or timezone.localdate().isoformat()
    try:
        report_date = _date.fromisoformat(date_str)
    except ValueError:
        report_date = timezone.localdate()

    shifts = CashShift.objects.filter(opened_at__date=report_date).select_related("branch", "opened_by")
    payments = Payment.objects.filter(created_at__date=report_date)
    income_by_method = {
        m[0]: payments.filter(type=Payment.TYPE_INCOME, method=m[0]).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        for m in Payment.METHOD_CHOICES
    }
    income_total = sum(income_by_method.values(), Decimal(0))
    refunds = payments.filter(type=Payment.TYPE_REFUND).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    sales_total = (ProductSale.objects.filter(created_at__date=report_date)
                   .aggregate(s=Sum("total"))["s"] or Decimal(0))
    advances_total = (StaffAdvance.objects.filter(created_at__date=report_date)
                       .aggregate(s=Sum("amount"))["s"] or Decimal(0))
    expenses_total = Expense.objects.filter(date=report_date).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    opening_total = shifts.aggregate(s=Sum("opening_balance"))["s"] or Decimal(0)
    closing_total = (shifts.filter(status=CashShift.STATUS_CLOSED)
                      .aggregate(s=Sum("closing_balance"))["s"] or Decimal(0))

    return render(request, "finance/cash_report.html", {
        "report_date": report_date, "shifts": shifts,
        "income_by_method": income_by_method, "income_total": income_total,
        "refunds": refunds, "sales_total": sales_total, "advances_total": advances_total,
        "expenses_total": expenses_total, "opening_total": opening_total, "closing_total": closing_total,
        "net": income_total - refunds + sales_total - advances_total - expenses_total,
    })


@login_required
@role_required("superadmin", "admin_main", "admin")
def cash_report_export(request):
    import openpyxl
    from datetime import date as _date

    date_str = request.GET.get("date") or timezone.localdate().isoformat()
    try:
        report_date = _date.fromisoformat(date_str)
    except ValueError:
        report_date = timezone.localdate()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Кассовый отчёт"
    ws.append(["Кассовый отчёт", report_date.strftime("%d.%m.%Y")])
    ws.append([])
    ws.append(["Платежи"])
    ws.append(["Пациент", "Сумма", "Метод", "Тип", "Принял", "Время"])
    for p in Payment.objects.filter(created_at__date=report_date).select_related("patient", "received_by"):
        ws.append([str(p.patient), float(p.amount), p.get_method_display(), p.get_type_display(),
                   p.received_by.name, p.created_at.strftime("%H:%M")])
    ws.append([])
    ws.append(["Продажи товаров"])
    ws.append(["№", "Пациент", "Сумма", "Способ оплаты", "Ответственный"])
    for s in ProductSale.objects.filter(created_at__date=report_date).select_related("patient", "responsible_staff"):
        ws.append([s.pk, str(s.patient), float(s.total), s.get_payment_method_display(), s.responsible_staff.name])
    ws.append([])
    ws.append(["Авансы сотрудникам"])
    ws.append(["Сотрудник", "Сумма", "Комментарий"])
    for a in StaffAdvance.objects.filter(created_at__date=report_date).select_related("employee"):
        ws.append([a.employee.name, float(a.amount), a.comment])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="cash_report_{report_date.isoformat()}.xlsx"'
    wb.save(response)
    return response
```

- [ ] **Step 4: Добавить URL-маршруты**

В `apps/finance/urls.py`:

```python
    path("cash/report/", views.cash_report, name="cash_report"),
    path("cash/report/export/", views.cash_report_export, name="cash_report_export"),
```

- [ ] **Step 5: Создать `templates/finance/cash_report.html`**

```html
{% extends "base.html" %}
{% block page_title %}Кассовый отчёт{% endblock %}
{% block content %}
<div class="space-y-4">
  <div class="flex items-center justify-between flex-wrap gap-3">
    <form method="get" class="flex items-center gap-2">
      <input type="date" name="date" value="{{ report_date|date:'Y-m-d' }}" onchange="this.form.submit()">
    </form>
    <a href="/finance/cash/report/export/?date={{ report_date|date:'Y-m-d' }}" class="btn-ghost">⬇ Экспорт в Excel</a>
  </div>

  <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
    <div class="stat"><div><p class="stat-label">Остаток на начало</p><p class="stat-value">{{ opening_total|floatformat:0 }} {{ clinic_settings.currency_label }}</p></div></div>
    <div class="stat"><div><p class="stat-label">Доходы</p><p class="stat-value" style="color:var(--green)">{{ income_total|add:sales_total|floatformat:0 }} {{ clinic_settings.currency_label }}</p></div></div>
    <div class="stat"><div><p class="stat-label">Расходы</p><p class="stat-value" style="color:var(--red)">{{ expenses_total|add:advances_total|floatformat:0 }} {{ clinic_settings.currency_label }}</p></div></div>
    <div class="stat"><div><p class="stat-label">Остаток на конец</p><p class="stat-value">{{ closing_total|floatformat:0 }} {{ clinic_settings.currency_label }}</p></div></div>
  </div>

  <div class="card card-pad">
    <h3 class="font-bold mb-3">Доходы по способу оплаты</h3>
    <table class="tbl">
      <thead><tr><th>Способ</th><th class="text-right">Сумма</th></tr></thead>
      <tbody>
        {% for method, amount in income_by_method.items %}
        <tr><td>{{ method }}</td><td class="text-right">{{ amount|floatformat:0 }} {{ clinic_settings.currency_label }}</td></tr>
        {% endfor %}
        <tr><td>Продажи товаров</td><td class="text-right">{{ sales_total|floatformat:0 }} {{ clinic_settings.currency_label }}</td></tr>
        <tr><td>Возвраты</td><td class="text-right">−{{ refunds|floatformat:0 }} {{ clinic_settings.currency_label }}</td></tr>
        <tr><td>Авансы сотрудникам</td><td class="text-right">−{{ advances_total|floatformat:0 }} {{ clinic_settings.currency_label }}</td></tr>
        <tr><td>Прочие расходы</td><td class="text-right">−{{ expenses_total|floatformat:0 }} {{ clinic_settings.currency_label }}</td></tr>
      </tbody>
    </table>
  </div>

  <div class="card card-pad">
    <h3 class="font-bold mb-3">Смены за день</h3>
    <table class="tbl">
      <thead><tr><th>Филиал</th><th>Открыл</th><th>Открыта</th><th>Закрыта</th><th class="text-right">Начало</th><th class="text-right">Конец</th></tr></thead>
      <tbody>
        {% for s in shifts %}
        <tr>
          <td>{{ s.branch }}</td><td>{{ s.opened_by.name }}</td>
          <td>{{ s.opened_at|date:"H:i" }}</td><td>{% if s.closed_at %}{{ s.closed_at|date:"H:i" }}{% else %}—{% endif %}</td>
          <td class="text-right">{{ s.opening_balance|floatformat:0 }}</td>
          <td class="text-right">{% if s.closing_balance is not None %}{{ s.closing_balance|floatformat:0 }}{% else %}—{% endif %}</td>
        </tr>
        {% empty %}
        <tr><td colspan="6" class="text-center py-6 text-slate-400">Смен за этот день не было</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.finance -v 2
```
Expected: все тесты Task 2–8 PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/finance/views.py apps/finance/urls.py apps/finance/tests.py templates/finance/cash_report.html
git commit -m "Модуль 1 (Касса): кассовый отчёт с экспортом в Excel"
```

---

## Task 9: Шаблон страницы «Касса» (вкладки, модалка продажи, управление сменой/авансами)

**Files:**
- Modify: `templates/finance/cash_dashboard.html` (заменить заглушку из Task 4 на полноценную страницу)

**Interfaces:**
- Consumes: контекст `cash_dashboard` из Task 7 (`tab`, `treatments`, `current_shift`, `products`, `staff`), URL-имена `cash_shift_open`/`cash_shift_close`/`cash_sale_create`/`cash_advance_create`/`cash_report` из Task 4–8.

- [ ] **Step 1: Написать полный шаблон**

```html
{% extends "base.html" %}
{% block page_title %}Касса{% endblock %}
{% block content %}
<div class="space-y-4" x-data="cashPage()">
  <div class="flex items-center justify-between flex-wrap gap-3">
    <div class="pill-tabs">
      <a href="?tab=issued" class="pill-tab {% if tab == 'issued' %}active{% endif %}">Выставленные</a>
      <a href="?tab=paid" class="pill-tab {% if tab == 'paid' %}active{% endif %}">Оплаченные</a>
      <a href="?tab=unpaid" class="pill-tab {% if tab == 'unpaid' %}active{% endif %}">Неоплаченные</a>
    </div>
    <div class="flex items-center gap-2 flex-wrap">
      <a href="/finance/cash/report/" class="btn-ghost">📊 Отчёт</a>
      {% if current_shift %}
        <span class="badge badge-green">Смена открыта · {{ current_shift.opened_at|date:"H:i" }}</span>
        <form method="post" action="/finance/cash/shifts/{{ current_shift.pk }}/close/" onsubmit="return confirm('Закрыть смену?')">
          {% csrf_token %}
          <button type="submit" class="btn-ghost">Закрыть смену</button>
        </form>
        <button type="button" class="btn-ghost" @click="advanceOpen=true">💵 Аванс сотруднику</button>
        <button type="button" class="btn-success" @click="saleOpen=true">+ Продажа товаров</button>
      {% else %}
        <button type="button" class="btn-primary" @click="openShift=true">Открыть смену</button>
      {% endif %}
    </div>
  </div>

  <div class="card overflow-hidden">
    <table class="tbl">
      <thead><tr><th>Пациент</th><th>Врач</th><th class="text-right">Сумма</th><th class="text-right">Оплачено</th><th class="text-right">Долг</th><th>Дата</th></tr></thead>
      <tbody>
        {% for t in treatments %}
        <tr>
          <td><a href="/patients/{{ t.patient.pk }}/" class="font-semibold" style="color:var(--primary)">{{ t.patient.full_name }}</a></td>
          <td>{{ t.doctor.name }}</td>
          <td class="text-right">{{ t.display_total|floatformat:0 }} {{ clinic_settings.currency_label }}</td>
          <td class="text-right">{{ t.paid_amount|floatformat:0 }} {{ clinic_settings.currency_label }}</td>
          <td class="text-right {% if t.debt > 0 %}text-red-500 font-bold{% endif %}">{{ t.debt|floatformat:0 }} {{ clinic_settings.currency_label }}</td>
          <td class="text-slate-400 text-xs">{{ t.created_at|date:"d.m.Y" }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="6" class="text-center py-12 text-slate-400">Нет приёмов в этой вкладке</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Открыть смену -->
  <div x-show="openShift" x-cloak class="modal-overlay" @click.self="openShift=false">
    <div class="modal-box max-w-sm">
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100">
        <h3 class="font-bold text-slate-800">Открыть смену</h3>
        <button @click="openShift=false" class="text-2xl text-slate-400">&times;</button>
      </div>
      <form method="post" action="/finance/cash/shifts/open/" class="px-6 py-5 space-y-4">
        {% csrf_token %}
        <div><label class="fld">Остаток на начало ({{ clinic_settings.currency_label }})</label><input type="number" name="opening_balance" step="0.01" value="0" required></div>
        <div class="flex gap-3 pt-2">
          <button type="submit" class="btn-primary flex-1 justify-center">Открыть</button>
          <button type="button" @click="openShift=false" class="btn-ghost">Отмена</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Аванс сотруднику -->
  <div x-show="advanceOpen" x-cloak class="modal-overlay" @click.self="advanceOpen=false">
    <div class="modal-box max-w-sm">
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100">
        <h3 class="font-bold text-slate-800">Аванс сотруднику</h3>
        <button @click="advanceOpen=false" class="text-2xl text-slate-400">&times;</button>
      </div>
      <form method="post" action="/finance/cash/advances/create/" class="px-6 py-5 space-y-4">
        {% csrf_token %}
        <div>
          <label class="fld">Сотрудник</label>
          <select name="employee" required>
            {% for s in staff %}<option value="{{ s.pk }}">{{ s.name }}</option>{% endfor %}
          </select>
        </div>
        <div><label class="fld">Сумма ({{ clinic_settings.currency_label }})</label><input type="number" name="amount" step="0.01" required></div>
        <div><label class="fld">Комментарий</label><textarea name="comment" rows="2"></textarea></div>
        <div class="flex gap-3 pt-2">
          <button type="submit" class="btn-primary flex-1 justify-center">Выдать</button>
          <button type="button" @click="advanceOpen=false" class="btn-ghost">Отмена</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Продажа товаров -->
  <div x-show="saleOpen" x-cloak class="modal-overlay" @click.self="saleOpen=false">
    <div class="modal-box max-w-lg">
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100">
        <h3 class="font-bold text-slate-800">Продажа товаров</h3>
        <button @click="saleOpen=false" class="text-2xl text-slate-400">&times;</button>
      </div>
      <form method="post" action="/finance/cash/sales/create/" class="px-6 py-5 space-y-4" @submit="submitSale($event)">
        {% csrf_token %}
        <div>
          <label class="fld">Пациент</label>
          <select name="patient" class="no-tom">
            <option value="">— Разовый клиент —</option>
            <!-- список пациентов подгружается тем же поисковым select, что и в форме платежа -->
          </select>
        </div>
        <div class="space-y-2">
          <label class="fld">Товары</label>
          <template x-for="(row, idx) in items" :key="idx">
            <div class="flex items-center gap-2">
              <select x-model="row.product_id" @change="onProductChange(row)" class="no-tom flex-1">
                <option value="">— выбрать товар —</option>
                {% for p in products %}
                <option value="{{ p.pk }}" data-price="{{ p.sale_price|default:0 }}">{{ p.name }} ({{ p.sale_price|floatformat:0 }} {{ clinic_settings.currency_label }})</option>
                {% endfor %}
              </select>
              <input type="number" x-model="row.quantity" min="0.001" step="0.001" style="width:90px" placeholder="Кол-во">
              <button type="button" @click="items.splice(idx,1)" class="text-red-500 text-xl leading-none">&times;</button>
            </div>
          </template>
          <button type="button" @click="items.push({product_id:'',quantity:1})" class="btn-ghost btn-sm">+ Добавить товар</button>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div><label class="fld">Скидка ({{ clinic_settings.currency_label }})</label><input type="number" name="discount" x-model="discount" step="0.01" value="0"></div>
          <div>
            <label class="fld">Способ оплаты</label>
            <select name="payment_method">
              <option value="cash">Наличные</option>
              <option value="card">Карта</option>
              <option value="transfer">Перевод</option>
              <option value="online">Онлайн</option>
            </select>
          </div>
        </div>
        <input type="hidden" name="items_json" :value="JSON.stringify(items.filter(r => r.product_id && r.quantity > 0))">
        <div class="flex gap-3 pt-2">
          <button type="submit" class="btn-success flex-1 justify-center">Оформить продажу</button>
          <button type="button" @click="saleOpen=false" class="btn-ghost">Отмена</button>
        </div>
      </form>
    </div>
  </div>
</div>
<script>
function cashPage() {
  return {
    openShift: false, advanceOpen: false, saleOpen: false,
    items: [{product_id: '', quantity: 1}],
    discount: 0,
    onProductChange(row) {},
    submitSale(e) {
      const valid = this.items.some(r => r.product_id && r.quantity > 0);
      if (!valid) { e.preventDefault(); alert('Добавьте хотя бы один товар'); }
    },
  };
}
</script>
{% endblock %}
```

Примечание: выбор конкретного существующего пациента в модалке продажи оставлен как обычный `<select name="patient">` без предзаполненного списка вариантов (в отличие от `payment_form.html`, где список пациентов подгружается через TomSelect с AJAX-поиском по всем пациентам клиники — см. `{{ form.patient }}` в `payments.html`). Для полной консистентности со стилем поиска пациента, используемым в форме платежа, при реализации стоит переиспользовать тот же виджет (TomSelect `class="searchable"`), подключив тот же источник данных, что использует `PaymentForm.fields["patient"]`. Это не блокирует работоспособность (пустой выбор = автосоздание разового клиента), но перед мануальной проверкой в Step 2 стоит сверить, что выбор существующего пациента в проде реально работает (см. как `patients_json`/поиск пациента подключены в `payment_form.html`, если этот файл существует — использовать тот же паттерн).

- [ ] **Step 2: Ручная проверка в браузере**

```bash
.venv/Scripts/python.exe manage.py runserver
```
Открыть `/finance/cash/` под администратором клиники:
- Вкладки Выставленные/Оплаченные/Неоплаченные переключаются и показывают разные приёмы.
- «Открыть смену» → модалка → после сохранения кнопка меняется на «Закрыть смену» + бейдж «Смена открыта».
- «Продажа товаров» → выбрать товар и количество (без выбора пациента) → «Оформить продажу» → success-сообщение, товар списался (проверить на `/warehouse/`).
- «Аванс сотруднику» → выдать → success-сообщение.
- «Закрыть смену» → success-сообщение с посчитанным остатком.
- Тёмная тема (переключатель в сайдбаре) — страница читаема, ничего не «слепит» (использует только CSS-переменные из `app.css`, отдельных цветов не хардкодили).

- [ ] **Step 3: Commit**

```bash
git add templates/finance/cash_dashboard.html
git commit -m "Модуль 1 (Касса): страница Касса — вкладки, продажа товаров, смена, авансы"
```

---

## Task 10: Печатный чек продажи товаров

ТЗ Модуля 1 явно требует чек для продажи товаров ("способ оплаты, чек"), который был пропущен при первом проходе плана. `ProductSale` пока нигде не отображается списком (только модалка создания в Task 9) — добавляем и чек, и мини-список продаж за текущую смену, из которого чек открывается.

**Files:**
- Modify: `apps/finance/views.py` (новая view `product_sale_receipt`, расширить `cash_dashboard` — добавить `recent_sales`)
- Modify: `apps/finance/urls.py`
- Modify: `templates/finance/cash_dashboard.html` (добавить блок «Продажи за смену»)
- Create: `templates/finance/product_sale_receipt.html`
- Test: `apps/finance/tests.py`

**Interfaces:**
- Consumes: `ProductSale`/`ProductSaleItem` (Task 3), `CashShift` (Task 2), `cash_dashboard` (Task 7 — расширяется, не переписывается).
- Produces: view `product_sale_receipt(request, pk)`, URL-имя `cash_sale_receipt`; контекст `cash_dashboard` дополняется `recent_sales`.

- [ ] **Step 1: Написать падающий тест**

Добавить в `apps/finance/tests.py`:

```python
class ProductSaleReceiptTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main8", address="-", phone="0", is_main=True)
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN)
        self.admin = User.objects.create(login="admin8", name="Админ8", email="admin8@test.local", role=admin_role)
        self.admin.branches.add(self.branch)
        self.client = Client()
        self.client.force_login(self.admin)
        self.client.post("/finance/cash/shifts/open/", {"opening_balance": "0"})
        self.shift = CashShift.objects.get(opened_by=self.admin, status=CashShift.STATUS_OPEN)
        self.product = Product.objects.create(
            name="Щётка", unit="шт", quantity=Decimal("10"),
            available_for_sale=True, sale_price=Decimal("300"),
        )
        self.patient = Patient.objects.create(first_name="Клиент", last_name="Чек", phone="708", branch=self.branch)
        self.sale = ProductSale.objects.create(
            patient=self.patient, shift=self.shift, branch=self.branch,
            payment_method=Payment.METHOD_CASH, responsible_staff=self.admin,
        )
        ProductSaleItem.objects.create(sale=self.sale, product=self.product, quantity=Decimal("2"), unit_price=Decimal("300"))
        self.sale.recalc_total()

    def test_receipt_page_shows_items_and_total(self):
        resp = self.client.get(f"/finance/cash/sales/{self.sale.pk}/receipt/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Щётка")
        self.assertContains(resp, "600")

    def test_dashboard_lists_recent_sales_of_current_shift(self):
        resp = self.client.get("/finance/cash/")
        sale_ids = [s.pk for s in resp.context["recent_sales"]]
        self.assertIn(self.sale.pk, sale_ids)
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

```bash
.venv/Scripts/python.exe manage.py test apps.finance.tests.ProductSaleReceiptTestCase -v 2
```
Expected: FAIL — 404 на `/finance/cash/sales/<pk>/receipt/`, и `KeyError: 'recent_sales'`.

- [ ] **Step 3: Добавить view в `apps/finance/views.py`**

```python
@login_required
@role_required("superadmin", "admin_main", "admin")
def product_sale_receipt(request, pk):
    sale = get_object_or_404(
        ProductSale.all_clinics.select_related("patient", "responsible_staff", "branch")
        .prefetch_related("items__product"),
        pk=pk,
    )
    return render(request, "finance/product_sale_receipt.html", {"sale": sale, "w80": request.GET.get("w") == "80"})
```

- [ ] **Step 4: Расширить `cash_dashboard` — добавить `recent_sales`**

В теле `cash_dashboard` (см. Task 7), перед `return render(...)`, добавить:

```python
    recent_sales = (ProductSale.objects.filter(shift=current_shift).select_related("patient").order_by("-created_at")[:20]
                     if current_shift else ProductSale.objects.none())
```

И добавить `"recent_sales": recent_sales,` в словарь контекста `return render(request, "finance/cash_dashboard.html", {...})`.

- [ ] **Step 5: Добавить URL**

В `apps/finance/urls.py`, после `cash_sale_create`:

```python
    path("cash/sales/<int:pk>/receipt/", views.product_sale_receipt, name="cash_sale_receipt"),
```

- [ ] **Step 6: Создать `templates/finance/product_sale_receipt.html`**

По образцу `templates/treatments/receipt_thermal.html` (термо-чек 80мм) — упрощённая версия без QR (для продажи товаров публичный QR-чек не требуется, только внутренняя печать):

```html
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Чек продажи #{{ sale.pk }}</title>
<style>
  body { font-family: Arial, sans-serif; font-size: 13px; color: #222; margin: 0; padding: 24px; }
  .wrap { max-width: 360px; margin: 0 auto; }
  .clinic { text-align: center; margin-bottom: 14px; }
  .clinic h1 { font-size: 18px; margin: 0 0 4px; }
  hr { border: none; border-top: 1px dashed #bbb; margin: 12px 0; }
  .row { display: flex; justify-content: space-between; padding: 4px 0; }
  .row .k { color: #666; } .row .v { font-weight: 600; text-align: right; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  td { padding: 4px 0; vertical-align: top; }
  td.r { text-align: right; white-space: nowrap; padding-left: 6px; }
  .tot { display:flex; justify-content:space-between; font-weight:800; font-size:15px; margin-top:8px; }
  .footer { margin-top: 16px; text-align: center; font-size: 10px; color: #999; }
  @media print { .noprint { display: none; } }
  .noprint { text-align:center; margin-top:18px; }
  .noprint button { padding:9px 22px; border:none; border-radius:8px; background:#2563EB; color:#fff; font-size:13px; cursor:pointer; }
{% if w80 %}
  @page { size: 80mm auto; margin: 0; }
  body { padding: 4mm 3mm; font-size: 12px; }
  .wrap { max-width: 74mm; }
  .clinic h1 { font-size: 15px; }
{% endif %}
</style>
</head>
<body onload="window.print()">
<div class="wrap">
  <div class="clinic">
    <h1>{% if clinic_settings %}{{ clinic_settings.receipt_display_name }}{% else %}Стоматология{% endif %}</h1>
  </div>
  <hr>
  <p style="text-align:center;font-weight:700;margin:0">Чек продажи товаров №{{ sale.pk }}</p>
  <hr>
  <div class="row"><span class="k">Пациент</span><span class="v">{{ sale.patient.full_name }}</span></div>
  <div class="row"><span class="k">Дата</span><span class="v">{{ sale.created_at|date:"d.m.Y H:i" }}</span></div>
  <div class="row"><span class="k">Способ оплаты</span><span class="v">{{ sale.get_payment_method_display }}</span></div>
  <hr>
  <table>
    <tbody>
      {% for item in sale.items.all %}
      <tr>
        <td>{{ item.product.name }} × {{ item.quantity }}</td>
        <td class="r">{{ item.subtotal|floatformat:0 }} {{ clinic_settings.currency_label }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <hr>
  {% if sale.discount %}<div class="row"><span class="k">Скидка</span><span class="v">−{{ sale.discount|floatformat:0 }} {{ clinic_settings.currency_label }}</span></div>{% endif %}
  <div class="tot"><span>Итого</span><span>{{ sale.total|floatformat:0 }} {{ clinic_settings.currency_label }}</span></div>
  <p class="footer">Ответственный: {{ sale.responsible_staff.name }}</p>
</div>
<div class="noprint"><button onclick="window.print()">Печать</button></div>
</body>
</html>
```

- [ ] **Step 7: Добавить блок «Продажи за смену» в `templates/finance/cash_dashboard.html`**

После блока с таблицей приёмов (перед модалками), добавить:

```html
  {% if recent_sales %}
  <div class="card overflow-hidden">
    <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100">
      <h3 class="font-bold" style="color:var(--text)">Продажи за текущую смену</h3>
    </div>
    <table class="tbl">
      <thead><tr><th>Пациент</th><th class="text-right">Сумма</th><th>Способ</th><th></th></tr></thead>
      <tbody>
        {% for s in recent_sales %}
        <tr>
          <td>{{ s.patient.full_name }}</td>
          <td class="text-right">{{ s.total|floatformat:0 }} {{ clinic_settings.currency_label }}</td>
          <td>{{ s.get_payment_method_display }}</td>
          <td class="text-right pr-3"><a href="/finance/cash/sales/{{ s.pk }}/receipt/?w=80" target="_blank" class="btn btn-ghost btn-sm">🧾 Чек</a></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
```

- [ ] **Step 8: Запустить тесты**

```bash
.venv/Scripts/python.exe manage.py test apps.finance -v 2
```
Expected: все тесты Task 2–10 PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/finance/views.py apps/finance/urls.py apps/finance/tests.py \
        templates/finance/cash_dashboard.html templates/finance/product_sale_receipt.html
git commit -m "Модуль 1 (Касса): печатный чек продажи товаров + список продаж за смену"
```

---

## Task 11: Быстрая оплата долга из списка должников

**Files:**
- Modify: `templates/finance/debtors.html`

**Interfaces:**
- Consumes: существующий `payment_create` view (`apps/finance/views.py`), который уже поддерживает предзаполнение через `?patient=<id>` (см. `payment_list` / `preselect`).

- [ ] **Step 1: Прочитать текущий `templates/finance/debtors.html`, найти таблицу должников**

- [ ] **Step 2: Добавить кнопку «Принять оплату» в последнюю колонку каждой строки**

Добавить в конце `<tr>` (там, где сейчас выводится должник) ячейку с ссылкой на уже существующий флоу оплаты — тот же, что используется в `payment_list`/`send_to_cashier`:

```html
<td class="text-right">
  <a href="/finance/payments/?patient={{ debtor.pk }}&amount={{ debtor.debt|floatformat:0 }}" class="btn-success btn-sm">Принять оплату</a>
</td>
```

Не создавать новый endpoint — `payment_list` (`apps/finance/views.py::payment_list`) уже читает `request.GET.get("patient")`/`amount` и открывает модалку создания платежа с предзаполненными полями (`preselect`, см. существующий код). Убедиться, что колонка присутствует в `<thead>` (`<th>Действия</th>` или аналогично).

- [ ] **Step 3: Ручная проверка**

Открыть `/finance/debtors/`, нажать «Принять оплату» у любого должника → должно открыться `/finance/payments/` с уже открытой модалкой и предзаполненной суммой долга (поведение идентично переходу с кнопки «В кассу» на карточке пациента).

- [ ] **Step 4: Commit**

```bash
git add templates/finance/debtors.html
git commit -m "Модуль 1 (Касса): кнопка быстрой оплаты в списке должников"
```

---

## Task 12: Навигация, переключатель модуля по клинике и админка

**Files:**
- Modify: `apps/settings_clinic/models.py` (добавить `"cash"` в `ClinicSettings.ALL_MODULES`)
- Modify: `templates/base.html` (добавить пункт меню «Касса»)
- Modify: `apps/finance/admin.py` (зарегистрировать новые модели)

**Interfaces:**
- Consumes: `ClinicSettings.ALL_MODULES` (см. Global Constraints — уже существующий per-clinic toggle-механизм, суперадминская форма в `templates/users/superadmin.html` рендерит его автоматически, новых полей формы добавлять не нужно), существующую структуру сайдбара (секция «Управление», строки ~111-116 рядом с пунктом «Финансы»), `django.contrib.admin`.

- [ ] **Step 1: Добавить «Касса» как отдельный переключаемый модуль**

В `apps/settings_clinic/models.py`, класс `ClinicSettings`, список `ALL_MODULES` (после `("finance", "Финансы")`):

```python
    ALL_MODULES = [
        ("calendar", "Расписание"),
        ("appointments", "Записи"),
        ("patients", "Пациенты"),
        ("treatments", "Лечения"),
        ("services", "Услуги"),
        ("finance", "Финансы"),
        ("cash", "Касса"),
        ("warehouse", "Склад"),
        ("medicines", "Лекарства"),
        ("technicians", "Техники"),
        ("tasks", "Задачи"),
        ("reports", "Аналитика"),
        ("staff", "Сотрудники"),
    ]
```

Отдельный ключ (не переиспользуем `"finance"`) — по требованию пользователя каждый новый модуль должен отключаться независимо для конкретной клиники. `TARIFF_PRESETS["premium"]` подхватит `"cash"` автоматически (уже строится как `[m[0] for m in ALL_MODULES]`); `"basic"`/`"standard"` НЕ трогать — это тарифный/ценовой вопрос, не относится к Модулю 1.

- [ ] **Step 2: Добавить пункт меню в `templates/base.html`**

В блоке «Управление» (`x-data="{ mgmtOpen: true }"`), сразу после ссылки на «Финансы»:

```html
{% if 'cash' in enabled_modules and 'finance' in user_sections and not user.is_doctor %}
<a href="/finance/cash/" class="nav-item {% if u == 'cash_dashboard' or 'cash_' in u %}active{% endif %}" data-mod="cash">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 6V4a2 2 0 012-2h8a2 2 0 012 2v2"/></svg>
  <span class="nav-label">Касса</span>
</a>
{% endif %}
```

Условие видимости — И модуль включён (`'cash' in enabled_modules`, новый ключ из Step 1), И у пользователя есть доступ к разделу «Финансы» (`'finance' in user_sections` — Касса не заводит отдельного пункта в персональных доступах `SECTIONS`, входит в существующий раздел «Финансы»). Врачам не показываем (`not user.is_doctor`, как и у «Финансы» рядом).

Активное состояние проверяется по `u == 'cash_dashboard' or 'cash_' in u` (все url_name кассовых views начинаются с `cash_` или равны `cash_dashboard`) — не пересекается с существующей проверкой `'finance' in u or 'payment' in u or 'expense' in u or 'debtor' in u` у пункта «Финансы» рядом, так что оба пункта не подсвечиваются одновременно.

- [ ] **Step 3: Зарегистрировать модели в `apps/finance/admin.py`**

Дополнить импорт и добавить регистрации:

```python
from .models import Payment, Expense, ExpenseCategory, PatientAdvance, CashShift, ProductSale, ProductSaleItem, StaffAdvance


@admin.register(CashShift)
class CashShiftAdmin(admin.ModelAdmin):
    list_display = ["branch", "opened_by", "opened_at", "closed_at", "status", "opening_balance", "closing_balance"]
    list_filter = ["status", "branch"]
    date_hierarchy = "opened_at"


class ProductSaleItemInline(admin.TabularInline):
    model = ProductSaleItem
    extra = 0


@admin.register(ProductSale)
class ProductSaleAdmin(admin.ModelAdmin):
    list_display = ["pk", "patient", "total", "payment_method", "responsible_staff", "created_at"]
    list_filter = ["payment_method", "branch"]
    date_hierarchy = "created_at"
    inlines = [ProductSaleItemInline]


@admin.register(StaffAdvance)
class StaffAdvanceAdmin(admin.ModelAdmin):
    list_display = ["employee", "amount", "shift", "created_at"]
    date_hierarchy = "created_at"
```

- [ ] **Step 4: Ручная проверка**

```bash
.venv/Scripts/python.exe manage.py runserver
```
- Пункт «Касса» появился в сайдбаре под «Финансы» (не виден врачу — проверить входом под ролью `doctor`).
- В `/users/superadmin/` (панель тарифов) в списке модулей появился переключатель «Касса» — выключить его для тестовой клиники и убедиться, что пункт «Касса» пропал из сайдбара этой клиники, а `/finance/cash/` по-прежнему открывается напрямую (только UI-скрытие, см. Global Constraints).
- `/django-admin/` → новые модели видны и открываются без ошибок.

- [ ] **Step 5: Commit**

```bash
git add apps/settings_clinic/models.py templates/base.html apps/finance/admin.py
git commit -m "Модуль 1 (Касса): переключатель модуля по клинике, пункт меню и регистрация моделей в admin"
```

---

## Task 13: Финальная проверка всего модуля

- [ ] **Step 1: Полный прогон тестов**

```bash
.venv/Scripts/python.exe manage.py test apps.finance apps.patients apps.warehouse apps.users -v 2
```
Expected: все тесты PASS, 0 failures/errors.

- [ ] **Step 2: Проверить, что миграции применяются с нуля без ошибок**

```bash
.venv/Scripts/python.exe manage.py migrate --check
```
Expected: без вывода (все миграции применены), либо `python manage.py showmigrations finance patients warehouse users` — все отмечены `[X]`.

- [ ] **Step 3: Сквозной сценарий вручную** (браузер, роль администратора клиники)

1. Открыть смену с остатком 1000.
2. Продать товар разовому клиенту наличными.
3. Принять оплату долга существующего пациента через `/finance/debtors/` → «Принять оплату».
4. Выдать аванс сотруднику 500.
5. Открыть `/finance/cash/report/` — сверить, что остаток на конец = 1000 + (наличная выручка) − 500, продажа товара учтена отдельной строкой, экспорт в Excel скачивается и открывается.
6. Закрыть смену — остаток совпадает с посчитанным в отчёте.

- [ ] **Step 4: Commit** (если Step 3 потребовал правок)

```bash
git add -A
git commit -m "Модуль 1 (Касса): финальные правки по итогам сквозной проверки"
```
