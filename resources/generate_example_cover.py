"""Generates the cover image for the one example program entry bundled with
every published build (example_data/programs.json) - a generic placeholder,
deliberately NOT real game box art (nothing copyrighted), so the filename
has to match cover_art.cover_path_for()'s hash of that entry's zip_path
exactly for the app to actually find/show it."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RESOURCES_DIR = Path(__file__).parent
ICON_SRC = RESOURCES_DIR / "icon-512.png"
EXAMPLE_ZIP_PATH = "beispiel/mein-spiel.zip"  # must match example_data/programs.json
COVER_SIZE = (250, 250)
BG_COLOR = (28, 33, 43)
BANNER_COLOR = (240, 168, 60)
BANNER_TEXT_COLOR = (20, 20, 20)


def main() -> None:
    cover = Image.new("RGB", COVER_SIZE, BG_COLOR)
    icon = Image.open(ICON_SRC).convert("RGBA")
    icon = icon.resize((170, 170), Image.LANCZOS)
    cover.paste(icon, ((COVER_SIZE[0] - 170) // 2, 24), icon)

    draw = ImageDraw.Draw(cover)
    banner_y0 = 204
    draw.rectangle((0, banner_y0, COVER_SIZE[0], COVER_SIZE[1]), fill=BANNER_COLOR)
    font = ImageFont.load_default(size=22)
    text = "BEISPIEL"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    draw.text(
        ((COVER_SIZE[0] - text_w) // 2, banner_y0 + 9),
        text,
        fill=BANNER_TEXT_COLOR,
        font=font,
    )

    key = hashlib.sha1(EXAMPLE_ZIP_PATH.encode()).hexdigest()[:16]
    dest_dir = RESOURCES_DIR.parent / "example_data" / "covers"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{key}.png"
    cover.save(dest, "PNG")
    print(f"Wrote {dest}")


if __name__ == "__main__":
    main()
