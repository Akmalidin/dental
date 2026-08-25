"""
Аудит-центр (/new/superadmin/) — платформенная лента событий безопасности.

Две задачи в одном модуле, сознательно не размазанные по apps/users/views.py
(и так один из самых больших файлов в проекте):

1. `log_audit_event()` — единая точка записи AuditEvent, используется из
   apps.tenancy (ClinicSoftDeleteModel.soft_delete/restore — один хук на
   ВСЕ удаляемые модели) и из мутаций супер-админа в apps.users.views
   (блокировка клиник/IP, доступы, филиалы, каналы...).
2. `superadmin_audit_feed()`/`superadmin_audit_metrics()` — сборка «Ленты
   событий» на лету из ТРЁХ источников, без дублирования хранения:
     - AuditEvent (изменения/удаления, которые больше нигде не логируются);
     - ClinicLoginEvent (входы/отказы — уже пишется в apps.users.forms.
       LoginForm.clean() при каждой попытке входа, здесь только читаем);
     - simple_history Patient/Treatment (правки карточек — тот же diff-приём,
       что уже был в audit_center, вынесен сюда в build_history_rows(),
       чтобы не дублировать код между старой страницей /users/audit/ и
       новой лентой).

«Просмотры» (категория "view") — НЕ общий трекинг каждого клика по
приложению (это был бы шум обычной работы персонала, а не журнал
безопасности), а только надзорные действия супер-админа/директора над
чужими данными: вход в конкретную клинику (apps.users.views.
set_active_clinic → action="clinic_enter"), открытие сводки клиники
супер-админом (clinic_overview → action="clinic_view", только для
is_superadmin — просмотр admin_main своей же клиники не логируется, это
рутина) и «Войти как сотрудник» (staff_login_as → action="impersonate_start").
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Count as _Count, Q
from django.utils import timezone


# Поля, которые не несут смысла в диффе (служебные/технические) — не
# показываем. Общее для build_history_rows() и старого audit_center.
_AUDIT_DIFF_SKIP_FIELDS = {"updated_at", "id"}

CATEGORY_LOGIN = "login"
CATEGORY_DENY = "deny"
CATEGORY_CHANGE = "change"
CATEGORY_DELETE = "delete"
CATEGORY_VIEW = "view"

# Дата включения захвата IP в историю правок (Patient/Treatment) — PR #76,
# задеплоен 2026-08-22 15:14 UTC. Записи истории ДО этого момента не могут
# получить IP задним числом (миграция добавляет только поле, не данные) —
# используем эту дату, чтобы отличить в UI «IP не отслеживался тогда» от
# «IP не определился технически».
IP_TRACKING_SINCE = datetime(2026, 8, 22, 15, 14, tzinfo=dt_timezone.utc)

ACTION_LABELS = {
    "ip_block": "Блокировка IP",
    "ip_unblock": "Снятие блокировки IP",
    "clinic_block": "Блокировка клиники",
    "clinic_unblock": "Разблокировка клиники",
    "clinic_feature_block": "Изменение запрещённых функций",
    "clinic_access_grant": "Изменение доступов клиники",
    "clinic_update": "Изменение клиники",
    "clinic_notify": "Уведомление клинике",
    "clinic_archive": "Архивация клиники",
    "clinic_restore": "Восстановление клиники",
    "clinic_create": "Создание клиники",
    "branch_toggle": "Блокировка/разблокировка филиала",
    "channel_toggle": "Переключение канала",
    "site_toggle": "Переключение публичного сайта",
    "access_request_status": "Статус заявки на доступ",
    "purge": "Окончательное удаление",
    "soft_delete": "Удаление",
    "restore": "Восстановление",
    "clinic_view": "Просмотр клиники",
    "clinic_enter": "Вход в клинику (супер-админ)",
    "impersonate_start": "Вход как сотрудник",
    "bulk_purge": "Массовая очистка (авто, >30 дней)",
    "backup_create": "Создание резервной копии БД",
    "backup_download": "Скачивание резервной копии БД",
    "patient_merge": "Объединение карточек пациентов",
}

# Возрастной порог массовой очистки «Удалений в очереди» — записи свежее
# этого возраста НЕ трогаем (ещё могут быть случайно восстановлены через
# обычную «Корзину»), см. bulk_purge_eligible_summary()/bulk_purge_old_deletions().
BULK_PURGE_DEFAULT_DAYS = 30
# Максимум объектов, реально удаляемых за один вызов bulk_purge_old_deletions()
# — синхронный запрос, без очереди задач (Celery) в проде, у gunicorn таймаут
# 120с (deploy/sadaf.service) — большая очередь чистится за несколько кликов.
BULK_PURGE_DEFAULT_LIMIT = 1000


def log_audit_event(*, action, category, object_repr="", actor=None, request=None,
                     object_model="", object_id="", clinic=None, diff=None, result="success"):
    """Единственная точка записи AuditEvent — вызывающая сторона (вьюха,
    soft_delete/restore) никогда не должна упасть из-за сбоя логирования,
    поэтому всё обёрнуто в try/except (тот же паттерн, что уже используется
    вокруг ClinicLoginEvent.objects.create в apps.users.forms.LoginForm)."""
    try:
        from .models import AuditEvent
        from apps.tenancy import get_client_ip

        ip_address = None
        user_agent = ""
        if request is not None:
            ip_address = get_client_ip(request)
            user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:300]
        has_actor = actor is not None and getattr(actor, "pk", None)
        AuditEvent.objects.create(
            action=action,
            category=category,
            actor=actor if has_actor else None,
            actor_name=(getattr(actor, "name", "") or "") if has_actor else "",
            actor_role=(getattr(actor, "role_name", "") or "") if has_actor else "",
            clinic=clinic,
            object_model=object_model,
            object_id=str(object_id) if object_id else "",
            object_repr=(object_repr or "")[:300],
            ip_address=ip_address,
            user_agent=user_agent,
            result=result,
            diff=diff or [],
        )
    except Exception:
        pass


def build_history_rows(qs, model_key, model_label, title_fn):
    """Строит строки ленты из simple_history queryset (diff между
    соседними версиями объекта) — общий приём для старого /users/audit/
    (apps.users.views.audit_center) и новой superadmin_audit_feed(), чтобы
    diff-логика не дублировалась между ними."""
    type_label = {"+": "Создание", "~": "Изменение", "-": "Удаление"}
    out = []
    for h in qs.select_related("history_user").order_by("-history_date")[:150]:
        prev = h.prev_record
        diff = []
        if prev:
            delta = h.diff_against(prev)
            diff = [
                {"field": c.field, "old": c.old, "new": c.new}
                for c in delta.changes if c.field not in _AUDIT_DIFF_SKIP_FIELDS
            ]
        out.append({
            "model": model_key, "model_label": model_label, "obj_id": h.id,
            "title": title_fn(h),
            "type": type_label.get(h.history_type, h.history_type),
            "raw_type": h.history_type,
            "user": h.history_user.name if h.history_user else "—",
            "date": h.history_date, "hid": h.history_id,
            "diff": diff,
            # history_ip — см. apps.tenancy.HistoricalIPAddressModel/_add_history_ip;
            # у записей ДО этой правки его нет — getattr с фолбэком на None.
            "ip": getattr(h, "history_ip", None),
        })
    return out


def _event_row(e):
    role = e.actor_role
    actor_label = f"{e.actor_name} · {role}" if (e.actor_name and role) else (e.actor_name or "—")
    return {
        "id": f"evt:{e.pk}", "source": "event", "created_at": e.created_at,
        "category": e.category,
        "action_label": ACTION_LABELS.get(e.action, e.action),
        "actor_label": actor_label,
        "object_repr": e.object_repr or "—",
        "ip": e.ip_address or "—", "ip_hint": None,
        "result": e.result,
    }


def _login_row(ev):
    # Если пользователь не резолвлен (отказ — неверный логин/пароль),
    # показываем сырой введённый логин вместо «—», чтобы было видно, ПОД
    # КАКИМ ИМЕНЕМ пытались войти (см. ClinicLoginEvent.attempted_login).
    actor_label = ev.user.name if ev.user else (
        f"Логин: {ev.attempted_login}" if ev.attempted_login else "—")
    return {
        "id": f"login:{ev.pk}", "source": "login", "created_at": ev.created_at,
        "category": CATEGORY_LOGIN if ev.success else CATEGORY_DENY,
        "action_label": "Вход в систему" if ev.success else "Отказ во входе",
        "actor_label": actor_label,
        "object_repr": f"user/{ev.user_id}" if ev.user_id else "—",
        "ip": ev.ip_address or "—", "ip_hint": None,
        "result": "success" if ev.success else "fail",
    }


def _history_row(r):
    category = CATEGORY_DELETE if r["raw_type"] == "-" else CATEGORY_CHANGE
    ip = r.get("ip")
    if ip:
        ip_display, ip_hint = ip, None
    elif r["date"] < IP_TRACKING_SINCE:
        ip_display, ip_hint = "—", "IP не отслеживался до 22.08.2026"
    else:
        ip_display, ip_hint = "—", None
    return {
        "id": f"hist:{r['model']}:{r['hid']}", "source": "history", "created_at": r["date"],
        "category": category,
        "action_label": f"{r['type']}: {r['model_label']}",
        "actor_label": r["user"],
        "object_repr": r["title"],
        "ip": ip_display, "ip_hint": ip_hint,
        "result": "success",
    }


def _history_source_rows():
    """simple_history Patient/Treatment — те же 150 последних версий на
    модель, что и в audit_center (защита от неограниченной выборки на
    большой базе); из них уже фильтруются даты/категория/поиск ниже."""
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment
    HP = Patient.history.model
    HT = Treatment.history.model
    rows = build_history_rows(HP.objects.all(), "patient", "Пациент",
                               lambda h: f"{h.last_name} {h.first_name}".strip() or f"#{h.id}")
    rows += build_history_rows(HT.objects.all(), "treatment", "Приём", lambda h: f"Приём #{h.id}")
    return [_history_row(r) for r in rows]


def superadmin_audit_feed(*, category="all", date_from=None, date_to=None, search="", page=1, page_size=50):
    """Объединённая, отфильтрованная, пагинированная лента событий — три
    источника на лету (см. докстринг модуля), без промежуточного хранения."""
    from .models import AuditEvent, ClinicLoginEvent

    events_qs = AuditEvent.objects.order_by("-created_at")[:2000]
    logins_qs = ClinicLoginEvent.objects.select_related("user").order_by("-created_at")[:2000]

    rows = [_event_row(e) for e in events_qs]
    rows += [_login_row(ev) for ev in logins_qs]
    rows += _history_source_rows()

    # Сравниваем по БИШКЕКСКОЙ календарной дате, не по UTC — иначе диапазон
    # дат, выбранный в интерфейсе, «плывёт» на 6 часов около полуночи
    # (created_at хранится в UTC, TIME_ZONE=Asia/Bishkek).
    if date_from:
        rows = [r for r in rows if timezone.localtime(r["created_at"]).date() >= date_from]
    if date_to:
        rows = [r for r in rows if timezone.localtime(r["created_at"]).date() <= date_to]

    if category and category != "all":
        rows = [r for r in rows if r["category"] == category]

    if search:
        s = search.strip().lower()
        rows = [
            r for r in rows
            if s in (r["object_repr"] or "").lower()
            or s in (r["actor_label"] or "").lower()
            or s in (r["ip"] or "").lower()
        ]

    rows.sort(key=lambda r: r["created_at"], reverse=True)

    total = len(rows)
    page = max(1, page)
    page_size = max(1, page_size)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    num_pages = max(1, (total + page_size - 1) // page_size)
    return {"rows": page_rows, "total": total, "page": page, "num_pages": num_pages}


def _pct_change(today_n, yday_n):
    """Возвращает изменение в процентах день-к-дню, или None если вчера
    было 0 событий (деление на ноль/бессмысленный процент — не рисуем)."""
    if yday_n <= 0:
        return None
    return round((today_n - yday_n) / yday_n * 100)


def superadmin_audit_metrics():
    """Метрики плашек ленты — отдельные прямые COUNT по всей платформе
    (кросс-клиниково), НЕ из уже отфильтрованной/пагинированной ленты."""
    from .models import AuditEvent, ClinicLoginEvent, BlockedIP
    from apps.patients.models import Patient
    from apps.treatments.models import Treatment

    now = timezone.now()
    # localdate(), не now().date() — иначе «сегодня» считается по UTC-
    # суткам, а не по Asia/Bishkek (TIME_ZONE), и метрика «за сутки»
    # ошибается на 6 часов у границы дня.
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    events_today = AuditEvent.objects.filter(created_at__date=today).count()
    events_yday = AuditEvent.objects.filter(created_at__date=yesterday).count()
    logins_today = ClinicLoginEvent.objects.filter(created_at__date=today).count()
    logins_yday = ClinicLoginEvent.objects.filter(created_at__date=yesterday).count()
    hist_today = (Patient.history.model.objects.filter(history_date__date=today).count()
                  + Treatment.history.model.objects.filter(history_date__date=today).count())
    hist_yday = (Patient.history.model.objects.filter(history_date__date=yesterday).count()
                 + Treatment.history.model.objects.filter(history_date__date=yesterday).count())
    total_today = events_today + logins_today + hist_today
    total_yday = events_yday + logins_yday + hist_yday

    denials_today = ClinicLoginEvent.objects.filter(success=False, created_at__date=today).count()
    denials_yday = ClinicLoginEvent.objects.filter(success=False, created_at__date=yesterday).count()

    # Ожидающие удаления — по ВСЕМ клиникам (в отличие от Корзины самой по
    # себе, которая клиника-скоуп, см. apps.users.views._recycle_qs) —
    # здесь нужен общий счётчик для супер-админа. Импорт отложен, чтобы не
    # тянуть весь views.py при загрузке модуля.
    from apps.users.views import _recycle_models
    pending_deletions = sum(
        Model.all_objects.filter(is_deleted=True).count()
        for Model, _label in _recycle_models().values()
    )

    blocked_ips = BlockedIP.objects.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()

    return {
        "events_today": total_today, "events_pct": _pct_change(total_today, total_yday),
        "denials_today": denials_today, "denials_pct": _pct_change(denials_today, denials_yday),
        "pending_deletions": pending_deletions,
        "blocked_ips": blocked_ips,
    }


def bulk_purge_eligible_summary(days=BULK_PURGE_DEFAULT_DAYS):
    """Сводка «сколько можно безвозвратно удалить» — по модели и по клинике,
    только записи, чей deleted_at старше `days` дней (свежие удаления ещё
    можно случайно восстановить через обычную «Корзину» — не трогаем).
    Читается вкладкой «Удаления» перед запуском bulk_purge_old_deletions(),
    та же форма кросс-клиникового запроса, что и pending_deletions в
    superadmin_audit_metrics(), плюс возрастной фильтр."""
    from apps.users.views import _recycle_models
    from apps.users.models import Clinic

    threshold = timezone.now() - timedelta(days=days)
    by_model = []
    breakdown = []
    total = 0
    for kind, (Model, label) in _recycle_models().items():
        qs = Model.all_objects.filter(is_deleted=True, deleted_at__lt=threshold)
        model_total = 0
        per_clinic = qs.values("clinic_id").annotate(n=_Count("id"))
        clinic_ids = [row["clinic_id"] for row in per_clinic if row["clinic_id"]]
        clinic_names = dict(Clinic.objects.filter(pk__in=clinic_ids).values_list("pk", "name"))
        for row in per_clinic:
            n = row["n"]
            model_total += n
            breakdown.append({
                "kind": kind, "label": label,
                "clinic_id": row["clinic_id"],
                "clinic_name": clinic_names.get(row["clinic_id"], "—"),
                "count": n,
            })
        by_model.append({"kind": kind, "label": label, "count": model_total})
        total += model_total
    breakdown.sort(key=lambda r: r["count"], reverse=True)
    return {"threshold_days": days, "total": total, "by_model": by_model, "rows": breakdown}


def bulk_purge_old_deletions(actor=None, request=None, days=BULK_PURGE_DEFAULT_DAYS,
                              limit=BULK_PURGE_DEFAULT_LIMIT):
    """Безвозвратно удаляет мягко-удалённые записи (ВСЕ клиники), у которых
    deleted_at старше `days` дней — не больше `limit` объектов за вызов (см.
    BULK_PURGE_DEFAULT_LIMIT). Тот же приём удаления/обработки ProtectedError,
    что и в apps.users.views.recycle_purge, но по всей платформе и пакетно."""
    from django.db.models import ProtectedError
    from apps.users.views import _recycle_models

    threshold = timezone.now() - timedelta(days=days)
    purged, skipped_protected = 0, 0
    by_model = {}
    for kind, (Model, label) in _recycle_models().items():
        if purged >= limit:
            break
        # Материализуем в список ДО удаления (не .iterator() — на Postgres
        # он открывает серверный курсор, а мы прямо во время обхода удаляем
        # строки из той же таблицы, что курсор читает: неопределённое
        # поведение). Срез по остатку бюджета — тот же лимит, но одним
        # запросом, а не «прочитать всё и потом резать в Python».
        qs = (Model.all_objects.filter(is_deleted=True, deleted_at__lt=threshold)
              .order_by("deleted_at"))[:limit - purged]
        for obj in list(qs):
            if purged >= limit:
                break
            title = str(obj)
            obj_pk, obj_clinic = obj.pk, getattr(obj, "clinic", None)
            try:
                if kind == "patient" and hasattr(obj, "purge_with_related"):
                    obj.purge_with_related()
                else:
                    obj.delete()
                log_audit_event(
                    action="purge", category=CATEGORY_DELETE, actor=actor, request=request,
                    clinic=obj_clinic, object_model=kind, object_id=obj_pk,
                    object_repr=f"{kind}/{obj_pk} — {title}",
                )
                purged += 1
                by_model[kind] = by_model.get(kind, 0) + 1
            except ProtectedError:
                skipped_protected += 1

    log_audit_event(
        action="bulk_purge", category=CATEGORY_DELETE, actor=actor, request=request,
        object_repr=f"Массовая очистка: {purged} объектов (>{days} дн.)",
        diff=[{"field": "purged_count", "old": "0", "new": str(purged)}],
    )
    remaining = bulk_purge_eligible_summary(days)["total"]
    return {"purged": purged, "skipped_protected": skipped_protected,
            "remaining": remaining, "by_model": by_model}
