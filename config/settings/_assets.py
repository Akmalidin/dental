# -*- coding: utf-8 -*-
"""Версия статики для cache-busting (?v=...).

Живёт отдельным модулем, потому что base.py и development.py не наследуют друг
друга, а версия нужна обоим: production.py идёт от base.py, а server.py и
local.py — от development.py.

Имена файлов не хэшируются (STATICFILES_STORAGE в Django 5.1 больше не
читается), а nginx отдаёт /static/ с длинным expires. Без версии в URL браузер
продолжал бы отдавать закэшированный app.js уже после деплоя.
"""

import os

# Бандлы, изменение которых обязано сбрасывать кэш у клиентов.
BUNDLES = (
    "newui/app.js",
    "newui/app.css",
    "marketing/landing.js",
    "marketing/landing.css",
)


def asset_version(base_dir):
    """Максимальный mtime бандлов. git меняет mtime только у реально
    обновившихся файлов, поэтому версия растёт ровно тогда, когда надо.

    Переопределяется переменной окружения ASSET_VERSION.
    """
    override = os.environ.get("ASSET_VERSION")
    if override:
        return override

    stamps = []
    for rel in BUNDLES:
        try:
            stamps.append(int(os.stat(os.path.join(str(base_dir), "static", *rel.split("/"))).st_mtime))
        except OSError:
            continue
    return str(max(stamps)) if stamps else "1"
