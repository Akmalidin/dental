from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


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
