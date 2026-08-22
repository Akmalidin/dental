#!/usr/bin/env python3
import base64
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
manifest = json.load(open(os.path.join(BASE, "src", "fontManifest.json"), encoding="utf-8"))

rules = []
for m in manifest:
    fpath = os.path.join(BASE, "public", "fonts", m["file"])
    data = base64.b64encode(open(fpath, "rb").read()).decode("ascii")
    rules.append(
        "@font-face{"
        f"font-family:'{m['family']}';font-style:normal;font-weight:{m['weight']};"
        "font-display:block;"
        f"src:url(data:font/woff2;base64,{data}) format('woff2');"
        f"unicode-range:{m['unicodeRange']};"
        "}"
    )

css = "".join(rules)
with open(os.path.join(BASE, "src", "embeddedFonts.ts"), "w", encoding="utf-8") as f:
    f.write("// Автогенерировано embed_fonts.py — шрифты встроены как data: URI,\n")
    f.write("// чтобы рендер не зависел от сети/dev-сервера (см. Fonts.tsx).\n")
    f.write(f"export const FONT_FACE_CSS = {json.dumps(css)};\n")

print("wrote embeddedFonts.ts,", len(css), "chars")
