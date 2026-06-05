import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import Notification, PushSubscription


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _user_notifications(request):
    """Уведомления пользователя в рамках текущей клиники (изоляция между клиниками)."""
    from apps.tenancy import get_current_clinic
    qs = Notification.objects.filter(user=request.user)
    clinic = get_current_clinic()
    if clinic is not None:
        qs = qs.filter(clinic=clinic)
    return qs


@login_required
def notification_list(request):
    notifications = _user_notifications(request)
    return render(request, "notifications/list.html", {"notifications": notifications})


@csrf_exempt
@login_required
def push_subscribe(request):
    """Сохранить подписку устройства на web push."""
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    try:
        data = json.loads(request.body)
        sub = data.get("subscription") or data
        endpoint = sub["endpoint"]
        keys = sub.get("keys", {})
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": keys.get("p256dh", ""),
                "auth": keys.get("auth", ""),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300],
            },
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)


def web_manifest(request):
    """PWA-манифест (установка иконкой, нужно для iOS web push)."""
    name = "SADAF"
    try:
        from apps.settings_clinic.models import ClinicSettings
        name = ClinicSettings.get().name or "SADAF"
    except Exception:
        pass
    manifest = {
        "name": name + " — Клиника",
        "short_name": name,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F8FAFC",
        "theme_color": "#6366F1",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    return JsonResponse(manifest)


def service_worker(request):
    """Service Worker (должен отдаваться из корня сайта для широкого scope)."""
    js = """
self.addEventListener('push', function(event) {
  let d = {};
  try { d = event.data.json(); } catch(e) { d = { title: 'SADAF', body: event.data ? event.data.text() : '' }; }
  event.waitUntil(self.registration.showNotification(d.title || 'SADAF', {
    body: d.body || '',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: { url: d.url || '/' },
    vibrate: [100, 50, 100],
  }));
});
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list) {
    for (const c of list) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
"""
    return HttpResponse(js, content_type="application/javascript")


@login_required
def notification_poll(request):
    """JSON для браузерных уведомлений: счётчик непрочитанных + последние."""
    qs = _user_notifications(request).filter(is_read=False)
    items = [
        {"id": n.pk, "title": n.title, "body": n.body, "link": n.link}
        for n in qs[:5]
    ]
    return JsonResponse({"count": qs.count(), "items": items})


@login_required
def notification_open(request, pk):
    """Открыть уведомление: пометить прочитанным и перейти по ссылке."""
    n = _user_notifications(request).filter(pk=pk).first()
    if not n:
        return redirect("notification_list")
    n.is_read = True
    n.save(update_fields=["is_read"])
    return redirect(n.link or "notification_list")


@login_required
def mark_read(request, pk):
    _user_notifications(request).filter(pk=pk).update(is_read=True)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")


@login_required
def mark_all_read(request):
    _user_notifications(request).filter(is_read=False).update(is_read=True)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")
