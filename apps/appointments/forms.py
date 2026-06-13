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
        from apps.users.models import clinic_doctors, Branch
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        self.fields["doctor"].queryset = clinic_doctors(clinic)
        self.fields["doctor"].label_from_instance = lambda u: u.name
        # филиал и кабинет — только текущей клиники (изоляция между клиниками)
        if clinic is not None:
            branches = Branch.objects.filter(clinic=clinic, is_active=True)
            inst = self.instance
            if inst and inst.pk and inst.branch_id:
                branches = (branches | Branch.objects.filter(pk=inst.branch_id)).distinct()
            self.fields["branch"].queryset = branches
            if "cabinet" in self.fields:
                from .models import Cabinet
                cabs = Cabinet.objects.filter(branch__clinic=clinic)
                if inst and inst.pk and inst.cabinet_id:
                    cabs = (cabs | Cabinet.objects.filter(pk=inst.cabinet_id)).distinct()
                self.fields["cabinet"].queryset = cabs
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
            # график работы врача — нельзя записать в нерабочий день/часы
            from .views import schedule_violation
            sched_err = schedule_violation(doctor, start, end)
            if sched_err:
                raise forms.ValidationError(sched_err)
            qs = Appointment.objects.filter(
                doctor=doctor, start_at__lt=end, end_at__gt=start,
            ).exclude(status__in=[Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW])
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            clash = qs.first()
            if clash:
                from django.utils import timezone as _tz
                cs, ce = _tz.localtime(clash.start_at), _tz.localtime(clash.end_at)
                raise forms.ValidationError(
                    "У врача уже есть запись на это время (%s–%s)" % (
                        cs.strftime("%d.%m %H:%M"), ce.strftime("%H:%M"))
                )
        return cleaned
