import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, Chip, fadeIn, riseIn } from "../SceneShell";

export const Scene12: React.FC = () => {
  const frame = useCurrentFrame();
  const pulse = 1 + 0.02 * Math.sin(frame / 10);
  return (
    <SceneShell>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: 0.5,
          transform: `scale(${pulse})`,
        }}
      >
        <svg viewBox="0 -60 800 260" width={720} height={234}>
          <path d="M40 180 Q400 -40 760 180" fill="none" stroke={theme.accent} strokeWidth={3} strokeLinecap="round" opacity={0.5} />
          <circle cx={400} cy={20} r={9} fill={theme.accent} />
        </svg>
      </div>

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 22,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, opacity: fadeIn(frame, 4, 16) }}>
          <span style={{ width: 14, height: 14, borderRadius: 7, background: theme.accent2, boxShadow: `0 0 20px 4px ${theme.accent2Soft}` }} />
          <span style={{ fontFamily: theme.font.mono, fontWeight: 600, fontSize: 46, color: theme.ink }}>stom.asia</span>
        </div>

        <div
          style={{
            opacity: fadeIn(frame, 18, 16),
            transform: `translateY(${riseIn(frame, 18, 16)}px)`,
            fontFamily: theme.font.display,
            fontWeight: 800,
            fontSize: 40,
            color: theme.ink,
            textAlign: "center",
          }}
        >
          Подключим клинику за 1 день
        </div>

        <div style={{ opacity: fadeIn(frame, 34, 16), transform: `translateY(${riseIn(frame, 34, 16)}px)` }}>
          <Chip tone="amber">Первая консультация — бесплатно</Chip>
        </div>
      </div>
    </SceneShell>
  );
};
