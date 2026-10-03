from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from .about_dialog import AboutDialog
from .config import APP_DIR, AppConfig, Program, load_config, save_config
from .cover_art import cover_path_for
from .cover_fetch_worker import CoverFetchWorker
from .cover_widget import CoverWidget
from .import_dialog import ImportDialog
from .launcher import ExtractionError, cleanup_extracted, dosbox_command_for, launch_program
from .program_dialog import ProgramDialog
from .settings_dialog import SettingsDialog
from .star_rating_widget import rating_to_stars
from .starfield import StarfieldWidget, ship_icon
from .version import APP_VERSION, RELEASE_STAGE

_COVER_MARGIN = 36
_ICON_PATH = APP_DIR / "resources" / "icon.png"
# Highest-resolution app-logo variant (1024x1024), used as the cover-art
# placeholder while no game is selected yet.
_JOYSTICK_LOGO_PATH = APP_DIR / "resources" / "icon-macos-1024.png"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        version_label = f"{APP_VERSION} {RELEASE_STAGE}" if RELEASE_STAGE else APP_VERSION
        self.setWindowTitle(f"DOSBox Launcher {version_label}")

        self.config: AppConfig = load_config()
        self.resize(self.config.window_width, self.config.window_height)

        if _ICON_PATH.exists():
            # Setting it on the window itself (not just QApplication) gets
            # picked up more reliably by the window manager's title bar /
            # taskbar icon on some Linux desktops.
            self.setWindowIcon(QIcon(str(_ICON_PATH)))

        self._cover_workers: list[CoverFetchWorker] = []

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Suchen…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_search_filter)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self._start_selected)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)

        add_btn = QPushButton("Hinzufügen")
        edit_btn = QPushButton("Bearbeiten")
        # A trash-can glyph instead of a text caption, same "plain Unicode
        # character as button text" pattern already used for ▲/▼ below -
        # no icon asset/resource needed. Tooltip keeps it discoverable.
        delete_btn = QPushButton("🗑")
        start_btn = QPushButton("Starten")
        up_btn = QPushButton("▲")
        down_btn = QPushButton("▼")
        import_btn = QPushButton("Importieren…")
        settings_btn = QPushButton("Einstellungen…")
        info_btn = QPushButton("Info")
        # Ship + asteroid mini-game show/hide toggle - a checkable button
        # using the same ship sprite as an icon (see ship_icon()) rather
        # than a text caption. Off by default (self.starfield_widget wires
        # this up further below, once it exists - StarfieldWidget itself
        # also already defaults to hidden).
        self.toggle_game_btn = QPushButton()
        self.toggle_game_btn.setIcon(ship_icon(32))
        # Qt's own default icon size (16x16) shrank the ship sprite down to
        # an indistinct sliver - set explicitly so it actually reads as a
        # ship, matching how prominent the 🗑 delete glyph already is.
        self.toggle_game_btn.setIconSize(QSize(28, 28))
        self.toggle_game_btn.setCheckable(True)
        self.toggle_game_btn.setToolTip("Mini-Spiel (Raumschiff + Asteroiden) ein-/ausblenden")
        # Just the ship, no button chrome - a light highlight on
        # hover/checked is the only visual feedback kept, so it's still
        # discoverable as clickable/showing its current on-off state.
        self.toggle_game_btn.setFlat(True)
        self.toggle_game_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 30); border-radius: 4px; }"
            "QPushButton:checked { background: rgba(255, 255, 255, 50); border-radius: 4px; }"
        )

        delete_btn.setToolTip("Löschen")
        up_btn.setToolTip("Ausgewähltes Programm nach oben verschieben")
        down_btn.setToolTip("Ausgewähltes Programm nach unten verschieben")
        delete_btn.setFixedWidth(32)
        up_btn.setFixedWidth(32)
        down_btn.setFixedWidth(32)

        add_btn.clicked.connect(self._add_program)
        edit_btn.clicked.connect(self._edit_program)
        delete_btn.clicked.connect(self._delete_program)
        start_btn.clicked.connect(self._start_selected)
        up_btn.clicked.connect(lambda: self._move_selected(-1))
        down_btn.clicked.connect(lambda: self._move_selected(1))
        import_btn.clicked.connect(self._open_import)
        settings_btn.clicked.connect(self._open_settings)
        info_btn.clicked.connect(self._open_about)

        start_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; }"
            "QPushButton:hover { background-color: #388e3c; }"
            "QPushButton:pressed { background-color: #1b5e20; }"
        )
        delete_btn.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; }"
            "QPushButton:hover { background-color: #d32f2f; }"
            "QPushButton:pressed { background-color: #8e0000; }"
        )

        button_row = QHBoxLayout()
        for btn in (start_btn, edit_btn, delete_btn, up_btn, down_btn, self.toggle_game_btn):
            button_row.addWidget(btn)
        button_row.addStretch()
        button_row.addWidget(add_btn)
        button_row.addWidget(import_btn)
        button_row.addWidget(settings_btn)
        button_row.addWidget(info_btn)

        self.list_widget.setStyleSheet(
            "QListWidget {"
            "  background-color: rgba(20, 25, 60, 90);"
            "  color: #f0f0ff;"
            "  border: 1px solid rgba(255, 255, 255, 70);"
            "  border-radius: 6px;"
            "}"
            "QListWidget::item { padding: 4px; }"
            "QListWidget::item:selected { background-color: rgba(90, 110, 220, 170); }"
        )
        self.search_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: rgba(20, 25, 60, 90);"
            "  color: #f0f0ff;"
            "  border: 1px solid rgba(255, 255, 255, 70);"
            "  border-radius: 6px;"
            "  padding: 5px 8px;"
            "}"
        )

        button_bar = QWidget()
        button_bar.setLayout(button_row)

        foreground = QWidget()
        foreground.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        fg_layout = QVBoxLayout(foreground)
        fg_layout.addWidget(self.search_edit)
        fg_layout.addWidget(self.list_widget)
        fg_layout.addWidget(button_bar)

        self.starfield_widget = StarfieldWidget()

        container = QWidget()
        stack = QStackedLayout(container)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self.starfield_widget)
        stack.addWidget(foreground)
        stack.setCurrentWidget(foreground)
        self.setCentralWidget(container)

        self.cover_widget = CoverWidget(container)
        self.cover_widget.raise_()
        self._position_cover_widget(container.width(), container.height())
        self.starfield_widget.set_floor_margin(button_bar.sizeHint().height())
        self.toggle_game_btn.toggled.connect(self.starfield_widget.set_game_visible)

        self._refresh_list()
        # _refresh_list() doesn't itself trigger currentRowChanged when the
        # selection stays at -1 (e.g. nothing selected yet on a fresh
        # start), so the cover placeholder needs an explicit first kick.
        self._on_selection_changed(self.list_widget.currentRow())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "cover_widget"):
            self._position_cover_widget(self.centralWidget().width(), self.centralWidget().height())

    def _position_cover_widget(self, container_width: int, container_height: int) -> None:
        # Right-aligned, vertically centered (rather than pinned to the top
        # corner) so it sits more toward the middle-right of the window.
        x = container_width - self.cover_widget.width() - _COVER_MARGIN
        y = (container_height - self.cover_widget.height()) // 2
        self.cover_widget.set_home_position(x, y)

    def _refresh_list(self, select_index: int | None = None) -> None:
        if select_index is None:
            select_index = self.list_widget.currentRow()
        self.list_widget.clear()
        for program in self.config.programs:
            text = program.name
            if program.rating:
                text = f"{program.name}  {rating_to_stars(program.rating)}"
            item = QListWidgetItem(text)
            self.list_widget.addItem(item)
        if 0 <= select_index < self.list_widget.count():
            self.list_widget.setCurrentRow(select_index)
        self._apply_search_filter(self.search_edit.text())

    def _apply_search_filter(self, text: str) -> None:
        needle = text.strip().lower()
        first_visible = -1
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            match = needle in item.text().lower()
            item.setHidden(not match)
            if match and first_visible < 0:
                first_visible = row
        current = self.list_widget.currentRow()
        if needle and (current < 0 or self.list_widget.item(current).isHidden()):
            self.list_widget.setCurrentRow(first_visible)

    def _selected_index(self) -> int:
        return self.list_widget.currentRow()

    def _add_program(self) -> None:
        dialog = ProgramDialog(self.config, self)
        accepted = dialog.exec()
        self._remember_program_dialog_size(dialog)
        if accepted:
            program = dialog.result_program()
            if program:
                self.config.programs.insert(0, program)
                self._refresh_list(select_index=0)
                self._maybe_fetch_cover(program)
        save_config(self.config)
        self.list_widget.setFocus()

    def _edit_program(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        dialog = ProgramDialog(self.config, self, program=self.config.programs[index])
        accepted = dialog.exec()
        self._remember_program_dialog_size(dialog)
        if accepted:
            program = dialog.result_program()
            if program:
                self.config.programs[index] = program
                self._refresh_list(select_index=index)
                self._maybe_fetch_cover(program)
        save_config(self.config)
        self.list_widget.setFocus()

    def _remember_program_dialog_size(self, dialog: ProgramDialog) -> None:
        self.config.program_dialog_width = dialog.width()
        self.config.program_dialog_height = dialog.height()

    def _maybe_fetch_cover(self, program: Program) -> None:
        if cover_path_for(program.identity_path).is_file():
            return
        worker = CoverFetchWorker(program.name, program.identity_path, self)
        worker.finished_ok.connect(self._on_cover_fetched)
        self._cover_workers.append(worker)
        worker.start()

    def _on_cover_fetched(self, identity_path: str, cover_path: str) -> None:
        self._cover_workers = [w for w in self._cover_workers if w.isRunning()]
        index = self._selected_index()
        if 0 <= index < len(self.config.programs) and self.config.programs[index].identity_path == identity_path:
            self.cover_widget.set_cover(Path(cover_path) if cover_path else None)

    def _on_selection_changed(self, row: int) -> None:
        if not (0 <= row < len(self.config.programs)):
            self.cover_widget.show_placeholder(_JOYSTICK_LOGO_PATH)
            return
        path = cover_path_for(self.config.programs[row].identity_path)
        self.cover_widget.set_cover(path if path.is_file() else None)

    def _delete_program(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        program = self.config.programs[index]
        reply = QMessageBox.question(
            self,
            "Löschen bestätigen",
            f"„{program.name}“ löschen?\n\nSicher?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.config.programs[index]
            save_config(self.config)
            self._refresh_list(select_index=min(index, len(self.config.programs) - 1))
        self.list_widget.setFocus()

    def _move_selected(self, offset: int) -> None:
        index = self._selected_index()
        new_index = index + offset
        if index < 0 or not (0 <= new_index < len(self.config.programs)):
            return
        programs = self.config.programs
        programs[index], programs[new_index] = programs[new_index], programs[index]
        save_config(self.config)
        self._refresh_list()
        self.list_widget.setCurrentRow(new_index)

    def _start_selected(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        program = self.config.programs[index]
        try:
            launch_program(self.config, program)
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "DOSBox nicht gefunden",
                f"Der Befehl „{dosbox_command_for(self.config, program)}“ konnte nicht ausgeführt werden.\n"
                "Bitte in den Einstellungen den richtigen Befehl/Pfad angeben.",
            )
        except ExtractionError as e:
            QMessageBox.critical(
                self,
                "Entpacken fehlgeschlagen",
                f"Das Archiv konnte nicht entpackt werden:\n{e}",
            )

    def _open_import(self) -> None:
        dialog = ImportDialog(self.config, self)
        accepted = dialog.exec()
        self.config.import_dialog_width = dialog.width()
        self.config.import_dialog_height = dialog.height()
        if accepted:
            new_programs = dialog.new_programs()
            if new_programs:
                self.config.programs[0:0] = new_programs
                self._refresh_list(select_index=0)
                for program in new_programs:
                    self._maybe_fetch_cover(program)
                QMessageBox.information(
                    self, "Import abgeschlossen", f"{len(new_programs)} Spiel(e) importiert."
                )
        save_config(self.config)
        self.list_widget.setFocus()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self, config=self.config)
        accepted = dialog.exec()
        self.config.settings_dialog_width = dialog.width()
        self.config.settings_dialog_height = dialog.height()
        if accepted:
            self.config.dosbox_variant = dialog.dosbox_variant()
            self.config.dosbox_command_staging = dialog.dosbox_command_staging()
            self.config.dosbox_command_x = dialog.dosbox_command_x()
            self.config.cleanup_on_exit = dialog.cleanup_on_exit()
            self.config.games_root = dialog.games_root()
            self.config.global_autoexec = dialog.global_autoexec()
            self.config.cpu_cycles_mode = dialog.cpu_cycles_mode()
            self.config.cpu_cycles_fixed = dialog.cpu_cycles_fixed()
            self.config.gfx_aspect = dialog.gfx_aspect()
            self.config.gfx_output = dialog.gfx_output()
            self.config.gfx_integer_scaling = dialog.gfx_integer_scaling()
            self.config.midi_device = dialog.midi_device()
            self.config.sb_type = dialog.sb_type()
            self.config.opl_mode = dialog.opl_mode()
            self.config.sb_irq = dialog.sb_irq()
            self.config.sb_dma = dialog.sb_dma()
            self.config.sb_hdma = dialog.sb_hdma()
            self.config.memsize = dialog.memsize()
        save_config(self.config)
        self.list_widget.setFocus()

    def _open_about(self) -> None:
        AboutDialog(self).exec()
        self.list_widget.setFocus()

    def closeEvent(self, event) -> None:
        self.config.window_width = self.width()
        self.config.window_height = self.height()
        save_config(self.config)
        if self.config.cleanup_on_exit:
            cleanup_extracted(self.config, self.config.programs)
        # CoverFetchWorker is a real QThread (a background cover-art network
        # search/download) - if one is still running when the window
        # closes, nothing here was ever stopping it, so the underlying
        # process would keep running invisibly until that network call
        # finished on its own (or hung indefinitely) - this is very likely
        # why the app "sometimes doesn't fully quit" even after the window
        # closes. Cover art is best-effort/non-critical, so a hard
        # terminate() is fine here - we're shutting down, not trying to
        # preserve partial results.
        for worker in self._cover_workers:
            if worker.isRunning():
                worker.terminate()
                worker.wait(2000)
        super().closeEvent(event)
