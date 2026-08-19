import React from "react";
import { FeatureShell } from "../FeatureShell";
import { PageFrame } from "../PageFrame";

export const Scene06: React.FC = () => {
  return (
    <FeatureShell fdi="18" chip="WhatsApp и Telegram" caption="Сами напоминают о приёме и присылают кнопки подтверждения">
      <PageFrame file="messages.jpg" duration={105} width={1420} zoomFrom={1.1} panXPct={-2} />
    </FeatureShell>
  );
};
