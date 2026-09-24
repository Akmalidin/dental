"""Telegram-бот клиники для ПАЦИЕНТОВ: два языка обслуживания (русский и
узбекский латиницей), привязка по номеру, регистрация нового пациента и
онлайн-запись прямо в боте.

Диалог:
  /start → выбор языка → «Поделиться номером»
    · номер есть в базе → карточка привязана → сразу запись (врач → дата → время)
    · номера нет → бот просит ФИО → создаёт карточку → запись
  Меню: «Записаться на приём», «Мои приёмы», «Мои долги», «Язык / Til».

Запись создаётся той же функцией, что и с сайта (apps.users.site_views.
create_booking): те же свободные слоты, проверка занятости, лид в «Заявки ·
CRM», уведомления администраторам, врачу и в группы.

Язык и шаг диалога хранятся в TgChat (на пару клиника + chat_id)."""
import html
import logging
from datetime import date, timedelta

from django.utils import timezone

log = logging.getLogger("apps")

LANGS = ("ru", "uz")
BOOK_DAYS = 14

T = {
    "choose_lang": {
        "ru": "🌐 Выберите язык / Tilni tanlang:",
        "uz": "🌐 Tilni tanlang / Выберите язык:",
    },
    "welcome": {
        "ru": "👋 Здравствуйте! Это бот клиники «{clinic}».\n\n"
              "Здесь можно записаться на приём и получать напоминания. "
              "Поделитесь, пожалуйста, номером телефона (кнопка ниже).",
        "uz": "👋 Assalomu alaykum! Bu «{clinic}» klinikasining boti.\n\n"
              "Bu yerda qabulga yozilishingiz va eslatmalar olishingiz mumkin. "
              "Iltimos, telefon raqamingizni yuboring (pastdagi tugma).",
    },
    "share_btn": {"ru": "📱 Поделиться номером телефона", "uz": "📱 Telefon raqamni yuborish"},
    "linked": {
        "ru": "✅ Готово, {name}! Теперь буду присылать сюда напоминания о приёмах.",
        "uz": "✅ Tayyor, {name}! Endi qabul haqidagi eslatmalarni shu yerga yuboraman.",
    },
    "welcome_back": {
        "ru": "👋 {name}, рады вас видеть! Выберите действие в меню ниже 👇",
        "uz": "👋 {name}, sizni ko'rganimizdan xursandmiz! Quyidagi menyudan tanlang 👇",
    },
    "ask_name": {
        "ru": "Мы не нашли этот номер в базе клиники — вы у нас впервые? 🙂\n\n"
              "Напишите, пожалуйста, ваши <b>фамилию, имя и отчество</b>.",
        "uz": "Bu raqam klinika bazasida topilmadi — birinchi marta kelyapsizmi? 🙂\n\n"
              "Iltimos, <b>familiya, ism va otangizning ismini</b> yozing.",
    },
    "name_bad": {
        "ru": "Напишите ФИО текстом, например: <i>Иванов Иван Иванович</i>",
        "uz": "F.I.Sh.ni matn bilan yozing, masalan: <i>Karimov Aziz Akmalovich</i>",
    },
    "registered": {
        "ru": "✅ Спасибо, {name}! Мы вас зарегистрировали.",
        "uz": "✅ Rahmat, {name}! Siz ro'yxatdan o'tdingiz.",
    },
    "need_phone": {
        "ru": "Сначала поделитесь номером телефона — нажмите /start",
        "uz": "Avval telefon raqamingizni yuboring — /start ni bosing",
    },
    "menu_hint": {"ru": "Выберите действие в меню ниже 👇", "uz": "Quyidagi menyudan tanlang 👇"},
    "btn_book": {"ru": "📝 Записаться на приём", "uz": "📝 Qabulga yozilish"},
    "btn_visits": {"ru": "🗓 Мои приёмы", "uz": "🗓 Qabullarim"},
    "btn_debt": {"ru": "💰 Мои долги", "uz": "💰 Qarzlarim"},
    "btn_lang": {"ru": "🌐 Язык / Til", "uz": "🌐 Til / Язык"},
    "lang_set": {"ru": "✅ Язык: русский", "uz": "✅ Til: o'zbekcha"},
    "pick_branch": {"ru": "🏥 Выберите филиал:", "uz": "🏥 Filialni tanlang:"},
    "pick_doctor": {"ru": "👨‍⚕️ Выберите врача:", "uz": "👨‍⚕️ Shifokorni tanlang:"},
    "pick_date": {
        "ru": "👨‍⚕️ {doctor}\n📅 Выберите дату приёма:",
        "uz": "👨‍⚕️ {doctor}\n📅 Qabul sanasini tanlang:",
    },
    "pick_time": {
        "ru": "👨‍⚕️ {doctor}\n📅 {date}\n🕐 Выберите время:",
        "uz": "👨‍⚕️ {doctor}\n📅 {date}\n🕐 Vaqtni tanlang:",
    },
    "no_doctors": {
        "ru": "К сожалению, онлайн-запись сейчас недоступна. Позвоните, пожалуйста, в клинику.",
        "uz": "Afsuski, hozir onlayn yozilish mavjud emas. Iltimos, klinikaga qo'ng'iroq qiling.",
    },
    "no_dates": {
        "ru": "У этого врача нет свободного времени в ближайшие 2 недели. Выберите другого врача.",
        "uz": "Bu shifokorda yaqin 2 hafta ichida bo'sh vaqt yo'q. Boshqa shifokorni tanlang.",
    },
    "no_slots": {
        "ru": "На эту дату свободного времени уже нет. Выберите другую дату.",
        "uz": "Bu sanada bo'sh vaqt qolmadi. Boshqa sanani tanlang.",
    },
    "confirm": {
        "ru": "Проверьте запись:\n\n👨‍⚕️ Врач: <b>{doctor}</b>\n📅 Дата: <b>{date}</b>\n"
              "🕐 Время: <b>{time}</b>\n🏥 Филиал: {branch}\n\nВсё верно?",
        "uz": "Yozuvni tekshiring:\n\n👨‍⚕️ Shifokor: <b>{doctor}</b>\n📅 Sana: <b>{date}</b>\n"
              "🕐 Vaqt: <b>{time}</b>\n🏥 Filial: {branch}\n\nHammasi to'g'rimi?",
    },
    "btn_confirm": {"ru": "✅ Записаться", "uz": "✅ Yozilish"},
    "btn_cancel": {"ru": "✖ Отмена", "uz": "✖ Bekor qilish"},
    "btn_back": {"ru": "◀ Назад", "uz": "◀ Orqaga"},
    "booked": {
        "ru": "✅ <b>Вы записаны!</b>\n\n👨‍⚕️ {doctor}\n📅 {date}  🕐 {time}\n🏥 {branch}\n\n"
              "Накануне пришлём напоминание. Если планы изменятся — пожалуйста, сообщите нам.",
        "uz": "✅ <b>Siz qabulga yozildingiz!</b>\n\n👨‍⚕️ {doctor}\n📅 {date}  🕐 {time}\n🏥 {branch}\n\n"
              "Bir kun oldin eslatma yuboramiz. Rejalaringiz o'zgarsa — iltimos, bizga xabar bering.",
    },
    "slot_taken": {
        "ru": "Это время только что заняли — выберите, пожалуйста, другое.",
        "uz": "Bu vaqt hozirgina band qilindi — iltimos, boshqasini tanlang.",
    },
    "book_error": {
        "ru": "Не получилось записаться: {error}. Попробуйте ещё раз или позвоните в клинику.",
        "uz": "Yozilib bo'lmadi: {error}. Qaytadan urinib ko'ring yoki klinikaga qo'ng'iroq qiling.",
    },
    "book_cancelled": {
        "ru": "Запись не оформлена. Когда будете готовы — нажмите «📝 Записаться на приём».",
        "uz": "Yozilish bekor qilindi. Tayyor bo'lganingizda «📝 Qabulga yozilish» tugmasini bosing.",
    },
    "debt_yes": {"ru": "💰 Ваш долг: <b>{amount} {cur}</b>", "uz": "💰 Qarzingiz: <b>{amount} {cur}</b>"},
    "debt_no": {"ru": "💰 У вас нет задолженности. Спасибо!", "uz": "💰 Sizda qarz yo'q. Rahmat!"},
    "upcoming": {"ru": "📌 <b>Ближайшие записи:</b>", "uz": "📌 <b>Yaqin qabullar:</b>"},
    "visits_none": {"ru": "🗓 Приёмов пока не найдено.", "uz": "🗓 Hozircha qabullar topilmadi."},
    "visits_list": {
        "ru": "🗓 Ваши приёмы (последние {n}) — выберите, чтобы посмотреть детали:",
        "uz": "🗓 Qabullaringiz (oxirgi {n} ta) — batafsil ko'rish uchun tanlang:",
    },
    "appt_new": {
        "ru": "✅ <b>{clinic}</b>\n\nЗдравствуйте, <b>{name}</b>!\nВы записаны на приём.\n\n"
              "📅 Дата: <b>{date}</b>\n🕐 Время: <b>{time}</b>\n👨‍⚕️ Врач: {doctor}",
        "uz": "✅ <b>{clinic}</b>\n\nAssalomu alaykum, <b>{name}</b>!\nSiz qabulga yozildingiz.\n\n"
              "📅 Sana: <b>{date}</b>\n🕐 Vaqt: <b>{time}</b>\n👨‍⚕️ Shifokor: {doctor}",
    },
    "btn_appt_confirm": {"ru": "✅ Подтвердить", "uz": "✅ Tasdiqlash"},
    "btn_appt_cancel": {"ru": "❌ Отменить", "uz": "❌ Bekor qilish"},
    "appt_confirmed": {
        "ru": "✅ <b>Запись подтверждена</b>\nЖдём вас {date} в {time}",
        "uz": "✅ <b>Qabul tasdiqlandi</b>\nSizni {date} kuni soat {time} da kutamiz",
    },
    "appt_cancelled": {"ru": "❌ <b>Запись отменена</b>", "uz": "❌ <b>Qabul bekor qilindi</b>"},
    "toast_confirmed": {"ru": "Запись подтверждена ✅", "uz": "Qabul tasdiqlandi ✅"},
    "toast_cancelled": {"ru": "Запись отменена", "uz": "Qabul bekor qilindi"},
    "today": {"ru": "Сегодня", "uz": "Bugun"},
    "tomorrow": {"ru": "Завтра", "uz": "Ertaga"},
}
WEEKDAYS = {"ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
            "uz": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]}


def t(key, lang, **kw):
    s = T[key].get(lang) or T[key]["ru"]
    return s.format(**kw) if kw else s


def labels(key):
    return {T[key][lg] for lg in LANGS}


def _esc(s):
    return html.escape(str(s or ""), quote=False)


# ── Состояние чата ───────────────────────────────────────────────────────

def get_chat(clinic, chat_id):
    from .models import TgChat
    chat, _c = TgChat.all_clinics.get_or_create(clinic=clinic, chat_id=chat_id)
    return chat


def lang_for_chat(clinic, chat_id):
    from .models import TgChat
    if not chat_id:
        return "ru"
    lg = (TgChat.all_clinics.filter(clinic=clinic, chat_id=chat_id)
          .values_list("lang", flat=True).first())
    return lg if lg in LANGS else "ru"


def _set_state(chat, state="", data=None):
    chat.state = state
    chat.data = data or {}
    chat.save(update_fields=["state", "data", "updated_at"])


# ── Отправка ─────────────────────────────────────────────────────────────

def _call(method, payload, token):
    from .telegram import _call as tg_call
    return tg_call(method, payload, token=token)


def _send(chat_id, text, token, buttons=None, keyboard=None):
    from .telegram import _inline_keyboard
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard is not None:
        payload["reply_markup"] = keyboard
    else:
        kb = _inline_keyboard(buttons)
        if kb:
            payload["reply_markup"] = kb
    return _call("sendMessage", payload, token)


def _edit(chat_id, message_id, text, token, buttons=None):
    from .telegram import tg_edit_message
    return tg_edit_message(chat_id, message_id, text, buttons=buttons, token=token)


def menu_keyboard(lang):
    return {
        "keyboard": [[{"text": t("btn_book", lang)}],
                     [{"text": t("btn_visits", lang)}, {"text": t("btn_debt", lang)}],
                     [{"text": t("btn_lang", lang)}]],
        "resize_keyboard": True,
    }


def send_menu(chat_id, lang, token, text=None):
    return _send(chat_id, text or t("menu_hint", lang), token, keyboard=menu_keyboard(lang))


def ask_language(chat_id, token):
    return _send(chat_id, T["choose_lang"]["ru"], token,
                 buttons=[[("🇷🇺 Русский", "lang:ru"), ("🇺🇿 O'zbekcha", "lang:uz")]])


def ask_contact(chat_id, clinic, lang, token):
    kb = {"keyboard": [[{"text": t("share_btn", lang), "request_contact": True}]],
          "resize_keyboard": True, "one_time_keyboard": True}
    return _send(chat_id, t("welcome", lang, clinic=_esc(clinic.name)), token, keyboard=kb)


# ── Привязка / регистрация ───────────────────────────────────────────────

def _log_in(patient, chat_id, text):
    from .views import _tg_log_inbound
    _tg_log_inbound(patient, chat_id, text)


def link_by_phone(clinic, chat, phone_raw, token):
    """Номер из контакта/текста → привязка к карточке и сразу запись;
    номера в базе нет → просим ФИО. Возвращает пациента или None."""
    from apps.patients.models import Patient, normalize_phone
    pnorm = normalize_phone(phone_raw)
    patient = Patient.objects.filter(phone_norm=pnorm).first() if len(pnorm) >= 9 else None
    lang = chat.lang or "ru"
    if patient is None:
        _set_state(chat, "await_name", {"phone": phone_raw})
        _send(chat.chat_id, t("ask_name", lang), token, keyboard={"remove_keyboard": True})
        return None
    patient.telegram_chat_id = chat.chat_id
    patient.save(update_fields=["telegram_chat_id"])
    _set_state(chat)
    _log_in(patient, chat.chat_id, "📱 Поделился(ась) номером телефона — подключил(а) уведомления")
    send_menu(chat.chat_id, lang, token,
              text=t("linked", lang, name=_esc((patient.first_name or "").strip() or patient.full_name)))
    start_booking(clinic, chat.chat_id, lang, token)
    return patient


def register_patient(clinic, chat, full_name, token):
    """ФИО нового пациента (после неизвестного номера) → карточка → запись."""
    from apps.patients.models import Patient
    from apps.users.models import Branch
    lang = chat.lang or "ru"
    words = [w for w in full_name.replace(",", " ").split() if w]
    if not words or len(full_name) < 2 or len(full_name) > 150 or any(ch.isdigit() for ch in full_name):
        _send(chat.chat_id, t("name_bad", lang), token)
        return None
    phone = (chat.data or {}).get("phone") or ""
    last, first, middle = "", "", ""
    if len(words) == 1:
        first = words[0]
    else:
        last, first, middle = words[0], words[1], " ".join(words[2:])
    branch = (Branch.objects.filter(clinic=clinic, is_active=True, is_main=True).first()
              or Branch.objects.filter(clinic=clinic, is_active=True).first())
    patient = Patient(first_name=first[:100], last_name=last[:100], middle_name=middle[:100],
                      phone=phone, branch=branch, telegram_chat_id=chat.chat_id, clinic=clinic)
    patient.save()
    _set_state(chat)
    _log_in(patient, chat.chat_id, "🆕 Новый пациент через Telegram-бот: %s, %s" % (patient.full_name, phone))
    send_menu(chat.chat_id, lang, token, text=t("registered", lang, name=_esc(first)))
    start_booking(clinic, chat.chat_id, lang, token)
    return patient


# ── Онлайн-запись ────────────────────────────────────────────────────────

def _branches(clinic):
    from apps.users.models import Branch
    return list(Branch.objects.filter(clinic=clinic, is_active=True).order_by("-is_main", "name"))


def _doctors(clinic, branch_id):
    """Врачи для записи: при нескольких филиалах — закреплённые за выбранным
    и не закреплённые ни за одним; при одном филиале — все врачи клиники."""
    from django.db.models import Q
    from apps.users.models import clinic_doctors
    qs = clinic_doctors(clinic)
    if branch_id and len(_branches(clinic)) > 1:
        qs = qs.filter(Q(branches=branch_id) | Q(branches__isnull=True)).distinct()
    return list(qs.order_by("name"))


def _day_label(d, lang):
    today = timezone.localdate()
    if d == today:
        return "%s %s" % (t("today", lang), d.strftime("%d.%m"))
    if d == today + timedelta(days=1):
        return "%s %s" % (t("tomorrow", lang), d.strftime("%d.%m"))
    return "%s %s" % (WEEKDAYS[lang][d.weekday()], d.strftime("%d.%m"))


def _free_days(clinic, doctor_id):
    from apps.users.site_views import slots_for_doctor
    today = timezone.localdate()
    out = []
    for i in range(BOOK_DAYS):
        d = today + timedelta(days=i)
        if slots_for_doctor(clinic, doctor_id, d.isoformat()):
            out.append(d)
    return out


def _grid(buttons, per_row):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def start_booking(clinic, chat_id, lang, token, message_id=None):
    """Первый шаг записи: филиал (если их несколько) или сразу врач."""
    branches = _branches(clinic)
    if len(branches) > 1:
        rows = [[(b.name, "pbb:%s" % b.pk)] for b in branches]
        rows.append([(t("btn_cancel", lang), "pbx")])
        text = t("pick_branch", lang)
    else:
        return _pick_doctor(clinic, chat_id, lang, token, branches[0].pk if branches else 0, message_id)
    if message_id:
        return _edit(chat_id, message_id, text, token, buttons=rows)
    return _send(chat_id, text, token, buttons=rows)


def _pick_doctor(clinic, chat_id, lang, token, branch_id, message_id=None):
    doctors = _doctors(clinic, branch_id)
    if not doctors:
        text, rows = t("no_doctors", lang), None
    else:
        rows = [[(d.name, "pbd:%s:%s" % (branch_id, d.pk))] for d in doctors]
        back = [(t("btn_back", lang), "pbk")] if len(_branches(clinic)) > 1 else []
        rows.append(back + [(t("btn_cancel", lang), "pbx")])
        text = t("pick_doctor", lang)
    if message_id:
        return _edit(chat_id, message_id, text, token, buttons=rows)
    return _send(chat_id, text, token, buttons=rows)


def _doctor(clinic, doctor_id):
    from apps.users.models import clinic_doctors
    return clinic_doctors(clinic).filter(pk=doctor_id).first()


def handle_callback(clinic, cq, token):
    """Инлайн-кнопки пациента: язык (lang:*) и шаги записи (pb*). True — обработано."""
    from .telegram import tg_answer_callback
    from apps.patients.models import Patient
    data = cq.get("data", "") or ""
    if not (data.startswith("lang:") or data.startswith("pb")):
        return False
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    cq_id = cq.get("id")
    chat = get_chat(clinic, chat_id)

    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        if lang not in LANGS:
            lang = "ru"
        chat.lang = lang
        chat.save(update_fields=["lang", "updated_at"])
        tg_answer_callback(cq_id, token=token)
        _edit(chat_id, message_id, t("lang_set", lang), token)
        patient = Patient.objects.filter(telegram_chat_id=chat_id).first()
        if patient is not None:
            send_menu(chat_id, lang, token, text=t("welcome_back", lang, name=_esc(patient.first_name or patient.full_name)))
        else:
            ask_contact(chat_id, clinic, lang, token)
        return True

    lang = chat.lang if chat.lang in LANGS else "ru"
    patient = Patient.objects.filter(telegram_chat_id=chat_id).first()
    if patient is None:
        tg_answer_callback(cq_id, t("need_phone", lang), token=token)
        return True
    tg_answer_callback(cq_id, token=token)

    parts = data.split(":")
    try:
        act = parts[0]
        if act == "pbx":
            _edit(chat_id, message_id, t("book_cancelled", lang), token)
        elif act == "pbk":
            start_booking(clinic, chat_id, lang, token, message_id=message_id)
        elif act == "pbb":
            _pick_doctor(clinic, chat_id, lang, token, int(parts[1]), message_id)
        elif act == "pbd":
            branch_id, doctor_id = int(parts[1]), int(parts[2])
            _pick_date(clinic, chat_id, message_id, lang, token, branch_id, doctor_id)
        elif act == "pbt":
            branch_id, doctor_id, day = int(parts[1]), int(parts[2]), _parse_day(parts[3])
            _pick_time(clinic, chat_id, message_id, lang, token, branch_id, doctor_id, day)
        elif act == "pbs":
            branch_id, doctor_id, day, hh = int(parts[1]), int(parts[2]), _parse_day(parts[3]), int(parts[4])
            doc = _doctor(clinic, doctor_id)
            branch = next((b for b in _branches(clinic) if b.pk == branch_id), None)
            if doc is None:
                return True
            _edit(chat_id, message_id, t("confirm", lang, doctor=_esc(doc.name), date=day.strftime("%d.%m.%Y"),
                                         time="%02d:00" % hh, branch=_esc(branch.name if branch else "—")),
                  token, buttons=[[(t("btn_confirm", lang), "pbc:%s:%s:%s:%s" % (branch_id, doctor_id, parts[3], hh))],
                                  [(t("btn_back", lang), "pbt:%s:%s:%s" % (branch_id, doctor_id, parts[3])),
                                   (t("btn_cancel", lang), "pbx")]])
        elif act == "pbc":
            branch_id, doctor_id, day, hh = int(parts[1]), int(parts[2]), _parse_day(parts[3]), int(parts[4])
            _confirm(clinic, patient, chat_id, message_id, lang, token, branch_id, doctor_id, day, hh)
    except (ValueError, IndexError):
        pass
    return True


def _parse_day(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _pick_date(clinic, chat_id, message_id, lang, token, branch_id, doctor_id):
    doc = _doctor(clinic, doctor_id)
    if doc is None:
        return
    days = _free_days(clinic, doctor_id)
    back = (t("btn_back", lang), "pbb:%s" % branch_id)
    if not days:
        _edit(chat_id, message_id, t("no_dates", lang), token, buttons=[[back]])
        return
    btns = [(_day_label(d, lang), "pbt:%s:%s:%s" % (branch_id, doctor_id, d.strftime("%Y%m%d"))) for d in days]
    rows = _grid(btns, 3) + [[back, (t("btn_cancel", lang), "pbx")]]
    _edit(chat_id, message_id, t("pick_date", lang, doctor=_esc(doc.name)), token, buttons=rows)


def _pick_time(clinic, chat_id, message_id, lang, token, branch_id, doctor_id, day):
    from apps.users.site_views import slots_for_doctor
    doc = _doctor(clinic, doctor_id)
    if doc is None:
        return
    slots = slots_for_doctor(clinic, doctor_id, day.isoformat())
    back = (t("btn_back", lang), "pbd:%s:%s" % (branch_id, doctor_id))
    if not slots:
        _edit(chat_id, message_id, t("no_slots", lang), token, buttons=[[back]])
        return
    ds = day.strftime("%Y%m%d")
    btns = [(s, "pbs:%s:%s:%s:%s" % (branch_id, doctor_id, ds, int(s[:2]))) for s in slots]
    rows = _grid(btns, 4) + [[back, (t("btn_cancel", lang), "pbx")]]
    _edit(chat_id, message_id, t("pick_time", lang, doctor=_esc(doc.name), date=_day_label(day, lang)),
          token, buttons=rows)


def _confirm(clinic, patient, chat_id, message_id, lang, token, branch_id, doctor_id, day, hh):
    from apps.users.site_views import create_booking
    from .models import WaMessage
    slot = "%02d:00" % hh
    appt, err = create_booking(
        clinic, name=patient.full_name, phone=patient.phone or str(chat_id), doctor_id=doctor_id,
        date_str=day.isoformat(), slot=slot, branch_id=branch_id, patient=patient, channel="telegram")
    if err:
        if err[1] == 409:
            _edit(chat_id, message_id, t("slot_taken", lang), token,
                  buttons=[[(t("btn_back", lang), "pbt:%s:%s:%s" % (branch_id, doctor_id, day.strftime("%Y%m%d")))]])
        else:
            _edit(chat_id, message_id, t("book_error", lang, error=_esc(err[0])), token)
        return
    doc_name = appt.doctor.name if appt.doctor_id else "—"
    _edit(chat_id, message_id, t("booked", lang, doctor=_esc(doc_name), date=day.strftime("%d.%m.%Y"),
                                 time=slot, branch=_esc(appt.branch.name if appt.branch_id else "—")), token)
    # в ленту «Мессенджеры» — без отдельного уведомления (create_booking уже уведомил персонал)
    WaMessage.objects.create(patient=patient, clinic=clinic, direction="in", channel="tg",
                             phone=str(chat_id), read=True,
                             body="📝 Записался(ась) через бота: %s %s, врач %s"
                                  % (day.strftime("%d.%m.%Y"), slot, doc_name))


# ── Сообщения ────────────────────────────────────────────────────────────

def handle_message(clinic, msg, token, cs):
    """Личное сообщение пациента (или ещё не привязанного человека)."""
    import re
    from apps.patients.models import Patient
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")
    chat = get_chat(clinic, chat_id)
    lang = chat.lang if chat.lang in LANGS else "ru"
    patient = Patient.objects.filter(telegram_chat_id=chat_id).first()

    if text.startswith("/start"):
        _set_state(chat)
        if not chat.lang:
            ask_language(chat_id, token)
        elif patient is not None:
            send_menu(chat_id, lang, token,
                      text=t("welcome_back", lang, name=_esc(patient.first_name or patient.full_name)))
        else:
            ask_contact(chat_id, clinic, lang, token)
        return True

    if text in labels("btn_lang") or text.startswith("/lang"):
        ask_language(chat_id, token)
        return True

    if contact:
        link_by_phone(clinic, chat, contact.get("phone_number") or "", token)
        return True

    if text in labels("btn_book") or text.startswith("/book"):
        if patient is None:
            _send(chat_id, t("need_phone", lang), token)
            return True
        _log_in(patient, chat_id, text)
        start_booking(clinic, chat_id, lang, token)
        return True

    if text in labels("btn_debt") | labels("btn_visits"):
        if patient is None:
            _send(chat_id, t("need_phone", lang), token)
            return True
        _log_in(patient, chat_id, text)
        if text in labels("btn_debt"):
            cur = cs.currency_label if cs else "сом"
            if patient.debt > 0:
                _send(chat_id, t("debt_yes", lang, amount="%.0f" % patient.debt, cur=_esc(cur)), token)
            else:
                _send(chat_id, t("debt_no", lang), token)
        else:
            _send_visits(patient, chat_id, lang, token)
        return True

    if chat.state == "await_name" and patient is None and text and not text.startswith("/"):
        register_patient(clinic, chat, text, token)
        return True

    # Номер напечатан текстом (не через кнопку «Поделиться»)
    if text and not text.startswith("/") and patient is None:
        digits = re.sub(r"\D", "", text)
        if 9 <= len(digits) <= 15 and re.fullmatch(r"[\d\s()+\-]+", text):
            link_by_phone(clinic, chat, text, token)
            return True
    return False


def _send_visits(patient, chat_id, lang, token):
    from apps.treatments.models import Treatment
    from apps.appointments.models import Appointment
    upcoming = list(Appointment.objects.filter(
        patient=patient, start_at__gte=timezone.now(),
        status__in=[Appointment.STATUS_SCHEDULED, Appointment.STATUS_CONFIRMED])
        .select_related("doctor").order_by("start_at")[:5])
    if upcoming:
        lines = [t("upcoming", lang)]
        for a in upcoming:
            st = timezone.localtime(a.start_at)
            lines.append("• %s %s — %s" % (st.strftime("%d.%m.%Y"), st.strftime("%H:%M"),
                                          _esc(a.doctor.name if a.doctor_id else "—")))
        _send(chat_id, "\n".join(lines), token)
    treatments = list(Treatment.objects.filter(patient=patient)
                      .exclude(status=Treatment.STATUS_DRAFT).order_by("-created_at")[:10])
    if not treatments:
        if not upcoming:
            _send(chat_id, t("visits_none", lang), token)
        return
    buttons = [[("%s — %s" % (tr.created_at.strftime("%d.%m.%Y"), tr.get_status_display()),
                 "my_treatment:%s" % tr.pk)] for tr in treatments]
    _send(chat_id, t("visits_list", lang, n=len(treatments)), token, buttons=buttons)
