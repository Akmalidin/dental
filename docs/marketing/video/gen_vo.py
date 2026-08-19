#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import json
import os

LINES = [
    ("01", "Пациент записан дважды. Второй — уже в дверях."),
    ("02", "Напомнить забыли. Касса не сходится. И никто не знает, кто менял карточку пациента."),
    ("03", "Один экран вместо восьми программ."),
    ("04", "Календарь сам не даёт записать двоих на одно время."),
    ("05", "История лечений и баланс — на одном экране."),
    ("06", "Ватсап и Телеграм сами напоминают о приёме и присылают кнопки подтверждения."),
    ("07", "Касса и склад материалов сходятся сами, без сверки по тетрадям."),
    ("08", "Каждое изменение в карточке — с именем и временем."),
    ("09", "Даже без интернета клиника продолжает работать."),
    ("10", "Выручка и загрузка врачей — в реальном времени."),
    ("11", "Первая неделя после подключения выглядит именно так."),
    ("12", "Подключим вашу клинику за один день. Первая консультация бесплатно. Стом асия."),
]

BASE = os.path.dirname(os.path.abspath(__file__))
VO_DIR = os.path.join(BASE, "audio", "vo")
os.makedirs(VO_DIR, exist_ok=True)

durations = {}

for n, text in LINES:
    raw = os.path.join(VO_DIR, f"{n}_raw.wav")
    out = os.path.join(VO_DIR, f"{n}.wav")
    subprocess.run(
        ["espeak-ng", "-v", "ru", "-s", "146", "-p", "32", "-a", "190", "-w", raw, text],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", raw,
            "-af",
            "volume=2.0,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,"
            "aecho=0.55:0.4:35:0.12,highpass=f=90,loudnorm=I=-16:TP=-1.5:LRA=8",
            "-ar", "44100", out,
        ],
        check=True,
    )
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", out],
        capture_output=True, text=True, check=True,
    )
    dur = float(json.loads(probe.stdout)["format"]["duration"])
    durations[n] = dur
    print(f"{n}  dur={dur:.2f}s  :: {text}")
    os.remove(raw)

with open(os.path.join(BASE, "audio", "vo_durations.json"), "w", encoding="utf-8") as f:
    json.dump(durations, f, ensure_ascii=False, indent=2)
