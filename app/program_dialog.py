from __future__ import annotations

import dataclasses
import shutil
import subprocess
import zipfile
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .conf_editor_dialog import ConfEditorDialog
from .config import (
    BOOT_DRIVE_C,
    BOOT_DRIVE_D,
    BOOT_DRIVE_E,
    DISPLAY_FULLSCREEN,
    DISPLAY_FULLSCREEN_WINDOWED,
    DISPLAY_WINDOW,
    INSTALL_MODE_GAME,
    INSTALL_MODE_WINDOWS,
    VARIANT_STAGING,
    VARIANT_X,
    AppConfig,
    Program,
    save_config,
)
from .cover_art import cover_path_for, load_local_cover_image, save_cover
from .cover_search_worker import CoverImageDownloadWorker, CoverSearchWorker
from .dosbox_config_widget import DosboxConfigWidget
from .star_rating_widget import StarRatingWidget
from .launcher import (
    FLOPPY_SIZE_720,
    FLOPPY_SIZE_1440,
    ExtractionError,
    FloppyCreationError,
    build_autoexec_conf,
    create_floppy_image,
    dosbox_command_for,
    dosbox_primary_conf_path,
    generate_autoexec_conf,
    image_geometry,
    program_dir_for,
)

RUNNABLE_SUFFIXES = (".exe", ".com", ".bat")
_PREVIEW_SIZE = 200

# "" = inherit the app-wide default variant (Einstellungen > Allgemein) -
# lets one game override just for itself (e.g. DOSBox-X handles a specific
# Windows 95 install better than Staging, without switching every other
# game over too).
_VARIANT_OVERRIDE_LABELS = {
    "": "Automatisch (globale Einstellung)",
    VARIANT_STAGING: "DOSBox Staging",
    VARIANT_X: "DOSBox-X",
}


def find_runnables(archive_path: str) -> list[str]:
    if archive_path.lower().endswith(".rar"):
        return _find_runnables_in_rar(archive_path)
    try:
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return []
    return [n for n in names if n.lower().endswith(RUNNABLE_SUFFIXES) and not n.endswith("/")]


def _find_runnables_in_rar(archive_path: str) -> list[str]:
    # Only unrar's "bare list" output is parsed here (one filename per line,
    # trivial to read); if it's not installed we simply don't offer a
    # preview list and the user types the executable name in by hand.
    if shutil.which("unrar") is None:
        return []
    try:
        result = subprocess.run(
            ["unrar", "lb", "-r", archive_path], capture_output=True, text=True, timeout=20
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.lower().endswith(RUNNABLE_SUFFIXES)]


def find_runnables_in_dir(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(
        str(p.relative_to(directory))
        for p in directory.rglob("*")
        if p.suffix.lower() in RUNNABLE_SUFFIXES
    )


def pil_to_pixmap(image) -> QPixmap:
    data = image.tobytes("raw", "RGB")
    qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


class _DropCoverLabel(QLabel):
    """The cover preview QLabel, extended to accept a local image file
    dropped onto it (drag & drop from the file manager) as a custom cover -
    an alternative to the automatic web search."""

    imageDropped = Signal(str)

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setAcceptDrops(True)

    def _dropped_image_path(self, mime_data) -> str | None:
        for url in mime_data.urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in _IMAGE_SUFFIXES:
                return url.toLocalFile()
        return None

    def dragEnterEvent(self, event) -> None:
        if self._dropped_image_path(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        path = self._dropped_image_path(event.mimeData())
        if path is not None:
            self.imageDropped.emit(path)
            event.acceptProposedAction()


class ProgramDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None, program: Program | None = None):
        super().__init__(parent)
        self.config = config
        self.program = program
        self.setWindowTitle("Programm bearbeiten" if program else "Programm hinzufügen")
        self.setMinimumWidth(480)
        self.resize(config.program_dialog_width, config.program_dialog_height)

        self.name_edit = QLineEdit(program.name if program else "")

        self.rating_widget = StarRatingWidget(program.rating if program else 0)
        rating_row = QHBoxLayout()
        rating_row.addWidget(self.rating_widget)
        rating_row.addStretch()

        self.website_label_edit = QLineEdit((program.website_label or "") if program else "")
        self.website_label_edit.setPlaceholderText("Bezeichnung, z. B. Codewheel")
        self.website_label_edit.setFixedWidth(120)

        self.website_edit = QLineEdit((program.website_url or "") if program else "")
        self.website_edit.setPlaceholderText("z. B. https://www.mobygames.com/game/...")

        self.website_open_btn = QPushButton("🔗")
        self.website_open_btn.setToolTip("Link im Browser öffnen")
        self.website_open_btn.setFixedWidth(32)
        self.website_open_btn.clicked.connect(self._open_website)
        self.website_open_btn.setEnabled(bool(self.website_edit.text().strip()))
        self.website_edit.textChanged.connect(
            lambda text: self.website_open_btn.setEnabled(bool(text.strip()))
        )

        website_row = QHBoxLayout()
        website_row.addWidget(self.website_label_edit)
        website_row.addWidget(self.website_edit)
        website_row.addWidget(self.website_open_btn)

        self.notes_edit = QPlainTextEdit((program.notes or "") if program else "")
        self.notes_edit.setPlaceholderText("Notizen zu diesem Spiel (z. B. Installationshinweise, Tricks, Bugs)")
        self.notes_edit.setFixedHeight(80)

        # --- Installationstyp: "Spiel" (Archiv, wie bisher) vs. "Windows /
        # OS2" (echte Ordner statt Archiv, für eine Windows/OS2-Installation
        # von einem Setup-Ordner auf ein leeres "virtuelles Laufwerk" C:). ---
        self.mode_game_radio = QRadioButton("Spiel (ZIP/RAR-Archiv)")
        self.mode_windows_radio = QRadioButton("Windows / OS2 (Ordner)")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.mode_game_radio)
        mode_group.addButton(self.mode_windows_radio)
        current_install_mode = program.install_mode if program else INSTALL_MODE_GAME
        if current_install_mode == INSTALL_MODE_WINDOWS:
            self.mode_windows_radio.setChecked(True)
        else:
            self.mode_game_radio.setChecked(True)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.mode_game_radio)
        mode_row.addWidget(self.mode_windows_radio)
        mode_row.addStretch()

        self.zip_edit = QLineEdit(program.zip_path if program else "")
        browse_btn = QPushButton("Durchsuchen…")
        browse_btn.clicked.connect(self._browse_zip)
        zip_row = QHBoxLayout()
        zip_row.addWidget(self.zip_edit)
        zip_row.addWidget(browse_btn)

        self.update_zip_edit = QLineEdit((program.update_zip_path or "") if program else "")
        self.update_zip_edit.setPlaceholderText("optional, z. B. Update/Patch-Archiv")
        update_browse_btn = QPushButton("Durchsuchen…")
        update_browse_btn.clicked.connect(self._browse_update_zip)
        update_zip_row = QHBoxLayout()
        update_zip_row.addWidget(self.update_zip_edit)
        update_zip_row.addWidget(update_browse_btn)

        # --- Windows/OS2-Modus: C:/D: sind echte Ordner oder Image-Dateien
        # statt Archive. ---
        self.windows_c_folder_radio = QRadioButton("Ordner")
        self.windows_c_image_radio = QRadioButton("Image-Datei")
        windows_c_type_group = QButtonGroup(self)
        windows_c_type_group.addButton(self.windows_c_folder_radio)
        windows_c_type_group.addButton(self.windows_c_image_radio)
        if program and program.windows_c_mode == "image":
            self.windows_c_image_radio.setChecked(True)
        else:
            self.windows_c_folder_radio.setChecked(True)
        windows_c_type_row = QHBoxLayout()
        windows_c_type_row.addWidget(self.windows_c_folder_radio)
        windows_c_type_row.addWidget(self.windows_c_image_radio)
        windows_c_type_row.addStretch()

        self.windows_c_edit = QLineEdit((program.windows_c_folder or "") if program else "")
        self.windows_c_edit.setPlaceholderText("Ordner für die Installation (kann leer/neu sein)")
        windows_c_browse_btn = QPushButton("Durchsuchen…")
        windows_c_browse_btn.clicked.connect(self._browse_windows_c)
        windows_c_row = QHBoxLayout()
        windows_c_row.addWidget(self.windows_c_edit)
        windows_c_row.addWidget(windows_c_browse_btn)

        self.windows_c_image_edit = QLineEdit((program.windows_c_image_path or "") if program else "")
        self.windows_c_image_edit.setPlaceholderText("z. B. hdd.img (imgmount/mount -t hdd)")
        windows_c_image_browse_btn = QPushButton("Durchsuchen…")
        windows_c_image_browse_btn.clicked.connect(self._browse_windows_c_image)
        windows_c_image_details_btn = QPushButton("Image-Details")
        windows_c_image_details_btn.clicked.connect(lambda: self._show_image_details(self.windows_c_image_edit, "C:"))
        windows_c_image_row = QHBoxLayout()
        windows_c_image_row.addWidget(self.windows_c_image_edit)
        windows_c_image_row.addWidget(windows_c_image_browse_btn)
        windows_c_image_row.addWidget(windows_c_image_details_btn)

        self.windows_d_folder_radio = QRadioButton("Ordner")
        self.windows_d_image_radio = QRadioButton("Image-Datei")
        windows_d_type_group = QButtonGroup(self)
        windows_d_type_group.addButton(self.windows_d_folder_radio)
        windows_d_type_group.addButton(self.windows_d_image_radio)
        if program and program.windows_d_mode == "image":
            self.windows_d_image_radio.setChecked(True)
        else:
            self.windows_d_folder_radio.setChecked(True)
        windows_d_type_row = QHBoxLayout()
        windows_d_type_row.addWidget(self.windows_d_folder_radio)
        windows_d_type_row.addWidget(self.windows_d_image_radio)
        windows_d_type_row.addStretch()

        self.windows_d_edit = QLineEdit((program.windows_d_folder or "") if program else "")
        self.windows_d_edit.setPlaceholderText("optional - Ordner mit dem Setup")
        windows_d_browse_btn = QPushButton("Durchsuchen…")
        windows_d_browse_btn.clicked.connect(self._browse_windows_d)
        windows_d_row = QHBoxLayout()
        windows_d_row.addWidget(self.windows_d_edit)
        windows_d_row.addWidget(windows_d_browse_btn)

        self.windows_d_image_edit = QLineEdit((program.windows_d_image_path or "") if program else "")
        self.windows_d_image_edit.setPlaceholderText("optional - z. B. setup.img")
        windows_d_image_browse_btn = QPushButton("Durchsuchen…")
        windows_d_image_browse_btn.clicked.connect(self._browse_windows_d_image)
        windows_d_image_details_btn = QPushButton("Image-Details")
        windows_d_image_details_btn.clicked.connect(lambda: self._show_image_details(self.windows_d_image_edit, "D:"))
        windows_d_image_row = QHBoxLayout()
        windows_d_image_row.addWidget(self.windows_d_image_edit)
        windows_d_image_row.addWidget(windows_d_image_browse_btn)
        windows_d_image_row.addWidget(windows_d_image_details_btn)

        # Folder row vs. image row swap visibility together per drive.
        self.windows_c_folder_label = QLabel("Laufwerk C: (Ordner):")
        self.windows_c_image_label = QLabel("Laufwerk C: (Image):")
        self.windows_d_folder_label = QLabel("Laufwerk D: (Ordner):")
        self.windows_d_image_label = QLabel("Laufwerk D: (Image):")

        self.boot_c_radio = QRadioButton("C:")
        self.boot_d_radio = QRadioButton("D:")
        self.boot_e_radio = QRadioButton("E: (CD-ROM)")
        boot_group = QButtonGroup(self)
        for radio in (self.boot_c_radio, self.boot_d_radio, self.boot_e_radio):
            boot_group.addButton(radio)
        current_boot_drive = program.boot_drive if program else BOOT_DRIVE_C
        {BOOT_DRIVE_C: self.boot_c_radio, BOOT_DRIVE_D: self.boot_d_radio, BOOT_DRIVE_E: self.boot_e_radio}[
            current_boot_drive
        ].setChecked(True)
        boot_row = QHBoxLayout()
        boot_row.addWidget(self.boot_c_radio)
        boot_row.addWidget(self.boot_d_radio)
        boot_row.addWidget(self.boot_e_radio)
        boot_row.addStretch()
        self.boot_drive_label = QLabel("Boot-Laufwerk (für Programm unten):")
        self.boot_drive_label.setToolTip(
            "Von welchem Laufwerk aus gestartet wird - meist D: oder E: (das Setup)\n"
            "während der Installation, danach manuell auf C: umstellen."
        )

        self.exe_combo = QComboBox()
        self.exe_combo.setEditable(True)

        self.exe_args_edit = QLineEdit((program.executable_args or "") if program else "")
        self.exe_args_edit.setPlaceholderText("optional, z. B. /is /im /id")
        self.exe_args_edit.setToolTip(
            "Zusätzliche Kommandozeilen-Schalter, getrennt vom Programmpfad\n"
            "(z. B. für eine unbeaufsichtigte Windows-Setup-Installation)."
        )

        self.auto_start_check = QCheckBox("Automatisch starten")
        self.auto_start_check.setChecked(program.auto_start if program else True)

        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItem("Vollbild", userData=DISPLAY_FULLSCREEN)
        self.display_mode_combo.addItem("Vollbild im Fenstermodus", userData=DISPLAY_FULLSCREEN_WINDOWED)
        self.display_mode_combo.addItem("Fenster (Standardgröße)", userData=DISPLAY_WINDOW)
        current_mode = program.display_mode if program else DISPLAY_WINDOW
        idx = self.display_mode_combo.findData(current_mode)
        self.display_mode_combo.setCurrentIndex(idx if idx >= 0 else self.display_mode_combo.count() - 1)

        self.installed_check = QCheckBox("Installiertes Programm (Ordner bleibt erhalten, kein erneutes Entpacken)")
        self.installed_check.setChecked(program.installed if program else False)
        self.installed_check.setToolTip(
            "Für Spiele, die erst per Setup installiert werden müssen: der entpackte\n"
            "Ordner neben der Archiv-Datei bleibt dauerhaft erhalten (auch beim Beenden)\n"
            "und wird nicht erneut überschrieben."
        )

        self.cdrom_check = QCheckBox("CD-ROM-Laufwerk emulieren (MSCDEX)")
        self.cdrom_check.setChecked(program.needs_cdrom if program else False)
        self.cdrom_check.setToolTip(
            "Für Spiele, die beim Start eine echte CD-ROM erwarten (z. B. Kopierschutz-\n"
            "Abfrage oder Sprachausgabe/Videos von CD): wird zusätzlich als Laufwerk E:\n"
            "eingebunden (C: bleibt die normale Installation, D: bleibt für ein Update-\n"
            "Archiv frei), DOSBox lädt dafür automatisch seine eingebaute MSCDEX-\n"
            "Schnittstelle. Dafür unten entweder ein CD-Image oder einen Ordner angeben.\n"
            "\n"
            "Wichtig bei „Von Diskette booten“ bzw. bootfähigem Image (siehe unten): Sobald\n"
            "wirklich gebootet wird, hängt die CD zusätzlich per „-ide“ am virtuellen IDE-\n"
            "Controller, und das gebootete Gastsystem (z. B. echtes MS-DOS) vergibt dafür\n"
            "SEINEN EIGENEN Laufwerksbuchstaben über sein eigenes MSCDEX - der kann von\n"
            "diesem „E:“ abweichen (z. B. R: statt E:)! „E:“ gilt nur für DOSBox' eigene\n"
            "interne Shell vor dem Booten - nach dem Booten zeigt meist eine Meldung wie\n"
            "„Drive R: = Driver ... unit 0“ den tatsächlich zugewiesenen Buchstaben."
        )

        self.cdrom_iso_edit = QLineEdit((program.cdrom_iso_path or "") if program else "")
        self.cdrom_iso_edit.setPlaceholderText("z. B. game.iso oder game.cue")
        cdrom_iso_browse_btn = QPushButton("Durchsuchen…")
        cdrom_iso_browse_btn.clicked.connect(self._browse_cdrom_iso)
        cdrom_iso_row = QHBoxLayout()
        cdrom_iso_row.addWidget(self.cdrom_iso_edit)
        cdrom_iso_row.addWidget(cdrom_iso_browse_btn)
        self.cdrom_iso_label = QLabel("  CD-Image (ISO/CUE) für Laufwerk E:")

        self.cdrom_folder_edit = QLineEdit((program.cdrom_folder_path or "") if program else "")
        self.cdrom_folder_edit.setPlaceholderText("Ordner mit dem CD-Inhalt")
        cdrom_folder_browse_btn = QPushButton("Durchsuchen…")
        cdrom_folder_browse_btn.clicked.connect(self._browse_cdrom_folder)
        cdrom_folder_row = QHBoxLayout()
        cdrom_folder_row.addWidget(self.cdrom_folder_edit)
        cdrom_folder_row.addWidget(cdrom_folder_browse_btn)
        self.cdrom_folder_label = QLabel("  ...oder Ordner für Laufwerk E:")

        # No UI toggle for MOUNT vs. IMGMOUNT anymore - CD images always use
        # IMGMOUNT on every variant now (see _mount_e_line()'s own
        # comments), full stop. The old checkbox for this was confusing
        # (its wording drifted from what it actually did) and, once
        # deprecated, added nothing - removed outright rather than kept
        # around disabled. `Program.cdrom_use_new_mount` stays in the data
        # model for old saved configs, just unused.

        cdrom_widgets = (
            self.cdrom_iso_label,
            self.cdrom_iso_edit,
            cdrom_iso_browse_btn,
            self.cdrom_folder_label,
            self.cdrom_folder_edit,
            cdrom_folder_browse_btn,
        )
        for widget in cdrom_widgets:
            self.cdrom_check.toggled.connect(widget.setEnabled)
            widget.setEnabled(self.cdrom_check.isChecked())

        # --- Disketten (A:/B:), unabhängig von C:/D:/E: - optional
        # eingebunden, und optional als Boot-Ziel (BOOT ersetzt dann den
        # normalen cd/run-Ablauf komplett). ---
        self.floppy_a_edit = QLineEdit((program.floppy_a_path or "") if program else "")
        self.floppy_a_edit.setPlaceholderText("optional, z. B. disk1.img")
        floppy_a_browse_btn = QPushButton("Durchsuchen…")
        floppy_a_browse_btn.clicked.connect(self._browse_floppy_a)
        floppy_a_create_btn = QPushButton("Erstellen…")
        floppy_a_create_btn.setToolTip("Erzeugt eine neue, leere, formatierte Diskette (720 KB oder 1,44 MB).")
        floppy_a_create_btn.clicked.connect(lambda: self._create_floppy(self.floppy_a_edit))
        floppy_a_eject_btn = QPushButton("Auswerfen")
        floppy_a_eject_btn.setToolTip("Leert das Diskettenfeld A: (kein Image mehr eingelegt).")
        floppy_a_eject_btn.clicked.connect(self._eject_floppy_a)
        floppy_a_row = QHBoxLayout()
        floppy_a_row.addWidget(self.floppy_a_edit)
        floppy_a_row.addWidget(floppy_a_browse_btn)
        floppy_a_row.addWidget(floppy_a_create_btn)
        floppy_a_row.addWidget(floppy_a_eject_btn)

        self.floppy_b_edit = QLineEdit((program.floppy_b_path or "") if program else "")
        self.floppy_b_edit.setPlaceholderText("optional, z. B. disk2.img")
        floppy_b_browse_btn = QPushButton("Durchsuchen…")
        floppy_b_browse_btn.clicked.connect(self._browse_floppy_b)
        floppy_b_create_btn = QPushButton("Erstellen…")
        floppy_b_create_btn.setToolTip("Erzeugt eine neue, leere, formatierte Diskette (720 KB oder 1,44 MB).")
        floppy_b_create_btn.clicked.connect(lambda: self._create_floppy(self.floppy_b_edit))
        floppy_b_eject_btn = QPushButton("Auswerfen")
        floppy_b_eject_btn.setToolTip("Leert das Diskettenfeld B: (kein Image mehr eingelegt).")
        floppy_b_eject_btn.clicked.connect(self._eject_floppy_b)
        floppy_b_row = QHBoxLayout()
        floppy_b_row.addWidget(self.floppy_b_edit)
        floppy_b_row.addWidget(floppy_b_browse_btn)
        floppy_b_row.addWidget(floppy_b_create_btn)
        floppy_b_row.addWidget(floppy_b_eject_btn)

        self.boot_floppy_check = QCheckBox("Von Diskette booten (BOOT-Befehl, ersetzt Programmstart)")
        self.boot_floppy_check.setChecked(bool(program.boot_floppy) if program else False)
        self.boot_floppy_check.setToolTip(
            "Bootet DOSBox direkt von der gewählten Diskette (z. B. für ein echtes\n"
            "DOS/Betriebssystem von Diskette) - ersetzt Mounten+cd+Programmstart\n"
            "komplett, da BOOT nie zu DOS zurückkehrt.\n"
            "\n"
            "Falls „CD-ROM-Laufwerk emulieren“ oben aktiv ist: die CD bekommt im\n"
            "gebooteten System einen eigenen, vom hier konfigurierten E: unabhängigen\n"
            "Laufwerksbuchstaben (siehe Tooltip dort)."
        )
        self.boot_floppy_a_radio = QRadioButton("A:")
        self.boot_floppy_b_radio = QRadioButton("B:")
        boot_floppy_group = QButtonGroup(self)
        boot_floppy_group.addButton(self.boot_floppy_a_radio)
        boot_floppy_group.addButton(self.boot_floppy_b_radio)
        if program and program.boot_floppy == "b":
            self.boot_floppy_b_radio.setChecked(True)
        else:
            self.boot_floppy_a_radio.setChecked(True)
        boot_floppy_row = QHBoxLayout()
        boot_floppy_row.addWidget(self.boot_floppy_check)
        boot_floppy_row.addWidget(self.boot_floppy_a_radio)
        boot_floppy_row.addWidget(self.boot_floppy_b_radio)
        boot_floppy_row.addStretch()
        for widget in (self.boot_floppy_a_radio, self.boot_floppy_b_radio):
            self.boot_floppy_check.toggled.connect(widget.setEnabled)
            widget.setEnabled(self.boot_floppy_check.isChecked())

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Bewertung:", rating_row)
        form.addRow("Webseite:", website_row)
        form.addRow("Notizen:", self.notes_edit)
        form.addRow("Installationstyp:", mode_row)
        form.addRow("Archiv-Datei (Laufwerk C:):", zip_row)
        form.addRow("Archiv-Datei (Laufwerk D:):", update_zip_row)
        form.addRow("Laufwerk C: Typ:", windows_c_type_row)
        form.addRow(self.windows_c_folder_label, windows_c_row)
        form.addRow(self.windows_c_image_label, windows_c_image_row)
        form.addRow("Laufwerk D: Typ:", windows_d_type_row)
        form.addRow(self.windows_d_folder_label, windows_d_row)
        form.addRow(self.windows_d_image_label, windows_d_image_row)
        form.addRow(self.boot_drive_label, boot_row)
        form.addRow("Auszuführendes Programm:", self.exe_combo)
        form.addRow("Argumente:", self.exe_args_edit)
        form.addRow("", self.auto_start_check)
        form.addRow("Anzeigemodus:", self.display_mode_combo)
        form.addRow("", self.installed_check)
        form.addRow("", self.cdrom_check)
        form.addRow(self.cdrom_iso_label, cdrom_iso_row)
        form.addRow(self.cdrom_folder_label, cdrom_folder_row)
        form.addRow("Diskette A::", floppy_a_row)
        form.addRow("Diskette B::", floppy_b_row)
        form.addRow("", boot_floppy_row)

        # Game-mode fields vs. Windows/OS2-mode fields swap visibility
        # together, based on the Installationstyp radio choice; within
        # Windows mode, each drive's folder-vs-image row additionally
        # swaps based on that drive's own type radio.
        self._form = form
        self._game_mode_fields = (zip_row, update_zip_row, self.installed_check)
        self._windows_mode_fields = (
            windows_c_type_row,
            windows_c_row,
            windows_c_image_row,
            windows_d_type_row,
            windows_d_row,
            windows_d_image_row,
            boot_row,
        )
        self._windows_c_rows = (windows_c_row, windows_c_image_row)
        self._windows_d_rows = (windows_d_row, windows_d_image_row)
        self.mode_game_radio.toggled.connect(self._update_mode_visibility)
        self.windows_c_image_radio.toggled.connect(self._update_mode_visibility)
        self.windows_d_image_radio.toggled.connect(self._update_mode_visibility)
        self._update_mode_visibility()

        # --- Cover art preview ---
        self.cover_preview = _DropCoverLabel("Kein Cover\n(oder Bild hierher ziehen)")
        self.cover_preview.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setStyleSheet(
            "QLabel { background-color: #1a1a1a; color: #888; border: 1px solid #444; }"
        )
        self.cover_preview.imageDropped.connect(self._on_cover_dropped)

        self.prev_cover_btn = QPushButton("◀")
        self.next_cover_btn = QPushButton("▶")
        self.reload_cover_btn = QPushButton("Cover neu laden")
        self.cover_status_label = QLabel("")
        self.prev_cover_btn.setFixedWidth(32)
        self.next_cover_btn.setFixedWidth(32)
        self.prev_cover_btn.setEnabled(False)
        self.next_cover_btn.setEnabled(False)

        self.prev_cover_btn.clicked.connect(lambda: self._show_candidate(self._candidate_index - 1))
        self.next_cover_btn.clicked.connect(lambda: self._show_candidate(self._candidate_index + 1))
        self.reload_cover_btn.clicked.connect(self._search_covers)

        cover_nav_row = QHBoxLayout()
        cover_nav_row.addStretch()
        cover_nav_row.addWidget(self.prev_cover_btn)
        cover_nav_row.addWidget(self.reload_cover_btn)
        cover_nav_row.addWidget(self.next_cover_btn)
        cover_nav_row.addStretch()

        cover_preview_row = QHBoxLayout()
        cover_preview_row.addStretch()
        cover_preview_row.addWidget(self.cover_preview)
        cover_preview_row.addStretch()

        cover_status_row = QHBoxLayout()
        cover_status_row.addStretch()
        cover_status_row.addWidget(self.cover_status_label)
        cover_status_row.addStretch()

        general_layout = QVBoxLayout()
        general_layout.addLayout(form)
        general_layout.addLayout(cover_preview_row)
        general_layout.addLayout(cover_status_row)
        general_layout.addLayout(cover_nav_row)
        general_tab = QWidget()
        general_tab.setLayout(general_layout)

        # --- DOSBox-Einstellungen tab: per-game override of the global
        # "DOSBox-Staging Config" settings (Einstellungen-Dialog). Off by
        # default - the game just uses whatever is configured globally.
        self.dosbox_override_check = QCheckBox("Eigene DOSBox-Einstellungen für dieses Spiel verwenden")
        self.dosbox_override_check.setChecked(program.override_dosbox_config if program else False)
        self.dosbox_override_check.setToolTip(
            "Überschreibt für dieses Spiel die globalen CPU/Grafik/Sound-Einstellungen\n"
            "aus 'Einstellungen > DOSBox-Staging Config'."
        )
        # Seed the panel from the game's own saved override if it already had
        # one, otherwise from the current global settings - so turning this
        # on for the first time starts from sensible values, not blank ones.
        seed = program if (program and program.override_dosbox_config) else config
        self.dosbox_config_widget = DosboxConfigWidget(
            cpu_cycles_mode=seed.cpu_cycles_mode,
            cpu_cycles_fixed=seed.cpu_cycles_fixed,
            gfx_aspect=seed.gfx_aspect,
            gfx_output=seed.gfx_output,
            gfx_integer_scaling=seed.gfx_integer_scaling,
            midi_device=seed.midi_device,
            sb_type=seed.sb_type,
            opl_mode=seed.opl_mode,
            sb_irq=seed.sb_irq,
            sb_dma=seed.sb_dma,
            sb_hdma=seed.sb_hdma,
            memsize=seed.memsize,
        )
        self.dosbox_config_widget.setEnabled(self.dosbox_override_check.isChecked())
        self.dosbox_override_check.toggled.connect(self.dosbox_config_widget.setEnabled)

        self.dosbox_variant_combo = QComboBox()
        for value, label in _VARIANT_OVERRIDE_LABELS.items():
            self.dosbox_variant_combo.addItem(label, userData=value)
        current_variant_override = program.dosbox_variant_override if program else ""
        variant_idx = self.dosbox_variant_combo.findData(current_variant_override)
        self.dosbox_variant_combo.setCurrentIndex(variant_idx if variant_idx >= 0 else 0)
        self.dosbox_variant_combo.setToolTip(
            "Welcher Emulator dieses Spiel startet - unabhängig von der globalen\n"
            "Voreinstellung (Einstellungen > Allgemein). Die Mount-/Boot-Befehle\n"
            "unten (Image-Mounts, CD-ROM/-ide, Disketten-Boot) werden automatisch\n"
            "für den hier gewählten Emulator passend erzeugt - z. B. falls DOSBox\n"
            "Staging bei einem bestimmten Spiel/Windows-Image Probleme macht,\n"
            "DOSBox-X aber funktioniert."
        )
        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("Emulator:"))
        variant_row.addWidget(self.dosbox_variant_combo)
        variant_row.addStretch()

        # "" (Automatisch) resolves to the app-wide default variant - the
        # panel below should gray out Staging-only fields accordingly, both
        # right away and live as the dropdown changes.
        self.dosbox_config_widget.set_variant(current_variant_override or self.config.dosbox_variant)
        self.dosbox_variant_combo.currentIndexChanged.connect(
            lambda: self.dosbox_config_widget.set_variant(
                self.dosbox_variant_combo.currentData() or self.config.dosbox_variant
            )
        )
        self._update_boot_e_enabled()
        self.dosbox_variant_combo.currentIndexChanged.connect(self._update_boot_e_enabled)

        program_conf_btn = QPushButton("Spiel-Konfig öffnen")
        program_conf_btn.setToolTip(
            "Öffnet die generierte DOSBox-Konfiguration dieses Spiels.\n"
            "Wird vor jedem Start neu geschrieben - Änderungen hier gelten nur\n"
            "bis zum nächsten Start (außer man speichert sie dauerhaft)."
        )
        program_conf_btn.clicked.connect(self._open_program_conf)
        program_conf_btn.setEnabled(program is not None)
        if program is None:
            program_conf_btn.setToolTip("Erst nach dem ersten Speichern verfügbar (Programm hinzufügen, dann bearbeiten).")

        dosbox_conf_btn = QPushButton("DOSBox-Konfiguration öffnen")
        dosbox_conf_btn.setToolTip(
            "Öffnet DOSBox' eigene, dauerhafte Konfigurationsdatei (des aktuell\n"
            "gewählten Emulators). Änderungen hier bleiben erhalten und gelten\n"
            "als Grundlage für jeden Start, zusätzlich zu den Einstellungen hier."
        )
        dosbox_conf_btn.clicked.connect(self._open_dosbox_conf)

        conf_button_row = QHBoxLayout()
        conf_button_row.addWidget(program_conf_btn)
        conf_button_row.addWidget(dosbox_conf_btn)
        conf_button_row.addStretch()

        dosbox_layout = QVBoxLayout()
        dosbox_layout.addLayout(variant_row)
        dosbox_layout.addLayout(conf_button_row)
        if program and program.custom_conf.strip():
            custom_conf_note = QLabel(
                "Dieses Spiel hat eine manuell gespeicherte Konfiguration (über „Spiel-Konfig "
                "öffnen“ oben) - die hat beim Start Vorrang vor den Einstellungen hier. Dort "
                "auf „Automatisch generieren“ + Speichern, um sie zu verwerfen."
            )
            custom_conf_note.setWordWrap(True)
            custom_conf_note.setStyleSheet("color: #d9a441;")
            dosbox_layout.addWidget(custom_conf_note)
        dosbox_layout.addWidget(self.dosbox_override_check)
        dosbox_layout.addWidget(self.dosbox_config_widget)
        dosbox_layout.addStretch()
        dosbox_tab = QWidget()
        dosbox_tab.setLayout(dosbox_layout)

        tabs = QTabWidget()
        tabs.addTab(general_tab, "Allgemein")
        tabs.addTab(dosbox_tab, "DOSBox-Einstellungen")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        if program:
            self._populate_runnables(preselect=program.executable)
        self.zip_edit.textChanged.connect(lambda _: self._populate_runnables())
        self.installed_check.toggled.connect(lambda _: self._populate_runnables())
        self.windows_c_edit.textChanged.connect(lambda _: self._populate_runnables())
        self.windows_d_edit.textChanged.connect(lambda _: self._populate_runnables())
        for radio in (self.boot_c_radio, self.boot_d_radio, self.boot_e_radio):
            radio.toggled.connect(lambda checked: self._populate_runnables() if checked else None)

        self._result_program: Program | None = None

        # Cover browsing state.
        self._candidate_urls: list[str] = []
        self._candidate_index: int = -1
        self._candidate_images: dict[int, object] = {}
        self._pending_image = None  # PIL Image chosen to be saved on accept
        self._search_worker: CoverSearchWorker | None = None
        self._download_worker: CoverImageDownloadWorker | None = None

        if program:
            existing = cover_path_for(program.identity_path)
            if existing.is_file():
                self.cover_preview.setPixmap(
                    QPixmap(str(existing)).scaled(
                        _PREVIEW_SIZE,
                        _PREVIEW_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def _to_stored_path(self, absolute_path: str) -> str:
        # If the picked file lives under the configured games root, store a
        # path relative to it (portable: survives moving/renaming the whole
        # app+games folder together). Otherwise fall back to the absolute
        # path, which still works via AppConfig.resolve_path.
        if self.config.games_root:
            try:
                rel = Path(absolute_path).resolve().relative_to(Path(self.config.games_root).resolve())
                return str(rel)
            except ValueError:
                pass
        return absolute_path

    def _open_website(self) -> None:
        url_text = self.website_edit.text().strip()
        if not url_text:
            return
        if "://" not in url_text:
            url_text = f"https://{url_text}"
        QDesktopServices.openUrl(QUrl(url_text))

    def _browse_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Archiv-Datei wählen", "", "Archive (*.zip *.rar)"
        )
        if path:
            self.zip_edit.setText(self._maybe_import_into_games_root(path))

    def _maybe_import_into_games_root(self, absolute_path: str) -> str:
        # If the picked archive already lives under games_root (or there's
        # no games_root configured), nothing to ask - same as before.
        if not self.config.games_root:
            return self._to_stored_path(absolute_path)
        games_root = Path(self.config.games_root).resolve()
        try:
            Path(absolute_path).resolve().relative_to(games_root)
            return self._to_stored_path(absolute_path)
        except ValueError:
            pass

        name = Path(absolute_path).name
        reply = QMessageBox.question(
            self,
            "In Spieleordner importieren?",
            f"„{name}“ liegt außerhalb des Spiele-Basisordners:\n{games_root}\n\n"
            "Soll die Datei dorthin kopiert werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return absolute_path

        dest = games_root / name
        if dest.exists():
            overwrite = QMessageBox.question(
                self,
                "Datei existiert bereits",
                f"„{name}“ existiert bereits im Spieleordner. Überschreiben?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return absolute_path

        try:
            games_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(absolute_path, dest)
        except OSError as e:
            QMessageBox.critical(self, "Kopieren fehlgeschlagen", f"Konnte nicht kopiert werden:\n{e}")
            return absolute_path

        return self._to_stored_path(str(dest))

    def _browse_update_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Archiv-Datei für Laufwerk D: wählen", "", "Archive (*.zip *.rar)"
        )
        if path:
            self.update_zip_edit.setText(self._to_stored_path(path))

    def _browse_cdrom_iso(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "CD-Image für Laufwerk E: wählen",
            "",
            "Disk-Images (*.iso *.cue *.bin *.mds *.mdf)",
        )
        if path:
            self.cdrom_iso_edit.setText(self._to_stored_path(path))

    def _browse_cdrom_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Ordner für Laufwerk E: wählen")
        if path:
            self.cdrom_folder_edit.setText(self._to_stored_path(path))

    def _browse_windows_c(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Ordner für Laufwerk C: wählen")
        if path:
            self.windows_c_edit.setText(self._to_stored_path(path))
            self._populate_runnables()

    def _browse_windows_d(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Setup-Ordner für Laufwerk D: wählen")
        if path:
            self.windows_d_edit.setText(self._to_stored_path(path))
            self._populate_runnables()

    def _browse_windows_c_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Image-Datei für Laufwerk C: wählen", "", "Disk-Images (*.img *.ima *.vhd)"
        )
        if path:
            self.windows_c_image_edit.setText(self._to_stored_path(path))

    def _browse_windows_d_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Image-Datei für Laufwerk D: wählen", "", "Disk-Images (*.img *.ima *.vhd)"
        )
        if path:
            self.windows_d_image_edit.setText(self._to_stored_path(path))

    def _show_image_details(self, edit: QLineEdit, drive_label: str) -> None:
        path_text = edit.text().strip()
        if not path_text:
            QMessageBox.information(self, "Image-Details", "Kein Image angegeben.")
            return
        resolved = Path(self.config.resolve_path(path_text))
        if not resolved.is_file():
            QMessageBox.warning(self, "Image-Details", f"Datei nicht gefunden:\n{resolved}")
            return

        size_bytes = resolved.stat().st_size
        cylinders, heads, sectors = image_geometry(size_bytes)
        try:
            with resolved.open("rb") as f:
                first_sector = f.read(512)
            has_boot_signature = len(first_sector) == 512 and first_sector[510:512] == b"\x55\xAA"
        except OSError:
            has_boot_signature = False

        drive_number = "2" if drive_label == "C:" else "3"
        lines = [
            f"Pfad: {resolved}",
            f"Größe: {size_bytes:,} Bytes (~{size_bytes / 1_000_000:.1f} MB)".replace(",", "."),
            f"Zylinder: {cylinders}",
            f"Köpfe: {heads}",
            f"Sektoren/Spur: {sectors}",
            f"-chs-Parameter: {cylinders},{heads},{sectors}",
            f"Boot-Signatur (0x55AA): {'vorhanden' if has_boot_signature else 'nicht vorhanden'}",
            f"Wird gemountet als: Laufwerk {drive_label} (DOSBox-Laufwerksnummer {drive_number})",
        ]
        QMessageBox.information(self, f"Image-Details – Laufwerk {drive_label}", "\n".join(lines))

    def _browse_floppy_a(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Disketten-Image für Laufwerk A: wählen", "", "Disk-Images (*.img *.ima)"
        )
        if path:
            self.floppy_a_edit.setText(self._to_stored_path(path))

    def _browse_floppy_b(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Disketten-Image für Laufwerk B: wählen", "", "Disk-Images (*.img *.ima)"
        )
        if path:
            self.floppy_b_edit.setText(self._to_stored_path(path))

    def _create_floppy(self, target_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Neue Diskette erstellen", "", "Disketten-Image (*.img)"
        )
        if not path:
            return
        if not path.lower().endswith((".img", ".ima")):
            path += ".img"

        size_dialog = QDialog(self)
        size_dialog.setWindowTitle("Diskettenformat wählen")
        size_layout = QVBoxLayout(size_dialog)
        size_720_radio = QRadioButton("720 KB (doppelte Dichte, DD)")
        size_1440_radio = QRadioButton("1,44 MB (hohe Dichte, HD)")
        size_1440_radio.setChecked(True)
        size_group = QButtonGroup(size_dialog)
        size_group.addButton(size_720_radio)
        size_group.addButton(size_1440_radio)
        size_layout.addWidget(size_720_radio)
        size_layout.addWidget(size_1440_radio)
        size_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        size_buttons.accepted.connect(size_dialog.accept)
        size_buttons.rejected.connect(size_dialog.reject)
        size_layout.addWidget(size_buttons)
        if size_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        size_kb = FLOPPY_SIZE_720 if size_720_radio.isChecked() else FLOPPY_SIZE_1440

        variant = self.dosbox_variant_combo.currentData() or self.config.dosbox_variant
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            create_floppy_image(self.config, variant, path, size_kb)
        except (FloppyCreationError, OSError) as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Diskette erstellen fehlgeschlagen", str(e))
            return
        QApplication.restoreOverrideCursor()

        target_edit.setText(self._to_stored_path(path))
        size_label = "1,44 MB" if size_kb == FLOPPY_SIZE_1440 else "720 KB"
        QMessageBox.information(
            self, "Diskette erstellt", f"Neue {size_label}-Diskette wurde erstellt:\n{path}"
        )

    def _eject_floppy_a(self) -> None:
        self.floppy_a_edit.clear()
        if self.boot_floppy_a_radio.isChecked():
            self.boot_floppy_check.setChecked(False)

    def _eject_floppy_b(self) -> None:
        self.floppy_b_edit.clear()
        if self.boot_floppy_b_radio.isChecked():
            self.boot_floppy_check.setChecked(False)

    def _open_program_conf(self) -> None:
        program = self.program
        if program is None:
            return
        try:
            # Reflects what will actually be used next: the saved
            # custom_conf override if this game has one, otherwise a fresh
            # auto-generated preview from the current (saved) settings.
            conf_path = build_autoexec_conf(self.config, program)
        except ExtractionError as e:
            QMessageBox.critical(self, "Entpacken fehlgeschlagen", f"Das Archiv konnte nicht entpackt werden:\n{e}")
            return

        def on_save(text: str) -> None:
            program.custom_conf = text
            save_config(self.config)

        dialog = ConfEditorDialog(
            conf_path,
            f"Spiel-Konfiguration: {program.name}",
            self,
            warning_text=(
                "Speichern macht diese Fassung dauerhaft für dieses Spiel - sie ersetzt "
                "dann die automatische Erzeugung aus den Einstellungen. Mit „Automatisch "
                "generieren“ lässt sich jederzeit wieder die aktuelle automatische Fassung laden."
            ),
            width=self.config.conf_editor_width,
            height=self.config.conf_editor_height,
            on_save=on_save,
            on_reset=lambda: generate_autoexec_conf(self.config, program),
        )
        dialog.exec()
        self.config.conf_editor_width = dialog.width()
        self.config.conf_editor_height = dialog.height()
        save_config(self.config)

    def _current_variant_program(self) -> Program | None:
        # Reflects the emulator dropdown's LIVE (possibly unsaved) selection
        # rather than self.program's last-saved value, so "DOSBox-Konfiguration
        # öffnen" always opens the config for whatever's currently picked.
        if self.program is None:
            return None
        return dataclasses.replace(
            self.program, dosbox_variant_override=self.dosbox_variant_combo.currentData()
        )

    def _update_boot_e_enabled(self) -> None:
        # DOSBox Staging's BOOT command only ever accepts A/C/D - confirmed
        # directly from its own source (boot.cpp) - there is no CD-ROM/El
        # Torito boot support there at all, so a program pinned (or
        # defaulting) to Staging can never actually boot from E:. DOSBox-X
        # does have real El Torito CD-boot support in principle (a separate
        # -bootcd/-el-torito flag, not yet wired up in this app's own conf
        # generation) - deliberately NOT disabling E: there, since it isn't
        # a hard impossibility for that variant the way it is for Staging.
        variant = self.dosbox_variant_combo.currentData() or self.config.dosbox_variant
        is_staging = variant == VARIANT_STAGING
        self.boot_e_radio.setEnabled(not is_staging)
        self.boot_e_radio.setToolTip(
            "DOSBox Staging kann grundsätzlich nicht von CD-ROM booten (bestätigt aus\n"
            "dessen eigenem Quellcode - BOOT akzeptiert nur A:/C:/D:, kein El-Torito-\n"
            "Support). Auf DOSBox-X umstellen, falls von CD gebootet werden soll."
            if is_staging
            else ""
        )

    def _open_dosbox_conf(self) -> None:
        variant_program = self._current_variant_program()
        try:
            conf_path = dosbox_primary_conf_path(self.config, variant_program)
        except (OSError, RuntimeError) as e:
            QMessageBox.critical(
                self,
                "DOSBox-Konfiguration nicht gefunden",
                f"Der Pfad zur DOSBox-Konfiguration konnte nicht ermittelt werden:\n{e}\n\n"
                f"Befehl/Pfad in den Einstellungen prüfen: „{dosbox_command_for(self.config, variant_program)}“.",
            )
            return
        dialog = ConfEditorDialog(
            conf_path,
            "DOSBox-Konfiguration",
            self,
            width=self.config.conf_editor_width,
            height=self.config.conf_editor_height,
        )
        dialog.exec()
        self.config.conf_editor_width = dialog.width()
        self.config.conf_editor_height = dialog.height()
        save_config(self.config)

    def _set_field_visible(self, field, visible: bool) -> None:
        label = self._form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        if isinstance(field, QHBoxLayout):
            for i in range(field.count()):
                widget = field.itemAt(i).widget()
                if widget is not None:
                    widget.setVisible(visible)
        else:
            field.setVisible(visible)

    def _update_mode_visibility(self) -> None:
        is_windows = self.mode_windows_radio.isChecked()
        for field in self._game_mode_fields:
            self._set_field_visible(field, not is_windows)
        for field in self._windows_mode_fields:
            self._set_field_visible(field, is_windows)
        if is_windows:
            c_folder_row, c_image_row = self._windows_c_rows
            self._set_field_visible(c_folder_row, not self.windows_c_image_radio.isChecked())
            self._set_field_visible(c_image_row, self.windows_c_image_radio.isChecked())
            d_folder_row, d_image_row = self._windows_d_rows
            self._set_field_visible(d_folder_row, not self.windows_d_image_radio.isChecked())
            self._set_field_visible(d_image_row, self.windows_d_image_radio.isChecked())
        self._populate_runnables()

    def _populate_runnables(self, preselect: str | None = None) -> None:
        self.exe_combo.clear()

        if self.mode_windows_radio.isChecked():
            runnables = self._windows_mode_runnables()
        else:
            runnables = self._game_mode_runnables()

        self.exe_combo.addItems(runnables)
        if preselect:
            idx = self.exe_combo.findText(preselect)
            if idx >= 0:
                self.exe_combo.setCurrentIndex(idx)
            else:
                self.exe_combo.setEditText(preselect)

    def _game_mode_runnables(self) -> list[str]:
        zip_path = self.zip_edit.text().strip()
        if not zip_path:
            return []
        resolved_zip_path = self.config.resolve_path(zip_path)

        runnables = []
        if self.installed_check.isChecked():
            # Once installed, the real executable usually lives in the
            # extracted folder (written there by the DOS setup), not in the
            # original zip anymore.
            fake_program = Program(name="", zip_path=zip_path, executable="")
            runnables = find_runnables_in_dir(program_dir_for(self.config, fake_program))
        if not runnables and Path(resolved_zip_path).is_file():
            # Nothing installed yet (or "Installiert" was just checked ahead
            # of time) - fall back to the zip's own contents, e.g. to pick
            # SETUP.EXE and run the installer for the first time.
            runnables = find_runnables(resolved_zip_path)
        return runnables

    def _windows_mode_runnables(self) -> list[str]:
        # Lists whichever drive is currently the boot drive - that's the
        # one `executable` needs to resolve against. An image-mode drive's
        # contents can't be inspected locally, so no listing there (same
        # as an ISO-based E: - the user just types the path by hand).
        if self.boot_d_radio.isChecked():
            if self.windows_d_image_radio.isChecked():
                return []
            folder_text = self.windows_d_edit.text().strip()
        elif self.boot_e_radio.isChecked():
            folder_text = self.cdrom_folder_edit.text().strip()
        else:
            if self.windows_c_image_radio.isChecked():
                return []
            folder_text = self.windows_c_edit.text().strip()
        if not folder_text:
            return []
        return find_runnables_in_dir(Path(self.config.resolve_path(folder_text)))

    # --- Cover art ---

    def _search_covers(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Kein Name", "Bitte zuerst einen Namen eingeben.")
            return

        self._candidate_urls = []
        self._candidate_index = -1
        self._candidate_images = {}
        self.prev_cover_btn.setEnabled(False)
        self.next_cover_btn.setEnabled(False)
        self.reload_cover_btn.setEnabled(False)
        self.cover_status_label.setText("Suche Cover…")
        self.cover_preview.setText("Suche…")
        self.cover_preview.setPixmap(QPixmap())

        self._search_worker = CoverSearchWorker(name, self)
        self._search_worker.finished_ok.connect(self._on_search_finished)
        self._search_worker.start()

    def _on_search_finished(self, urls: list[str]) -> None:
        self.reload_cover_btn.setEnabled(True)
        self._candidate_urls = urls
        if not urls:
            self.cover_status_label.setText("Keine Cover gefunden.")
            self.cover_preview.setText("Kein Cover")
            return
        self._show_candidate(0)

    def _show_candidate(self, index: int) -> None:
        if not (0 <= index < len(self._candidate_urls)):
            return
        self._candidate_index = index
        self.prev_cover_btn.setEnabled(index > 0)
        self.next_cover_btn.setEnabled(index < len(self._candidate_urls) - 1)
        self.cover_status_label.setText(f"Bild {index + 1} / {len(self._candidate_urls)}")

        cached = self._candidate_images.get(index)
        if cached is not None:
            self._apply_candidate_image(cached)
            return

        self.cover_preview.setText("Lade…")
        self.cover_preview.setPixmap(QPixmap())
        self._download_worker = CoverImageDownloadWorker(index, self._candidate_urls[index], self)
        self._download_worker.finished_ok.connect(self._on_image_downloaded)
        self._download_worker.start()

    def _on_image_downloaded(self, index: int, image) -> None:
        if image is None:
            if index == self._candidate_index:
                self.cover_preview.setText("Fehler beim Laden")
            return
        self._candidate_images[index] = image
        if index == self._candidate_index:
            self._apply_candidate_image(image)

    def _on_cover_dropped(self, path: str) -> None:
        image = load_local_cover_image(path)
        if image is None:
            QMessageBox.warning(self, "Cover laden fehlgeschlagen", f"Konnte das Bild nicht laden:\n{path}")
            return
        # A dropped image replaces any in-progress web-search browsing state,
        # since prev/next would otherwise navigate back to search results.
        self._candidate_urls = []
        self._candidate_index = -1
        self.prev_cover_btn.setEnabled(False)
        self.next_cover_btn.setEnabled(False)
        self.cover_status_label.setText("Eigenes Bild (per Drag & Drop)")
        self._apply_candidate_image(image)

    def _apply_candidate_image(self, image) -> None:
        self._pending_image = image
        self.cover_preview.setPixmap(
            pil_to_pixmap(image).scaled(
                _PREVIEW_SIZE,
                _PREVIEW_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        executable = self.exe_combo.currentText().strip()
        is_windows = self.mode_windows_radio.isChecked()

        if not name or not executable:
            QMessageBox.warning(self, "Fehlende Angaben", "Bitte Name und Programm angeben.")
            return

        zip_path = ""
        update_zip_path = None
        windows_c_folder = ""
        windows_c_image_path = ""
        windows_d_folder = ""
        windows_d_image_path = ""
        windows_c_mode = "image" if self.windows_c_image_radio.isChecked() else "folder"
        windows_d_mode = "image" if self.windows_d_image_radio.isChecked() else "folder"

        if is_windows:
            if windows_c_mode == "image":
                windows_c_image_path = self.windows_c_image_edit.text().strip()
                if not windows_c_image_path:
                    QMessageBox.warning(self, "Fehlende Angaben", "Bitte eine Image-Datei für Laufwerk C: angeben.")
                    return
                if not Path(self.config.resolve_path(windows_c_image_path)).is_file():
                    QMessageBox.warning(
                        self,
                        "Datei nicht gefunden",
                        f"Die Datei existiert nicht:\n{self.config.resolve_path(windows_c_image_path)}",
                    )
                    return
            else:
                windows_c_folder = self.windows_c_edit.text().strip()
                if not windows_c_folder:
                    QMessageBox.warning(self, "Fehlende Angaben", "Bitte einen Ordner für Laufwerk C: angeben.")
                    return

            if windows_d_mode == "image":
                windows_d_image_path = self.windows_d_image_edit.text().strip()
                if windows_d_image_path and not Path(self.config.resolve_path(windows_d_image_path)).is_file():
                    QMessageBox.warning(
                        self,
                        "Datei nicht gefunden",
                        f"Die Datei existiert nicht:\n{self.config.resolve_path(windows_d_image_path)}",
                    )
                    return
            else:
                windows_d_folder = self.windows_d_edit.text().strip()
                if windows_d_folder and not Path(self.config.resolve_path(windows_d_folder)).is_dir():
                    QMessageBox.warning(
                        self,
                        "Ordner nicht gefunden",
                        f"Der Ordner existiert nicht:\n{self.config.resolve_path(windows_d_folder)}",
                    )
                    return

            if self.boot_d_radio.isChecked() and not (windows_d_folder or windows_d_image_path):
                QMessageBox.warning(
                    self,
                    "Boot-Laufwerk ohne Inhalt",
                    "Boot-Laufwerk ist D:, aber weder Ordner noch Image für Laufwerk D: angegeben.",
                )
                return
            if self.boot_e_radio.isChecked() and not self.cdrom_check.isChecked():
                QMessageBox.warning(
                    self,
                    "Boot-Laufwerk ohne CD-ROM",
                    "Boot-Laufwerk ist E:, aber „CD-ROM-Laufwerk emulieren“ ist nicht aktiviert.",
                )
                return
        else:
            zip_path = self.zip_edit.text().strip()
            if not zip_path:
                QMessageBox.warning(self, "Fehlende Angaben", "Bitte eine Archiv-Datei angeben.")
                return
            if not Path(self.config.resolve_path(zip_path)).is_file():
                QMessageBox.warning(
                    self,
                    "Archiv nicht gefunden",
                    f"Die Datei existiert nicht:\n{self.config.resolve_path(zip_path)}",
                )
                return

            update_zip_path = self.update_zip_edit.text().strip() or None
            if update_zip_path and not Path(self.config.resolve_path(update_zip_path)).is_file():
                QMessageBox.warning(
                    self,
                    "Archiv nicht gefunden",
                    f"Die Datei existiert nicht:\n{self.config.resolve_path(update_zip_path)}",
                )
                return

        cdrom_iso_path = self.cdrom_iso_edit.text().strip() or None
        if cdrom_iso_path and not Path(self.config.resolve_path(cdrom_iso_path)).is_file():
            QMessageBox.warning(
                self,
                "CD-Image nicht gefunden",
                f"Die Datei existiert nicht:\n{self.config.resolve_path(cdrom_iso_path)}",
            )
            return

        cdrom_folder_path = self.cdrom_folder_edit.text().strip() or None
        if cdrom_folder_path and not Path(self.config.resolve_path(cdrom_folder_path)).is_dir():
            QMessageBox.warning(
                self,
                "Ordner nicht gefunden",
                f"Der Ordner existiert nicht:\n{self.config.resolve_path(cdrom_folder_path)}",
            )
            return

        if self.cdrom_check.isChecked() and not cdrom_iso_path and not cdrom_folder_path:
            QMessageBox.warning(
                self,
                "CD-ROM ohne Inhalt",
                "Für „CD-ROM-Laufwerk emulieren“ bitte entweder ein CD-Image oder\n"
                "einen Ordner für Laufwerk E: angeben.",
            )
            return

        floppy_a_path = self.floppy_a_edit.text().strip()
        if floppy_a_path and not Path(self.config.resolve_path(floppy_a_path)).is_file():
            QMessageBox.warning(
                self,
                "Datei nicht gefunden",
                f"Die Datei existiert nicht:\n{self.config.resolve_path(floppy_a_path)}",
            )
            return
        floppy_b_path = self.floppy_b_edit.text().strip()
        if floppy_b_path and not Path(self.config.resolve_path(floppy_b_path)).is_file():
            QMessageBox.warning(
                self,
                "Datei nicht gefunden",
                f"Die Datei existiert nicht:\n{self.config.resolve_path(floppy_b_path)}",
            )
            return

        boot_floppy = ""
        if self.boot_floppy_check.isChecked():
            boot_floppy = "b" if self.boot_floppy_b_radio.isChecked() else "a"
            if not (floppy_b_path if boot_floppy == "b" else floppy_a_path):
                QMessageBox.warning(
                    self,
                    "Boot-Diskette ohne Image",
                    f"„Von Diskette booten“ ist aktiv (Laufwerk {boot_floppy.upper()}:), aber kein\n"
                    f"Image dafür angegeben.",
                )
                return

        identity_path = zip_path or windows_c_folder or windows_c_image_path
        if self._pending_image is not None:
            save_cover(self._pending_image, identity_path)

        self._result_program = Program(
            name=name,
            rating=self.rating_widget.rating(),
            website_label=self.website_label_edit.text().strip(),
            website_url=self.website_edit.text().strip(),
            notes=self.notes_edit.toPlainText(),
            zip_path=zip_path,
            executable=executable,
            executable_args=self.exe_args_edit.text().strip(),
            auto_start=self.auto_start_check.isChecked(),
            installed=self.installed_check.isChecked(),
            update_zip_path=update_zip_path,
            display_mode=self.display_mode_combo.currentData(),
            needs_cdrom=self.cdrom_check.isChecked(),
            cdrom_iso_path=cdrom_iso_path,
            cdrom_folder_path=cdrom_folder_path,
            cdrom_use_new_mount=True,  # no UI control anymore - IMGMOUNT is always used regardless
            install_mode=INSTALL_MODE_WINDOWS if is_windows else INSTALL_MODE_GAME,
            windows_c_mode=windows_c_mode,
            windows_c_folder=windows_c_folder,
            windows_c_image_path=windows_c_image_path,
            windows_d_mode=windows_d_mode,
            windows_d_folder=windows_d_folder,
            windows_d_image_path=windows_d_image_path,
            floppy_a_path=floppy_a_path,
            floppy_b_path=floppy_b_path,
            boot_floppy=boot_floppy,
            boot_drive=(
                BOOT_DRIVE_D if self.boot_d_radio.isChecked()
                else BOOT_DRIVE_E if self.boot_e_radio.isChecked()
                else BOOT_DRIVE_C
            ),
            dosbox_variant_override=self.dosbox_variant_combo.currentData(),
            override_dosbox_config=self.dosbox_override_check.isChecked(),
            cpu_cycles_mode=self.dosbox_config_widget.cpu_cycles_mode(),
            cpu_cycles_fixed=self.dosbox_config_widget.cpu_cycles_fixed(),
            gfx_aspect=self.dosbox_config_widget.gfx_aspect(),
            gfx_output=self.dosbox_config_widget.gfx_output(),
            gfx_integer_scaling=self.dosbox_config_widget.gfx_integer_scaling(),
            midi_device=self.dosbox_config_widget.midi_device(),
            sb_type=self.dosbox_config_widget.sb_type(),
            opl_mode=self.dosbox_config_widget.opl_mode(),
            sb_irq=self.dosbox_config_widget.sb_irq(),
            sb_dma=self.dosbox_config_widget.sb_dma(),
            sb_hdma=self.dosbox_config_widget.sb_hdma(),
            memsize=self.dosbox_config_widget.memsize(),
        )
        self.accept()

    def result_program(self) -> Program | None:
        return self._result_program
