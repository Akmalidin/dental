"""Эндпоинты синхронизации (облако ↔ локальная копия)."""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .core import export_clinic, import_blocks


def _user_clinic(request):
    user = request.user
    if getattr(user, "is_superadmin", False):
        cid = request.GET.get("clinic") or request.session.get("active_clinic")
        if cid:
            from apps.users.models import Clinic
            return Clinic.objects.filter(pk=cid).first()
    return getattr(user, "clinic", None)


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

        # 1) push локальных данных вверх
        clinic = Clinic.objects.first()
        pushed = 0
        if clinic:
            res = cli.post_json("/sync/push/", {"blocks": export_clinic(clinic)})
            pushed = sum(res.get("applied", {}).values()) if res.get("ok") else 0

        # 2) pull свежих данных вниз
        data = cli.get_json("/sync/export/")
        pulled = 0
        if data.get("ok"):
            with transaction.atomic():
                counts = import_blocks(data["blocks"])
            pulled = sum(counts.values())

        return JsonResponse({"ok": True, "pushed": pushed, "pulled": pulled})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


@csrf_exempt
@login_required
def sync_push(request):
    """Принять локальные изменения и применить в облаке (upsert по PK).

    ВНИМАНИЕ: базовая версия (last-write-wins по PK). Полное разрешение
    конфликтов и маппинг ID — следующий этап.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)
    try:
        payload = json.loads(request.body)
        # prefer_newer: не затирать в облаке записи, которые там изменились позже
        res = import_blocks(payload.get("blocks", []), prefer_newer=True)
        return JsonResponse({"ok": True, "applied": res.get("applied", {}), "skipped": res.get("skipped", {})})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
