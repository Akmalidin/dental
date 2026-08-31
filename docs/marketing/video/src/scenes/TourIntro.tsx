import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, fadeIn } from "../SceneShell";

export const TourIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const pathLen = 1200;
  const draw = interpolate(frame, [2, 26], [0, pathLen], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const dotOpacity = interpolate(frame, [22, 32], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <SceneShell vignette={false}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse 60% 55% at 50% 40%, ${theme.accentSoft}, transparent 70%)`,
        }}
      />
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", top: -80 }}>
        <svg viewBox="0 -60 800 260" width={760} height={247}>
          <path
            d="M40 180 Q400 -40 760 180"
            fill="none"
            stroke={theme.accent}
            strokeWidth={5}
            strokeLinecap="round"
            strokeDasharray={pathLen}
            strokeDashoffset={pathLen - draw}
          />
          <circle cx={400} cy={20} r={12} fill={theme.accent} opacity={dotOpacity} />
        </svg>
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 340,
          display: "flex",
          justifyContent: "center",
          opacity: fadeIn(frame, 6, 16),
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ width: 14, height: 14, borderRadius: 7, background: theme.accent, boxShadow: `0 0 20px 4px ${theme.accentSoft}` }} />
          <span style={{ fontFamily: theme.font.mono, fontWeight: 600, fontSize: 44, color: theme.ink }}>stom.asia</span>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 220,
          display: "flex",
          justifyContent: "center",
          opacity: fadeIn(frame, 24, 16),
        }}
      >
        <h1 style={{ fontFamily: theme.font.display, fontWeight: 800, fontSize: 52, color: theme.ink, margin: 0, textAlign: "center" }}>
          Как устроена система
        </h1>
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 158,
          display: "flex",
          justifyContent: "center",
          opacity: fadeIn(frame, 40, 16),
        }}
      >
        <span style={{ fontFamily: theme.font.mono, fontSize: 24, letterSpacing: "0.12em", textTransform: "uppercase", color: theme.accent }}>
          Полный обзор — от заявки до отчёта
        </span>
      </div>
    </SceneShell>
  );
};
