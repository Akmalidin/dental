from django import forms
from .models import Appointment


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["patient", "doctor", "cabinet", "branch", "services", "start_at", "end_at", "status", "notes"]
        widgets = {
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "services": forms.SelectMultiple(attrs={"class": "searchable-multi"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["end_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["branch"].required = False   # проставляется во view (основной филиал)
        self.fields["status"].required = False   # по умолчанию «Записан»
        # врач — только доктора текущей клиники (а не все пользователи/создатель)
        from apps.users.models import clinic_doctors
        from apps.tenancy import get_current_clinic
        self.fields["doctor"].queryset = clinic_doctors(get_current_clinic())
        self.fields["doctor"].label_from_instance = lambda u: u.name
        for f in ("patient", "doctor", "service", "cabinet"):
            if f in self.fields:
                self.fields[f].widget.attrs["class"] = "searchable"

    def clean(self):
        cleaned = super().clean()
        doctor = cleaned.get("doctor")
        start = cleaned.get("start_at")
        end = cleaned.get("end_at")
        if doctor and start and end:
            if end <= start:
                raise forms.ValidationError("Время окончания должно быть позже начала")
            qs = Appointment.objects.filter(
                doctor=doctor, start_at__lt=end, end_at__gt=start,
            ).exclude(status=Appointment.STATUS_CANCELLED)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            clash = qs.first()
            if clash:
                raise forms.ValidationError(
                    "У врача уже есть запись на это время (%s–%s)" % (
                        clash.start_at.strftime("%d.%m %H:%M"), clash.end_at.strftime("%H:%M"))
                )
        return cleaned
