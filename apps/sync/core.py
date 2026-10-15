"""
Оффлайн-режим: обмен данными одной клиники между облаком и офлайн-копией.

Как это работает
----------------
Офлайн-копия — компьютер в клинике со своей базой SQLite; остальные
компьютеры клиники открывают его по Wi-Fi. Синхронизация (кнопка
«Синхронизация» или sync_run):

1. push — офлайн-копия отправляет в облако ТОЛЬКО то, что изменилось у неё
   с прошлой синхронизации (журнал SyncChange: сохранения и удаления).
2. pull — забирает из облака полный снимок клиники и приводит свою базу
   в точное соответствие с ним (кроме ещё не отправленных своих изменений).

Правила, чтобы данные не терялись и не путались
-----------------------------------------------
- Своё пространство id. Записи, созданные офлайн, получают id из диапазона
  своего устройства (device_range): 10¹² + номер_устройства × 10⁹. Облако
  нумерует с 1, поэтому новая запись офлайн никогда не совпадёт по id с
  записью облака или другой офлайн-копии и не затрёт её.
- Конфликт. Если запись изменили и офлайн, и в облаке после прошлой
  синхронизации — облачная версия остаётся, а офлайн-версия сохраняется в
  «Конфликты синхронизации» (SyncConflict), где можно выбрать нужную.
  Ничьи правки молча не пропадают.
- Удалено в облаке. Запись облака, которую там удалили, а офлайн в это время
  меняли — не воскрешается (иначе удалённое возвращалось бы).
- Совпадение по смыслу (зуб пациента, процент категории и т. п. —
  уникальные сочетания полей): новая офлайн-запись объединяется с уже
  существующей в облаке (по правилу конфликта выше).
- № приёма. Новый офлайн-приём получает в облаке следующий свободный номер.
- Безопасность. Облако принимает только записи своей клиники (проверяется и
  новая, и текущая версия) и только разрешённых моделей; учётные записи,
  роли, клиники, филиалы, настройки, общие справочники, кассовые смены и
  распределения оплат офлайн только получает (они ведутся/пересчитываются
  в облаке).
- После push облако пересчитывает балансы затронутых пациентов
  (распределение оплат, долги) — как при обычной работе онлайн.
"""
import json
import threading

from django.apps import apps as django_apps
from django.core import serializers
from django.db import transaction
from django.utils import timezone

# Порядок важен: родители раньше детей (для корректной загрузки FK).
# (app_label, ModelName, способ фильтрации по клинике)
#   "self"   — сама клиника
#   "all"    — общие справочники (для всех клиник)
#   "direct" — у модели есть поле clinic
#   ("via", "fk__path__clinic") — клиника через связь
EXPORT_PLAN = [
    ("users", "Clinic", "self"),
    ("users", "Role", "all"),
    ("users", "Branch", "direct"),
    ("users", "User", "direct"),
    ("settings_clinic", "ClinicSettings", "direct"),
    ("appointments", "Cabinet", ("via", "branch__clinic")),
    ("users", "DoctorSchedule", ("via", "branch__clinic")),
    ("patients", "LeadSource", "all"),
    ("patients", "Tag", "all"),
    ("patients", "InsuranceCompany", "all"),
    ("patients", "BlacklistEntry", "direct"),
    ("patients", "SharedPhoneNumber", "all"),
    ("services", "ServiceCategory", "direct"),
    ("services", "Service", "direct"),
    ("users", "SalaryScheme", ("via", "user__clinic")),
    ("users", "SalaryCategoryPercent", ("via", "scheme__user__clinic")),
    ("users", "SalaryPayout", "direct"),
    ("technicians", "Technician", "direct"),
    ("technicians", "TechnicianAgreement", ("via", "technician__clinic")),
    ("warehouse", "Supplier", "direct"),
    ("warehouse", "ProductCategory", "direct"),
    ("warehouse", "Product", "direct"),
    ("services", "ServiceMaterialNorm", ("via", "service__clinic")),
    ("warehouse", "WarehouseEntry", ("via", "product__clinic")),
    ("warehouse", "WarehouseDistribution", ("via", "product__clinic")),
    ("warehouse", "WarehouseTransfer", ("via", "from_branch__clinic")),
    ("warehouse", "WarehouseTransferItem", ("via", "transfer__from_branch__clinic")),
    ("warehouse", "InventoryDocument", ("via", "branch__clinic")),
    ("warehouse", "InventoryItem", ("via", "document__branch__clinic")),
    ("finance", "ExpenseCategory", "direct"),
    ("appointments", "CancellationReason", "all"),
    ("settings_clinic", "DocumentTemplate", "direct"),
    ("medicines", "Medicine", "direct"),
    ("patients", "Patient", "direct"),
    ("patients", "Lead", "direct"),
    ("tasks", "Task", "direct"),
    ("treatments", "MedicalRecordTemplate", "direct"),
    ("treatments", "ToothStatus", "all"),
    ("treatments", "ToothSurfaceStatus", "all"),
    ("treatments", "ToothGumStatus", "all"),
    ("treatments", "ToothCondition", ("via", "patient__clinic")),
    ("treatments", "ToothSurfaceCondition", ("via", "patient__clinic")),
    ("treatments", "ToothGumCondition", ("via", "patient__clinic")),
    ("appointments", "Appointment", "direct"),
    ("appointments", "WaitlistEntry", "direct"),
    ("treatments", "Treatment", "direct"),
    ("treatments", "TreatmentCure", ("via", "treatment__clinic")),
    ("treatments", "TreatmentFollowUp", ("via", "treatment__clinic")),
    ("technicians", "TechnicianTask", "direct"),
    ("technicians", "TechnicianOrderEvent", ("via", "task__clinic")),
    ("technicians", "TechnicianOrderMessage", ("via", "task__clinic")),
    ("treatments", "MedicalRecord", ("via", "treatment__clinic")),
    ("treatments", "TreatmentPlan", ("via", "patient__clinic")),
    ("treatments", "TreatmentPlanStage", ("via", "plan__patient__clinic")),
    ("treatments", "TreatmentPlanItem", ("via", "plan__patient__clinic")),
    ("patients", "PatientVisit", "direct"),
    ("finance", "CashShift", "direct"),
    ("finance", "Payment", "direct"),
    ("finance", "PaymentAllocation", ("via", "payment__clinic")),
    ("finance", "Expense", "direct"),
    ("finance", "PatientAdvance", ("via", "patient__clinic")),
    ("finance", "InstallmentPlan", "direct"),
    ("finance", "InstallmentItem", ("via", "plan__clinic")),
    ("medicines", "PatientMedicine", ("via", "patient__clinic")),
    ("technicians", "TechnicianWarrantyCase", "direct"),
]

PLAN_RULES = {f"{a}.{m}": rule for a, m, rule in EXPORT_PLAN}
PLAN_ORDER = {label: i for i, label in enumerate(PLAN_RULES)}

# Что офлайн-копия НЕ может прислать в облако — только получает.
PUSH_DENY_RULES = ("self", "all")
PUSH_DENY_MODELS = {
    "users.User", "users.Branch", "users.Clinic", "users.Role",
    "settings_clinic.ClinicSettings",
    # кассовая смена ведётся в облаке (авто-открытие/закрытие), одна открытая
    # на филиал; распределения оплат облако пересчитывает само после push
    "finance.CashShift", "finance.PaymentAllocation",
}

# Диапазоны id офлайн-устройств (BigAutoField; < 2⁵³, чтобы id без потерь
# проходили через JavaScript).
DEVICE_ID_BASE = 10 ** 12
DEVICE_ID_SPAN = 10 ** 9


def device_range(device_id):
    lo = DEVICE_ID_BASE + int(device_id) * DEVICE_ID_SPAN
    return lo, lo + DEVICE_ID_SPAN - 1


def pushable(model_label):
    rule = PLAN_RULES.get(model_label)
    return rule is not None and rule not in PUSH_DENY_RULES and model_label not in PUSH_DENY_MODELS


# ─── «Сейчас применяем данные из облака» — не журналировать ────────────────
_local = threading.local()


class remote_apply:
    """Контекст: изменения внутри — пришли из облака (pull), а не сделаны
    пользователем офлайн, поэтому в журнал на отправку они не попадают."""

    def __enter__(self):
        self._prev = getattr(_local, "remote", False)
        _local.remote = True

    def __exit__(self, *exc):
        _local.remote = self._prev


def applying_remote():
    return getattr(_local, "remote", False)


# ─── Принадлежность записи клинике ──────────────────────────────────────────
def _clinic_of(obj, rule):
    """id клиники, которой принадлежит запись (по правилу из EXPORT_PLAN);
    None — если не удалось определить (ссылка на несуществующего родителя)."""
    try:
        if rule == "direct":
            return obj.clinic_id
        if isinstance(rule, tuple) and rule[0] == "via":
            parts = rule[1].split("__")
            cur = obj
            for name in parts[:-1]:
                cur = getattr(cur, name, None)
                if cur is None:
                    return None
            return getattr(cur, parts[-1] + "_id", None)
    except Exception:  # noqa: BLE001 — битая ссылка = чужая/неизвестная запись
        return None
    return None


def push_allowed(model_label, obj, existing, clinic):
    """Можно ли применить присланную запись к облаку: модель разрешена к
    отправке, и запись (новая версия и текущая в облаке) — этой клиники."""
    if not pushable(model_label):
        return False
    rule = PLAN_RULES[model_label]
    if _clinic_of(obj, rule) != clinic.pk:
        return False
    if existing is not None and _clinic_of(existing, rule) != clinic.pk:
        return False
    return True


def _manager(model):
    """Менеджер без фильтра по клинике/удалению (видит всё)."""
    for name in ("all_objects", "all_clinics", "objects"):
        if hasattr(model, name):
            return getattr(model, name)
    return model._default_manager


def _queryset_for(model, rule, clinic):
    mgr = _manager(model)
    if rule == "self":
        return mgr.filter(pk=clinic.pk)
    if rule == "all":
        return mgr.all()
    if rule == "direct":
        return mgr.filter(clinic=clinic)
    if isinstance(rule, tuple) and rule[0] == "via":
        return mgr.filter(**{rule[1]: clinic})
    return mgr.none()


def _plan_models():
    for app_label, model_name, rule in EXPORT_PLAN:
        try:
            yield f"{app_label}.{model_name}", django_apps.get_model(app_label, model_name), rule
        except LookupError:
            continue


def _dump(objs):
    return json.loads(serializers.serialize("json", objs))


# Секреты интеграций в снимок не попадают никогда: офлайн-копии они не нужны
# (уведомления шлёт облако), а снимок может скачать и человек.
SECRET_FIELDS = {
    "settings_clinic.ClinicSettings": ("telegram_bot_token", "telegram_webhook_secret", "wa_token"),
}


def export_clinic(clinic, include_password_hashes=True):
    """Полный снимок данных клиники: список блоков JSON-объектов.

    Хеши паролей нужны только офлайн-копии (вход сотрудников без интернета) —
    при выгрузке через браузер их нет (include_password_hashes=False)."""
    blocks = []
    for label, model, rule in _plan_models():
        data = _dump(_queryset_for(model, rule, clinic).order_by("pk"))
        hidden = list(SECRET_FIELDS.get(label, ()))
        if label == "users.User" and not include_password_hashes:
            hidden.append("password")
        if hidden:
            for raw in data:
                fields = raw.get("fields") or {}
                for name in hidden:
                    if name in fields:
                        fields[name] = ""
        blocks.append({"model": label, "objects": data, "count": len(data)})
    return blocks


def _object_repr(raw):
    """Короткое человекочитаемое описание записи для списка конфликтов."""
    f = raw.get("fields", {}) or {}
    for combo in (("last_name", "first_name"), ("title",), ("name",)):
        parts = [str(f[k]) for k in combo if f.get(k)]
        if parts:
            return " ".join(parts)
    return f"#{raw.get('pk')}"


# ─── ОБЛАКО: приём изменений от офлайн-копии ───────────────────────────────
def _natural_twin(model, obj):
    """Существующая запись с теми же значениями уникального сочетания полей
    (unique_together / unique), если новая офлайн-запись с ним совпала."""
    mgr = model._base_manager
    sets = [tuple(u) for u in (model._meta.unique_together or ())]
    for c in model._meta.constraints:
        if getattr(c, "fields", None) and getattr(c, "condition", None) is None:
            sets.append(tuple(c.fields))
    for f in model._meta.fields:
        if f.unique and not f.primary_key:
            sets.append((f.name,))
    for fields in sets:
        try:
            lookup = {model._meta.get_field(n).attname: getattr(obj, model._meta.get_field(n).attname)
                      for n in fields}
        except Exception:  # noqa: BLE001
            continue
        twin = mgr.filter(**lookup).exclude(pk=obj.pk).first()
        if twin is not None:
            return twin
    return None


def _conflict(model_label, pk, raw, existing):
    cloud_snapshot = _dump([existing])[0] if existing is not None else None
    up = getattr(existing, "updated_at", None)
    return {
        "model": model_label, "pk": pk, "object_repr": _object_repr(raw),
        "local_data": raw, "cloud_data": cloud_snapshot,
        "local_updated_at": (raw.get("fields") or {}).get("updated_at"),
        "cloud_updated_at": up.isoformat() if up else None,
    }


def _cloud_changed(existing, since):
    up = getattr(existing, "updated_at", None)
    return since is not None and up is not None and up > since


def apply_push(changes, deletions, clinic, since):
    """Применить изменения офлайн-копии к облаку.

    changes   — блоки [{"model": label, "objects": [raw...]}] (сохранения);
    deletions — [{"model": label, "pk": pk}];
    since     — время облака на момент прошлой синхронизации этой копии.

    Возвращает итог и список done: записи, по которым решение окончательное
    (применено, конфликт записан, отклонено) — офлайн-копия убирает их из
    журнала; записи с ошибкой (например, родитель ещё не дошёл) остаются и
    отправятся в следующий раз."""
    from django.db.models import Max
    from apps.tenancy import unscoped
    from apps.treatments.models import Treatment

    res = {"applied": 0, "conflicts": [], "rejected": 0, "skipped_deleted": 0,
           "errors": [], "done": []}
    patients, new_appts = set(), []

    def _done(label, pk):
        res["done"].append([label, pk])

    blocks = sorted(changes or [], key=lambda b: PLAN_ORDER.get(b.get("model"), 10 ** 6))
    with unscoped():
        for block in blocks:
            label = block.get("model")
            try:
                model = django_apps.get_model(label)
            except Exception:  # noqa: BLE001
                model = None
            for raw in block.get("objects", []):
                pk = raw.get("pk")
                if model is None or pk is None or not pushable(label):
                    res["rejected"] += 1
                    _done(label, pk)
                    continue
                existing = model._base_manager.filter(pk=pk).first()
                if existing is None and int(pk) < DEVICE_ID_BASE:
                    # запись облака, которую в облаке удалили — не воскрешаем
                    res["skipped_deleted"] += 1
                    _done(label, pk)
                    continue
                try:
                    with transaction.atomic():
                        d = next(serializers.deserialize("python", [raw]))
                        obj = d.object
                        if not push_allowed(label, obj, existing, clinic):
                            res["rejected"] += 1
                            _done(label, pk)
                            continue
                        if existing is not None and _cloud_changed(existing, since):
                            res["conflicts"].append(_conflict(label, pk, raw, existing))
                            _done(label, pk)
                            continue
                        if existing is None:
                            twin = _natural_twin(model, obj)
                            if twin is not None:
                                if _cloud_changed(twin, since) or not push_allowed(label, obj, twin, clinic):
                                    res["conflicts"].append(_conflict(label, twin.pk, raw, twin))
                                    _done(label, pk)
                                    continue
                                obj.pk = twin.pk   # объединяем с существующей
                            if label == "treatments.Treatment" and obj.clinic_id:
                                last = (Treatment.all_objects.filter(clinic_id=obj.clinic_id)
                                        .aggregate(m=Max("number"))["m"] or 0)
                                obj.number = last + 1
                            if label == "appointments.Appointment":
                                new_appts.append(obj.pk)
                        if hasattr(obj, "updated_at"):
                            # время облака, а не часов офлайн-компьютера — иначе
                            # следующая синхронизация видела бы ложные конфликты
                            obj.updated_at = timezone.now()
                        d.save()
                    res["applied"] += 1
                    _done(label, pk)
                    pid = obj.pk if label == "patients.Patient" else getattr(obj, "patient_id", None)
                    if pid:
                        patients.add(pid)
                except Exception as e:  # noqa: BLE001
                    res["errors"].append({"model": label, "pk": pk, "error": str(e)[:200]})

        for item in sorted(deletions or [], key=lambda x: -PLAN_ORDER.get(x.get("model"), 0)):
            label, pk = item.get("model"), item.get("pk")
            try:
                model = django_apps.get_model(label)
            except Exception:  # noqa: BLE001
                res["rejected"] += 1
                _done(label, pk)
                continue
            existing = model._base_manager.filter(pk=pk).first()
            if existing is None:
                _done(label, pk)          # уже нет — цель достигнута
                continue
            if not push_allowed(label, existing, existing, clinic):
                res["rejected"] += 1
                _done(label, pk)
                continue
            if _cloud_changed(existing, since):
                raw = {"model": label, "pk": pk, "fields": {}, "deleted": True}
                res["conflicts"].append(_conflict(label, pk, raw, existing))
                _done(label, pk)
                continue
            try:
                pid = getattr(existing, "patient_id", None)
                with transaction.atomic():
                    existing.delete()
                res["applied"] += 1
                _done(label, pk)
                if pid:
                    patients.add(pid)
            except Exception as e:  # noqa: BLE001
                res["errors"].append({"model": label, "pk": pk, "error": str(e)[:200]})

        # балансы и распределение оплат — как при обычной работе онлайн
        from apps.patients.models import Patient
        for p in Patient.all_objects.filter(pk__in=patients):
            try:
                p.recalc_balance()
            except Exception:  # noqa: BLE001
                pass
        res["overlaps"] = _overlaps(new_appts)
    res["patients"] = len(patients)
    return res


def _overlaps(appointment_ids):
    """Новые офлайн-записи на приём, пересекающиеся по времени с другой
    записью того же врача (например, ИИ-ассистент записал в облаке на тот же
    час) — показываем администратору, чтобы развести."""
    from apps.appointments.models import Appointment
    out = []
    if not appointment_ids:
        return out
    for a in Appointment.all_objects.filter(pk__in=appointment_ids).select_related("patient", "doctor"):
        if not (a.start_at and a.end_at and a.doctor_id):
            continue
        qs = (Appointment.all_objects.filter(doctor_id=a.doctor_id, start_at__lt=a.end_at,
                                             end_at__gt=a.start_at)
              .exclude(pk=a.pk).exclude(status="cancelled"))
        if hasattr(Appointment, "is_deleted"):
            qs = qs.filter(is_deleted=False)
        if qs.exists():
            out.append(f"{timezone.localtime(a.start_at):%d.%m %H:%M} — {a.doctor.name}: "
                       f"{a.patient.full_name if a.patient_id else ''}")
    return out


# ─── ОФЛАЙН: журнал изменений и свой диапазон id ───────────────────────────
_pk_lock = threading.Lock()
_pk_next = {}


def cfg_path():
    from django.conf import settings
    return getattr(settings, "DATA_DIR", settings.BASE_DIR) / "offline_cloud.json"


def read_local_cfg():
    p = cfg_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def write_local_cfg(cfg):
    cfg_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def local_device_id():
    from django.conf import settings
    if not getattr(settings, "OFFLINE_MODE", False):
        return None
    return read_local_cfg().get("device_id")


def next_local_pk(model, device_id):
    """Следующий id из диапазона этого устройства (счётчик в памяти, при
    первом обращении — от максимального id диапазона в базе)."""
    from django.db.models import Max
    lo, hi = device_range(device_id)
    key = (model._meta.label, int(device_id))
    with _pk_lock:
        if key not in _pk_next:
            m = model._base_manager.filter(pk__gte=lo, pk__lte=hi).aggregate(m=Max("pk"))["m"]
            _pk_next[key] = (m + 1) if m else lo
        pk = _pk_next[key]
        if pk > hi:
            raise RuntimeError("Закончился диапазон id офлайн-копии")
        _pk_next[key] = pk + 1
        return pk


def on_pre_save(sender, instance, raw=False, **kw):
    if raw or applying_remote() or instance.pk is not None:
        return
    device_id = local_device_id()
    if device_id:
        instance.pk = next_local_pk(sender, device_id)


def journal(label, pk, op):
    from .models import SyncChange
    if pk is None or not pushable(label):
        return
    SyncChange.objects.filter(model_label=label, object_pk=pk).delete()
    SyncChange.objects.create(model_label=label, object_pk=pk, op=op)


def on_post_save(sender, instance, raw=False, **kw):
    if raw or applying_remote():
        return
    journal(sender._meta.label, instance.pk, "save")


def on_post_delete(sender, instance, **kw):
    if applying_remote():
        return
    journal(sender._meta.label, instance.pk, "delete")


def on_m2m_changed(sender, instance, action, **kw):
    if applying_remote() or action not in ("post_add", "post_remove", "post_clear"):
        return
    journal(instance._meta.label, instance.pk, "save")


def connect_offline_signals():
    """Подключается только в офлайн-режиме (apps.SyncConfig.ready)."""
    from django.db.models.signals import pre_save, post_save, post_delete, m2m_changed
    for label, model, _rule in _plan_models():
        pre_save.connect(on_pre_save, sender=model, dispatch_uid=f"sync-pre-{label}")
        post_save.connect(on_post_save, sender=model, dispatch_uid=f"sync-post-{label}")
        post_delete.connect(on_post_delete, sender=model, dispatch_uid=f"sync-del-{label}")
        for f in model._meta.many_to_many:
            m2m_changed.connect(on_m2m_changed, sender=f.remote_field.through,
                                dispatch_uid=f"sync-m2m-{label}-{f.name}")


def export_changes():
    """Изменения из журнала: (changes_blocks, deletions, max_journal_id)."""
    from .models import SyncChange
    entries = list(SyncChange.objects.order_by("id"))
    max_id = entries[-1].id if entries else 0
    saves, deletions = {}, []
    for e in entries:
        if e.op == SyncChange.OP_DELETE:
            deletions.append({"model": e.model_label, "pk": e.object_pk})
        else:
            saves.setdefault(e.model_label, []).append(e.object_pk)
    blocks = []
    for label, pks in saves.items():
        try:
            model = django_apps.get_model(label)
        except LookupError:
            continue
        objs = list(model._base_manager.filter(pk__in=pks))
        if objs:
            blocks.append({"model": label, "objects": _dump(objs)})
    blocks.sort(key=lambda b: PLAN_ORDER.get(b["model"], 10 ** 6))
    return blocks, deletions, max_id


def clear_journal(done, upto_id):
    """Убрать из журнала записи, по которым облако приняло решение, — только
    те, что были в отправке (правки, сделанные во время синхронизации,
    остаются)."""
    from .models import SyncChange
    keys = {(m, int(pk)) for m, pk in done if pk is not None}
    ids = [e.id for e in SyncChange.objects.filter(id__lte=upto_id)
           if (e.model_label, e.object_pk) in keys]
    SyncChange.objects.filter(id__in=ids).delete()


def pending_keys():
    from .models import SyncChange
    return set(SyncChange.objects.values_list("model_label", "object_pk"))


def replace_from_snapshot(blocks, clinic, keep=frozenset()):
    """Привести локальную базу в точное соответствие со снимком облака:
    добавить/обновить всё из снимка и удалить то, чего в облаке больше нет —
    кроме keep (ещё не отправленные свои изменения). Вызывать в транзакции."""
    counts = {}
    present = {}
    with remote_apply():
        for block in blocks:
            label = block["model"]
            try:
                django_apps.get_model(label)
            except LookupError:
                continue
            n = 0
            ids = set()
            for raw in block.get("objects", []):
                ids.add(raw.get("pk"))
                if (label, raw.get("pk")) in keep:
                    continue
                try:
                    with transaction.atomic():
                        for d in serializers.deserialize("python", [raw]):
                            d.save()
                    n += 1
                except Exception:  # noqa: BLE001
                    pass
            present[label] = ids
            counts[label] = n
        # удалить локальное, чего нет в облаке (дети раньше родителей)
        for label, model, rule in reversed(list(_plan_models())):
            if label not in present or rule == "self":
                continue
            kept = {pk for (m, pk) in keep if m == label}
            stale = set(_queryset_for(model, rule, clinic).values_list("pk", flat=True)) - present[label] - kept
            if stale:
                model._base_manager.filter(pk__in=stale)._raw_delete(model._base_manager.db)
    _heal_dangling_fks()
    return counts


def import_blocks(blocks, prefer_newer=False, since=None, collect_conflicts=False, clinic=None):
    """Загрузка снимка в локальную базу при первичной настройке (upsert по pk,
    без журнала). Приём изменений в облаке — apply_push."""
    counts = {}
    with remote_apply():
        for block in blocks:
            n = 0
            for raw in block.get("objects", []):
                try:
                    with transaction.atomic():
                        for d in serializers.deserialize("python", [raw]):
                            d.save()
                    n += 1
                except Exception:  # noqa: BLE001
                    continue
            counts[block["model"]] = n
    _heal_dangling_fks()
    return counts


def _heal_dangling_fks():
    """SQLite откладывает проверку внешних ключей до конца транзакции — до
    commit точечно устраняем нарушения (обнуляем ссылку или удаляем строку
    связи), чтобы одна «осиротевшая» ссылка не роняла всю синхронизацию."""
    from django.db import connection
    errors = {}
    if connection.vendor != "sqlite":
        return errors
    with connection.cursor() as cur:
        cur.execute("PRAGMA foreign_key_check")
        violations = cur.fetchall()
        for table, rowid, ref_table, fkid in violations:
            cur.execute(f"PRAGMA foreign_key_list({table})")
            match = [row for row in cur.fetchall() if row[0] == fkid]
            if not match:
                continue
            fk_column = match[0][3]
            try:
                cur.execute(f'UPDATE "{table}" SET "{fk_column}" = NULL WHERE rowid = %s', [rowid])
            except Exception:  # noqa: BLE001
                cur.execute(f'DELETE FROM "{table}" WHERE rowid = %s', [rowid])
            errors[table] = errors.get(table, 0) + 1
    return errors


def backup_local_db(keep=20):
    """Резервная копия локальной базы (sqlite backup API — безопасно при
    работающем сервере): DATA_DIR/backups/offline-ГГГГММДД-ЧЧММСС.sqlite3,
    хранятся последние keep копий."""
    import sqlite3
    from datetime import datetime
    from django.conf import settings
    db = settings.DATABASES["default"]
    if "sqlite" not in db["ENGINE"]:
        return None
    folder = getattr(settings, "DATA_DIR", settings.BASE_DIR) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"offline-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    src = sqlite3.connect(str(db["NAME"]))
    out = sqlite3.connect(str(dst))
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    for old in sorted(folder.glob("offline-*.sqlite3"))[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return dst
