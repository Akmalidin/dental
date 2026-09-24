from django.db import models
from django.conf import settings
from apps.tenancy import ClinicScopedModel


class MessageTemplate(ClinicScopedModel):
    """Редактируемый шаблон WhatsApp-сообщения. Плейсхолдеры:
    {имя} {фамилия} {фио} {телефон} {клиника} {долг} {баланс} {дата} {время} {врач} {сумма}"""
    KIND_CHOICES = [
        ("manual", "Произвольное"),
        ("appointment", "О записи"),
        ("reminder", "Напоминание о приёме (за день)"),
        ("reminder_hour", "Напоминание (за час)"),
        ("confirm", "Подтверждение записи"),
        ("debt", "О задолженности"),
        ("birthday", "Поздравление"),
    ]
    name = models.CharField(max_length=200, verbose_name="Название")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="manual", verbose_name="Тип")
    body = models.TextField(verbose_name="Текст сообщения")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Шаблон сообщения"
        verbose_name_plural = "Шаблоны сообщений"
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name


class WaMessage(ClinicScopedModel):
    """История переписки с пациентом — WhatsApp и Telegram (лог исходящих +
    входящие для чата). channel различает канал; для Telegram в поле phone
    хранится chat_id (в виде строки), т.к. отдельного канала со своим номером нет."""
    DIR_OUT, DIR_IN = "out", "in"
    CH_WA, CH_TG = "wa", "tg"
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="wa_messages",
        null=True, blank=True, verbose_name="Пациент",
    )
    direction = models.CharField(max_length=3, choices=[(DIR_OUT, "Исходящее"), (DIR_IN, "Входящее")],
                                 default=DIR_OUT)
    channel = models.CharField(max_length=3, choices=[(CH_WA, "WhatsApp"), (CH_TG, "Telegram")],
                               default=CH_WA, db_index=True, verbose_name="Канал")
    phone = models.CharField(max_length=30, blank=True)
    body = models.TextField(blank=True)
    # Ссылки на файлы от Green-API/Telegram недолговечны (у Telegram — около часа),
    # поэтому голосовые/медиа скачиваем и храним у себя (см. wa_webhook/tg_webhook).
    MEDIA_VOICE, MEDIA_AUDIO, MEDIA_IMAGE, MEDIA_VIDEO, MEDIA_DOCUMENT = (
        "voice", "audio", "image", "video", "document")
    media_file = models.FileField(upload_to="chat_media/%Y/%m/", blank=True, null=True, verbose_name="Медиафайл")
    media_type = models.CharField(max_length=10, blank=True, verbose_name="Тип медиа", choices=[
        (MEDIA_VOICE, "Голосовое"), (MEDIA_AUDIO, "Аудио"), (MEDIA_IMAGE, "Фото"),
        (MEDIA_VIDEO, "Видео"), (MEDIA_DOCUMENT, "Документ"),
    ])
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="+")
    ok = models.BooleanField(default=True)
    read = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "WhatsApp-сообщение"
        verbose_name_plural = "WhatsApp-сообщения"
        ordering = ["created_at"]


class WaGroup(ClinicScopedModel):
    """WhatsApp-группа клиники, в которую можно слать уведомления (записи/отмены).

    chat_id — идентификатор группы Green-API вида '120363XXXXXXXXX@g.us'.
    notify — слать ли уведомления в эту группу (управляет Директор)."""
    chat_id = models.CharField(max_length=64, verbose_name="ID группы (@g.us)")
    name = models.CharField(max_length=200, blank=True, verbose_name="Название группы")
    notify = models.BooleanField(default=True, verbose_name="Слать уведомления")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "WhatsApp-группа"
        verbose_name_plural = "WhatsApp-группы"
        ordering = ["name", "chat_id"]
        unique_together = [["clinic", "chat_id"]]

    def __str__(self):
        return self.name or self.chat_id


class TgGroup(ClinicScopedModel):
    """Telegram-группа персонала, куда бот клиники шлёт уведомления (новые
    записи/заявки/отмены, вечерняя сводка на завтра). Подключается командой
    /group, которую пишет в группе администратор клиники, привязанный к боту
    (см. apps.notifications.tg_staff)."""
    chat_id = models.BigIntegerField(verbose_name="ID чата Telegram")
    title = models.CharField(max_length=255, blank=True, verbose_name="Название группы")
    notify = models.BooleanField(default=True, verbose_name="Слать уведомления")
    last_summary_on = models.DateField(null=True, blank=True, verbose_name="Последняя сводка")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Telegram-группа"
        verbose_name_plural = "Telegram-группы"
        ordering = ["title", "chat_id"]
        unique_together = [["clinic", "chat_id"]]

    def __str__(self):
        return self.title or str(self.chat_id)


class TgChat(ClinicScopedModel):
    """Состояние личного чата пациента с ботом клиники: выбранный язык
    обслуживания (ru / uz — узбекский латиницей) и шаг диалога (ждём ФИО
    нового пациента и т.п.) — см. apps.notifications.tg_patient."""
    chat_id = models.BigIntegerField(verbose_name="ID чата Telegram")
    lang = models.CharField(max_length=2, blank=True, verbose_name="Язык")
    state = models.CharField(max_length=30, blank=True, verbose_name="Шаг диалога")
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram-чат пациента"
        verbose_name_plural = "Telegram-чаты пациентов"
        unique_together = [["clinic", "chat_id"]]

    def __str__(self):
        return "%s (%s)" % (self.chat_id, self.lang or "—")


class Broadcast(models.Model):
    """Одна рассылка объявления из супер-админ-панели (/new/superadmin/,
    вкладка «Push-рассылка», apps.users.newui_views.
    newui_superadmin_broadcast_send) — история отправок + данные для
    «Повторить». Сами уведомления получателям — обычные Notification(type=
    "broadcast"), у каждой FK сюда (Notification.broadcast), поэтому список
    получателей конкретной рассылки — просто notifications.all()."""
    AUDIENCE_CHOICES = [
        ("all", "Всем сотрудникам"),
        ("directors", "Директорам"),
        ("doctors", "Врачам"),
    ]

    text = models.CharField(max_length=300, verbose_name="Текст")
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default="all", verbose_name="Кому")
    # Пусто = по всем клиникам платформы (как и в newui_superadmin_broadcast_send) —
    # само поле хранит именно ВЫБОР супер-админа при отправке (для «Повторить»
    # той же рассылки), а не производный список клиник получателей (тот
    # виден через notifications__clinic).
    clinics = models.ManyToManyField("users.Clinic", blank=True, related_name="+", verbose_name="Клиники")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Отправитель",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Рассылка"
        verbose_name_plural = "Рассылки"
        ordering = ["-created_at"]

    def __str__(self):
        return self.text[:60]


class Notification(models.Model):
    TYPE_CHOICES = [
        ("appointment", "Запись"),
        ("task", "Задача"),
        ("payment", "Платёж"),
        ("wa", "WhatsApp"),
        ("system", "Система"),
        ("reminder", "Напоминание"),
        ("broadcast", "Объявление супер-админа"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Пользователь",
    )
    clinic = models.ForeignKey(
        "users.Clinic", on_delete=models.CASCADE, null=True, blank=True,
        related_name="+", verbose_name="Клиника", db_index=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", verbose_name="Отправитель",
    )
    # Заполнено только для type="broadcast" — какая именно рассылка (история
    # + список получателей в модалке супер-админ-панели).
    broadcast = models.ForeignKey(
        Broadcast, on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications", verbose_name="Рассылка",
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Тип")
    title = models.CharField(max_length=300, verbose_name="Заголовок")
    body = models.TextField(blank=True, verbose_name="Сообщение")
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.title}"

    @classmethod
    def send(cls, user, title, body="", type="system", link="", actor=None, broadcast=None, clinic=None):
        # clinic=None (по умолчанию) — старое поведение: клиника текущего
        # запроса, а если её нет — клиника получателя. ЯВНО передать clinic
        # нужно там, где отправитель и получатель могут быть в РАЗНЫХ
        # клиниках (супер-админ-рассылка, newui_superadmin_broadcast_send) —
        # иначе всем получателям проставлялась бы клиника ТЕКУЩЕГО запроса
        # (клиника поддомена, на котором сидит супер-админ в момент отправки),
        # а не собственная клиника каждого получателя. Из-за этого
        # get_current_clinic()-фильтр в apps.notifications.views.
        # _user_notifications (использует его и mark_read, и notification_poll)
        # переставал видеть уведомление получателя — крестик на баннере слал
        # /notifications/<id>/read/ с кодом 200, но update() не находил ни
        # одной строки (clinic не совпадала) и баннер появлялся снова.
        if clinic is None:
            from apps.tenancy import get_current_clinic
            clinic = get_current_clinic() or getattr(user, "clinic", None)
        n = cls.objects.create(user=user, clinic=clinic, actor=actor,
                               title=title, body=body, type=type, link=link, broadcast=broadcast)
        # дополнительно — web push (телефон/фон, даже если вкладка закрыта)
        try:
            from .push import send_web_push
            send_web_push(user, title, body, link or "/")
        except Exception:
            pass
        return n


class PushSubscription(models.Model):
    """Подписка устройства на web push (Service Worker)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Push-подписка"
        verbose_name_plural = "Push-подписки"

    def __str__(self):
        return f"{self.user} · {self.endpoint[:40]}"
