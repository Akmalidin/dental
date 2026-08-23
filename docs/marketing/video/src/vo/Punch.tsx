import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, fadeIn } from "../SceneShell";

// Короткий "удар"-переход под реплику "Хватит! Пора это остановить." —
// крупный текст, вспышка, ничего лишнего.
export const Punch: React.FC = () => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, 8], [0.85, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const flash = interpolate(frame, [0, 6, 20], [0.5, 0, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <SceneShell vignette={false}>
      <div style={{ position: "absolute", inset: 0, background: theme.accent2, opacity: flash }} />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: "0 160px",
          opacity: fadeIn(frame, 2, 8),
          transform: `scale(${scale})`,
        }}
      >
        <span style={{ fontFamily: theme.font.display, fontWeight: 800, fontSize: 76, color: theme.ink, lineHeight: 1.15 }}>
          Хватит!<br />Пора это остановить.
        </span>
      </div>
    </SceneShell>
  );
};
