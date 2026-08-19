import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { FontFaces } from "./Fonts";
import { theme } from "./theme";

import { Scene01 } from "./scenes/Scene01";
import { Scene02 } from "./scenes/Scene02";
import { Scene03 } from "./scenes/Scene03";
import { Scene04 } from "./scenes/Scene04";
import { Scene05 } from "./scenes/Scene05";
import { Scene06 } from "./scenes/Scene06";
import { Scene07 } from "./scenes/Scene07";
import { Scene08 } from "./scenes/Scene08";
import { Scene09 } from "./scenes/Scene09";
import { Scene10 } from "./scenes/Scene10";
import { Scene11 } from "./scenes/Scene11";
import { Scene12 } from "./scenes/Scene12";

export type SceneMeta = {
  id: string;
  Component: React.FC;
  frames: number;
};

// Без озвучки — темп сцен подобран под комфортное чтение подписи в кадре
// (Caption/чипы), а не под длину реплики диктора. См.
// docs/marketing/advertising_video_script.md за исходным сценарием/таймкодами.
export const SCENES: SceneMeta[] = [
  { id: "01", Component: Scene01, frames: 100 },
  { id: "02", Component: Scene02, frames: 140 },
  { id: "03", Component: Scene03, frames: 95 },
  { id: "04", Component: Scene04, frames: 100 },
  { id: "05", Component: Scene05, frames: 95 },
  { id: "06", Component: Scene06, frames: 105 },
  { id: "07", Component: Scene07, frames: 100 },
  { id: "08", Component: Scene08, frames: 95 },
  { id: "09", Component: Scene09, frames: 85 },
  { id: "10", Component: Scene10, frames: 95 },
  { id: "11", Component: Scene11, frames: 110 },
  { id: "12", Component: Scene12, frames: 130 },
];

export const TOTAL_FRAMES = SCENES.reduce((s, x) => s + x.frames, 0);

let acc = 0;
export const SCENE_STARTS = SCENES.map((s) => {
  const start = acc;
  acc += s.frames;
  return start;
});

export const StomAd: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bg }}>
      <FontFaces />
      <Audio src={staticFile("audio/music.wav")} volume={0.5} />
      {SCENES.map((s, i) => (
        <Sequence key={s.id} from={SCENE_STARTS[i]} durationInFrames={s.frames} name={`scene-${s.id}`}>
          <s.Component />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
