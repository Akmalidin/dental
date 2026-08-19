import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene05: React.FC = () => {
  return (
    <FeatureShell fdi="21" chip="Карточки пациентов" caption="История лечений и баланс — на одном экране">
      <PageFrame file="patientcard.jpg" duration={95} width={1420} zoomFrom={1.1} panXPct={2} cursorPoints={[{ x: 34, y: 32 }]} />
    </FeatureShell>
  );
};
