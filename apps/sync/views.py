"""Эндпоинты синхронизации (облако ↔ офлайн-копия).

Облако:
  POST /sync/register/  — регистрация офлайн-копии (вход сотрудника по паролю
                          один раз, при настройке) → номер устройства и токен;
  GET  /sync/export/    — полный снимок клиники (токен устройства или
                          директор/админ в браузере);
  POST /sync/push/      — изменения офлайн-копии (только токен устройства);
  /sync/conflicts/      — конфликты и их разрешение (браузер).
Офлайн-копия:
  POST /sync/run/       — кнопка «Синхронизация».
"""
import hashlib
import hmac
import json
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .core import export_clinic


def _user_clinic(request):
    user = request.user
    if getattr(user, "is_superadmin", False):
        cid = request.GET.get("clinic") or request.session.get("active_clinic")
        if cid:
            from apps.users.models import Clinic
            return Clinic.objects.filter(pk=cid).first()
    return getattr(user, "clinic", None)


def _sync_staff_ok(user):
    return bool(user and user.is_authenticated and user.is_active and
                (user.is_superadmin or user.is_admin_main or user.is_admin))


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _device_from_request(request):
    """Устройство по заголовку «Authorization: Device <номер>:<токен>».
    Токен действует, пока устройство активно и сотрудник, который его
    зарегистрировал, активен и остаётся директором/админом этой клиники."""
    from .models import SyncDevice
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Device "):
        return None
    try:
        dev_id, token = auth[7:].strip().split(":", 1)
        dev = SyncDevice.objects.select_related("clinic", "created_by").get(pk=int(dev_id), is_active=True)
    except Exception:  # noqa: BLE001
        return None
    if not hmac.compare_digest(dev.token_hash, _token_hash(token)):
        return None
    user = dev.created_by
    if not _sync_staff_ok(user):
        return None
    if not user.is_superadmin and user.clinic_id != dev.clinic_id:
        return None
    return dev


@login_required
@require_POST
def sync_register(request):
    """Зарегистрировать офлайн-копию клиники: выдать номер устройства (свой
    диапазон id для новых записей) и токен синхронизации."""
    from .models import SyncDevice
    if not _sync_staff_ok(request.user):
        return JsonResponse({"ok": False, "error": "Нет доступа"}, status=403)
    clinic = _user_clinic(request)
    if clinic is None:
        return JsonResponse({"ok": False, "error": "У пользователя не задана клиника"}, status=400)
    token = secrets.token_urlsafe(32)
    dev = SyncDevice.objects.create(
        clinic=clinic, name=(request.POST.get("name") or "")[:120],
        token_hash=_token_hash(token), created_by=request.user,
    )
    return JsonResponse({"ok": True, "device_id": dev.pk, "token": token,
                         "clinic": {"id": clinic.pk, "name": clinic.name}})


def sync_export(request):
    """Полный снимок данных клиники (первичная загрузка и pull)."""
    dev = _device_from_request(request)
    if dev is not None:
        clinic = dev.clinic
    else:
        # Через браузер — только директор/суперадмин и без хешей паролей.
        user = request.user
        if not (user.is_authenticated and user.is_active and (user.is_superadmin or user.is_admin_main)):
            return JsonResponse({"ok": False, "error": "Нет доступа"}, status=403)
        clinic = _user_clinic(request)
    if clinic is None:
        return JsonResponse({"ok": False, "error": "У пользователя не задана клиника"}, status=400)
    exported_at = timezone.now()
    blocks = export_clinic(clinic, include_password_hashes=dev is not None)
    if dev is not None:
        dev.last_sync_at = exported_at
        dev.save(update_fields=["last_sync_at"])
    return JsonResponse({
        "ok": True,
        "clinic": {"id": clinic.pk, "name": clinic.name},
        "exported_at": exported_at.isoformat(),
        "blocks": blocks,
    })


@csrf_exempt   # только токен устройства (cookie-сессия здесь не принимается)
@require_POST
def sync_push(request):
    """Принять изменения офлайн-копии (см. core.apply_push)."""
    from .core import apply_push
    from .models import SyncConflict
    dev = _device_from_request(request)
    if dev is None:
        return JsonResponse({"ok": False, "error": "Нет доступа"}, status=403)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Неверный формат"}, status=400)
    since = parse_datetime(payload.get("since") or "")
    if since is None:
        return JsonResponse({"ok": False, "error": "Нет отметки прошлой синхронизации"}, status=400)
    res = apply_push(payload.get("changes", []), payload.get("deletions", []), dev.clinic, since)
    for c in res["conflicts"]:
        SyncConflict.objects.create(
            clinic=dev.clinic, model_label=c["model"], object_pk=str(c["pk"]),
            object_repr=c["object_repr"], local_data=c["local_data"], cloud_data=c["cloud_data"],
            local_updated_at=parse_datetime(c["local_updated_at"] or "") if c["local_updated_at"] else None,
            cloud_updated_at=parse_datetime(c["cloud_updated_at"] or "") if c["cloud_updated_at"] else None,
        )
    return JsonResponse({
        "ok": True, "applied": res["applied"], "conflicts": len(res["conflicts"]),
        "rejected": res["rejected"], "skipped_deleted": res["skipped_deleted"],
        "errors": res["errors"], "done": res["done"], "overlaps": res["overlaps"],
    })


@login_required
@require_POST
def sync_run(request):
    """Офлайн-копия: кнопка «Синхронизация»."""
    from django.conf import settings
    if not getattr(settings, "OFFLINE_MODE", False):
        return JsonResponse({"ok": False, "error": "Доступно только в оффлайн-режиме"}, status=400)
    from .runner import run_sync, SyncError
    try:
        return JsonResponse(run_sync())
    except SyncError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:  # noqa: BLE001 — нет интернета и т. п.
        return JsonResponse({"ok": False, "error": f"Нет связи с облаком: {e}"}, status=400)


@login_required
def sync_conflicts(request):
    """Список неразрешённых конфликтов синхронизации текущей клиники."""
    if not _sync_staff_ok(request.user):
        return redirect("/")
    from .models import SyncConflict
    clinic = _user_clinic(request)
    if clinic is None:
        return redirect("/")
    qs = SyncConflict.objects.filter(resolved=False, clinic=clinic)
    return render(request, "sync/conflicts.html", {"conflicts": qs.select_related("clinic").order_by("-created_at")})


@login_required
@require_POST
def sync_conflict_resolve(request, pk):
    """Разрешить конфликт: оставить облачную версию (ничего не меняем) или
    применить офлайн-версию (перезаписать или удалить текущую запись)."""
    if not _sync_staff_ok(request.user):
        return redirect("/")
    from django.apps import apps as django_apps
    from django.core import serializers as _serializers
    from .core import push_allowed
    from .models import SyncConflict
    clinic = _user_clinic(request)
    if clinic is None:
        return redirect("/")
    c = get_object_or_404(SyncConflict, pk=pk, clinic=clinic, resolved=False)
    if request.POST.get("action") == "local":
        model = django_apps.get_model(c.model_label)
        existing = model._base_manager.filter(pk=c.object_pk).first()
        patient_id = getattr(existing, "patient_id", None)
        if (c.local_data or {}).get("deleted"):
            if existing is not None:
                if not push_allowed(c.model_label, existing, existing, clinic):
                    messages.error(request, "Эту запись нельзя изменить")
                    return redirect("sync_conflicts")
                existing.delete()
        else:
            for d in _serializers.deserialize("python", [c.local_data]):
                d.object.pk = existing.pk if existing is not None else d.object.pk
                if not push_allowed(c.model_label, d.object, existing, clinic):
                    messages.error(request, "Эту запись нельзя применить")
                    return redirect("sync_conflicts")
                d.save()
                patient_id = patient_id or getattr(d.object, "patient_id", None) or (
                    d.object.pk if c.model_label == "patients.Patient" else None)
        if patient_id:
            from apps.patients.models import Patient
            p = Patient.all_objects.filter(pk=patient_id).first()
            if p:
                p.recalc_balance()
        c.resolution = SyncConflict.RESOLUTION_LOCAL
        messages.success(request, "Применена офлайн-версия записи")
    else:
        c.resolution = SyncConflict.RESOLUTION_CLOUD
        messages.success(request, "Оставлена облачная версия записи")
    c.resolved = True
    c.resolved_by = request.user
    c.resolved_at = timezone.now()
    c.save(update_fields=["resolution", "resolved", "resolved_by", "resolved_at"])
    return redirect("sync_conflicts")
