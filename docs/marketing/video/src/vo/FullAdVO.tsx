import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { FontFaces } from "../Fonts";
import { theme } from "../theme";

import { Scene01 } from "../scenes/Scene01";
import { Scene03 } from "../scenes/Scene03";
import { Scene12 } from "../scenes/Scene12";
import { SingleAlert } from "./SingleAlert";
import { Punch } from "./Punch";
import { FeatureSlide } from "./FeatureSlide";
import { PatientJourney, TOTAL as PATIENT_JOURNEY_FRAMES } from "./PatientJourney";
import { BeforeAfter } from "./BeforeAfter";

// Полный ролик под реальную озвучку ElevenLabs (public/audio/real-vo.mp3,
// 75.18с). Тайминг сегментов получен через ffmpeg silencedetect (границы пауз
// в аудио) + пропорциональное распределение по числу слов реплики —
// расшифровки (ASR) не было, HuggingFace/Whisper недоступны из песочницы.
// Один реальный найденный silence-порог (63.75с) почти точно совпал с
// расчётной границей "было/стало" → "CTA" (63.74с), что подтверждает тайминг.
type Beat = { name: string; frames: number; Component: React.FC };

const beats: Beat[] = [
  { name: "chaos", frames: 241, Component: Scene01 },
  { name: "alert", frames: 95, Component: () => <SingleAlert text="Снова потеряли снимок или ищете карту прямо во время приёма?" /> },
  { name: "punch", frames: 47, Component: Punch },
  { name: "brand", frames: 141, Component: Scene03 },
  {
    name: "schedule",
    frames: 212,
    Component: () => (
      <FeatureSlide
        fdi="11"
        chip="Расписание и записи"
        caption="Календарь сам не даёт записать двоих на одно время"
        file="schedule.jpg"
        duration={212}
        panXPct={-3}
        cursorPoints={[{ x: 33, y: 30 }]}
      />
    ),
  },
  { name: "patient-journey", frames: PATIENT_JOURNEY_FRAMES, Component: PatientJourney },
  {
    name: "whatsapp",
    frames: 200,
    Component: () => (
      <FeatureSlide
        fdi="18"
        chip="WhatsApp и Telegram"
        caption="Сами напоминают о приёме и присылают кнопки подтверждения"
        file="messages.jpg"
        duration={200}
        panXPct={-2}
        cursorPoints={[{ x: 22, y: 28 }]}
      />
    ),
  },
  {
    name: "cashdesk",
    frames: 153,
    Component: () => (
      <FeatureSlide
        fdi="31"
        chip="Финансы и склад"
        caption="Касса и склад материалов сходятся сами, без сверки по тетрадям"
        file="cashdesk.jpg"
        duration={153}
        panXPct={3}
        cursorPoints={[{ x: 26, y: 32 }]}
      />
    ),
  },
  {
    name: "prices",
    frames: 118,
    Component: () => (
      <FeatureSlide
        fdi="35"
        chip="Услуги и цены"
        caption="Прайс-лист — прозрачные цены на каждую услугу, без звонков «уточнить»"
        file="services.jpg"
        duration={118}
        panXPct={-2}
        cursorPoints={[{ x: 26, y: 20 }, { x: 95, y: 4 }]}
      />
    ),
  },
  {
    name: "audit",
    frames: 153,
    Component: () => (
      <FeatureSlide
        fdi="41"
        chip="Аудит-центр"
        caption="Каждое изменение в карточке — с именем и временем"
        file="audit.jpg"
        duration={153}
        panXPct={-2}
        cursorPoints={[{ x: 20, y: 19 }]}
      />
    ),
  },
  {
    name: "analytics",
    frames: 165,
    Component: () => (
      <FeatureSlide
        fdi="48"
        chip="Аналитика"
        caption="Выручка и загрузка врачей — в реальном времени"
        file="reports.jpg"
        duration={165}
        panXPct={2}
        cursorPoints={[{ x: 32, y: 35 }]}
      />
    ),
  },
  { name: "before-after", frames: 165, Component: BeforeAfter },
  { name: "cta", frames: 341, Component: Scene12 },
];

export const TOTAL_FRAMES_VO = beats.reduce((s, b) => s + b.frames, 0);

let acc = 0;
export const BEAT_STARTS = beats.map((b) => {
  const start = acc;
  acc += b.frames;
  return start;
});

export const FullAdVO: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <FontFaces />
      <Audio src={staticFile("audio/music.wav")} volume={0.12} />
      <Audio src={staticFile("audio/real-vo.mp3")} />
      {beats.map((b, i) => (
        <Sequence key={b.name} from={BEAT_STARTS[i]} durationInFrames={b.frames} name={b.name}>
          <b.Component />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
