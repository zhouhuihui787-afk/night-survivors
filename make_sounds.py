"""make_sounds.py — short sound effects for Night Survivors.

Run this on your computer:  python3 make_sounds.py
It writes .wav files into sounds/. Python's standard library only (wave, math,
array), so it needs nothing installed.

main.py never imports this file and never imports wave: it only plays the
finished files from sounds/.
"""

import array
import math
import os
import wave

RATE = 22050          # samples per second, plenty for a small effect
PEAK = 0.45           # how loud the loudest point is (0.0 - 1.0)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sounds")


def fade(i, total, attack=0.004, release=0.02):
    """A short fade in and out, so the sound does not click at its edges."""
    a = int(RATE * attack)
    r = int(RATE * release)
    if i < a:
        return i / float(a)
    if i > total - r:
        return max(0.0, (total - i) / float(r))
    return 1.0


def write(name, seconds, make):
    """Fill one effect with 'make' and save it as a 16-bit mono .wav file."""
    total = int(RATE * seconds)
    data = array.array("h")
    for i in range(total):
        value = make(i, total) * fade(i, total) * PEAK
        data.append(int(max(-1.0, min(1.0, value)) * 32767))
    path = os.path.join(OUT, name)
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(data.tobytes())
    print("  %-13s %4.2f s  %6d bytes" % (name, seconds, os.path.getsize(path)))


# ---------------------------------------------------------------- the effects


def hit(i, total):
    """A spark or blade landing: a bright tick with a fast decay."""
    t = i / float(RATE)
    tick = math.sin(2 * math.pi * (1400.0 - 900.0 * t * 16) * t)
    noise = math.sin(2 * math.pi * 97.3 * i)  # cheap pseudo-noise
    return (0.7 * tick + 0.3 * noise) * math.exp(-t * 55.0)


def gem(i, total):
    """A gem picked up: a rising blip that stops before the end."""
    t = i / float(RATE)
    body = math.sin(2 * math.pi * (700.0 + 2600.0 * t) * t)
    return body * math.exp(-t * 22.0)


def levelup(i, total):
    """Three rising notes: you are stronger now."""
    t = i / float(RATE)
    notes = (523.25, 659.25, 783.99)
    length = total / float(RATE) / len(notes)
    index = min(len(notes) - 1, int(t / length))
    note_t = t - index * length
    body = math.sin(2 * math.pi * notes[index] * note_t)
    shimmer = 0.25 * math.sin(2 * math.pi * notes[index] * 2 * note_t)
    return (body + shimmer) * math.exp(-note_t * 6.0)


def hurt(i, total):
    """The hero is hurt: a low buzz that bends down."""
    t = i / float(RATE)
    freq = 190.0 - 90.0 * t * 6.0
    saw = math.sin(2 * math.pi * freq * t) + 0.5 * math.sin(2 * math.pi * freq * 2 * t)
    return saw * math.exp(-t * 18.0)


def end(i, total):
    """The last two notes of a run: it falls away."""
    t = i / float(RATE)
    half = total / float(RATE) / 2.0
    second = t >= half
    freq = 261.63 if second else 392.0
    note_t = t - half if second else t
    body = math.sin(2 * math.pi * freq * note_t)
    fifth = 0.35 * math.sin(2 * math.pi * freq * 1.5 * note_t)
    return (body + fifth) * math.exp(-note_t * 4.0)


EFFECTS = [("hit.wav", 0.10, hit),
           ("gem.wav", 0.16, gem),
           ("levelup.wav", 0.42, levelup),
           ("hurt.wav", 0.20, hurt),
           ("end.wav", 0.70, end)]


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    print("sounds/")
    for name, seconds, make in EFFECTS:
        write(name, seconds, make)
    print("%d files written" % len(EFFECTS))


if __name__ == "__main__":
    main()
