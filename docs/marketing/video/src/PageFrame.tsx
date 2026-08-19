import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { theme } from "./theme";

// Реальный скриншот страницы системы (см. public/screens/*.jpg, генерируются
// screenshot.js в scratchpad — не абстрактный макет, а настоящий /new/* UI)
// в рамке «окна браузера» с медленным Ken Burns zoom/pan.
//
// duration — длительность СВОЕЙ сцены в кадрах (не всей композиции!). Внутри
// вложенной <Sequence> useVideoConfig() всё равно вернул бы длительность
// всего видео, а не сцены, — с ним зум почти не успевал бы прогрессировать
// за короткую сцену, поэтому длительность передаём явно.
export const PageFrame: React.FC<{
  file: string;
  duration: number;
  width?: number;
  zoomFrom?: number;
  zoomTo?: number;
  panXPct?: number; // % ширины изображения — лёгкий боковой пан
  focusTop?: boolean; // true = якорь кадрирования сверху (для длинных списков)
}> = ({ file, duration, width = 1360, zoomFrom = 1.07, zoomTo = 1.0, panXPct = 0, focusTop = true }) => {
  const frame = useCurrentFrame();
  const t = Math.min(1, frame / Math.max(duration - 1, 1));
  const scale = interpolate(t, [0, 1], [zoomFrom, zoomTo]);
  const panX = interpolate(t, [0, 1], [0, panXPct]);
  const height = (width * 1080) / 1920;

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          width,
          borderRadius: 14,
          overflow: "hidden",
          border: `1px solid ${theme.border}`,
          boxShadow: "0 44px 100px rgba(0,0,0,.55), 0 0 0 1px rgba(0,0,0,.2)",
          background: theme.panel,
        }}
      >
        <div style={{ height: 30, background: "#e8ebef", display: "flex", alignItems: "center", gap: 7, padding: "0 14px" }}>
          <span style={{ width: 10, height: 10, borderRadius: 5, background: "#ff5f57" }} />
          <span style={{ width: 10, height: 10, borderRadius: 5, background: "#febc2e" }} />
          <span style={{ width: 10, height: 10, borderRadius: 5, background: "#28c840" }} />
        </div>
        <div style={{ width, height, overflow: "hidden", position: "relative" }}>
          <Img
            src={staticFile(`screens/${file}`)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: focusTop ? "top" : "center",
              transform: `scale(${scale}) translateX(${panX}%)`,
              transformOrigin: focusTop ? "top center" : "center",
            }}
          />
        </div>
      </div>
    </div>
  );
};
