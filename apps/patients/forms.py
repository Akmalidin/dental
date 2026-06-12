from django import forms
from .models import Patient, Tag, LeadSource
from apps.users.models import Branch


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "first_name", "last_name", "middle_name",
            "birth_date", "gender", "phone", "phone2",
            "address", "source", "primary_doctor", "tags", "branch",
            "insurance", "insurance_policy", "insurance_valid_until",
            "notes",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "insurance_valid_until": forms.DateInput(attrs={"type": "date"}),
            "tags": forms.CheckboxSelectMultiple(),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "source": forms.Select(attrs={"class": "searchable"}),
            "primary_doctor": forms.Select(attrs={"class": "searchable"}),
            "branch": forms.Select(attrs={"class": "searchable"}),
            "insurance": forms.Select(attrs={"class": "searchable"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Изоляция клиник: «Лечащий врач» и «Филиал» — только текущей клиники.
        # User не привязан к менеджеру клиники, поэтому фильтруем явно.
        from apps.tenancy import get_current_clinic
        from apps.users.models import clinic_doctors
        clinic = get_current_clinic()
        if clinic is not None:
            from apps.users.models import User as _U
            doctor_ids = set(clinic_doctors(clinic).values_list("pk", flat=True))
            branches = Branch.objects.filter(clinic=clinic, is_active=True)
            # При редактировании сохраняем уже выбранное значение в списке,
            # даже если оно вне текущего фильтра (иначе форма не пройдёт валидацию).
            inst = self.instance
            if inst and inst.pk:
                if inst.primary_doctor_id:
                    doctor_ids.add(inst.primary_doctor_id)
                if inst.branch_id:
                    branches = (branches | Branch.objects.filter(pk=inst.branch_id)).distinct()
            self.fields["primary_doctor"].queryset = _U.objects.filter(pk__in=doctor_ids)
            self.fields["branch"].queryset = branches
