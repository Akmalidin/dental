import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { shortTheme as theme } from "../short/theme";

// Чистый лого-кадр: значок-зуб + wordmark "ODONTIS" на белом — тот же
// значок, что в реальном сайдбаре приложения (см. BrandBug в short/ShortShell.tsx),
// без частиц — коротко и быстро для вставки между сценой боли и дашбордом.
export const LogoCard: React.FC = () => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, 12], [0.88, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const opacity = interpolate(frame, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <div style={{ position: "absolute", inset: 0, background: theme.bgWhite, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 20, opacity, transform: `scale(${scale})` }}>
        <div style={{ width: 76, height: 76, borderRadius: 20, background: theme.coral, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 18px 40px ${theme.coralSoft}` }}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 2C8 2 5 4.5 5 8.2c0 2.6.9 3.4 1.4 6.9.4 2.7.9 5.4 2.4 5.4 1.7 0 1.6-3.6 2-5.4.3-1.2.9-1.2 1.2 0 .4 1.8.3 5.4 2 5.4 1.5 0 2-2.7 2.4-5.4.5-3.5 1.4-4.3 1.4-6.9C19 4.5 16 2 12 2Z"
              fill="#ffffff"
            />
          </svg>
        </div>
        <span style={{ fontFamily: theme.font.display, fontWeight: 800, fontSize: 96, color: theme.ink, letterSpacing: "-0.01em" }}>ODONTIS</span>
      </div>
    </div>
  );
};
