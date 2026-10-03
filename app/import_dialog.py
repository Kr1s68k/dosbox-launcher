from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from .config import AppConfig, Program
from .import_scan import ArchiveCandidate
from .import_scan_worker import ImportScanWorker

VARIANT_COPY = "copy"
VARIANT_LINK = "link"


class ImportDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Spiele importieren")
        self.setMinimumSize(560, 480)
        self.resize(config.import_dialog_width, config.import_dialog_height)

        self.source_edit = QLineEdit("")
        source_browse_btn = QPushButton("Durchsuchen…")
        source_browse_btn.clicked.connect(self._browse_source)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_edit)
        source_row.addWidget(source_browse_btn)

        self.games_root_edit = QLineEdit(config.games_root)
        games_root_browse_btn = QPushButton("Durchsuchen…")
        games_root_browse_btn.clicked.connect(self._browse_games_root)
        games_root_row = QHBoxLayout()
        games_root_row.addWidget(self.games_root_edit)
        games_root_row.addWidget(games_root_browse_btn)

        self.copy_radio = QRadioButton(
            "Dateien in den Spiele-Basisordner kopieren (Programmordner wird eigenständig)"
        )
        self.link_radio = QRadioButton(
            "Nur verknüpfen (Dateien bleiben, wo sie sind - relativer Pfad zum Spiele-Basisordner)"
        )
        self.copy_radio.setChecked(True)

        scan_btn = QPushButton("Ordner scannen")
        scan_btn.clicked.connect(self._scan)

        form = QFormLayout()
        form.addRow("Quellordner:", source_row)
        form.addRow("Spiele-Basisordner:", games_root_row)

        self.result_list = QListWidget()
        self.result_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.status_label = QLabel("Noch nicht gescannt.")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Importieren")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.copy_radio)
        layout.addWidget(self.link_radio)
        layout.addWidget(scan_btn)
        layout.addWidget(self.status_label)
        layout.addWidget(self.result_list)
        layout.addWidget(buttons)

        self._candidates: list[ArchiveCandidate] = []
        self._scan_worker: ImportScanWorker | None = None
        self._new_programs: list[Program] = []

    def _browse_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Quellordner wählen")
        if path:
            self.source_edit.setText(path)

    def _browse_games_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Spiele-Basisordner wählen")
        if path:
            self.games_root_edit.setText(path)

    def _scan(self) -> None:
        source = self.source_edit.text().strip()
        if not source or not Path(source).is_dir():
            QMessageBox.warning(self, "Ordner fehlt", "Bitte einen gültigen Quellordner wählen.")
            return
        if not self.games_root_edit.text().strip():
            QMessageBox.warning(
                self, "Basisordner fehlt", "Bitte einen Spiele-Basisordner angeben."
            )
            return

        self.result_list.clear()
        self.status_label.setText("Scanne…")
        self._scan_worker = ImportScanWorker(Path(source), self)
        self._scan_worker.finished_ok.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_finished(self, candidates: list[ArchiveCandidate]) -> None:
        self._candidates = candidates
        self.result_list.clear()
        if not candidates:
            self.status_label.setText("Keine ZIP-/RAR-Archive gefunden.")
            return

        for candidate in candidates:
            exe_hint = candidate.guessed_executable or "(kein Programm gefunden - nach dem Import bearbeiten)"
            item = QListWidgetItem(f"{candidate.guessed_name}  —  {exe_hint}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if candidate.guessed_executable else Qt.CheckState.Unchecked
            )
            item.setToolTip(str(candidate.path))
            self.result_list.addItem(item)

        self.status_label.setText(f"{len(candidates)} Archiv(e) gefunden.")

    def _on_accept(self) -> None:
        games_root = self.games_root_edit.text().strip()
        if not games_root:
            QMessageBox.warning(self, "Basisordner fehlt", "Bitte einen Spiele-Basisordner angeben.")
            return
        games_root_path = Path(games_root)

        variant = VARIANT_COPY if self.copy_radio.isChecked() else VARIANT_LINK

        selected = [
            (self._candidates[i], self.result_list.item(i))
            for i in range(self.result_list.count())
            if self.result_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            QMessageBox.warning(self, "Nichts ausgewählt", "Bitte mindestens ein Spiel auswählen.")
            return

        games_root_path.mkdir(parents=True, exist_ok=True)
        new_programs = []
        for candidate, _item in selected:
            if variant == VARIANT_COPY:
                dest = self._copy_into_games_root(candidate.path, games_root_path)
                stored_path = str(dest.relative_to(games_root_path))
            else:
                try:
                    stored_path = str(candidate.path.resolve().relative_to(games_root_path.resolve()))
                except ValueError:
                    stored_path = str(candidate.path)

            new_programs.append(
                Program(
                    name=candidate.guessed_name,
                    zip_path=stored_path,
                    executable=candidate.guessed_executable,
                )
            )

        self._new_programs = new_programs
        self.config.games_root = games_root
        self.accept()

    @staticmethod
    def _copy_into_games_root(source: Path, games_root: Path) -> Path:
        dest = games_root / source.name
        if dest.exists():
            if dest.resolve() == source.resolve():
                return dest
            stem, suffix = source.stem, source.suffix
            n = 2
            while dest.exists():
                dest = games_root / f"{stem} ({n}){suffix}"
                n += 1
        shutil.copy2(source, dest)
        return dest

    def new_programs(self) -> list[Program]:
        return self._new_programs
