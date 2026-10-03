#!/usr/bin/env python3
"""Synthesizes laser.wav (the starfield spaceship's fire sound effect) -
a classic descending-frequency "pew", built entirely with the standard
library (wave/struct/math, no numpy/audio deps) so it needs nothing beyond
what's already installed. Re-run this any time the sound should be
regenerated; the user can also just drop in their own resources/laser.wav
to replace it - nothing else in the app cares how that file was made."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = RESOURCES_DIR / "laser.wav"

SAMPLE_RATE = 44100
DURATION_S = 0.18
START_FREQ = 1400.0
END_FREQ = 220.0
AMPLITUDE = 0.5  # of full 16-bit range, headroom to avoid clipping


def _envelope(t: float, duration: float) -> float:
    # Fast attack, exponential-ish decay - avoids a click at the start and
    # tapers naturally into silence rather than cutting off abruptly.
    attack = min(1.0, t / 0.005)
    decay = math.exp(-4.0 * t / duration)
    return attack * decay


def main() -> None:
    num_samples = int(SAMPLE_RATE * DURATION_S)
    samples = []
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        progress = t / DURATION_S
        # Exponential frequency sweep (high -> low) reads as a "laser" more
        # than a linear sweep - matches the classic arcade-shooter timbre.
        freq = START_FREQ * (END_FREQ / START_FREQ) ** progress
        # A touch of second-harmonic distortion gives it more bite than a
        # pure sine, without needing a noise/sawtooth generator.
        value = math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(4 * math.pi * freq * t)
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
