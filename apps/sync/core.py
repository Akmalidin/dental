"""
Оффлайн-режим: экспорт/импорт данных одной клиники между облаком и локальной копией.

Идея: пользователь работает локально (localhost, SQLite). При первом запуске
скачивает все данные своей клиники с облака. По кнопке «Синхронизация» отправляет
локальные изменения в облако (push) и забирает свежие данные (pull).

Этот модуль — ядро: сбор объектов клиники, (де)сериализация в JSON и обнаружение
конфликтов (запись менялась И локально, И в облаке после последней синхронизации).
"""
import json
from django.core import serializers
from django.apps import apps as django_apps
from django.utils.dateparse import parse_datetime


# Порядок важен: родители раньше детей (для корректной загрузки FK).
# (app_label, ModelName, способ фильтрации по клинике)
#   "direct"  — у модели есть поле clinic
#   ("via", "fk_path")  — фильтр по клинике через связь
EXPORT_PLAN = [
    ("users", "Clinic", "self"),
    ("users", "Role", "all"),                       # роли общие
    ("users", "Branch", "direct"),
    ("users", "User", "direct"),
    ("appointments", "Cabinet", ("via", "branch__clinic")),
    ("patients", "LeadSource", "all"),
    ("patients", "Tag", "all"),
    ("patients", "InsuranceCompany", "all"),
    ("services", "ServiceCategory", "direct"),
    ("services", "Service", "direct"),
    ("technicians", "Technician", "direct"),
    ("warehouse", "Supplier", "direct"),
    ("warehouse", "ProductCategory", "direct"),
    ("warehouse", "Product", "direct"),
    ("finance", "ExpenseCategory", "direct"),
    ("appointments", "CancellationReason", "all"),
    ("settings_clinic", "DocumentTemplate", "direct"),
    ("medicines", "Medicine", "direct"),
    ("patients", "Patient", "direct"),
    ("treatments", "MedicalRecordTemplate", "direct"),
    ("treatments", "ToothStatus", "all"),
    ("treatments", "ToothCondition", ("via", "patient__clinic")),
    ("treatments", "Treatment", "direct"),
    ("treatments", "TreatmentCure", ("via", "treatment__clinic")),
    ("technicians", "TechnicianTask", "direct"),
    ("treatments", "MedicalRecord", ("via", "treatment__clinic")),
    ("treatments", "TreatmentPlan", ("via", "patient__clinic")),
    ("treatments", "TreatmentPlanStage", ("via", "plan__patient__clinic")),
    ("treatments", "TreatmentPlanItem", ("via", "plan__patient__clinic")),
    ("appointments", "Appointment", "direct"),
    ("finance", "Payment", "direct"),
    ("finance", "Expense", "direct"),
    ("finance", "PatientAdvance", ("via", "patient__clinic")),
    ("medicines", "PatientMedicine", ("via", "patient__clinic")),
    ("technicians", "TechnicianWarrantyCase", "direct"),
]


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


def export_clinic(clinic):
    """Сериализовать все данные клиники в список блоков JSON-объектов."""
    blocks = []
    for app_label, model_name, rule in EXPORT_PLAN:
        try:
            model = django_apps.get_model(app_label, model_name)
        except LookupError:
            continue
        qs = _queryset_for(model, rule, clinic)
        # сериализуем в JSON-формат (даты → строки), затем в чистые dict —
        # чтобы блоки были JSON-безопасны для отправки на сервер
        data = json.loads(serializers.serialize("json", qs))
        blocks.append({"model": f"{app_label}.{model_name}", "objects": data, "count": len(data)})
    return blocks


def _object_repr(raw):
    """Короткое человекочитаемое описание записи для списка конфликтов."""
    f = raw.get("fields", {}) or {}
    for combo in (("last_name", "first_name"), ("title",), ("name",)):
        parts = [str(f[k]) for k in combo if f.get(k)]
        if parts:
            return " ".join(parts)
    return f"#{raw.get('pk')}"


def import_blocks(blocks, prefer_newer=False, since=None, collect_conflicts=False):
    """Загрузить блоки (upsert по PK).

    prefer_newer=True — НЕ перезаписывать запись, если у получателя версия свежее
    (по updated_at). Простой режим без учёта того, менялась ли запись локально.

    since — datetime последней успешной синхронизации. Вместе с
    collect_conflicts=True включает точное обнаружение конфликтов: запись
    считается конфликтной, только если она реально менялась И локально,
    И в облаке после этой отметки (а не просто «у получателя версия новее» —
    так мы не путаем «в облаке просто ничего не менялось» с настоящим
    одновременным редактированием с двух сторон).

    Конфликтные записи НЕ применяются автоматически — они возвращаются
    списком (см. sync_push), а текущая (облачная) версия остаётся как есть.
    """
    from django.db import transaction

    counts = {}
    skipped = {}
    errors_by_model = {}
    conflicts = []
    for block in blocks:
        n = sk = err = 0
        model_label = block["model"]
        try:
            app_label, model_name = model_label.split(".")
            model = django_apps.get_model(app_label, model_name)
        except Exception:
            model = None

        for raw in block.get("objects", []):
            pk = raw.get("pk")
            fields = raw.get("fields", {}) or {}
            existing = None
            if model is not None and pk is not None:
                existing = model._base_manager.filter(pk=pk).first()
            up_dt = parse_datetime(fields["updated_at"]) if fields.get("updated_at") else None
            ex_up = getattr(existing, "updated_at", None) if existing else None

            if collect_conflicts and since is not None and up_dt is not None and ex_up is not None:
                local_changed = up_dt > since
                cloud_changed = ex_up > since
                if local_changed and cloud_changed:
                    cloud_snapshot = json.loads(serializers.serialize("json", [existing]))[0]
                    conflicts.append({
                        "model": model_label, "pk": pk,
                        "object_repr": _object_repr(raw),
                        "local_data": raw, "cloud_data": cloud_snapshot,
                        "local_updated_at": up_dt.isoformat(), "cloud_updated_at": ex_up.isoformat(),
                    })
                    sk += 1
                    continue
                if not local_changed:
                    sk += 1
                    continue  # локально не менялось — облако не трогаем
            elif prefer_newer and ex_up is not None and up_dt is not None and ex_up > up_dt:
                sk += 1
                continue  # в облаке версия свежее — не затираем

            # На бэкендах с немедленной проверкой внешних ключей (PostgreSQL —
            # так работает облако) savepoint на объект ловит нарушение сразу
            # и пропускает именно эту запись. На SQLite (локальная копия)
            # проверка отложена до конца транзакции — там подчищаем через
            # _heal_dangling_fks() ниже, savepoint здесь безвреден, но сам
            # по себе нарушение не поймает.
            try:
                with transaction.atomic():
                    for d in serializers.deserialize("python", [raw]):
                        d.save()
                n += 1
            except Exception:
                err += 1
                continue
        counts[model_label] = n
        if sk:
            skipped[model_label] = sk
        if err:
            errors_by_model[model_label] = err

    # SQLite откладывает проверку внешних ключей до конца транзакции (нельзя
    # поймать нарушение через try/except на отдельном объекте — сохранение
    # «проходит», а падает только итоговый commit). Поэтому здесь, ДО commit,
    # ищем реальные нарушения и точечно лечим именно их — обнуляем нерабочую
    # ссылку (если поле необязательное) или удаляем именно эту связь (если
    # обязательное, например M2M) — а не роняем всю синхронизацию сотен
    # объектов из-за одной «осиротевшей» ссылки где-то в старых данных.
    for table, n_healed in _heal_dangling_fks().items():
        errors_by_model[table] = errors_by_model.get(table, 0) + n_healed
    errors = errors_by_model

    if collect_conflicts:
        return {"applied": counts, "skipped": skipped, "conflicts": conflicts, "errors": errors}
    if prefer_newer:
        return {"applied": counts, "skipped": skipped, "errors": errors}
    return counts


def _heal_dangling_fks():
    """См. import_blocks: точечно устраняет нарушения внешних ключей,
    оставшиеся в текущей (незакоммиченной) транзакции SQLite, чтобы не
    ронять всю синхронизацию из-за единичных «осиротевших» ссылок."""
    from django.db import connection
    errors = {}
    if connection.vendor != "sqlite":
        return errors
    with connection.cursor() as cur:
        cur.execute("PRAGMA foreign_key_check")
        violations = cur.fetchall()
        for table, rowid, ref_table, fkid in violations:
            cur.execute(f"PRAGMA foreign_key_list({table})")
            fk_list = cur.fetchall()
            if fkid >= len(fk_list):
                continue
            fk_column = fk_list[fkid][3]  # 'from' — имя колонки с внешним ключом
            try:
                cur.execute(f'UPDATE "{table}" SET "{fk_column}" = NULL WHERE rowid = %s', [rowid])
            except Exception:
                # поле обязательное (NOT NULL, например M2M-таблица связи) —
                # удаляем именно эту повреждённую строку/связь целиком
                cur.execute(f'DELETE FROM "{table}" WHERE rowid = %s', [rowid])
            errors[table] = errors.get(table, 0) + 1
    return errors
