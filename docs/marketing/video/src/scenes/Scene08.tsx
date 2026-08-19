import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

const ROWS = [
  { w: 78, hi: false },
  { w: 60, hi: true },
  { w: 85, hi: false },
  { w: 50, hi: false },
];

export const Scene08: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <FeatureShell fdi="41" chip="Аудит-центр" caption="Каждое изменение в карточке — с именем и временем">
      <div style={{ width: 600, display: "flex", flexDirection: "column", gap: 16 }}>
        {ROWS.map((r, i) => {
          const op = interpolate(frame, [i * 10, i * 10 + 14], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          const glow = r.hi ? interpolate(frame, [40, 56, 72], [0, 1, 0.5], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, opacity: op }}>
              <span
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: 5,
                  background: r.hi ? theme.accent : theme.muted,
                  boxShadow: r.hi ? `0 0 ${8 * glow}px 2px ${theme.accent}` : "none",
                  flexShrink: 0,
                }}
              />
              <div
                style={{
                  height: 12,
                  width: `${r.w}%`,
                  borderRadius: 4,
                  background: r.hi ? theme.accentSoft : theme.panel2,
                  border: `1px solid ${r.hi ? theme.borderStrong : theme.border}`,
                }}
              />
            </div>
          );
        })}
      </div>
    </FeatureShell>
  );
};
