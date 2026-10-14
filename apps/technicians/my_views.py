"""Кабинет зубного техника (/new/lab/my/): только его заказы — доска по
статусам, файлы, история — и его выплаты. Привязка логина к технику —
lab_link (администратор, вкладка «Техники» в Лаборатории)."""
import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Technician, TechnicianOrderFile, TechnicianTask
from .services import TECH_MOVES, apply_status

UPLOAD_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".pdf", ".stl", ".ply", ".obj", ".zip"}
UPLOAD_MAX = 25 * 1024 * 1024
BOARD = [TechnicianTask.STATUS_TRANSFERRED, TechnicianTask.STATUS_IN_PROGRESS, TechnicianTask.STATUS_CORRECTION,
         TechnicianTask.STATUS_READY, TechnicianTask.STATUS_FITTING, TechnicianTask.STATUS_INSTALLED]


def _norm(s):
    return " ".join((s or "").lower().replace("ё", "е").split())


def technician_for(user):
    """Техник этого логина. Если ещё не привязан, а в клинике ровно один
    свободный техник с тем же именем — привязываем сам."""
    tech = Technician.objects.filter(user=user).first()
    if tech is not None or not user.has_role("technician"):
        return tech
    same = [t for t in Technician.objects.filter(user__isnull=True, is_active=True) if _norm(t.name) == _norm(user.name)]
    if len(same) == 1:
        tech = same[0]
        tech.user = user
        tech.save(update_fields=["user"])
        return tech
    return None


def _d(v):
    return v.strftime("%d.%m.%Y") if v else ""


def _order_json(t):
    from apps.users.media_views import signed_url
    p = t.patient
    doctor = t.treatment.doctor if t.treatment_id and t.treatment.doctor_id else None
    return {
        "id": t.pk, "code": f"#L-{t.pk:04d}", "status": t.status, "statusLabel": t.get_status_display(),
        "patient": f"{p.last_name} {p.first_name}".strip() if p else "—",
        "doctor": doctor.name if doctor else "",
        "service": t.service.name if t.service_id else "", "tooth": t.tooth_number, "material": t.material,
        "color": t.vita_color, "comment": t.doctor_comment,
        "transferred": _d(t.transferred_at), "expectedReady": _d(t.expected_ready),
        "expectedIso": t.expected_ready.isoformat() if t.expected_ready else "",
        "readyAt": _d(t.ready_at), "installedAt": _d(t.installed_at),
        "overdue": t.is_overdue, "amount": float(t.amount), "paid": t.paid,
        "moves": list(TECH_MOVES.get(t.status, ())),
        "files": [{"id": f.pk, "name": f.name or os.path.basename(f.file.name), "url": signed_url(f.file.name),
                   "isImage": f.is_image} for f in t.files.all()],
        "events": [{"label": e.get_status_display(), "at": timezone.localtime(e.at).strftime("%d.%m %H:%M"),
                    "by": e.by.name if e.by_id else ""} for e in t.events.all()],
    }


def my_data(tech):
    today = timezone.localdate()
    recent = today - timedelta(days=30)
    qs = (TechnicianTask.objects.filter(technician=tech, status__in=BOARD)
          .exclude(status=TechnicianTask.STATUS_INSTALLED, installed_at__lt=recent)
          .select_related("patient", "service", "treatment__doctor")
          .prefetch_related("files", "events__by").order_by("expected_ready", "created_at"))
    month = today.replace(day=1)
    mine = TechnicianTask.objects.filter(technician=tech)
    installed = mine.filter(status=TechnicianTask.STATUS_INSTALLED)
    s = lambda q: float(q.aggregate(x=Sum("amount"))["x"] or Decimal(0))  # noqa: E731
    works = (installed.filter(installed_at__gte=today - timedelta(days=90))
             .select_related("patient", "service").order_by("-installed_at")[:200])
    return {
        "technician": {"id": tech.pk, "name": tech.name},
        "orders": [_order_json(t) for t in qs[:300]],
        "statuses": [{"value": v, "label": dict(TechnicianTask.STATUS_CHOICES)[v]} for v in BOARD],
        "pay": {
            "earnedMonth": s(installed.filter(installed_at__gte=month)),
            "unpaid": s(installed.filter(paid=False)),
            "paidMonth": s(mine.filter(paid=True, paid_at__gte=month)),
            "inWork": s(mine.filter(status__in=TechnicianTask.OPEN_STATUSES)),
            "works": [{"date": _d(t.installed_at), "patient": f"{t.patient.last_name} {t.patient.first_name}".strip()
                       if t.patient_id else "—", "service": t.service.name if t.service_id else "",
                       "tooth": t.tooth_number, "amount": float(t.amount), "paid": t.paid, "paidAt": _d(t.paid_at)}
                      for t in works],
        },
        "today": today.isoformat(),
    }


@login_required
def my_lab(request):
    from apps.users.newui_views import _render
    tech = technician_for(request.user)
    if tech is None and not request.user.is_technician_only:
        return redirect("/new/lab/")
    return _render(request, "labmy", "lab_my.html", {"labMy": my_data(tech) if tech else None})


@login_required
def my_lab_json(request):
    tech = technician_for(request.user)
    if tech is None:
        return JsonResponse({"ok": False, "error": "Учётная запись не связана с техником"}, status=403)
    return JsonResponse(my_data(tech))


def _my_task(request, pk):
    tech = technician_for(request.user)
    if tech is None:
        return None
    return (TechnicianTask.objects.filter(pk=pk, technician=tech)
            .select_related("patient", "service", "treatment__doctor", "technician__user").first())


@login_required
@require_POST
def my_status(request, pk):
    task = _my_task(request, pk)
    if task is None:
        return JsonResponse({"ok": False, "error": "Заказ не найден"}, status=404)
    new_status = request.POST.get("status")
    if new_status not in TECH_MOVES.get(task.status, ()):
        return JsonResponse({"ok": False, "error": "Этот статус ставит клиника"}, status=400)
    apply_status(task, new_status, request.user)
    return JsonResponse({"ok": True, "order": _order_json(task)})


@login_required
@require_POST
def my_upload(request, pk):
    task = _my_task(request, pk)
    if task is None:
        return JsonResponse({"ok": False, "error": "Заказ не найден"}, status=404)
    f = request.FILES.get("file")
    if f is None:
        return JsonResponse({"ok": False, "error": "Выберите файл"}, status=400)
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in UPLOAD_EXT:
        return JsonResponse({"ok": False, "error": "Можно фото, PDF, STL/PLY/OBJ или ZIP"}, status=400)
    if f.size > UPLOAD_MAX:
        return JsonResponse({"ok": False, "error": "Файл больше 25 МБ"}, status=400)
    name = os.path.basename(f.name).replace("<", "").replace(">", "")[:200]
    TechnicianOrderFile.objects.create(task=task, file=f, name=name)
    return JsonResponse({"ok": True, "order": _order_json(task)})


@login_required
@require_POST
def lab_link(request):
    """Администратор привязывает логин к технику (или отвязывает: user_id пустой)."""
    from apps.users.models import User
    if not (request.user.is_superadmin or request.user.is_admin):
        return JsonResponse({"ok": False, "error": "Привязать вход может администратор"}, status=403)
    tech = Technician.objects.filter(pk=request.POST.get("technician_id") or 0).first()
    if tech is None:
        return JsonResponse({"ok": False, "error": "Техник не найден"}, status=404)
    uid = request.POST.get("user_id")
    user = None
    if uid:
        user = User.objects.filter(pk=uid, clinic_id=tech.clinic_id, is_active=True).first()
        if user is None or not user.has_role("technician"):
            return JsonResponse({"ok": False, "error": "Выберите сотрудника с ролью «Техник»"}, status=400)
        Technician.all_clinics.filter(user=user).exclude(pk=tech.pk).update(user=None)
    tech.user = user
    tech.save(update_fields=["user"])
    return JsonResponse({"ok": True})
