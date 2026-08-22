#!/usr/bin/env python3
import re
import os
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
css = open(os.path.join(BASE, "fonts.css"), encoding="utf-8").read()

blocks = re.findall(
    r"/\* (\S+) \*/\s*@font-face\s*\{([^}]+)\}", css, re.S
)

KEEP_SUBSETS = {"latin", "cyrillic"}
FONT_DIR = os.path.join(BASE, "public", "fonts")
os.makedirs(FONT_DIR, exist_ok=True)

manifest = []
for subset, body in blocks:
    if subset not in KEEP_SUBSETS:
        continue
    family = re.search(r"font-family:\s*'([^']+)'", body).group(1)
    weight = re.search(r"font-weight:\s*(\d+)", body).group(1)
    url = re.search(r"url\(([^)]+)\)", body).group(1)
    unicode_range = re.search(r"unicode-range:\s*([^;]+);", body).group(1)
    fname = f"{family.replace(' ', '')}-{weight}-{subset}.woff2".lower()
    fpath = os.path.join(FONT_DIR, fname)
    urllib.request.urlretrieve(url, fpath)
    print("downloaded", fname, os.path.getsize(fpath), "bytes")
    manifest.append(
        {"family": family, "weight": int(weight), "file": fname, "unicodeRange": unicode_range}
    )

import json

with open(os.path.join(BASE, "src", "fontManifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("wrote src/fontManifest.json with", len(manifest), "faces")
