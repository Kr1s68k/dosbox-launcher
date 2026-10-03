from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import (
    CPU_CYCLES_FIXED,
    CPU_CYCLES_MAX,
    CPU_CYCLES_MAX_VALUE,
    CPU_CYCLES_MIN,
    SB_DMAS,
    SB_HDMAS,
    SB_IRQS,
    VARIANT_STAGING,
)

_STAGING_ONLY_TOOLTIP = (
    "Nur für DOSBox Staging - DOSBox-X hat hierfür keinen entsprechenden\n"
    "Konfigurationsschlüssel (bestätigt aus dessen eigenem Quellcode)."
)

_GFX_OUTPUT_LABELS = {
    "opengl": "OpenGL (Standard)",
    "texture": "Texture (Fallback, falls OpenGL Probleme macht)",
    "texturenb": "Texture, ohne Bilinearfilter (scharf/pixelig)",
}

_INTEGER_SCALING_LABELS = {
    "auto": "Automatisch",
    "off": "Aus (weich skaliert)",
    "horizontal": "Nur horizontal",
    "vertical": "Nur vertikal",
}

_MIDI_DEVICE_LABELS = {
    "auto": "Automatisch",
    "none": "Kein MIDI",
    "soundcanvas": "Roland Sound Canvas",
    "fluidsynth": "FluidSynth (SoundFont)",
    "mt32": "Roland MT-32",
    "alsa": "ALSA (System-MIDI)",
}

_SB_TYPE_LABELS = {
    "none": "Keine Sound Blaster",
    "sb1": "Sound Blaster 1.0",
    "sb2": "Sound Blaster 2.0",
    "sbpro1": "Sound Blaster Pro",
    "sbpro2": "Sound Blaster Pro 2",
    "sb16": "Sound Blaster 16 (Standard)",
    "gb": "Game Blaster",
}

_OPL_MODE_LABELS = {
    "auto": "Automatisch (passend zum Sound-Blaster-Typ)",
    "opl2": "AdLib / OPL2 (mono)",
    "dualopl2": "Dual OPL2 (Stereo)",
    "opl3": "OPL3 (Stereo)",
    "opl3gold": "OPL3 Gold (mit Sound Blaster 16 für AdLib Gold 1000)",
    "esfm": "ESFM (erweitert, OPL3-kompatibel)",
    "none": "Kein FM-Sound",
}

_SLIDER_STEPS = 1000

# Rough era guidance from DOSBox Staging's own docs, shown live next to the
# cycles slider so a number alone doesn't have to mean anything to the user.
_CYCLES_HINTS = (
    (600, "früher 8088er-Titel (z. B. Alley Cat)"),
    (2500, "XT/286-Ära"),
    (8000, "386er-Titel"),
    (30000, "486er-Titel"),
    (70000, "486/frühe Pentium-Titel (z. B. Doom)"),
    (float("inf"), "spätere Pentium-Titel (z. B. Quake)"),
)


def _cycles_hint(cycles: int) -> str:
    for limit, text in _CYCLES_HINTS:
        if cycles <= limit:
            return text
    return _CYCLES_HINTS[-1][1]


def _cycles_to_slider(cycles: int) -> int:
    cycles = max(CPU_CYCLES_MIN, min(CPU_CYCLES_MAX_VALUE, cycles))
    log_min, log_max = math.log(CPU_CYCLES_MIN), math.log(CPU_CYCLES_MAX_VALUE)
    ratio = (math.log(cycles) - log_min) / (log_max - log_min)
    return round(ratio * _SLIDER_STEPS)


def _slider_to_cycles(position: int) -> int:
    log_min, log_max = math.log(CPU_CYCLES_MIN), math.log(CPU_CYCLES_MAX_VALUE)
    ratio = position / _SLIDER_STEPS
    return round(math.exp(log_min + ratio * (log_max - log_min)))


def _combo(labels: dict[str, str], current: str) -> QComboBox:
    combo = QComboBox()
    for value, label in labels.items():
        combo.addItem(label, userData=value)
    idx = combo.findData(current)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    return combo


def _int_combo(values: tuple[int, ...], current: int, default: int) -> QComboBox:
    combo = QComboBox()
    for value in values:
        label = f"{value}" + (" (Standard)" if value == default else "")
        combo.addItem(label, userData=value)
    idx = combo.findData(current)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    return combo


class DosboxConfigWidget(QWidget):
    """CPU/Cycles, Grafik and Sound/MIDI controls for the DOSBox-Staging
    config keys - shared between the global settings dialog and each
    program's own override panel, so the two never drift apart."""

    def __init__(
        self,
        parent=None,
        *,
        cpu_cycles_mode: str = CPU_CYCLES_MAX,
        cpu_cycles_fixed: int = 3000,
        gfx_aspect: bool = True,
        gfx_output: str = "opengl",
        gfx_integer_scaling: str = "auto",
        midi_device: str = "auto",
        sb_type: str = "sb16",
        opl_mode: str = "auto",
        sb_irq: int = 7,
        sb_dma: int = 1,
        sb_hdma: int = 5,
        memsize: int = 16,
    ):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_memory_group(memsize))
        layout.addWidget(self._build_cpu_group(cpu_cycles_mode, cpu_cycles_fixed))
        layout.addWidget(self._build_gfx_group(gfx_aspect, gfx_output, gfx_integer_scaling))
        layout.addWidget(
            self._build_sound_group(midi_device, sb_type, opl_mode, sb_irq, sb_dma, sb_hdma)
        )

    def _build_memory_group(self, memsize: int) -> QGroupBox:
        group = QGroupBox("Arbeitsspeicher")

        self.memsize_spin = QSpinBox()
        self.memsize_spin.setRange(1, 256)
        self.memsize_spin.setValue(memsize)
        self.memsize_spin.setSuffix(" MB")
        self.memsize_spin.setToolTip(
            "DOSBox-Standard ist 16 MB. Für Windows 95/OS2 sind 64-128 MB sinnvoll,\n"
            "reine DOS-Spiele brauchen meist nicht mehr als 16-32 MB."
        )

        form = QFormLayout()
        form.addRow("RAM:", self.memsize_spin)
        group.setLayout(form)
        return group

    def _build_cpu_group(self, cpu_cycles_mode: str, cpu_cycles_fixed: int) -> QGroupBox:
        group = QGroupBox("CPU / Cycles")

        self.cycles_mode_combo = QComboBox()
        self.cycles_mode_combo.addItem("Maximal (automatisch)", userData=CPU_CYCLES_MAX)
        self.cycles_mode_combo.addItem("Fest (Regler)", userData=CPU_CYCLES_FIXED)
        idx = self.cycles_mode_combo.findData(cpu_cycles_mode)
        self.cycles_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.cycles_slider = QSlider(Qt.Orientation.Horizontal)
        self.cycles_slider.setRange(0, _SLIDER_STEPS)
        self.cycles_slider.setValue(_cycles_to_slider(cpu_cycles_fixed))

        self.cycles_spin = QSpinBox()
        self.cycles_spin.setRange(CPU_CYCLES_MIN, 2_000_000)
        self.cycles_spin.setValue(cpu_cycles_fixed)
        self.cycles_spin.setSuffix(" Cycles")

        self.cycles_hint_label = QLabel()
        self.cycles_hint_label.setStyleSheet("color: #888;")

        self.cycles_slider.valueChanged.connect(self._on_cycles_slider_changed)
        self.cycles_spin.valueChanged.connect(self._on_cycles_spin_changed)
        self.cycles_mode_combo.currentIndexChanged.connect(self._update_cycles_enabled)

        cycles_row = QHBoxLayout()
        cycles_row.addWidget(self.cycles_slider)
        cycles_row.addWidget(self.cycles_spin)

        form = QFormLayout()
        form.addRow("Cycles-Modus:", self.cycles_mode_combo)
        form.addRow("Cycles:", cycles_row)
        form.addRow("", self.cycles_hint_label)
        group.setLayout(form)

        self._update_cycles_hint(cpu_cycles_fixed)
        self._update_cycles_enabled()
        return group

    def _on_cycles_slider_changed(self, position: int) -> None:
        cycles = _slider_to_cycles(position)
        self.cycles_spin.blockSignals(True)
        self.cycles_spin.setValue(cycles)
        self.cycles_spin.blockSignals(False)
        self._update_cycles_hint(cycles)

    def _on_cycles_spin_changed(self, cycles: int) -> None:
        self.cycles_slider.blockSignals(True)
        self.cycles_slider.setValue(_cycles_to_slider(cycles))
        self.cycles_slider.blockSignals(False)
        self._update_cycles_hint(cycles)

    def _update_cycles_hint(self, cycles: int) -> None:
        self.cycles_hint_label.setText(f"≈ {_cycles_hint(cycles)}")

    def _update_cycles_enabled(self) -> None:
        enabled = self.cycles_mode_combo.currentData() == CPU_CYCLES_FIXED
        self.cycles_slider.setEnabled(enabled)
        self.cycles_spin.setEnabled(enabled)

    def _build_gfx_group(self, gfx_aspect: bool, gfx_output: str, gfx_integer_scaling: str) -> QGroupBox:
        group = QGroupBox("Grafik")

        self.aspect_check = QCheckBox("Seitenverhältnis-Korrektur (4:3 statt quadratischer Pixel)")
        self.aspect_check.setChecked(gfx_aspect)

        self.output_combo = _combo(_GFX_OUTPUT_LABELS, gfx_output)
        self.integer_scaling_combo = _combo(_INTEGER_SCALING_LABELS, gfx_integer_scaling)

        form = QFormLayout()
        form.addRow("", self.aspect_check)
        form.addRow("Rendering-Backend:", self.output_combo)
        form.addRow("Integer-Scaling:", self.integer_scaling_combo)
        group.setLayout(form)
        return group

    def _build_sound_group(
        self, midi_device: str, sb_type: str, opl_mode: str, sb_irq: int, sb_dma: int, sb_hdma: int
    ) -> QGroupBox:
        group = QGroupBox("Sound / MIDI")

        self.midi_device_combo = _combo(_MIDI_DEVICE_LABELS, midi_device)
        self.sb_type_combo = _combo(_SB_TYPE_LABELS, sb_type)
        self.opl_mode_combo = _combo(_OPL_MODE_LABELS, opl_mode)
        self.opl_mode_combo.setToolTip(
            "Steuert die AdLib/FM-Emulation unabhängig vom Sound-Blaster-Typ.\n"
            "Für eine reine AdLib-Karte (ohne Sound Blaster): Sound-Blaster-Typ\n"
            "'Keine Sound Blaster' + hier 'AdLib / OPL2'."
        )
        self.sb_irq_combo = _int_combo(SB_IRQS, sb_irq, 7)
        self.sb_dma_combo = _int_combo(SB_DMAS, sb_dma, 1)
        self.sb_hdma_combo = _int_combo(SB_HDMAS, sb_hdma, 5)
        irq_dma_tooltip = (
            "Nur ändern, wenn ein bestimmtes Spiel eine andere IRQ/DMA erwartet -\n"
            "die Standardwerte passen für die meisten Spiele."
        )
        self.sb_irq_combo.setToolTip(irq_dma_tooltip)
        self.sb_dma_combo.setToolTip(irq_dma_tooltip)
        self.sb_hdma_combo.setToolTip(irq_dma_tooltip)

        form = QFormLayout()
        form.addRow("MIDI-Gerät:", self.midi_device_combo)
        form.addRow("Sound-Blaster-Typ:", self.sb_type_combo)
        form.addRow("AdLib/FM-Emulation:", self.opl_mode_combo)
        form.addRow("Sound-Blaster-IRQ:", self.sb_irq_combo)
        form.addRow("Sound-Blaster-DMA:", self.sb_dma_combo)
        form.addRow("Sound-Blaster-High-DMA (16-Bit):", self.sb_hdma_combo)
        group.setLayout(form)
        return group

    def set_variant(self, variant: str) -> None:
        """Grays out the two fields that only apply to DOSBox Staging
        (confirmed from DOSBox-X's own source that it has no equivalent
        conf key at all for these - not just a different name) whenever a
        different emulator is effectively selected, so the panel doesn't
        silently imply settings that won't actually take effect. Called
        both at dialog build time and live whenever the emulator dropdown
        (global or per-game) changes."""
        is_staging = variant == VARIANT_STAGING
        self.output_combo.setEnabled(is_staging)
        self.integer_scaling_combo.setEnabled(is_staging)
        tip = "" if is_staging else _STAGING_ONLY_TOOLTIP
        self.output_combo.setToolTip(tip)
        self.integer_scaling_combo.setToolTip(tip)

    # --- getters ---

    def cpu_cycles_mode(self) -> str:
        return self.cycles_mode_combo.currentData()

    def cpu_cycles_fixed(self) -> int:
        return self.cycles_spin.value()

    def gfx_aspect(self) -> bool:
        return self.aspect_check.isChecked()

    def gfx_output(self) -> str:
        return self.output_combo.currentData()

    def gfx_integer_scaling(self) -> str:
        return self.integer_scaling_combo.currentData()

    def midi_device(self) -> str:
        return self.midi_device_combo.currentData()

    def sb_type(self) -> str:
        return self.sb_type_combo.currentData()

    def opl_mode(self) -> str:
        return self.opl_mode_combo.currentData()

    def sb_irq(self) -> int:
        return self.sb_irq_combo.currentData()

    def sb_dma(self) -> int:
        return self.sb_dma_combo.currentData()

    def sb_hdma(self) -> int:
        return self.sb_hdma_combo.currentData()

    def memsize(self) -> int:
        return self.memsize_spin.value()
