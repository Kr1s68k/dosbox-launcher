from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .cover_art import fetch_cover


class CoverFetchWorker(QThread):
    finished_ok = Signal(str, str)  # zip_path, cover_path ("" on failure)

    def __init__(self, name: str, zip_path: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._zip_path = zip_path

    def run(self) -> None:
        result = fetch_cover(self._name, self._zip_path)
        self.finished_ok.emit(self._zip_path, str(result) if result else "")
