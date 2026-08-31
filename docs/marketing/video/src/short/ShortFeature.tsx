import React from "react";
import { shortTheme as theme } from "./theme";
import { ShortShell, ShortCaption, BrandBug, fadeIn, riseIn, useCurrentFrame } from "./ShortShell";
import { PageFrame } from "../PageFrame";
import { CursorPoint } from "../AnimatedCursor";

// Клипы 3–8 сценария: вместо «абстрактной визуализации функции» — настоящий
// экран ODONTIS (см. README docs/marketing/video) в рамке окна браузера,
// с курсором, кликающим по реальному элементу. Решение по итоговой сноске
// самого сценария: абстракция хорошо продаёт настроение, но не показывает
// работающий продукт — на функциональных клипах используем реальный UI.
export const ShortFeature: React.FC<{
  file: string;
  duration: number;
  caption: string;
  cursorPoints: CursorPoint[];
  width?: number;
}> = ({ file, duration, caption, cursorPoints, width = 980 }) => {
  const frame = useCurrentFrame();
  return (
    <ShortShell bg={theme.bgWhite}>
      <BrandBug frame={frame} />
      <div
        style={{
          position: "absolute",
          top: 150,
          bottom: 300,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: fadeIn(frame, 4, 16),
          transform: `translateY(${riseIn(frame, 4, 16, 16)}px)`,
        }}
      >
        <PageFrame file={file} duration={duration} width={width} zoomFrom={1.08} cursorPoints={cursorPoints} />
      </div>
      <ShortCaption text={caption} frame={frame} start={10} />
    </ShortShell>
  );
};
