import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { FontFaces } from "../Fonts";
import { theme } from "../theme";
import { PageFrame } from "../PageFrame";

// Вставка "вся история лечения и документы": карточка пациента → клик по
// вкладке "История приёмов" → клик по "Документы" → снимки/файлы. Тот же
// пациент, что в PatientSearch (Джумабекова Мадина) — продолжение той сцены.
// Без звука, для монтажа в свой ролик.
const A_FRAMES = 70;
const B_START = 55;
const B_FRAMES = 75; // mounted 55..130
const C_START = 115;
const C_FRAMES = 65; // mounted 115..180
export const TOTAL = 180; // 6с @30fps

const Fading: React.FC<{ file: string; fadeInAt?: number; fadeOutAt?: number; dur: number; cursor?: { x: number; y: number }[] }> = ({
  file,
  fadeInAt,
  fadeOutAt,
  dur,
  cursor,
}) => {
  const frame = useCurrentFrame();
  let opacity = 1;
  if (fadeInAt !== undefined) {
    opacity = Math.min(opacity, interpolate(frame, [fadeInAt, fadeInAt + 15], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  }
  if (fadeOutAt !== undefined) {
    opacity = Math.min(opacity, interpolate(frame, [fadeOutAt, fadeOutAt + 15], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  }
  return (
    <AbsoluteFill style={{ opacity, alignItems: "center", justifyContent: "center", display: "flex" }}>
      <PageFrame file={file} duration={dur} width={1700} zoomFrom={1.05} zoomTo={1.0} cursorPoints={cursor} />
    </AbsoluteFill>
  );
};

export const TreatmentHistory: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <FontFaces />
      <Sequence from={0} durationInFrames={A_FRAMES} name="card">
        <Fading file="patientcard.jpg" fadeOutAt={55} dur={A_FRAMES} cursor={[{ x: 27, y: 17 }]} />
      </Sequence>
      <Sequence from={B_START} durationInFrames={B_FRAMES} name="history">
        <Fading file="patientcard-history.jpg" fadeInAt={0} fadeOutAt={60} dur={B_FRAMES} cursor={[{ x: 44, y: 17 }]} />
      </Sequence>
      <Sequence from={C_START} durationInFrames={C_FRAMES} name="docs">
        <Fading file="patientcard-docs.jpg" fadeInAt={0} dur={C_FRAMES} cursor={[{ x: 35, y: 35 }]} />
      </Sequence>
    </AbsoluteFill>
  );
};
