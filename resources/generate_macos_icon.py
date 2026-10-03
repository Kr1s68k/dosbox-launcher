"""Generates a macOS-style app icon (rounded-square "squircle" card with a
soft drop shadow) from the same joystick artwork, and writes out a properly
named .iconset folder ready for `iconutil -c icns` on a Mac."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RESOURCES_DIR = Path(__file__).parent
SRC = RESOURCES_DIR / "joystick_source.png"
ICONSET_DIR = RESOURCES_DIR / "AppIcon.iconset"

CANVAS = 1024
BG_COLOR = np.array([248, 248, 244])

# Proportions follow Apple's macOS Big Sur+ icon template: the squircle
# "card" fills about 80% of the full canvas, artwork sits further inset
# within that card.
CARD_FRAC = 0.82
CARD_RADIUS_FRAC = 0.225  # relative to the card size
ART_INSET_FRAC = 0.14  # relative to the card size

CARD_COLOR = (255, 255, 255, 255)
SHADOW_COLOR = (0, 0, 0, 70)

# (filename, pixel size) pairs macOS's iconutil expects inside a .iconset.
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def extract_artwork(img: Image.Image) -> Image.Image:
    arr = np.array(img.convert("RGB")).astype(np.int16)
    dist = np.sqrt(((arr - BG_COLOR) ** 2).sum(axis=2))
    alpha = np.clip((dist - 6) / 18 * 255, 0, 255).astype(np.uint8)
    rgba = np.dstack([arr.astype(np.uint8), alpha])
    cutout = Image.fromarray(rgba, "RGBA")
    bbox = cutout.split()[-1].getbbox()
    return cutout.crop(bbox)


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def render_master() -> Image.Image:
    artwork = extract_artwork(Image.open(SRC))

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    card_size = int(CANVAS * CARD_FRAC)
    card_radius = int(card_size * CARD_RADIUS_FRAC)
    card_pos = ((CANVAS - card_size) // 2, (CANVAS - card_size) // 2)

    # Soft drop shadow beneath the card.
    shadow_layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow_mask = rounded_mask(card_size, card_radius)
    shadow = Image.new("RGBA", (card_size, card_size), SHADOW_COLOR)
    shadow_layer.paste(shadow, (card_pos[0], card_pos[1] + int(CANVAS * 0.018)), shadow_mask)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(CANVAS * 0.02))
    canvas.alpha_composite(shadow_layer)

    # White squircle card.
    card = Image.new("RGBA", (card_size, card_size), CARD_COLOR)
    card_mask = rounded_mask(card_size, card_radius)
    canvas.paste(card, card_pos, card_mask)

    # Artwork, scaled to fit inside the card with inset padding, preserving
    # aspect ratio.
    art_area = int(card_size * (1 - ART_INSET_FRAC * 2))
    scale = min(art_area / artwork.width, art_area / artwork.height)
    art_w, art_h = int(artwork.width * scale), int(artwork.height * scale)
    artwork_resized = artwork.resize((art_w, art_h), Image.LANCZOS)
    art_pos = (
        card_pos[0] + (card_size - art_w) // 2,
        card_pos[1] + (card_size - art_h) // 2,
    )
    canvas.alpha_composite(artwork_resized, art_pos)

    return canvas


def main() -> None:
    master = render_master()
    ICONSET_DIR.mkdir(exist_ok=True)
    for filename, size in ICONSET_SIZES:
        resized = master.resize((size, size), Image.LANCZOS)
        resized.save(ICONSET_DIR / filename)
    master.save(RESOURCES_DIR / "icon-macos-1024.png")
    print(f"Wrote {len(ICONSET_SIZES)} files to {ICONSET_DIR}")
    print("On a Mac: iconutil -c icns AppIcon.iconset  (produces AppIcon.icns)")


if __name__ == "__main__":
    main()
