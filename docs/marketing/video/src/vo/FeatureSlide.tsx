import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

// Универсальная "фичевая" сцена (fdi-код + чип + подпись + скриншот с курсором),
// но с длительностью, подобранной под конкретный тайминг реальной озвучки —
// в отличие от Scene04/06/07/08/10/Prices, которые жёстко зашиты под StomAd.
export const FeatureSlide: React.FC<{
  fdi: string;
  chip: string;
  caption: string;
  file: string;
  duration: number;
  width?: number;
  zoomFrom?: number;
  panXPct?: number;
  cursorPoints?: { x: number; y: number }[];
}> = ({ fdi, chip, caption, file, duration, width = 1420, zoomFrom = 1.1, panXPct = 0, cursorPoints }) => (
  <FeatureShell fdi={fdi} chip={chip} caption={caption}>
    <PageFrame file={file} duration={duration} width={width} zoomFrom={zoomFrom} panXPct={panXPct} cursorPoints={cursorPoints} />
  </FeatureShell>
);
