import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, fadeIn } from "../SceneShell";

export const Scene03: React.FC = () => {
  const frame = useCurrentFrame();
  const pathLen = 1200;
  const draw = interpolate(frame, [4, 34], [0, pathLen], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const dotOpacity = interpolate(frame, [30, 40], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const dotScale = interpolate(frame, [30, 44, 60], [0.4, 1.3, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const wordmarkOpacity = fadeIn(frame, 46, 16);

  return (
    <SceneShell vignette={false}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse 60% 55% at 50% 42%, ${theme.accentSoft}, transparent 70%)`,
        }}
      />
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg viewBox="0 -60 800 260" width={880} height={286}>
          <path
            d="M40 180 Q400 -40 760 180"
            fill="none"
            stroke={theme.accent}
            strokeWidth={5}
            strokeLinecap="round"
            strokeDasharray={pathLen}
            strokeDashoffset={pathLen - draw}
          />
          <circle cx={400} cy={20} r={13} fill={theme.accent} opacity={dotOpacity} transform={`translate(400 20) scale(${dotScale}) translate(-400 -20)`} />
        </svg>
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 300,
          display: "flex",
          justifyContent: "center",
          opacity: wordmarkOpacity,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ width: 16, height: 16, borderRadius: 8, background: theme.accent, boxShadow: `0 0 24px 4px ${theme.accentSoft}` }} />
          <span style={{ fontFamily: theme.font.mono, fontWeight: 600, fontSize: 64, color: theme.ink }}>stom.asia</span>
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
          opacity: fadeIn(frame, 58, 16),
        }}
      >
        <span style={{ fontFamily: theme.font.mono, fontSize: 24, letterSpacing: "0.14em", textTransform: "uppercase", color: theme.accent }}>
          CRM для стоматологий
        </span>
      </div>
    </SceneShell>
  );
};
