import React from "react";
import { Composition } from "remotion";
import { StomAd, TOTAL_FRAMES } from "./Video";
import { StomTour, TOUR_TOTAL_FRAMES } from "./TourVideo";
import { OdontisShort, SHORT_TOTAL_FRAMES } from "./ShortVideo";
import { LogoBridge, TOTAL as LOGO_BRIDGE_TOTAL } from "./bridge/LogoBridgeVideo";
import { PatientSearch, TOTAL as PATIENT_SEARCH_TOTAL } from "./bridge/PatientSearchVideo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="StomAd" component={StomAd} durationInFrames={TOTAL_FRAMES} fps={30} width={1920} height={1080} />
      <Composition id="StomTour" component={StomTour} durationInFrames={TOUR_TOTAL_FRAMES} fps={30} width={1920} height={1080} />
      <Composition id="OdontisShort" component={OdontisShort} durationInFrames={SHORT_TOTAL_FRAMES} fps={30} width={1080} height={1920} />
      <Composition id="LogoBridge" component={LogoBridge} durationInFrames={LOGO_BRIDGE_TOTAL} fps={30} width={1920} height={1080} />
      <Composition id="PatientSearch" component={PatientSearch} durationInFrames={PATIENT_SEARCH_TOTAL} fps={30} width={1920} height={1080} />
    </>
  );
};
