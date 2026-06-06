"""
Мульти-клиники (логическая изоляция в одной БД).

Текущая клиника хранится в thread-local и устанавливается middleware из
request.user.clinic (или из выбора суперадмина). Менеджеры моделей с миксинами
ниже автоматически фильтруют по текущей клинике, а save() проставляет клинику
новым записям.

Базовые классы:
  ClinicScopedModel       — clinic FK + авто-фильтр (каталог, финансы, справочники)
  ClinicSoftDeleteModel   — то же + мягкое удаление (пациенты, приёмы, записи)
"""
import threading
from django.db import models
from django.utils import timezone

_state = threading.local()


def set_current_clinic(clinic):
    _state.clinic = clinic


def get_current_clinic():
    return getattr(_state, "clinic", None)


def clear_current_clinic():
    _state.clinic = None


class _Unscoped:
    """Контекст-менеджер: временно отключить фильтрацию по клинике (суперадмин/сидинг)."""
    def __enter__(self):
        self.prev = getattr(_state, "unscoped", False)
        _state.unscoped = True
        return self

    def __exit__(self, *a):
        _state.unscoped = self.prev


def unscoped():
    return _Unscoped()


def _is_unscoped():
    return getattr(_state, "unscoped", False)


class CurrentClinicMiddleware:
    """Ставит текущую клинику из request.user (или из выбора суперадмина)."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_clinic(None)
        try:
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                if getattr(user, "is_superadmin", False):
                    # суперадмин: либо выбранная клиника, либо все (None = без фильтра)
                    cid = request.session.get("active_clinic")
                    if cid:
                        from apps.users.models import Clinic
                        set_current_clinic(Clinic.objects.filter(pk=cid).first())
                else:
                    set_current_clinic(getattr(user, "clinic", None))
        except Exception:
            set_current_clinic(None)
        try:
            return self.get_response(request)
        finally:
            clear_current_clinic()


class TariffGuardMiddleware:
    """Блокирует доступ, если тариф клиники истёк (кроме суперадмина)."""
    ALLOWED_PREFIXES = ("/login", "/logout", "/static", "/i18n", "/sw.js", "/manifest.json")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not getattr(user, "is_superadmin", False):
            clinic = getattr(user, "clinic", None)
            if clinic is not None and clinic.is_expired:
                path = request.path
                if not any(path.startswith(p) for p in self.ALLOWED_PREFIXES):
                    from django.shortcuts import render
                    return render(request, "tariff_expired.html", {"clinic": clinic}, status=402)
        return self.get_response(request)


class PublicSiteMiddleware:
    """Поддомен клиники → публичный сайт.

    <slug>.PUBLIC_BASE_DOMAIN (кроме APP_HOST) → ищем клинику по slug, если сайт включён,
    переключаем urlconf на публичный и ставим текущую клинику. Иначе — 404.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings as dj
        host = request.get_host().split(":")[0].lower()
        app_host = (getattr(dj, "APP_HOST", "") or "").lower()
        base = (getattr(dj, "PUBLIC_BASE_DOMAIN", "") or "").lower()
        if base and host != app_host and host.endswith("." + base):
            slug = host[: -(len(base) + 1)]
            if slug and slug not in ("www", "app"):
                from apps.users.models import Clinic, ClinicSite
                clinic = Clinic.objects.filter(slug=slug).first()
                site = ClinicSite.objects.filter(clinic=clinic).first() if clinic else None
                if clinic and site and site.enabled and site.published:
                    request.public_clinic = clinic
                    request.public_site = site
                    request.urlconf = "config.urls_site"
                    set_current_clinic(clinic)
                else:
                    from django.http import HttpResponse
                    return HttpResponse(
                        "<!doctype html><meta charset=utf-8><title>Сайт недоступен</title>"
                        "<div style='font-family:sans-serif;text-align:center;padding:80px'>"
                        "<h1>Сайт недоступен</h1><p>Публичный сайт этой клиники не активирован.</p></div>",
                        status=404, content_type="text/html; charset=utf-8",
                    )
        return self.get_response(request)


class SectionAccessMiddleware:
    """Персональные доступы: блокирует заход в раздел, если он не разрешён пользователю.

    Дополняет роли/тариф. allowed_sections=None у пользователя — без ограничений.
    Регистрировать ПОСЛЕ MessageMiddleware (использует messages).
    """
    # (URL-префикс, ключ раздела). Длинные/частные префиксы — первыми.
    # key=None — служебные/всегда-доступные пути (не блокируются здесь).
    PREFIXES = [
        ("/users/recycle-bin", "recycle"),
        ("/users/superadmin", None),
        ("/users/clinic", None),       # обзор клиники — проверяется во вьюхе
        ("/users/set-clinic", None),
        ("/users/set-branch", None),
        ("/users/my-earnings", None),  # своя зарплата — доступна врачу
        ("/users", "staff"),
        ("/settings", "settings"),
        ("/calendar", "calendar"),
        ("/appointments", "appointments"),
        ("/patients", "patients"),
        ("/treatments", "treatments"),
        ("/services", "services"),
        ("/finance", "finance"),
        ("/warehouse", "warehouse"),
        ("/medicines", "medicines"),
        ("/technicians", "technicians"),
        ("/tasks", "tasks"),
        ("/reports", "reports"),
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated
                and not getattr(user, "is_superadmin", False)):
            allowed = getattr(user, "allowed_sections", None)
            if allowed is not None:  # None = персональных ограничений нет
                path = request.path
                for prefix, key in self.PREFIXES:
                    if path.startswith(prefix):
                        if key is not None and key not in allowed:
                            from django.shortcuts import redirect
                            from django.contrib import messages
                            messages.error(request, "У вас нет доступа к этому разделу")
                            return redirect("/")
                        break
        return self.get_response(request)


def _apply_clinic(qs):
    if _is_unscoped():
        return qs
    clinic = get_current_clinic()
    if clinic is not None:
        return qs.filter(clinic=clinic)
    return qs


# ─── Clinic-scoped (без мягкого удаления) ────────────────────────────────────

class ClinicManager(models.Manager):
    def get_queryset(self):
        return _apply_clinic(super().get_queryset())


class _ClinicSaveMixin:
    def save(self, *args, **kwargs):
        if getattr(self, "clinic_id", None) is None:
            cur = get_current_clinic()
            if cur is not None:
                self.clinic = cur
        super().save(*args, **kwargs)


class ClinicScopedModel(_ClinicSaveMixin, models.Model):
    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="+", verbose_name="Клиника", db_index=True,
    )
    objects = ClinicManager()
    all_clinics = models.Manager()

    class Meta:
        abstract = True
        base_manager_name = "all_clinics"


# ─── Clinic-scoped + мягкое удаление ─────────────────────────────────────────

class ClinicSoftDeleteManager(models.Manager):
    def get_queryset(self):
        return _apply_clinic(super().get_queryset().filter(is_deleted=False))


class ClinicSoftDeleteModel(_ClinicSaveMixin, models.Model):
    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="+", verbose_name="Клиника", db_index=True,
    )
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="Удалён")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Удалён в")
    deleted_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Кто удалил",
    )

    objects = ClinicSoftDeleteManager()   # без удалённых, по текущей клинике
    all_objects = models.Manager()        # все записи (для корзины/служебного)

    class Meta:
        abstract = True
        base_manager_name = "all_objects"

    def _has_updated_at(self):
        return any(f.name == "updated_at" for f in self._meta.fields)

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user is not None and getattr(user, "pk", None):
            self.deleted_by = user
        fields = ["is_deleted", "deleted_at", "deleted_by"]
        if self._has_updated_at():
            self.updated_at = timezone.now()   # важно для синхронизации (кто новее)
            fields.append("updated_at")
        self.save(update_fields=fields)

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        fields = ["is_deleted", "deleted_at", "deleted_by"]
        if self._has_updated_at():
            self.updated_at = timezone.now()   # важно для синхронизации (кто новее)
            fields.append("updated_at")
        self.save(update_fields=fields)
