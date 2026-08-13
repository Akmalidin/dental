"""
Статусы зубной карты (справочник состояний зуба) и состояние зубов пациента.
"""
from django.db import models
from django.conf import settings


# Дефолтные статусы: (код, название, цвет HEX)
DEFAULT_TOOTH_STATUSES = [
    ("healthy", "Здоров", "#22C55E"),
    ("caries", "Кариес", "#F59E0B"),
    ("filling", "Пломба", "#3B82F6"),
    ("root_canal", "Лечён канал", "#8B5CF6"),
    ("crown", "Коронка", "#EAB308"),
    ("implant", "Имплант", "#06B6D4"),
    ("bridge", "Мост", "#14B8A6"),
    ("to_remove", "Подлежит удалению", "#F97316"),
    ("missing", "Отсутствует / удалён", "#EF4444"),
]

# Каталог статусов зуба в БД (ToothStatus, коды выше) — не тот же словарь,
# что богатый клинический список кодов зубной карты нового интерфейса
# (toothConditions в templates/newui/base.html, ~30 кодов); сопоставляем на
# ближайший визуально. Общий источник для apps.users.views (карточка
# пациента) и apps.treatments.views_visit (карточка приёма), чтобы не разойтись.
REAL_TO_JS_TOOTH_CODE = {
    "healthy": "norma", "caries": "caries_mid", "filling": "filling",
    "root_canal": "canal_filled", "crown": "crown", "implant": "implant",
    "bridge": "bridge", "to_remove": "to_remove", "missing": "missing",
}
JS_TO_REAL_TOOTH_CODE = {v: k for k, v in REAL_TO_JS_TOOTH_CODE.items()}


class ToothStatus(models.Model):
    """Справочник состояний зуба с цветом."""
    code = models.CharField(max_length=40, blank=True, verbose_name="Код")
    name = models.CharField(max_length=80, verbose_name="Название")
    color = models.CharField(max_length=9, default="#6366F1", verbose_name="Цвет")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Статус зуба"
        verbose_name_plural = "Статусы зубов"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class ToothCondition(models.Model):
    """Текущее состояние конкретного зуба у пациента."""
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="tooth_conditions"
    )
    tooth_number = models.PositiveSmallIntegerField(verbose_name="Зуб (FDI)")
    status = models.ForeignKey(
        ToothStatus, on_delete=models.SET_NULL, null=True, blank=True, related_name="conditions"
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Заметка")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Состояние зуба"
        verbose_name_plural = "Состояния зубов"
        unique_together = [("patient", "tooth_number")]
        ordering = ["tooth_number"]

    def __str__(self):
        return f"{self.patient_id} · зуб {self.tooth_number}"


# Поверхности и дёсны — отдельные уровни детализации зубной карты (не то же
# самое, что ToothStatus/ToothCondition выше — состояние зуба целиком). Коды
# берём 1:1 из templates/newui/base.html:surfaceConditions/gumConditions —
# в отличие от ToothStatus (где приходится сопоставлять через
# REAL_TO_JS_TOOTH_CODE, т.к. справочник в БД грубее богатого JS-списка),
# здесь коды в БД специально заведены совпадающими с JS, конвертация не нужна.
DEFAULT_SURFACE_STATUSES = [
    ("secondary_caries", "Вторичный кариес", "#B0B0B0"),
    ("filling", "Пломба", "#6A3FE8"),
    ("fluorosis", "Флюороз", "#4CD964"),
    ("temp_filling", "Временная пломба", "#E91E8C"),
    ("caries_simple", "Кариес", "#9C94EA"),
    ("chip_simple", "Скол", "#8BC34A"),
]
DEFAULT_GUM_STATUSES = [
    ("parodontoz", "Пародонтоз", "#F5A623"),
    ("fluss", "Флюс", "#3B82F6"),
    ("gum_inflammation", "Воспаление дёсны", "#EC1E79"),
    ("parodontit", "Пародонтит", "#4B5259"),
]


class ToothSurfaceStatus(models.Model):
    """Справочник состояний поверхности зуба (клик по сегменту индикатора)."""
    code = models.CharField(max_length=40, blank=True, verbose_name="Код")
    name = models.CharField(max_length=80, verbose_name="Название")
    color = models.CharField(max_length=9, default="#6366F1", verbose_name="Цвет")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Статус поверхности зуба"
        verbose_name_plural = "Статусы поверхностей зубов"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class ToothGumStatus(models.Model):
    """Справочник состояний дёсен/пародонта у конкретного зуба."""
    code = models.CharField(max_length=40, blank=True, verbose_name="Код")
    name = models.CharField(max_length=80, verbose_name="Название")
    color = models.CharField(max_length=9, default="#6366F1", verbose_name="Цвет")
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Статус дёсен"
        verbose_name_plural = "Статусы дёсен"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class ToothSurfaceCondition(models.Model):
    """Текущее состояние одной из 6 поверхностей конкретного зуба у пациента.
    Раньше это жило только в JS-памяти браузера (surfaceStates в base.html) и
    терялось при перезагрузке страницы — карточка приёма визуально обещала
    сохранение (модалка «поверхность»), а по факту не сохраняла ничего."""
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="tooth_surface_conditions"
    )
    tooth_number = models.PositiveSmallIntegerField(verbose_name="Зуб (FDI)")
    surface_index = models.PositiveSmallIntegerField(verbose_name="Поверхность (0–5)")
    status = models.ForeignKey(
        ToothSurfaceStatus, on_delete=models.SET_NULL, null=True, blank=True, related_name="conditions"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Состояние поверхности зуба"
        verbose_name_plural = "Состояния поверхностей зубов"
        unique_together = [("patient", "tooth_number", "surface_index")]
        ordering = ["tooth_number", "surface_index"]

    def __str__(self):
        return f"{self.patient_id} · зуб {self.tooth_number} · поверхность {self.surface_index}"


class ToothGumCondition(models.Model):
    """Текущее состояние дёсен у конкретного зуба пациента (та же история
    несохранения, что и у ToothSurfaceCondition — см. её докстрок)."""
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="tooth_gum_conditions"
    )
    tooth_number = models.PositiveSmallIntegerField(verbose_name="Зуб (FDI)")
    status = models.ForeignKey(
        ToothGumStatus, on_delete=models.SET_NULL, null=True, blank=True, related_name="conditions"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Состояние дёсен зуба"
        verbose_name_plural = "Состояния дёсен зубов"
        unique_together = [("patient", "tooth_number")]
        ordering = ["tooth_number"]

    def __str__(self):
        return f"{self.patient_id} · зуб {self.tooth_number} · дёсны"
