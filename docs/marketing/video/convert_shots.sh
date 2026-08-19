#!/usr/bin/env bash
# Масштабирует и ужимает скриншоты screenshot.js (screens-raw/*.png) до
# 1920x1080 JPEG в public/screens — то, что реально грузит Remotion.
set -euo pipefail
cd "$(dirname "$0")"
SRC=screens-raw
DST=public/screens
mkdir -p "$DST"
for f in "$SRC"/*.png; do
  name=$(basename "$f" .png)
  ffmpeg -y -loglevel error -i "$f" -vf "scale=1920:1080" -q:v 3 "$DST/$name.jpg"
done
ls -la "$DST"
du -sh "$DST"
