"""Telegram-бот клиники для ПЕРСОНАЛА (врачи, администраторы) и групп.

Пациентская часть бота (привязка по номеру, «Мои долги/приёмы», кнопки
подтверждения записи) живёт в views._tg_handle_update. Здесь — всё, что
касается сотрудников:

* привязка: сотрудник пишет боту /start и делится СВОИМ контактом; если номер
  совпадает с телефоном сотрудника в CRM — в User.telegram_id сохраняется его
  Telegram ID, и вместо меню пациента он получает меню сотрудника;
* меню: «Приёмы сегодня», «Выбрать дату» (календарь из инлайн-кнопок, можно и
  напечатать дату «25.09»), «Напомнить пациентам» (выбор даты → подтверждение
  → рассылка напоминаний пациентам этих записей);
* группы: бота добавляют в группу персонала, администратор пишет там /group —
  туда начинают приходить новые записи/заявки/отмены (всё, что уходит в
  WhatsApp-группы через notify_groups) и вечерняя сводка записей на завтра.

Врач видит только свои записи, администратор/директор/остальной персонал —
все записи клиники (с именем врача)."""
import html
import logging
import re
from datetime import date, timedelta

from django.utils import timezone

log = logging.getLogger("apps")

BTN_TODAY = "📅 Приёмы сегодня"
BTN_PICK_DATE = "📆 Выбрать дату"
BTN_REMIND = "🔔 Напомнить пациентам"
STAFF_KEYBOARD = {
    "keyboard": [[{"text": BTN_TODAY}, {"text": BTN_PICK_DATE}], [{"text": BTN_REMIND}]],
    "resize_keyboard": True,
}

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
STATUS_ICONS = {
    "scheduled": "🕓 Записан",
    "confirmed": "✅ Подтвердил",
    "arrived": "🚪 Пришёл",
    "in_progress": "🦷 На приёме",
    "completed": "✔️ Завершён",
    "no_show": "⚠️ Не пришёл",
}
PICKER_DAYS = 14
TG_LIMIT = 3800  # у Telegram предел 4096 символов, оставляем запас на разметку


# ── Общие утилиты ────────────────────────────────────────────────────────

def wa_to_html(text):
    """Текст в разметке WhatsApp (*жирный*, _курсив_) → HTML для Telegram,
    чтобы одни и те же уведомления можно было слать в оба мессенджера."""
    out = html.escape(text or "", quote=False)
    out = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w/])_([^_\n]+)_(?![\w])", r"<i>\1</i>", out)
    return out


def _esc(s):
    return html.escape(str(s or ""), quote=False)


def _send(chat_id, text, token, buttons=None, keyboard=None):
    from .telegram import _call, _inline_keyboard
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    else:
        kb = _inline_keyboard(buttons)
        if kb:
            payload["reply_markup"] = kb
    return _call("sendMessage", payload, token=token)


def _day_label(d):
    today = timezone.localdate()
    base = "%s, %s" % (WEEKDAYS[d.weekday()], d.strftime("%d.%m.%Y"))
    if d == today:
        return "сегодня (%s)" % base
    if d == today + timedelta(days=1):
        return "завтра (%s)" % base
    return base


def parse_date(text):
    """«25.09», «25.09.2026», «25/09/26», «2026-09-25» → date или None."""
    t = (text or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?", t)
        if not m:
            return None
        d, mo = int(m.group(1)), int(m.group(2))
        y = m.group(3)
        y = timezone.localdate().year if y is None else (2000 + int(y) if len(y) == 2 else int(y))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


# ── Сотрудники ───────────────────────────────────────────────────────────

def staff_for_chat(clinic, from_id):
    from apps.users.models import User
    if not from_id:
        return None
    return User.objects.filter(clinic=clinic, is_active=True, telegram_id=from_id).first()


def find_staff_by_phone(clinic, phone):
    from apps.users.models import User
    from apps.patients.models import normalize_phone
    norm = normalize_phone(phone)
    if len(norm) < 9:
        return None
    for u in User.objects.filter(clinic=clinic, is_active=True).exclude(phone=""):
        if normalize_phone(u.phone) == norm:
            return u
    return None


def _superadmin_q():
    from django.db.models import Q
    from apps.users.models import Role
    return Q(is_superuser=True) | Q(role__name=Role.SUPERADMIN) | Q(roles__name=Role.SUPERADMIN)


def superadmin_for_chat(from_id):
    """Суперадмин платформы, подтвердивший себя в боте командой /admin.
    Telegram ID один и тот же во всех ботах, поэтому подтверждения в одном
    боте достаточно, чтобы подключать группы (/group) у любой клиники."""
    from apps.users.models import User
    if not from_id:
        return None
    return User.objects.filter(_superadmin_q(), is_active=True, telegram_id=from_id).distinct().first()


def find_superadmin_by_phone(phone):
    from apps.users.models import User
    from apps.patients.models import normalize_phone
    norm = normalize_phone(phone)
    if len(norm) < 9:
        return None
    for u in User.objects.filter(_superadmin_q(), is_active=True).exclude(phone="").distinct():
        if normalize_phone(u.phone) == norm:
            return u
    return None


def sees_all(user):
    """Врач — только свои записи; админ/директор и прочий персонал — все."""
    return bool(user.is_superadmin or user.is_admin or not user.is_doctor)


def can_manage_groups(user):
    return bool(user.is_superadmin or user.is_admin)


def _role_label(user):
    if user.is_superadmin or user.is_admin_main:
        return "директор"
    if user.is_admin:
        return "администратор"
    if user.is_doctor:
        return "врач"
    return "сотрудник"


def send_staff_menu(chat_id, user, token, text=None):
    if text is None:
        scope = "все записи клиники" if sees_all(user) else "ваши записи"
        text = ("👋 %s, это меню сотрудника.\n\n"
                "📅 <b>Приёмы сегодня</b> — %s на сегодня\n"
                "📆 <b>Выбрать дату</b> — приёмы на любой день (можно просто написать дату, например 25.09)\n"
                "🔔 <b>Напомнить пациентам</b> — отправить напоминание пациентам записей на выбранный день"
                % (_esc(user.name), scope))
    return _send(chat_id, text, token, keyboard=STAFF_KEYBOARD)


# ── Списки приёмов ───────────────────────────────────────────────────────

def _day_qs(user, day):
    from apps.appointments.models import Appointment
    qs = (Appointment.objects.filter(start_at__date=day)
          .select_related("patient", "doctor").order_by("start_at"))
    if user is not None and not sees_all(user):
        qs = qs.filter(doctor=user)
    return qs


def day_report(user, day, title=None):
    """Список приёмов на день → список сообщений (длинный день режется на части)."""
    appts = list(_day_qs(user, day))
    active = [a for a in appts if a.status != "cancelled"]
    cancelled = len(appts) - len(active)
    show_doctor = user is None or sees_all(user)
    head = title or "📅 <b>Приёмы на %s</b>" % _day_label(day)
    if not active:
        body = head + "\n\nЗаписей нет."
        if cancelled:
            body += "\nОтменено: %s" % cancelled
        return [body]

    blocks = []
    if show_doctor:
        by_doc = {}
        for a in active:
            by_doc.setdefault(a.doctor.name if a.doctor_id else "—", []).append(a)
        for doc_name, items in sorted(by_doc.items()):
            blocks.append("\n👨‍⚕️ <b>%s</b> — %s" % (_esc(doc_name), len(items)))
            blocks.extend(_appt_line(a) for a in items)
    else:
        blocks.extend(_appt_line(a) for a in active)

    foot = "\nВсего: <b>%s</b>" % len(active)
    if cancelled:
        foot += " · отменено: %s" % cancelled

    chunks, cur = [], head + "\n"
    for b in blocks:
        if len(cur) + len(b) + 1 > TG_LIMIT:
            chunks.append(cur)
            cur = ""
        cur += "\n" + b
    cur += "\n" + foot
    chunks.append(cur)
    return chunks


def _appt_line(a):
    st, en = timezone.localtime(a.start_at), timezone.localtime(a.end_at)
    p = a.patient
    name = _esc(p.full_name) if p else "—"
    line = "🕘 <b>%s–%s</b> %s" % (st.strftime("%H:%M"), en.strftime("%H:%M"), name)
    extra = []
    if p and p.phone:
        extra.append("📞 %s" % _esc(p.phone))
    extra.append(STATUS_ICONS.get(a.status, _esc(a.get_status_display())))
    if a.source == "online":
        extra.append("🌐 с сайта")
    return line + "\n      " + " · ".join(extra)


# ── Выбор даты (инлайн-календарь) ────────────────────────────────────────

def date_picker(mode, page=0):
    """mode: 'l' — показать приёмы, 'r' — напомнить пациентам.
    Страница — 14 дней начиная с сегодня + 14*page (для напоминаний только вперёд)."""
    today = timezone.localdate()
    if mode == "r":
        page = max(0, page)
    start = today + timedelta(days=PICKER_DAYS * page)
    days = [start + timedelta(days=i) for i in range(PICKER_DAYS)]
    rows, row = [], []
    for d in days:
        label = "Сегодня" if d == today else ("Завтра" if d == today + timedelta(days=1)
                                              else "%s %s" % (WEEKDAYS[d.weekday()], d.strftime("%d.%m")))
        row.append((label, "sdd:%s:%s" % (mode, d.isoformat())))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if mode == "l" or page > 0:
        nav.append(("◀ Раньше", "sdp:%s:%s" % (mode, page - 1)))
    nav.append(("Позже ▶", "sdp:%s:%s" % (mode, page + 1)))
    rows.append(nav)
    if mode == "r":
        text = "🔔 <b>Напомнить пациентам</b> — выберите день приёмов:"
    else:
        text = "📆 <b>Выберите дату</b> (или напишите её, например 25.09):"
    text += "\n%s — %s" % (days[0].strftime("%d.%m.%Y"), days[-1].strftime("%d.%m.%Y"))
    return text, rows


# ── Напоминания пациентам ────────────────────────────────────────────────

def _remind_targets(user, day):
    from apps.appointments.models import Appointment
    qs = _day_qs(user, day).filter(
        patient__isnull=False,
        status__in=[Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED],
        start_at__gt=timezone.now())
    return list(qs)


def _reminder_text(appt):
    from .models import MessageTemplate
    from .whatsapp import render_message
    t = MessageTemplate.objects.filter(kind="reminder", is_active=True).first()
    body = t.body if t else (
        "🔔 *{клиника}*\n\nЗдравствуйте, *{имя}*!\n"
        "Напоминаем о приёме.\n\n📅 Дата: *{дата}*\n🕐 Время: *{время}*\n👨‍⚕️ Врач: _{врач}_\n\n"
        "Если планы изменились — пожалуйста, сообщите нам.")
    return render_message(body, patient=appt.patient, appt=appt)


def send_patient_reminder(appt):
    """Напомнить пациенту о записи: основной мессенджер клиники, при неудаче —
    второй. В Telegram — с кнопками «Подтвердить/Отменить». True, если ушло."""
    from .models import WaMessage
    from .whatsapp import wa_enabled, wa_send_text
    from .telegram import tg_enabled, tg_send_text
    from apps.settings_clinic.models import ClinicSettings
    p = appt.patient
    if p is None:
        return False
    msg = _reminder_text(appt)

    def via_tg():
        if not (p.telegram_chat_id and tg_enabled()):
            return False
        ok = tg_send_text(p.telegram_chat_id, wa_to_html(msg),
                          buttons=[[("✅ Подтвердить", "appt_confirm:%s" % appt.pk),
                                    ("❌ Отменить", "appt_cancel:%s" % appt.pk)]])
        WaMessage.objects.create(patient=p, direction="out", channel="tg",
                                 phone=str(p.telegram_chat_id), body=msg, ok=ok)
        return ok

    def via_wa():
        if not (p.phone and wa_enabled()):
            return False
        ok = wa_send_text(p.phone, msg)
        WaMessage.objects.create(patient=p, direction="out", channel="wa",
                                 phone=p.phone, body=msg, ok=ok)
        return ok

    cs = ClinicSettings.get()
    first, second = (via_tg, via_wa) if getattr(cs, "primary_messenger", "") == "tg" else (via_wa, via_tg)
    ok = first() or second()
    # Если приём в ближайшие сутки — это и есть напоминание «за день»,
    # авто-рассылка (wa_reminders) не должна прислать его второй раз.
    if ok and appt.start_at <= timezone.now() + timedelta(hours=25):
        type(appt).objects.filter(pk=appt.pk).update(reminded_day=True)
    return ok


# ── Обработчики апдейтов ─────────────────────────────────────────────────

def _cmd(text):
    """'/group@my_bot arg' → 'group'."""
    if not text.startswith("/"):
        return ""
    return text[1:].split(None, 1)[0].split("@", 1)[0].lower() if len(text) > 1 else ""


def handle_private(clinic, msg, token):
    """Личный чат с ботом. True — апдейт обработан как сотрудник (дальше
    пациентскую логику не запускать)."""
    chat_id = msg.get("chat", {}).get("id")
    from_id = (msg.get("from") or {}).get("id")
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")

    staff = staff_for_chat(clinic, from_id)

    # Суперадмин: /admin → «Подтвердить номер» → его Telegram ID запоминается,
    # и в группах он может писать /group. В личке остаётся обычным
    # пациентом (его номер может быть и пациентом клиники), поэтому
    # автоматически по контакту суперадмина не переключаем.
    from .tg_patient import get_chat
    if staff is None and _cmd(text) == "admin":
        chat = get_chat(clinic, chat_id)
        chat.state, chat.data = "await_admin", {}
        chat.save(update_fields=["state", "data", "updated_at"])
        _send(chat_id, "Подтвердите номер супер-админа — нажмите кнопку ниже.", token, keyboard={
            "keyboard": [[{"text": "📱 Подтвердить номер", "request_contact": True}]],
            "resize_keyboard": True, "one_time_keyboard": True})
        return True
    if staff is None and contact:
        chat = get_chat(clinic, chat_id)
        if chat.state == "await_admin":
            chat.state = ""
            chat.save(update_fields=["state", "updated_at"])
            own = contact.get("user_id") and contact.get("user_id") == from_id
            su = find_superadmin_by_phone(contact.get("phone_number") or "") if own else None
            if su is None:
                _send(chat_id, "Этот номер не принадлежит супер-админу (или отправлен чужой контакт).", token,
                      keyboard={"remove_keyboard": True})
                return True
            su.telegram_id = from_id
            su.save(update_fields=["telegram_id"])
            _send(chat_id, "✅ Вы подтверждены как супер-админ: <b>%s</b>.\n\n"
                           "Теперь добавьте бота клиники в группу и напишите там /group — "
                           "это работает в группах ботов всех клиник." % _esc(su.name), token,
                  keyboard={"remove_keyboard": True})
            return True

    if staff is None:
        # Привязка только по СВОЕМУ контакту (кнопка «Поделиться номером»):
        # чужую визитку или напечатанный номер подделать легко, а сотрудник
        # по боту видит данные пациентов.
        if contact and contact.get("user_id") and contact.get("user_id") == from_id:
            u = find_staff_by_phone(clinic, contact.get("phone_number") or "")
            if u is not None:
                from apps.users.models import User
                User.objects.filter(clinic=clinic, telegram_id=from_id).exclude(pk=u.pk).update(telegram_id=None)
                u.telegram_id = from_id
                u.save(update_fields=["telegram_id"])
                send_staff_menu(chat_id, u, token, text=(
                    "✅ Вы подключены как %s: <b>%s</b>.\n\n"
                    "Сюда будут приходить новые записи к вам, заявки с сайта и отмены.\n"
                    "Кнопки внизу — приёмы на сегодня, на любую дату и напоминания пациентам."
                    % (_role_label(u), _esc(u.name))))
                return True
        return False

    cmd = _cmd(text)
    if cmd == "stop":
        staff.telegram_id = None
        staff.save(update_fields=["telegram_id"])
        from .telegram import _call
        _call("sendMessage", {"chat_id": chat_id,
                              "text": "Вы отключены от бота. Чтобы подключиться снова — /start",
                              "reply_markup": {"remove_keyboard": True}}, token=token)
        return True
    if cmd in ("start", "menu", "help") or contact:
        send_staff_menu(chat_id, staff, token)
        return True
    if text == BTN_TODAY or cmd == "today":
        for part in day_report(staff, timezone.localdate()):
            _send(chat_id, part, token)
        return True
    if text == BTN_PICK_DATE or cmd == "date":
        t, rows = date_picker("l")
        _send(chat_id, t, token, buttons=rows)
        return True
    if text == BTN_REMIND or cmd == "remind":
        t, rows = date_picker("r")
        _send(chat_id, t, token, buttons=rows)
        return True
    d = parse_date(text)
    if d is not None:
        for part in day_report(staff, d):
            _send(chat_id, part, token)
        return True
    send_staff_menu(chat_id, staff, token, text=(
        "Не понял команду. Выберите кнопку внизу или напишите дату, например <b>25.09</b>."))
    return True


def handle_callback(clinic, cq, token):
    """Инлайн-кнопки меню сотрудника (sdp/sdd/sdr). True — обработано."""
    from .telegram import tg_answer_callback, tg_edit_message
    data = cq.get("data", "") or ""
    if not data.startswith(("sdp:", "sdd:", "sdr:")):
        return False
    cq_id = cq.get("id")
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    staff = staff_for_chat(clinic, (cq.get("from") or {}).get("id"))
    if staff is None:
        tg_answer_callback(cq_id, "Доступно только сотрудникам клиники", token=token)
        return True

    parts = data.split(":")
    try:
        if parts[0] == "sdp":
            mode, page = parts[1], int(parts[2])
            t, rows = date_picker(mode, page)
            tg_edit_message(chat_id, message_id, t, buttons=rows, token=token)
        elif parts[0] == "sdd":
            mode, day = parts[1], date.fromisoformat(parts[2])
            if mode == "r":
                targets = _remind_targets(staff, day)
                if not targets:
                    tg_edit_message(chat_id, message_id,
                                    "🔔 На %s нет предстоящих записей, кому можно напомнить." % _day_label(day),
                                    buttons=[[("◀ Другая дата", "sdp:r:0")]], token=token)
                else:
                    names = "\n".join("• %s — %s" % (timezone.localtime(a.start_at).strftime("%H:%M"),
                                                      _esc(a.patient.full_name)) for a in targets[:30])
                    if len(targets) > 30:
                        names += "\n… и ещё %s" % (len(targets) - 30)
                    tg_edit_message(chat_id, message_id,
                                    "🔔 Напомнить <b>%s</b> пациентам о приёме на %s?\n\n%s"
                                    % (len(targets), _day_label(day), names),
                                    buttons=[[("✅ Отправить", "sdr:%s" % day.isoformat()),
                                              ("✖ Отмена", "sdp:r:0")]], token=token)
            else:
                reports = day_report(staff, day)
                tg_edit_message(chat_id, message_id, reports[0],
                                buttons=[[("◀ Другая дата", "sdp:l:0")]] if len(reports) == 1 else None,
                                token=token)
                for part in reports[1:]:
                    _send(chat_id, part, token)
        elif parts[0] == "sdr":
            day = date.fromisoformat(parts[1])
            targets = _remind_targets(staff, day)
            tg_edit_message(chat_id, message_id, "⏳ Отправляю напоминания…", token=token)
            sent = sum(1 for a in targets if send_patient_reminder(a))
            tg_edit_message(chat_id, message_id,
                            "✅ Напоминания на %s отправлены: <b>%s</b> из %s.%s"
                            % (_day_label(day), sent, len(targets),
                               "" if sent == len(targets) else
                               "\nОстальным не удалось — нет Telegram/WhatsApp или номер не в мессенджере."),
                            token=token)
    except (ValueError, IndexError):
        pass
    tg_answer_callback(cq_id, token=token)
    return True


def handle_group(clinic, msg, token):
    """Сообщения из групп: только служебные (/group, /ungroup, добавление
    бота, миграция в супергруппу). Переписку группы в CRM не пишем."""
    from .models import TgGroup
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    title = chat.get("title") or ""

    new_id = msg.get("migrate_to_chat_id")
    if new_id:
        TgGroup.all_clinics.filter(clinic=clinic, chat_id=chat_id).update(chat_id=new_id)
        return

    for m in msg.get("new_chat_members") or []:
        if m.get("is_bot"):
            from apps.settings_clinic.models import ClinicSettings
            uname = (ClinicSettings.get().telegram_bot_username or "").lower()
            if not uname or (m.get("username") or "").lower() == uname:
                _send(chat_id, "👋 Привет! Чтобы сюда приходили уведомления о записях и заявках, "
                               "администратор клиники должен написать в этой группе команду /group.\n\n"
                               "Перед этим он должен подключиться к боту в личных сообщениях: "
                               "/start → «Поделиться номером».", token)
                return

    cmd = _cmd((msg.get("text") or "").strip())
    if cmd not in ("group", "ungroup"):
        return
    from_id = (msg.get("from") or {}).get("id")
    staff = staff_for_chat(clinic, from_id) or superadmin_for_chat(from_id)
    if staff is None or not can_manage_groups(staff):
        _send(chat_id, "Подключать группу может только администратор или директор клиники, "
                       "подключённый к боту: напишите боту в личные сообщения /start и поделитесь номером. "
                       "Супер-админ — один раз напишите боту в личные сообщения /admin.", token)
        return
    if cmd == "group":
        g, _c = TgGroup.all_clinics.update_or_create(
            clinic=clinic, chat_id=chat_id, defaults={"title": title[:255], "notify": True})
        _send(chat_id, "✅ Группа подключена. Сюда будут приходить новые записи, заявки с сайта, "
                       "отмены и вечером — список записей на завтра.\n\nОтключить: /ungroup", token)
    else:
        TgGroup.all_clinics.filter(clinic=clinic, chat_id=chat_id).delete()
        _send(chat_id, "Группа отключена — уведомления сюда больше не придут.", token)


# ── Уведомления персоналу ────────────────────────────────────────────────

def notify_user(user, text_wa):
    """Личное уведомление сотруднику в Telegram (если он подключён к боту)."""
    try:
        from .telegram import tg_enabled, tg_send_chat
        if user is None or not getattr(user, "telegram_id", None) or not tg_enabled():
            return False
        return bool(tg_send_chat(user.telegram_id, wa_to_html(text_wa)))
    except Exception:  # noqa: BLE001
        log.exception("Telegram: уведомление сотруднику не отправлено")
        return False


def _send_group(g, text, token):
    """Отправить в группу; сама разбирается с миграцией в супергруппу и с
    исключением бота из группы. True — доставлено."""
    res = _send(g.chat_id, text, token)
    if res.get("ok"):
        return True
    err = res.get("error") or b""
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    m = re.search(r'"migrate_to_chat_id"\s*:\s*(-?\d+)', err)
    if m:
        g.chat_id = int(m.group(1))
        g.save(update_fields=["chat_id"])
        return bool(_send(g.chat_id, text, token).get("ok"))
    low = err.lower()
    if "kicked" in low or "chat not found" in low or "not a member" in low or "deleted" in low:
        g.delete()
    return False


def notify_groups(text_wa, clinic=None):
    """Разослать текст (разметка WhatsApp) во все Telegram-группы клиники."""
    try:
        from .models import TgGroup
        from .telegram import _tg_config
        from apps.tenancy import get_current_clinic
        enabled, token = _tg_config()
        if not (enabled and token):
            return 0
        cl = clinic or get_current_clinic()
        if cl is None:
            return 0
        text = wa_to_html(text_wa)
        return sum(1 for g in TgGroup.all_clinics.filter(clinic=cl, notify=True) if _send_group(g, text, token))
    except Exception:  # noqa: BLE001
        log.exception("Telegram: уведомление в группы не отправлено")
        return 0


def send_group_summaries(clinic, now=None, dry=False):
    """Вечерняя сводка (19:00–22:00 местного) записей на завтра в группы.
    Вызывается из wa_reminders каждые ~15 минут; раз в день на группу."""
    from .models import TgGroup
    from .telegram import _tg_config
    now = now or timezone.now()
    local = timezone.localtime(now)
    if not (19 <= local.hour < 22):
        return 0
    enabled, token = _tg_config()
    if not (enabled and token):
        return 0
    today = local.date()
    groups = list(TgGroup.all_clinics.filter(clinic=clinic, notify=True)
                  .exclude(last_summary_on=today))
    if not groups:
        return 0
    tomorrow = today + timedelta(days=1)
    parts = day_report(None, tomorrow, title="🗓 <b>Записи на %s</b>" % _day_label(tomorrow))
    sent = 0
    for g in groups:
        if dry:
            sent += 1
            continue
        ok = all(_send_group(g, p, token) for p in parts)
        if ok:
            TgGroup.all_clinics.filter(pk=g.pk).update(last_summary_on=today)
            sent += 1
    return sent
