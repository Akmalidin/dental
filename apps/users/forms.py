from django import forms
from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from .models import User, Role, Branch, SECTIONS


# Защита от подбора пароля: после LOGIN_MAX_FAILS неудачных попыток подряд
# для одного логина вход по нему закрыт на LOGIN_LOCK_MINUTES (успешный вход
# обнуляет счётчик). С одного IP — не больше LOGIN_MAX_IP_FAILS неудач за то
# же окно (перебор разных логинов). Считаем по журналу входов
# ClinicLoginEvent — он общий для всех воркеров gunicorn, в отличие от
# локального кэша.
LOGIN_MAX_FAILS = 5
LOGIN_MAX_IP_FAILS = 20
LOGIN_LOCK_MINUTES = 15


def _minutes_left(oldest, now):
    import math
    from datetime import timedelta
    return max(1, math.ceil(((oldest + timedelta(minutes=LOGIN_LOCK_MINUTES)) - now).total_seconds() / 60))


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
            from django.db.models import Q
            from django.utils import timezone
            from apps.tenancy import get_client_ip
            from .models import BlockedIP, ClinicLoginEvent
            ip = get_client_ip(self.request) if self.request else None
            # Блокировка со сроком (BlockedIP.expires_at) больше не действует
            # после истечения — но запись не удаляется (история блокировок
            # остаётся видна в Аудит-центре), поэтому не просто .exists() по
            # ip_address, а с учётом срока.
            if ip and BlockedIP.objects.filter(ip_address=ip).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            ).exists():
                raise forms.ValidationError(_("Доступ с этого IP заблокирован"))
            from datetime import timedelta
            now = timezone.now()
            since = now - timedelta(minutes=LOGIN_LOCK_MINUTES)
            last_ok = (ClinicLoginEvent.objects.filter(attempted_login__iexact=login, success=True, created_at__gte=since)
                       .order_by("-created_at").values_list("created_at", flat=True).first())
            fails = list(ClinicLoginEvent.objects.filter(
                attempted_login__iexact=login, success=False, created_at__gte=last_ok or since)
                .order_by("-created_at").values_list("created_at", flat=True)[:LOGIN_MAX_FAILS])
            if len(fails) >= LOGIN_MAX_FAILS:
                raise forms.ValidationError(
                    _("Слишком много неверных попыток. Вход заблокирован, попробуйте через %(m)s мин.")
                    % {"m": _minutes_left(fails[-1], now)})
            if ip:
                ip_fails = list(ClinicLoginEvent.objects.filter(ip_address=ip, success=False, created_at__gte=since)
                                .order_by("-created_at").values_list("created_at", flat=True)[:LOGIN_MAX_IP_FAILS])
                if len(ip_fails) >= LOGIN_MAX_IP_FAILS:
                    raise forms.ValidationError(
                        _("Слишком много неверных попыток с этого устройства. Попробуйте через %(m)s мин.")
                        % {"m": _minutes_left(ip_fails[-1], now)})
            self.user_cache = authenticate(self.request, username=login, password=password)
            success = self.user_cache is not None and self.user_cache.is_active
            # Пишем событие входа в любом случае (успех/провал) — супер-админ
            # должен видеть и подозрительные неудачные попытки, не только
            # успешные входы (см. /new/superadmin/ — «Последние входы»).
            try:
                ClinicLoginEvent.objects.create(
                    user=self.user_cache, clinic=getattr(self.user_cache, "clinic", None),
                    ip_address=ip,
                    user_agent=(self.request.META.get("HTTP_USER_AGENT", "") if self.request else "")[:300],
                    success=success,
                    attempted_login=login[:150],
                )
            except Exception:
                pass
            if self.user_cache is None:
                left = LOGIN_MAX_FAILS - len(fails) - 1
                if left <= 0:
                    raise forms.ValidationError(
                        _("Неверный логин или пароль. Вход заблокирован на %(m)s мин.") % {"m": LOGIN_LOCK_MINUTES})
                if left <= 3:
                    raise forms.ValidationError(
                        _("Неверный логин или пароль. Осталось попыток: %(n)s") % {"n": left})
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
                  "can_view_all_appointments", "is_active", "avatar", "color",
                  "specialty", "doctor_types"]
        widgets = {
            "branches": forms.CheckboxSelectMultiple(),
            "roles": forms.CheckboxSelectMultiple(),
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].label = "Основная роль"
        self.fields["role"].required = False
        self.fields["roles"].label = "Дополнительные роли (можно несколько)"
        self.fields["roles"].required = False
        # Суперадмин AKM SOFT — служебная роль платформы, её не назначают через
        # обычную форму сотрудника ни при каких обстоятельствах.
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
