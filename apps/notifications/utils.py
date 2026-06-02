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


def notify_admins(text: str):
    """Send a notification to all admin/superadmin users who have telegram_id."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    admins = User.objects.filter(
        role__name__in=["superadmin", "admin_main", "admin"],
        telegram_id__isnull=False,
        is_active=True,
    ).values_list("telegram_id", flat=True)
    for chat_id in admins:
        send_telegram(chat_id, text)
