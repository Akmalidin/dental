from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from .models import Notification


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(user=request.user)
    return render(request, "notifications/list.html", {"notifications": notifications})


@login_required
def notification_poll(request):
    """JSON для браузерных уведомлений: счётчик непрочитанных + последние."""
    qs = Notification.objects.filter(user=request.user, is_read=False)
    items = [
        {"id": n.pk, "title": n.title, "body": n.body, "link": n.link}
        for n in qs[:5]
    ]
    return JsonResponse({"count": qs.count(), "items": items})


@login_required
def notification_open(request, pk):
    """Открыть уведомление: пометить прочитанным и перейти по ссылке."""
    n = Notification.objects.filter(pk=pk, user=request.user).first()
    if not n:
        return redirect("notification_list")
    n.is_read = True
    n.save(update_fields=["is_read"])
    return redirect(n.link or "notification_list")


@login_required
def mark_read(request, pk):
    Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")


@login_required
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect("notification_list")
