from django import forms
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from .models import User, Role, Branch


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

    class Meta:
        model = User
        fields = ["login", "name", "email", "phone", "role", "roles", "branches",
                  "can_view_all_appointments", "is_active", "avatar"]
        widgets = {
            "branches": forms.CheckboxSelectMultiple(),
            "roles": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].label = "Основная роль"
        self.fields["role"].required = False
        self.fields["roles"].label = "Дополнительные роли (можно несколько)"
        self.fields["roles"].required = False
        self.fields["can_view_all_appointments"].label = "Видит записи всех врачей"
        self.fields["can_view_all_appointments"].required = False

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
        fields = ["name", "address", "phone", "is_main", "is_active"]
