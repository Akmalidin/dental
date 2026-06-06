"""Публичный сайт клиники (поддомен). Без логина. Клиника берётся из request.public_clinic
(ставится PublicSiteMiddleware)."""
from django.shortcuts import render
from django.http import Http404


def _ctx(request):
    clinic = getattr(request, "public_clinic", None)
    site = getattr(request, "public_site", None)
    if clinic is None or site is None:
        raise Http404("Сайт недоступен")
    return clinic, site


def public_home(request):
    clinic, site = _ctx(request)

    doctors = []
    if site.show_doctors:
        from apps.users.models import clinic_doctors
        doctors = list(clinic_doctors(clinic)[:24])

    services = []
    if site.show_services:
        from apps.services.models import Service
        services = list(
            Service.objects.filter(is_active=True).select_related("category")
            .order_by("category__sort_order", "name")[:60]
        )

    from apps.users.models import Branch
    branches = list(Branch.objects.filter(is_active=True))

    return render(request, "public/home.html", {
        "clinic": clinic, "site": site,
        "doctors": doctors, "services": services, "branches": branches,
    })


def public_book(request):
    """Онлайн-запись (Phase C). Пока — заглушка-страница."""
    clinic, site = _ctx(request)
    return render(request, "public/booking.html", {"clinic": clinic, "site": site})
