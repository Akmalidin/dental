# Видео stom.asia / ODONTIS — исходники (Remotion)

Три ролика, один Remotion-проект (`Root.tsx` регистрирует все композиции):

- **`StomAd`** — рекламный ролик 16:9, ~74 сек по сценарию из
  `docs/marketing/advertising_video_script.md` (13 сцен: боль/поиск карточки
  в тетрадях → бренд → модули, включая цены → было/стало → CTA). С русской
  озвучкой (espeak-ng) поверх музыки.
- **`StomTour`** — обзорный ролик «как устроена система» (~84 сек, 18
  реальных страниц `/new/*` подряд: от заявки до отчёта). Тоже без озвучки.
- **`OdontisShort`** — вертикальный (9:16, 1080×1920) ролик ~45 сек по
  сценарию `odontis_seedance_full_script.md` (изначально написан под Seedance
  AI-видео). Та же раскадровка/тайминг/палитра (cobalt/coral/teal), но без
  внешнего AI-видео-сервиса: клипы 1-2-9 (хаос → переход → лого) — кодовая
  2D-анимация тем же приёмом, что абстрактные сцены `StomAd`; клипы 3-8 —
  настоящие экраны ODONTIS вместо нечитаемой AI-абстракции интерфейса (сам
  сценарий в финальной сноске рекомендует именно эту гибридную схему).

Никаких сторонних AI-видео/озвучка-сервисов — всё собрано локально:

- **UI в кадре** — не макеты, а настоящие скриншоты приложения (`/new/schedule/`,
  `/new/patients/<id>/`, `/new/cashdesk/` и т.д.), снятые Playwright с
  демо-клиникой (см. «Пересобрать с нуля» ниже). Обрамлены в рамку окна
  браузера, оживлены медленным Ken Burns zoom/pan и курсором, кликающим по
  реальному элементу (`PageFrame.tsx` + `AnimatedCursor.tsx`).
- **Озвучка `StomAd`** — русский голос через `espeak-ng` + обработка ffmpeg
  (компрессор, лёгкое эхо, нормализация громкости), см. `gen_vo.py`. Голос
  роботизированный (offline TTS — единственный вариант без выхода в
  интернет к ElevenLabs) — годится для тайминга и предпросмотра, для
  финальной версии стоит заменить на запись диктора.
- **Музыка** — процедурный синтез на numpy (бас, пэд-аккорды, арпеджио,
  хай-хэты, риз/импакт), без сэмплов. Отдельный трек под каждый ролик
  (`gen_music.py` / `gen_music_tour.py` / `gen_music_short.py`), т.к. они
  разной длины.
- **Шрифты** (Manrope/Inter/JetBrains Mono, кириллица) — скачиваются с Google
  Fonts один раз и встраиваются в бандл как `data:` URI (`embed_fonts.py`) —
  рендер не зависит от сети.

## Структура

```
src/
  theme.ts            — цвета/шрифты (токены лендинга stom.asia)
  SceneShell.tsx       — общие анимационные хелперы (fade/rise), Caption, Chip
  FeatureShell.tsx      — каркас сцен-модулей рекламного ролика (04–10): FDI-код, чип, подпись
  TourShell.tsx          — каркас карточки обзорного ролика: группа/индекс «03 / 18», заголовок, подпись
  PageFrame.tsx           — рамка «окна браузера» с реальным скриншотом + Ken Burns (общий для обоих роликов)
  Fonts.tsx               — встроенные шрифты (embeddedFonts.ts, генерируется)
  Video.tsx / TourVideo.tsx — таймлайны роликов (SCENES[] / PAGES[], монтаж, музыка)
  Root.tsx, index.ts       — регистрация композиций StomAd + StomTour
  scenes/Scene01..12.tsx, ScenePrices.tsx — покадровая раскадровка рекламного ролика
  scenes/TourIntro.tsx, TourOutro.tsx — бренд-заставка и CTA обзорного ролика
```

## Пересобрать с нуля

Из корня репозитория (`dental/`):

```bash
# 0) окружение (если ещё не установлено)
pip install -r requirements.txt
apt-get install -y espeak-ng ffmpeg   # оба обязательны — espeak-ng озвучивает StomAd

# 1) демо-данные (реалистичная демо-клиника для скриншотов)
export DJANGO_SETTINGS_MODULE=config.settings.development
export SECRET_KEY=dev-secret
python3 manage.py migrate
python3 manage.py shell < docs/marketing/video/seed_demo.py
python3 manage.py shell < docs/marketing/video/seed_demo2.py   # заявки, задачи, план лечения, лаборатория
python3 manage.py runserver 127.0.0.1:8000 &

# 2) скриншоты реальных страниц (Playwright, headless Chromium)
cd docs/marketing/video
npm install playwright-core   # разово, в отдельную node_modules
node screenshot.js            # -> ../../../scratchpad/screens/*.png (путь в скрипте — поправить под себя)
bash convert_shots.sh         # -> public/screens/*.jpg (масштаб 1920×1080, ужатые)

# 3) шрифты (кириллица) как data: URI
npm install
python3 fetch_fonts.py        # -> public/fonts/*.woff2, src/fontManifest.json
python3 embed_fonts.py        # -> src/embeddedFonts.ts

# 4) озвучка StomAd (espeak-ng) — 13 реплик, см. LINES в gen_vo.py
python3 gen_vo.py             # -> audio/vo/01..12,prices.wav

# 5) музыка (numpy) — отдельный трек под каждый ролик, своя длительность
python3 gen_music.py
ffmpeg -y -i audio/music_raw.wav -af "loudnorm=I=-23:TP=-2:LRA=9" audio/music.wav
python3 gen_music_tour.py
ffmpeg -y -i audio/tour_music_raw.wav -af "loudnorm=I=-20:TP=-2:LRA=9" audio/tour-music.wav
mkdir -p public/audio/vo && cp audio/vo/*.wav public/audio/vo/
cp audio/music.wav audio/tour-music.wav public/audio/

# 6) рендер (нужен headless Chromium + ffmpeg с libx264 — см. remotion.config.ts)
npm run render         # -> out/stom-asia-ad.mp4
npm run render:tour    # -> out/stom-asia-tour.mp4
```

`seed_demo.py`/`seed_demo2.py` создают клинику «Стоматология «Асия»»
(логин `demo_director` / пароль `demo12345`) с пациентами, приёмами,
оплатами, складом, заявками, задачами, планом лечения и историей правок
карточки (для «Журнала аудита») — всё вымышленное, без реальных персональных
данных.

Тайминг сцен рекламного ролика (`SCENES[]` в `Video.tsx`) — под длину
реплики озвучки (`voLeadIn`/`voDur`, кадры) + отступы, пересчитывается из
`audio/vo_durations.json` после `gen_vo.py`; тайминг карточек обзорного
ролика (`PAGES[]` в `TourVideo.tsx`) — фиксированные 126 кадров (4.2 с) на
страницу. Меняете текст реплики/список страниц — пересчитайте длительности
сцен и границы секций `gen_music.py`/`gen_music_tour.py`
(`T_A_END`/`T_B_END`/`T_C_END`/`T_D_END`/`TOTAL`) под новую суммарную
длительность.
