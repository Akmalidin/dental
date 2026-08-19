import React from "react";
import { FONT_FACE_CSS } from "./embeddedFonts";

// Шрифты встроены как data: URI (см. embed_fonts.py) — рендерятся синхронно,
// без fetch к dev-серверу/сети, поэтому не зависят от сети и не могут
// зависнуть на delayRender() при параллельном рендере кадров.
export const FontFaces: React.FC = () => <style>{FONT_FACE_CSS}</style>;
