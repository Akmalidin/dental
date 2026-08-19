import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

export const Scene06: React.FC = () => {
  const frame = useCurrentFrame();
  const bubbleY = interpolate(frame, [10, 30], [-30, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const bubbleOp = interpolate(frame, [10, 30], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const btnOp = interpolate(frame, [40, 56], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <FeatureShell fdi="18" chip="WhatsApp и Telegram" caption="Сами напоминают о приёме и присылают кнопки подтверждения">
      <div
        style={{
          width: 300,
          height: 400,
          border: `3px solid ${theme.panel2}`,
          borderRadius: 30,
          background: theme.panel,
          padding: 18,
        }}
      >
        <div style={{ height: 8, width: 60, background: theme.panel2, borderRadius: 4, margin: "0 auto 26px" }} />
        <div
          style={{
            opacity: bubbleOp,
            transform: `translateY(${bubbleY}px)`,
            background: theme.accentSoft,
            border: `1.5px solid ${theme.borderStrong}`,
            borderRadius: "14px 14px 14px 3px",
            padding: 16,
          }}
        >
          <div style={{ height: 7, width: "80%", background: theme.accent, opacity: 0.65, borderRadius: 3, marginBottom: 8 }} />
          <div style={{ height: 7, width: "55%", background: theme.accent, opacity: 0.65, borderRadius: 3, marginBottom: 16 }} />
          <div style={{ display: "flex", gap: 8, opacity: btnOp }}>
            <span
              style={{
                flex: 1,
                textAlign: "center",
                fontFamily: theme.font.mono,
                fontSize: 13,
                fontWeight: 600,
                background: theme.accent,
                color: theme.bg,
                borderRadius: 8,
                padding: "9px 0",
              }}
            >
              Подтвердить
            </span>
            <span
              style={{
                flex: 1,
                textAlign: "center",
                fontFamily: theme.font.mono,
                fontSize: 13,
                fontWeight: 600,
                background: "transparent",
                color: theme.accent,
                border: `1.5px solid ${theme.borderStrong}`,
                borderRadius: 8,
                padding: "8px 0",
              }}
            >
              Перенести
            </span>
          </div>
        </div>
      </div>
    </FeatureShell>
  );
};
