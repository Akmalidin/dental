from django.contrib.auth.models import AbstractUser, Permission
from django.db import models
from apps.tenancy import ClinicScopedModel


class Clinic(models.Model):
    """Клиника (арендатор). Изоляция данных по полю clinic в одной БД."""
    name = models.CharField(max_length=200, verbose_name="Название клиники")
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    tariff_plan = models.CharField(max_length=20, default="standard", verbose_name="Тариф")
    enabled_modules = models.JSONField(default=list, blank=True, verbose_name="Включённые модули")
    tariff_until = models.DateField(null=True, blank=True, verbose_name="Тариф оплачен до")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_expired(self):
        from django.utils import timezone
        return bool(self.tariff_until and self.tariff_until < timezone.localdate())

    class Meta:
        verbose_name = "Клиника"
        verbose_name_plural = "Клиники"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Branch(ClinicScopedModel):
    """Physical branch / location of a clinic."""

    name = models.CharField(max_length=200, verbose_name="Название")
    address = models.CharField(max_length=500, verbose_name="Адрес")
    phone = models.CharField(max_length=30, verbose_name="Телефон")
    is_main = models.BooleanField(default=False, verbose_name="Главный филиал")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"
        ordering = ["-is_main", "name"]

    def __str__(self):
        return self.name


class Role(models.Model):
    """Custom role with explicit permissions."""

    SUPERADMIN = "superadmin"
    ADMIN_MAIN = "admin_main"
    ADMIN = "admin"
    DOCTOR = "doctor"
    NURSE = "nurse"

    ROLE_CHOICES = [
        (SUPERADMIN, "Суперадмин AKM SOFT"),
        (ADMIN_MAIN, "Директор"),
        (ADMIN, "Администратор"),
        (DOCTOR, "Доктор"),
        (NURSE, "Медсестра"),
    ]

    name = models.CharField(max_length=50, choices=ROLE_CHOICES, unique=True, verbose_name="Роль")
    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        verbose_name="Права доступа",
    )

    class Meta:
        verbose_name = "Роль"
        verbose_name_plural = "Роли"

    def __str__(self):
        return self.get_name_display()


# ─── Разделы системы (для персональных доступов) ─────────────────────────────
# (ключ, подпись, URL-префикс). dashboard всегда доступен и не блокируется.
SECTIONS = [
    ("dashboard",    "Дашборд",    "/"),
    ("calendar",     "Расписание", "/calendar/"),
    ("appointments", "Записи",     "/appointments/"),
    ("patients",     "Пациенты",   "/patients/"),
    ("treatments",   "Лечения",    "/treatments/"),
    ("services",     "Услуги",     "/services/"),
    ("finance",      "Финансы",    "/finance/"),
    ("warehouse",    "Склад",      "/warehouse/"),
    ("medicines",    "Лекарства",  "/medicines/"),
    ("technicians",  "Техники",    "/technicians/"),
    ("tasks",        "Задачи",     "/tasks/"),
    ("reports",      "Аналитика",  "/reports/"),
    ("staff",        "Сотрудники", "/users/"),
    ("settings",     "Настройки",  "/settings/"),
    ("recycle",      "Корзина",    "/users/recycle-bin/"),
]
SECTION_KEYS = [s[0] for s in SECTIONS]
SECTION_LABELS = {s[0]: s[1] for s in SECTIONS}


class User(AbstractUser):
    """Custom user model replacing username with login field."""

    username = None  # removed — use login instead
    login = models.CharField(max_length=150, unique=True, verbose_name="Логин")
    name = models.CharField(max_length=200, verbose_name="Имя")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Телефон")
    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="users", verbose_name="Клиника",
    )
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True, verbose_name="Аватар")
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Роль",
    )
    branches = models.ManyToManyField(
        Branch,
        blank=True,
        related_name="users",
        verbose_name="Филиалы",
    )
    roles = models.ManyToManyField(
        "users.Role", blank=True, related_name="users_extra",
        verbose_name="Доп. роли",
    )
    telegram_id = models.BigIntegerField(null=True, blank=True, verbose_name="Telegram ID")
    can_view_all_appointments = models.BooleanField(
        default=True, verbose_name="Видит записи всех врачей",
        help_text="Если выключено — врач видит только свои записи",
    )
    allowed_sections = models.JSONField(
        null=True, blank=True, default=None, verbose_name="Разрешённые разделы",
        help_text="Пусто (null) = все разделы по роли. Список ключей = только эти разделы.",
    )
    is_active = models.BooleanField(default=True)

    USERNAME_FIELD = "login"
    REQUIRED_FIELDS = ["email", "name"]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.name or self.login

    @property
    def role_name(self):
        return self.role.name if self.role else None

    @property
    def all_role_names(self):
        """Все роли пользователя: основная + дополнительные (M2M)."""
        names = set()
        if self.role_id:
            names.add(self.role_name)
        try:
            names.update(self.roles.values_list("name", flat=True))
        except Exception:
            pass
        return names

    def has_role(self, *role_names):
        return bool(self.all_role_names & set(role_names))

    @property
    def is_superadmin(self):
        return self.is_superuser or Role.SUPERADMIN in self.all_role_names

    @property
    def is_doctor(self):
        return Role.DOCTOR in self.all_role_names

    @property
    def is_admin(self):
        return bool(self.all_role_names & {Role.ADMIN, Role.ADMIN_MAIN})

    @property
    def is_admin_main(self):
        return Role.ADMIN_MAIN in self.all_role_names

    def can_access(self, section):
        """Персональный доступ к разделу. None в allowed_sections = всё (по роли)."""
        if self.is_superadmin:
            return True
        if section == "dashboard":
            return True  # дашборд всегда доступен (иначе некуда редиректить)
        allowed = self.allowed_sections
        if allowed is None:
            return True
        return section in allowed

    @property
    def nav_sections(self):
        """Множество ключей разделов, доступных пользователю лично (для сайдбара)."""
        if self.is_superadmin or self.allowed_sections is None:
            return set(SECTION_KEYS)
        return set(self.allowed_sections) | {"dashboard"}


def clinic_doctors(clinic=None):
    """Врачи клиники — пользователи с ролью «доктор» (основной ИЛИ доп.), активные."""
    from django.db.models import Q
    qs = (User.objects.filter(is_active=True)
          .filter(Q(role__name=Role.DOCTOR) | Q(roles__name=Role.DOCTOR))
          .exclude(is_superuser=True).distinct())
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return qs


class UserActivity(models.Model):
    """Audit log for user actions."""

    ACTION_CHOICES = [
        ("login", "Вход"),
        ("logout", "Выход"),
        ("create", "Создание"),
        ("update", "Изменение"),
        ("delete", "Удаление"),
        ("view", "Просмотр"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="activities")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Действие пользователя"
        verbose_name_plural = "Действия пользователей"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.action} — {self.created_at:%d.%m.%Y %H:%M}"


# Re-export salary & schedule models (defined after User/Branch to avoid circular refs)
from .models_salary import SalaryScheme, DoctorSchedule  # noqa: E402,F401
