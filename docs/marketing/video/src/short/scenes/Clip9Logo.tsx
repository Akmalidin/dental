import React, { useMemo } from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { shortTheme as theme } from "../theme";
import { fadeIn, riseIn } from "../ShortShell";

export const Clip9Logo: React.FC = () => {
  const frame = useCurrentFrame();

  const particles = useMemo(() => {
    const rng = (seed: number) => {
      let s = seed;
      return () => {
        s = (s * 9301 + 49297) % 233280;
        return s / 233280;
      };
    };
    return [...Array(36)].map((_, i) => {
      const r = rng(i * 17 + 3);
      const edge = Math.floor(r() * 4);
      const along = r();
      const from =
        edge === 0 ? { x: along * 100, y: -8 } : edge === 1 ? { x: 108, y: along * 100 } : edge === 2 ? { x: along * 100, y: 108 } : { x: -8, y: along * 100 };
      const to = { x: 42 + (r() - 0.5) * 26, y: 46 + (r() - 0.5) * 8 };
      return { from, to, delay: Math.floor(r() * 20) };
    });
  }, []);

  const textOpacity = fadeIn(frame, 28, 18);
  const particleOut = interpolate(frame, [26, 40], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <div style={{ position: "absolute", inset: 0, background: theme.bgWhite }}>
      {particles.map((p, i) => {
        const local = interpolate(frame, [p.delay, p.delay + 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        const ease = local * local * (3 - 2 * local);
        const x = p.from.x + (p.to.x - p.from.x) * ease;
        const y = p.from.y + (p.to.y - p.from.y) * ease;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${x}%`,
              top: `${y}%`,
              width: 7,
              height: 7,
              marginLeft: -3.5,
              marginTop: -3.5,
              borderRadius: 3.5,
              background: i % 3 === 0 ? theme.coral : theme.cobalt,
              opacity: fadeIn(frame, p.delay, 6) * particleOut,
              boxShadow: `0 0 8px 2px ${i % 3 === 0 ? theme.coralSoft : theme.cobaltSoft}`,
            }}
          />
        );
      })}

      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, opacity: textOpacity, transform: `translateY(${riseIn(frame, 28, 18)}px)` }}>
          <div style={{ width: 52, height: 52, borderRadius: 14, background: theme.coral, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2C8 2 5 4.5 5 8.2c0 2.6.9 3.4 1.4 6.9.4 2.7.9 5.4 2.4 5.4 1.7 0 1.6-3.6 2-5.4.3-1.2.9-1.2 1.2 0 .4 1.8.3 5.4 2 5.4 1.5 0 2-2.7 2.4-5.4.5-3.5 1.4-4.3 1.4-6.9C19 4.5 16 2 12 2Z"
                fill="#ffffff"
              />
            </svg>
          </div>
          <span style={{ fontFamily: theme.font.display, fontWeight: 800, fontSize: 68, color: theme.ink, letterSpacing: "-0.01em" }}>ODONTIS</span>
        </div>
        <div style={{ opacity: fadeIn(frame, 52, 16), transform: `translateY(${riseIn(frame, 52, 16)}px)` }}>
          <span style={{ fontFamily: theme.font.mono, fontSize: 26, letterSpacing: "0.1em", textTransform: "uppercase", color: theme.cobalt }}>
            Полная CRM для стоматологии
          </span>
        </div>
        <div
          style={{
            marginTop: 8,
            opacity: fadeIn(frame, 74, 16),
            transform: `translateY(${riseIn(frame, 74, 16)}px)`,
            fontFamily: theme.font.mono,
            fontSize: 24,
            color: theme.teal,
            background: theme.tealSoft,
            border: `1.5px solid rgba(14,156,125,.4)`,
            borderRadius: 12,
            padding: "12px 24px",
          }}
        >
          Подключим клинику за 1 день
        </div>
      </div>
    </div>
  );
};
