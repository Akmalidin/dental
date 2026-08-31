import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene08: React.FC = () => {
  return (
    <FeatureShell fdi="41" chip="Аудит-центр" caption="Каждое изменение в карточке — с именем и временем">
      <PageFrame file="audit.jpg" duration={151} width={1420} zoomFrom={1.1} panXPct={-2} cursorPoints={[{ x: 20, y: 19 }]} />
    </FeatureShell>
  );
};
