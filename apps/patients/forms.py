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
