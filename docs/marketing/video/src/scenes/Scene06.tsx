import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene06: React.FC = () => {
  return (
    <FeatureShell fdi="18" chip="WhatsApp и Telegram" caption="Сами напоминают о приёме и присылают кнопки подтверждения">
      <PageFrame file="messages.jpg" duration={194} width={1420} zoomFrom={1.1} panXPct={-2} cursorPoints={[{ x: 22, y: 28 }]} />
    </FeatureShell>
  );
};
