"""Проверка надёжности паролей и принудительная смена слабого пароля.

Слабый пароль (короче 8 символов, из словаря частых, только цифры, похож на
логин/имя) не сбрасывается — это заблокировало бы людей. Вместо этого при
входе в сессию ставится флаг, и ForcePasswordChangeMiddleware не пускает
дальше страницы смены пароля, пока пользователь не задаст надёжный.
"""
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect

SESSION_FLAG = "must_change_password"
CHANGE_URL = "/password-change/"

_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ("login", "name", "email", "phone")}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

_MESSAGES = {
    "password_too_short": "Пароль слишком короткий — минимум 8 символов",
    "password_too_common": "Этот пароль слишком распространён",
    "password_entirely_numeric": "Пароль не может состоять только из цифр",
    "password_too_similar": "Пароль слишком похож на логин или имя",
}


def password_problems(password, user=None):
    """Список понятных (русских) причин, почему пароль ненадёжен; [] — пароль годится."""
    validators = password_validation.get_password_validators(_VALIDATORS)
    try:
        password_validation.validate_password(password or "", user, password_validators=validators)
    except ValidationError as e:
        out = []
        for err in e.error_list:
            msg = _MESSAGES.get(err.code) or " ".join(err.messages)
            if msg not in out:
                out.append(msg)
        return out
    return []


def is_weak(password, user=None):
    return bool(password_problems(password, user))


_ALLOWED_PREFIXES = (
    CHANGE_URL, "/logout", "/static/", "/media/", "/healthz", "/favicon", "/i18n/", "/jsi18n",
    "/manifest", "/sw.js", "/stop-impersonate",
)


class ForcePasswordChangeMiddleware:
    """Пока в сессии стоит флаг слабого пароля — всё, кроме страницы смены
    пароля и выхода, недоступно. Флаг ставит login_view, снимает
    password_change_view после успешной смены."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, "session", None)
        user = getattr(request, "user", None)
        if (session is not None and session.get(SESSION_FLAG)
                and user is not None and user.is_authenticated
                and not getattr(request, "impersonator", None)
                and not request.path.startswith(_ALLOWED_PREFIXES)
                and not request.path.rstrip("/").endswith("/stop-impersonate")):
            wants_json = (request.method != "GET"
                          or request.headers.get("x-requested-with") == "XMLHttpRequest"
                          or "application/json" in request.headers.get("accept", ""))
            if wants_json:
                return JsonResponse({"ok": False, "error": "Нужно сменить пароль", "redirect": CHANGE_URL},
                                    status=403)
            return redirect(CHANGE_URL)
        return self.get_response(request)
