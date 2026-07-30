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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Изоляция клиник — переприсваиваем querysets ЗАНОВО на каждый запрос (см.
        # apps/appointments/forms.py AppointmentForm: ModelForm строит base_fields один
        # раз при импорте модуля, когда текущей клиники ещё нет — без переприсвоения
        # здесь пациенты/лекарства/приёмы чужих клиник утекают в выпадающие списки).
        from apps.patients.models import Patient
        from apps.treatments.models import Treatment
        from apps.users.models import clinic_doctors
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        inst = self.instance

        patients = Patient.objects.all()
        if inst and inst.pk and inst.patient_id:
            patients = (patients | Patient.all_objects.filter(pk=inst.patient_id)).distinct()
        self.fields["patient"].queryset = patients

        medicines = Medicine.objects.all()
        if inst and inst.pk and inst.medicine_id:
            medicines = (medicines | Medicine.all_clinics.filter(pk=inst.medicine_id)).distinct()
        self.fields["medicine"].queryset = medicines

        treatments = Treatment.objects.all()
        if inst and inst.pk and inst.treatment_id:
            treatments = (treatments | Treatment.all_objects.filter(pk=inst.treatment_id)).distinct()
        self.fields["treatment"].queryset = treatments

        doctor_ids = set(clinic_doctors(clinic).values_list("pk", flat=True))
        if inst and inst.pk and inst.doctor_id:
            doctor_ids.add(inst.doctor_id)
        from apps.users.models import User as _U
        self.fields["doctor"].queryset = _U.objects.filter(pk__in=doctor_ids)
