import React from "react";
import { useCurrentFrame, interpolate } from "remotion";
import { theme } from "../theme";
import { SceneShell, Caption, fadeIn } from "../SceneShell";

const NOTEBOOKS = [
  { left: 210, top: 250, w: 300, h: 220, rot: -7 },
  { left: 470, top: 300, w: 280, h: 210, rot: 4 },
  { left: 330, top: 460, w: 300, h: 210, rot: -3 },
  { left: 640, top: 470, w: 260, h: 190, rot: 6 },
];

export const Scene01: React.FC = () => {
  const frame = useCurrentFrame();

  // администратор листает тетради одну за другой в поисках карточки —
  // палец/маркер скачет между стопками, а не едет по одной странице
  const hopIndex = Math.min(NOTEBOOKS.length - 1, Math.floor(frame / 22));
  const hop = NOTEBOOKS[hopIndex];
  const hopX = interpolate(frame % 22, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  const clockOpacity = fadeIn(frame, 30, 16);
  const elapsedMin = Math.min(6, Math.floor(frame / 18));

  return (
    <SceneShell>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          filter: "saturate(.55) brightness(.9)",
        }}
      >
        {/* messy monitor windows */}
        <div style={{ position: "absolute", right: 260, top: 190, opacity: fadeIn(frame, 0, 20) }}>
          <div
            style={{
              width: 360,
              height: 230,
              background: theme.panel2,
              border: `1px solid ${theme.border}`,
              borderRadius: 10,
            }}
          >
            <div style={{ height: 26, borderBottom: `1px solid ${theme.border}`, display: "flex", alignItems: "center", gap: 6, padding: "0 10px" }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: theme.muted, opacity: 0.5 }} />
              <span style={{ width: 8, height: 8, borderRadius: 4, background: theme.muted, opacity: 0.5 }} />
            </div>
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                style={{
                  height: 12,
                  margin: "12px 14px",
                  width: `${70 - i * 6}%`,
                  background: theme.muted,
                  opacity: 0.25,
                  borderRadius: 3,
                }}
              />
            ))}
          </div>
        </div>

        {/* стопка тетрадей — админ перебирает их одну за другой */}
        {NOTEBOOKS.map((n, i) => {
          const op = fadeIn(frame, i * 6, 14);
          const active = i === hopIndex;
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: n.left,
                top: n.top,
                width: n.w,
                height: n.h,
                background: `repeating-linear-gradient(${theme.panel2} 0 4px, transparent 4px 30px), ${theme.panel}`,
                border: `1px solid ${active ? "rgba(255,183,74,.5)" : theme.border}`,
                borderRadius: 4,
                opacity: op,
                transform: `rotate(${n.rot}deg) scale(${active ? 1.04 : 1})`,
                boxShadow: active ? "0 26px 50px rgba(0,0,0,.55)" : "0 14px 30px rgba(0,0,0,.4)",
                transition: "none",
                zIndex: active ? 5 : 1,
              }}
            />
          );
        })}

        {/* "рука/маркер" — прыгает от тетради к тетради */}
        <div
          style={{
            position: "absolute",
            left: hop.left + 24,
            top: hop.top + 30 + hopX * (hop.h - 60),
            width: 84,
            height: 22,
            borderRadius: 5,
            background: theme.accent2,
            opacity: 0.8 * fadeIn(frame, 0, 16),
            transform: `rotate(${hop.rot}deg)`,
          }}
        />

        {/* таймер — сколько уже ищут карточку */}
        <div
          style={{
            position: "absolute",
            left: 210,
            top: 210,
            opacity: clockOpacity,
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontFamily: theme.font.mono,
            fontSize: 20,
            color: theme.accent2,
            background: theme.accent2Soft,
            border: "1.5px solid rgba(255,183,74,.4)",
            borderRadius: 8,
            padding: "6px 12px",
          }}
        >
          ⏱ ищут карточку — {elapsedMin} мин
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          top: 96,
          left: 96,
          fontFamily: theme.font.mono,
          fontSize: 22,
          color: theme.muted,
          opacity: fadeIn(frame, 0, 20),
        }}
      >
        РЕГИСТРАТУРА · 8:47
      </div>

      <Caption text="Администратор ищет карточку пациента в тетрадях — уже который день" frame={frame} start={30} />
    </SceneShell>
  );
};
