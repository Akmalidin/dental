# stom.asia — 2D motion-ролик (Remotion)

Программная сборка 45-секундного рекламного ролика из `docs/marketing/advertising_video_script.md` — векторная 2D-анимация (React + [Remotion](https://www.remotion.dev/)), без внешних AI-видео-сервисов. Все 12 сцен построены на фирменной палитре и шрифтах stom.asia.

## Установка и запуск

```bash
cd docs/marketing/video-remotion
npm install

# живой предпросмотр с таймлайном
npm start

# рендер финального mp4 → out/stom-asia-ad.mp4
npm run render
```

## Структура

- `src/theme.ts` — цвета бренда (`#0b0f14 / #3fd0c9 / #ffb74a / #eaf5ff`).
- `src/fonts.ts` — Manrope / Inter / JetBrains Mono через `@remotion/google-fonts`.
- `src/components.tsx` — переиспользуемые части: фон-подложка, чипы, дуга-логотип, wordmark.
- `src/scenes.tsx` — все 12 сцен раскадровки (Scene01…Scene12).
- `src/Video.tsx` — сборка сцен в таймлайн через `<Series>`, тайминги в кадрах (30fps) соответствуют таймкодам сценария.
- `remotion.config.ts` — рендер использует уже установленный в среде Chromium (`/opt/pw-browsers`).

## Что дальше

- Готовый mp4 — картинка и текст без звука. Голос (ElevenLabs) и музыку (Suno) накладывайте поверх в CapCut/DaVinci по репликам из сценария.
- Хотите поменять текст, тайминг сцены или цвет — правьте `src/scenes.tsx` и `src/Video.tsx` и перезапускайте `npm run render`.
