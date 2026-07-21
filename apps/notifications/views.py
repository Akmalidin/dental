import json
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import Notification, PushSubscription


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _user_notifications(request):
    """Уведомления пользователя в рамках текущей клиники (изоляция между клиниками)."""
    from apps.tenancy import get_current_clinic
    qs = Notification.objects.filter(user=request.user)
    clinic = get_current_clinic()
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return qs


@login_required
def notification_list(request):
    from django.utils import timezone
    base = _user_notifications(request)
    counts = {
        "all": base.count(),
        "unread": base.filter(is_read=False).count(),
        "appointment": base.filter(type__in=["appointment", "reminder"]).count(),
        "payment": base.filter(type="payment").count(),
        "wa": base.filter(type="wa").count(),
    }
    filt = request.GET.get("type", "all")
    qs = base
    if filt == "unread":
        qs = qs.filter(is_read=False)
    elif filt == "appointment":
        qs = qs.filter(type__in=["appointment", "reminder"])
    elif filt == "payment":
        qs = qs.filter(type="payment")
    elif filt == "wa":
        qs = qs.filter(type="wa")

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    groups = []
    cur_label, cur_items = None, None
    for n in qs.select_related("actor"):
        d = timezone.localtime(n.created_at).date()
        if d == today:
            label = "Сегодня"
        elif d == yesterday:
            label = "Вчера"
        else:
            label = "Ранее"
        if label != cur_label:
            cur_label, cur_items = label, []
            groups.append((label, cur_items))
        cur_items.append(n)

    return render(request, "notifications/list.html", {
        "groups": groups, "counts": counts, "filt": filt,
    })


@csrf_exempt
@login_required
def push_subscribe(request):
    """Сохранить подписку устройства на web push."""
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    try:
        data = json.loads(request.body)
        sub = data.get("subscription") or data
        endpoint = sub["endpoint"]
        keys = sub.get("keys", {})
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": keys.get("p256dh", ""),
                "auth": keys.get("auth", ""),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300],
            },
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


def web_manifest(request):
    """PWA-манифест (установка иконкой, нужно для iOS web push)."""
    name = "SADAF"
    try:
        from apps.settings_clinic.models import ClinicSettings
        name = ClinicSettings.get().name or "SADAF"
    except Exception:
        pass
    manifest = {
        "name": name + " — Клиника",
        "short_name": name,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F8FAFC",
        "theme_color": "#6366F1",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    return JsonResponse(manifest)


def service_worker(request):
    """Service Worker (должен отдаваться из корня сайта для широкого scope)."""
    js = """
self.addEventListener('push', function(event) {
  let d = {};
  try { d = event.data.json(); } catch(e) { d = { title: 'SADAF', body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(d.title || 'SADAF', {
    body: d.body || '',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: { url: d.url || '/' },
    vibrate: [100, 50, 100],
  }));
});
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list) {
    for (const c of list) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
"""
    return HttpResponse(js, content_type="application/javascript")


@login_required
def notification_poll(request):
    """JSON для браузерных уведомлений: счётчик непрочитанных + последние."""
    qs = _user_notifications(request).filter(is_read=False)
    items = [
        {"id": n.pk, "title": n.title, "body": n.body, "link": n.link}
        for n in qs[:5]
    ]
    return JsonResponse({"count": qs.count(), "items": items})


@login_required
def notification_open(request, pk):
    """Открыть уведомление: пометить прочитанным и перейти по ссылке."""
    n = _user_notifications(request).filter(pk=pk).first()
    if not n:
        return redirect("notification_list")
    n.is_read = True
    n.save(update_fields=["is_read"])
    return redirect(n.link or "notification_list")


@login_required
def mark_read(request, pk):
    _user_notifications(request).filter(pk=pk).update(is_read=True)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")


@login_required
def mark_all_read(request):
    _user_notifications(request).filter(is_read=False).update(is_read=True)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")


@login_required
def message_templates(request):
    """Управление редактируемыми шаблонами WhatsApp-сообщений."""
    from django.contrib import messages
    from .models import MessageTemplate
    from .whatsapp import seed_default_templates
    if request.method == "POST":
        pk = request.POST.get("id")
        name = (request.POST.get("name") or "").strip()
        kind = request.POST.get("kind") or "manual"
        body = (request.POST.get("body") or "").strip()
        if name and body:
            if pk:
                t = MessageTemplate.objects.filter(pk=pk).first()
                if t:
                    t.name, t.kind, t.body = name, kind, body
                    t.is_active = bool(request.POST.get("is_active"))
                    t.save()
            else:
                MessageTemplate.objects.create(name=name, kind=kind, body=body)
            messages.success(request, "Шаблон сохранён")
        return redirect("message_templates")
    if not MessageTemplate.objects.exists():
        try:
            seed_default_templates()
        except Exception:
            pass
    tpls = list(MessageTemplate.objects.all())
    return render(request, "notifications/templates.html", {
        "templates": tpls,
        "templates_json": [{"id": t.pk, "name": t.name, "kind": t.kind,
                            "body": t.body, "is_active": t.is_active} for t in tpls],
        "kinds": MessageTemplate.KIND_CHOICES,
    })


@login_required
def message_template_delete(request, pk):
    from django.contrib import messages
    from .models import MessageTemplate
    if request.method == "POST":
        MessageTemplate.objects.filter(pk=pk).delete()
        messages.success(request, "Шаблон удалён")
    return redirect("message_templates")


@csrf_exempt
def wa_webhook(request):
    """Webhook Green-API: входящие WhatsApp-сообщения → WaMessage(direction=in)."""
    from django.conf import settings as dj
    if request.method != "POST":
        return HttpResponse(status=405)
    key = getattr(dj, "GREENAPI_WEBHOOK_KEY", "")
    if key and request.GET.get("key") != key:
        return HttpResponse("forbidden", status=403)
    try:
        data = json.loads(request.body or b"{}")
    except Exception:
        return HttpResponse("bad", status=400)
    if data.get("typeWebhook") == "incomingMessageReceived":
        md = data.get("messageData", {}) or {}
        tm = md.get("typeMessage")
        text = ""
        if tm == "textMessage":
            text = (md.get("textMessageData") or {}).get("textMessage", "")
        elif tm in ("extendedTextMessage", "quotedMessage"):
            text = (md.get("extendedTextMessageData") or {}).get("text", "")
        sender = data.get("senderData") or {}
        chat_id = sender.get("chatId", "") or ""
        # Группа: автоматически регистрируем (для выбора Директором), уведомления по умолчанию выкл.
        if chat_id.endswith("@g.us"):
            try:
                from apps.notifications.models import WaGroup
                from apps.patients.models import Patient
                from apps.tenancy import unscoped
                import re as _re
                gname = sender.get("chatName") or ""
                # клиника группы: по номеру отправителя, иначе единственная клиника
                cl = None
                sp = (sender.get("sender") or "").split("@")[0]
                tail = _re.sub(r"\D", "", sp)[-9:]
                with unscoped():
                    if tail:
                        p = Patient.all_objects.filter(phone__icontains=tail).order_by("-id").first()
                        cl = p.clinic if p else None
                    if cl is None:
                        from apps.users.models import Clinic
                        cs = list(Clinic.objects.all()[:2])
                        cl = cs[0] if len(cs) == 1 else None
                    if cl is not None:
                        g, created = WaGroup.all_clinics.get_or_create(
                            clinic=cl, chat_id=chat_id,
                            defaults={"name": gname, "notify": False})
                        if not created and gname and g.name != gname:
                            g.name = gname
                            g.save(update_fields=["name"])
            except Exception:
                pass
            return JsonResponse({"ok": True})
        phone = chat_id.split("@")[0]
        if text and phone:
            import re
            from apps.patients.models import Patient
            from apps.notifications.models import WaMessage
            from apps.tenancy import unscoped
            digits = re.sub(r"\D", "", phone)
            tail = digits[-9:] if len(digits) >= 9 else digits
            with unscoped():
                patient = (Patient.all_objects.filter(phone__icontains=tail, is_deleted=False)
                           .order_by("-id").first() if tail else None)
                m = WaMessage(patient=patient, direction="in", phone=phone, body=text, read=False)
                if patient is not None:
                    m.clinic = patient.clinic
                m.save()
            # уведомление персоналу клиники о входящем сообщении
            if patient is not None:
                try:
                    from apps.tenancy import set_current_clinic
                    from apps.users.models import User as U, Role
                    from django.db.models import Q
                    set_current_clinic(patient.clinic)
                    recipients = U.objects.filter(clinic=patient.clinic, is_active=True).filter(
                        Q(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN])
                        | Q(roles__name__in=[Role.ADMIN, Role.ADMIN_MAIN]))
                    if patient.primary_doctor_id:
                        recipients = recipients | U.objects.filter(pk=patient.primary_doctor_id)
                    snippet = (text[:80] + "…") if len(text) > 80 else text
                    link = "/patients/%s/notify/" % patient.pk
                    from django.utils import timezone as _tz
                    for u in recipients.distinct():
                        # компактно: одно уведомление на пациента — обновляем существующее непрочитанное
                        existing = Notification.objects.filter(
                            user=u, link=link, type="wa", is_read=False).first()
                        if existing:
                            Notification.objects.filter(pk=existing.pk).update(
                                body="%s: %s" % (patient.full_name, snippet), created_at=_tz.now())
                        else:
                            Notification.send(u, "💬 WhatsApp",
                                              "%s: %s" % (patient.full_name, snippet),
                                              type="wa", link=link)
                except Exception:
                    pass
    return JsonResponse({"ok": True})


def _wa_staff_ok(user):
    return user.is_superadmin or user.is_admin


@login_required
def wa_inbox(request):
    """Инбокс WhatsApp-чатов: последние переписки с пациентами."""
    if not _wa_staff_ok(request.user):
        return redirect("/")
    from .models import WaMessage
    from apps.tenancy import get_current_clinic
    base = WaMessage.all_clinics.exclude(patient__isnull=True)
    clinic = get_current_clinic()
    if clinic is not None:
        base = base.filter(clinic=clinic)
    convos = {}
    for m in base.select_related("patient").order_by("-id")[:2000]:
        c = convos.get(m.patient_id)
        if c is None:
            c = convos[m.patient_id] = {"patient": m.patient, "last": m, "unread": 0}
        if m.direction == "in" and not m.read:
            c["unread"] += 1
    rows = sorted(convos.values(), key=lambda c: c["last"].created_at, reverse=True)
    return render(request, "notifications/wa_inbox.html", {
        "rows": rows, "total_unread": sum(c["unread"] for c in rows),
    })


def _broadcast_patients(audience):
    from apps.patients.models import Patient
    from apps.appointments.models import Appointment
    from django.utils import timezone
    qs = Patient.objects.exclude(phone="")
    if audience == "debtors":
        return qs.filter(balance__lt=0)
    if audience == "upcoming":
        pids = (Appointment.objects.filter(start_at__gte=timezone.now())
                .exclude(status__in=["cancelled", "no_show"])
                .values_list("patient_id", flat=True).distinct())
        return qs.filter(pk__in=pids)
    return qs


@login_required
def wa_broadcast(request):
    """Массовая WhatsApp-рассылка по аудитории (все / должники / с приёмами)."""
    from django.contrib import messages
    if not _wa_staff_ok(request.user):
        return redirect("/")
    from .models import MessageTemplate, WaMessage
    from .whatsapp import wa_send_text, wa_enabled, render_message
    from apps.appointments.models import Appointment
    from django.utils import timezone

    if request.method == "POST":
        audience = request.POST.get("audience", "all")
        tpl_id = request.POST.get("template")
        text = (request.POST.get("text") or "").strip()
        if tpl_id and not text:
            t = MessageTemplate.objects.filter(pk=tpl_id).first()
            text = t.body if t else ""
        if not text:
            messages.error(request, "Выберите шаблон или введите текст")
            return redirect("wa_broadcast")
        if not wa_enabled():
            messages.error(request, "WhatsApp не настроен")
            return redirect("wa_broadcast")
        sent = failed = 0
        for p in list(_broadcast_patients(audience).select_related()[:500]):
            if not p.phone:
                continue
            appt = (Appointment.objects.filter(patient=p, start_at__gte=timezone.now())
                    .exclude(status__in=["cancelled", "no_show"]).order_by("start_at").first())
            msg = render_message(text, patient=p, appt=appt)
            ok = wa_send_text(p.phone, msg)
            WaMessage.objects.create(patient=p, direction="out", phone=p.phone,
                                     body=msg, sent_by=request.user, ok=ok)
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        messages.success(request, "Рассылка завершена. Отправлено: %s, ошибок: %s" % (sent, failed))
        return redirect("wa_broadcast")

    from apps.settings_clinic.models import ClinicSettings
    return render(request, "notifications/wa_broadcast.html", {
        "templates": MessageTemplate.objects.filter(is_active=True),
        "wa_enabled": wa_enabled(),
        "count_all": _broadcast_patients("all").count(),
        "count_debtors": _broadcast_patients("debtors").count(),
        "count_upcoming": _broadcast_patients("upcoming").count(),
        "cs": ClinicSettings.get(),
    })


@login_required
def wa_settings(request):
    """Сохранить настройки авто-напоминаний текущей клиники."""
    from django.contrib import messages
    if not _wa_staff_ok(request.user):
        return redirect("/")
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()
    cs.wa_remind_day = bool(request.POST.get("wa_remind_day"))
    cs.wa_remind_hour = bool(request.POST.get("wa_remind_hour"))
    try:
        cs.wa_remind_debt_days = max(0, int(request.POST.get("wa_remind_debt_days") or 0))
    except (TypeError, ValueError):
        cs.wa_remind_debt_days = 0
    cs.save(update_fields=["wa_remind_day", "wa_remind_hour", "wa_remind_debt_days"])
    messages.success(request, "Настройки напоминаний сохранены")
    return redirect("wa_broadcast")


@login_required
def wa_groups(request):
    """Управление WhatsApp-группами клиники (Директор/Администратор):
    в какие группы слать уведомления о записях/отменах."""
    from django.contrib import messages
    if not _wa_staff_ok(request.user):
        return redirect("/")
    from .models import WaGroup

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            chat_id = (request.POST.get("chat_id") or "").strip()
            name = (request.POST.get("name") or "").strip()
            # допускаем ввод только цифр id — дополним до @g.us
            if chat_id and "@" not in chat_id:
                digits = "".join(ch for ch in chat_id if ch.isdigit())
                if digits:
                    chat_id = digits + "@g.us"
            if not chat_id.endswith("@g.us"):
                messages.error(request, "Укажите корректный ID группы (…@g.us)")
            else:
                WaGroup.objects.get_or_create(chat_id=chat_id, defaults={"name": name, "notify": True})
                messages.success(request, "Группа добавлена")
        elif action == "toggle":
            g = WaGroup.objects.filter(pk=request.POST.get("id")).first()
            if g:
                g.notify = not g.notify
                g.save(update_fields=["notify"])
        elif action == "delete":
            WaGroup.objects.filter(pk=request.POST.get("id")).delete()
            messages.success(request, "Группа удалена")
        return redirect("wa_groups")

    from .whatsapp import wa_enabled
    groups = list(WaGroup.objects.all())
    return render(request, "notifications/wa_groups.html", {
        "groups": groups, "wa_enabled": wa_enabled(),
    })


@login_required
def wa_connect(request):
    """Подключение WhatsApp клиники: свой инстанс/токен/номер + переключатель + QR.
    Только Директор/Администратор."""
    from django.contrib import messages
    if not _wa_staff_ok(request.user):
        return redirect("/")
    from apps.settings_clinic.models import ClinicSettings
    cs = ClinicSettings.get()

    if request.method == "POST":
        cs.wa_enabled = bool(request.POST.get("wa_enabled"))
        cs.wa_id_instance = (request.POST.get("wa_id_instance") or "").strip()
        cs.wa_token = (request.POST.get("wa_token") or "").strip()
        cs.wa_api_url = (request.POST.get("wa_api_url") or "").strip()
        cs.wa_phone = (request.POST.get("wa_phone") or "").strip()
        cs.save(update_fields=["wa_enabled", "wa_id_instance", "wa_token", "wa_api_url", "wa_phone"])
        messages.success(request, "Настройки WhatsApp сохранены")
        return redirect("wa_connect")

    from .whatsapp import wa_state, wa_qr, wa_enabled
    state = wa_state()
    qr_type, qr_msg = ("", "")
    if state and state != "authorized":
        qr_type, qr_msg = wa_qr()
    return render(request, "notifications/wa_connect.html", {
        "cs": cs,
        "wa_enabled": wa_enabled(),
        "has_keys": bool((cs.wa_id_instance or "").strip() and (cs.wa_token or "").strip()),
        "state": state,
        "qr_type": qr_type,
        "qr_b64": qr_msg if qr_type == "qrCode" else "",
    })


# ─── Telegram ────────────────────────────────────────────────────────────

def _tg_staff_ok(user):
    return user.is_superadmin or user.is_admin


@csrf_exempt
def tg_webhook(request, clinic_slug):
    """Webhook Telegram Bot API — свой URL на каждую клинику (её слаг зашит в
    адрес, который был передан в setWebhook при подключении бота)."""
    if request.method != "POST":
        return HttpResponse(status=405)
    from apps.users.models import Clinic
    from apps.tenancy import set_current_clinic
    clinic = Clinic.objects.filter(slug=clinic_slug, is_active=True).first()
    if clinic is None:
        return HttpResponse(status=404)
    set_current_clinic(clinic)

    try:
        update = json.loads(request.body or b"{}")
    except Exception:
        return HttpResponse(status=400)

    from apps.settings_clinic.models import ClinicSettings
    from .telegram import (
        tg_send_text, tg_send_contact_request, tg_edit_message, tg_answer_callback,
    )
    cs = ClinicSettings.get()
    token = (cs.telegram_bot_token or "").strip()
    if not token:
        return JsonResponse({"ok": True})

    # ── Нажатие инлайн-кнопки (подтверждение/отмена записи и т.п.) ──
    cq = update.get("callback_query")
    if cq:
        _handle_tg_callback(cq, token)
        return JsonResponse({"ok": True})

    msg = update.get("message")
    if not msg:
        return JsonResponse({"ok": True})

    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    contact = msg.get("contact")

    # ── /start — приветствие + запрос номера для привязки к карточке пациента ──
    if text.startswith("/start"):
        tg_send_contact_request(
            chat_id,
            "👋 Здравствуйте! Это бот клиники «%s».\n\n"
            "Чтобы получать напоминания о приёмах и другие уведомления, "
            "поделитесь, пожалуйста, номером телефона (кнопка ниже)." % clinic.name,
            token=token,
        )
        return JsonResponse({"ok": True})

    # ── Поделился номером — привязываем chat_id к карточке пациента ──
    if contact:
        from apps.patients.models import Patient, normalize_phone
        phone = contact.get("phone_number") or ""
        pnorm = normalize_phone(phone)
        patient = Patient.objects.filter(phone_norm=pnorm).first() if pnorm else None
        if patient is not None:
            patient.telegram_chat_id = chat_id
            patient.save(update_fields=["telegram_chat_id"])
            name = (patient.first_name or "").strip() or "!"
            tg_send_text(chat_id, "✅ Готово, %s Теперь буду присылать сюда напоминания о приёмах." % name)
        else:
            tg_send_text(chat_id, "Не нашли карточку с таким номером в базе клиники. Обратитесь на ресепшене.")
        return JsonResponse({"ok": True})

    # ── Обычное входящее сообщение — логируем для инбокса + уведомляем персонал ──
    if text:
        from apps.patients.models import Patient
        from .models import WaMessage
        patient = Patient.objects.filter(telegram_chat_id=chat_id).first()
        m = WaMessage(patient=patient, direction="in", channel="tg", phone=str(chat_id), body=text, read=False)
        if patient is not None:
            m.clinic = patient.clinic
        m.save()
        if patient is not None:
            try:
                from apps.users.models import User as U, Role
                from django.db.models import Q
                recipients = U.objects.filter(clinic=patient.clinic, is_active=True).filter(
                    Q(role__name__in=[Role.ADMIN, Role.ADMIN_MAIN])
                    | Q(roles__name__in=[Role.ADMIN, Role.ADMIN_MAIN]))
                if patient.primary_doctor_id:
                    recipients = recipients | U.objects.filter(pk=patient.primary_doctor_id)
                snippet = (text[:80] + "…") if len(text) > 80 else text
                link = "/patients/%s/notify/" % patient.pk
                from django.utils import timezone as _tz
                for u in recipients.distinct():
                    existing = Notification.objects.filter(
                        user=u, link=link, type="wa", is_read=False).first()
                    if existing:
                        Notification.objects.filter(pk=existing.pk).update(
                            body="✈️ Telegram — %s: %s" % (patient.full_name, snippet), created_at=_tz.now())
                    else:
                        Notification.send(u, "✈️ Telegram", "%s: %s" % (patient.full_name, snippet),
                                          type="wa", link=link)
            except Exception:
                pass
    return JsonResponse({"ok": True})


def _handle_tg_callback(cq, token):
    """Обработка нажатия инлайн-кнопки: сейчас — подтверждение/отмена записи
    пациентом прямо из Telegram (см. notify_appointment_created)."""
    from .telegram import tg_edit_message, tg_answer_callback
    data = cq.get("data", "") or ""
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    cq_id = cq.get("id")

    if ":" not in data:
        tg_answer_callback(cq_id, token=token)
        return
    action, _, appt_id = data.partition(":")
    try:
        from apps.appointments.models import Appointment
        appt = Appointment.objects.filter(pk=int(appt_id)).first()
    except (ValueError, TypeError):
        appt = None
    if appt is None:
        tg_answer_callback(cq_id, "Запись не найдена", token=token)
        return

    if action == "appt_confirm":
        if appt.status in ("scheduled",):
            appt.status = "confirmed"
            appt.save(update_fields=["status"])
        tg_edit_message(chat_id, message_id,
                        "✅ <b>Запись подтверждена</b>\nЖдём вас %s в %s" % (
                            appt.start_at.strftime("%d.%m.%Y"), appt.start_at.strftime("%H:%M")),
                        token=token)
        tg_answer_callback(cq_id, "Запись подтверждена ✅", token=token)
    elif action == "appt_cancel":
        if appt.status not in ("completed", "cancelled"):
            appt.status = "cancelled"
            appt.save(update_fields=["status"])
        tg_edit_message(chat_id, message_id, "❌ <b>Запись отменена</b>", token=token)
        tg_answer_callback(cq_id, "Запись отменена", token=token)
    else:
        tg_answer_callback(cq_id, token=token)


@login_required
def tg_connect(request):
    """Подключение Telegram-бота клиники: токен (создаётся у @BotFather) + webhook.
    Только Директор/Администратор."""
    from django.contrib import messages
    if not _tg_staff_ok(request.user):
        return redirect("/")
    from apps.settings_clinic.models import ClinicSettings
    from apps.tenancy import get_current_clinic
    from .telegram import tg_set_webhook, tg_get_me, tg_get_webhook_info
    cs = ClinicSettings.get()
    clinic = get_current_clinic()

    if request.method == "POST":
        cs.telegram_enabled = bool(request.POST.get("telegram_enabled"))
        cs.telegram_bot_token = (request.POST.get("telegram_bot_token") or "").strip()
        cs.save(update_fields=["telegram_enabled", "telegram_bot_token"])
        if cs.telegram_bot_token and clinic is not None:
            me = tg_get_me(cs.telegram_bot_token)
            if me.get("ok"):
                cs.telegram_bot_username = me["result"].get("username", "")
                cs.save(update_fields=["telegram_bot_username"])
                webhook_url = request.build_absolute_uri(
                    "/notifications/tg-webhook/%s/" % clinic.slug)
                res = tg_set_webhook(cs.telegram_bot_token, webhook_url)
                if res.get("ok"):
                    messages.success(request, "Бот подключён: @%s" % cs.telegram_bot_username)
                else:
                    messages.warning(request, "Токен сохранён, но не удалось настроить webhook: %s" % res.get("description", ""))
            else:
                messages.error(request, "Не удалось проверить токен — убедитесь, что он верный (от @BotFather)")
        else:
            messages.success(request, "Настройки Telegram сохранены")
        return redirect("tg_connect")

    webhook_info = {}
    if cs.telegram_bot_token:
        webhook_info = tg_get_webhook_info(cs.telegram_bot_token).get("result", {})
    return render(request, "notifications/tg_connect.html", {
        "cs": cs,
        "webhook_info": webhook_info,
        "bot_link": ("https://t.me/%s" % cs.telegram_bot_username) if cs.telegram_bot_username else "",
    })


@login_required
def tg_inbox(request):
    """Инбокс Telegram-чатов: последние переписки с пациентами (тот же UI, что WhatsApp)."""
    if not _wa_staff_ok(request.user):
        return redirect("/")
    from .models import WaMessage
    from apps.tenancy import get_current_clinic
    base = WaMessage.all_clinics.filter(channel="tg").exclude(patient__isnull=True)
    clinic = get_current_clinic()
    if clinic is not None:
        base = base.filter(clinic=clinic)
    convos = {}
    for m in base.select_related("patient").order_by("-id")[:2000]:
        c = convos.get(m.patient_id)
        if c is None:
            c = convos[m.patient_id] = {"patient": m.patient, "last": m, "unread": 0}
        if m.direction == "in" and not m.read:
            c["unread"] += 1
    rows = sorted(convos.values(), key=lambda c: c["last"].created_at, reverse=True)
    return render(request, "notifications/tg_inbox.html", {
        "rows": rows, "total_unread": sum(c["unread"] for c in rows),
    })


@login_required
def tg_broadcast(request):
    """Массовая Telegram-рассылка по аудитории (все / должники / с приёмами) —
    только пациентам, у кого уже привязан telegram_chat_id."""
    from django.contrib import messages
    if not _tg_staff_ok(request.user):
        return redirect("/")
    from .models import MessageTemplate, WaMessage
    from .telegram import tg_send_text, tg_enabled
    from .whatsapp import render_message
    from apps.appointments.models import Appointment
    from django.utils import timezone

    if request.method == "POST":
        audience = request.POST.get("audience", "all")
        tpl_id = request.POST.get("template")
        text = (request.POST.get("text") or "").strip()
        if tpl_id and not text:
            t = MessageTemplate.objects.filter(pk=tpl_id).first()
            text = t.body if t else ""
        if not text:
            messages.error(request, "Выберите шаблон или введите текст")
            return redirect("tg_broadcast")
        if not tg_enabled():
            messages.error(request, "Telegram не настроен")
            return redirect("tg_broadcast")
        sent = failed = 0
        qs = _broadcast_patients(audience).exclude(telegram_chat_id__isnull=True)
        for p in list(qs.select_related()[:500]):
            appt = (Appointment.objects.filter(patient=p, start_at__gte=timezone.now())
                    .exclude(status__in=["cancelled", "no_show"]).order_by("start_at").first())
            msg = render_message(text, patient=p, appt=appt)
            ok = tg_send_text(p.telegram_chat_id, msg)
            WaMessage.objects.create(patient=p, direction="out", channel="tg", phone=str(p.telegram_chat_id),
                                     body=msg, sent_by=request.user, ok=ok)
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        messages.success(request, "Рассылка завершена. Отправлено: %s, ошибок: %s" % (sent, failed))
        return redirect("tg_broadcast")

    from apps.settings_clinic.models import ClinicSettings
    linked_count = _broadcast_patients("all").exclude(telegram_chat_id__isnull=True).count()
    return render(request, "notifications/tg_broadcast.html", {
        "templates": MessageTemplate.objects.filter(is_active=True),
        "tg_enabled": tg_enabled(),
        "count_all": _broadcast_patients("all").count(),
        "count_debtors": _broadcast_patients("debtors").count(),
        "count_upcoming": _broadcast_patients("upcoming").count(),
        "linked_count": linked_count,
        "cs": ClinicSettings.get(),
    })
