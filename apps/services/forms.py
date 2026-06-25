from django import forms
from .models import Service, ServiceCategory


class ServiceCategoryForm(forms.ModelForm):
    class Meta:
        model = ServiceCategory
        fields = ["name", "color", "sort_order"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "code", "category", "price", "dms_price", "duration", "is_active", "description",
                  "is_lab", "warranty_months", "lab_days"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "category": forms.Select(attrs={"class": "searchable"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Гарантия/срок нужны только лаб-услугам — не обязательны, пусто = 0
        for f in ("warranty_months", "lab_days"):
            self.fields[f].required = False

    def clean_warranty_months(self):
        return self.cleaned_data.get("warranty_months") or 0

    def clean_lab_days(self):
        return self.cleaned_data.get("lab_days") or 0
