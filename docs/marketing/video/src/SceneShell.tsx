import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { theme } from "./theme";

export const fadeIn = (frame: number, start = 0, dur = 15) =>
  interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

export const fadeOutTail = (frame: number, total: number, dur = 12) =>
  interpolate(frame, [total - dur, total], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

export const riseIn = (frame: number, start = 0, dur = 18, px = 22) =>
  interpolate(frame, [start, start + dur], [px, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

export const Chip: React.FC<{ children: React.ReactNode; tone?: "accent" | "amber" }> = ({
  children,
  tone = "accent",
}) => (
  <span
    style={{
      fontFamily: theme.font.mono,
      fontWeight: 500,
      fontSize: 22,
      color: tone === "accent" ? theme.accent : theme.accent2,
      background: tone === "accent" ? theme.accentSoft : theme.accent2Soft,
      border: `1.5px solid ${tone === "accent" ? theme.borderStrong : "rgba(255,183,74,.45)"}`,
      borderRadius: 10,
      padding: "9px 18px",
      display: "inline-block",
    }}
  >
    {children}
  </span>
);

export const Caption: React.FC<{ text: string; frame: number; start?: number }> = ({
  text,
  frame,
  start = 6,
}) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 92,
      display: "flex",
      justifyContent: "center",
      opacity: fadeIn(frame, start, 14),
      transform: `translateY(${riseIn(frame, start, 14, 12)}px)`,
      padding: "0 160px",
    }}
  >
    <p
      style={{
        fontFamily: theme.font.body,
        fontWeight: 500,
        fontSize: 34,
        lineHeight: 1.4,
        color: theme.ink,
        textAlign: "center",
        margin: 0,
        textWrap: "balance" as any,
      }}
    >
      {text}
    </p>
  </div>
);

export const Eyebrow: React.FC<{ text: string; frame: number; start?: number }> = ({
  text,
  frame,
  start = 4,
}) => (
  <div
    style={{
      position: "absolute",
      top: 72,
      left: 0,
      right: 0,
      display: "flex",
      justifyContent: "center",
      opacity: fadeIn(frame, start, 12),
    }}
  >
    <div
      style={{
        fontFamily: theme.font.mono,
        fontSize: 22,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        color: theme.accent,
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <span style={{ width: 22, height: 1, background: theme.accent, display: "inline-block" }} />
      {text}
    </div>
  </div>
);

export const SceneShell: React.FC<{ children: React.ReactNode; vignette?: boolean }> = ({
  children,
  vignette = true,
}) => (
  <AbsoluteFill style={{ background: theme.bg }}>
    {vignette && (
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(ellipse 70% 60% at 50% 32%, rgba(63,208,201,.09), transparent 65%)",
        }}
      />
    )}
    {children}
  </AbsoluteFill>
);

export const useLocalFrame = () => useCurrentFrame();
