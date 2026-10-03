from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)


class ConfEditorDialog(QDialog):
    """A minimal built-in text editor for a single .conf file. Used instead
    of QDesktopServices.openUrl (relies on a default-app file association
    for .conf being registered, which a fresh Linux desktop - notably
    SteamOS - often doesn't have, so "open" would silently do nothing)."""

    def __init__(
        self,
        path: Path,
        title: str,
        parent=None,
        warning_text: str | None = None,
        width: int = 640,
        height: int = 520,
        on_save: Callable[[str], None] | None = None,
        on_reset: Callable[[], str] | None = None,
    ):
        super().__init__(parent)
        self._path = path
        # Called with the saved text in addition to writing it to `path` -
        # lets the caller persist it elsewhere too (e.g. a Program's own
        # custom_conf field), without this generic dialog knowing about
        # AppConfig/Program at all.
        self._on_save = on_save
        # When given, shows an extra "Automatisch generieren" button that
        # refills the text box with this callback's return value (not
        # written anywhere until Save is pressed) - used to get back to the
        # auto-generated content after a custom_conf override was saved.
        self._on_reset = on_reset
        self.setWindowTitle(title)
        self.resize(width, height)

        layout = QVBoxLayout(self)

        if warning_text:
            warning_label = QLabel(warning_text)
            warning_label.setWordWrap(True)
            warning_label.setStyleSheet("color: #d9a441;")
            layout.addWidget(warning_label)

        self.path_label = QLabel(str(path))
        self.path_label.setStyleSheet("color: #888;")
        layout.addWidget(self.path_label)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setFont(QFont("monospace"))
        self.text_edit.setPlainText(path.read_text() if path.is_file() else "")
        layout.addWidget(self.text_edit)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._save)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self._on_close_clicked)
        if on_reset:
            reset_btn = buttons.addButton("Automatisch generieren", QDialogButtonBox.ButtonRole.ActionRole)
            reset_btn.clicked.connect(self._reset)
        layout.addWidget(buttons)

        self._saved_text = self.text_edit.toPlainText()

    def _save(self) -> None:
        text = self.text_edit.toPlainText()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(text)
        except OSError as e:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", f"Konnte nicht gespeichert werden:\n{e}")
            return
        if self._on_save:
            self._on_save(text)
        self._saved_text = text
        self.status_label.setText("Gespeichert.")

    def _reset(self) -> None:
        if not self._on_reset:
            return
        self.text_edit.setPlainText(self._on_reset())
        self.status_label.setText("Automatisch generierter Inhalt geladen (noch nicht gespeichert).")

    def _on_close_clicked(self) -> None:
        if self.text_edit.toPlainText() != self._saved_text:
            reply = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Änderungen. Ohne Speichern schließen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.accept()
