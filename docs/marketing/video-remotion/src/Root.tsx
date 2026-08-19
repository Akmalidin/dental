import React from 'react';
import {Composition} from 'remotion';
import {StomAsiaAd, TOTAL_DURATION_IN_FRAMES, FPS} from './Video';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="StomAsiaAd"
      component={StomAsiaAd}
      durationInFrames={TOTAL_DURATION_IN_FRAMES}
      fps={FPS}
      width={1920}
      height={1080}
    />
  );
};
