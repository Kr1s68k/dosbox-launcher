from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _app_base_dir() -> Path:
    # Frozen (PyInstaller --onedir build): sys.executable sits directly in
    # the portable app folder. Dev mode: this file lives in <app>/app/, so
    # its grandparent is the project/portable root.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_base_dir()

# All app-owned data (settings, program list, cover cache) lives next to the
# app itself rather than under $HOME/.config - that's what makes the whole
# folder portable (copy it anywhere under $HOME and it keeps working).
CONFIG_DIR = APP_DIR / "data"
CONFIG_FILE = CONFIG_DIR / "programs.json"
# Snapshot of programs.json from right before the most recent save - a
# cheap safety net against a save from stale/in-memory state silently
# clobbering real data (bit us once: a crashed rebuild left an old config
# on disk, and the next ordinary save then overwrote it further).
BACKUP_FILE = CONFIG_DIR / "programs.json.bak"

# Where earlier (non-portable) versions kept this - used for a one-time,
# automatic migration so nobody loses their existing game list.
_LEGACY_CONFIG_FILE = Path.home() / ".config" / "dosbox-launcher" / "programs.json"

# Bundled into every published build (see dosbox-launcher.spec's datas) -
# one example program entry (settings + a cached placeholder cover, no real
# game archive) so a fresh install shows a populated, demonstrably-working
# list instead of either a blank one or, worse, a developer's own real
# library ending up in a public release. Only seeded on a genuinely frozen
# build's very first run (see load_config()) - local dev mode
# (.venv/bin/python main.py) never touches this, always starts from
# whatever's really in data/ like before.
_EXAMPLE_DATA_DIR = APP_DIR / "example_data"

VARIANT_STAGING = "staging"
VARIANT_X = "x"

# Flatpak is how most Linux users install DOSBox Staging/DOSBox-X, so that
# stays the Linux default exactly as before. Neither Windows nor macOS has
# Flatpak at all - there the best guess is the bare binary name on PATH
# (Homebrew's "dosbox-staging"/"dosbox-x" formulas, or a Windows build
# unzipped somewhere the user added to PATH) - wrong as often as not for a
# given install, same as the Flatpak default already is for a native Linux
# install, but it's user-editable in Einstellungen either way.
if sys.platform == "win32":
    DEFAULT_COMMAND_STAGING = "dosbox-staging"
    DEFAULT_COMMAND_X = "dosbox-x"
elif sys.platform == "darwin":
    DEFAULT_COMMAND_STAGING = "dosbox-staging"
    DEFAULT_COMMAND_X = "dosbox-x"
else:
    DEFAULT_COMMAND_STAGING = "flatpak run io.github.dosbox-staging"
    DEFAULT_COMMAND_X = "flatpak run com.dosbox_x.DOSBox-X"

DISPLAY_FULLSCREEN = "fullscreen"
DISPLAY_FULLSCREEN_WINDOWED = "fullscreen_windowed"
DISPLAY_WINDOW = "window"

# "game" = archive-based (the original ZIP/RAR mode). "windows" = a
# Windows/OS2 install: C:/D: are real folders picked directly (no
# archive/extraction involved at all).
INSTALL_MODE_GAME = "game"
INSTALL_MODE_WINDOWS = "windows"

# Which drive the generated autoexec switches to and runs `executable`
# from. Game mode always boots C: (hardcoded, ignores this field). Windows
# mode uses it to boot the setup source (D: or E:) during a fresh install,
# then switches to C: once installed - the user flips this manually.
BOOT_DRIVE_C = "c"
BOOT_DRIVE_D = "d"
BOOT_DRIVE_E = "e"

# Verified against the real dosbox-staging.conf keys (0.83) - see
# [[project_dosbox_launcher]] memory for sources, don't guess new ones.
CPU_CYCLES_MAX = "max"
CPU_CYCLES_FIXED = "fixed"

GFX_OUTPUTS = ("opengl", "texture", "texturenb")
INTEGER_SCALING_MODES = ("auto", "off", "horizontal", "vertical")

MIDI_DEVICES = ("auto", "none", "soundcanvas", "fluidsynth", "mt32", "alsa")
SB_TYPES = ("none", "sb1", "sb2", "sbpro1", "sbpro2", "sb16", "gb")
# AdLib/FM (OPL) emulation - independent of sbtype ("auto" follows sbtype's
# own OPL chip; a standalone AdLib card is sbtype=none + oplmode=opl2).
OPL_MODES = ("auto", "opl2", "dualopl2", "opl3", "opl3gold", "esfm", "none")

# Sound Blaster IRQ/DMA - defaults match DOSBox Staging's own (see
# dosbox-staging.org/0.83/manual/sound/sound-devices/sound-blaster/), only
# worth changing per-game if a specific title needs a different one.
SB_IRQS = (3, 5, 7, 9, 10, 11, 12)
SB_DMAS = (0, 1, 3, 5, 6, 7)
SB_HDMAS = (0, 1, 3, 5, 6, 7)

CPU_CYCLES_MIN = 50
CPU_CYCLES_MAX_VALUE = 200_000  # UI cap - the format itself allows up to 2,000,000


@dataclass
class Program:
    name: str
    zip_path: str
    executable: str
    # Extra command-line switches appended after `executable` in the run
    # line (e.g. "/is /im /id" for an unattended Windows 95 setup) - kept
    # separate from `executable` itself rather than typed inline, since
    # `executable_dir`/`executable_name` parse it as a filesystem path and
    # would mis-split on the spaces before any switches.
    executable_args: str = ""
    auto_start: bool = True
    installed: bool = False
    update_zip_path: str | None = None
    display_mode: str = DISPLAY_WINDOW
    # Mounts a separate drive E: with "-t cdrom", which makes DOSBox load
    # its built-in MSCDEX/CD-ROM interface - needed for games that check for
    # a real CD-ROM drive (volume label, MSCDEX presence) before starting.
    # See MOUNT/IMGMOUNT docs: dosbox-staging.org/0.83/manual/using-dosbox
    # -staging/commands/ and dosbox.com/wiki/MOUNT + wiki/IMGMOUNT.
    needs_cdrom: bool = False
    # Exactly one of these supplies E:'s content - deliberately no fallback
    # to C:'s own folder (that silently reused C:'s content for a supposedly
    # separate drive, which doesn't make sense once the user has to pick one
    # explicitly). cdrom_iso_path: a real CD image (.iso/.cue+.bin/.mds+.mdf)
    # mounted via IMGMOUNT - needed when the CD content (e.g. CD-DA audio
    # tracks, data not copied during install) isn't in any extracted folder.
    # cdrom_folder_path: a plain directory mounted via MOUNT -t cdrom, for
    # when the CD content exists as files on disk but not as an image.
    cdrom_iso_path: str | None = None
    cdrom_folder_path: str | None = None
    # DOSBox Staging deprecated IMGMOUNT in favor of a unified MOUNT that
    # auto-detects image files (dosbox-staging.org/0.83/manual/using-dosbox
    # -staging/storage/) - DOSBox-X/classic DOSBox still need the older
    # IMGMOUNT ... -t iso form, so this is opt-in and only applied when the
    # variant is actually Staging (silently falls back to IMGMOUNT
    # otherwise, since the new form isn't guaranteed to work elsewhere).
    cdrom_use_new_mount: bool = False

    # --- Windows/OS2 mode C:/D: can each be a plain folder (as before) or
    # a raw disk image file (e.g. a prepared Windows 95 HDD image), mounted
    # via MOUNT (Staging) or IMGMOUNT ... -t hdd (DOSBox-X/classic). ---
    windows_c_mode: str = "folder"  # "folder" or "image"
    windows_c_image_path: str = ""
    windows_d_mode: str = "folder"
    windows_d_image_path: str = ""

    # --- Floppy images (A:/B:), independent of C:/D:/E: - mounted if a
    # path is given, and optionally the actual boot target: BOOT works
    # directly on the image file, no prior mount needed (dosbox.com/wiki
    # /BOOT, confirmed still true in the current Staging manual). When set,
    # this replaces the normal cd/run flow entirely (BOOT never returns to
    # DOS, so nothing after it would ever execute anyway). ---
    floppy_a_path: str = ""
    floppy_b_path: str = ""
    boot_floppy: str = ""  # "", "a" or "b"

    # Per-game override of the "DOSBox-Staging Config" settings (see
    # AppConfig below) - off by default, meaning the game just uses whatever
    # is configured globally. Values below only take effect when this is on;
    # they otherwise just sit at their last-edited value from the dialog.
    override_dosbox_config: bool = False
    cpu_cycles_mode: str = CPU_CYCLES_MAX
    cpu_cycles_fixed: int = 3000
    gfx_aspect: bool = True
    gfx_output: str = "opengl"
    gfx_integer_scaling: str = "auto"
    midi_device: str = "auto"
    sb_type: str = "sb16"
    opl_mode: str = "auto"
    # memsize is a portable [dosbox]-section key, valid on every variant
    # (unlike the Staging-only cpu/gfx/sound keys above) - see
    # dosbox-staging.org/0.83/manual/system/memory/. 16 is DOSBox's own
    # default; Windows 95 typically wants 64-128.
    memsize: int = 16
    sb_irq: int = 7
    sb_dma: int = 1
    sb_hdma: int = 5

    # A hand-edited full autoexec .conf (saved via the "Spiel-Konfig
    # öffnen" editor) - when non-empty, used verbatim for this game's
    # launches instead of auto-generating from the settings above. Empty
    # (default) = auto-generate as normal.
    custom_conf: str = ""

    # Windows/OS2 install mode: instead of an archive, C: (and optionally
    # D:) are real folders picked directly via a folder browser - nothing
    # is ever extracted, and these folders persist forever (there's no
    # archive to re-extract from in the first place). zip_path/installed/
    # update_zip_path are unused (left empty/default) in this mode.
    install_mode: str = INSTALL_MODE_GAME
    windows_c_folder: str = ""
    windows_d_folder: str = ""
    boot_drive: str = BOOT_DRIVE_C

    # Per-program override of which DOSBox variant/emulator launches this
    # program - "" (default) means "use the global default"
    # (AppConfig.dosbox_variant). Needed because the two variants sometimes
    # behave differently for the same real-hardware-install workflow (e.g.
    # DOSBox Staging having trouble with a specific Windows 95 install that
    # DOSBox-X handles fine, or vice versa) - lets one program pin a
    # specific variant without changing the app-wide default for everything
    # else. Values: "" / VARIANT_STAGING / VARIANT_X.
    dosbox_variant_override: str = ""

    # 5-star rating in half-star steps: 0 (no stars) to 10 (5 full stars),
    # so a value of 7 means "3.5 stars". Int rather than float to avoid
    # any rounding/precision fuss - there are only 11 valid values anyway.
    rating: int = 0

    # Free-form label describing what the link is (e.g. "Codewheel", "Wiki",
    # "Patch") - not every game just has "the website", so this is editable
    # per game rather than a fixed caption.
    website_label: str = ""
    website_url: str = ""
    notes: str = ""

    @property
    def executable_dir(self) -> str:
        return str(Path(self.executable).parent) if "/" in self.executable.replace("\\", "/") else ""

    @property
    def executable_name(self) -> str:
        return Path(self.executable.replace("\\", "/")).name

    @property
    def identity_path(self) -> str:
        # Used only as a stable per-program key (cover-art cache filename,
        # matching a background cover-fetch result back to its program) -
        # zip_path for game mode, windows_c_folder/windows_c_image_path
        # for Windows mode (which has no zip_path at all).
        return self.zip_path or self.windows_c_folder or self.windows_c_image_path


@dataclass
class AppConfig:
    dosbox_variant: str = VARIANT_STAGING
    dosbox_command_staging: str = DEFAULT_COMMAND_STAGING
    dosbox_command_x: str = DEFAULT_COMMAND_X
    cleanup_on_exit: bool = True
    # Extra DOS commands run before every game (e.g. "keyb gr" for a German
    # keyboard layout), inserted right after mounting/switching to C:.
    global_autoexec: str = ""
    # Base folder that Program.zip_path/update_zip_path are resolved against
    # when they're relative paths (absolute paths still work as before, for
    # entries added before this existed, or pointing outside the games
    # root on purpose). Empty = not configured yet.
    games_root: str = ""
    window_width: int = 560
    window_height: int = 420
    program_dialog_width: int = 480
    program_dialog_height: int = 620
    settings_dialog_width: int = 560
    settings_dialog_height: int = 640
    import_dialog_width: int = 560
    import_dialog_height: int = 480
    conf_editor_width: int = 640
    conf_editor_height: int = 520

    # --- DOSBox Staging Config tab (global [cpu]/[render]/[midi]/[sblaster]
    # settings, applied to every launch). ---
    cpu_cycles_mode: str = CPU_CYCLES_MAX
    cpu_cycles_fixed: int = 3000
    gfx_aspect: bool = True
    gfx_output: str = "opengl"
    gfx_integer_scaling: str = "auto"
    midi_device: str = "auto"
    sb_type: str = "sb16"
    opl_mode: str = "auto"
    sb_irq: int = 7
    sb_dma: int = 1
    sb_hdma: int = 5
    memsize: int = 16

    programs: list[Program] = field(default_factory=list)

    @property
    def dosbox_command(self) -> str:
        if self.dosbox_variant == VARIANT_X:
            return self.dosbox_command_x
        return self.dosbox_command_staging

    def resolve_path(self, raw_path: str) -> str:
        p = Path(raw_path)
        if p.is_absolute() or not self.games_root:
            return str(p)
        return str(Path(self.games_root) / p)


def _seed_example_data() -> None:
    """Copies the bundled example_data/ (one placeholder program entry +
    its cover) into data/, so a genuinely frozen build's very first run
    isn't just a blank list. See _EXAMPLE_DATA_DIR's own comment for why
    this only ever runs for a frozen build, never in dev mode."""
    example_programs = _EXAMPLE_DATA_DIR / "programs.json"
    if not example_programs.is_file():
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(example_programs, CONFIG_FILE)
    example_covers = _EXAMPLE_DATA_DIR / "covers"
    if example_covers.is_dir():
        dest_covers = CONFIG_DIR / "covers"
        dest_covers.mkdir(parents=True, exist_ok=True)
        for cover_file in example_covers.iterdir():
            shutil.copy(cover_file, dest_covers / cover_file.name)


def load_config() -> AppConfig:
    if not CONFIG_FILE.exists() and _LEGACY_CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(_LEGACY_CONFIG_FILE, CONFIG_FILE)

    if not CONFIG_FILE.exists() and getattr(sys, "frozen", False):
        _seed_example_data()

    if not CONFIG_FILE.exists():
        return AppConfig()
    data = json.loads(CONFIG_FILE.read_text())
    programs = []
    for p in data.get("programs", []):
        # "fullscreen" (bool) is the pre-display_mode key; migrate it.
        if "fullscreen" in p and "display_mode" not in p:
            p = {**p, "display_mode": DISPLAY_FULLSCREEN if p["fullscreen"] else DISPLAY_WINDOW}
        p.pop("fullscreen", None)
        programs.append(Program(**p))
    # "dosbox_command" is the pre-variant-selector key; fall back to it so
    # existing config files keep working.
    legacy_command = data.get("dosbox_command")
    return AppConfig(
        dosbox_variant=data.get("dosbox_variant", VARIANT_STAGING),
        dosbox_command_staging=data.get(
            "dosbox_command_staging", legacy_command or DEFAULT_COMMAND_STAGING
        ),
        dosbox_command_x=data.get("dosbox_command_x", DEFAULT_COMMAND_X),
        cleanup_on_exit=data.get("cleanup_on_exit", True),
        global_autoexec=data.get("global_autoexec", ""),
        games_root=data.get("games_root", ""),
        window_width=data.get("window_width", 560),
        window_height=data.get("window_height", 420),
        program_dialog_width=data.get("program_dialog_width", 480),
        program_dialog_height=data.get("program_dialog_height", 620),
        settings_dialog_width=data.get("settings_dialog_width", 560),
        settings_dialog_height=data.get("settings_dialog_height", 640),
        import_dialog_width=data.get("import_dialog_width", 560),
        import_dialog_height=data.get("import_dialog_height", 480),
        conf_editor_width=data.get("conf_editor_width", 640),
        conf_editor_height=data.get("conf_editor_height", 520),
        cpu_cycles_mode=data.get("cpu_cycles_mode", CPU_CYCLES_MAX),
        cpu_cycles_fixed=data.get("cpu_cycles_fixed", 3000),
        gfx_aspect=data.get("gfx_aspect", True),
        gfx_output=data.get("gfx_output", "opengl"),
        gfx_integer_scaling=data.get("gfx_integer_scaling", "auto"),
        midi_device=data.get("midi_device", "auto"),
        sb_type=data.get("sb_type", "sb16"),
        opl_mode=data.get("opl_mode", "auto"),
        sb_irq=data.get("sb_irq", 7),
        sb_dma=data.get("sb_dma", 1),
        sb_hdma=data.get("sb_hdma", 5),
        memsize=data.get("memsize", 16),
        programs=programs,
    )


def save_config(config: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.is_file():
        shutil.copyfile(CONFIG_FILE, BACKUP_FILE)
    data = {
        "dosbox_variant": config.dosbox_variant,
        "dosbox_command_staging": config.dosbox_command_staging,
        "dosbox_command_x": config.dosbox_command_x,
        "cleanup_on_exit": config.cleanup_on_exit,
        "global_autoexec": config.global_autoexec,
        "games_root": config.games_root,
        "window_width": config.window_width,
        "window_height": config.window_height,
        "program_dialog_width": config.program_dialog_width,
        "program_dialog_height": config.program_dialog_height,
        "settings_dialog_width": config.settings_dialog_width,
        "settings_dialog_height": config.settings_dialog_height,
        "import_dialog_width": config.import_dialog_width,
        "import_dialog_height": config.import_dialog_height,
        "conf_editor_width": config.conf_editor_width,
        "conf_editor_height": config.conf_editor_height,
        "cpu_cycles_mode": config.cpu_cycles_mode,
        "cpu_cycles_fixed": config.cpu_cycles_fixed,
        "gfx_aspect": config.gfx_aspect,
        "gfx_output": config.gfx_output,
        "gfx_integer_scaling": config.gfx_integer_scaling,
        "midi_device": config.midi_device,
        "sb_type": config.sb_type,
        "opl_mode": config.opl_mode,
        "sb_irq": config.sb_irq,
        "sb_dma": config.sb_dma,
        "sb_hdma": config.sb_hdma,
        "memsize": config.memsize,
        "programs": [asdict(p) for p in config.programs],
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
