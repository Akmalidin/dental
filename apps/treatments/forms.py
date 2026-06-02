from django import forms
from django.forms import inlineformset_factory
from .models import Treatment, TreatmentCure


class TreatmentForm(forms.ModelForm):
    class Meta:
        model = Treatment
        fields = ["patient", "doctor", "branch", "status", "discount", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "patient": forms.Select(attrs={"class": "searchable"}),
            "doctor": forms.Select(attrs={"class": "searchable"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # branch проставляется во view (основной филиал), поэтому не обязателен в форме
        self.fields["branch"].required = False


class TreatmentCureForm(forms.ModelForm):
    class Meta:
        model = TreatmentCure
        fields = ["service", "tooth_number", "quantity", "price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Don't inherit model default (1) as initial — otherwise an empty extra
        # row is treated as "changed" and wrongly required. Empty rows stay empty.
        self.fields["quantity"].initial = None
        self.fields["quantity"].required = False


TreatmentCureFormSet = inlineformset_factory(
    Treatment,
    TreatmentCure,
    form=TreatmentCureForm,
    extra=1,
    can_delete=True,
)
