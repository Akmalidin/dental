from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from .models import Notification


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(user=request.user)
    return render(request, "notifications/list.html", {"notifications": notifications})


@login_required
def mark_read(request, pk):
    Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
    return JsonResponse({"ok": True})


@login_required
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"ok": True})
