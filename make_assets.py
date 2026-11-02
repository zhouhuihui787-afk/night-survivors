"""Run this on your computer:  python3 make_assets.py

It reads the original pictures in raw_art/ (never changes them) and writes
finished pictures into assets/ for main.py to load.

Two things happen:
1. every raw_art/*.png is made 3 times bigger with NEAREST scaling, so the
   pixels stay sharp and nothing is blurred;
2. two bright crystal gems are made from raw_art/gem.png: a blue one (worth 1 XP)
   and a pink one (worth 2 XP).

main.py never imports Pillow, so this script must be run before you play.
"""

import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw_art")
OUT = os.path.join(HERE, "assets")

SCALE = 3  # GAME.md: pictures are made 3x bigger

# Each gem is a colour ramp: dark edge -> middle body -> bright top -> white sparkle.
# A pixel of gem.png is placed on the ramp by how bright it is.
GEM_RAMPS = {
    "gem_blue.png": [
        (0.00, (20, 48, 116)),
        (0.45, (42, 118, 214)),
        (0.75, (104, 190, 252)),
        (0.92, (186, 234, 255)),
        (1.00, (255, 255, 255)),
    ],
    "gem_pink.png": [
        (0.00, (112, 18, 92)),
        (0.45, (214, 52, 158)),
        (0.75, (252, 122, 200)),
        (0.92, (255, 190, 234)),
        (1.00, (255, 255, 255)),
    ],
}


def enlarge(image):
    """3x bigger, keeping every pixel square (NEAREST = no blurring)."""
    wide, high = image.size
    return image.resize((wide * SCALE, high * SCALE), Image.NEAREST)


def ramp_colour(ramp, t):
    """The colour of a ramp at position t (0.0 = darkest, 1.0 = brightest)."""
    for i in range(1, len(ramp)):
        stop, colour = ramp[i]
        if t <= stop:
            start, previous = ramp[i - 1]
            span = stop - start
            mix = 0.0 if span <= 0 else (t - start) / span
            return tuple(int(round(a + (b - a) * mix)) for a, b in zip(previous, colour))
    return ramp[-1][1]


def recolour(image, ramp):
    """Keep the shape and the alpha, but paint every pixel from the ramp."""
    pixels = image.load()
    wide, high = image.size
    for y in range(high):
        for x in range(wide):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                continue
            light = (0.30 * red + 0.59 * green + 0.11 * blue) / 255.0
            pixels[x, y] = ramp_colour(ramp, light) + (alpha,)
    return image


def main():
    if not os.path.isdir(RAW):
        raise SystemExit("raw_art/ is missing - the original pictures are needed.")
    os.makedirs(OUT, exist_ok=True)

    made = []
    for name in sorted(os.listdir(RAW)):
        if not name.lower().endswith(".png"):
            continue
        with Image.open(os.path.join(RAW, name)) as source:
            picture = enlarge(source.convert("RGBA"))
        picture.save(os.path.join(OUT, name))
        made.append(name)

    # the two gems are coloured from the original, then enlarged like everything else
    for name, ramp in sorted(GEM_RAMPS.items()):
        with Image.open(os.path.join(RAW, "gem.png")) as source:
            gem = recolour(source.convert("RGBA").copy(), ramp)
        enlarge(gem).save(os.path.join(OUT, name))
        made.append(name)

    for name in made:
        with Image.open(os.path.join(OUT, name)) as check:
            print("%-14s %dx%d" % (name, check.size[0], check.size[1]))
    print("\n%d pictures written to %s" % (len(made), OUT))
    print("raw_art/ was only read, never changed.")


if __name__ == "__main__":
    main()
