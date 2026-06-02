from django import forms
from .models import Product, WarehouseEntry, WarehouseDistribution


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "category", "unit", "min_qty", "supplier", "is_active"]


class WarehouseEntryForm(forms.ModelForm):
    class Meta:
        model = WarehouseEntry
        fields = ["product", "quantity", "price", "supplier", "date", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "product": forms.Select(attrs={"class": "searchable"}),
            "supplier": forms.Select(attrs={"class": "searchable"}),
        }


class WarehouseDistributionForm(forms.ModelForm):
    class Meta:
        model = WarehouseDistribution
        fields = ["product", "quantity", "branch", "issued_to", "date", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "product": forms.Select(attrs={"class": "searchable"}),
            "issued_to": forms.Select(attrs={"class": "searchable"}),
        }
