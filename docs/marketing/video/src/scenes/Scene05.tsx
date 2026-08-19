import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

export const Scene05: React.FC = () => {
  const frame = useCurrentFrame();
  const h = interpolate(frame, [0, 26], [40, 340], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const lineOpacity = (delay: number) =>
    interpolate(frame, [delay, delay + 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <FeatureShell fdi="21" chip="Карточки пациентов" caption="История лечений и баланс — на одном экране">
      <div
        style={{
          width: 560,
          height: h,
          overflow: "hidden",
          background: theme.panel2,
          border: `1.5px solid ${theme.border}`,
          borderRadius: 16,
          padding: 26,
        }}
      >
        <div style={{ height: 16, width: "55%", background: theme.ink, opacity: 0.55, borderRadius: 4, marginBottom: 18 }} />
        {[0.9, 0.7, 0.8, 0.5].map((w, i) => (
          <div
            key={i}
            style={{
              height: 9,
              width: `${w * 100}%`,
              background: theme.muted,
              opacity: 0.35 * lineOpacity(14 + i * 6),
              borderRadius: 3,
              marginBottom: 12,
            }}
          />
        ))}
        <div
          style={{
            marginTop: 14,
            display: "inline-block",
            fontFamily: theme.font.mono,
            fontSize: 16,
            color: theme.accent,
            background: theme.accentSoft,
            border: `1px solid ${theme.borderStrong}`,
            padding: "7px 14px",
            borderRadius: 8,
            opacity: lineOpacity(48),
          }}
        >
          баланс: 0 сом
        </div>
      </div>
    </FeatureShell>
  );
};
