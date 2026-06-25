from django import forms
from .models import Payment, Expense


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["patient", "treatment", "amount", "method", "type", "branch", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "patient": forms.Select(attrs={"class": "searchable"}),
            "treatment": forms.Select(attrs={"class": "searchable"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # филиал проставляется во view (основной), поэтому в форме не обязателен
        self.fields["branch"].required = False


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["amount", "description", "branch", "date"]  # категория — авто
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # филиал — только текущей клиники (без утечки чужих клиник)
        from apps.users.models import Branch
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        qs = Branch.all_clinics.filter(is_active=True)
        if clinic is not None:
            qs = qs.filter(clinic=clinic)
        self.fields["branch"].queryset = qs.order_by("-is_main", "name")
        self.fields["branch"].required = False
