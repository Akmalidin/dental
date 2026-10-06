"""Перевести вебхуки мессенджеров со старого сервера на новый.

После переезда сервера Green-API (WhatsApp и Telegram-аккаунт) и боты
Telegram продолжали слать входящие на старый домен — сообщения пациентов
не доходили до CRM (на проде: с 19.09 ни одного входящего WhatsApp).

    manage.py fix_webhooks --old app.denta.tw1.ru --new app.sadaf.kg          # только показать
    manage.py fix_webhooks --old app.denta.tw1.ru --new app.sadaf.kg --apply  # исправить

Меняется только домен в адресе — путь, ключ (?key=) и секрет вебхука
Telegram сохраняются. Адреса, которые указывают на другой домен, не трогаем.
"""
import json
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.management.base import BaseCommand


def _mask(url):
    import re
    return re.sub(r"(key=)[^&]+", r"\1***", url or "")


def _ga(base, idi, token, method, payload=None):
    url = "%s/waInstance%s/%s/%s" % ((base or "https://api.greenapi.com").rstrip("/"), idi, method, token)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class Command(BaseCommand):
    help = "Перевести вебхуки WhatsApp/Telegram со старого домена на новый"

    def add_arguments(self, parser):
        parser.add_argument("--old", required=True)
        parser.add_argument("--new", required=True)
        parser.add_argument("--apply", action="store_true")

    def _swap(self, url, old, new):
        parts = urlsplit(url or "")
        if parts.hostname != old:
            return None
        netloc = new + (":%s" % parts.port if parts.port else "")
        return urlunsplit((parts.scheme or "https", netloc, parts.path, parts.query, parts.fragment))

    def _green(self, label, base, idi, token, old, new, apply):
        if not (idi and token):
            return
        try:
            cur = _ga(base, idi, token, "getSettings").get("webhookUrl", "")
        except Exception as e:  # noqa: BLE001
            self.stdout.write("%s: getSettings не удался: %s" % (label, e))
            return
        fixed = self._swap(cur, old, new)
        self.stdout.write("%s: %s%s" % (label, _mask(cur), (" → " + _mask(fixed)) if fixed else " (не меняем)"))
        if fixed and apply:
            res = _ga(base, idi, token, "setSettings", {"webhookUrl": fixed, "incomingWebhook": "yes",
                                                        "outgoingMessageWebhook": "yes"})
            self.stdout.write("   setSettings: %s" % res)

    def handle(self, old, new, apply, **o):
        self._green("WhatsApp (общий)", settings.GREENAPI_API_URL, settings.GREENAPI_ID_INSTANCE,
                    settings.GREENAPI_TOKEN, old, new, apply)
        self._green("Telegram-аккаунт (Green-API)", getattr(settings, "TELEGRAM_GA_API_URL", ""),
                    getattr(settings, "TELEGRAM_GA_ID_INSTANCE", ""), getattr(settings, "TELEGRAM_GA_TOKEN", ""),
                    old, new, apply)
        from apps.settings_clinic.models import ClinicSettings
        from apps.notifications.telegram import tg_get_webhook_info, tg_set_webhook
        for cs in ClinicSettings.objects.exclude(clinic=None).select_related("clinic"):
            if cs.wa_id_instance and cs.wa_token:
                self._green("WhatsApp клиники %s" % cs.name, cs.wa_api_url, cs.wa_id_instance, cs.wa_token,
                            old, new, apply)
            if cs.telegram_bot_token:
                info = tg_get_webhook_info(cs.telegram_bot_token)
                cur = (info.get("result") or {}).get("url", "")
                fixed = self._swap(cur, old, new)
                self.stdout.write("Telegram-бот клиники %s: %s%s" % (cs.name, cur or "(нет)",
                                                                    (" → " + fixed) if fixed else " (не меняем)"))
                if fixed and apply:
                    res = tg_set_webhook(cs.telegram_bot_token, fixed, secret_token=cs.telegram_webhook_secret or None)
                    self.stdout.write("   setWebhook: %s" % res.get("ok"))
        if not apply:
            self.stdout.write("Это был просмотр. Для исправления добавьте --apply.")
