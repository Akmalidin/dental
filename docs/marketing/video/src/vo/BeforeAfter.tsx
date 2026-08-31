import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, Caption } from "../SceneShell";

// Тот же слева/справа split, что Scene11, но с подписью под реальный текст
// озвучки: "Было — тетради... Стало — один экран, который помнит всё за вас."
export const BeforeAfter: React.FC = () => {
  const frame = useCurrentFrame();
  const split = interpolate(frame, [0, 26], [100, 50], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <SceneShell vignette={false}>
      <div style={{ position: "absolute", inset: 0, display: "flex" }}>
        <div style={{ width: `${split}%`, background: theme.panel2, filter: "grayscale(.6) brightness(.75)", position: "relative" }}>
          <span
            style={{
              position: "absolute",
              top: 64,
              left: 0,
              right: 0,
              textAlign: "center",
              fontFamily: theme.font.mono,
              fontSize: 26,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: theme.muted,
            }}
          >
            Было
          </span>
        </div>
        <div style={{ width: `${100 - split}%`, background: `radial-gradient(ellipse at center, ${theme.accentSoft}, ${theme.bg})`, position: "relative" }}>
          <span
            style={{
              position: "absolute",
              top: 64,
              left: 0,
              right: 0,
              textAlign: "center",
              fontFamily: theme.font.mono,
              fontSize: 26,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: theme.accent,
            }}
          >
            Стало
          </span>
        </div>
        <div style={{ position: "absolute", top: 0, bottom: 0, left: `${split}%`, width: 3, background: theme.accent, boxShadow: `0 0 20px 2px ${theme.accentSoft}` }} />
      </div>
      <Caption text="Было — тетради, забытые приёмы, потерянные снимки. Стало — один экран, который помнит всё за вас." frame={frame} start={18} />
    </SceneShell>
  );
};
