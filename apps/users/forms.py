from django import forms
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from .models import User, Role, Branch, SECTIONS


class LoginForm(forms.Form):
    login = forms.CharField(
        label=_("Логин"),
        widget=forms.TextInput(attrs={"autofocus": True, "class": "form-input", "placeholder": "Логин или email"}),
    )
    password = forms.CharField(
        label=_("Пароль"),
        widget=forms.PasswordInput(attrs={"class": "form-input", "placeholder": "Пароль"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        login = self.cleaned_data.get("login")
        password = self.cleaned_data.get("password")
        if login and password:
            self.user_cache = authenticate(self.request, username=login, password=password)
            if self.user_cache is None:
                raise forms.ValidationError(_("Неверный логин или пароль"))
            if not self.user_cache.is_active:
                raise forms.ValidationError(_("Аккаунт отключён"))
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class UserForm(forms.ModelForm):
    password = forms.CharField(
        label=_("Пароль"),
        widget=forms.PasswordInput(),
        required=False,
        help_text=_("Оставьте пустым, чтобы не менять пароль"),
    )
    # Персональные доступы к разделам. full_access=True → allowed_sections=None (все разделы).
    full_access = forms.BooleanField(
        label=_("Полный доступ ко всем разделам"), required=False, initial=True,
    )
    sections = forms.MultipleChoiceField(
        label=_("Доступные разделы"), required=False,
        choices=[(k, lbl) for k, lbl, _url in SECTIONS if k != "dashboard"],
        widget=forms.CheckboxSelectMultiple(),
    )
    doctor_types = forms.MultipleChoiceField(
        label=_("Тип врача"), required=False,
        choices=User.DOCTOR_TYPE_CHOICES,
        widget=forms.CheckboxSelectMultiple(),
        help_text=_("Для фильтра по специализации при записи на приём"),
    )

    class Meta:
        model = User
        fields = ["login", "name", "email", "phone", "role", "roles", "branches",
                  "can_view_all_appointments", "is_active", "avatar",
                  "specialty", "doctor_types"]
        widgets = {
            "branches": forms.CheckboxSelectMultiple(),
            "roles": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, request_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].label = "Основная роль"
        self.fields["role"].required = False
        self.fields["roles"].label = "Дополнительные роли (можно несколько)"
        self.fields["roles"].required = False
        # Роль суперадмина назначает только сам суперадмин — остальным её не показываем и не даём выбрать.
        if not (request_user and request_user.is_superadmin):
            self.fields["role"].queryset = self.fields["role"].queryset.exclude(name=Role.SUPERADMIN)
            self.fields["roles"].queryset = self.fields["roles"].queryset.exclude(name=Role.SUPERADMIN)
        self.fields["can_view_all_appointments"].label = "Видит записи всех врачей"
        self.fields["can_view_all_appointments"].required = False
        # Филиалы — только текущей клиники (queryset вычисляется в запросе, а не на импорте,
        # иначе ModelForm захватывает несфильтрованный список всех клиник).
        self.fields["branches"].queryset = Branch.objects.all()
        # Предзаполнить доступы из allowed_sections редактируемого пользователя.
        inst = self.instance if self.instance and self.instance.pk else None
        if inst is not None and not self.is_bound:
            if inst.allowed_sections is None:
                self.fields["full_access"].initial = True
                self.fields["sections"].initial = [k for k, _l, _u in SECTIONS if k != "dashboard"]
            else:
                self.fields["full_access"].initial = False
                self.fields["sections"].initial = list(inst.allowed_sections)

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "address", "phone", "hours", "latitude", "longitude", "is_main", "is_active"]
        widgets = {
            "latitude": forms.NumberInput(attrs={"step": "any", "placeholder": "42.8746"}),
            "longitude": forms.NumberInput(attrs={"step": "any", "placeholder": "74.5698"}),
            "hours": forms.TextInput(attrs={"placeholder": "Пн–Сб: 09:00–18:00"}),
        }


class CabinetForm(forms.ModelForm):
    class Meta:
        from apps.appointments.models import Cabinet
        model = Cabinet
        fields = ["name", "color", "is_active"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}
