#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Процедурная генерация фоновой музыки для ролика stom.asia.
Без внешних сэмплов/сервисов — чистый синтез (numpy), укладывается в
таймлайн сцен (см. TIMELINE ниже, сек. от начала)."""
import numpy as np
import wave
import os

SR = 44100
BASE = os.path.dirname(os.path.abspath(__file__))

# ── Границы секций (сек) — подставляются после расчёта длительностей сцен ──
# A: напряжение (01-02), B: бренд-риз (03), C: groove (04-10),
# D: подъём (11), E: аутро (12)
T_A_END = 13.700
T_B_END = 18.033
T_C_END = 53.733
T_D_END = 58.733
TOTAL = 66.733


def note_hz(name):
    # простая таблица нот (A1..C5) через A4=440
    NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    n = name[:-1]
    octave = int(name[-1])
    semitone = NAMES[n]
    midi = (octave - 4) * 12 + semitone + 9  # относительно A4=69 semitone offset trick
    # проще: строим по формуле midi = 12*(octave+1) + semitone_from_C
    SEMI_FROM_C = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
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
    tone = 0.75 * sine(freq, n) + 0.25 * sine(freq * 2, n)
    # лёгкий питч-дроп для "веса"
    t = np.arange(n) / SR
    drop = 1 - 0.04 * np.clip(t / 0.05, 0, 1)
    tone = 0.75 * np.sin(2 * np.pi * freq * drop * t) + 0.25 * sine(freq * 2, n)
    return amp * tone * e


def pluck(freq, dur, amp=0.28):
    n = int(dur * SR)
    e = env_ad(n, 0.002, dur * 0.35, 0.0)
    tone = 0.6 * sine(freq, n) + 0.3 * sine(freq * 2, n) + 0.1 * sine(freq * 3, n)
    return amp * tone * e


def pad_chord(freqs, dur, amp=0.18, lfo_hz=0.15):
    n = int(dur * SR)
    t = np.arange(n) / SR
    e = env_ad(n, dur * 0.35, dur * 0.6, 0.85)
    lfo = 1 + 0.08 * np.sin(2 * np.pi * lfo_hz * t)
    out = np.zeros(n)
    for f in freqs:
        out += np.sin(2 * np.pi * f * t) * lfo
        out += 0.5 * np.sin(2 * np.pi * (f * 1.003) * t)  # лёгкая расстройка — "живее"
    out /= len(freqs) * 1.5
    return amp * out * e


def hat(dur=0.045, amp=0.10):
    n = int(dur * SR)
    noise = np.random.default_rng(0).standard_normal(n)
    e = env_ad(n, 0.001, dur * 0.5, 0.0)
    # грубый band-pass через разность двух экспоненциальных сглаживаний
    b = np.convolve(noise, np.ones(6) / 6, mode="same")
    hp = noise - b
    return amp * hp * e


def riser(dur, amp=0.22):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(1)
    noise = rng.standard_normal(n)
    b = np.convolve(noise, np.ones(24) / 24, mode="same")
    hp = noise - b
    sweep = sine(220 + 900 * (t / dur) ** 1.5, n)
    e = (t / dur) ** 1.6
    return amp * e * (0.5 * hp + 0.5 * sweep)


def impact(dur=1.4, amp=0.5):
    n = int(dur * SR)
    e = env_ad(n, 0.004, dur * 0.8, 0.0)
    chord = pad_chord([note_hz("A3"), note_hz("E4"), note_hz("A4")], dur, amp=1.0, lfo_hz=0.0)[:n]
    sub = bass_hit(note_hz("A1"), dur, amp=0.7)[:n]
    return amp * e * (0.6 * chord + 0.6 * sub)


def mix_at(buf, sound, start_sec):
    i0 = int(start_sec * SR)
    i1 = i0 + len(sound)
    if i1 > len(buf):
        sound = sound[: len(buf) - i0]
        i1 = len(buf)
    buf[i0:i1] += sound


def main():
    n_total = int((TOTAL + 2.0) * SR)
    buf = np.zeros(n_total)

    beat = 60 / 104  # 104 BPM

    # ── Section A: напряжение (0 .. T_A_END) — редкие низкие тычки + шум-тик
    t = 0.0
    root_a = note_hz("A1")
    while t < T_A_END:
        mix_at(buf, bass_hit(root_a, beat * 1.6, amp=0.30), t)
        if t + beat * 0.5 < T_A_END:
            mix_at(buf, hat(0.03, amp=0.05), t + beat * 1.0)
        t += beat * 2.0
    mix_at(buf, pad_chord([note_hz("A2"), note_hz("C3"), note_hz("E3")], T_A_END, amp=0.07, lfo_hz=0.1), 0.0)

    # ── Section B: бренд-риз + импакт (T_A_END .. T_B_END)
    riser_dur = min(2.6, T_B_END - T_A_END - 0.2)
    mix_at(buf, riser(riser_dur, amp=0.20), T_A_END)
    mix_at(buf, impact(1.6, amp=0.55), T_A_END + riser_dur + 0.05)

    # ── Section C: groove (T_B_END .. T_C_END) — прогрессия Am-F-C-G
    prog = [
        ["A2", "C3", "E3"],
        ["F2", "A2", "C3"],
        ["C3", "E3", "G3"],
        ["G2", "B2", "D3"],
    ]
    bar = beat * 4
    tt = T_B_END
    chord_i = 0
    while tt < T_C_END:
        chord = [note_hz(x) for x in prog[chord_i % len(prog)]]
        mix_at(buf, pad_chord(chord, bar + 0.4, amp=0.10, lfo_hz=0.2), tt)
        mix_at(buf, bass_hit(note_hz(prog[chord_i % len(prog)][0][:-1] + "1"), beat * 0.9, amp=0.34), tt)
        mix_at(buf, bass_hit(note_hz(prog[chord_i % len(prog)][0][:-1] + "1"), beat * 0.9, amp=0.22), tt + beat * 2)
        # аркпеджио 8-е доли
        for k in range(8):
            f = chord[k % len(chord)] * 2
            mix_at(buf, pluck(f, beat * 0.5, amp=0.10), tt + k * beat * 0.5)
        for k in range(4):
            mix_at(buf, hat(0.035, amp=0.06), tt + k * beat)
        chord_i += 1
        tt += bar

    # ── Section D: подъём (T_C_END .. T_D_END) — ярче, чаще хэты
    mix_at(buf, pad_chord([note_hz("F2"), note_hz("A2"), note_hz("C3"), note_hz("F3")],
                           T_D_END - T_C_END, amp=0.13, lfo_hz=0.25), T_C_END)
    tt = T_C_END
    while tt < T_D_END:
        mix_at(buf, hat(0.03, amp=0.06), tt)
        tt += beat / 2

    # ── Section E: аутро — резолв-аккорд + затухающий pad (T_D_END .. TOTAL)
    mix_at(buf, impact(2.2, amp=0.42), T_D_END + 0.1)
    mix_at(buf, pad_chord([note_hz("A2"), note_hz("C3"), note_hz("E3"), note_hz("A3")],
                           TOTAL - T_D_END, amp=0.10, lfo_hz=0.08), T_D_END + 0.3)

    # мягкий лимитер (tanh) + затухание в самом хвосте
    buf = np.tanh(buf * 1.15) * 0.9
    fade_n = int(1.2 * SR)
    if len(buf) > fade_n:
        fade = np.linspace(1, 0, fade_n)
        buf[-fade_n:] *= fade

    stereo = np.stack([buf, buf * 0.985], axis=1)  # лёгкая ширина
    stereo_i16 = np.clip(stereo * 32767, -32768, 32767).astype(np.int16)

    out_path = os.path.join(BASE, "audio", "music_raw.wav")
    with wave.open(out_path, "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo_i16.tobytes())
    print("wrote", out_path, "duration", len(buf) / SR)


if __name__ == "__main__":
    main()
