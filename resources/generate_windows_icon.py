"""Generates resources/icon.ico (multi-resolution) from the existing square
icon-512.png artwork, for PyInstaller's --icon on Windows builds. Unlike
macOS, Windows has no special "squircle card" icon convention, so this just
re-encodes the same square artwork already used on Linux - no new artwork,
no platform-specific tool needed (Pillow writes .ico natively, works on any
OS, including this Linux dev machine)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

RESOURCES_DIR = Path(__file__).parent
SRC = RESOURCES_DIR / "icon-512.png"
DEST = RESOURCES_DIR / "icon.ico"

# Standard Windows icon sizes (Explorer, taskbar, Alt-Tab, shortcuts).
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    master = Image.open(SRC).convert("RGBA")
    master.save(DEST, format="ICO", sizes=ICO_SIZES)
    print(f"Wrote {DEST} ({', '.join(f'{w}x{h}' for w, h in ICO_SIZES)})")


if __name__ == "__main__":
    main()
