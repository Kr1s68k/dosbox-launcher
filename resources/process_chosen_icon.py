"""Takes the chosen AI-generated Miro-style joystick illustration
(miro_recraft_1.png), crops it square around the artwork keeping its white
background, rounds the corners, and writes out the full icon size set."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RESOURCES_DIR = Path(__file__).parent
SRC = RESOURCES_DIR / "joystick_source.png"
PADDING_FRAC = 0.14
CORNER_RADIUS_FRAC = 0.18


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def main() -> None:
    img = Image.open(SRC).convert("RGB")

    # Find the artwork's bounding box against the flat cream background,
    # just to know where to crop - the background itself is kept.
    import numpy as np

    arr = np.array(img).astype(np.int16)
    bg = np.array([248, 248, 244])
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    content_mask = Image.fromarray((dist > 10).astype("uint8") * 255)
    bbox = content_mask.getbbox()
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    side = max(w, h) * (1 + PADDING_FRAC * 2)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    crop_box = (int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))

    square = Image.new("RGB", (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]), (255, 255, 255))
    src_crop_box = (
        max(crop_box[0], 0),
        max(crop_box[1], 0),
        min(crop_box[2], img.width),
        min(crop_box[3], img.height),
    )
    paste_pos = (src_crop_box[0] - crop_box[0], src_crop_box[1] - crop_box[1])
    square.paste(img.crop(src_crop_box), paste_pos)

    for size in (16, 32, 48, 64, 128, 256, 512):
        resized = square.resize((size, size), Image.LANCZOS).convert("RGBA")
        mask = rounded_mask(size, int(size * CORNER_RADIUS_FRAC))
        resized.putalpha(mask)
        resized.save(RESOURCES_DIR / f"icon-{size}.png")
    (RESOURCES_DIR / "icon.png").write_bytes((RESOURCES_DIR / "icon-256.png").read_bytes())
    print("Icons written to", RESOURCES_DIR, "master square size:", square.size)


if __name__ == "__main__":
    main()
