from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


def require_permission(perm_code):
    """Серверная проверка тонкого права (RBAC MVP). В отличие от role_required
    (проверка по имени роли) — проверяет конкретное действие через
    Role.has_perm(). Суперадмин проходит всегда. Возвращает 403 напрямую
    (не raise PermissionDenied) — так декоратор ведёт себя одинаково и в
    полном request/response цикле, и при прямом вызове view в тестах."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("/login/")
            if request.user.is_superadmin:
                return view_func(request, *args, **kwargs)
            if not request.user.role_id or not request.user.role.has_perm(perm_code):
                return HttpResponseForbidden(f"Missing permission: {perm_code}")
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


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
