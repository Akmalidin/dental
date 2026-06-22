from django import forms
from .models import Technician, TechnicianTask


class TechnicianForm(forms.ModelForm):
    class Meta:
        model = Technician
        fields = ["name", "phone", "lab_name", "lab_contact", "specialization",
                  "default_lead_days", "is_active", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class TechnicianTaskForm(forms.ModelForm):
    class Meta:
        model = TechnicianTask
        fields = ["technician", "treatment", "service", "tooth_number", "material",
                  "vita_color", "amount", "expected_ready", "doctor_comment"]
        widgets = {"expected_ready": forms.DateInput(attrs={"type": "date"})}
