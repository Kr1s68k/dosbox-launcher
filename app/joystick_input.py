from __future__ import annotations

import sys
import threading

try:
    import evdev
    from evdev import ecodes
except ImportError:
    evdev = None
    ecodes = None


def _find_joystick():
    """Auto-detects the first input device that looks like a joystick/
    gamepad rather than hardcoding a specific USB adapter's device name -
    a Competition Pro-to-USB adapter's exact identity varies by chipset,
    so scanning capabilities is more robust than guessing one. Tries
    ABS_X/ABS_Y first (analog-style axes), then ABS_HAT0X/ABS_HAT0Y (hat-
    switch axes - common on cheap digital-joystick-to-USB adapters, which
    a plain Competition Pro is likely to use instead of true analog axes).
    Returns (device, x_code, y_code) or None."""
    if evdev is None:
        print("[joystick] evdev nicht installiert - keine Joystick-Steuerung.", file=sys.stderr)
        return None
    candidates = []
    permission_errors = []
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
        except PermissionError as e:
            # The most common real-world cause: the device node (usually
            # root:input, mode 660) isn't readable by this user - happens
            # silently otherwise, which is exactly what made this so hard
            # to diagnose without a report from real hardware.
            permission_errors.append((path, str(e)))
            continue
        except OSError:
            continue
        # device.capabilities()[EV_ABS] is a list of (code, AbsInfo) TUPLES,
        # not bare codes (unlike EV_KEY/EV_REL, which are just int lists) -
        # `{code for code in ...}` without unpacking silently built a set of
        # whole (code, AbsInfo) tuples instead of a set of codes, so
        # `ecodes.ABS_X in abs_codes` could never match anything even when
        # the device genuinely reported ABS_X - this was the actual root
        # cause of the joystick never working, confirmed via a real
        # Competition Pro reporting exactly ABS codes 0/1 (ABS_X/ABS_Y) in
        # its own capabilities list while this function still reported "kein
        # Joystick gefunden". Unpacking the tuple to keep just the code
        # fixes it.
        abs_codes = {code for code, _info in device.capabilities().get(ecodes.EV_ABS, [])}
        candidates.append((device.path, device.name, sorted(abs_codes)))
        if ecodes.ABS_X in abs_codes and ecodes.ABS_Y in abs_codes:
            print(f"[joystick] gefunden: {device.name} ({device.path}), Achsen ABS_X/ABS_Y", file=sys.stderr)
            return device, ecodes.ABS_X, ecodes.ABS_Y
        if ecodes.ABS_HAT0X in abs_codes and ecodes.ABS_HAT0Y in abs_codes:
            print(f"[joystick] gefunden: {device.name} ({device.path}), Achsen ABS_HAT0X/ABS_HAT0Y", file=sys.stderr)
            return device, ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y

    print("[joystick] kein Joystick mit ABS_X/Y oder ABS_HAT0X/Y gefunden.", file=sys.stderr)
    if permission_errors:
        print("[joystick] KEINE LESERECHTE für folgende Geräte (das ist sehr wahrscheinlich die Ursache):", file=sys.stderr)
        for path, error in permission_errors:
            print(f"  - {path}: {error}", file=sys.stderr)
        print(
            "[joystick] Fix: sudo usermod -aG input $USER, danach ab-/anmelden (oder neu starten).",
            file=sys.stderr,
        )
    if candidates:
        print("[joystick] gefundene (lesbare) Eingabegeräte, aber keins passte:", file=sys.stderr)
        for path, name, abs_codes in candidates:
            print(f"  - {name} ({path}), ABS-Codes: {abs_codes}", file=sys.stderr)
    if not permission_errors and not candidates:
        print("[joystick] gar keine Eingabegeräte über evdev sichtbar.", file=sys.stderr)
    return None


class JoystickReader:
    """Best-effort Linux joystick reading (via evdev) for the starfield
    spaceship. Not available at all (evdev not installed, or nothing
    detected) simply means the ship stays put - direction() always
    returns (0, 0) rather than raising, so this is safe to use
    unconditionally. Runs its own background thread; the UI polls
    direction() on its own timer instead of reacting to raw events, since
    only the latest state matters for continuous movement."""

    def __init__(self):
        self._dx = 0.0
        self._dy = 0.0
        self._fire = False
        self._lock = threading.Lock()
        found = _find_joystick()
        self._device = found[0] if found else None
        self._thread: threading.Thread | None = None
        if found is not None:
            device, x_code, y_code = found
            self._x_code = x_code
            self._y_code = y_code
            self._x_info = device.absinfo(x_code)
            self._y_info = device.absinfo(y_code)
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    @property
    def available(self) -> bool:
        return self._device is not None

    def direction(self) -> tuple[float, float]:
        """Current joystick deflection as (dx, dy), each in [-1, 1]."""
        with self._lock:
            return self._dx, self._dy

    def take_fire(self) -> bool:
        """True exactly once per button press - edge-triggered (reset as
        soon as read) so a single tap fires once, not continuously for as
        long as the button stays held. Any button on the device counts
        (EV_KEY, not a specific BTN_* code) - deliberately not hardcoded to
        one button number, since which physical button maps to which code
        varies by adapter and this app has no other use for buttons yet, so
        there's nothing a second button could conflict with."""
        with self._lock:
            fired = self._fire
            self._fire = False
            return fired

    def _run(self) -> None:
        try:
            for event in self._device.read_loop():
                if event.type == ecodes.EV_KEY and event.value == 1:
                    with self._lock:
                        self._fire = True
                    continue
                if event.type != ecodes.EV_ABS:
                    continue
                if event.code == self._x_code:
                    value = self._normalize(event.value, self._x_info)
                    with self._lock:
                        self._dx = value
                elif event.code == self._y_code:
                    value = self._normalize(event.value, self._y_info)
                    with self._lock:
                        self._dy = value
        except OSError:
            # Device unplugged mid-session - just stop updating; the ship
            # keeps whatever direction it last had frozen at 0 next tick
            # since read_loop() exiting means no more updates arrive.
            with self._lock:
                self._dx = 0.0
                self._dy = 0.0

    @staticmethod
    def _normalize(value: int, info) -> float:
        center = (info.max + info.min) / 2
        span = (info.max - info.min) / 2 or 1
        return max(-1.0, min(1.0, (value - center) / span))
