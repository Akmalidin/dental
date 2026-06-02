"""
Insurance companies and DMS (voluntary medical insurance) module.
Placed here to avoid a separate app for small functionality.
"""
from django.db import models


class InsuranceCompany(models.Model):
    name = models.CharField(max_length=200, verbose_name="Страховая компания")
    short_name = models.CharField(max_length=100, blank=True, verbose_name="Краткое наименование")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Телефон")
    email = models.EmailField(blank=True, verbose_name="Email")
    contact_person = models.CharField(max_length=200, blank=True, verbose_name="Контактное лицо")
    address = models.CharField(max_length=500, blank=True, verbose_name="Адрес")
    notes = models.TextField(blank=True, verbose_name="Примечания")
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Страховая компания"
        verbose_name_plural = "Страховые компании"
        ordering = ["name"]

    def __str__(self):
        return self.short_name or self.name
