import React from "react";
import { useCurrentFrame } from "remotion";
import { theme } from "./theme";
import { SceneShell, Chip, Caption, fadeIn, riseIn } from "./SceneShell";

export const FeatureShell: React.FC<{
  fdi: string;
  chip: string;
  caption: string;
  children: React.ReactNode;
}> = ({ fdi, chip, caption, children }) => {
  const frame = useCurrentFrame();
  return (
    <SceneShell>
      <div
        style={{
          position: "absolute",
          top: 70,
          left: 90,
          fontFamily: theme.font.mono,
          fontSize: 100,
          fontWeight: 600,
          color: theme.border,
          opacity: fadeIn(frame, 0, 16),
        }}
      >
        {fdi}
      </div>
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 220,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: fadeIn(frame, 4, 16),
          transform: `translateY(${riseIn(frame, 4, 16, 18)}px)`,
        }}
      >
        {children}
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 168,
          display: "flex",
          justifyContent: "center",
          opacity: fadeIn(frame, 6, 14),
        }}
      >
        <Chip>{chip}</Chip>
      </div>
      <Caption text={caption} frame={frame} start={10} />
    </SceneShell>
  );
};
