import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { theme } from "../theme";
import { PageFrame } from "../PageFrame";

// Сжатая версия PatientSearch + TreatmentHistory в один блок под реплику
// про карточку пациента: список → поиск → карточка → история приёмов → документы.
// Пациентка Джумабекова Мадина — сквозной персонаж по всему ролику.
const A_FRAMES = 70; // список/поиск
const B_START = 55;
const B_FRAMES = 60; // мonтировано 55..115, карточка
const C_START = 100;
const C_FRAMES = 65; // 100..165, история приёмов
const D_START = 150;
const D_FRAMES = 74; // 150..224, документы
export const TOTAL = 224;

const Fading: React.FC<{ file: string; fadeInAt?: number; fadeOutAt?: number; dur: number; cursor?: { x: number; y: number }[]; width?: number }> = ({
  file,
  fadeInAt,
  fadeOutAt,
  dur,
  cursor,
  width = 1700,
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
      <PageFrame file={file} duration={dur} width={width} zoomFrom={1.05} zoomTo={1.0} cursorPoints={cursor} />
    </AbsoluteFill>
  );
};

export const PatientJourney: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <Sequence from={0} durationInFrames={A_FRAMES} name="list">
        <Fading file="patients.jpg" fadeOutAt={55} dur={A_FRAMES} width={1700} cursor={[{ x: 73, y: 4 }, { x: 18, y: 61.5 }]} />
      </Sequence>
      <Sequence from={B_START} durationInFrames={B_FRAMES} name="card">
        <Fading file="patientcard.jpg" fadeInAt={0} fadeOutAt={45} dur={B_FRAMES} cursor={[{ x: 27, y: 17 }]} />
      </Sequence>
      <Sequence from={C_START} durationInFrames={C_FRAMES} name="history">
        <Fading file="patientcard-history.jpg" fadeInAt={0} fadeOutAt={50} dur={C_FRAMES} cursor={[{ x: 44, y: 17 }]} />
      </Sequence>
      <Sequence from={D_START} durationInFrames={D_FRAMES} name="docs">
        <Fading file="patientcard-docs.jpg" fadeInAt={0} dur={D_FRAMES} cursor={[{ x: 35, y: 35 }]} />
      </Sequence>
    </AbsoluteFill>
  );
};
