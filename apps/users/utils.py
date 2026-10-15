"""Общие мелкие хелперы apps.users, не привязанные к конкретной модели."""


def validate_uploaded_image(f):
    """Проверить, что загруженный файл — действительно валидное изображение.

    Django сам верифицирует содержимое ImageField через Pillow, но ТОЛЬКО
    при прохождении через ModelForm.full_clean()/is_valid(). Наши вьюхи
    сохраняют логотип/обложку сайта клиники и аватары присваиванием файла
    напрямую полю модели (`obj.avatar = request.FILES["avatar"]`) — это
    быстрее написать, но полностью пропускает проверку содержимого: под
    видом .jpg/.png можно загрузить произвольный файл (например, SVG с
    <script> — при прямой отдаче из /media/ это stored XSS). Эта функция
    закрывает дыру перед присваиванием файла полю модели.

    Возвращает True, если файл открылся как изображение и прошёл verify().
    """
    from PIL import Image

    try:
        f.seek(0)
        Image.open(f).verify()
    except Exception:
        return False
    finally:
        f.seek(0)
    return True


def safe_referer(request, default):
    """Вернуться туда, откуда пришли (Referer), — только если это наш же сайт.
    Иначе default (URL или имя маршрута для redirect()): Referer задаёт тот,
    кто прислал ссылку, и без проверки это open redirect."""
    from django.utils.http import url_has_allowed_host_and_scheme
    url = request.META.get("HTTP_REFERER")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return url
    return default


def neutralize_formulas(wb):
    """Экспорт в Excel: текст, начинающийся с «=», openpyxl записывает как
    формулу — имя/заметка «=HYPERLINK(...)» из формы записи на сайте стала бы
    формулой у того, кто откроет файл. Такие значения пишем как обычный текст."""
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f" and isinstance(cell.value, str):
                    cell.data_type = "s"
    return wb
