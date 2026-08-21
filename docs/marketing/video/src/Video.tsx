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
import { ScenePrices } from "./scenes/ScenePrices";
import { Scene08 } from "./scenes/Scene08";
import { Scene09 } from "./scenes/Scene09";
import { Scene10 } from "./scenes/Scene10";
import { Scene11 } from "./scenes/Scene11";
import { Scene12 } from "./scenes/Scene12";

export type SceneMeta = {
  id: string;
  Component: React.FC;
  frames: number;
  voLeadIn: number; // кадры до начала VO внутри сцены
  voDur: number; // кадры длительности VO-файла (audio/vo/<id>.wav)
};

// С озвучкой (espeak-ng, см. gen_vo.py) — длительность каждой сцены =
// отступ до реплики + длина реплики + хвост. См.
// docs/marketing/advertising_video_script.md за исходным сценарием.
export const SCENES: SceneMeta[] = [
  { id: "01", Component: Scene01, frames: 190, voLeadIn: 18, voDur: 154 },
  { id: "02", Component: Scene02, frames: 269, voLeadIn: 18, voDur: 233 },
  { id: "03", Component: Scene03, frames: 127, voLeadIn: 27, voDur: 82 },
  { id: "04", Component: Scene04, frames: 135, voLeadIn: 18, voDur: 99 },
  { id: "05", Component: Scene05, frames: 132, voLeadIn: 18, voDur: 96 },
  { id: "06", Component: Scene06, frames: 194, voLeadIn: 18, voDur: 158 },
  { id: "07", Component: Scene07, frames: 179, voLeadIn: 18, voDur: 143 },
  { id: "prices", Component: ScenePrices, frames: 176, voLeadIn: 18, voDur: 140 },
  { id: "08", Component: Scene08, frames: 151, voLeadIn: 18, voDur: 115 },
  { id: "09", Component: Scene09, frames: 134, voLeadIn: 18, voDur: 98 },
  { id: "10", Component: Scene10, frames: 144, voLeadIn: 18, voDur: 108 },
  { id: "11", Component: Scene11, frames: 150, voLeadIn: 18, voDur: 114 },
  { id: "12", Component: Scene12, frames: 240, voLeadIn: 18, voDur: 189 },
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
      <Audio src={staticFile("audio/music.wav")} volume={0.38} />
      {SCENES.map((s, i) => (
        <Sequence key={s.id} from={SCENE_STARTS[i]} durationInFrames={s.frames} name={`scene-${s.id}`}>
          <s.Component />
          <Sequence from={s.voLeadIn} durationInFrames={s.voDur} name={`vo-${s.id}`}>
            <Audio src={staticFile(`audio/vo/${s.id}.wav`)} volume={1} />
          </Sequence>
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
