import React from "react";
import { Composition } from "remotion";
import { StomAd, TOTAL_FRAMES } from "./Video";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="StomAd"
      component={StomAd}
      durationInFrames={TOTAL_FRAMES}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
