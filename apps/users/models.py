from django.conf import settings
from django.contrib.auth.models import AbstractUser, Permission
from django.db import models
from apps.tenancy import ClinicScopedModel


# Часовые пояса для выбора в настройках клиники (по городу/стране).
# value = IANA-зона, label — город/страна для понятного выбора.
TIMEZONE_CHOICES = [
    ("Asia/Bishkek", "Бишкек (Кыргызстан, UTC+6)"),
    ("Asia/Almaty", "Алматы / Астана (Казахстан, UTC+5)"),
    ("Asia/Tashkent", "Ташкент (Узбекистан, UTC+5)"),
    ("Asia/Dushanbe", "Душанбе (Таджикистан, UTC+5)"),
    ("Asia/Ashgabat", "Ашхабад (Туркменистан, UTC+5)"),
    ("Asia/Yekaterinburg", "Екатеринбург (Россия, UTC+5)"),
    ("Asia/Omsk", "Омск (Россия, UTC+6)"),
    ("Asia/Novosibirsk", "Новосибирск (Россия, UTC+7)"),
    ("Europe/Moscow", "Москва (Россия, UTC+3)"),
    ("Europe/Kyiv", "Киев (Украина, UTC+2)"),
    ("Europe/Minsk", "Минск (Беларусь, UTC+3)"),
    ("Asia/Baku", "Баку (Азербайджан, UTC+4)"),
    ("Asia/Yerevan", "Ереван (Армения, UTC+4)"),
    ("Asia/Tbilisi", "Тбилиси (Грузия, UTC+4)"),
    ("Asia/Dubai", "Дубай (ОАЭ, UTC+4)"),
    ("Asia/Istanbul", "Стамбул (Турция, UTC+3)"),
    ("UTC", "UTC (всемирное время)"),
]


class Clinic(models.Model):
    """Клиника (арендатор). Изоляция данных по полю clinic в одной БД."""
    name = models.CharField(max_length=200, verbose_name="Название клиники")
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    tariff_plan = models.CharField(max_length=20, default="standard", verbose_name="Тариф")
    enabled_modules = models.JSONField(default=list, blank=True, verbose_name="Включённые модули")
    tariff_until = models.DateField(null=True, blank=True, verbose_name="Тариф оплачен до")
    timezone = models.CharField(
        max_length=64, default="Asia/Bishkek", choices=TIMEZONE_CHOICES,
        verbose_name="Часовой пояс (город/страна)",
        help_text="Время записей и расписания показывается в этом поясе на всех устройствах.",
    )
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
    hours = models.CharField(max_length=200, blank=True, verbose_name="Часы работы")
    latitude = models.FloatField(null=True, blank=True, verbose_name="Широта (для карты)")
    longitude = models.FloatField(null=True, blank=True, verbose_name="Долгота (для карты)")
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
    # ── Публичный профиль врача (для сайта клиники) ──
    specialty = models.CharField(max_length=150, blank=True, verbose_name="Специализация")
    bio = models.TextField(blank=True, verbose_name="Биография")
    experience_years = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Стаж (лет)")
    show_on_site = models.BooleanField(default=True, verbose_name="Показывать на сайте")
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


class ClinicSite(models.Model):
    """Публичный сайт клиники (поддомен). Доступ включает суперадмин, правит суперадмин/Директор."""
    clinic = models.OneToOneField(
        "users.Clinic", on_delete=models.CASCADE, related_name="site", verbose_name="Клиника",
    )
    enabled = models.BooleanField(default=False, verbose_name="Публичный сайт включён",
                                  help_text="Включает только суперадмин")
    published = models.BooleanField(default=True, verbose_name="Опубликован")

    headline = models.CharField(max_length=200, blank=True, verbose_name="Заголовок (hero)")
    tagline = models.CharField(max_length=300, blank=True, verbose_name="Подзаголовок")
    about = models.TextField(blank=True, verbose_name="О клинике")
    phone = models.CharField(max_length=50, blank=True, verbose_name="Телефон")
    address = models.CharField(max_length=300, blank=True, verbose_name="Адрес")
    hours = models.CharField(max_length=200, blank=True, verbose_name="Часы работы")

    logo = models.ImageField(upload_to="site/", null=True, blank=True, verbose_name="Логотип")
    cover = models.ImageField(upload_to="site/", null=True, blank=True, verbose_name="Обложка (hero)")
    theme_color = models.CharField(max_length=20, default="#4F46E5", verbose_name="Цвет темы")

    instagram = models.CharField(max_length=200, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)
    telegram = models.CharField(max_length=100, blank=True)

    show_doctors = models.BooleanField(default=True, verbose_name="Показывать врачей")
    show_services = models.BooleanField(default=True, verbose_name="Показывать услуги")
    show_booking = models.BooleanField(default=True, verbose_name="Онлайн-запись")

    seo_title = models.CharField(max_length=200, blank=True)
    seo_description = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Сайт клиники"
        verbose_name_plural = "Сайты клиник"

    def __str__(self):
        return f"Сайт {self.clinic.name}"


class GoogleCalendarAccount(models.Model):
    """Подключённый Google-аккаунт врача для синхронизации записей с Google Calendar."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="gcal_account", verbose_name="Пользователь")
    email = models.CharField(max_length=200, blank=True, verbose_name="Google email")
    refresh_token = models.TextField(verbose_name="Refresh token")
    access_token = models.TextField(blank=True, verbose_name="Access token")
    token_expiry = models.DateTimeField(null=True, blank=True, verbose_name="Срок access token")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Google Calendar аккаунт"
        verbose_name_plural = "Google Calendar аккаунты"

    def __str__(self):
        return f"{self.user.name} → {self.email or 'Google'}"


class DoctorReview(ClinicScopedModel):
    """Отзыв о враче для публичного сайта (управляется в настройках сайта)."""
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="reviews", verbose_name="Врач")
    author = models.CharField(max_length=150, verbose_name="Автор")
    rating = models.PositiveSmallIntegerField(default=5, verbose_name="Оценка (1–5)")
    text = models.TextField(verbose_name="Отзыв")
    is_published = models.BooleanField(default=True, verbose_name="Опубликован")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Отзыв о враче"
        verbose_name_plural = "Отзывы о врачах"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.author} → {self.doctor.name} ({self.rating}★)"


# Re-export salary & schedule models (defined after User/Branch to avoid circular refs)
from .models_salary import SalaryScheme, DoctorSchedule  # noqa: E402,F401
