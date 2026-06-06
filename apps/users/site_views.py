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
    map_points = [
        {"name": b.name, "address": b.address, "phone": b.phone,
         "lat": b.latitude, "lng": b.longitude}
        for b in branches if b.latitude is not None and b.longitude is not None
    ]

    return render(request, "public/home.html", {
        "clinic": clinic, "site": site,
        "doctors": doctors, "services": services, "branches": branches,
        "map_points": map_points,
    })


def public_service(request, pk):
    """Полная страница об услуге/лечении."""
    clinic, site = _ctx(request)
    from apps.services.models import Service
    service = Service.objects.filter(pk=pk, is_active=True).select_related("category").first()
    if service is None:
        raise Http404("Услуга не найдена")
    related = list(
        Service.objects.filter(is_active=True, category=service.category)
        .exclude(pk=service.pk)[:6]
    )
    return render(request, "public/service.html", {
        "clinic": clinic, "site": site, "service": service, "related": related,
    })


def public_book(request):
    """Онлайн-запись (Phase C). Пока — заглушка-страница."""
    clinic, site = _ctx(request)
    return render(request, "public/booking.html", {"clinic": clinic, "site": site})
