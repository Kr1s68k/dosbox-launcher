from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import VARIANT_STAGING, VARIANT_X, AppConfig
from .dosbox_config_widget import DosboxConfigWidget

_VARIANT_LABELS = {
    VARIANT_STAGING: "DOSBox Staging",
    VARIANT_X: "DOSBox-X",
}


def _combo(labels: dict[str, str], current: str) -> QComboBox:
    combo = QComboBox()
    for value, label in labels.items():
        combo.addItem(label, userData=value)
    idx = combo.findData(current)
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    return combo


class SettingsDialog(QDialog):
    def __init__(self, parent=None, config: AppConfig | None = None):
        super().__init__(parent)
        config = config or AppConfig()
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        self.resize(config.settings_dialog_width, config.settings_dialog_height)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(config), "Allgemein")
        tabs.addTab(self._build_dosbox_config_tab(config), "DOSBox-Staging Config")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # --- Tab: Allgemein ---

    def _build_general_tab(self, config: AppConfig) -> QWidget:
        self.variant_combo = _combo(_VARIANT_LABELS, config.dosbox_variant)

        self.command_staging_edit = QLineEdit(config.dosbox_command_staging)
        self.command_x_edit = QLineEdit(config.dosbox_command_x)

        self.cleanup_check = QCheckBox("Entpackte Spiele beim Beenden löschen")
        self.cleanup_check.setChecked(config.cleanup_on_exit)

        self.games_root_edit = QLineEdit(config.games_root)
        self.games_root_edit.setPlaceholderText("optional, für relative Archiv-Pfade")
        games_root_browse_btn = QPushButton("Durchsuchen…")
        games_root_browse_btn.clicked.connect(self._browse_games_root)
        games_root_row = QHBoxLayout()
        games_root_row.addWidget(self.games_root_edit)
        games_root_row.addWidget(games_root_browse_btn)

        self.global_autoexec_edit = QPlainTextEdit(config.global_autoexec)
        self.global_autoexec_edit.setPlaceholderText("z. B.:\nkeyb gr")
        self.global_autoexec_edit.setFixedHeight(80)
        self.global_autoexec_edit.setToolTip(
            "Wird vor jedem Spielstart ausgeführt, direkt nach dem Mounten\n"
            "(z. B. Tastaturlayout/Codepage mit 'keyb gr' umstellen)."
        )

        form = QFormLayout()
        form.addRow("Zu startender Emulator:", self.variant_combo)
        form.addRow("Befehl (DOSBox Staging):", self.command_staging_edit)
        form.addRow("Befehl (DOSBox-X):", self.command_x_edit)
        form.addRow("", self.cleanup_check)
        form.addRow("Spiele-Basisordner:", games_root_row)
        form.addRow("Autoexec vor jedem Start:", self.global_autoexec_edit)

        tab = QWidget()
        tab.setLayout(form)
        return tab

    def _browse_games_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Spiele-Basisordner wählen")
        if path:
            self.games_root_edit.setText(path)

    # --- Tab: DOSBox-Staging Config ---

    def _build_dosbox_config_tab(self, config: AppConfig) -> QWidget:
        note = QLabel(
            "Wird für den oben gewählten Emulator passend erzeugt (eigene Konfigura-\n"
            "tionsschlüssel je nach Staging/DOSBox-X) und bei jedem Start neu ge-\n"
            "schrieben. Rendering-Backend und Integer-Scaling gelten nur für DOSBox\n"
            "Staging (DOSBox-X kennt diese Schlüssel nicht) - für DOSBox-X ausgegraut.\n"
            "Das ist die Grundeinstellung für alle Spiele - einzelne Spiele können sie\n"
            "im Programm-Dialog bei Bedarf noch überschreiben."
        )
        note.setStyleSheet("color: #888;")

        self.dosbox_config = DosboxConfigWidget(
            cpu_cycles_mode=config.cpu_cycles_mode,
            cpu_cycles_fixed=config.cpu_cycles_fixed,
            gfx_aspect=config.gfx_aspect,
            gfx_output=config.gfx_output,
            gfx_integer_scaling=config.gfx_integer_scaling,
            midi_device=config.midi_device,
            sb_type=config.sb_type,
            opl_mode=config.opl_mode,
            sb_irq=config.sb_irq,
            sb_dma=config.sb_dma,
            sb_hdma=config.sb_hdma,
            memsize=config.memsize,
        )
        self.dosbox_config.set_variant(config.dosbox_variant)
        self.variant_combo.currentIndexChanged.connect(
            lambda: self.dosbox_config.set_variant(self.variant_combo.currentData())
        )

        layout = QVBoxLayout()
        layout.addWidget(note)
        layout.addWidget(self.dosbox_config)
        layout.addStretch()

        tab = QWidget()
        tab.setLayout(layout)
        return tab

    # --- getters ---

    def dosbox_variant(self) -> str:
        return self.variant_combo.currentData()

    def dosbox_command_staging(self) -> str:
        return self.command_staging_edit.text().strip()

    def dosbox_command_x(self) -> str:
        return self.command_x_edit.text().strip()

    def cleanup_on_exit(self) -> bool:
        return self.cleanup_check.isChecked()

    def games_root(self) -> str:
        return self.games_root_edit.text().strip()

    def global_autoexec(self) -> str:
        return self.global_autoexec_edit.toPlainText().strip()

    def cpu_cycles_mode(self) -> str:
        return self.dosbox_config.cpu_cycles_mode()

    def cpu_cycles_fixed(self) -> int:
        return self.dosbox_config.cpu_cycles_fixed()

    def gfx_aspect(self) -> bool:
        return self.dosbox_config.gfx_aspect()

    def gfx_output(self) -> str:
        return self.dosbox_config.gfx_output()

    def gfx_integer_scaling(self) -> str:
        return self.dosbox_config.gfx_integer_scaling()

    def midi_device(self) -> str:
        return self.dosbox_config.midi_device()

    def sb_type(self) -> str:
        return self.dosbox_config.sb_type()

    def opl_mode(self) -> str:
        return self.dosbox_config.opl_mode()

    def sb_irq(self) -> int:
        return self.dosbox_config.sb_irq()

    def sb_dma(self) -> int:
        return self.dosbox_config.sb_dma()

    def sb_hdma(self) -> int:
        return self.dosbox_config.sb_hdma()

    def memsize(self) -> int:
        return self.dosbox_config.memsize()
