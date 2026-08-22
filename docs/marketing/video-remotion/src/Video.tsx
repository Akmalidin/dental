import React from 'react';
import {Series} from 'remotion';
import {
  Scene01,
  Scene02,
  Scene03,
  Scene04,
  Scene05,
  Scene06,
  Scene07,
  Scene08,
  Scene09,
  Scene10,
  Scene11,
  Scene12,
} from './scenes';

// Frame durations follow the shot list in docs/marketing/advertising_video_script.md (30fps).
export const StomAsiaAd: React.FC = () => {
  return (
    <Series>
      <Series.Sequence durationInFrames={120} name="01 Было">
        <Scene01 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={150} name="02 Эскалация">
        <Scene02 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={120} name="03 Бренд">
        <Scene03 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={120} name="04 Расписание">
        <Scene04 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90} name="05 Карточка пациента">
        <Scene05 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={120} name="06 WhatsApp/Telegram">
        <Scene06 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={120} name="07 Финансы и склад">
        <Scene07 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90} name="08 Аудит-центр">
        <Scene08 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={60} name="09 Офлайн-режим">
        <Scene09 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={90} name="10 Аналитика">
        <Scene10 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={120} name="11 Было/Стало">
        <Scene11 />
      </Series.Sequence>
      <Series.Sequence durationInFrames={150} name="12 CTA">
        <Scene12 />
      </Series.Sequence>
    </Series>
  );
};

export const TOTAL_DURATION_IN_FRAMES = 1350;
export const FPS = 30;
