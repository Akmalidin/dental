from django import forms
from .models import Technician, TechnicianTask


class TechnicianForm(forms.ModelForm):
    class Meta:
        model = Technician
        fields = ["name", "phone", "is_active", "notes"]


class TechnicianTaskForm(forms.ModelForm):
    class Meta:
        model = TechnicianTask
        fields = ["technician", "treatment", "service", "amount", "deadline", "notes"]
        widgets = {"deadline": forms.DateInput(attrs={"type": "date"})}
