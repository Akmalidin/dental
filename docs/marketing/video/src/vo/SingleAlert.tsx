import React from "react";
import { useCurrentFrame } from "remotion";
import { theme } from "../theme";
import { SceneShell, fadeIn, riseIn } from "../SceneShell";

// Одно тревожное сообщение вместо каскада из четырёх (Scene02) — под короткую
// реплику озвучки "Снова потеряли снимок... или ищете зубную карту".
export const SingleAlert: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame();
  const o = fadeIn(frame, 4, 12);
  const y = riseIn(frame, 4, 12, 18);
  return (
    <SceneShell>
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div
          style={{
            opacity: o,
            transform: `translateY(${y}px)`,
            fontFamily: theme.font.mono,
            fontWeight: 500,
            fontSize: 42,
            color: theme.accent2,
            background: theme.accent2Soft,
            border: "2px solid rgba(255,183,74,.45)",
            borderRadius: 16,
            padding: "24px 38px",
            display: "flex",
            alignItems: "center",
            gap: 18,
          }}
        >
          <span>⚠</span>
          {text}
        </div>
      </div>
    </SceneShell>
  );
};
