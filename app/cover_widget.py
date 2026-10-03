from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

_SIZE = 260
_DRIFT_MS = 50
_DRIFT_X = 8
_DRIFT_Y = 5


class CoverWidget(QLabel):
    """Floating cover-art box that gently drifts back and forth."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_SIZE, _SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)
        self.setStyleSheet(
            "QLabel {"
            "  background-color: rgba(10, 10, 30, 200);"
            "  border: 2px solid rgba(255, 255, 255, 90);"
            "  border-radius: 8px;"
            "}"
        )
        self.hide()

        self._base_x = 0
        self._base_y = 0
        self._t = 0.0

        self._drift_timer = QTimer(self)
        self._drift_timer.timeout.connect(self._drift)
        self._drift_timer.start(_DRIFT_MS)

    def set_home_position(self, x: int, y: int) -> None:
        self._base_x = x
        self._base_y = y
        # Apply immediately rather than waiting for the next drift tick, so
        # a resize doesn't leave the widget visibly lagging for up to
        # _DRIFT_MS behind its new home position.
        self._drift()

    def _drift(self) -> None:
        self._t += 0.02
        dx = math.sin(self._t) * _DRIFT_X
        dy = math.cos(self._t * 0.7) * _DRIFT_Y
        self.move(int(self._base_x + dx), int(self._base_y + dy))

    def set_cover(self, path: Path | None) -> None:
        if path and path.is_file():
            pixmap = QPixmap(str(path)).scaled(
                _SIZE - 8,
                _SIZE - 8,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(pixmap)
            self.show()
        else:
            self.clear()
            self.hide()

    def show_placeholder(self, path: Path) -> None:
        # Used specifically for "nothing selected yet" (not for "selected
        # but no cover found", which still just hides as before) - shows
        # the app's own logo instead of leaving an empty corner.
        if not path.is_file():
            self.hide()
            return
        pixmap = QPixmap(str(path)).scaled(
            _SIZE - 8,
            _SIZE - 8,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)
        self.show()
