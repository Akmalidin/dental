import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {theme} from './theme';
import {fonts} from './fonts';

export const Backdrop: React.FC<{children: React.ReactNode; glow?: 'accent' | 'accent2' | 'none'}> = ({
  children,
  glow = 'accent',
}) => {
  const glowColor = glow === 'accent2' ? 'rgba(255,183,74,0.14)' : 'rgba(63,208,201,0.14)';
  return (
    <AbsoluteFill style={{backgroundColor: theme.bg}}>
      {glow !== 'none' && (
        <AbsoluteFill
          style={{
            background: `radial-gradient(ellipse 60% 55% at 50% 38%, ${glowColor}, transparent 70%)`,
          }}
        />
      )}
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>{children}</AbsoluteFill>
    </AbsoluteFill>
  );
};

// Fades a value in over `dur` frames starting at `from`, staying at 1 after.
export const fadeIn = (frame: number, from: number, dur = 18) =>
  interpolate(frame, [from, from + dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

export const riseIn = (frame: number, from: number, dur = 18, distance = 24) =>
  interpolate(frame, [from, from + dur], [distance, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

export const Chip: React.FC<{
  children: React.ReactNode;
  tone?: 'accent' | 'accent2';
  style?: React.CSSProperties;
}> = ({children, tone = 'accent', style}) => {
  const color = tone === 'accent2' ? theme.accent2 : theme.accent;
  const soft = tone === 'accent2' ? theme.accent2Soft : theme.accentSoft;
  const border = tone === 'accent2' ? theme.accent2Border : theme.accentBorder;
  return (
    <span
      style={{
        display: 'inline-block',
        fontFamily: fonts.mono,
        fontWeight: 500,
        fontSize: 26,
        letterSpacing: '0.01em',
        color,
        background: soft,
        border: `1px solid ${border}`,
        borderRadius: 10,
        padding: '10px 20px',
        ...style,
      }}
    >
      {children}
    </span>
  );
};

export const SceneLabel: React.FC<{text: string; frame: number; from: number}> = ({text, frame, from}) => (
  <div
    style={{
      position: 'absolute',
      bottom: 90,
      opacity: fadeIn(frame, from),
      transform: `translateY(${riseIn(frame, from)}px)`,
    }}
  >
    <Chip>{text}</Chip>
  </div>
);

export const ArchLogo: React.FC<{frame: number; from: number; size?: number}> = ({frame, from, size = 520}) => {
  const drawn = interpolate(frame, [from, from + 45], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const dotScale = interpolate(frame, [from + 38, from + 58], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const pathLength = 900;
  return (
    <svg width={size} height={size * 0.4} viewBox="0 -60 800 260">
      <path
        d="M40 180 Q400 -40 760 180"
        fill="none"
        stroke={theme.accent}
        strokeWidth={5}
        strokeLinecap="round"
        strokeDasharray={pathLength}
        strokeDashoffset={pathLength * (1 - drawn)}
      />
      <circle cx={400} cy={20} r={12 * dotScale} fill={theme.accent2} />
      <circle cx={400} cy={20} r={22 * dotScale} fill="none" stroke={theme.accent2} strokeWidth={2} opacity={0.5} />
    </svg>
  );
};

export const Wordmark: React.FC<{frame: number; from: number; size?: number}> = ({frame, from, size = 56}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      opacity: fadeIn(frame, from),
      fontFamily: fonts.mono,
      fontWeight: 600,
      fontSize: size,
      color: theme.ink,
    }}
  >
    <span
      style={{
        width: size * 0.22,
        height: size * 0.22,
        borderRadius: '50%',
        background: theme.accent,
        boxShadow: `0 0 ${size * 0.4}px 4px ${theme.accentSoft}`,
      }}
    />
    stom.asia
  </div>
);

export const useLoopFrame = () => useCurrentFrame();
