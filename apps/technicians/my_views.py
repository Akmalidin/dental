"""Кабинет зубного техника (/new/lab/my/).

Техник может работать сразу с несколькими клиниками:
- клиники в ODONTIS — подключают его по коду техника (TechnicianCode): у каждой
  своя запись Technician с user=этот логин, заказы врачи отправляют сами;
- клиники вне ODONTIS — техник заводит их и их заказы сам (ExternalClinic,
  ExternalOrder), это его личные записи, клиники их не видят.
В кабинете — переключатель клиник, общая доска заказов, выплаты по клиникам.
Всё ищется по связке «заказ → техник → этот логин» во всех клиниках
(all_clinics), поэтому чужие заказы недоступны."""
import os
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (ExternalClinic, ExternalOrder, ExternalOrderFile, Technician, TechnicianCode,
                     TechnicianOrderFile, TechnicianTask)
from .services import TECH_MOVES, add_comment, apply_status, messages_json, request_deadline

UPLOAD_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".pdf", ".stl", ".ply", ".obj", ".zip"}
UPLOAD_MAX = 25 * 1024 * 1024
BOARD = [TechnicianTask.STATUS_TRANSFERRED, TechnicianTask.STATUS_IN_PROGRESS, TechnicianTask.STATUS_CORRECTION,
         TechnicianTask.STATUS_READY, TechnicianTask.STATUS_FITTING, TechnicianTask.STATUS_INSTALLED]
STATUS_LABEL = dict(TechnicianTask.STATUS_CHOICES)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _norm(s):
    return " ".join((s or "").lower().replace("ё", "е").split())


def _clean(v, n=200):
    return (v or "").replace("<", "").replace(">", "").strip()[:n]


def technicians_for(user):
    """Все записи «техник» этого логина во всех клиниках. Если в своей
    клинике ещё не привязан, а там ровно один свободный техник с тем же
    именем — привязываем сам."""
    if user.has_role("technician") and not Technician.objects.filter(user=user).exists():
        same = [t for t in Technician.objects.filter(user__isnull=True, is_active=True)
                if _norm(t.name) == _norm(user.name)]
        if len(same) == 1:
            same[0].user = user
            same[0].save(update_fields=["user"])
    return list(Technician.all_clinics.filter(user=user, is_active=True).select_related("clinic"))


def technician_code(user):
    obj = TechnicianCode.objects.filter(user=user).first()
    if obj is None:
        obj = _new_code(user)
    return obj.code


def _new_code(user):
    TechnicianCode.objects.filter(user=user).delete()
    while True:
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        code = f"T-{raw[:4]}-{raw[4:]}"
        if not TechnicianCode.objects.filter(code=code).exists():
            return TechnicianCode.objects.create(user=user, code=code)


def _d(v):
    return v.strftime("%d.%m.%Y") if v else ""


def _files(qs):
    from apps.users.media_views import signed_url
    return [{"id": f.pk, "name": f.name or os.path.basename(f.file.name), "url": signed_url(f.file.name),
             "isImage": f.is_image} for f in qs]


def _clinic_name(tech):
    return tech.clinic.name if tech.clinic_id else "Клиника"


def _order_json(t):
    p = t.patient
    doctor = t.treatment.doctor if t.treatment_id and t.treatment.doctor_id else None
    return {
        "key": f"c{t.pk}", "id": t.pk, "src": "clinic", "code": f"#L-{t.pk:04d}",
        "clinicKey": f"c{t.clinic_id}", "clinicName": _clinic_name(t.technician),
        "status": t.status, "statusLabel": t.get_status_display(),
        "patient": f"{p.last_name} {p.first_name}".strip() if p else "—",
        "doctor": doctor.name if doctor else "",
        "service": t.service.name if t.service_id else "", "tooth": t.tooth_number, "material": t.material,
        "color": t.vita_color, "comment": t.doctor_comment,
        "transferred": _d(t.transferred_at), "expectedReady": _d(t.expected_ready),
        "expectedIso": t.expected_ready.isoformat() if t.expected_ready else "",
        "readyAt": _d(t.ready_at), "installedAt": _d(t.installed_at),
        "overdue": t.is_overdue, "amount": float(t.amount), "paid": t.paid,
        "moves": list(TECH_MOVES.get(t.status, ())),
        "files": _files(t.files.all()),
        "events": [{"label": e.get_status_display(), "at": timezone.localtime(e.at).strftime("%d.%m %H:%M"),
                    "by": e.by.name if e.by_id else ""} for e in t.events.all()],
        "messages": messages_json(t),
        "canRequestDeadline": t.status in TechnicianTask.OPEN_STATUSES,
    }


def _ext_json(o):
    return {
        "key": f"e{o.pk}", "id": o.pk, "src": "ext", "code": f"#E-{o.pk:04d}",
        "clinicKey": f"x{o.clinic_id}", "clinicName": o.clinic.name, "clinicId": o.clinic_id,
        "status": o.status, "statusLabel": STATUS_LABEL.get(o.status, o.status),
        "patient": o.patient_name or "—", "doctor": o.doctor_name, "service": o.work, "tooth": o.tooth_number,
        "material": o.material, "color": o.vita_color, "comment": o.comment,
        "transferred": _d(o.transferred_at), "transferredIso": o.transferred_at.isoformat() if o.transferred_at else "",
        "expectedReady": _d(o.expected_ready), "expectedIso": o.expected_ready.isoformat() if o.expected_ready else "",
        "readyAt": _d(o.ready_at), "installedAt": _d(o.installed_at),
        "overdue": o.is_overdue, "amount": float(o.amount), "paid": o.paid, "paidAt": _d(o.paid_at),
        "moves": [s for s in BOARD + [TechnicianTask.STATUS_CANCELLED] if s != o.status],
        "files": _files(o.files.all()), "events": [],
    }


def _sum(qs):
    return float(qs.aggregate(x=Sum("amount"))["x"] or Decimal(0))


def _pay_row(key, name, qs, today):
    month = today.replace(day=1)
    installed = qs.filter(status=TechnicianTask.STATUS_INSTALLED)
    return {"key": key, "name": name,
            "earnedMonth": _sum(installed.filter(installed_at__gte=month)),
            "unpaid": _sum(installed.filter(paid=False)),
            "paidMonth": _sum(qs.filter(paid=True, paid_at__gte=month)),
            "inWork": _sum(qs.filter(status__in=TechnicianTask.OPEN_STATUSES))}


def my_data(user):
    today = timezone.localdate()
    recent = today - timedelta(days=30)
    techs = technicians_for(user)
    tasks = (TechnicianTask.all_clinics.filter(technician__in=techs, status__in=BOARD)
             .exclude(status=TechnicianTask.STATUS_INSTALLED, installed_at__lt=recent)
             .select_related("patient", "service", "treatment__doctor", "technician__clinic")
             .prefetch_related("files", "events__by", "messages__author", "messages__decided_by")
             .order_by("expected_ready", "created_at"))
    ext = (ExternalOrder.objects.filter(owner=user, status__in=BOARD)
           .exclude(status=TechnicianTask.STATUS_INSTALLED, installed_at__lt=recent)
           .select_related("clinic").prefetch_related("files").order_by("expected_ready", "created_at"))
    ext_clinics = list(ExternalClinic.objects.filter(owner=user, is_active=True))
    orders = [_order_json(t) for t in tasks[:300]] + [_ext_json(o) for o in ext[:300]]

    open_by = {}
    for o in orders:
        if o["status"] in TechnicianTask.OPEN_STATUSES:
            open_by[o["clinicKey"]] = open_by.get(o["clinicKey"], 0) + 1
    clinics = [{"key": f"c{t.clinic_id}", "kind": "odontis", "name": _clinic_name(t), "techId": t.pk,
                "home": t.clinic_id == user.clinic_id, "open": open_by.get(f"c{t.clinic_id}", 0)} for t in techs]
    clinics += [{"key": f"x{c.pk}", "kind": "ext", "name": c.name, "id": c.pk, "phone": c.phone,
                 "contact": c.contact, "open": open_by.get(f"x{c.pk}", 0)} for c in ext_clinics]

    pay = [_pay_row(f"c{t.clinic_id}", _clinic_name(t), TechnicianTask.all_clinics.filter(technician=t), today)
           for t in techs]
    pay += [_pay_row(f"x{c.pk}", c.name, ExternalOrder.objects.filter(owner=user, clinic=c), today)
            for c in ext_clinics]
    since = today - timedelta(days=90)
    works = [{"clinicKey": f"c{t.clinic_id}", "clinicName": _clinic_name(t.technician), "date": _d(t.installed_at),
              "iso": t.installed_at.isoformat(), "patient": f"{t.patient.last_name} {t.patient.first_name}".strip()
              if t.patient_id else "—", "service": t.service.name if t.service_id else "", "tooth": t.tooth_number,
              "amount": float(t.amount), "paid": t.paid, "paidAt": _d(t.paid_at)}
             for t in TechnicianTask.all_clinics.filter(technician__in=techs, status=TechnicianTask.STATUS_INSTALLED,
                                                        installed_at__gte=since)
             .select_related("patient", "service", "technician__clinic")[:300]]
    works += [{"clinicKey": f"x{o.clinic_id}", "clinicName": o.clinic.name, "date": _d(o.installed_at),
               "iso": o.installed_at.isoformat(), "patient": o.patient_name or "—", "service": o.work,
               "tooth": o.tooth_number, "amount": float(o.amount), "paid": o.paid, "paidAt": _d(o.paid_at),
               "extId": o.pk}
              for o in ExternalOrder.objects.filter(owner=user, status=TechnicianTask.STATUS_INSTALLED,
                                                    installed_at__gte=since).select_related("clinic")[:300]]
    works.sort(key=lambda w: w["iso"], reverse=True)
    return {
        "technician": {"name": user.name, "code": technician_code(user), "linked": bool(techs)},
        "clinics": clinics,
        "orders": orders,
        "statuses": [{"value": v, "label": STATUS_LABEL[v]} for v in BOARD],
        "pay": {"clinics": pay, "works": works},
        "today": today.isoformat(),
    }


@login_required
def my_lab(request):
    from apps.users.newui_views import _render
    if not request.user.is_technician_only and not technicians_for(request.user) \
            and not ExternalClinic.objects.filter(owner=request.user).exists():
        return redirect("/new/lab/")
    return _render(request, "labmy", "lab_my.html", {"labMy": my_data(request.user)})


@login_required
def my_lab_json(request):
    return JsonResponse(my_data(request.user))


def _ok(order_json):
    return JsonResponse({"ok": True, "order": order_json})


def _err(msg, status=400):
    return JsonResponse({"ok": False, "error": msg}, status=status)


def _my_task(request, pk):
    return (TechnicianTask.all_clinics.filter(pk=pk, technician__user=request.user, technician__is_active=True)
            .select_related("patient", "service", "treatment__doctor", "technician__user", "technician__clinic")
            .first())


def _upload_check(f):
    if f is None:
        return "Выберите файл"
    if os.path.splitext(f.name)[1].lower() not in UPLOAD_EXT:
        return "Можно фото, PDF, STL/PLY/OBJ или ZIP"
    if f.size > UPLOAD_MAX:
        return "Файл больше 25 МБ"
    return None


@login_required
@require_POST
def my_status(request, pk):
    task = _my_task(request, pk)
    if task is None:
        return _err("Заказ не найден", 404)
    new_status = request.POST.get("status")
    if new_status not in TECH_MOVES.get(task.status, ()):
        return _err("Этот статус ставит клиника")
    apply_status(task, new_status, request.user)
    return _ok(_order_json(task))


@login_required
@require_POST
def my_upload(request, pk):
    task = _my_task(request, pk)
    if task is None:
        return _err("Заказ не найден", 404)
    f = request.FILES.get("file")
    err = _upload_check(f)
    if err:
        return _err(err)
    TechnicianOrderFile.objects.create(task=task, file=f, name=_clean(os.path.basename(f.name)))
    return _ok(_order_json(task))


@login_required
@require_POST
def my_comment(request, pk):
    """Комментарий техника к заказу клиники — врачу и администраторам уведомление."""
    task = _my_task(request, pk)
    if task is None:
        return _err("Заказ не найден", 404)
    text = _clean(request.POST.get("text"), 2000)
    if not text:
        return _err("Напишите комментарий")
    add_comment(task, request.user, text, from_tech=True)
    return _ok(_order_json(task))


@login_required
@require_POST
def my_deadline(request, pk):
    """Техник не успевает — просит новый срок; меняется после подтверждения клиники."""
    task = _my_task(request, pk)
    if task is None:
        return _err("Заказ не найден", 404)
    err = request_deadline(task, request.user, _date(request.POST.get("date")), _clean(request.POST.get("reason"), 500))
    if err:
        return _err(err)
    return _ok(_order_json(task))


@login_required
@require_POST
def my_code_new(request):
    """Новый код техника (старый перестаёт работать; подключённые клиники остаются)."""
    return JsonResponse({"ok": True, "code": _new_code(request.user).code})


@login_required
@require_POST
def my_leave(request, pk):
    """Техник сам отключается от клиники ODONTIS (заказы остаются у клиники)."""
    n = Technician.all_clinics.filter(pk=pk, user=request.user).update(user=None)
    return JsonResponse({"ok": bool(n)}, status=200 if n else 404)


# ─── Клиники вне ODONTIS ─────────────────────────────────────────────────────

def _date(v):
    try:
        return datetime.fromisoformat(v).date() if v else None
    except ValueError:
        return None


@login_required
@require_POST
def ext_clinic_save(request):
    P = request.POST
    name = _clean(P.get("name"))
    if not name:
        return _err("Укажите название клиники")
    c = None
    if P.get("id"):
        c = ExternalClinic.objects.filter(pk=P["id"], owner=request.user).first()
        if c is None:
            return _err("Клиника не найдена", 404)
    elif ExternalClinic.objects.filter(owner=request.user, is_active=True).count() >= 200:
        return _err("Слишком много клиник")
    c = c or ExternalClinic(owner=request.user)
    c.name, c.phone, c.contact, c.is_active = name, _clean(P.get("phone"), 40), _clean(P.get("contact")), True
    c.save()
    return JsonResponse({"ok": True, "id": c.pk})


@login_required
@require_POST
def ext_clinic_delete(request, pk):
    c = ExternalClinic.objects.filter(pk=pk, owner=request.user).first()
    if c is None:
        return _err("Клиника не найдена", 404)
    if c.orders.exists():
        c.is_active = False        # история заказов и выплат остаётся
        c.save(update_fields=["is_active"])
    else:
        c.delete()
    return JsonResponse({"ok": True})


def _my_ext(request, pk):
    return (ExternalOrder.objects.filter(pk=pk, owner=request.user)
            .select_related("clinic").prefetch_related("files").first())


def _money(v):
    try:
        d = Decimal(str(v or "0").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None
    return d if Decimal(0) <= d <= Decimal("99999999") else None


@login_required
@require_POST
def ext_order_save(request):
    P = request.POST
    clinic = ExternalClinic.objects.filter(pk=P.get("clinic_id") or 0, owner=request.user).first()
    if clinic is None:
        return _err("Выберите клинику")
    work = _clean(P.get("work"))
    if not work:
        return _err("Укажите работу")
    amount = _money(P.get("amount"))
    if amount is None:
        return _err("Неверная сумма")
    if P.get("id"):
        o = _my_ext(request, P["id"])
        if o is None:
            return _err("Заказ не найден", 404)
    else:
        o = ExternalOrder(owner=request.user, transferred_at=timezone.localdate())
    o.clinic, o.work, o.amount = clinic, work, amount
    o.patient_name = _clean(P.get("patient"))
    o.doctor_name = _clean(P.get("doctor"))
    o.tooth_number = _clean(P.get("tooth"), 120)
    o.material = _clean(P.get("material"), 120)
    o.vita_color = _clean(P.get("color"), 20)
    o.comment = _clean(P.get("comment"), 2000)
    o.transferred_at = _date(P.get("transferred")) or o.transferred_at
    o.expected_ready = _date(P.get("expected"))
    o.save()
    return _ok(_ext_json(o))


@login_required
@require_POST
def ext_order_status(request, pk):
    o = _my_ext(request, pk)
    if o is None:
        return _err("Заказ не найден", 404)
    st = request.POST.get("status")
    if st not in STATUS_LABEL:
        return _err("Неизвестный статус")
    today = timezone.localdate()
    o.status = st
    if st == TechnicianTask.STATUS_READY and not o.ready_at:
        o.ready_at = today
    if st == TechnicianTask.STATUS_INSTALLED and not o.installed_at:
        o.installed_at = today
    o.save()
    return _ok(_ext_json(o))


@login_required
@require_POST
def ext_order_paid(request, pk):
    o = _my_ext(request, pk)
    if o is None:
        return _err("Заказ не найден", 404)
    o.paid = request.POST.get("paid") in ("1", "true", "on")
    o.paid_at = timezone.localdate() if o.paid else None
    o.save(update_fields=["paid", "paid_at", "updated_at"])
    return _ok(_ext_json(o))


@login_required
@require_POST
def ext_order_upload(request, pk):
    o = _my_ext(request, pk)
    if o is None:
        return _err("Заказ не найден", 404)
    f = request.FILES.get("file")
    err = _upload_check(f)
    if err:
        return _err(err)
    ExternalOrderFile.objects.create(order=o, file=f, name=_clean(os.path.basename(f.name)))
    return _ok(_ext_json(_my_ext(request, pk)))


@login_required
@require_POST
def ext_order_delete(request, pk):
    o = _my_ext(request, pk)
    if o is None:
        return _err("Заказ не найден", 404)
    for f in o.files.all():
        f.file.delete(save=False)
    o.delete()
    return JsonResponse({"ok": True})


# ─── Сторона клиники ─────────────────────────────────────────────────────────

def _is_admin(user):
    return user.is_superadmin or user.is_admin


@login_required
@require_POST
def lab_link(request):
    """Администратор привязывает логин своей клиники к технику (или отвязывает: user_id пустой)."""
    from apps.users.models import User
    if not _is_admin(request.user):
        return _err("Привязать вход может администратор", 403)
    tech = Technician.objects.filter(pk=request.POST.get("technician_id") or 0).first()
    if tech is None:
        return _err("Техник не найден", 404)
    uid = request.POST.get("user_id")
    user = None
    if uid:
        user = User.objects.filter(pk=uid, clinic_id=tech.clinic_id, is_active=True).first()
        if user is None or not user.has_role("technician"):
            return _err("Выберите сотрудника с ролью «Техник»")
        Technician.all_clinics.filter(user=user, clinic_id=tech.clinic_id).exclude(pk=tech.pk).update(user=None)
    tech.user = user
    tech.save(update_fields=["user"])
    return JsonResponse({"ok": True})


@login_required
@require_POST
def lab_connect(request):
    """Подключить техника из другой клиники по его коду: в нашей клинике
    появляется техник (или привязывается выбранный), заказы ему уходят в его
    кабинет. Попыток ввода кода — не больше 10 в час."""
    from apps.notifications.models import Notification
    from apps.tenancy import get_current_clinic
    if not _is_admin(request.user):
        return _err("Подключить техника может администратор", 403)
    clinic = get_current_clinic() or request.user.clinic
    if clinic is None:
        return _err("Выберите клинику")
    key = f"labconnect:{request.user.pk}"
    tries = cache.get(key, 0)
    if tries >= 10:
        return _err("Слишком много попыток — попробуйте через час", 429)
    cache.set(key, tries + 1, 3600)
    code = (request.POST.get("code") or "").strip().upper().replace(" ", "")
    if code and not code.startswith("T-") and len(code) == 8:
        code = f"T-{code[:4]}-{code[4:]}"
    tc = TechnicianCode.objects.filter(code=code).select_related("user").first()
    if tc is None or not tc.user.is_active:
        return _err("Код не найден — проверьте у техника код в его кабинете")
    tuser = tc.user
    if Technician.all_clinics.filter(clinic=clinic, user=tuser).exists():
        return _err("Этот техник уже подключён к вашей клинике")
    tech = None
    if request.POST.get("technician_id"):
        tech = Technician.objects.filter(pk=request.POST["technician_id"], user__isnull=True).first()
        if tech is None:
            return _err("Техник не найден или уже привязан")
    if tech is None:
        tech = Technician(clinic=clinic, name=tuser.name or tuser.login, phone=getattr(tuser, "phone", "") or "",
                          notes="Подключён по коду техника")
    tech.user = tuser
    tech.save()
    cache.delete(key)
    try:
        Notification.send(tuser, f"Клиника «{clinic.name}» подключила вас как техника",
                          "Её заказы теперь приходят в ваш кабинет.", type="task", link="/new/lab/my/",
                          clinic=tuser.clinic)
    except Exception:  # noqa: BLE001
        pass
    return JsonResponse({"ok": True, "id": tech.pk, "name": tech.name})


def _clinic_task(request, pk):
    if request.user.is_technician_only:
        return None
    return (TechnicianTask.objects.filter(pk=pk)
            .select_related("patient", "service", "treatment__doctor", "technician__user", "technician__clinic")
            .first())


def _clinic_order_json(t):
    from .services import pending_deadline
    p = t.patient
    pend = pending_deadline(t)
    return {
        "id": t.pk, "code": f"#L-{t.pk:04d}", "status": t.status, "statusLabel": t.get_status_display(),
        "patient": p.full_name if p else "—", "patientId": t.patient_id,
        "doctor": t.treatment.doctor.name if t.treatment_id and t.treatment.doctor_id else "",
        "technician": t.technician.name if t.technician_id else "",
        "service": t.service.name if t.service_id else "", "tooth": t.tooth_number, "material": t.material,
        "color": t.vita_color, "comment": t.doctor_comment, "amount": float(t.amount),
        "transferred": _d(t.transferred_at), "expectedReady": _d(t.expected_ready), "overdue": t.is_overdue,
        "files": _files(t.files.all()), "messages": messages_json(t),
        "pendingDeadline": pend.pk if pend else None,
    }


@login_required
def lab_order_json(request, pk):
    """Карточка заказа для клиники (Лаборатория → Канбан): детали, файлы, переписка."""
    t = _clinic_task(request, pk)
    if t is None:
        return _err("Заказ не найден", 404)
    return JsonResponse({"ok": True, "order": _clinic_order_json(t)})


@login_required
@require_POST
def lab_order_comment(request, pk):
    t = _clinic_task(request, pk)
    if t is None:
        return _err("Заказ не найден", 404)
    text = _clean(request.POST.get("text"), 2000)
    if not text:
        return _err("Напишите комментарий")
    add_comment(t, request.user, text, from_tech=False)
    return JsonResponse({"ok": True, "order": _clinic_order_json(t)})


@login_required
@require_POST
def lab_order_deadline(request, pk, mid):
    """Клиника решает по запросу техника о новом сроке."""
    from .models import TechnicianOrderMessage as M
    from .services import decide_deadline
    t = _clinic_task(request, pk)
    if t is None:
        return _err("Заказ не найден", 404)
    msg = M.objects.filter(pk=mid, task=t, kind=M.KIND_DEADLINE, decision=M.PENDING).first()
    if msg is None:
        return _err("Запрос уже решён")
    decide_deadline(msg, request.user, request.POST.get("approve") in ("1", "true", "on"))
    return JsonResponse({"ok": True, "order": _clinic_order_json(t)})


@login_required
@require_POST
def lab_create_login(request):
    """«Создать вход» в строке техника: учётная запись с ролью «Техник»,
    логин — телефон (без «+»), пароль — случайный, показывается один раз.
    Техник сразу привязан и входит в свой кабинет."""
    from apps.users.models import Role, User
    if not _is_admin(request.user):
        return _err("Создать вход может администратор", 403)
    tech = Technician.objects.filter(pk=request.POST.get("technician_id") or 0).first()
    if tech is None:
        return _err("Техник не найден", 404)
    if tech.user_id:
        return _err("У техника уже есть вход")
    role = Role.objects.filter(name=Role.TECHNICIAN, clinic__isnull=True).first()
    if role is None:
        return _err("Роль «Техник» не найдена")
    digits = "".join(ch for ch in (tech.phone or "") if ch.isdigit())
    base = digits if len(digits) >= 6 else f"tech{tech.pk}"
    login, n = base, 2
    while User.objects.filter(login=login).exists():
        login, n = f"{base}-{n}", n + 1
    password = "".join(secrets.choice(CODE_ALPHABET.lower() + "23456789") for _ in range(8))
    user = User(login=login, name=tech.name, phone=tech.phone or "", clinic_id=tech.clinic_id, role=role,
                use_new_interface=True)
    user.set_password(password)
    user.save()
    tech.user = user
    tech.save(update_fields=["user"])
    return JsonResponse({"ok": True, "login": login, "password": password, "userId": user.pk})
