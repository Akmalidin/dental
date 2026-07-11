# Unify Patient Debt/Balance + Fix API PaymentAllocation Gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `Patient.debt` into a read of the already-correct `Patient.balance` field, and make `Payment.save()` create `PaymentAllocation` rows for income payments regardless of caller — fixing the DRF API path, which currently creates payments with no allocation at all.

**Architecture:** `Patient.debt` becomes `max(0, -self.balance)` — no new query, no new formula, since `balance` is already kept fresh by `recalc_balance()` from every mutation path (payment save/delete, discount edit, status change, treatment total recalc). `_allocate_income()` and `_recompute_treatment_paid()` move from `apps/finance/views.py` to `apps/finance/models.py` as module-level functions, and `Payment.save()` calls `_allocate_income(self)` for income payments. Existing explicit calls in `views.py` stay in place (idempotent, needed for discount-ordering — see spec).

**Tech Stack:** Django 5.1, Django `TestCase` (first tests in this project — no test infra exists yet), PostgreSQL (dev settings), no new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-07-unify-patient-debt-calc-design.md` — read it if anything here is ambiguous.
- **Do not touch** `Payment.delete()` or `Payment._update_treatment_paid()` (direct-sum `paid_amount` calc) — out of scope this round (see spec's "Не в рамках").
- **Do not remove** the explicit `_allocate_income()`/`_recalc_patient_balance()` calls in `apps/finance/views.py`'s `payment_create`/`payment_edit`/`payment_delete` — they are idempotent and required for correct ordering with the treatment-discount update.
- This touches money logic on a production system with live data (SADAF, `denta.tw1.ru`). No task in this plan deploys to production — that is a separate, explicit step the user will trigger manually after reviewing locally.
- Settings module for local test runs: `config.settings.development` (Django default from `manage.py`), backed by PostgreSQL — `python manage.py test` will create/drop a `test_<dbname>` database automatically.

---

## File Structure

- Modify: `apps/finance/models.py` — add `_allocate_income()`, `_recompute_treatment_paid()` module functions; wire `_allocate_income()` into `Payment.save()`.
- Modify: `apps/finance/views.py` — remove local `_allocate_income`/`_recompute_treatment_paid` defs, import from `models.py` instead. No behavior change in this file.
- Create: `apps/finance/tests.py` — tests for `Payment.save()` auto-allocating (web path unchanged, API-style path now allocates).
- Modify: `apps/patients/models.py` — `Patient.debt` body replaced.
- Create: `apps/patients/tests.py` — tests proving `debt == max(0, -balance)`, including the cross-clinic superadmin scenario the old code got wrong.

---

## Task 1: Move allocation helpers into `finance/models.py`, wire into `Payment.save()`

**Files:**
- Modify: `apps/finance/models.py` (add functions near top of file, after imports; modify `Payment.save()`)
- Modify: `apps/finance/views.py:100-152` (remove local defs, import from models)
- Test: `apps/finance/tests.py` (new file)

**Interfaces:**
- Produces: `apps.finance.models._allocate_income(payment) -> None`, `apps.finance.models._recompute_treatment_paid(treatment) -> None` — both importable from `apps.finance.models` for use in `views.py` and tests.
- Consumes: `apps.finance.models.Payment`, `apps.finance.models.PaymentAllocation`, `apps.treatments.models.Treatment`.

Read `apps/finance/models.py` fully before editing — it currently has `Payment.save()`/`delete()`/`_update_patient_balance()`/`_update_treatment_paid()` around lines 74-119, and `PaymentAllocation` class starting at line 110. The new module functions go **before** the `Payment` class definition (they're referenced from `Payment.save()`), but `PaymentAllocation` is defined **after** `Payment` in the same file — so the functions must do their `PaymentAllocation`/`Treatment` imports **inside the function body** (matching the existing style in `views.py`, which already does local imports to dodge circularity) rather than at module top.

- [ ] **Step 1: Write the failing test for API-path allocation**

Create `apps/finance/tests.py`:

```python
from decimal import Decimal
from django.test import TestCase, RequestFactory
from apps.users.models import User, Branch
from apps.patients.models import Patient
from apps.treatments.models import Treatment
from apps.finance.models import Payment, PaymentAllocation
from apps.finance.serializers import PaymentSerializer


class PaymentAllocationTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="—", phone="0000000000", is_main=True)
        self.doctor = User.objects.create(login="doc1", name="Doctor One", email="doc1@test.local")
        self.patient = Patient.objects.create(
            first_name="Ivan", last_name="Ivanov", phone="0700000001", branch=self.branch,
        )
        self.treatment = Treatment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_IN_PROGRESS, total_amount=Decimal("1000"),
        )

    def test_web_path_payment_creates_allocation(self):
        """Existing behavior: a plain Payment.save() for an income payment allocates it."""
        payment = Payment.objects.create(
            patient=self.patient, treatment=self.treatment, amount=Decimal("400"),
            type=Payment.TYPE_INCOME, branch=self.branch, received_by=self.doctor,
        )
        allocations = PaymentAllocation.objects.filter(payment=payment)
        self.assertEqual(allocations.count(), 1)
        self.assertEqual(allocations.first().amount, Decimal("400"))

    def test_api_serializer_creates_allocation(self):
        """Regression test for the audit finding: DRF-created payments must also allocate."""
        request = RequestFactory().post("/api/v1/payments/")
        request.user = self.doctor
        serializer = PaymentSerializer(context={"request": request})
        payment = serializer.create({
            "patient": self.patient,
            "treatment": self.treatment,
            "amount": Decimal("250"),
            "type": Payment.TYPE_INCOME,
            "branch": self.branch,
        })
        allocations = PaymentAllocation.objects.filter(payment=payment)
        self.assertEqual(allocations.count(), 1)
        self.assertEqual(allocations.first().amount, Decimal("250"))
```

- [ ] **Step 2: Run tests to verify the API-path test fails, web-path test passes**

Run: `python manage.py test apps.finance.tests -v 2`
Expected: `test_web_path_payment_creates_allocation` PASSES (this already works today via the explicit view-level call being irrelevant here — wait, this test calls `Payment.objects.create()` directly, bypassing `views.py` entirely, so today it FAILS too — `Payment.save()` alone does not currently allocate). Expected: **both tests FAIL** with `AssertionError: 0 != 1` (no allocation exists yet, since only `views.py` explicitly triggers `_allocate_income`, not `Payment.save()` itself).

- [ ] **Step 3: Add allocation helpers to `apps/finance/models.py`**

Open `apps/finance/models.py`. After the imports (after line 6, before `class ExpenseCategory`), add:

```python
def _recompute_treatment_paid(treatment):
    """paid_amount приёма = сумма распределений всех платежей на него."""
    from django.db.models import Sum
    from decimal import Decimal
    from apps.treatments.models import Treatment
    total = PaymentAllocation.objects.filter(treatment=treatment).aggregate(s=Sum("amount"))["s"] or Decimal(0)
    Treatment.all_objects.filter(pk=treatment.pk).update(paid_amount=total)


def _allocate_income(payment):
    """Распределить income-платёж по приёмам пациента: сначала привязанный приём,
    затем остальные по возрастанию даты, заполняя остаток долга. Создаёт PaymentAllocation."""
    from django.db.models import Sum
    from decimal import Decimal
    from apps.treatments.models import Treatment
    patient = payment.patient
    if not patient:
        return
    PaymentAllocation.objects.filter(payment=payment).delete()
    treatments = list(Treatment.objects.filter(patient=patient)
                      .exclude(status__in=["cancelled", "draft"]).order_by("created_at"))
    if payment.treatment_id:
        treatments.sort(key=lambda t: 0 if t.pk == payment.treatment_id else 1)
    left = payment.amount
    affected = []
    for t in treatments:
        if left <= 0:
            break
        already = PaymentAllocation.objects.filter(treatment=t).aggregate(s=Sum("amount"))["s"] or Decimal(0)
        billed = (t.total_amount or Decimal(0)) - (t.discount or Decimal(0))
        remaining = billed - already
        if remaining <= 0:
            continue
        alloc = min(left, remaining)
        PaymentAllocation.objects.create(payment=payment, treatment=t, amount=alloc)
        left -= alloc
        affected.append(t)
    if left > 0 and payment.treatment_id:
        t = Treatment.all_objects.filter(pk=payment.treatment_id).first()
        if t:
            PaymentAllocation.objects.create(payment=payment, treatment=t, amount=left)
            affected.append(t)
    for t in set(affected):
        _recompute_treatment_paid(t)
```

This is a verbatim move of the two functions currently in `apps/finance/views.py:100-145` — do not change the logic, only the location. Note `_allocate_income` references `PaymentAllocation`, which is defined later in this same file (`class PaymentAllocation(models.Model)`, currently after `class Payment`) — that's fine in Python since the function body only resolves the name at call time, not at module-load time, as long as `PaymentAllocation` exists in the module's namespace by the time `_allocate_income` is actually called (it will, since all classes in the file load before any request-time code calls these functions).

- [ ] **Step 4: Wire `_allocate_income` into `Payment.save()`**

In `apps/finance/models.py`, find the existing `Payment.save()`:

```python
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_patient_balance()
        if self.treatment:
            self._update_treatment_paid()
```

Change to:

```python
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_patient_balance()
        if self.treatment:
            self._update_treatment_paid()
        if self.type == self.TYPE_INCOME:
            _allocate_income(self)
```

Do not touch `Payment.delete()` — out of scope (see Global Constraints).

- [ ] **Step 5: Run tests to verify both pass**

Run: `python manage.py test apps.finance.tests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Update `apps/finance/views.py` to import instead of redefine**

In `apps/finance/views.py`, find the local definitions of `_recompute_treatment_paid` (currently lines ~100-105) and `_allocate_income` (currently lines ~108-145). Delete both function bodies and replace with an import at the top of the function-call sites, i.e. add near the top of `apps/finance/views.py` (with the other imports):

```python
from apps.finance.models import _allocate_income, _recompute_treatment_paid
```

Then delete the two now-duplicate `def _recompute_treatment_paid(treatment):` and `def _allocate_income(payment):` blocks entirely from `views.py`. **Do not** change any call sites (`payment_create`, `payment_edit`, `payment_delete`, `payment_allocations`) — they keep calling `_allocate_income(...)`/`_recompute_treatment_paid(...)` exactly as before, just now resolved via the import instead of a local def.

- [ ] **Step 7: Run the full finance test suite plus a manual sanity check**

Run: `python manage.py test apps.finance -v 2`
Expected: PASS, no import errors (confirms no circular import issue from the new top-level import in `views.py`).

Run: `python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 8: Commit**

```bash
git add apps/finance/models.py apps/finance/views.py apps/finance/tests.py
git commit -m "$(cat <<'EOF'
Payment.save() allocates income payments automatically

Fixes the audit finding that DRF-created payments never got a
PaymentAllocation, leaving the allocation modal empty for API
payments. _allocate_income/_recompute_treatment_paid moved from
views.py to models.py so Payment.save() can call them directly;
existing explicit view-level calls are left in place (idempotent,
needed for discount-ordering in payment_create).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Unify `Patient.debt` to read from `Patient.balance`

**Files:**
- Modify: `apps/patients/models.py:239-253` (the `debt` property)
- Test: `apps/patients/tests.py` (new file)

**Interfaces:**
- Consumes: `Patient.balance` (existing field, kept fresh by `Patient.recalc_balance()`, itself already exercised by Task 1's `Payment.save()` path — no change needed there).
- Produces: `Patient.debt` (property, same external contract: returns a non-negative `Decimal`).

- [ ] **Step 1: Write the failing test for the cross-clinic bugfix**

Create `apps/patients/tests.py`:

```python
from decimal import Decimal
from django.test import TestCase
from apps.tenancy import set_current_clinic, clear_current_clinic
from apps.users.models import User, Branch, Clinic
from apps.patients.models import Patient
from apps.treatments.models import Treatment
from apps.finance.models import Payment


class PatientDebtTestCase(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Main", address="—", phone="0000000000", is_main=True)
        self.doctor = User.objects.create(login="doc2", name="Doctor Two", email="doc2@test.local")
        self.patient = Patient.objects.create(
            first_name="Petr", last_name="Petrov", phone="0700000002", branch=self.branch,
        )
        self.treatment = Treatment.objects.create(
            patient=self.patient, doctor=self.doctor, branch=self.branch,
            status=Treatment.STATUS_IN_PROGRESS, total_amount=Decimal("1000"),
        )

    def tearDown(self):
        clear_current_clinic()

    def test_debt_matches_balance_after_partial_payment(self):
        Payment.objects.create(
            patient=self.patient, treatment=self.treatment, amount=Decimal("300"),
            type=Payment.TYPE_INCOME, branch=self.branch, received_by=self.doctor,
        )
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.balance, Decimal("-700"))
        self.assertEqual(self.patient.debt, Decimal("700"))

    def test_debt_zero_when_overpaid(self):
        Payment.objects.create(
            patient=self.patient, treatment=self.treatment, amount=Decimal("1500"),
            type=Payment.TYPE_INCOME, branch=self.branch, received_by=self.doctor,
        )
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.balance, Decimal("500"))
        self.assertEqual(self.patient.debt, Decimal("0"))

    def test_debt_correct_when_viewer_active_clinic_differs_from_patients(self):
        """Regression test: old `debt` property filtered treatments by the viewer's
        active clinic (session thread-local), not the patient's own clinic — a
        superadmin viewing a patient from a different active clinic saw a wrong
        (too-low or zero) debt. `balance` (all_objects, no clinic filter) is correct."""
        other_clinic = Clinic.objects.create(name="Other Clinic", slug="other-clinic")
        set_current_clinic(other_clinic)
        try:
            self.patient.refresh_from_db()
            self.assertEqual(self.patient.debt, Decimal("1000"))
        finally:
            clear_current_clinic()
```

- [ ] **Step 2: Run tests to verify the cross-clinic test fails, the others pass**

Run: `python manage.py test apps.patients.tests -v 2`
Expected: `test_debt_matches_balance_after_partial_payment` and `test_debt_zero_when_overpaid` PASS (old formula already gives the right number when there's no clinic-context mismatch). `test_debt_correct_when_viewer_active_clinic_differs_from_patients` FAILS — old `debt` property uses `self.treatments` (clinic-filtered manager), so with `other_clinic` active it wrongly returns `Decimal("0")` instead of `Decimal("1000")`.

If `Clinic` model requires more fields than `name`/`slug` to save, check `apps/users/models.py` for the `Clinic` class definition and adjust the fixture — read the model before assuming the constructor above is complete.

- [ ] **Step 3: Replace `Patient.debt` body**

In `apps/patients/models.py`, replace:

```python
    @property
    def debt(self):
        from django.db.models import Sum
        from decimal import Decimal
        from apps.finance.models import Payment
        # Долг = (сумма приёмов − скидки) − (оплаты − возвраты). Считаем по фактическим
        # платежам пациента (не по paid_amount приёма), чтобы учесть нераспределённые оплаты.
        qs = self.treatments.exclude(status__in=["cancelled", "draft"])
        total = qs.aggregate(total=Sum("total_amount"))["total"] or Decimal(0)
        disc = qs.aggregate(disc=Sum("discount"))["disc"] or Decimal(0)
        income = (Payment.all_clinics.filter(patient_id=self.pk, type=Payment.TYPE_INCOME)
                  .aggregate(s=Sum("amount"))["s"] or Decimal(0))
        refund = (Payment.all_clinics.filter(patient_id=self.pk, type=Payment.TYPE_REFUND)
                  .aggregate(s=Sum("amount"))["s"] or Decimal(0))
        return max(Decimal(0), (total - disc) - (income - refund))
```

with:

```python
    @property
    def debt(self):
        """Долг = -balance, если пациент должен (balance < 0), иначе 0.
        balance поддерживается свежим через recalc_balance() из всех точек мутации
        (платежи, скидка приёма, смена статуса, пересчёт суммы приёма)."""
        from decimal import Decimal
        return max(Decimal(0), -self.balance)
```

- [ ] **Step 4: Run tests to verify all three pass**

Run: `python manage.py test apps.patients.tests -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full test suite to check for unrelated breakage**

Run: `python manage.py test apps.finance apps.patients apps.treatments -v 2`
Expected: PASS, no errors from other code paths that read `Patient.debt` (e.g. `apps/appointments/views.py:748`, `apps/reports/views.py:102`, `apps/notifications/whatsapp.py:213` — these all read the property, not its internals, so they don't need code changes, but this run confirms nothing else in those apps' own test suites — if any exist — breaks).

Run: `python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 6: Commit**

```bash
git add apps/patients/models.py apps/patients/tests.py
git commit -m "$(cat <<'EOF'
Unify Patient.debt to read from the already-correct balance field

debt and balance were two independent implementations of the same
formula (debt == max(0, -balance)). balance is kept fresh from every
mutation path already; collapsing debt into it removes a duplicate
query and fixes a real bug where debt used the viewer's active-clinic
session filter instead of the patient's own clinic (wrong number for
a superadmin viewing a patient from a different active clinic).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Manual verification before any production deploy

**Files:** none (manual/local verification only — no code changes).

This task exists because the spec explicitly calls for manual sanity checks beyond automated tests, and because this touches money logic on a system with live production data. **Do not deploy to production as part of this plan** — deployment is a separate, explicit action for the user to trigger after reviewing this locally.

- [ ] **Step 1: Run the full local test suite one more time**

Run: `python manage.py test apps.finance apps.patients -v 2`
Expected: all tests PASS.

- [ ] **Step 2: Manual check against local dev data (not production)**

With the local dev server running against local Postgres (per `akmsoft_clinic` README/`.env.example` setup — NOT the production `.env`), open the Django shell:

```bash
python manage.py shell
```

```python
from apps.patients.models import Patient
mismatches = []
for p in Patient.objects.all()[:200]:
    p.recalc_balance()
    if p.debt != max(0, -p.balance):
        mismatches.append(p.pk)
print("checked:", Patient.objects.count(), "mismatches:", mismatches)
```

Expected: `mismatches: []` (by construction, since `debt` now literally reads `balance` — this step is a smoke test that `recalc_balance()`/`debt` don't raise on real-shaped local data, not a test of the equivalence proof itself).

- [ ] **Step 3: Report back to the user**

Summarize test results and the shell check output. Wait for explicit user go-ahead before anyone runs `deploy/update.sh` against the production server — that step is intentionally not part of this plan.

---

## Self-Review Notes

- **Spec coverage:** Spec's narrowed 3-point plan (models.py allocation move + save() wiring, views.py import cleanup, Patient.debt) — all three are Tasks 1-2 above. `Payment.delete()`/`_update_treatment_paid()` explicitly left untouched, matching spec's "Не в рамках". Deploy explicitly excluded per user's stated concern about live data.
- **Placeholder scan:** none found — every step has literal code.
- **Type consistency:** `_allocate_income(payment)` / `_recompute_treatment_paid(treatment)` signatures identical in Task 1 Step 3 (definition) and Task 1 Step 6 (import in views.py) and Task 1 Step 1 (test usage via `Payment.save()`, not called directly). `Patient.debt` remains a property returning `Decimal` in both old and new implementations — no caller-visible signature change.
