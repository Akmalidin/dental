"""
Точка входа для .exe (PyInstaller): поднимает локальный Django-сервер и открывает браузер.
Запуск как обычное приложение (иконка), без консоли.

Первая настройка (нет локальной базы рядом с .exe): персонал клиники
заранее заполняет offline_setup.json (адрес облака, логин, пароль) —
при первом запуске программа сама скачивает данные клиники, используя эти
данные, и создаёт постоянную локальную базу offline.sqlite3 рядом с .exe.
При последующих запусках база уже есть — сразу поднимается сервер.
"""
import os
import sys
import threading
import time
import webbrowser

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# Постоянное место (рядом с .exe) — переживает перезапуск программы, в
# отличие от временной папки распаковки PyInstaller (_MEIPASS).
if getattr(sys, "frozen", False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(DATA_DIR, "offline.sqlite3")
CLOUD_CFG_PATH = os.path.join(DATA_DIR, "offline_cloud.json")
SETUP_CFG_PATH = os.path.join(DATA_DIR, "offline_setup.json")

# при сборке onefile рабочая папка процесса — _MEIPASS; данные (templates/
# static) добавлены туда через --add-data. Меняем cwd ПОСЛЕ вычисления
# DATA_DIR выше (который считается от sys.executable, а не от cwd).
if getattr(sys, "frozen", False):
    os.chdir(sys._MEIPASS)  # noqa


def _show_message(title, text, error=False):
    """Окошко с сообщением (например, «заполните offline_setup.json») —
    единственное место, где нужен графический ввод/вывод без консоли."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text, parent=root)
        root.destroy()
    except Exception:
        pass


def _first_run_setup():
    """Скачать данные клиники по данным из offline_setup.json (заполняется
    персоналом один раз, вручную, в текстовом редакторе, ДО первого запуска).
    Возвращает True, если данные успешно скачаны и можно запускать сервер."""
    import json

    if not os.path.exists(SETUP_CFG_PATH):
        _show_message(
            "SADAF — нужна первая настройка",
            "Рядом с программой нет файла offline_setup.json.\n\n"
            "Создайте его (см. инструкцию) с адресом облака, логином и паролем, "
            "и запустите программу ещё раз.",
            error=True,
        )
        return False

    try:
        cfg = json.loads(open(SETUP_CFG_PATH, encoding="utf-8").read())
        url = (cfg.get("url") or "").strip()
        login = (cfg.get("login") or "").strip()
        password = cfg.get("password") or ""
    except Exception:
        _show_message(
            "SADAF — ошибка настройки",
            "Не удалось прочитать offline_setup.json — проверьте, что это корректный JSON.",
            error=True,
        )
        return False

    if not (url and login and password):
        _show_message(
            "SADAF — нужна первая настройка",
            "В offline_setup.json не заполнены url / login / password.",
            error=True,
        )
        return False

    import django
    django.setup()
    from django.core.management import call_command
    try:
        call_command("migrate", "--noinput")
    except Exception as e:
        _show_message("SADAF — ошибка", f"Не удалось подготовить локальную базу:\n{e}", error=True)
        return False
    try:
        call_command("offline_pull", url=url, login=login, password=password)
    except Exception as e:
        _show_message(
            "SADAF — ошибка загрузки данных",
            f"Не удалось скачать данные клиники:\n{e}\n\n"
            "Проверьте адрес/логин/пароль в offline_setup.json и что есть интернет.",
            error=True,
        )
        return False
    return True


def _run_server():
    import django
    from django.core.management import call_command
    django.setup()
    try:
        call_command("migrate", "--noinput")
        call_command("collectstatic", "--noinput", verbosity=0)
    except Exception:
        pass
    try:
        from waitress import serve
        from config.wsgi import application
        serve(application, host="0.0.0.0", port=8765)
    except Exception:
        call_command("runserver", "0.0.0.0:8765", "--noreload")


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        if not _first_run_setup():
            sys.exit(1)
    threading.Thread(target=_run_server, daemon=True).start()
    time.sleep(3.5)
    webbrowser.open("http://127.0.0.1:8765/")
    # держим процесс живым, пока работает сервер
    while True:
        time.sleep(3600)
