from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

_STAR_COUNT = 5
_MAX_RATING = _STAR_COUNT * 2  # half-star steps: 0..10
_STAR_SIZE = 22
_STAR_SPACING = 3
_FILLED_COLOR = QColor(255, 190, 0)
_OUTLINE_COLOR = QColor(150, 150, 150)


def _star_polygon(cx: float, cy: float, outer_r: float, inner_r: float) -> QPolygonF:
    points = []
    for i in range(_STAR_COUNT * 2):
        angle = math.pi / 2 + i * math.pi / _STAR_COUNT
        r = outer_r if i % 2 == 0 else inner_r
        points.append(QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle)))
    return QPolygonF(points)


def rating_to_stars(rating: int) -> str:
    """Plain-text rendering of a 0-10 half-star rating (e.g. for the game
    list, which is a plain QListWidget - no per-row custom painting)."""
    rating = max(0, min(_MAX_RATING, rating))
    full = rating // 2
    half = rating % 2 == 1
    empty = _STAR_COUNT - full - (1 if half else 0)
    return "★" * full + ("⯨" if half else "") + "☆" * empty


class StarRatingWidget(QWidget):
    """5-star rating control in half-star steps (0-10). Right-click ANYWHERE
    on the star row adds half a star, left-click removes half a star -
    deliberately not "click star N to jump straight to N" (a more usual
    star-widget pattern), per explicit request: every click just nudges the
    current rating by one half-step, regardless of which star it lands on."""

    ratingChanged = Signal(int)

    def __init__(self, rating: int = 0, parent=None):
        super().__init__(parent)
        self._rating = max(0, min(_MAX_RATING, rating))
        self.setFixedSize(_STAR_COUNT * (_STAR_SIZE + _STAR_SPACING) - _STAR_SPACING, _STAR_SIZE)
        self.setToolTip(
            "Rechtsklick: halben Stern hinzufügen\nLinksklick: halben Stern entfernen"
        )

    def rating(self) -> int:
        return self._rating

    def setRating(self, value: int) -> None:
        value = max(0, min(_MAX_RATING, value))
        if value != self._rating:
            self._rating = value
            self.update()
            self.ratingChanged.emit(self._rating)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.setRating(self._rating + 1)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.setRating(self._rating - 1)
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer_r = _STAR_SIZE / 2
        inner_r = outer_r * 0.4
        for i in range(_STAR_COUNT):
            x = i * (_STAR_SIZE + _STAR_SPACING)
            cx = x + _STAR_SIZE / 2
            cy = _STAR_SIZE / 2
            star = _star_polygon(cx, cy, outer_r, inner_r)
            # Value for this specific star: 2 = full, 1 = half, 0 = empty.
            star_value = max(0, min(2, self._rating - i * 2))

            painter.setPen(QPen(_OUTLINE_COLOR, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(star)

            if star_value <= 0:
                continue
            painter.save()
            if star_value == 1:
                painter.setClipRect(QRectF(x, 0, _STAR_SIZE / 2, _STAR_SIZE))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_FILLED_COLOR)
            painter.drawPolygon(star)
            painter.restore()
