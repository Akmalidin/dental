"""Защищённая выдача файлов пациентов: снимки и документы приёмов
(treatments/), вложения переписки WhatsApp/Telegram (chat_media/), файлы
заказов техникам (tech_orders/).

Раньше nginx отдавал всю папку /media/ без входа — снимок можно было открыть,
зная или угадав адрес. Теперь эти папки nginx передаёт сюда, а файл
отдаётся только:
- вошедшему сотруднику клиники, которой принадлежит файл (суперадмину — любой);
- или по подписанной ссылке (?s=…) с ограниченным сроком — так открываются
  снимки на публичной странице чека по QR-коду.
Сам файл на сервере отдаёт nginx (X-Accel-Redirect на внутренний
/protected-media/), без нагрузки на Django; без nginx (офлайн, разработка) —
FileResponse.

Логотипы, аватары и картинки сайта клиники (clinic/, avatars/, site/)
остаются публичными."""
import mimetypes
import os

from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404, HttpResponse

PROTECTED_PREFIXES = ("treatments/", "chat_media/", "tech_orders/")
SIGN_SALT = "protected-media"
SIGN_MAX_AGE = 60 * 60 * 24 * 30   # 30 дней


def is_protected(name):
    return bool(name) and name.startswith(PROTECTED_PREFIXES)


def signed_url(name):
    """Ссылка на защищённый файл, которая работает без входа ограниченное время."""
    url = settings.MEDIA_URL + name
    if not is_protected(name):
        return url
    return url + "?s=" + signing.TimestampSigner(salt=SIGN_SALT).sign(name).split(":", 1)[1]


def _signature_ok(name, sig):
    if not sig:
        return False
    try:
        signing.TimestampSigner(salt=SIGN_SALT).unsign(f"{name}:{sig}", max_age=SIGN_MAX_AGE)
        return True
    except signing.BadSignature:
        return False


def _file_clinic_id(name):
    """Клиника, которой принадлежит файл; None — файл не найден в базе."""
    from apps.treatments.models import TreatmentFile
    from apps.notifications.models import WaMessage
    from apps.technicians.models import TechnicianOrderFile
    if name.startswith("treatments/"):
        f = TreatmentFile.objects.filter(file=name).select_related("treatment", "patient").first()
        if f is not None:
            owner = f.treatment if f.treatment_id else f.patient
            return getattr(owner, "clinic_id", None) or -1
    elif name.startswith("chat_media/"):
        m = WaMessage.all_clinics.filter(media_file=name).only("clinic_id").first()
        if m is not None:
            return m.clinic_id or -1
    elif name.startswith("tech_orders/"):
        f = TechnicianOrderFile.objects.filter(file=name).select_related("task").first()
        if f is not None:
            return f.task.clinic_id or -1
    return None


def protected_media(request, path):
    name = os.path.normpath(path).replace("\\", "/")
    if name.startswith(("../", "/")) or name == ".." or not is_protected(name):
        raise Http404
    allowed = _signature_ok(name, request.GET.get("s", ""))
    if not allowed:
        user = request.user
        if not (user.is_authenticated and user.is_active):
            raise Http404
        clinic_id = _file_clinic_id(name)
        if clinic_id is None:
            raise Http404
        allowed = user.is_superadmin or clinic_id == user.clinic_id
    if not allowed:
        raise Http404
    full = os.path.join(settings.MEDIA_ROOT, name)
    if not os.path.isfile(full):
        raise Http404
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if getattr(settings, "MEDIA_ACCEL_REDIRECT", False):
        resp = HttpResponse(content_type=ctype)
        from urllib.parse import quote
        resp["X-Accel-Redirect"] = "/protected-media/" + quote(name)
    else:
        resp = FileResponse(open(full, "rb"), content_type=ctype)
    resp["Cache-Control"] = "private, max-age=3600"
    resp["X-Content-Type-Options"] = "nosniff"
    # html/svg с чужих телефонов не должен исполняться как страница нашего сайта
    if ctype in ("text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/xml"):
        resp["Content-Disposition"] = "attachment"
    return resp
