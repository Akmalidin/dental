# Рекламный ролик stom.asia — исходники (Remotion)

Код 2D motion-ролика по сценарию из `docs/marketing/advertising_video_script.md`
(12 сцен, ~67 сек). Собран на [Remotion](https://remotion.dev) — React-компоненты
рендерятся в mp4 через headless Chromium + ffmpeg, без сторонних AI-видео-сервисов.

Озвучка и музыка тоже сгенерированы локально (offline), без ElevenLabs/Suno:
- **Озвучка** — `espeak-ng` (русский голос) + ffmpeg-обработка (компрессор, лёгкое
  эхо/реверб, нормализация громкости). Черновой уровень, годится для тайминга и
  предпросмотра — для финальной версии эту дорожку стоит заменить на запись
  живого диктора (см. промпты для ElevenLabs в истории задачи/чате).
- **Музыка** — процедурный синтез на numpy (без сэмплов): бас, пэд-аккорды,
  арпеджио, хай-хэты, риз и «импакт»-удар на выходе бренда — уложены по
  таймкодам сцен.
- **Шрифты** (Manrope/Inter/JetBrains Mono, кириллица) — скачиваются с Google
  Fonts один раз и встраиваются в бандл как `data:` URI (см. `embed_fonts.py`) —
  рендер не зависит от сети.

## Структура

```
src/
  theme.ts          — цвета/шрифты (те же токены, что на лендинге stom.asia)
  SceneShell.tsx     — общие анимационные хелперы (fade/rise), Caption, Chip
  FeatureShell.tsx   — общий каркас для сцен-модулей (04–10): FDI-код, чип, подпись
  Fonts.tsx          — встроенные шрифты (embeddedFonts.ts, генерируется)
  Video.tsx          — таймлайн: SCENES[] (кадры/тайминг VO), музыка, монтаж сцен
  Root.tsx, index.ts — регистрация композиции Remotion
  scenes/Scene01..12.tsx — покадровая раскадровка (см. сценарий)
```

## Пересобрать с нуля

```bash
npm install

# 1) скачать и встроить шрифты (кириллица) как data: URI
python3 fetch_fonts.py     # -> public/fonts/*.woff2, src/fontManifest.json
python3 embed_fonts.py     # -> src/embeddedFonts.ts

# 2) озвучка (espeak-ng должен быть установлен: apt install espeak-ng)
python3 gen_vo.py          # -> audio/vo/01..12.wav

# 3) музыка (numpy)
python3 gen_music.py       # -> audio/music_raw.wav
ffmpeg -y -i audio/music_raw.wav -af "loudnorm=I=-20:TP=-2:LRA=9" audio/music.wav

# 4) разложить аудио в public/ (Remotion берёт статику отсюда)
mkdir -p public/audio && cp audio/vo/*.wav audio/music.wav public/audio/

# 5) рендер (нужен headless Chromium + ffmpeg с libx264 — см. remotion.config.ts)
npm run render              # -> out/stom-asia-ad.mp4
```

Тайминг каждой сцены в `Video.tsx` (`SCENES[]`) подобран под длительность
реальных VO-файлов (espeak) + отступы — при замене озвучки на другую (другой
темп речи) длительности сцен нужно пересчитать под новые файлы.
