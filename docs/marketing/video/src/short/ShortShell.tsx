import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { shortTheme as theme } from "./theme";

export const fadeIn = (frame: number, start = 0, dur = 15) =>
  interpolate(frame, [start, start + dur], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

export const riseIn = (frame: number, start = 0, dur = 18, px = 22) =>
  interpolate(frame, [start, start + dur], [px, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

export const ShortShell: React.FC<{ bg?: string; children: React.ReactNode }> = ({ bg = theme.bgWhite, children }) => (
  <AbsoluteFill style={{ background: bg }}>{children}</AbsoluteFill>
);

// Подпись внизу кадра — в «безопасной зоне» над тем местом, где у Reels/TikTok
// обычно живут подписи/кнопки самого приложения.
export const ShortCaption: React.FC<{ text: string; frame: number; start?: number; dark?: boolean }> = ({
  text,
  frame,
  start = 8,
  dark = false,
}) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 210,
      display: "flex",
      justifyContent: "center",
      opacity: fadeIn(frame, start, 14),
      transform: `translateY(${riseIn(frame, start, 14, 14)}px)`,
      padding: "0 88px",
    }}
  >
    <p
      style={{
        fontFamily: theme.font.display,
        fontWeight: 700,
        fontSize: 42,
        lineHeight: 1.28,
        color: dark ? "#ffffff" : theme.ink,
        textAlign: "center",
        margin: 0,
        textWrap: "balance" as any,
      }}
    >
      {text}
    </p>
  </div>
);

// Маленький бейдж-лого (тот же значок «зуб», что и в реальном сайдбаре
// ODONTIS) — держит бренд в кадре на всём ролике, как «водяной знак».
export const BrandBug: React.FC<{ frame: number; dark?: boolean }> = ({ frame, dark = false }) => (
  <div
    style={{
      position: "absolute",
      top: 72,
      left: 0,
      right: 0,
      display: "flex",
      justifyContent: "center",
      opacity: fadeIn(frame, 0, 14),
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div
        style={{
          width: 30,
          height: 30,
          borderRadius: 8,
          background: theme.coral,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 2C8 2 5 4.5 5 8.2c0 2.6.9 3.4 1.4 6.9.4 2.7.9 5.4 2.4 5.4 1.7 0 1.6-3.6 2-5.4.3-1.2.9-1.2 1.2 0 .4 1.8.3 5.4 2 5.4 1.5 0 2-2.7 2.4-5.4.5-3.5 1.4-4.3 1.4-6.9C19 4.5 16 2 12 2Z"
            fill="#ffffff"
          />
        </svg>
      </div>
      <span style={{ fontFamily: theme.font.mono, fontWeight: 600, fontSize: 26, color: dark ? "#ffffff" : theme.ink, letterSpacing: "0.02em" }}>
        ODONTIS
      </span>
    </div>
  </div>
);

export { useCurrentFrame };
