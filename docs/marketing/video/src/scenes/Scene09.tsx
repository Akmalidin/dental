import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { FeatureShell } from "../FeatureShell";

export const Scene09: React.FC = () => {
  const frame = useCurrentFrame();
  const wifiOpacity = interpolate(frame, [0, 20, 26], [1, 1, 0.12], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const syncOpacity = interpolate(frame, [28, 42], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const syncRotate = interpolate(frame, [28, 135], [0, 300]);
  return (
    <FeatureShell fdi="28" chip="Офлайн-режим" caption="Даже без интернета клиника продолжает работать">
      <div style={{ position: "relative", width: 180, height: 180 }}>
        <svg viewBox="0 0 100 70" style={{ position: "absolute", inset: 0, opacity: wifiOpacity }}>
          <path d="M10 28 Q50 -6 90 28" fill="none" stroke={theme.muted} strokeWidth={5} strokeLinecap="round" />
          <path d="M24 40 Q50 18 76 40" fill="none" stroke={theme.muted} strokeWidth={5} strokeLinecap="round" />
          <path d="M38 52 Q50 42 62 52" fill="none" stroke={theme.muted} strokeWidth={5} strokeLinecap="round" />
          <circle cx={50} cy={62} r={5} fill={theme.muted} />
        </svg>
        <svg
          viewBox="0 0 60 60"
          style={{
            position: "absolute",
            inset: 0,
            opacity: syncOpacity,
            transform: `rotate(${syncRotate}deg)`,
          }}
        >
          <path d="M10 30a20 20 0 0 1 34-14" fill="none" stroke={theme.accent} strokeWidth={4} strokeLinecap="round" />
          <path d="M50 30a20 20 0 0 1-34 14" fill="none" stroke={theme.accent} strokeWidth={4} strokeLinecap="round" />
          <circle cx={30} cy={30} r={4} fill={theme.accent} />
        </svg>
      </div>
    </FeatureShell>
  );
};
