import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

const SLOTS = [
  0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0,
];

export const Scene04: React.FC = () => {
  const frame = useCurrentFrame();
  const blockFlash = interpolate(frame, [46, 54, 62], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <FeatureShell fdi="11" chip="Расписание и записи" caption="Календарь сам не даёт записать двоих на одно время">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, width: 620 }}>
        {SLOTS.map((on, i) => (
          <div
            key={i}
            style={{
              height: 34,
              borderRadius: 7,
              background: on ? theme.accentSoft : theme.panel2,
              border: `1.5px solid ${on ? theme.borderStrong : theme.border}`,
              opacity: interpolate(frame, [i * 1.2, i * 1.2 + 14], [0, 1], {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              }),
            }}
          />
        ))}
        <div
          style={{
            gridColumn: "3 / 4",
            gridRow: "2 / 3",
            position: "relative",
            top: -44,
            height: 34,
            borderRadius: 7,
            border: `2.5px solid ${theme.accent2}`,
            boxShadow: `0 0 0 4px rgba(255,183,74,${0.35 * blockFlash})`,
            opacity: blockFlash,
          }}
        />
      </div>
    </FeatureShell>
  );
};
