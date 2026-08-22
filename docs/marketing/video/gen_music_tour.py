#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фоновая музыка для тур-ролика (StomTour) — длиннее и спокойнее, чем в
рекламном ролике: почти всё время — ровный фоновый groove, чтобы не мешать
чтению подписей на 18 карточках. Тот же синтез-инструментарий, что и
gen_music.py (без сэмплов/сервисов)."""
import numpy as np
import wave
import os

SR = 44100
BASE = os.path.dirname(os.path.abspath(__file__))

INTRO_END = 3.0
OUTRO_START = 78.6
TOTAL = 83.6


def note_hz(name):
    SEMI_FROM_C = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    n = name[:-1]
    octave = int(name[-1])
    midi = 12 * (octave + 1) + SEMI_FROM_C[n]
    return 440.0 * (2 ** ((midi - 69) / 12))


def env_ad(n, attack, decay, sustain_level=0.0):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-6), 0, 1)
    d = np.exp(-t / max(decay, 1e-6))
    return a * (sustain_level + (1 - sustain_level) * d)


def sine(freq, n, phase=0.0):
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * freq * t + phase)


def bass_hit(freq, dur, amp=0.5):
    n = int(dur * SR)
    e = env_ad(n, 0.006, dur * 0.55, 0.05)
    t = np.arange(n) / SR
    drop = 1 - 0.04 * np.clip(t / 0.05, 0, 1)
    tone = 0.75 * np.sin(2 * np.pi * freq * drop * t) + 0.25 * sine(freq * 2, n)
    return amp * tone * e


def pluck(freq, dur, amp=0.22):
    n = int(dur * SR)
    e = env_ad(n, 0.002, dur * 0.35, 0.0)
    tone = 0.6 * sine(freq, n) + 0.3 * sine(freq * 2, n) + 0.1 * sine(freq * 3, n)
    return amp * tone * e


def pad_chord(freqs, dur, amp=0.14, lfo_hz=0.12):
    n = int(dur * SR)
    t = np.arange(n) / SR
    e = env_ad(n, dur * 0.35, dur * 0.6, 0.85)
    lfo = 1 + 0.06 * np.sin(2 * np.pi * lfo_hz * t)
    out = np.zeros(n)
    for f in freqs:
        out += np.sin(2 * np.pi * f * t) * lfo
        out += 0.5 * np.sin(2 * np.pi * (f * 1.003) * t)
    out /= len(freqs) * 1.5
    return amp * out * e


def hat(dur=0.045, amp=0.06):
    n = int(dur * SR)
    noise = np.random.default_rng(2).standard_normal(n)
    e = env_ad(n, 0.001, dur * 0.5, 0.0)
    b = np.convolve(noise, np.ones(6) / 6, mode="same")
    hp = noise - b
    return amp * hp * e


def riser(dur, amp=0.18):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(n)
    b = np.convolve(noise, np.ones(24) / 24, mode="same")
    hp = noise - b
    sweep = sine(220 + 700 * (t / dur) ** 1.5, n)
    e = (t / dur) ** 1.6
    return amp * e * (0.5 * hp + 0.5 * sweep)


def impact(dur=2.0, amp=0.4):
    n = int(dur * SR)
    e = env_ad(n, 0.004, dur * 0.8, 0.0)
    chord = pad_chord([note_hz("A3"), note_hz("E4"), note_hz("A4")], dur, amp=1.0, lfo_hz=0.0)[:n]
    sub = bass_hit(note_hz("A1"), dur, amp=0.6)[:n]
    return amp * e * (0.6 * chord + 0.6 * sub)


def mix_at(buf, sound, start_sec):
    i0 = int(start_sec * SR)
    i1 = i0 + len(sound)
    if i1 > len(buf):
        sound = sound[: len(buf) - i0]
        i1 = len(buf)
    if i1 <= i0:
        return
    buf[i0:i1] += sound


def main():
    n_total = int((TOTAL + 2.0) * SR)
    buf = np.zeros(n_total)
    beat = 60 / 100  # спокойнее, 100 BPM

    mix_at(buf, riser(INTRO_END - 0.2, amp=0.16), 0.0)
    mix_at(buf, impact(1.6, amp=0.32), INTRO_END - 0.15)

    prog = [
        ["A2", "C3", "E3"],
        ["F2", "A2", "C3"],
        ["C3", "E3", "G3"],
        ["G2", "B2", "D3"],
    ]
    bar = beat * 4
    tt = INTRO_END
    chord_i = 0
    while tt < OUTRO_START:
        chord = [note_hz(x) for x in prog[chord_i % len(prog)]]
        mix_at(buf, pad_chord(chord, bar + 0.4, amp=0.085, lfo_hz=0.15), tt)
        mix_at(buf, bass_hit(note_hz(prog[chord_i % len(prog)][0][:-1] + "1"), beat * 0.9, amp=0.24), tt)
        mix_at(buf, bass_hit(note_hz(prog[chord_i % len(prog)][0][:-1] + "1"), beat * 0.9, amp=0.16), tt + beat * 2)
        for k in range(4):
            f = chord[k % len(chord)] * 2
            mix_at(buf, pluck(f, beat, amp=0.07), tt + k * beat)
        if chord_i % 2 == 0:
            for k in range(4):
                mix_at(buf, hat(0.03, amp=0.045), tt + k * beat)
        chord_i += 1
        tt += bar

    mix_at(buf, impact(2.4, amp=0.36), OUTRO_START + 0.1)
    mix_at(buf, pad_chord([note_hz("A2"), note_hz("C3"), note_hz("E3"), note_hz("A3")],
                           TOTAL - OUTRO_START, amp=0.09, lfo_hz=0.08), OUTRO_START + 0.3)

    buf = np.tanh(buf * 1.1) * 0.9
    fade_n = int(1.4 * SR)
    if len(buf) > fade_n:
        fade = np.linspace(1, 0, fade_n)
        buf[-fade_n:] *= fade

    stereo = np.stack([buf, buf * 0.985], axis=1)
    stereo_i16 = np.clip(stereo * 32767, -32768, 32767).astype(np.int16)

    out_path = os.path.join(BASE, "audio", "tour_music_raw.wav")
    with wave.open(out_path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo_i16.tobytes())
    print("wrote", out_path, "duration", len(buf) / SR)


if __name__ == "__main__":
    main()
