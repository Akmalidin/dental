"""Сжатие загружаемых ФОТО (не рентгена) перед сохранением на диск.

Фото с телефона весят 3–8 МБ при 4000+ px по стороне; для карточки
пациента достаточно 2560 px по длинной стороне в JPEG качества 85 — на
экране разница не видна, а места уходит в 5–10 раз меньше.

Диагностические снимки (прицельный, ОПТГ, КЛКТ, рентген) и документы
НЕ трогаем вовсе: для врача важна каждая деталь, хранится оригинал —
см. TreatmentFile.COMPRESS_KINDS."""
import io
import os
import logging

from django.core.files.base import ContentFile

log = logging.getLogger("apps")

MAX_SIDE = 2560
QUALITY = 85
MIN_BYTES = 400 * 1024  # меньше и так лёгкие — не пережимаем, если и размер в норме
FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "BMP"}


def compress_photo(uploaded):
    """uploaded — файл из request.FILES (или любой File). Возвращает
    ContentFile со сжатым JPEG или None, если сжимать не нужно/нельзя
    (не картинка, анимация, уже лёгкий файл, результат не меньше оригинала)."""
    try:
        from PIL import Image, ImageOps
        uploaded.seek(0)
        raw = uploaded.read()
        uploaded.seek(0)
        img = Image.open(io.BytesIO(raw))
        if img.format not in FORMATS or getattr(img, "is_animated", False) and img.format != "MPO":
            return None
        if len(raw) < MIN_BYTES and max(img.size) <= MAX_SIDE:
            return None
        img = ImageOps.exif_transpose(img)  # повернуть по EXIF до удаления метаданных
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        data = out.getvalue()
        if len(data) >= len(raw):
            return None
        stem = os.path.splitext(os.path.basename(getattr(uploaded, "name", "") or "photo"))[0] or "photo"
        return ContentFile(data, name=stem + ".jpg")
    except Exception as e:  # noqa: BLE001 — не картинка/битый файл: сохраняем как есть
        log.info("Сжатие фото пропущено (%s): %s", getattr(uploaded, "name", ""), e)
        try:
            uploaded.seek(0)
        except Exception:
            pass
        return None
