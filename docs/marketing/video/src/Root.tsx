import React from "react";
import { Composition } from "remotion";
import { StomAd, TOTAL_FRAMES } from "./Video";
import { StomTour, TOUR_TOTAL_FRAMES } from "./TourVideo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="StomAd" component={StomAd} durationInFrames={TOTAL_FRAMES} fps={30} width={1920} height={1080} />
      <Composition id="StomTour" component={StomTour} durationInFrames={TOUR_TOTAL_FRAMES} fps={30} width={1920} height={1080} />
    </>
  );
};
