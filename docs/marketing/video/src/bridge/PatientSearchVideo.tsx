import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { FontFaces } from "../Fonts";
import { theme } from "../theme";
import { PageFrame } from "../PageFrame";

// Вставка "поиск пациента" под реплику "Найти нужного пациента — три
// секунды. Не десять минут в тетради": список пациентов → курсор кликает
// в поиск, потом по строке пациента → кроссфейд в её реальную карточку
// (та же Джумабекова Мадина, что и в patientcard.jpg — узнаваемо).
// Без звука, для монтажа в свой ролик.
const LIST_FRAMES = 100;
const CROSSFADE_START = 80;
export const TOTAL = 130; // ~4.33с @30fps

const FadingList: React.FC = () => {
  const frame = useCurrentFrame();
  const fadeOut = interpolate(frame, [CROSSFADE_START, LIST_FRAMES], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity: fadeOut, alignItems: "center", justifyContent: "center", display: "flex" }}>
      <PageFrame
        file="patients.jpg"
        duration={LIST_FRAMES}
        width={1700}
        zoomFrom={1.05}
        zoomTo={1.0}
        cursorPoints={[
          { x: 73, y: 4 }, // поле поиска "ФИО, телефон…"
          { x: 18, y: 61.5 }, // строка "Джумабекова Мадина"
        ]}
      />
    </AbsoluteFill>
  );
};

const FadingCard: React.FC = () => {
  const frame = useCurrentFrame(); // локальный, от своей Sequence (from=CROSSFADE_START)
  const dur = TOTAL - CROSSFADE_START;
  const fadeIn = interpolate(frame, [0, LIST_FRAMES - CROSSFADE_START], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity: fadeIn, alignItems: "center", justifyContent: "center", display: "flex" }}>
      <PageFrame file="patientcard.jpg" duration={dur} width={1700} zoomFrom={1.06} zoomTo={1.0} />
    </AbsoluteFill>
  );
};

export const PatientSearch: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <FontFaces />
      <Sequence from={0} durationInFrames={LIST_FRAMES} name="list">
        <FadingList />
      </Sequence>
      <Sequence from={CROSSFADE_START} durationInFrames={TOTAL - CROSSFADE_START} name="card">
        <FadingCard />
      </Sequence>
    </AbsoluteFill>
  );
};
