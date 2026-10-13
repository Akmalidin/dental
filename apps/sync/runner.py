"""Офлайн-копия: первичная настройка и синхронизация с облаком."""
import socket

from django.db import transaction

from .cloud_client import CloudClient
from .core import (
    backup_local_db, clear_journal, export_changes, import_blocks, pending_keys,
    read_local_cfg, replace_from_snapshot, write_local_cfg,
)


class SyncError(Exception):
    pass


def setup(url, login, password, name=None, clinic_id=None):
    """Первый запуск: войти, зарегистрировать устройство, скачать данные."""
    url = url.rstrip("/")
    cli = CloudClient(url)
    if not cli.login(login, password):
        raise SyncError("Не удалось войти (проверьте логин и пароль)")
    reg = cli.register(name or socket.gethostname())
    if not reg.get("ok"):
        raise SyncError("Облако отказало в регистрации: " + str(reg.get("error")))
    cli = CloudClient(url, reg["device_id"], reg["token"])
    data = cli.get_json("/sync/export/")
    if not data.get("ok"):
        raise SyncError("Ошибка загрузки данных: " + str(data.get("error")))
    with transaction.atomic():
        counts = import_blocks(data["blocks"])
    write_local_cfg({
        "url": url, "device_id": reg["device_id"], "token": reg["token"],
        "clinic_id": data["clinic"]["id"], "clinic": data["clinic"]["name"],
        "last_synced_at": data["exported_at"],
    })
    return data["clinic"]["name"], counts


def run_sync():
    """Синхронизация: резервная копия → отправить свои изменения → получить
    снимок облака. Возвращает итог для кнопки."""
    from apps.users.models import Clinic
    cfg = read_local_cfg()
    if not cfg.get("device_id") or not cfg.get("token"):
        raise SyncError("Офлайн-копия не настроена или настроена старой версией — "
                        "запустите первичную настройку (offline_setup) заново")
    clinic = Clinic.objects.filter(pk=cfg.get("clinic_id")).first() or Clinic.objects.first()
    if clinic is None:
        raise SyncError("В локальной базе нет клиники — запустите первичную настройку")
    cli = CloudClient(cfg["url"], cfg["device_id"], cfg["token"])

    backup_local_db()

    changes, deletions, upto = export_changes()
    pushed = conflicts = rejected = 0
    errors, overlaps = [], []
    if changes or deletions:
        res = cli.post_json("/sync/push/", {
            "since": cfg.get("last_synced_at", ""), "changes": changes, "deletions": deletions,
        })
        if not res.get("ok"):
            raise SyncError("Облако не приняло изменения: " + str(res.get("error")))
        clear_journal(res.get("done", []), upto)
        pushed, conflicts, rejected = res.get("applied", 0), res.get("conflicts", 0), res.get("rejected", 0)
        errors, overlaps = res.get("errors", []), res.get("overlaps", [])

    data = cli.get_json("/sync/export/")
    if not data.get("ok"):
        raise SyncError("Не удалось получить данные из облака: " + str(data.get("error")))
    with transaction.atomic():
        counts = replace_from_snapshot(data["blocks"], clinic, keep=pending_keys())
    cfg["last_synced_at"] = data["exported_at"]
    write_local_cfg(cfg)
    return {
        "ok": True, "pushed": pushed, "pulled": sum(counts.values()),
        "conflicts": conflicts, "rejected": rejected,
        "errors": len(errors), "error_details": errors[:10], "overlaps": overlaps,
        "pending": len(pending_keys()),
    }
