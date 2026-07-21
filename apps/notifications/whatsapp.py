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


def _wa_config():
    """(enabled, id_instance, token, api_url) для ТЕКУЩЕЙ клиники.

    Приоритет — настройки клиники (ClinicSettings: свой инстанс/токен/номер).
    Если клиника свои ключи не задала — глобальные из .env (для совместимости),
    но переключатель клиники (wa_enabled) и мастер-переключатель суперадмина
    (Clinic.wa_master_enabled) всё равно учитываются.
    """
    g_id = getattr(settings, "GREENAPI_ID_INSTANCE", "") or ""
    g_token = getattr(settings, "GREENAPI_TOKEN", "") or ""
    g_url = getattr(settings, "GREENAPI_API_URL", "") or ""
    g_enabled = bool(getattr(settings, "GREENAPI_ENABLED", False))
    master_enabled = True
    try:
        from apps.tenancy import get_current_clinic
        clinic = get_current_clinic()
        if clinic is not None:
            master_enabled = bool(getattr(clinic, "wa_master_enabled", True))
    except Exception:
        pass
    cs = None
    try:
        from apps.settings_clinic.models import ClinicSettings
        cs = ClinicSettings.get()
    except Exception:
        cs = None
    if cs is not None:
        c_enabled = bool(getattr(cs, "wa_enabled", True)) and master_enabled
        cid = (getattr(cs, "wa_id_instance", "") or "").strip()
        ctok = (getattr(cs, "wa_token", "") or "").strip()
        curl = (getattr(cs, "wa_api_url", "") or "").strip()
        if cid and ctok:
            return (c_enabled, cid, ctok, curl or g_url)
        # своих ключей нет → глобальные, но уважаем выключатель клиники
        return (c_enabled and g_enabled, g_id, g_token, g_url)
    return (g_enabled and master_enabled, g_id, g_token, g_url)


def wa_enabled():
    enabled, idi, token, _url = _wa_config()
    return bool(enabled and idi and token)


def _chat_id(phone):
    """Телефон → chatId Green-API: '996XXXXXXXXX@c.us'. 0XXXXXXXXX (KG) → 996XXXXXXXXX."""
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    if d.startswith("0") and len(d) == 10:
        d = "996" + d[1:]
    if not d:
        return None
    return d + "@c.us"


def _api_url(method):
    _enabled, idi, token, url = _wa_config()
    base = (url or "https://api.greenapi.com").rstrip("/")
    return "%s/waInstance%s/%s/%s" % (base, idi, method, token)


def wa_send_chat(chat, text):
    """Отправить текст в произвольный чат Green-API (chatId уже готов: @c.us или @g.us)."""
    if not wa_enabled():
        log.info("WhatsApp(Green-API) выключен — пропуск отправки в %s", chat)
        return False
    if not chat:
        return False
    payload = {"chatId": chat, "message": text}
    req = urllib.request.Request(
        _api_url("sendMessage"), data=json.dumps(payload).encode("utf-8"), method="POST",
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


def wa_send_text(phone, text):
    """Отправить текст на номер телефона (преобразуется в chatId @c.us). True/False."""
    chat = _chat_id(phone)
    if not chat:
        return False
    return wa_send_chat(chat, text)


def notify_groups(text, clinic=None):
    """Разослать текст во все включённые WhatsApp-группы клиники. Возвращает кол-во отправленных."""
    if not wa_enabled():
        return 0
    from apps.notifications.models import WaGroup
    from apps.tenancy import get_current_clinic
    qs = WaGroup.all_clinics.filter(notify=True)
    cl = clinic or get_current_clinic()
    if cl is not None:
        qs = qs.filter(clinic=cl)
    sent = 0
    for g in qs:
        if g.chat_id and wa_send_chat(g.chat_id, text):
            sent += 1
    return sent


def wa_state():
    """Состояние инстанса Green-API: 'authorized' | 'notAuthorized' | 'starting' | '' (ошибка/выкл)."""
    _enabled, idi, token, _url = _wa_config()
    if not (idi and token):
        return ""
    try:
        with urllib.request.urlopen(_api_url("getStateInstance"), timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return data.get("stateInstance", "")
    except Exception as e:  # noqa: BLE001
        log.warning("WhatsApp(Green-API) getStateInstance ошибка: %s", e)
        return ""


def wa_qr():
    """QR-код для привязки устройства. Возвращает (type, message):
    type='qrCode' → message = base64 PNG; type='alreadyLogged' → уже подключено; '' → ошибка."""
    _enabled, idi, token, _url = _wa_config()
    if not (idi and token):
        return ("", "")
    try:
        with urllib.request.urlopen(_api_url("qr"), timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return (data.get("type", ""), data.get("message", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("WhatsApp(Green-API) qr ошибка: %s", e)
        return ("", "")


# Совместимость с возможными вызовами шаблонов — у Green-API шаблоны не нужны
def wa_notify(phone, text, template_setting=None, params=None):
    return wa_send_text(phone, text)


DEFAULT_TEMPLATES = [
    ("Подтверждение записи", "confirm",
     "✅ *{клиника}*\n\n"
     "Здравствуйте, *{имя}*!\n"
     "Ваш приём *подтверждён* 🎉\n\n"
     "📅 Дата: *{дата}*\n"
     "🕐 Время: *{время}*\n"
     "👨‍⚕️ Врач: _{врач}_\n\n"
     "Ждём вас! 💙"),
    ("Напоминание о приёме", "reminder",
     "🔔 *{клиника}*\n\n"
     "Здравствуйте, *{имя}*!\n"
     "Напоминаем о вашем приёме _завтра_:\n\n"
     "📅 Дата: *{дата}*\n"
     "🕐 Время: *{время}*\n"
     "👨‍⚕️ Врач: _{врач}_\n\n"
     "До встречи! 😊 Если планы изменятся — пожалуйста, сообщите нам."),
    ("Напоминание (за час)", "reminder_hour",
     "⏰ *{клиника}*\n\n"
     "Здравствуйте, *{имя}*!\n"
     "Напоминаем: ваш приём _сегодня в {время}_ 🕐\n"
     "👨‍⚕️ Врач: _{врач}_\n\n"
     "Ждём вас! Не опаздывайте, пожалуйста 🙏"),
    ("О задолженности", "debt",
     "💳 *{клиника}*\n\n"
     "Здравствуйте, *{имя}*!\n"
     "У вас числится задолженность: *{долг} сом*.\n\n"
     "Просим погасить её при следующем визите. Спасибо за понимание! 🙏"),
    ("Благодарность за визит", "manual",
     "💙 *{клиника}*\n\n"
     "Спасибо, что выбрали нас, *{имя}*!\n"
     "Будем рады видеть вас снова. Здоровья и красивой улыбки! 😁🦷"),
    ("Поздравление с днём рождения", "birthday",
     "🎉 *С Днём Рождения!* 🎂\n\n"
     "Уважаемый(ая) *{фио}*!\n"
     "Команда *{клиника}* от всей души поздравляет вас и желает крепкого "
     "здоровья, счастья и сияющей улыбки! ✨🦷"),
]


def seed_default_templates():
    """Создать набор дефолтных шаблонов для текущей клиники (если их нет)."""
    from apps.notifications.models import MessageTemplate
    for name, kind, body in DEFAULT_TEMPLATES:
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
    # убрать незаполненные плейсхолдеры и пустые маркеры форматирования
    import re
    out = re.sub(r"\{[А-Яа-яёЁ]+\}", "", out)
    out = re.sub(r"\*\s*\*", "", out)   # пустой *жирный*
    out = re.sub(r"_\s*_", "", out)     # пустой _курсив_
    return out
