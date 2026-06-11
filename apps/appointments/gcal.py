"""Синхронизация записей с Google Calendar врача (OAuth2, REST через urllib).

Без тяжёлых google-библиотек: OAuth2 и Calendar API дёргаем напрямую.
Безопасно-выключено: если ключи не заданы или у врача нет подключённого аккаунта —
функции тихо ничего не делают и не падают.

Настройка (env на сервере):
  GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI
"""
import json
import logging
import urllib.parse
import urllib.request
import urllib.error
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

log = logging.getLogger("apps")

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://www.googleapis.com/oauth2/v3/userinfo"
CAL_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPE = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/userinfo.email"


def gcal_enabled():
    return bool(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
                and getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", ""))


def redirect_uri():
    return getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI",
                   "https://app.denta.tw1.ru/google/calendar/callback/")


def auth_url(state):
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",          # всегда выдаём refresh_token
        "include_granted_scopes": "true",
        "state": state,
    }
    return AUTH_URI + "?" + urllib.parse.urlencode(params)


def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def exchange_code(code):
    """code → {access_token, refresh_token, expires_in}."""
    return _post_form(TOKEN_URI, {
        "code": code,
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    })


def userinfo_email(access_token):
    try:
        req = urllib.request.Request(USERINFO_URI, headers={"Authorization": "Bearer " + access_token})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("email", "")
    except Exception:
        return ""


def _valid_access_token(account):
    """Вернуть рабочий access_token, при необходимости обновив по refresh_token."""
    now = timezone.now()
    if account.access_token and account.token_expiry and account.token_expiry > now + timedelta(seconds=60):
        return account.access_token
    if not account.refresh_token:
        return None
    try:
        data = _post_form(TOKEN_URI, {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": account.refresh_token,
            "grant_type": "refresh_token",
        })
    except Exception as e:  # noqa: BLE001
        log.warning("Google token refresh failed: %s", e)
        return None
    token = data.get("access_token")
    if not token:
        return None
    account.access_token = token
    account.token_expiry = now + timedelta(seconds=int(data.get("expires_in", 3600)))
    account.save(update_fields=["access_token", "token_expiry"])
    return token


def _event_payload(appt):
    tz = getattr(settings, "TIME_ZONE", "Asia/Bishkek")
    start = timezone.localtime(appt.start_at)
    end = timezone.localtime(appt.end_at)
    patient = appt.patient.full_name if appt.patient_id else "Пациент"
    service = appt.service.name if appt.service_id else ""
    summary = "%s%s" % (patient, (" — " + service) if service else "")
    desc_lines = []
    if appt.patient_id and appt.patient.phone:
        desc_lines.append("📞 " + appt.patient.phone)
    if appt.get_status_display():
        desc_lines.append("Статус: " + appt.get_status_display())
    if appt.notes:
        desc_lines.append(appt.notes)
    desc_lines.append("Запись из CRM SADAF")
    return {
        "summary": summary,
        "description": "\n".join(desc_lines),
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
    }


def _account_for(doctor):
    if doctor is None:
        return None
    from apps.users.models import GoogleCalendarAccount
    return GoogleCalendarAccount.objects.filter(user=doctor).first()


def push_event(appt):
    """Создать или обновить событие в Google Calendar врача. Тихо пропускает, если не настроено."""
    if not gcal_enabled():
        return
    try:
        account = _account_for(appt.doctor)
        if account is None:
            return
        token = _valid_access_token(account)
        if not token:
            return
        payload = json.dumps(_event_payload(appt)).encode("utf-8")
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if appt.gcal_event_id:
            url = CAL_BASE + "/" + urllib.parse.quote(appt.gcal_event_id)
            req = urllib.request.Request(url, data=payload, method="PATCH", headers=headers)
        else:
            req = urllib.request.Request(CAL_BASE, data=payload, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        ev_id = data.get("id")
        if ev_id and ev_id != appt.gcal_event_id:
            type(appt).all_objects.filter(pk=appt.pk).update(gcal_event_id=ev_id)
            appt.gcal_event_id = ev_id
    except urllib.error.HTTPError as e:
        body = e.read()[:300]
        log.warning("Google Calendar push failed (%s): %s", e.code, body)
        # Событие удалили вручную в Google → создадим заново при следующем пуше
        if e.code in (404, 410) and appt.gcal_event_id:
            type(appt).all_objects.filter(pk=appt.pk).update(gcal_event_id="")
    except Exception as e:  # noqa: BLE001
        log.warning("Google Calendar push error: %s", e)


def delete_event(appt):
    """Удалить событие из Google Calendar врача."""
    if not gcal_enabled() or not appt.gcal_event_id:
        return
    try:
        account = _account_for(appt.doctor)
        if account is None:
            return
        token = _valid_access_token(account)
        if not token:
            return
        url = CAL_BASE + "/" + urllib.parse.quote(appt.gcal_event_id)
        req = urllib.request.Request(url, method="DELETE",
                                     headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        type(appt).all_objects.filter(pk=appt.pk).update(gcal_event_id="")
        appt.gcal_event_id = ""
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):  # уже нет — ок
            type(appt).all_objects.filter(pk=appt.pk).update(gcal_event_id="")
        else:
            log.warning("Google Calendar delete failed (%s)", e.code)
    except Exception as e:  # noqa: BLE001
        log.warning("Google Calendar delete error: %s", e)
