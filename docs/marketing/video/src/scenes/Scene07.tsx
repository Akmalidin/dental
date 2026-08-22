import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene07: React.FC = () => {
  return (
    <FeatureShell fdi="31" chip="Финансы и склад" caption="Касса и склад материалов сходятся сами, без сверки по тетрадям">
      <PageFrame file="cashdesk.jpg" duration={179} width={1420} zoomFrom={1.1} panXPct={3} cursorPoints={[{ x: 26, y: 32 }]} />
    </FeatureShell>
  );
};
