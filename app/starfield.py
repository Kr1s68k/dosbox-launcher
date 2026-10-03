from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QPolygonF
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QWidget

from .config import APP_DIR
from .joystick_input import JoystickReader

# (star count, speed in px/tick, dot size in px, color) - farthest to nearest.
_LAYERS = [
    (50, 0.25, 1, QColor(110, 110, 150)),
    (35, 0.6, 2, QColor(170, 170, 210)),
    (20, 1.3, 3, QColor(255, 255, 255)),
]

_TICK_MS = 33

_SHIP_GIF_PATH = APP_DIR / "resources" / "Raumschiff.gif"
_SHIP_SIZE = 80
_SHIP_SPEED = 4.0  # px per tick at full joystick deflection
_SHIP_GAP = 10  # gap kept above the button row

_LASER_SOUND_PATH = APP_DIR / "resources" / "laser.wav"
_BEAM_WIDTH = 3
_BEAM_HEIGHT = 16
_BEAM_SPEED = 10.0  # px per tick, upward
_BEAM_COLOR = QColor(255, 60, 60)
# Minimum ticks between shots - halves the max possible fire rate versus
# "as fast as the button can physically be tapped/repeats" (no cooldown
# existed before; user asked for the rate to come down by 50%).
_FIRE_COOLDOWN_TICKS = 12

# Asteroid mini-game: always ~2 drifting right-to-left at once (same
# direction as the star layers, briefly 1 right after one explodes, until
# its replacement is spawned the very same tick) - takes 3 laser hits to
# destroy, each hit tinting it a bit redder as visual feedback before it
# actually explodes.
_ASTEROID_TARGET_COUNT = 2
# Faster than every star layer, including the nearest/fastest one
# (_LAYERS' own top speed is 1.3px/tick) - asteroids need to read as being
# IN FRONT of the starfield, not just another background layer.
_ASTEROID_SPEED = 2.0  # px per tick, leftward
_ASTEROID_RADIUS_RANGE = (18, 28)
_ASTEROID_HITS_TO_DESTROY = 3
_ASTEROID_BASE_COLOR = QColor(120, 100, 85)
_ASTEROID_HIT_COLOR = QColor(220, 70, 40)
_EXPLOSION_TICKS = 14  # ~0.5s at _TICK_MS
_EXPLOSION_COLOR = QColor(255, 170, 60)
_EXPLOSION_SOUND_PATH = APP_DIR / "resources" / "explosion.wav"


@dataclass
class _Asteroid:
    x: float
    y: float
    radius: float
    hits: int = 0
    # (dx, dy) offsets from center, fixed at spawn - gives each asteroid its
    # own irregular "rocky" silhouette instead of a plain circle.
    shape: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class _Explosion:
    x: float
    y: float
    radius: float
    age: int = 0


def _make_asteroid_shape(radius: float) -> list[tuple[float, float]]:
    num_points = random.randint(7, 10)
    points = []
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        point_radius = radius * random.uniform(0.65, 1.0)
        points.append((point_radius * math.cos(angle), point_radius * math.sin(angle)))
    return points

# Frames are near-black-background pixel art - chroma-keyed to transparent
# on load (rather than shipping a pre-cut version) so any future GIF swap
# keeps working without a separate editing step. Loaded lazily, once, and
# shared by every StarfieldWidget instance (there's only ever one, but no
# reason to redo the ~0.5s decode if that ever changes).
_ship_frames_cache: list[QPixmap] | None = None


def _load_ship_frames() -> list[QPixmap]:
    global _ship_frames_cache
    if _ship_frames_cache is not None:
        return _ship_frames_cache
    if not _SHIP_GIF_PATH.is_file():
        _ship_frames_cache = []
        return _ship_frames_cache

    from PIL import Image, ImageChops, ImageSequence

    frames = []
    with Image.open(_SHIP_GIF_PATH) as gif:
        for frame in ImageSequence.Iterator(gif):
            rgba = frame.convert("RGBA")
            r, g, b, _a = rgba.split()
            # Near-black (the GIF's own background) -> transparent, so the
            # ship composites cleanly over this widget's own starfield.
            max_channel = ImageChops.lighter(ImageChops.lighter(r, g), b)
            mask = max_channel.point(lambda v: 0 if v < 16 else 255)
            rgba.putalpha(mask)
            rgba = rgba.resize((_SHIP_SIZE, _SHIP_SIZE), Image.LANCZOS)
            data = rgba.tobytes("raw", "RGBA")
            qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
            frames.append(QPixmap.fromImage(qimage.copy()))
    _ship_frames_cache = frames
    return frames


def ship_icon(size: int = 24) -> QIcon:
    """The ship sprite's first frame, in its normal (standing) orientation,
    scaled down for use as a button icon - reuses the existing chroma-keyed
    GIF frames rather than needing a separate icon asset. Used for the main
    window's mini-game show/hide toggle button."""
    frames = _load_ship_frames()
    if not frames:
        return QIcon()
    pixmap = frames[0].scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    return QIcon(pixmap)


class StarfieldWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layers: list[list[list[float]]] = []
        self._seeded = False
        # Ship + asteroid mini-game visibility - off by default (the
        # starfield itself always keeps animating regardless; this only
        # gates the ship/beams/asteroids/explosions on top of it), toggled
        # via the main window's ship-icon button.
        self._game_visible = False

        self._ship_frames = _load_ship_frames()
        self._ship_frame_index = 0
        self._ship_x = 0.0
        self._ship_y = 0.0
        self._ship_y_min = 0.0  # top of the lower third - see _update_ship_y_bounds()
        self._ship_y_max = 0.0  # fixed hover height just above the button row
        self._ship_positioned = False
        self._floor_margin = 0  # set via set_floor_margin() - height of the button row
        self._joystick = JoystickReader()

        self._beams: list[list[float]] = []  # each [x, y], moving upward
        self._fire_cooldown = 0
        self._laser_sound = QSoundEffect(self)
        if _LASER_SOUND_PATH.is_file():
            self._laser_sound.setSource(QUrl.fromLocalFile(str(_LASER_SOUND_PATH)))
            self._laser_sound.setVolume(0.5)

        self._asteroids: list[_Asteroid] = []
        self._explosions: list[_Explosion] = []
        self._explosion_sound = QSoundEffect(self)
        if _EXPLOSION_SOUND_PATH.is_file():
            self._explosion_sound.setSource(QUrl.fromLocalFile(str(_EXPLOSION_SOUND_PATH)))
            self._explosion_sound.setVolume(0.6)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_TICK_MS)

    def set_game_visible(self, visible: bool) -> None:
        self._game_visible = visible
        self.update()

    def set_floor_margin(self, margin_px: int) -> None:
        # The ship's lowest allowed position (its default/starting height)
        # sits just above the button row - not the widget's own bottom
        # edge, which extends behind it.
        self._floor_margin = margin_px
        self._update_ship_y_bounds()

    def _update_ship_y_bounds(self) -> None:
        if self.height() <= 0:
            return
        self._ship_y_max = self.height() - _SHIP_SIZE - self._floor_margin - _SHIP_GAP
        # Free vertical movement is confined to the lower third of the
        # canvas - the ship's own top edge never goes above that line.
        self._ship_y_min = min(self._ship_y_max, self.height() * 2 / 3 - _SHIP_SIZE)
        if self._ship_positioned:
            self._ship_y = min(self._ship_y_max, max(self._ship_y_min, self._ship_y))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._seeded:
            self._seed_stars()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._seed_stars()
        self._update_ship_y_bounds()
        if not self._ship_positioned and self._ship_frames:
            self._ship_x = (self.width() - _SHIP_SIZE) / 2
            self._ship_y = self._ship_y_max
            self._ship_positioned = True

    def _seed_stars(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        self._layers = [
            [[random.uniform(0, self.width()), random.uniform(0, self.height())] for _ in range(count)]
            for count, *_ in _LAYERS
        ]
        self._seeded = True

    def _tick(self) -> None:
        if not self._seeded:
            return
        width = self.width()
        for stars, (_count, speed, *_rest) in zip(self._layers, _LAYERS):
            for star in stars:
                star[0] -= speed
                if star[0] < 0:
                    star[0] = width
                    star[1] = random.uniform(0, self.height())

        # Ship/beams/asteroids/explosions only tick while the mini-game is
        # actually visible (default off) - the starfield above keeps
        # animating regardless either way. Frozen exactly as-is while
        # hidden, so turning it back on resumes rather than resets.
        if self._game_visible and self._ship_frames:
            self._ship_frame_index = (self._ship_frame_index + 1) % len(self._ship_frames)
            dx, dy = self._joystick.direction()
            if dx:
                max_x = max(0, self.width() - _SHIP_SIZE)
                self._ship_x = min(max_x, max(0, self._ship_x + dx * _SHIP_SPEED))
            if dy:
                # Free vertical movement, but confined to the lower third
                # of the canvas (see _update_ship_y_bounds()) - the ship
                # never wanders up among the asteroids themselves.
                self._ship_y = min(self._ship_y_max, max(self._ship_y_min, self._ship_y + dy * _SHIP_SPEED))

            if self._fire_cooldown > 0:
                self._fire_cooldown -= 1
            elif self._ship_positioned and self._joystick.take_fire():
                beam_x = self._ship_x + _SHIP_SIZE / 2 - _BEAM_WIDTH / 2
                # Fired from the ship's own upper cockpit, not its center -
                # roughly a quarter of the way down the sprite.
                beam_y = self._ship_y + _SHIP_SIZE * 0.25
                self._beams.append([beam_x, beam_y])
                self._fire_cooldown = _FIRE_COOLDOWN_TICKS
                if self._laser_sound.source().isValid():
                    self._laser_sound.play()

            for beam in self._beams:
                beam[1] -= _BEAM_SPEED
            self._beams = [beam for beam in self._beams if beam[1] + _BEAM_HEIGHT > 0]

            # Asteroids: drift slowly right-to-left, same direction as the
            # star layers, pruned once fully off the left edge - a
            # replacement spawns the very same tick (see the "top up to
            # target count" loop below), so there's never more than one
            # tick's gap below the target of 2 at once.
            for asteroid in self._asteroids:
                asteroid.x -= _ASTEROID_SPEED
            self._asteroids = [a for a in self._asteroids if a.x + a.radius > 0]

            # Beam-vs-asteroid collisions - a beam is consumed on its
            # first hit (simple circle test against the asteroid's base
            # radius, not its exact rocky outline - plenty accurate for
            # this); an asteroid explodes (and is replaced) on its third.
            remaining_beams = []
            for beam in self._beams:
                beam_x, beam_y = beam[0] + _BEAM_WIDTH / 2, beam[1]
                hit_asteroid = None
                for asteroid in self._asteroids:
                    if math.hypot(beam_x - asteroid.x, beam_y - asteroid.y) <= asteroid.radius:
                        hit_asteroid = asteroid
                        break
                if hit_asteroid is None:
                    remaining_beams.append(beam)
                    continue
                hit_asteroid.hits += 1
                if hit_asteroid.hits >= _ASTEROID_HITS_TO_DESTROY:
                    self._explosions.append(
                        _Explosion(x=hit_asteroid.x, y=hit_asteroid.y, radius=hit_asteroid.radius)
                    )
                    self._asteroids.remove(hit_asteroid)
                    if self._explosion_sound.source().isValid():
                        self._explosion_sound.play()
            self._beams = remaining_beams

            while len(self._asteroids) < _ASTEROID_TARGET_COUNT:
                self._spawn_asteroid()

            for explosion in self._explosions:
                explosion.age += 1
            self._explosions = [e for e in self._explosions if e.age < _EXPLOSION_TICKS]

        self.update()

    def _spawn_asteroid(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        radius = random.uniform(*_ASTEROID_RADIUS_RANGE)
        y = random.uniform(radius, max(radius, self.height() - radius))
        self._asteroids.append(
            _Asteroid(x=self.width() + radius, y=y, radius=radius, shape=_make_asteroid_shape(radius))
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(6, 6, 22))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        for stars, (_count, _speed, size, color) in zip(self._layers, _LAYERS):
            painter.setBrush(color)
            for x, y in stars:
                painter.drawEllipse(int(x), int(y), size, size)

        if not self._game_visible:
            return

        if self._ship_frames and self._ship_positioned:
            painter.drawPixmap(int(self._ship_x), int(self._ship_y), self._ship_frames[self._ship_frame_index])

        painter.setBrush(_BEAM_COLOR)
        for x, y in self._beams:
            painter.drawRoundedRect(int(x), int(y), _BEAM_WIDTH, _BEAM_HEIGHT, 1, 1)

        for asteroid in self._asteroids:
            # Tints redder with each hit (0/3 = base color, 3/3 would be
            # the full hit color, though it explodes right at 3 so that
            # exact shade is never actually shown) - cheap visual feedback
            # that a hit registered, before the third one blows it up.
            hit_ratio = asteroid.hits / _ASTEROID_HITS_TO_DESTROY
            r = round(_ASTEROID_BASE_COLOR.red() + (_ASTEROID_HIT_COLOR.red() - _ASTEROID_BASE_COLOR.red()) * hit_ratio)
            g = round(
                _ASTEROID_BASE_COLOR.green() + (_ASTEROID_HIT_COLOR.green() - _ASTEROID_BASE_COLOR.green()) * hit_ratio
            )
            b = round(_ASTEROID_BASE_COLOR.blue() + (_ASTEROID_HIT_COLOR.blue() - _ASTEROID_BASE_COLOR.blue()) * hit_ratio)
            painter.setBrush(QColor(r, g, b))
            polygon = QPolygonF([QPointF(asteroid.x + dx, asteroid.y + dy) for dx, dy in asteroid.shape])
            painter.drawPolygon(polygon)

        for explosion in self._explosions:
            progress = explosion.age / _EXPLOSION_TICKS
            radius = explosion.radius * (1.0 + progress)
            color = QColor(_EXPLOSION_COLOR)
            color.setAlpha(round(255 * (1.0 - progress)))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(explosion.x, explosion.y), radius, radius)
