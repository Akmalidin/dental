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
        fields = ["category", "amount", "description", "branch", "date"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }
