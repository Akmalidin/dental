from django.contrib.auth.models import AbstractUser, Permission
from django.db import models


class Branch(models.Model):
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
        (ADMIN_MAIN, "Главный администратор"),
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


class User(AbstractUser):
    """Custom user model replacing username with login field."""

    username = None  # removed — use login instead
    login = models.CharField(max_length=150, unique=True, verbose_name="Логин")
    name = models.CharField(max_length=200, verbose_name="Имя")
    phone = models.CharField(max_length=30, blank=True, verbose_name="Телефон")
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
    telegram_id = models.BigIntegerField(null=True, blank=True, verbose_name="Telegram ID")
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

    def has_role(self, *role_names):
        return self.role_name in role_names

    @property
    def is_superadmin(self):
        return self.is_superuser or self.role_name == Role.SUPERADMIN

    @property
    def is_doctor(self):
        return self.role_name == Role.DOCTOR

    @property
    def is_admin(self):
        return self.role_name in (Role.ADMIN, Role.ADMIN_MAIN)


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
