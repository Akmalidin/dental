from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.db.models import Count
from apps.tenants.models import Tenant, Subscription
from django.utils import timezone
from datetime import date


def superadmin_required(view_func):
    from functools import wraps
    from django.conf import settings

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("/login/")
        if not (request.user.is_superuser or request.user.email == settings.SUPERADMIN_EMAIL):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Доступ запрещён")
        return view_func(request, *args, **kwargs)
    return wrapper


@superadmin_required
def central_dashboard(request):
    tenants = Tenant.objects.select_related("subscription").annotate(
        domain_count=Count("domains")
    )
    active_count = Tenant.objects.filter(is_active=True).count()
    trial_count = Subscription.objects.filter(plan="trial", is_active=True).count()
    blocked_count = Subscription.objects.filter(is_blocked=True).count()
    return render(request, "dashboard/superadmin.html", {
        "tenants": tenants,
        "tenant_count": active_count,
        "subscription_count": Subscription.objects.filter(is_active=True).count(),
        "trial_count": trial_count,
        "blocked_count": blocked_count,
    })


@superadmin_required
def tenant_list(request):
    tenants = Tenant.objects.select_related("subscription").order_by("-id")
    return render(request, "central/tenants.html", {"tenants": tenants})


@superadmin_required
def tenant_create(request):
    from .forms import TenantCreateForm
    form = TenantCreateForm(request.POST or None)
    if form.is_valid():
        tenant = form.save()
        messages.success(request, _("Клиника создана"))
        return redirect("central_tenant_list")
    return render(request, "central/tenant_form.html", {"form": form})


@superadmin_required
def tenant_block(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    if request.method == "POST":
        sub = getattr(tenant, "subscription", None)
        if sub:
            sub.is_blocked = True
            sub.save()
        tenant.is_active = False
        tenant.save()
        messages.success(request, _("Клиника заблокирована"))
        return redirect("central_tenant_list")
    return render(request, "central/confirm_block.html", {"tenant": tenant})


@superadmin_required
def tenant_unblock(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    if request.method == "POST":
        sub = getattr(tenant, "subscription", None)
        if sub:
            sub.is_blocked = False
            sub.is_active = True
            sub.save()
        tenant.is_active = True
        tenant.save()
        messages.success(request, _("Клиника разблокирована"))
        return redirect("central_tenant_list")
    return render(request, "central/confirm_block.html", {"tenant": tenant, "unblock": True})


@superadmin_required
def subscription_list(request):
    subscriptions = Subscription.objects.select_related("tenant").order_by("-tenant__id")
    return render(request, "central/subscriptions.html", {"subscriptions": subscriptions})
