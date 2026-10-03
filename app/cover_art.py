from __future__ import annotations

import hashlib
import io
import shutil
import urllib.request
from pathlib import Path

from .config import APP_DIR

COVERS_DIR = APP_DIR / "data" / "covers"
_LEGACY_COVERS_DIR = Path.home() / ".local" / "share" / "dosbox-launcher" / "covers"
COVER_SIZE = (250, 250)
_USER_AGENT = "Mozilla/5.0"


def _migrate_legacy_covers() -> None:
    if COVERS_DIR.exists() or not _LEGACY_COVERS_DIR.is_dir():
        return
    shutil.copytree(_LEGACY_COVERS_DIR, COVERS_DIR)


def cover_path_for(zip_path: str) -> Path:
    _migrate_legacy_covers()
    key = hashlib.sha1(zip_path.encode()).hexdigest()[:16]
    return COVERS_DIR / f"{key}.png"


def search_cover_candidates(name: str, max_results: int = 10) -> list[str]:
    """Search the web for cover art candidates. Returns image URLs, or an
    empty list if nothing was found (e.g. no internet connection)."""
    from ddgs import DDGS

    query = f"{name} Cover Spiel DOS"
    try:
        results = list(DDGS().images(query, max_results=max_results))
    except Exception:
        return []
    return [r["image"] for r in results if r.get("image")]


def download_cover_image(url: str):
    """Downloads one candidate and fits it to COVER_SIZE. Returns a PIL
    Image, or None if the download/decode failed."""
    from PIL import Image, ImageOps

    try:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        data = urllib.request.urlopen(request, timeout=10).read()
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    return ImageOps.fit(image, COVER_SIZE, Image.LANCZOS)


def load_local_cover_image(path: str):
    """Loads a local image file (e.g. dropped onto the cover preview via
    drag & drop) and fits it to COVER_SIZE, the same way a downloaded
    search-result candidate is prepared. Returns a PIL Image, or None if
    the file can't be read/decoded as an image."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return None
    return ImageOps.fit(image, COVER_SIZE, Image.LANCZOS)


def save_cover(image, zip_path: str) -> Path:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    dest = cover_path_for(zip_path)
    image.save(dest, "PNG")
    return dest


def fetch_cover(name: str, zip_path: str) -> Path | None:
    """Search + download the first usable candidate and save it. Used for
    the automatic background fetch after adding/editing a program."""
    for url in search_cover_candidates(name, max_results=5):
        image = download_cover_image(url)
        if image is not None:
            return save_cover(image, zip_path)
    return None
