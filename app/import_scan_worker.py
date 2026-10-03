from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .import_scan import ArchiveCandidate, scan_archives


class ImportScanWorker(QThread):
    finished_ok = Signal(list)  # list[ArchiveCandidate]

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self._folder = folder

    def run(self) -> None:
        candidates: list[ArchiveCandidate] = scan_archives(self._folder)
        self.finished_ok.emit(candidates)
