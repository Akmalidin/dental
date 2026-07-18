"""Эндпоинты синхронизации (облако ↔ локальная копия)."""
import json
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .core import export_clinic, import_blocks


def _user_clinic(request):
    user = request.user
    if getattr(user, "is_superadmin", False):
        cid = request.GET.get("clinic") or request.session.get("active_clinic")
        if cid:
            from apps.users.models import Clinic
            return Clinic.objects.filter(pk=cid).first()
    return getattr(user, "clinic", None)


def _sync_staff_ok(user):
    return user.is_superadmin or user.is_admin_main or user.is_admin


@login_required
def sync_export(request):
    """Отдать все данные клиники пользователя (для первичной загрузки в оффлайн-копию)."""
    clinic = _user_clinic(request)
    if clinic is None:
        return JsonResponse({"ok": False, "error": "У пользователя не задана клиника"}, status=400)
    blocks = export_clinic(clinic)
    return JsonResponse({
        "ok": True,
        "clinic": {"id": clinic.pk, "name": clinic.name},
        "exported_at": timezone.now().isoformat(),
        "blocks": blocks,
    })


@login_required
def sync_run(request):
    """Локальная кнопка «Синхронизация»: отправить локальные данные в облако и забрать свежие."""
    from django.conf import settings
    if not getattr(settings, "OFFLINE_MODE", False):
        return JsonResponse({"ok": False, "error": "Доступно только в оффлайн-режиме"}, status=400)
    cfg_path = settings.BASE_DIR / "offline_cloud.json"
    if not cfg_path.exists():
        return JsonResponse({"ok": False, "error": "Сначала выполните первичную настройку (offline_setup)"}, status=400)
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        from .cloud_client import CloudClient
        from .core import export_clinic, import_blocks
        from apps.users.models import Clinic
        from django.db import transaction

        cli = CloudClient(cfg["url"])
        if not cli.login(cfg["login"], cfg["password"]):
            return JsonResponse({"ok": False, "error": "Не удалось войти в облако"}, status=400)

        # Отметка последней успешной синхронизации — точка отсчёта для
        # обнаружения конфликтов (что реально поменялось с обеих сторон с тех пор).
        since = cfg.get("last_synced_at", "")
        sync_started_at = timezone.now().isoformat()

        # 1) push локальных данных вверх
        clinic = Clinic.objects.first()
        pushed = conflicts = 0
        if clinic:
            res = cli.post_json("/sync/push/", {"blocks": export_clinic(clinic), "since": since})
            pushed = sum(res.get("applied", {}).values()) if res.get("ok") else 0
            conflicts = res.get("conflicts", 0) if res.get("ok") else 0

        # 2) pull свежих данных вниз (в т.ч. то, что не применилось из-за конфликта —
        # у нас останется актуальная облачная версия локально)
        data = cli.get_json("/sync/export/")
        pulled = 0
        if data.get("ok"):
            with transaction.atomic():
                counts = import_blocks(data["blocks"])
            pulled = sum(counts.values())

        # Сдвигаем отметку синхронизации вперёд независимо от конфликтов —
        # неразрешённые конфликты остаются в списке (см. /sync/conflicts/)
        # и не будут блокировать дальнейшую работу.
        cfg["last_synced_at"] = sync_started_at
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        return JsonResponse({"ok": True, "pushed": pushed, "pulled": pulled, "conflicts": conflicts})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


@csrf_exempt
@login_required
def sync_push(request):
    """Принять локальные изменения и применить в облаке (upsert по PK).

    Если пришла отметка `since` (последняя успешная синхронизация) — включаем
    точное обнаружение конфликтов: запись, изменённая одновременно и локально,
    и в облаке, НЕ перезаписывается молча, а сохраняется в SyncConflict для
    разрешения персоналом клиники вручную (см. /sync/conflicts/).
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)
    try:
        payload = json.loads(request.body)
        since_raw = payload.get("since") or ""
        since = parse_datetime(since_raw) if since_raw else None

        if since is not None:
            res = import_blocks(payload.get("blocks", []), since=since, collect_conflicts=True)
            clinic = _user_clinic(request)
            if clinic is not None:
                from .models import SyncConflict
                for c in res.get("conflicts", []):
                    SyncConflict.objects.create(
                        clinic=clinic, model_label=c["model"], object_pk=str(c["pk"]),
                        object_repr=c["object_repr"],
                        local_data=c["local_data"], cloud_data=c["cloud_data"],
                        local_updated_at=c["local_updated_at"], cloud_updated_at=c["cloud_updated_at"],
                    )
            return JsonResponse({
                "ok": True, "applied": res.get("applied", {}), "skipped": res.get("skipped", {}),
                "conflicts": len(res.get("conflicts", [])),
            })

        # Нет отметки последней синхронизации (старый локальный клиент или
        # первый push) — прежнее поведение: не затираем то, что в облаке новее.
        res = import_blocks(payload.get("blocks", []), prefer_newer=True)
        return JsonResponse({
            "ok": True, "applied": res.get("applied", {}), "skipped": res.get("skipped", {}), "conflicts": 0,
        })
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


@login_required
def sync_conflicts(request):
    """Список неразрешённых конфликтов синхронизации текущей клиники."""
    if not _sync_staff_ok(request.user):
        return redirect("/")
    from .models import SyncConflict
    clinic = _user_clinic(request)
    qs = SyncConflict.objects.filter(resolved=False)
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return render(request, "sync/conflicts.html", {"conflicts": qs.select_related("clinic").order_by("-created_at")})


@login_required
@require_POST
def sync_conflict_resolve(request, pk):
    """Разрешить конфликт: оставить облачную версию (по умолчанию, ничего не
    делаем с данными) или применить локальную (перезаписать текущую запись)."""
    if not _sync_staff_ok(request.user):
        return redirect("/")
    from .models import SyncConflict
    from django.core import serializers as _serializers
    c = get_object_or_404(SyncConflict, pk=pk)
    action = request.POST.get("action")
    if action == "local":
        for d in _serializers.deserialize("python", [c.local_data]):
            d.save()
        c.resolution = SyncConflict.RESOLUTION_LOCAL
        messages.success(request, "Применена локальная версия записи")
    else:
        c.resolution = SyncConflict.RESOLUTION_CLOUD
        messages.success(request, "Оставлена облачная версия записи")
    c.resolved = True
    c.resolved_by = request.user
    c.resolved_at = timezone.now()
    c.save(update_fields=["resolution", "resolved", "resolved_by", "resolved_at"])
    return redirect("sync_conflicts")
