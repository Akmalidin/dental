from functools import wraps
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


def require_permission(perm_code):
    """Серверная проверка тонкого права (RBAC MVP). В отличие от role_required
    (проверка по имени роли) — проверяет конкретное действие через
    User.has_granular_perm() (учитывает и основную роль, и дополнительные —
    в отличие от голого Role.has_perm() на одной роли, см. модель User;
    раньше здесь была именно эта асимметрия — доп. роль права не давала,
    хотя role_required/has_role() всегда учитывали обе). Суперадмин
    проходит всегда. Возвращает 403 напрямую (не raise PermissionDenied) —
    так декоратор ведёт себя одинаково и в полном request/response цикле,
    и при прямом вызове view в тестах.

    Тело 403-ответа — не голый текст: XHR-запросы (X-Requested-With,
    fetch с credentials — касса и т.п.) получают JSON {"error", "error_key"},
    который уже понимает apiErrorMessage() в base.html; обычные POST-формы
    (postForm() + extractFormError()) получают HTML-фрагмент с классом
    .bg-red-50 — тем же, который extractFormError() уже ищет для форм
    сотрудника и т.п. Раньше оба пути падали на общий fallback-текст
    («Не удалось сохранить»/«Проверьте введённые данные»), и реальная
    причина («не хватает права X») никогда не доходила до пользователя."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("/login/")
            if request.user.is_superadmin:
                return view_func(request, *args, **kwargs)
            if not request.user.has_granular_perm(perm_code):
                from .models import Permission
                label = Permission.objects.filter(code=perm_code).values_list("label", flat=True).first() or perm_code
                msg = str(_(
                    "Недостаточно прав: «%(label)s». Обратитесь к директору клиники — "
                    "выдать право можно в Настройках → Роли и права доступа."
                ) % {"label": label})
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse({"error": msg, "error_key": "missing_permission"}, status=403)
                return HttpResponseForbidden(f'<div class="bg-red-50">{msg}</div>')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_superadmin(view_func):
    """Строже, чем require_permission(...) — не делегируется через RBAC-права
    вообще, только реальный суперадмин (никакая роль/грант не подходит).
    Для действий вроде удаления платежа: раньше это была
    require_permission("finance.delete_payment") — но тогда её мог выдать
    себе/другим любой admin_main через редактор ролей, а кнопка в новом
    интерфейсе (deletePayment(), base.html) и так уже скрыта у всех, кроме
    IS_SUPERADMIN, — сервер должен требовать ровно то же самое, а не более
    широкий permission-based доступ. Тот же формат ответа, что и у
    require_permission (403 напрямую, не redirect) — чтобы JS, который
    проверяет res.redirected, не принял отказ за успех."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("/login/")
        if not request.user.is_superadmin:
            return HttpResponseForbidden("Superadmin only")
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(*roles):
    """Restrict view to users with specified roles."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("/login/")
            if not request.user.is_superadmin and not request.user.has_role(*roles):
                messages.error(request, _("У вас нет доступа к этой странице"))
                return redirect("/")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
