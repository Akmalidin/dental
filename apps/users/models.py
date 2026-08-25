from django.conf import settings
from django.contrib.auth.models import AbstractUser, Permission as DjangoPermission
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
    # Мастер-переключатели уровня суперадмина (по тарифу/лицензии) — независимо
    # от собственных настроек WhatsApp/Telegram самой клиники (ClinicSettings):
    # чтобы реально отправлять сообщения, нужно, чтобы ОБА переключателя были включены.
    wa_master_enabled = models.BooleanField(default=True, verbose_name="WhatsApp разрешён клинике")
    telegram_master_enabled = models.BooleanField(default=True, verbose_name="Telegram разрешён клинике")
    # Реестр фич, которые выдаёт ТОЛЬКО супер-админ (central-панель) — жёсткое
    # серверное разрешение на конкретные действия, сама клиника изменить его
    # не может (в отличие от enabled_modules — это косметика навигации по
    # тарифу, которую отчасти настраивает сама клиника). По умолчанию пусто:
    # ни одна клиника не может делать это действие, пока супер-админ явно не
    # выдал доступ. Добавлять новые ключи сюда по мере надобности — остальной
    # код (has_access) их не знает заранее.
    GRANTABLE_ACCESS = [
        ("branches", "Создание филиалов"),
    ]
    granted_access = models.JSONField(default=list, blank=True, verbose_name="Доступы (супер-админ)")
    # В отличие от granted_access (выдать то, чего нет по умолчанию) — это
    # ОБРАТНОЕ: список функций, которые обычно РАБОТАЮТ, но супер-админ может
    # точечно запретить конкретной клинике. Пусто по умолчанию — ничего не
    # блокируется, поведение всех существующих клиник не меняется. Ключи,
    # кроме voice_bot, специально совпадают с SECTION_KEYS/
    # SectionAccessMiddleware.PREFIXES (apps/tenancy.py) — там же и
    # применяется блокировка, без отдельной таблицы соответствий.
    BLOCKABLE_FEATURES = [
        ("voice_bot", "Голосовой/ИИ-бот"),
        ("warehouse", "Склад"),
        ("finance", "Финансы/Касса"),
        ("technicians", "Лаборатория"),
        ("medicines", "Лекарства"),
        ("reports", "Аналитика"),
    ]
    blocked_features = models.JSONField(default=list, blank=True, verbose_name="Заблокированные функции")
    # Причина блокировки клиники целиком (is_active=False) — задаётся
    # супер-админом в момент блокировки, показывается клинике на странице
    # «Запросить доступ» вместо простого «недоступна».
    blocked_reason = models.TextField(blank=True, verbose_name="Причина блокировки")
    created_at = models.DateTimeField(auto_now_add=True)

    def has_access(self, key):
        return key in (self.granted_access or [])

    def is_blocked(self, key):
        return key in (self.blocked_features or [])

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


class PermissionCategory(models.TextChoices):
    FINANCE = "finance", "Финансы"
    PATIENTS = "patients", "Пациенты"
    STAFF = "staff", "Персонал"
    REPORTS = "reports", "Отчёты"


class Permission(models.Model):
    """Каталог доступных прав — заполняется data migration (Task 2), не через UI."""
    code = models.CharField(max_length=64, unique=True, verbose_name="Код")
    category = models.CharField(max_length=32, choices=PermissionCategory.choices, verbose_name="Категория")
    label = models.CharField(max_length=255, verbose_name="Название")
    help_text = models.CharField(max_length=255, blank=True, verbose_name="Подсказка")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Право доступа"
        verbose_name_plural = "Права доступа"
        ordering = ["category", "sort_order", "label"]

    def __str__(self):
        return self.label


class Role(models.Model):
    """Custom role with explicit permissions."""

    SUPERADMIN = "superadmin"
    ADMIN_MAIN = "admin_main"
    ADMIN = "admin"
    DOCTOR = "doctor"
    NURSE = "nurse"
    TECHNICIAN = "technician"

    ROLE_CHOICES = [
        (SUPERADMIN, "Суперадмин AKM SOFT"),
        (ADMIN_MAIN, "Директор"),
        (ADMIN, "Администратор"),
        (DOCTOR, "Доктор"),
        (NURSE, "Медсестра"),
        (TECHNICIAN, "Техник"),
    ]

    name = models.CharField(max_length=50, verbose_name="Роль")
    # None = системная роль (видна и доступна всем клиникам, создаётся только
    # сидинг-миграцией). Заполнено = кастомная роль, созданная и видимая
    # ТОЛЬКО этой клиникой — без этого поля роль одной клиники была бы видна
    # и доступна для назначения во всех остальных клиниках SaaS.
    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="custom_roles", verbose_name="Клиника",
    )
    is_system = models.BooleanField(default=False, verbose_name="Системная роль")
    granular_permissions = models.ManyToManyField(
        Permission, blank=True, related_name="roles", verbose_name="Права (новая система)",
    )
    # Старое поле — встроенный Django Permission, мёртвый код (нигде не проверяется
    # за пределами этого файла), оставляем нетронутым по поведению, только меняем
    # имя импортированного класса на DjangoPermission (см. правку импорта выше).
    permissions = models.ManyToManyField(
        DjangoPermission,
        blank=True,
        verbose_name="Права доступа",
    )

    class Meta:
        verbose_name = "Роль"
        verbose_name_plural = "Роли"
        constraints = [
            models.UniqueConstraint(fields=["clinic", "name"], name="unique_role_name_per_clinic"),
        ]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        """Человекочитаемое имя роли: для системных ролей — русская подпись
        из ROLE_CHOICES (name хранит код вида "admin_main"), для кастомных
        ролей клиники — сам name (директор ввёл его сам, переводить нечего).
        Замена removed choices=ROLE_CHOICES на поле name (Task 1 RBAC) —
        раньше это делал автосгенерированный get_name_display()."""
        if self.is_system:
            return dict(self.ROLE_CHOICES).get(self.name, self.name)
        return self.name

    def has_perm(self, code: str) -> bool:
        return self.granular_permissions.filter(code=code).exists()


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
    # Персональная настройка сайдбара нового интерфейса (скрытые пункты/порядок/
    # главный экран — см. "Настроить меню" в /new/*): {hidden:[...], order:{...}, home:"..."}.
    # Пусто — используется меню клиники по умолчанию (ClinicSettings.menu_prefs), если оно
    # задано директором, иначе — стандартный порядок сайдбара как есть.
    menu_prefs = models.JSONField(default=dict, blank=True, verbose_name="Настройка меню (личная)")
    color = models.CharField(
        max_length=7, blank=True, verbose_name="Цвет",
        help_text="Необязательно. Используется для аватара и различения врачей в расписании. "
                  "Пусто — обычный фиолетовый градиент.",
    )
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
    # ── Тип врача (для фильтра при записи на приём — в отличие от specialty
    #    ниже, это не свободный текст, а фиксированный список, по нему можно
    #    фильтровать/группировать). Один врач может иметь несколько типов.
    DOCTOR_TYPE_CHOICES = [
        ("terapevt", "Терапевт"),
        ("ortoped", "Ортопед"),
        ("ortodont", "Ортодонт"),
        ("hirurg_implantolog", "Хирург-имплантолог"),
    ]
    doctor_types = models.JSONField(
        default=list, blank=True, verbose_name="Тип врача",
        help_text="Для фильтра по специализации при записи на приём",
    )
    # ── Публичный профиль врача (для сайта клиники) ──
    specialty = models.CharField(max_length=150, blank=True, verbose_name="Специализация")
    bio = models.TextField(blank=True, verbose_name="Биография")
    experience_years = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Стаж (лет)")
    show_on_site = models.BooleanField(default=True, verbose_name="Показывать на сайте")
    is_active = models.BooleanField(default=True)
    # Какой интерфейс открывать после входа — запоминаем последний, которым
    # пользователь реально пользовался (переключается сам: заход на любую
    # страницу /new/* включает, ссылка «Старый интерфейс» в сайдбаре нового
    # выключает — см. apps.users.newui_views._render и newui_use_old_interface),
    # чтобы не приходилось каждый раз при входе заново нажимать «Новый интерфейс».
    use_new_interface = models.BooleanField(default=False, verbose_name="Использует новый интерфейс")

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

    def has_granular_perm(self, perm_code):
        """В отличие от role.has_perm() (проверяет только ОДНУ роль) —
        учитывает и основную роль, и дополнительные (self.roles, M2M), как
        уже делает has_role()/all_role_names. require_permission() должен
        использовать именно этот метод, а не request.user.role.has_perm()
        напрямую — иначе доп. роль права не даёт (была асимметрия с
        role_required/has_role(), которая обе роли учитывает всегда)."""
        if self.role_id and self.role.has_perm(perm_code):
            return True
        return self.roles.filter(granular_permissions__code=perm_code).exists()

    @property
    def is_superadmin(self):
        return self.is_superuser or Role.SUPERADMIN in self.all_role_names

    @property
    def is_doctor(self):
        return Role.DOCTOR in self.all_role_names

    @property
    def doctor_types_display(self):
        labels = dict(self.DOCTOR_TYPE_CHOICES)
        return ", ".join(labels.get(t, t) for t in (self.doctor_types or []))

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


def clinic_staff(clinic=None):
    """Весь активный персонал клиники (врачи, администраторы и т.д.), кроме суперпользователя."""
    qs = (User.objects.filter(is_active=True)
          .exclude(is_superuser=True).select_related("role").distinct())
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


class ClinicAccessRequest(models.Model):
    """Заявка «дайте доступ» — публичная форма (apps.users.views.
    clinic_access_request), показывается посетителю вместо тихого редиректа
    на общий вход, когда поддомен не соответствует ни одной клинике или
    клиника заблокирована (Clinic.is_active=False). Супер-админ видит список
    новых заявок в /new/superadmin/."""
    STATUS_NEW, STATUS_CONTACTED, STATUS_RESOLVED = "new", "contacted", "resolved"
    STATUS_CHOICES = [(STATUS_NEW, "Новая"), (STATUS_CONTACTED, "Связались"), (STATUS_RESOLVED, "Решено")]
    clinic_slug = models.CharField(max_length=120, blank=True, verbose_name="Поддомен (если вводили)")
    clinic_name = models.CharField(max_length=200, verbose_name="Название клиники")
    contact_name = models.CharField(max_length=200, verbose_name="Контактное лицо")
    phone = models.CharField(max_length=30, verbose_name="Телефон")
    email = models.EmailField(blank=True)
    message = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Заявка на доступ"
        verbose_name_plural = "Заявки на доступ"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.clinic_name} — {self.get_status_display()}"


class ClinicLoginEvent(models.Model):
    """Лог попыток входа (успешных и нет) — IP/устройство/клиника, для
    супер-админ-панели («Последние входы» по клинике) и как основа для
    блокировки по IP (см. BlockedIP, apps.users.forms.LoginForm.clean)."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    clinic = models.ForeignKey(Clinic, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    success = models.BooleanField(default=True)
    # Сырой введённый логин — пишем ВСЕГДА (успех/отказ). При отказе `user`
    # обычно null (логин не найден/неверный пароль) — без этого поля Аудит-
    # центр не мог показать, ПОД КАКИМ ЛОГИНОМ пытались войти.
    attempted_login = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Вход в систему"
        verbose_name_plural = "Входы в систему"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ip_address} — {'ok' if self.success else 'fail'} — {self.created_at:%d.%m.%Y %H:%M}"


class BlockedIP(models.Model):
    """Глобальная блокировка входа по IP (не привязана к одной клинике —
    заблокированный IP не сможет войти ни в одну клинику). Проверяется в
    apps.users.forms.LoginForm.clean() при каждой попытке входа И в
    apps.tenancy.BlockedIPMiddleware на каждом запросе уже вошедших."""
    ip_address = models.GenericIPAddressField(unique=True)
    note = models.CharField(max_length=300, blank=True)
    blocked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Пусто = блокировка бессрочная (как у всех записей до этого поля).
    # Иначе — блок автоматически перестаёт действовать после этой даты, но
    # запись из таблицы не удаляется (история блокировок сохраняется для
    # Аудит-центра) — проверка "активна ли блокировка сейчас" — в двух
    # местах: LoginForm.clean() и BlockedIPMiddleware (оба фильтруют по
    # expires_at__isnull=True или expires_at__gt=now).
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Блокировка до")

    class Meta:
        verbose_name = "Заблокированный IP"
        verbose_name_plural = "Заблокированные IP"
        ordering = ["-created_at"]

    def __str__(self):
        return self.ip_address

    @property
    def is_active_block(self):
        from django.utils import timezone
        return self.expires_at is None or self.expires_at > timezone.now()


class AuditEvent(models.Model):
    """Платформенное событие для Аудит-центра (/new/superadmin/) — единая
    лента изменений/удалений через всю систему, независимо от клиники.

    Не дублирует то, что уже есть: логины/отказы входа берутся напрямую из
    ClinicLoginEvent, правки карточек Пациент/Приём — из их же
    simple_history (см. apps.users.audit.build_history_rows, тот же приём,
    что уже используется в audit_center) — эта модель нужна только для
    действий, которые больше нигде не логируются: блокировки клиник/IP,
    выдача/запрет доступов, удаления объектов (через
    ClinicSoftDeleteModel.soft_delete/restore, см. apps.tenancy),
    надзорные просмотры (супер-админ входит в клинику/за сотрудника —
    category="view") и т.п. Пишется через apps.users.audit.log_audit_event()
    — никогда не должна ронять вызывающую вьюху при ошибке записи."""
    CATEGORY_CHOICES = [
        ("change", "Изменение"),
        ("delete", "Удаление"),
        ("view", "Просмотр"),
    ]
    RESULT_CHOICES = [
        ("success", "Успех"),
        ("fail", "Отказ"),
    ]
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    action = models.CharField(max_length=40, verbose_name="Действие")  # "ip_block", "clinic_block", "soft_delete", ...
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # Снимок имени/роли актёра НА МОМЕНТ действия — роль пользователя может
    # измениться позже, а запись аудита должна показывать, кем он был тогда.
    actor_name = models.CharField(max_length=200, blank=True)
    actor_role = models.CharField(max_length=100, blank=True)
    clinic = models.ForeignKey(Clinic, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    object_model = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=60, blank=True)
    object_repr = models.CharField(max_length=300, blank=True, verbose_name="Объект")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, default="success")
    # [{"field": "...", "old": "...", "new": "..."}, ...] — тот же вид diff'а,
    # что уже строит audit_center (apps.users.views._AUDIT_DIFF_SKIP_FIELDS).
    diff = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Событие аудита"
        verbose_name_plural = "События аудита"

    def __str__(self):
        return f"{self.action} — {self.object_repr} — {self.created_at:%d.%m.%Y %H:%M}"


class AuditRevert(models.Model):
    """Лог явных откатов в Аудит-центре.

    Нужен, чтобы отличать «текущую линию» истории объекта от «устаревшей
    ветки» — записей, которые были сделаны ПОСЛЕ версии, к которой откатили,
    но ДО момента самого отката (they got superseded and no longer describe
    what happened to the live record). Персонал может посмотреть эту ветку
    отдельно и удалить её, если она больше не нужна."""

    model_label = models.CharField(max_length=20, verbose_name="Модель")
    object_id = models.PositiveIntegerField(verbose_name="ID записи")
    reverted_to_hid = models.PositiveIntegerField(verbose_name="ID версии, к которой откатили")
    reverted_to_date = models.DateTimeField(verbose_name="Дата версии, к которой откатили")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    performed_at = models.DateTimeField(auto_now_add=True, verbose_name="Когда откатили")

    class Meta:
        verbose_name = "Откат в аудите"
        verbose_name_plural = "Откаты в аудите"
        ordering = ["-performed_at"]

    def __str__(self):
        return f"{self.model_label} #{self.object_id} → версия от {self.reverted_to_date:%d.%m.%Y %H:%M}"


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
