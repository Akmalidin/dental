"""Отправка Web Push уведомлений через VAPID (pywebpush)."""
import base64
import json
from django.conf import settings


def _private_pem():
    b64 = getattr(settings, "VAPID_PRIVATE_B64", "")
    if not b64:
        return None
    try:
        return base64.b64decode(b64).decode()
    except Exception:
        return None


# Сервер шлёт POST на endpoint подписки — только https-адреса известных
# push-сервисов браузеров, а не любой адрес (127.0.0.1, 169.254.169.254...).
_PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "updates.push.services.mozilla.com",
               "push.services.mozilla.com", "notify.windows.com", "push.apple.com")


def push_endpoint_ok(endpoint):
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(str(endpoint or ""))
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or port not in (None, 443) or parts.username:
        return False
    return any(host == h or host.endswith("." + h) for h in _PUSH_HOSTS)


def send_web_push(user, title, body="", url="/"):
    """Отправить push на все устройства пользователя. Истёкшие подписки удаляются."""
    pem = _private_pem()
    if not pem:
        return 0
    from pywebpush import webpush, WebPushException
    from .models import PushSubscription

    payload = json.dumps({"title": title, "body": body or "", "url": url or "/"})
    claims = {"sub": getattr(settings, "VAPID_CLAIM_EMAIL", "mailto:admin@example.com")}
    sent = 0
    for s in PushSubscription.objects.filter(user=user):
        if not push_endpoint_ok(s.endpoint):
            continue
        try:
            webpush(
                subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                data=payload,
                vapid_private_key=pem,
                vapid_claims=dict(claims),
            )
            sent += 1
        except WebPushException as e:
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code in (404, 410):
                s.delete()  # подписка больше не действительна
        except Exception:
            pass
    return sent
