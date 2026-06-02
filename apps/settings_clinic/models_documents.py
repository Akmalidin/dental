"""Document templates with variable substitution for printing."""
from django.db import models


class DocumentTemplate(models.Model):
    TYPE_CONSENT = "consent"
    TYPE_CONTRACT = "contract"
    TYPE_PRESCRIPTION = "prescription"
    TYPE_REFERRAL = "referral"
    TYPE_CERTIFICATE = "certificate"
    TYPE_OTHER = "other"

    TYPE_CHOICES = [
        (TYPE_CONSENT, "Информированное согласие"),
        (TYPE_CONTRACT, "Договор"),
        (TYPE_PRESCRIPTION, "Назначение / рецепт"),
        (TYPE_REFERRAL, "Направление"),
        (TYPE_CERTIFICATE, "Справка"),
        (TYPE_OTHER, "Другое"),
    ]

    name = models.CharField(max_length=200, verbose_name="Название шаблона")
    doc_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_CONSENT, verbose_name="Тип")
    content = models.TextField(
        verbose_name="Содержимое",
        help_text="Используйте переменные: {{patient_name}}, {{patient_dob}}, {{doctor_name}}, {{clinic_name}}, {{date}}, {{services}}, {{tooth_numbers}}",
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Шаблон документа"
        verbose_name_plural = "Шаблоны документов"
        ordering = ["doc_type", "name"]

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.name}"

    def render(self, context: dict) -> str:
        """Replace {{variable}} placeholders with actual values."""
        text = self.content
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", str(value or ""))
        return text
