import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene04: React.FC = () => {
  return (
    <FeatureShell fdi="11" chip="Расписание и записи" caption="Календарь сам не даёт записать двоих на одно время">
      <PageFrame file="schedule.jpg" duration={135} width={1420} zoomFrom={1.1} panXPct={-3} cursorPoints={[{ x: 33, y: 30 }]} />
    </FeatureShell>
  );
};
