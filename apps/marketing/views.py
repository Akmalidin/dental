from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import LandingLead


def _domain():
    from django.conf import settings as dj_settings
    return getattr(dj_settings, "CRM_BASE_DOMAIN", "") or getattr(dj_settings, "PUBLIC_BASE_DOMAIN", "denta.tw1.ru")


def landing(request):
    return render(request, "marketing/landing.html")


def robots(request):
    """robots.txt апекса stom.asia — публичный маркетинговый сайт,
    индексация разрешена целиком (в отличие от app.sadaf.kg, см.
    config/urls_dev.py _app_robots — там Disallow: /, это приватный вход
    персонала). Поддомены клиник (<slug>.stom.asia) — отдельный robots.txt
    через apps.users.site_views.public_robots, сюда не относится."""
    base = request.build_absolute_uri("/")
    content = f"User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n"
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


def sitemap(request):
    """sitemap.xml апекса stom.asia — главная и каталог клиник (/book/).
    Публичные сайты отдельных клиник живут на своих поддоменах и в этот
    sitemap не входят (у каждой клиники — свой, см. public_sitemap)."""
    base = request.build_absolute_uri("/").rstrip("/")
    urls = [base + "/", base + "/book/"]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        parts.append(f"  <url><loc>{u}</loc></url>")
    parts.append("</urlset>")
    return HttpResponse("\n".join(parts), content_type="application/xml; charset=utf-8")


def directory(request):
    """Каталог всех клиник на платформе (апекс stom.asia, «Найти клинику и
    записаться») — карта + список «блоками». Если у клиники включён и
    опубликован публичный сайт (ClinicSite.enabled+published — тот же
    переключатель, что супер-админ уже включает в
    /users/clinic/<id>/overview/, apps.users.views.toggle_clinic_site) —
    запись идёт на её сайт (<slug>.CRM_BASE_DOMAIN/book/). Без сайта —
    запись всё равно доступна через общую страницу на самом апексе
    (book_clinic, /book/<slug>/, без DNS/поддомена — см. book_clinic ниже),
    поэтому каждая активная клиника теперь кликабельна для записи. Без
    активного филиала с указанным адресом — «Адрес: скоро добавим» вместо
    карточки/пина."""
    from apps.users.models import Clinic, Branch, ClinicSite

    domain = _domain()
    site_ids = set(
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
        has_site = c.pk in site_ids
        book_url = f"https://{c.slug}.{domain}/book/" if has_site else f"/book/{c.slug}/"
        clinics.append({
            "clinic": c, "slug": c.slug, "bookable": True, "has_site": has_site,
            "book_url": book_url, "branches": branches,
        })
        for b in branches:
            if b["lat"] is not None and b["lng"] is not None:
                map_points.append({
                    "clinicName": c.name, "branchId": b["id"], "branchName": b["name"],
                    "address": b["address"], "phone": b["phone"],
                    "lat": b["lat"], "lng": b["lng"],
                    "bookUrl": f"{book_url}?branch={b['id']}",
                })

    # Местоположение посетителя по IP (без запроса разрешения в браузере):
    # карта центрируется на его городе, ближайшие клиники — первыми в списке.
    # Не определилось (локальный IP, сервис недоступен) — всё как раньше.
    from apps.tenancy import get_client_ip
    from apps.users.geoip import get_ip_latlon
    user_loc = get_ip_latlon(get_client_ip(request))
    if user_loc:
        for item in clinics:
            dists = [_distance_km(user_loc["lat"], user_loc["lng"], b["lat"], b["lng"])
                     for b in item["branches"] if b["lat"] is not None and b["lng"] is not None]
            item["distance_km"] = round(min(dists)) if dists else None
        clinics.sort(key=lambda i: (i["distance_km"] is None, i["distance_km"] or 0))

    from django.conf import settings as dj_settings
    return render(request, "marketing/directory.html", {
        "clinics": clinics, "map_points": map_points, "user_loc": user_loc,
        "google_maps_key": getattr(dj_settings, "GOOGLE_MAPS_API_KEY", ""),
    })


def _distance_km(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def book_clinic(request, slug):
    """Общая страница записи БЕЗ отдельного сайта клиники (апекс
    stom.asia/book/<slug>/) — для клиник без включённого/опубликованного
    ClinicSite (см. directory() выше): та же форма (public/booking.html),
    что и на поддомене клиники, но по прямой ссылке апекса — без
    DNS/поддомена, которых у такой клиники ещё нет."""
    from apps.users.models import Clinic
    from apps.users.site_views import book_context_for, tg_bot_link_for
    from apps.tenancy import set_current_clinic

    clinic = Clinic.objects.filter(slug=slug, is_active=True).first()
    if clinic is None:
        raise Http404("Клиника не найдена")
    set_current_clinic(clinic)
    ctx = book_context_for(clinic, request.GET.get("branch"))
    return render(request, "public/booking.html", {
        "clinic": clinic, "site": None, **ctx,
        "book_slots_url": f"/book/{slug}/slots/", "book_submit_url": f"/book/{slug}/submit/",
        "back_url": "/book/", "back_label": "← К клиникам",
        "tg_bot_link": tg_bot_link_for(clinic),
    })


def book_clinic_slots(request, slug):
    """Свободные часовые слоты врача на дату (JSON) — для book_clinic."""
    from apps.users.models import Clinic
    from apps.users.site_views import slots_for_doctor
    from apps.tenancy import set_current_clinic

    clinic = Clinic.objects.filter(slug=slug, is_active=True).first()
    if clinic is None:
        return JsonResponse({"slots": []}, status=404)
    set_current_clinic(clinic)
    slots = slots_for_doctor(clinic, request.GET.get("doctor"), request.GET.get("date"))
    return JsonResponse({"slots": slots})


def book_clinic_submit(request, slug):
    """Создать заявку с общей страницы записи (book_clinic) — та же логика,
    что и с сайта клиники (apps.users.site_views.submit_booking)."""
    from apps.users.models import Clinic
    from apps.users.site_views import submit_booking
    from apps.tenancy import set_current_clinic

    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST"}, status=405)
    clinic = Clinic.objects.filter(slug=slug, is_active=True).first()
    if clinic is None:
        return JsonResponse({"ok": False, "error": "Клиника не найдена"}, status=404)
    set_current_clinic(clinic)
    return submit_booking(request, clinic)


@require_POST
def landing_lead(request):
    clinic_name = (request.POST.get("clinic_name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    city = (request.POST.get("city") or "").strip()
    if not clinic_name or not phone:
        messages.error(request, "Укажите название клиники и телефон")
        return redirect("/#contact")
    LandingLead.objects.create(clinic_name=clinic_name, phone=phone, city=city)
    # Раньше такие заявки лежали только в django-admin и никто о них не
    # узнавал — уведомляем супер-админов (колокольчик + web push), тем же
    # способом, что и запрос доступа (apps.users.views.clinic_access_request).
    try:
        from apps.users.models import User, Role
        from apps.notifications.models import Notification
        for su in User.objects.filter(role__name=Role.SUPERADMIN, is_active=True):
            Notification.send(
                su, "Заявка на подключение: %s" % clinic_name,
                body=phone + (" — %s" % city if city else ""),
                type="system", link="/django-admin/marketing/landinglead/",
            )
    except Exception:
        pass
    messages.success(request, "Заявка отправлена — свяжемся с вами в течение дня.")
    return redirect("/#contact")
