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
