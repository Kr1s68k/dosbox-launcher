from __future__ import annotations

import importlib.metadata
import platform
import socket

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

from .config import APP_DIR
from .version import APP_VERSION, AUTHOR, BUILD_DATE, BUILD_NUMBER, RELEASE_STAGE

_AMIGA_ICON_PATH = APP_DIR / "resources" / "System_Amiga.png"


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unbekannt"


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Über DOSBox Launcher")
        self.setMinimumWidth(380)

        version_label = f"{APP_VERSION} {RELEASE_STAGE}" if RELEASE_STAGE else APP_VERSION
        text = (
            f"<h3>DOSBox Launcher</h3>"
            f"<p>Version {version_label} (Build {BUILD_NUMBER})<br>"
            f"Erstellt am: {BUILD_DATE}<br>"
            f"Autor: {AUTHOR}</p>"
            f"<p>Rechner: {socket.gethostname()}<br>"
            f"Python: {platform.python_version()}</p>"
            f"<p>Verwendete Pakete:<br>"
            f"PySide6 {_package_version('PySide6')}<br>"
            f"PyInstaller {_package_version('pyinstaller')} (Build-Werkzeug)</p>"
        )

        label = QLabel(text)

        content_row = QHBoxLayout()
        content_row.addWidget(label)
        content_row.addStretch()
        if _AMIGA_ICON_PATH.is_file():
            amiga_pixmap = QPixmap(str(_AMIGA_ICON_PATH))
            amiga_label = QLabel()
            amiga_label.setPixmap(
                amiga_pixmap.scaled(
                    amiga_pixmap.width() // 2,
                    amiga_pixmap.height() // 2,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            amiga_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            content_row.addWidget(amiga_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(content_row)
        layout.addWidget(buttons)
