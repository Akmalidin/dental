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
        self.fields["branch"].required = False
        # только филиалы текущей клиники
        from apps.users.models import Branch
        from apps.patients.models import Patient
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        qs = Branch.all_clinics.filter(is_active=True)
        if clinic is not None:
            qs = qs.filter(clinic=clinic)
        self.fields["branch"].queryset = qs.order_by("-is_main", "name")
        # Пациент — переприсваиваем ЗАНОВО на каждый запрос (см. apps/appointments/forms.py
        # AppointmentForm: ModelForm строит base_fields один раз при импорте модуля, когда
        # текущей клиники ещё нет — без переприсвоения здесь список пациентов утекает
        # между клиниками).
        patients = Patient.objects.all()
        inst = self.instance
        if inst and inst.pk and inst.patient_id:
            patients = (patients | Patient.all_objects.filter(pk=inst.patient_id)).distinct()
        self.fields["patient"].queryset = patients


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
