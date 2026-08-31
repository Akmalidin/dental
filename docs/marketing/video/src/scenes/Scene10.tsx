import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene10: React.FC = () => {
  return (
    <FeatureShell fdi="48" chip="Аналитика" caption="Выручка и загрузка врачей — в реальном времени">
      <PageFrame file="reports.jpg" duration={144} width={1420} zoomFrom={1.1} panXPct={2} cursorPoints={[{ x: 32, y: 35 }]} />
    </FeatureShell>
  );
};
