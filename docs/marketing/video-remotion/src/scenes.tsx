import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {theme} from './theme';
import {fonts} from './fonts';
import {Backdrop, Chip, SceneLabel, ArchLogo, Wordmark, fadeIn, riseIn} from './components';

const clamp = (v: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));

/* ---------- 01 · Было: бумажный хаос ---------- */
export const Scene01: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 120], [1, 1.07], {extrapolateRight: 'clamp'});
  return (
    <Backdrop glow="none">
      <div
        style={{
          width: 1500,
          height: 780,
          position: 'relative',
          transform: `scale(${zoom})`,
          filter: 'saturate(0.55) brightness(0.92)',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 90,
            top: 100,
            width: 620,
            height: 560,
            background: `repeating-linear-gradient(${theme.panel2} 0 5px, transparent 5px 26px), ${theme.panel}`,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            transform: 'rotate(-3.5deg)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            right: 120,
            top: 70,
            width: 420,
            height: 300,
            background: theme.panel2,
            border: `1px solid ${theme.border}`,
            borderRadius: 10,
          }}
        >
          <div style={{margin: '18px', height: 10, width: '55%', background: theme.muted, opacity: 0.4, borderRadius: 5}} />
        </div>
        <div
          style={{
            position: 'absolute',
            right: 70,
            bottom: 90,
            width: 340,
            height: 240,
            background: theme.panel2,
            border: `1px solid ${theme.border}`,
            borderRadius: 10,
            opacity: 0.85,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 70,
            bottom: 40,
            fontFamily: fonts.mono,
            fontSize: 22,
            letterSpacing: '0.06em',
            color: theme.muted,
            opacity: fadeIn(frame, 20, 30),
          }}
        >
          8:47 · РЕГИСТРАТУРА
        </div>
      </div>
    </Backdrop>
  );
};

/* ---------- 02 · Эскалация проблемы ---------- */
const alertRow = (frame: number, from: number, text: string) => {
  const o = fadeIn(frame, from, 14);
  const x = riseIn(frame, from, 14, -40);
  return (
    <div key={text} style={{opacity: o, transform: `translateX(${x}px)`}}>
      <Chip tone="accent2" style={{fontSize: 30}}>
        ⚠ {text}
      </Chip>
    </div>
  );
};

export const Scene02: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Backdrop glow="none">
      <div style={{display: 'flex', flexDirection: 'column', gap: 22, alignItems: 'flex-start'}}>
        {alertRow(frame, 0, 'Забыли напомнить о приёме')}
        {alertRow(frame, 60, 'Касса не сходится со складом')}
        {alertRow(frame, 110, 'Кто менял карточку — неизвестно')}
      </div>
    </Backdrop>
  );
};

/* ---------- 03 · Перелом: выход бренда ---------- */
export const Scene03: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Backdrop glow="accent">
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 30}}>
        <ArchLogo frame={frame} from={0} />
        <Wordmark frame={frame} from={55} size={64} />
        <div style={{opacity: fadeIn(frame, 80, 20), transform: `translateY(${riseIn(frame, 80, 20)}px)`}}>
          <span style={{fontFamily: fonts.body, fontSize: 30, color: theme.text}}>
            Один экран вместо восьми программ
          </span>
        </div>
      </div>
    </Backdrop>
  );
};

/* ---------- 04 · Расписание и записи ---------- */
export const Scene04: React.FC = () => {
  const frame = useCurrentFrame();
  const cells = 15;
  const onPattern = [1, 4, 5, 8, 11];
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, 130px)', gap: 14}}>
          {Array.from({length: cells}).map((_, i) => {
            const litFrom = 10 + i * 4;
            const isOn = onPattern.includes(i);
            const isConflict = i === 4;
            const lit = fadeIn(frame, litFrom, 12);
            const flash = isConflict
              ? interpolate(frame, [70, 78, 86, 94], [0, 1, 0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                })
              : 0;
            const bg = isConflict && flash > 0.5 ? theme.accent2Soft : isOn ? theme.accentSoft : theme.panel2;
            const border = isConflict && flash > 0.5 ? theme.accent2Border : isOn ? theme.accentBorder : theme.border;
            return (
              <div
                key={i}
                style={{
                  width: 130,
                  height: 46,
                  borderRadius: 8,
                  background: bg,
                  border: `1px solid ${border}`,
                  opacity: isOn || isConflict ? lit : 0.55,
                }}
              />
            );
          })}
        </div>
        <SceneLabel text="Расписание и записи" frame={frame} from={95} />
      </div>
    </Backdrop>
  );
};

/* ---------- 05 · Карточка пациента ---------- */
export const Scene05: React.FC = () => {
  const frame = useCurrentFrame();
  const height = interpolate(frame, [0, 30], [40, 420], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <div
          style={{
            width: 620,
            height,
            background: theme.panel2,
            border: `1px solid ${theme.border}`,
            borderRadius: 16,
            padding: 28,
            overflow: 'hidden',
          }}
        >
          <div style={{height: 22, width: '48%', background: theme.ink, opacity: 0.55, borderRadius: 6, marginBottom: 22}} />
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                opacity: fadeIn(frame, 20 + i * 10, 14) * 0.3,
                height: 12,
                width: i === 1 ? '82%' : i === 2 ? '58%' : '95%',
                background: theme.muted,
                borderRadius: 4,
                marginBottom: 14,
              }}
            />
          ))}
          <div style={{opacity: fadeIn(frame, 55, 16), marginTop: 8}}>
            <Chip>баланс: 0 сом</Chip>
          </div>
        </div>
        <SceneLabel text="Карточки пациентов" frame={frame} from={65} />
      </div>
    </Backdrop>
  );
};

/* ---------- 06 · WhatsApp / Telegram ---------- */
export const Scene06: React.FC = () => {
  const frame = useCurrentFrame();
  const phoneO = fadeIn(frame, 0, 20);
  const bubbleY = riseIn(frame, 30, 22, -60);
  const bubbleO = fadeIn(frame, 30, 22);
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <div
          style={{
            width: 340,
            height: 560,
            border: `3px solid ${theme.panel2}`,
            borderRadius: 34,
            background: theme.panel,
            padding: '28px 18px',
            opacity: phoneO,
          }}
        >
          <div
            style={{
              opacity: bubbleO,
              transform: `translateY(${bubbleY}px)`,
              background: theme.accentSoft,
              border: `1px solid ${theme.accentBorder}`,
              borderRadius: '14px 14px 14px 4px',
              padding: 16,
            }}
          >
            <div style={{height: 10, width: '85%', background: theme.accent, opacity: 0.7, borderRadius: 4, marginBottom: 8}} />
            <div style={{height: 10, width: '55%', background: theme.accent, opacity: 0.7, borderRadius: 4, marginBottom: 14}} />
            <div style={{display: 'flex', gap: 8}}>
              <span
                style={{
                  opacity: fadeIn(frame, 65, 14),
                  flex: 1,
                  textAlign: 'center',
                  fontFamily: fonts.mono,
                  fontWeight: 600,
                  fontSize: 15,
                  background: theme.accent,
                  color: theme.bg,
                  borderRadius: 8,
                  padding: '10px 0',
                }}
              >
                Подтвердить
              </span>
              <span
                style={{
                  opacity: fadeIn(frame, 78, 14),
                  flex: 1,
                  textAlign: 'center',
                  fontFamily: fonts.mono,
                  fontWeight: 600,
                  fontSize: 15,
                  background: 'transparent',
                  border: `1px solid ${theme.accentBorder}`,
                  color: theme.accent,
                  borderRadius: 8,
                  padding: '10px 0',
                }}
              >
                Перенести
              </span>
            </div>
          </div>
        </div>
        <SceneLabel text="WhatsApp и Telegram" frame={frame} from={95} />
      </div>
    </Backdrop>
  );
};

/* ---------- 07 · Финансы и склад ---------- */
export const Scene07: React.FC = () => {
  const frame = useCurrentFrame();
  const heights = [130, 230, 180, 280, 200];
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <div style={{display: 'flex', alignItems: 'flex-end', gap: 22, height: 300}}>
          {heights.map((h, i) => {
            const from = 10 + i * 15;
            const grown = interpolate(frame, [from, from + 26], [0, h], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            return (
              <div
                key={i}
                style={{
                  width: 70,
                  height: grown,
                  borderRadius: '6px 6px 0 0',
                  background: `linear-gradient(to top, ${theme.accent}, ${theme.accentSoft})`,
                }}
              />
            );
          })}
        </div>
        <SceneLabel text="Финансы и склад" frame={frame} from={95} />
      </div>
    </Backdrop>
  );
};

/* ---------- 08 · Аудит-центр ---------- */
export const Scene08: React.FC = () => {
  const frame = useCurrentFrame();
  const rows = ['Изменена запись — Асель Т.', 'Обновлена карточка — Марат К.', 'Правка баланса — Айгуль С.'];
  const glow = 0.6 + 0.4 * Math.sin(frame / 6);
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <div style={{display: 'flex', flexDirection: 'column', gap: 16, width: 700}}>
          {rows.map((r, i) => {
            const from = i * 14;
            const hi = i === 1;
            return (
              <div
                key={r}
                style={{
                  opacity: fadeIn(frame, from, 14),
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  padding: '12px 18px',
                  borderRadius: 8,
                  background: theme.panel2,
                  border: `1px solid ${hi ? theme.accentBorder : theme.border}`,
                }}
              >
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: hi ? theme.accent : theme.muted,
                    boxShadow: hi ? `0 0 ${10 * glow}px ${theme.accent}` : 'none',
                  }}
                />
                <span style={{fontFamily: fonts.mono, fontSize: 22, color: hi ? theme.accent : theme.muted}}>{r}</span>
              </div>
            );
          })}
        </div>
        <SceneLabel text="Аудит-центр" frame={frame} from={65} />
      </div>
    </Backdrop>
  );
};

/* ---------- 09 · Офлайн-режим ---------- */
export const Scene09: React.FC = () => {
  const frame = useCurrentFrame();
  const wifiO = fadeIn(frame, 0, 15) - fadeIn(frame, 12, 12);
  const syncO = fadeIn(frame, 20, 20);
  const rot = interpolate(frame, [20, 60], [0, 140], {extrapolateRight: 'clamp'});
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <div style={{width: 180, height: 180, position: 'relative'}}>
          <svg
            width={180}
            height={180}
            viewBox="0 0 60 60"
            style={{position: 'absolute', opacity: clamp(wifiO)}}
          >
            <path
              d="M10 26a24 24 0 0 1 40 0M18 34a14 14 0 0 1 24 0"
              fill="none"
              stroke={theme.muted}
              strokeWidth={3}
              strokeLinecap="round"
            />
            <circle cx={30} cy={44} r={3} fill={theme.muted} />
          </svg>
          <svg
            width={180}
            height={180}
            viewBox="0 0 60 60"
            style={{position: 'absolute', opacity: syncO, transform: `rotate(${rot}deg)`}}
          >
            <path
              d="M10 30a20 20 0 0 1 34-14M50 30a20 20 0 0 1-34 14"
              fill="none"
              stroke={theme.accent}
              strokeWidth={3}
              strokeLinecap="round"
            />
            <circle cx={44} cy={16} r={4} fill={theme.accent} />
            <circle cx={16} cy={44} r={4} fill={theme.accent} />
          </svg>
        </div>
        <SceneLabel text="Офлайн-режим" frame={frame} from={35} />
      </div>
    </Backdrop>
  );
};

/* ---------- 10 · Аналитика ---------- */
export const Scene10: React.FC = () => {
  const frame = useCurrentFrame();
  const linePath = 'M0,88 L60,64 L140,72 L220,36 L300,46 L400,12';
  const pathLen = 460;
  const drawn = interpolate(frame, [0, 50], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const areaO = fadeIn(frame, 20, 30);
  return (
    <Backdrop>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44}}>
        <svg width={700} height={180} viewBox="0 0 400 100">
          <path d={`${linePath} L400,100 L0,100 Z`} fill={theme.accentSoft} opacity={areaO} />
          <path
            d={linePath}
            fill="none"
            stroke={theme.accent}
            strokeWidth={3}
            strokeLinecap="round"
            strokeDasharray={pathLen}
            strokeDashoffset={pathLen * (1 - drawn)}
          />
        </svg>
        <SceneLabel text="Аналитика" frame={frame} from={60} />
      </div>
    </Backdrop>
  );
};

/* ---------- 11 · Было / Стало ---------- */
export const Scene11: React.FC = () => {
  const frame = useCurrentFrame();
  const lineH = interpolate(frame, [0, 24], [0, 100], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: theme.bg, flexDirection: 'row'}}>
      <AbsoluteFill
        style={{
          left: 0,
          width: '50%',
          background: theme.panel2,
          filter: 'grayscale(0.65) brightness(0.75)',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            opacity: fadeIn(frame, 10, 18),
            fontFamily: fonts.mono,
            fontSize: 30,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: theme.muted,
          }}
        >
          Было
        </span>
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          left: '50%',
          width: '50%',
          background: `radial-gradient(ellipse at center, ${theme.accentSoft}, ${theme.panel})`,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            opacity: fadeIn(frame, 40, 18),
            fontFamily: fonts.mono,
            fontSize: 30,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: theme.accent,
          }}
        >
          Стало
        </span>
      </AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: '50%',
          width: 2,
          height: `${lineH}%`,
          background: theme.accent,
          transform: 'translate(-50%, -50%)',
          boxShadow: `0 0 20px ${theme.accent}`,
        }}
      />
      <div style={{position: 'absolute', bottom: 90, left: 0, right: 0, textAlign: 'center', opacity: fadeIn(frame, 70, 20)}}>
        <span style={{fontFamily: fonts.body, fontSize: 30, color: theme.text}}>
          Первая неделя после подключения выглядит именно так
        </span>
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 12 · Призыв к действию ---------- */
export const Scene12: React.FC = () => {
  const frame = useCurrentFrame();
  const pulse = 1 + 0.03 * Math.sin(frame / 10);
  return (
    <Backdrop glow="accent2">
      <div
        style={{
          position: 'absolute',
          opacity: 0.22,
          transform: `translateY(220px) scale(${pulse * 1.7})`,
        }}
      >
        <ArchLogo frame={frame} from={-999} size={640} />
      </div>
      <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 26, zIndex: 1}}>
        <Wordmark frame={frame} from={0} size={40} />
        <div style={{opacity: fadeIn(frame, 40, 18), transform: `translateY(${riseIn(frame, 40, 18)}px)`}}>
          <h1
            style={{
              fontFamily: fonts.display,
              fontWeight: 800,
              fontSize: 50,
              color: theme.ink,
              textAlign: 'center',
              margin: 0,
              maxWidth: 920,
              whiteSpace: 'nowrap',
            }}
          >
            Подключим клинику за 1 день
          </h1>
        </div>
        <div style={{opacity: fadeIn(frame, 60, 18)}}>
          <span style={{fontFamily: fonts.body, fontSize: 26, color: theme.text}}>
            Первая консультация — бесплатно
          </span>
        </div>
        <div
          style={{
            opacity: fadeIn(frame, 80, 16),
            transform: `scale(${interpolate(frame, [80, 96], [0.85, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })})`,
            marginTop: 8,
          }}
        >
          <span
            style={{
              fontFamily: fonts.body,
              fontWeight: 600,
              fontSize: 26,
              background: theme.accent2,
              color: '#241503',
              padding: '18px 40px',
              borderRadius: 12,
              display: 'inline-block',
            }}
          >
            Оставить заявку · stom.asia
          </span>
        </div>
      </div>
    </Backdrop>
  );
};
