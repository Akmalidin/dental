import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { theme } from "./theme";

export type CursorPoint = { x: number; y: number }; // % внутри области скриншота (0–100)

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

// Курсор, который заходит в кадр, доезжает до точки, «кликает» (пульс +
// лёгкое приседание), едет ко второй точке, снова кликает и замирает —
// имитация того, что кто-то реально пользуется интерфейсом на скриншоте.
// Координаты — в процентах от области самого скриншота (см. PageFrame),
// поэтому не зависят от текущего zoom/pan картинки под курсором.
export const AnimatedCursor: React.FC<{ points: CursorPoint[]; duration: number }> = ({ points, duration }) => {
  const frame = useCurrentFrame();
  if (points.length === 0) return null;

  const start: CursorPoint = { x: -6, y: 10 };
  const clickDur = 16;
  const t1 = Math.max(18, Math.round(duration * 0.26));
  const p1End = t1 + clickDur;
  const t2 = points.length > 1 ? p1End + Math.max(14, Math.round(duration * 0.28)) : p1End;
  const p2End = t2 + clickDur;

  const ease = Easing.inOut(Easing.quad);

  let pos: CursorPoint;
  let clickWindows: number[] = [];

  if (frame <= t1) {
    const t = interpolate(frame, [0, t1], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
    pos = { x: lerp(start.x, points[0].x, t), y: lerp(start.y, points[0].y, t) };
  } else if (frame <= p1End || points.length < 2) {
    pos = points[0];
  } else if (frame <= t2) {
    const t = interpolate(frame, [p1End, t2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
    pos = { x: lerp(points[0].x, points[1].x, t), y: lerp(points[0].y, points[1].y, t) };
  } else {
    pos = points[1];
  }

  if (frame >= t1 && frame <= p1End + 4) clickWindows.push(t1);
  if (points.length > 1 && frame >= t2 && frame <= p2End + 4) clickWindows.push(t2);

  const pressAt = (clickStart: number) =>
    interpolate(frame, [clickStart, clickStart + 5, clickStart + 11], [1, 0.82, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  const isClicking = frame >= t1 && frame <= t1 + 11 || (points.length > 1 && frame >= t2 && frame <= t2 + 11);
  const activeClickStart = frame <= t1 + 11 ? t1 : t2;
  const pressScale = isClicking ? pressAt(activeClickStart) : 1;

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      {clickWindows.map((clickStart, i) => {
        const local = frame - clickStart;
        if (local < 0 || local > clickDur) return null;
        const p = clickStart === t1 ? points[0] : points[1];
        const t = local / clickDur;
        const scale = lerp(0.2, 2.1, t);
        const opacity = 1 - t;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${p.x}%`,
              top: `${p.y}%`,
              width: 30,
              height: 30,
              marginLeft: -15,
              marginTop: -15,
              borderRadius: "50%",
              border: `2px solid ${theme.accent}`,
              background: theme.accentSoft,
              opacity,
              transform: `scale(${scale})`,
            }}
          />
        );
      })}
      <div
        style={{
          position: "absolute",
          left: `${pos.x}%`,
          top: `${pos.y}%`,
          transform: `scale(${pressScale})`,
          transformOrigin: "6px 4px",
          filter: "drop-shadow(0 3px 5px rgba(0,0,0,.45))",
        }}
      >
        <svg width="30" height="34" viewBox="0 0 22 26">
          <path
            d="M1 1 L1 19.5 L5.5 15.7 L8.3 22.5 L11.3 21.2 L8.6 14.6 L14.5 14.6 Z"
            fill="#ffffff"
            stroke="#1a2129"
            strokeWidth="1.4"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  );
};
