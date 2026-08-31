import React, { useMemo } from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { shortTheme as theme } from "../theme";
import { fadeIn } from "../ShortShell";

// Точки на контуре зуба (упрощённый силуэт), к которым слетаются частицы.
function toothOutline(n: number): { x: number; y: number }[] {
  const pts: { x: number; y: number }[] = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    // грубая "зубная" форма: шире сверху (коронка), уже снизу (корень)
    const top = 0.5 - 0.5 * Math.cos(a);
    const rx = 15 * (1 - top * 0.35);
    const ry = 20;
    const cy = -4 + Math.sin(a) * ry * (a > Math.PI ? 1.3 : 1);
    pts.push({ x: 50 + Math.cos(a) * rx, y: 50 + cy * 0.6 });
  }
  return pts;
}

export const Clip2Transition: React.FC = () => {
  const frame = useCurrentFrame();
  const duration = 90;
  const t = interpolate(frame, [0, duration], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const bgT = interpolate(frame, [10, duration - 6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  const particles = useMemo(() => {
    const targets = toothOutline(46);
    const rng = (seed: number) => {
      let s = seed;
      return () => {
        s = (s * 9301 + 49297) % 233280;
        return s / 233280;
      };
    };
    return targets.map((tp, i) => {
      const r = rng(i * 13 + 7);
      const angle = r() * Math.PI * 2;
      const dist = 60 + r() * 55;
      return {
        from: { x: 50 + Math.cos(angle) * dist, y: 50 + Math.sin(angle) * dist },
        to: tp,
        delay: Math.floor(r() * 26),
      };
    });
  }, []);

  const drawT = interpolate(frame, [46, duration], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <div style={{ position: "absolute", inset: 0, background: `linear-gradient(${theme.bgDark}, ${theme.bgDark})` }}>
      <div style={{ position: "absolute", inset: 0, background: theme.bgWhite, opacity: bgT }} />
      {particles.map((p, i) => {
        const local = interpolate(frame, [p.delay, p.delay + 30], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const ease = local * local * (3 - 2 * local);
        const x = p.from.x + (p.to.x - p.from.x) * ease;
        const y = p.from.y + (p.to.y - p.from.y) * ease;
        const op = fadeIn(frame, p.delay, 8) * interpolate(frame, [duration - 14, duration], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${x}%`,
              top: `${y}%`,
              width: 6,
              height: 6,
              marginLeft: -3,
              marginTop: -3,
              borderRadius: 3,
              background: theme.cobalt,
              opacity: op,
              boxShadow: `0 0 8px 2px ${theme.cobaltSoft}`,
            }}
          />
        );
      })}

      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", opacity: drawT }}>
        <svg width="180" height="220" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 2C8 2 5 4.5 5 8.2c0 2.6.9 3.4 1.4 6.9.4 2.7.9 5.4 2.4 5.4 1.7 0 1.6-3.6 2-5.4.3-1.2.9-1.2 1.2 0 .4 1.8.3 5.4 2 5.4 1.5 0 2-2.7 2.4-5.4.5-3.5 1.4-4.3 1.4-6.9C19 4.5 16 2 12 2Z"
            fill={theme.cobalt}
            opacity={0.9}
          />
        </svg>
      </div>
    </div>
  );
};
