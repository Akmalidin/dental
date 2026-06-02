from django import forms
from .models import Medicine, PatientMedicine


class MedicineForm(forms.ModelForm):
    class Meta:
        model = Medicine
        fields = ["name", "form", "quantity", "unit", "min_qty", "is_active"]


class PatientMedicineForm(forms.ModelForm):
    class Meta:
        model = PatientMedicine
        fields = ["patient", "treatment", "medicine", "dosage", "duration", "doctor", "date", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "patient": forms.Select(attrs={"class": "searchable"}),
            "medicine": forms.Select(attrs={"class": "searchable"}),
            "doctor": forms.Select(attrs={"class": "searchable"}),
            "treatment": forms.Select(attrs={"class": "searchable"}),
        }
