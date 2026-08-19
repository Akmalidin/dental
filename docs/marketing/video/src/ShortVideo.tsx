import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { FontFaces } from "./Fonts";
import { shortTheme as theme } from "./short/theme";
import { Clip1Chaos } from "./short/scenes/Clip1Chaos";
import { Clip2Transition } from "./short/scenes/Clip2Transition";
import { ShortFeature } from "./short/ShortFeature";
import { Clip9Logo } from "./short/scenes/Clip9Logo";

// Ролик по odontis_seedance_full_script.md — та же раскадровка/тайминг/
// палитра (cobalt/coral/teal, 9:16), но без Seedance: клипы 1-2-9
// (хаос/переход/лого) — кодовая 2D-анимация тем же приёмом, что и абстрактные
// сцены в StomAd; клипы 3-8 — реальные экраны ODONTIS вместо нечитаемой
// AI-абстракции UI (см. финальную сноску самого сценария — она же и
// рекомендует эту гибридную схему).
const CLIPS = [
  { id: "1", frames: 120, Component: Clip1Chaos },
  { id: "2", frames: 90, Component: Clip2Transition },
  {
    id: "3",
    frames: 180,
    Component: () => (
      <ShortFeature file="funnel.jpg" duration={180} caption="Заявки — в одной воронке" cursorPoints={[{ x: 26, y: 33 }, { x: 90, y: 17 }]} />
    ),
  },
  {
    id: "4",
    frames: 180,
    Component: () => (
      <ShortFeature file="schedule.jpg" duration={180} caption="Календарь — без двойных записей" cursorPoints={[{ x: 33, y: 30 }, { x: 95, y: 4 }]} />
    ),
  },
  {
    id: "5",
    frames: 180,
    Component: () => (
      <ShortFeature file="patientcard.jpg" duration={180} caption="Зубная карта и история лечения — в одной карточке" cursorPoints={[{ x: 23, y: 17 }, { x: 94, y: 10 }]} />
    ),
  },
  {
    id: "6",
    frames: 180,
    Component: () => (
      <ShortFeature file="cashdesk.jpg" duration={180} caption="Оплата и чек — в одном окне" cursorPoints={[{ x: 26, y: 32 }, { x: 91, y: 17 }]} />
    ),
  },
  {
    id: "7",
    frames: 150,
    Component: () => (
      <ShortFeature file="messages.jpg" duration={150} caption="WhatsApp и Telegram — в одном чате" cursorPoints={[{ x: 22, y: 28 }, { x: 60, y: 33 }]} />
    ),
  },
  {
    id: "8",
    frames: 120,
    Component: () => (
      <ShortFeature file="reports.jpg" duration={120} caption="Выручка и загрузка врачей — сразу видно" cursorPoints={[{ x: 32, y: 35 }, { x: 68, y: 30 }]} />
    ),
  },
  { id: "9", frames: 150, Component: Clip9Logo },
];

export const SHORT_TOTAL_FRAMES = CLIPS.reduce((s, c) => s + c.frames, 0);

let acc = 0;
export const SHORT_STARTS = CLIPS.map((c) => {
  const s = acc;
  acc += c.frames;
  return s;
});

export const OdontisShort: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bgWhite }}>
      <FontFaces />
      <Audio src={staticFile("audio/short-music.wav")} volume={0.5} />
      {CLIPS.map((c, i) => (
        <Sequence key={c.id} from={SHORT_STARTS[i]} durationInFrames={c.frames} name={`clip-${c.id}`}>
          <c.Component />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
