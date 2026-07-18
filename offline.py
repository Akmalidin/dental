"""
Оффлайн-режим SADAF — интерактивный запуск (Python корректно работает с кириллицей,
в отличие от .bat). Вызывается из offline_setup.bat / offline_start.bat.

  python offline.py setup   — первичная загрузка данных клиники
  python offline.py start   — запуск локального сервера + браузер

Сервер слушает на 0.0.0.0:8765 — значит, доступен не только с этого
компьютера, но и с любого другого компьютера/ноутбука в той же Wi-Fi/LAN
сети клиники (просто открыть в браузере http://<IP этого компьютера>:8765/,
адрес показывается и в консоли, и прямо в приложении). Так несколько
компьютеров клиники работают с ОДНОЙ локальной базой, а не расходятся
каждый со своей копией.
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")


def _django():
    import django
    django.setup()


def _lan_ip():
    """Локальный IP этого компьютера в сети клиники (для подсказки другим
    компьютерам — реально никуда не подключается, просто определяет
    исходящий сетевой интерфейс)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def setup():
    _django()
    from django.core.management import call_command
    print("=" * 50)
    print("  SADAF — первичная настройка оффлайн-копии")
    print("=" * 50)
    print("Создание локальной базы...")
    call_command("migrate", "--noinput")
    try:
        call_command("collectstatic", "--noinput", verbosity=0)
    except Exception:
        pass
    url = input("\nАдрес облака [https://sadaf.denta.tw1.ru]: ").strip() or "https://sadaf.denta.tw1.ru"
    login = input("Ваш логин: ").strip()
    try:
        import getpass
        pw = getpass.getpass("Ваш пароль: ")
    except Exception:
        pw = input("Ваш пароль: ")
    print("\nСкачивание данных вашей клиники...")
    call_command("offline_pull", url=url, login=login, password=pw)
    print("\nГотово! Запускайте программу: SADAF_Offline.vbs (или offline_start.bat)")
    input("Нажмите Enter для выхода...")


def start():
    _django()
    from django.core.management import call_command
    try:
        call_command("migrate", "--noinput")
        call_command("collectstatic", "--noinput", verbosity=0)
    except Exception:
        pass
    import threading
    import webbrowser
    ip = _lan_ip()
    threading.Timer(3.0, lambda: webbrowser.open("http://127.0.0.1:8765/")).start()
    print("=" * 60)
    print("  SADAF (оффлайн-режим) запущен — не закрывайте это окно")
    print("=" * 60)
    print(f"  Этот компьютер:        http://127.0.0.1:8765/")
    print(f"  Другие компьютеры сети: http://{ip}:8765/")
    print("  (на других компьютерах просто открыть этот адрес в браузере)")
    print("=" * 60)
    try:
        from waitress import serve
        from config.wsgi import application
        serve(application, host="0.0.0.0", port=8765)
    except Exception:
        call_command("runserver", "0.0.0.0:8765", "--noreload")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    (setup if cmd == "setup" else start)()
