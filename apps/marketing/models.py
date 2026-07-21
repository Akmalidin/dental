from django.db import models


class LandingLead(models.Model):
    """Заявка с лендинга stom.asia — клиника хочет подключиться."""
    clinic_name = models.CharField(max_length=200, verbose_name="Название клиники")
    phone = models.CharField(max_length=30, verbose_name="Телефон / WhatsApp")
    city = models.CharField(max_length=120, blank=True, verbose_name="Город")
    created_at = models.DateTimeField(auto_now_add=True)
    contacted = models.BooleanField(default=False, verbose_name="Связались")

    class Meta:
        verbose_name = "Заявка с лендинга"
        verbose_name_plural = "Заявки с лендинга (stom.asia)"
        ordering = ["-created_at"]

    def __str__(self):
        return "%s — %s" % (self.clinic_name, self.phone)
