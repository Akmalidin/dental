import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const ScenePrices: React.FC = () => {
  return (
    <FeatureShell fdi="35" chip="Услуги и цены" caption="Прайс-лист — прозрачные цены на каждую услугу, без звонков «уточнить»">
      <PageFrame
        file="services.jpg"
        duration={176}
        width={1420}
        zoomFrom={1.1}
        panXPct={-2}
        cursorPoints={[{ x: 26, y: 20 }, { x: 95, y: 4 }]}
      />
    </FeatureShell>
  );
};
