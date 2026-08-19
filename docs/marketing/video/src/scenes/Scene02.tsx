import React from "react";
import { useCurrentFrame } from "remotion";
import { theme } from "../theme";
import { SceneShell, fadeIn, riseIn } from "../SceneShell";

const Alert: React.FC<{ text: string; frame: number; start: number }> = ({ text, frame, start }) => {
  const o = fadeIn(frame, start, 10);
  const y = riseIn(frame, start, 10, 16);
  return (
    <div
      style={{
        opacity: o,
        transform: `translateY(${y}px)`,
        fontFamily: theme.font.mono,
        fontWeight: 500,
        fontSize: 36,
        color: theme.accent2,
        background: theme.accent2Soft,
        border: "2px solid rgba(255,183,74,.45)",
        borderRadius: 14,
        padding: "18px 30px",
        display: "flex",
        alignItems: "center",
        gap: 14,
      }}
    >
      <span>⚠</span>
      {text}
    </div>
  );
};

export const Scene02: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <SceneShell>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 26,
        }}
      >
        <Alert text="Забыли напомнить" frame={frame} start={4} />
        <Alert text="Касса не сходится" frame={frame} start={70} />
        <Alert text="Кто менял карточку?" frame={frame} start={140} />
      </div>
    </SceneShell>
  );
};
