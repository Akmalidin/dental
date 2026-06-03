"""
Оффлайн-режим: экспорт/импорт данных одной клиники между облаком и локальной копией.

Идея: пользователь работает локально (localhost, SQLite). При первом запуске
скачивает все данные своей клиники с облака. По кнопке «Синхронизация» отправляет
локальные изменения в облако (push) и забирает свежие данные (pull).

Этот модуль — ядро: сбор объектов клиники и (де)сериализация в JSON.
"""
from django.core import serializers
from django.apps import apps as django_apps


# Порядок важен: родители раньше детей (для корректной загрузки FK).
# (app_label, ModelName, способ фильтрации по клинике)
#   "direct"  — у модели есть поле clinic
#   ("via", "fk_path")  — фильтр по клинике через связь
EXPORT_PLAN = [
    ("users", "Clinic", "self"),
    ("users", "Role", "all"),                       # роли общие
    ("users", "Branch", "direct"),
    ("users", "User", "direct"),
    ("patients", "LeadSource", "all"),
    ("patients", "Tag", "all"),
    ("patients", "InsuranceCompany", "all"),
    ("services", "ServiceCategory", "direct"),
    ("services", "Service", "direct"),
    ("warehouse", "Supplier", "direct"),
    ("warehouse", "ProductCategory", "direct"),
    ("warehouse", "Product", "direct"),
    ("finance", "ExpenseCategory", "direct"),
    ("appointments", "CancellationReason", "all"),
    ("settings_clinic", "DocumentTemplate", "direct"),
    ("medicines", "Medicine", "direct"),
    ("patients", "Patient", "direct"),
    ("treatments", "MedicalRecordTemplate", "direct"),
    ("treatments", "Treatment", "direct"),
    ("treatments", "TreatmentCure", ("via", "treatment__clinic")),
    ("treatments", "MedicalRecord", ("via", "treatment__clinic")),
    ("treatments", "TreatmentPlan", ("via", "patient__clinic")),
    ("treatments", "TreatmentPlanItem", ("via", "plan__patient__clinic")),
    ("appointments", "Appointment", "direct"),
    ("finance", "Payment", "direct"),
    ("finance", "Expense", "direct"),
    ("medicines", "PatientMedicine", ("via", "patient__clinic")),
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
        data = serializers.serialize("python", qs)
        blocks.append({"model": f"{app_label}.{model_name}", "objects": data, "count": len(data)})
    return blocks


def import_blocks(blocks):
    """Загрузить блоки в локальную БД (upsert по PK). Возвращает счётчики."""
    counts = {}
    for block in blocks:
        objs = block.get("objects", [])
        n = 0
        for obj in serializers.deserialize("python", objs):
            obj.save()
            n += 1
        counts[block["model"]] = n
    return counts
