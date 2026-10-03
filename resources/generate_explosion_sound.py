#!/usr/bin/env python3
"""Synthesizes explosion.wav (the starfield mini-game's asteroid-destroyed
sound effect) - a short low rumble + noise burst, built entirely with the
standard library (wave/struct/math/random, no numpy/audio deps), same
approach as generate_laser_sound.py. Re-run any time it should be
regenerated; the user can also just drop in their own resources/
explosion.wav to replace it - nothing else in the app cares how it was
made."""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = RESOURCES_DIR / "explosion.wav"

SAMPLE_RATE = 44100
DURATION_S = 0.35
RUMBLE_START_FREQ = 110.0
RUMBLE_END_FREQ = 45.0
AMPLITUDE = 0.55


def _envelope(t: float, duration: float) -> float:
    attack = min(1.0, t / 0.003)
    decay = math.exp(-3.2 * t / duration)
    return attack * decay


def main() -> None:
    num_samples = int(SAMPLE_RATE * DURATION_S)
    samples = []
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        progress = t / DURATION_S
        # Low rumble (pitch drooping slightly, like a real detonation's
        # low-end) plus a noise burst that's loudest at the very start and
        # fades faster than the rumble - gives it a "crack" up front and a
        # boom tail, rather than a flat buzz.
        freq = RUMBLE_START_FREQ * (RUMBLE_END_FREQ / RUMBLE_START_FREQ) ** progress
        rumble = math.sin(2 * math.pi * freq * t)
        noise = (random.uniform(-1.0, 1.0)) * math.exp(-8.0 * progress)
        value = 0.6 * rumble + 0.5 * noise
        value *= _envelope(t, DURATION_S) * AMPLITUDE
        samples.append(int(max(-1.0, min(1.0, value)) * 32767))

    with wave.open(str(OUTPUT_PATH), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    print(f"Geschrieben: {OUTPUT_PATH} ({num_samples} Samples, {DURATION_S * 1000:.0f}ms)")


if __name__ == "__main__":
    main()
