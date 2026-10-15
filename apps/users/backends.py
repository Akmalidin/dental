from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class LoginBackend(ModelBackend):
    """Authenticate by login OR email."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        login = username or kwargs.get("login")
        if not login:
            return None
        try:
            user = User.objects.get(login=login)
        except User.DoesNotExist:
            # email не уникален: при двух сотрудниках с одним email входить
            # по нему нельзя (раньше — MultipleObjectsReturned → 500).
            matches = list(User.objects.filter(email__iexact=login)[:2]) if "@" in login else []
            if len(matches) != 1:
                return None
            user = matches[0]

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
