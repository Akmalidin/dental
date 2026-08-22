"""Лёгкий best-effort парсер User-Agent для карточки события в
Аудит-центре (макет: «Chrome 128 · macOS 15») — без внешней библиотеки
(в requirements.txt её нет и добавлять ради одной строки текста не
нужно), чистый re. Не претендует на полноту (нет мобильных вариантов
каждого браузера/UA-редких клиентов) — при нераспознанном UA просто
возвращает исходную строку, обрезанную для отображения."""
import re

_BROWSER_PATTERNS = [
    ("Edge", r"Edg(?:e|A|iOS)?/([\d.]+)"),
    ("Opera", r"OPR/([\d.]+)"),
    ("Chrome", r"Chrome/([\d.]+)"),
    ("Firefox", r"Firefox/([\d.]+)"),
    ("Safari", r"Version/([\d.]+).*Safari"),
]

_OS_PATTERNS = [
    ("Windows", r"Windows NT ([\d.]+)"),
    ("macOS", r"Mac OS X ([\d_.]+)"),
    ("Android", r"Android ([\d.]+)"),
    ("iOS", r"(?:iPhone|iPad).*OS ([\d_]+)"),
    ("Linux", r"(Linux)"),
]

_WINDOWS_VERSION_LABELS = {
    "10.0": "10/11", "6.3": "8.1", "6.2": "8", "6.1": "7",
}


def _browser(ua):
    for name, pattern in _BROWSER_PATTERNS:
        m = re.search(pattern, ua)
        if m:
            version = m.group(1).split(".")[0]
            return f"{name} {version}"
    return None


def _os(ua):
    for name, pattern in _OS_PATTERNS:
        m = re.search(pattern, ua)
        if not m:
            continue
        if name == "Linux":
            return "Linux"
        raw = m.group(1).replace("_", ".")
        if name == "Windows":
            return f"Windows {_WINDOWS_VERSION_LABELS.get(raw, raw)}"
        major = raw.split(".")[0]
        return f"{name} {major}"
    return None


def parse_user_agent(ua):
    """"Chrome 128 · macOS 15" — или «—», если UA пуст/не распознан."""
    ua = (ua or "").strip()
    if not ua:
        return "—"
    browser = _browser(ua)
    os_name = _os(ua)
    parts = [p for p in (browser, os_name) if p]
    if parts:
        return " · ".join(parts)
    return ua[:60]
