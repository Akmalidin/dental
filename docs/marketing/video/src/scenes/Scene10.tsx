import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

const PATH = "M0,45 L15,35 L35,38 L55,20 L75,25 L100,8";

export const Scene10: React.FC = () => {
  const frame = useCurrentFrame();
  const len = 220;
  const draw = interpolate(frame, [0, 40], [0, len], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const dotX = interpolate(frame, [0, 40], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <FeatureShell fdi="48" chip="Аналитика" caption="Выручка и загрузка врачей — в реальном времени">
      <div style={{ width: 560, height: 260 }}>
        <svg viewBox="0 0 100 50" width="100%" height="100%" preserveAspectRatio="none">
          <path d={`${PATH} L100,50 L0,50 Z`} fill={theme.accentSoft} stroke="none" />
          <path
            d={PATH}
            fill="none"
            stroke={theme.accent}
            strokeWidth={2}
            strokeDasharray={len}
            strokeDashoffset={len - draw}
          />
          <circle cx={dotX} cy={8 + (100 - dotX) * 0.12} r={2.4} fill={theme.accent} />
        </svg>
      </div>
    </FeatureShell>
  );
};
