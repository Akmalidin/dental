from django import forms
from django.forms import inlineformset_factory
from .models import Treatment, TreatmentCure


class TreatmentForm(forms.ModelForm):
    class Meta:
        model = Treatment
        fields = ["patient", "doctor", "branch", "status", "discount", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "patient": forms.Select(attrs={"class": "searchable"}),
            "doctor": forms.Select(attrs={"class": "searchable"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # branch проставляется во view (основной филиал), поэтому не обязателен в форме
        self.fields["branch"].required = False
        # Изоляция клиник: врач и филиал — только текущей клиники.
        from apps.tenancy import get_current_clinic
        from apps.users.models import clinic_doctors, Branch
        clinic = get_current_clinic()
        if clinic is not None:
            from apps.users.models import User as _U
            doctor_ids = set(clinic_doctors(clinic).values_list("pk", flat=True))
            branches = Branch.objects.filter(clinic=clinic, is_active=True)
            # Не ломаем редактирование уже существующего приёма: текущий врач/филиал
            # остаётся в списке, даже если он вне фильтра.
            inst = self.instance
            if inst and inst.pk:
                if inst.doctor_id:
                    doctor_ids.add(inst.doctor_id)
                if inst.branch_id:
                    branches = (branches | Branch.objects.filter(pk=inst.branch_id)).distinct()
            self.fields["doctor"].queryset = _U.objects.filter(pk__in=doctor_ids)
            self.fields["branch"].queryset = branches


class TreatmentCureForm(forms.ModelForm):
    class Meta:
        model = TreatmentCure
        fields = ["service", "tooth_number", "quantity", "price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Don't inherit model default (1) as initial — otherwise an empty extra
        # row is treated as "changed" and wrongly required. Empty rows stay empty.
        self.fields["quantity"].initial = None
        self.fields["quantity"].required = False


TreatmentCureFormSet = inlineformset_factory(
    Treatment,
    TreatmentCure,
    form=TreatmentCureForm,
    extra=1,
    can_delete=True,
)
