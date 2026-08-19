import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

const BARS = [40, 70, 55, 88, 62, 75];

export const Scene07: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <FeatureShell fdi="31" chip="Финансы и склад" caption="Касса и склад материалов сходятся сами, без сверки по тетрадям">
      <div style={{ display: "flex", alignItems: "flex-end", gap: 20, height: 260, width: 560 }}>
        {BARS.map((h, i) => {
          const grown = interpolate(frame, [i * 6, i * 6 + 24], [0, h], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: `${grown}%`,
                borderRadius: "6px 6px 2px 2px",
                background: `linear-gradient(to top, ${theme.accent}, ${theme.accentSoft})`,
              }}
            />
          );
        })}
      </div>
    </FeatureShell>
  );
};
