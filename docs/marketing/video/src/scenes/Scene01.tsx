import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, Caption, fadeIn } from "../SceneShell";

export const Scene01: React.FC = () => {
  const frame = useCurrentFrame();
  const paperRotate = interpolate(frame, [0, 120], [-3, -5]);
  const handX = interpolate(frame, [0, 60, 120], [0, 40, 10], {
    extrapolateRight: "clamp",
  });

  return (
    <SceneShell>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          filter: "saturate(.55) brightness(.9)",
        }}
      >
        {/* messy monitor windows */}
        <div style={{ position: "absolute", right: 300, top: 210, opacity: fadeIn(frame, 0, 20) }}>
          <div
            style={{
              width: 380,
              height: 250,
              background: theme.panel2,
              border: `1px solid ${theme.border}`,
              borderRadius: 10,
            }}
          >
            <div style={{ height: 26, borderBottom: `1px solid ${theme.border}`, display: "flex", alignItems: "center", gap: 6, padding: "0 10px" }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: theme.muted, opacity: 0.5 }} />
              <span style={{ width: 8, height: 8, borderRadius: 4, background: theme.muted, opacity: 0.5 }} />
            </div>
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                style={{
                  height: 12,
                  margin: "12px 14px",
                  width: `${70 - i * 6}%`,
                  background: theme.muted,
                  opacity: 0.25,
                  borderRadius: 3,
                }}
              />
            ))}
          </div>
        </div>
        <div style={{ position: "absolute", right: 250, top: 500, opacity: fadeIn(frame, 10, 20) }}>
          <div
            style={{
              width: 260,
              height: 170,
              background: theme.panel2,
              border: `1px solid ${theme.border}`,
              borderRadius: 10,
              opacity: 0.85,
            }}
          />
        </div>

        {/* paper journal */}
        <div
          style={{
            position: "absolute",
            left: 260,
            top: 260,
            width: 560,
            height: 460,
            background: `repeating-linear-gradient(${theme.panel2} 0 4px, transparent 4px 34px), ${theme.panel}`,
            border: `1px solid ${theme.border}`,
            borderRadius: 4,
            transform: `rotate(${paperRotate}deg)`,
            boxShadow: "0 30px 60px rgba(0,0,0,.5)",
          }}
        />
        {/* hand / finger indicator sliding down rows */}
        <div
          style={{
            position: "absolute",
            left: 260 + handX,
            top: 300 + interpolate(frame, [0, 120], [0, 300]),
            width: 90,
            height: 26,
            borderRadius: 6,
            background: theme.accent2,
            opacity: 0.75 * fadeIn(frame, 0, 20),
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          top: 96,
          left: 96,
          fontFamily: theme.font.mono,
          fontSize: 22,
          color: theme.muted,
          opacity: fadeIn(frame, 0, 20),
        }}
      >
        РЕГИСТРАТУРА · 8:47
      </div>

      <Caption text="Пациент записан дважды. Второй — уже в дверях." frame={frame} start={24} />
    </SceneShell>
  );
};
