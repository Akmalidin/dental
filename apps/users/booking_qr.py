"""QR-код онлайн-записи клиники (stom.asia/book/<slug>/) в PNG — для
скачивания/печати из Настроек нового интерфейса, опционально с логотипом
клиники в центре (ClinicSettings.qr_logo).

Логотип перекрывает часть модулей, поэтому код строится с максимальной
коррекцией ошибок (H, ~30%), а логотип занимает не больше ~22% ширины —
такой QR уверенно читается камерами телефонов."""
import io

LOGO_SHARE = 0.22


def booking_url_for(clinic):
    from django.conf import settings as dj_settings
    domain = getattr(dj_settings, "CRM_BASE_DOMAIN", "") or getattr(dj_settings, "PUBLIC_BASE_DOMAIN", "denta.tw1.ru")
    return f"https://{domain}/book/{clinic.slug}/"


def booking_qr_png(url, logo_file=None):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H
    from PIL import Image, ImageDraw

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=20, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")

    if logo_file:
        try:
            logo_file.open("rb")
            logo = Image.open(logo_file).convert("RGBA")
        except Exception:
            logo = None
        finally:
            try:
                logo_file.close()
            except Exception:
                pass
        if logo is not None:
            side = int(img.width * LOGO_SHARE)
            logo.thumbnail((side, side))
            pad = max(6, side // 10)
            box_w, box_h = logo.width + pad * 2, logo.height + pad * 2
            plate = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
            ImageDraw.Draw(plate).rounded_rectangle(
                (0, 0, box_w - 1, box_h - 1), radius=pad * 2, fill=(255, 255, 255, 255))
            plate.alpha_composite(logo, (pad, pad))
            img.paste(plate, ((img.width - box_w) // 2, (img.height - box_h) // 2), plate)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
