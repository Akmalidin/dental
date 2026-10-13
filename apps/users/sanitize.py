"""Очистка текста, который может прийти снаружи (имя из WhatsApp/Telegram,
форма записи на сайте, заявка, отзыв, лид): убираем угловые скобки «<» и «>»,
а кавычки " и ` заменяем на типографские.

Зачем: такие строки потом показываются в интерфейсе сотрудников; если в имени
пациента придёт «<img src=x onerror=…>», без очистки это выполнилось бы в
браузере администратора (XSS). В именах, телефонах, адресах и заметках
угловые скобки не нужны. Сами сообщения переписки (WaMessage.body) не
меняем — они экранируются при выводе."""
import re

from django.db.models.signals import pre_save

_ANGLE = re.compile(r"[<>]")
# кавычки, которые ломают HTML-атрибут (title="…", onclick="…") — заменяем на
# типографские: смысл текста не меняется, вырваться из атрибута нельзя
_QUOTES = str.maketrans({'"': "”", "`": "ʼ"})

FIELDS = {
    "patients.Patient": ("first_name", "last_name", "middle_name", "phone", "phone2", "pin", "address",
                         "insurance_policy", "allergy", "blood_group", "notes"),
    "patients.Lead": ("name", "phone", "comment"),
    "marketing.LandingLead": ("clinic_name", "phone", "city"),
    "users.ClinicAccessRequest": ("clinic_slug", "clinic_name", "contact_name", "phone", "email", "message"),
    "users.DoctorReview": ("author", "text"),
    "appointments.Appointment": ("notes", "cancel_note"),
    "notifications.Notification": ("title", "body"),
}


def clean(value):
    return _ANGLE.sub("", value).translate(_QUOTES) if isinstance(value, str) else value


def _dirty(v):
    return isinstance(v, str) and any(ch in v for ch in '<>"`')


def _make_handler(fields):
    def handler(sender, instance, raw=False, **kw):
        for f in fields:
            v = getattr(instance, f, None)
            if _dirty(v):
                setattr(instance, f, clean(v))
    return handler


_handlers = []


def connect():
    from django.apps import apps
    for label, fields in FIELDS.items():
        try:
            model = apps.get_model(label)
        except LookupError:
            continue
        h = _make_handler(fields)
        _handlers.append(h)   # держим ссылку (weak=False ниже тоже)
        pre_save.connect(h, sender=model, weak=False, dispatch_uid=f"sanitize-{label}")


# Ключи данных страницы (real_data), в которых лежат имена/телефоны людей —
# их интерфейс местами вставляет в HTML как есть. «<» и «>» в таких значениях
# не бывает, поэтому убираем их перед отдачей страницы: даже если вредное имя
# когда-то попало в базу в обход очистки, на странице оно не выполнится.
_NAME_KEY = re.compile(r"(name|patient|doctor|author|sender|phone|actor|fio|who|client)", re.I)


def strip_names(obj, _key=""):
    if isinstance(obj, dict):
        return {k: strip_names(v, k) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [strip_names(v, _key) for v in obj]
    if _key and _NAME_KEY.search(_key) and _dirty(obj):
        return clean(obj)
    return obj


class JsonNamesMiddleware:
    """То же для JSON-ответов приложения (списки пациентов, чаты, касса…):
    в полях с именами/телефонами убираем символы, которыми можно вставить
    код в страницу. Синхронизацию не трогаем (там нужны данные как есть)."""

    SKIP = ("/sync/",)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            ctype = response.get("Content-Type", "")
            if (not ctype.startswith("application/json") or getattr(response, "streaming", False)
                    or request.path.startswith(self.SKIP)):
                return response
            body = response.content
            if not any(ch in body for ch in (b"<", b">", b'\\"', b"`", b"\\u003c", b"\\u003e")):
                return response
            import json
            data = json.loads(body)
            cleaned = strip_names(data)
            if cleaned != data:
                response.content = json.dumps(cleaned, ensure_ascii=False).encode("utf-8")
                response["Content-Length"] = str(len(response.content))
        except Exception:  # noqa: BLE001 — не ломаем ответ из-за очистки
            pass
        return response
