import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { FontFaces } from "../Fonts";
import { PageFrame } from "../PageFrame";
import { LogoCard } from "./LogoCard";

// Короткая вставка "лого → дашборд" для монтажа в CapCut/DaVinci: чистый
// лого-кадр ODONTIS держится, потом кроссфейдит в реальный дашборд системы
// (тот же логотип уже виден в его сайдбаре — преемственность бренда).
// Без звука — аудио вы накладываете сами поверх своей дорожки.
export const LOGO_HOLD = 60; // кадров держится чистое лого (с учётом входа)
export const DASH_START = 45; // кроссфейд начинается тут (15f внахлёст)
export const TOTAL = 105; // 3.5с @30fps

const FadingLogo: React.FC = () => {
  const frame = useCurrentFrame();
  const fadeOut = interpolate(frame, [DASH_START, LOGO_HOLD], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity: fadeOut }}>
      <LogoCard />
    </AbsoluteFill>
  );
};

const FadingDashboard: React.FC = () => {
  const frame = useCurrentFrame(); // локальный, относительно своей Sequence (from=DASH_START)
  const dur = TOTAL - DASH_START;
  const fadeIn = interpolate(frame, [0, LOGO_HOLD - DASH_START], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity: fadeIn, background: "#ffffff", alignItems: "center", justifyContent: "center", display: "flex" }}>
      <PageFrame file="dashboard.jpg" duration={dur} width={1760} zoomFrom={1.07} zoomTo={1.0} />
    </AbsoluteFill>
  );
};

export const LogoBridge: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: "#ffffff" }}>
      <FontFaces />
      <Sequence from={0} durationInFrames={LOGO_HOLD} name="logo">
        <FadingLogo />
      </Sequence>
      <Sequence from={DASH_START} durationInFrames={TOTAL - DASH_START} name="dashboard">
        <FadingDashboard />
      </Sequence>
    </AbsoluteFill>
  );
};
