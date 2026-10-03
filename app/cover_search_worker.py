from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .cover_art import download_cover_image, search_cover_candidates


class CoverSearchWorker(QThread):
    finished_ok = Signal(list)  # list[str] of image URLs

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name

    def run(self) -> None:
        self.finished_ok.emit(search_cover_candidates(self._name))


class CoverImageDownloadWorker(QThread):
    finished_ok = Signal(int, object)  # candidate index, PIL.Image or None

    def __init__(self, index: int, url: str, parent=None):
        super().__init__(parent)
        self._index = index
        self._url = url

    def run(self) -> None:
        self.finished_ok.emit(self._index, download_cover_image(self._url))
