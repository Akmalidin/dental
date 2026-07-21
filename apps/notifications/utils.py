from django.conf import settings


def send_telegram(chat_id: int, text: str) -> bool:
    """Send a Telegram message via Bot API. Returns True on success."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        return False
    try:
        import urllib.request, urllib.parse, json
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def notify_admins(text: str, clinic=None):
    """Send a notification to admin/superadmin users who have telegram_id.

    Pass `clinic` to restrict to that clinic's own admins (avoids leaking one
    clinic's financial data to another clinic's staff).
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    qs = User.objects.filter(
        role__name__in=["superadmin", "admin_main", "admin"],
        telegram_id__isnull=False,
        is_active=True,
    )
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    for chat_id in qs.values_list("telegram_id", flat=True):
        send_telegram(chat_id, text)
