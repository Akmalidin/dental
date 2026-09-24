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


BOX = 20
BORDER = 3
DARK = (0, 0, 0, 255)
LIGHT = (255, 255, 255, 255)


def _render_rounded(qr):
    """Свой рендер вместо стандартного: скруглённые «глазки» по углам
    (рамка + внутренний квадрат), квадратные точки со слегка скруглёнными
    углами (стыкуются, без зазоров — так надёжнее читается) и скруглённые
    углы всей карточки (прозрачный фон за углами)."""
    from PIL import Image, ImageDraw

    matrix = qr.get_matrix()  # уже с рамкой BORDER модулей
    n = len(matrix)
    size = n * BOX
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(BOX * 2.2), fill=LIGHT)

    count = n - 2 * BORDER
    eyes = [(BORDER, BORDER), (BORDER, BORDER + count - 7), (BORDER + count - 7, BORDER)]

    def in_eye(r, c):
        return any(er <= r < er + 7 and ec <= c < ec + 7 for er, ec in eyes)

    for r in range(n):
        for c in range(n):
            if matrix[r][c] and not in_eye(r, c):
                x, y = c * BOX, r * BOX
                d.rounded_rectangle((x, y, x + BOX - 1, y + BOX - 1), radius=int(BOX * 0.2), fill=DARK)

    for er, ec in eyes:
        x, y = ec * BOX, er * BOX
        d.rounded_rectangle((x, y, x + 7 * BOX - 1, y + 7 * BOX - 1), radius=int(BOX * 2), fill=DARK)
        d.rounded_rectangle((x + BOX, y + BOX, x + 6 * BOX - 1, y + 6 * BOX - 1),
                            radius=int(BOX * 1.4), fill=LIGHT)
        d.rounded_rectangle((x + 2 * BOX, y + 2 * BOX, x + 5 * BOX - 1, y + 5 * BOX - 1),
                            radius=int(BOX * 0.9), fill=DARK)
    return img


def booking_qr_png(url, logo_file=None):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H
    from PIL import Image, ImageDraw

    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=BOX, border=BORDER)
    qr.add_data(url)
    qr.make(fit=True)
    img = _render_rounded(qr)

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
