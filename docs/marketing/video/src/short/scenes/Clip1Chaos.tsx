import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { shortTheme as theme } from "../theme";
import { ShortShell, ShortCaption, fadeIn } from "../ShortShell";

const PAPERS = [
  { x: 30, y: 30, r: -8, w: 260, delay: 0 },
  { x: 62, y: 24, r: 6, w: 220, delay: 4 },
  { x: 22, y: 46, r: 4, w: 240, delay: 8 },
  { x: 58, y: 50, r: -5, w: 210, delay: 12 },
];

// Иконки-«уведомления»: чат, звонок, календарь — залетают с краёв и
// «сталкиваются» у центра (лёгкий джиттер вместо честной физики).
const ICONS = [
  { kind: "chat", fromX: -10, fromY: 20, toX: 40, toY: 60, delay: 10 },
  { kind: "phone", fromX: 110, fromY: 25, toX: 62, toY: 58, delay: 22 },
  { kind: "calendar", fromX: -10, fromY: 75, toX: 48, toY: 68, delay: 34 },
  { kind: "chat", fromX: 110, fromY: 70, toX: 58, toY: 66, delay: 46 },
  { kind: "phone", fromX: 20, fromY: -10, toX: 45, toY: 62, delay: 58 },
];

const IconGlyph: React.FC<{ kind: string }> = ({ kind }) => {
  if (kind === "chat")
    return (
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
        <path d="M4 5h16v11H9l-5 4V5Z" fill={theme.coral} />
      </svg>
    );
  if (kind === "phone")
    return (
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
        <path d="M6 3l4 1 1 4-3 2c1 3 3 5 6 6l2-3 4 1 1 4c-1 2-3 2-5 1-6-2-10-6-12-12-1-2-1-4 1-5Z" fill={theme.coral} />
      </svg>
    );
  return (
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
      <rect x="4" y="5" width="16" height="15" rx="2" fill={theme.coral} />
      <rect x="4" y="5" width="16" height="4" rx="2" fill="#ffffff" opacity={0.35} />
    </svg>
  );
};

export const Clip1Chaos: React.FC = () => {
  const frame = useCurrentFrame();
  // лёгкая "ручная тряска камеры"
  const shakeX = Math.sin(frame / 3.1) * 2.2 + Math.sin(frame / 7) * 1.1;
  const shakeY = Math.cos(frame / 2.7) * 2.0 + Math.sin(frame / 5.3) * 1.2;

  return (
    <ShortShell bg={theme.bgDark}>
      <div style={{ position: "absolute", inset: 0, transform: `translate(${shakeX}px, ${shakeY}px)` }}>
        {PAPERS.map((p, i) => {
          const op = fadeIn(frame, p.delay, 10);
          const wobble = Math.sin((frame - p.delay) / 9) * 1.5;
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${p.x}%`,
                top: `${p.y}%`,
                width: p.w,
                height: p.w * 1.28,
                background: "#161c3a",
                border: "1px solid rgba(255,255,255,.08)",
                borderRadius: 6,
                opacity: op * 0.9,
                transform: `rotate(${p.r + wobble}deg)`,
                boxShadow: "0 20px 40px rgba(0,0,0,.5)",
              }}
            >
              {[...Array(5)].map((_, j) => (
                <div
                  key={j}
                  style={{
                    height: 6,
                    margin: "16px 18px",
                    width: `${70 - j * 8}%`,
                    background: "#3a4270",
                    borderRadius: 3,
                  }}
                />
              ))}
            </div>
          );
        })}

        {ICONS.map((ic, i) => {
          const local = frame - ic.delay;
          const t = interpolate(local, [0, 16], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          const op = fadeIn(frame, ic.delay, 8);
          const jx = local > 16 ? Math.sin(local / 3.3) * 1.8 : 0;
          const jy = local > 16 ? Math.cos(local / 2.9) * 1.8 : 0;
          const x = ic.fromX + (ic.toX - ic.fromX) * t + jx;
          const y = ic.fromY + (ic.toY - ic.fromY) * t + jy;
          const pulse = 1 + 0.12 * Math.sin(frame / 4 + i);
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${x}%`,
                top: `${y}%`,
                opacity: op,
                transform: `scale(${pulse}) translate(-50%,-50%)`,
                filter: "drop-shadow(0 0 10px rgba(232,93,45,.55))",
              }}
            >
              <IconGlyph kind={ic.kind} />
              <div
                style={{
                  position: "absolute",
                  top: -4,
                  right: -4,
                  width: 10,
                  height: 10,
                  borderRadius: 5,
                  background: "#ff3b3b",
                  boxShadow: "0 0 8px 2px rgba(255,59,59,.7)",
                }}
              />
            </div>
          );
        })}
      </div>

      <ShortCaption text="Клиника ведёт запись в блокноте и переписке?" frame={frame} start={70} dark />
    </ShortShell>
  );
};
