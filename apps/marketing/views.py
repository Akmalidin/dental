from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import LandingLead


def landing(request):
    return render(request, "marketing/landing.html")


def directory(request):
    """Каталог всех клиник на платформе (апекс stom.asia, «Найти клинику и
    записаться») — карта + список «блоками». Клиника кликабельна для записи,
    только если у неё включён и опубликован публичный сайт (ClinicSite.
    enabled+published — тот же переключатель, что супер-админ уже включает
    в /users/clinic/<id>/overview/, apps.users.views.toggle_clinic_site) —
    иначе показываем «Запись скоро будет доступна» вместо битой ссылки на
    <slug>.CRM_BASE_DOMAIN/book/, которого без сайта не существует (см.
    apps.tenancy.StomAsiaRoutingMiddleware). Без активного филиала с
    указанным адресом — «Адрес: скоро добавим» вместо карточки/пина."""
    from django.conf import settings as dj_settings
    from apps.users.models import Clinic, Branch, ClinicSite

    domain = getattr(dj_settings, "CRM_BASE_DOMAIN", "") or getattr(dj_settings, "PUBLIC_BASE_DOMAIN", "denta.tw1.ru")
    bookable_ids = set(
        ClinicSite.objects.filter(enabled=True, published=True).values_list("clinic_id", flat=True)
    )

    clinics = []
    map_points = []
    for c in Clinic.objects.filter(is_active=True).order_by("name"):
        branches = [
            {"id": b.pk, "name": b.name, "address": b.address, "phone": b.phone,
             "lat": b.latitude, "lng": b.longitude}
            for b in Branch.objects.filter(clinic=c, is_active=True).order_by("-is_main", "name")
            if b.address.strip()
        ]
        bookable = c.pk in bookable_ids
        clinics.append({
            "clinic": c, "slug": c.slug, "bookable": bookable,
            "book_url": f"https://{c.slug}.{domain}/book/" if bookable else "",
            "branches": branches,
        })
        if bookable:
            for b in branches:
                if b["lat"] is not None and b["lng"] is not None:
                    map_points.append({
                        "clinicName": c.name, "branchId": b["id"], "branchName": b["name"],
                        "address": b["address"], "phone": b["phone"],
                        "lat": b["lat"], "lng": b["lng"],
                        "bookUrl": f"https://{c.slug}.{domain}/book/?branch={b['id']}",
                    })

    return render(request, "marketing/directory.html", {
        "clinics": clinics, "map_points": map_points,
    })


@require_POST
def landing_lead(request):
    clinic_name = (request.POST.get("clinic_name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    city = (request.POST.get("city") or "").strip()
    if not clinic_name or not phone:
        messages.error(request, "Укажите название клиники и телефон")
        return redirect("/#contact")
    LandingLead.objects.create(clinic_name=clinic_name, phone=phone, city=city)
    messages.success(request, "Заявка отправлена — свяжемся с вами в течение дня.")
    return redirect("/#contact")
