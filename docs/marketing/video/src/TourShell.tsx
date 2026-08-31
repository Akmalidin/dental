import React from "react";
import { useCurrentFrame } from "remotion";
import { theme } from "./theme";
import { SceneShell, Caption, fadeIn, riseIn } from "./SceneShell";

export const TourShell: React.FC<{
  index: number;
  total: number;
  group: string;
  title: string;
  caption: string;
  children: React.ReactNode;
}> = ({ index, total, group, title, caption, children }) => {
  const frame = useCurrentFrame();
  return (
    <SceneShell>
      <div
        style={{
          position: "absolute",
          top: 56,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 10,
          opacity: fadeIn(frame, 0, 14),
        }}
      >
        <div
          style={{
            fontFamily: theme.font.mono,
            fontSize: 20,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: theme.accent,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span style={{ width: 18, height: 1, background: theme.accent, display: "inline-block" }} />
          {group}
          <span style={{ color: theme.muted, fontWeight: 400 }}>
            {String(index).padStart(2, "0")} / {String(total).padStart(2, "0")}
          </span>
        </div>
        <div style={{ fontFamily: theme.font.display, fontWeight: 800, fontSize: 40, color: theme.ink }}>{title}</div>
      </div>

      <div
        style={{
          position: "absolute",
          top: 168,
          bottom: 130,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: fadeIn(frame, 4, 16),
          transform: `translateY(${riseIn(frame, 4, 16, 16)}px)`,
        }}
      >
        {children}
      </div>

      <Caption text={caption} frame={frame} start={8} />
    </SceneShell>
  );
};
