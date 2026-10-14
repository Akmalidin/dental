"""«Что может этот сотрудник» (Персонал → 🔑 Доступы): итог всех правил
доступа одной таблицей — разделы (личные «Разделы» + блокировки тарифа),
действия (права ролей), правила, зашитые в код (только директор и т.п.),
филиалы. Считается по СОХРАНЁННЫМ настройкам сотрудника."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .models import SECTIONS, Permission, User

DIRECTOR_ONLY = [
    "Зарплаты: расчёт, схемы, выплаты",
    "Сотрудники: пароли, удаление",
    "Филиалы, кабинеты, графики работы врачей",
    "Настройки клиники, справочники, шаблоны карт, документы",
    "Безвозвратное удаление из корзины",
]


def _role_names(u):
    names = [u.role.display_name] if u.role_id else []
    names += [r.display_name for r in u.roles.all()]
    return names


def summary(u, clinic):
    from apps.settings_clinic.models import ClinicSettings
    blocked = set((clinic.blocked_features or []) if clinic is not None else [])
    director = u.is_superadmin or u.is_admin_main
    tech_only = u.is_technician_only

    sections = []
    for key, label, _url in SECTIONS:
        if key == "dashboard":
            continue
        if tech_only:
            ok = False
            why = "у техника только «Мои заказы» и «Касса»"
        elif key in blocked:
            ok, why = False, "отключено тарифом клиники"
        elif not u.can_access(key):
            ok, why = False, "не отмечено в «Разделах» сотрудника"
        else:
            ok = True
            why = "полный доступ" if u.allowed_sections is None or u.is_superadmin else "отмечено в «Разделах»"
        sections.append({"label": label, "ok": ok, "why": why})
    if tech_only:
        sections.insert(0, {"label": "Мои заказы (кабинет техника) и Касса", "ok": True,
                            "why": "роль «Техник» — отдельный кабинет"})

    grant_by = {}
    roles = ([u.role] if u.role_id else []) + list(u.roles.all())
    for r in roles:
        for code in r.granular_permissions.values_list("code", flat=True):
            grant_by.setdefault(code, []).append(r.display_name)
    actions = []
    for p in Permission.objects.order_by("category", "sort_order", "label"):
        ok = u.is_superadmin or p.code in grant_by
        actions.append({"label": p.label, "ok": ok,
                        "why": ("суперадмин" if u.is_superadmin and p.code not in grant_by
                                else "роль «" + "», «".join(grant_by[p.code]) + "»" if ok
                                else "нет у роли «" + "», «".join(_role_names(u) or ["—"]) + "»")})

    cs = ClinicSettings.get()
    special = [{"label": t, "ok": director, "why": "только директор" + ("" if director else " — у сотрудника другая роль")}
               for t in DIRECTOR_ONLY]
    admin_like = u.is_superadmin or u.is_admin
    special += [
        {"label": "Рассрочки: отмена, настройки напоминаний", "ok": admin_like,
         "why": "директор и администратор"},
        {"label": "Лаборатория: вход техника в кабинет, подключение по коду", "ok": admin_like,
         "why": "директор и администратор"},
        {"label": "Журнал посещений", "ok": bool((director or cs.visits_journal_staff) and u.can_access("patients")),
         "why": "директор всегда; остальные — если включено в настройках клиники"
                + ("" if cs.visits_journal_staff else " (сейчас выключено)")},
        {"label": "Корзина (восстановление удалённого)",
         "ok": bool((director or cs.recycle_bin_staff) and admin_like and u.can_access("recycle")),
         "why": "директор; администратор — если включено в настройках клиники"},
    ]
    branches = [b.name for b in u.branches.filter(is_active=True)]
    return {
        "name": u.name or u.login, "roles": _role_names(u), "active": u.is_active,
        "fullAccess": u.allowed_sections is None, "techOnly": tech_only,
        "branches": branches,
        "sections": sections, "actions": actions, "special": special,
    }


@login_required
def staff_access(request, pk):
    me = request.user
    if not (me.is_superadmin or me.is_admin_main or me.has_granular_perm("staff.manage")):
        return JsonResponse({"ok": False, "error": "Нет доступа"}, status=403)
    from apps.tenancy import get_current_clinic
    clinic = get_current_clinic() or me.clinic
    qs = User.objects.filter(pk=pk).select_related("role", "clinic")
    if not me.is_superadmin:
        qs = qs.filter(clinic=me.clinic)
    u = qs.first()
    if u is None:
        return JsonResponse({"ok": False, "error": "Сотрудник не найден"}, status=404)
    return JsonResponse({"ok": True, **summary(u, u.clinic or clinic)})

