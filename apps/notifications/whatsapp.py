"""Отправка WhatsApp через Green-API (https://green-api.com).

Подключаешь свой номер WhatsApp в консоли Green-API (скан QR), затем система шлёт
обычные текстовые сообщения клиентам/врачам. Одобрение шаблонов не нужно.

Безопасно-выключено: если ключи не заданы (GREENAPI_ENABLED!=1 или нет id/token) —
просто логирует и возвращает False, ничего не падает. Ключи — только в env, не в git.
"""
import json
import logging
import urllib.request
import urllib.error
from django.conf import settings

log = logging.getLogger("apps")


def wa_enabled():
    return bool(getattr(settings, "GREENAPI_ENABLED", False)
                and getattr(settings, "GREENAPI_ID_INSTANCE", "")
                and getattr(settings, "GREENAPI_TOKEN", ""))


def _chat_id(phone):
    """Телефон → chatId Green-API: '996XXXXXXXXX@c.us'. 0XXXXXXXXX (KG) → 996XXXXXXXXX."""
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    if d.startswith("0") and len(d) == 10:
        d = "996" + d[1:]
    if not d:
        return None
    return d + "@c.us"


def wa_send_text(phone, text):
    """Отправить текст в WhatsApp. Возвращает True/False."""
    if not wa_enabled():
        log.info("WhatsApp(Green-API) выключен — пропуск отправки на %s", phone)
        return False
    chat = _chat_id(phone)
    if not chat:
        return False
    base = getattr(settings, "GREENAPI_API_URL", "").rstrip("/")
    if not base:
        base = "https://api.greenapi.com"
    url = "%s/waInstance%s/sendMessage/%s" % (
        base, settings.GREENAPI_ID_INSTANCE, settings.GREENAPI_TOKEN)
    payload = {"chatId": chat, "message": text}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except urllib.error.HTTPError as e:
        log.warning("WhatsApp(Green-API) отправка не удалась (%s): %s", e.code, e.read()[:400])
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("WhatsApp(Green-API) ошибка: %s", e)
        return False


# Совместимость с возможными вызовами шаблонов — у Green-API шаблоны не нужны
def wa_notify(phone, text, template_setting=None, params=None):
    return wa_send_text(phone, text)


def seed_default_templates():
    """Создать набор дефолтных шаблонов для текущей клиники (если их нет)."""
    from apps.notifications.models import MessageTemplate
    defaults = [
        ("Подтверждение записи", "confirm",
         "Здравствуйте, {имя}! Ваш приём в клинике «{клиника}» {дата} в {время} подтверждён. Ждём вас!"),
        ("Напоминание о приёме", "reminder",
         "Здравствуйте, {имя}! Напоминаем: завтра {дата} в {время} у вас приём в клинике «{клиника}». До встречи!"),
        ("О задолженности", "debt",
         "Здравствуйте, {имя}! У вас задолженность {долг} сом в клинике «{клиника}». Просьба погасить при визите. Спасибо!"),
        ("Благодарность за визит", "manual",
         "Здравствуйте, {имя}! Спасибо, что выбрали клинику «{клиника}». Будем рады видеть вас снова. Здоровья и красивой улыбки!"),
        ("Поздравление с днём рождения", "birthday",
         "Уважаемый(ая) {фио}! Клиника «{клиника}» поздравляет вас с днём рождения! 🎉 Желаем здоровья и яркой улыбки."),
    ]
    for name, kind, body in defaults:
        MessageTemplate.objects.create(name=name, kind=kind, body=body)


def render_message(body, patient=None, appt=None, amount=None):
    """Подстановка плейсхолдеров шаблона данными пациента/записи."""
    from django.utils import timezone
    repl = {}
    try:
        from apps.settings_clinic.models import ClinicSettings
        repl["{клиника}"] = ClinicSettings.get().name
    except Exception:
        repl["{клиника}"] = ""
    if patient is not None:
        repl["{имя}"] = patient.first_name or ""
        repl["{фамилия}"] = patient.last_name or ""
        repl["{фио}"] = patient.full_name
        repl["{телефон}"] = patient.phone or ""
        try:
            repl["{долг}"] = str(int(patient.debt))
        except Exception:
            repl["{долг}"] = "0"
        try:
            repl["{баланс}"] = str(int(patient.balance))
        except Exception:
            repl["{баланс}"] = "0"
    if appt is not None:
        st = timezone.localtime(appt.start_at)
        repl["{дата}"] = st.strftime("%d.%m.%Y")
        repl["{время}"] = st.strftime("%H:%M")
        repl["{врач}"] = appt.doctor.name if appt.doctor else ""
    if amount is not None:
        repl["{сумма}"] = str(int(amount))
    out = body or ""
    for k, v in repl.items():
        out = out.replace(k, str(v))
    return out
