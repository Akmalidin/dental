"""
Точка входа для .exe (PyInstaller): поднимает локальный Django-сервер и открывает браузер.
Запуск как обычное приложение (иконка), без консоли.
"""
import os
import sys
import threading
import time
import webbrowser

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# при сборке onefile рабочая папка — _MEIPASS; данные (templates/static) добавлены через --add-data
if getattr(sys, "frozen", False):
    base = sys._MEIPASS  # noqa
    os.chdir(base)


def _run_server():
    import django
    from django.core.management import call_command
    django.setup()
    # применить миграции локальной базы (первый запуск создаёт схему)
    try:
        call_command("migrate", "--noinput")
        call_command("collectstatic", "--noinput", verbosity=0)
    except Exception:
        pass
    # запуск сервера (waitress если есть, иначе runserver)
    try:
        from waitress import serve
        from config.wsgi import application
        serve(application, host="127.0.0.1", port=8765)
    except Exception:
        call_command("runserver", "127.0.0.1:8765", "--noreload")


if __name__ == "__main__":
    threading.Thread(target=_run_server, daemon=True).start()
    time.sleep(3.5)
    webbrowser.open("http://127.0.0.1:8765/")
    # держим процесс живым, пока работает сервер
    while True:
        time.sleep(3600)
