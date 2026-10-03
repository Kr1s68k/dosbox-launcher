from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import (
    BOOT_DRIVE_C,
    BOOT_DRIVE_D,
    BOOT_DRIVE_E,
    CONFIG_DIR,
    CPU_CYCLES_FIXED,
    DISPLAY_FULLSCREEN,
    DISPLAY_FULLSCREEN_WINDOWED,
    INSTALL_MODE_WINDOWS,
    VARIANT_STAGING,
    VARIANT_X,
    AppConfig,
    Program,
)

_AUTOEXEC_TEMPLATE = """{hw_sections}[sdl]
{sdl_lines}
[autoexec]
@echo off
{mount_c_line}{mount_d_line}{mount_e_line}{mount_floppy_lines}{boot_drive_line}
{global_autoexec_lines}{cd_line}{run_line}
"""

def _sdl_lines(variant: str, display_mode: str, gfx_output: str) -> str:
    """[sdl] section lines. Staging's own behavior here is intentionally
    UNCHANGED from before DOSBox-X support existed (still always writes
    `window_size = default`, `fullscreen_mode = forced-borderless`,
    `output = ...`) - a standing rule for this project is that DOSBox-X
    work must never alter the already-working, already-tested Staging
    output, even when a DOSBox-X investigation surfaces something that
    looks like it'd apply to Staging too (see [[feedback_dosbox_x_isolated_from_staging]]).

    DOSBox-X gets its own, separately-reasoned-about behavior: it has no
    `window_size` key at all (its real equivalent is the differently-named
    `windowresolution=`, confirmed via its own source, sdlmain.cpp) - since
    this app doesn't offer a resolution field of its own for DOSBox-X, it
    deliberately omits any resolution-related key there entirely, so
    whatever the user has set directly in DOSBox-X's own persistent conf
    keeps applying (DOSBox conf files layer - confirmed from DOSBox-X's own
    Config::ParseConfigFile()/Section_prop::HandleInputline() - a later
    -conf file only overrides keys it explicitly mentions). DOSBox-X also
    has no `fullscreen_mode`/"forced-borderless" equivalent (grepped its
    source, no match; its own `fullresolution=` already defaults to the
    sensible "desktop" value, so nothing is lost by not setting it there).
    """
    if variant != VARIANT_STAGING:
        if display_mode in (DISPLAY_FULLSCREEN, DISPLAY_FULLSCREEN_WINDOWED):
            return "fullscreen = on\n"
        return "fullscreen = off\n"

    if display_mode == DISPLAY_FULLSCREEN:
        return "fullscreen = on\n" f"output = {gfx_output}\n"
    if display_mode == DISPLAY_FULLSCREEN_WINDOWED:
        return "fullscreen = on\n" "fullscreen_mode = forced-borderless\n" f"output = {gfx_output}\n"
    return "fullscreen = off\n" "window_size = default\n" f"output = {gfx_output}\n"


@dataclass
class _EffectiveDosboxConfig:
    cpu_cycles_mode: str
    cpu_cycles_fixed: int
    gfx_aspect: bool
    gfx_output: str
    gfx_integer_scaling: str
    midi_device: str
    sb_type: str
    opl_mode: str
    sb_irq: int
    sb_dma: int
    sb_hdma: int
    memsize: int


def _effective_dosbox_config(config: AppConfig, program: Program) -> _EffectiveDosboxConfig:
    # A game's own "DOSBox-Einstellungen" tab can override the global
    # "DOSBox-Staging Config" settings - global is the default, per-game
    # only takes effect when the game explicitly opts in.
    source = program if program.override_dosbox_config else config
    return _EffectiveDosboxConfig(
        cpu_cycles_mode=source.cpu_cycles_mode,
        cpu_cycles_fixed=source.cpu_cycles_fixed,
        gfx_aspect=source.gfx_aspect,
        gfx_output=source.gfx_output,
        gfx_integer_scaling=source.gfx_integer_scaling,
        midi_device=source.midi_device,
        sb_type=source.sb_type,
        opl_mode=source.opl_mode,
        sb_irq=source.sb_irq,
        sb_dma=source.sb_dma,
        sb_hdma=source.sb_hdma,
        memsize=source.memsize,
    )


def _effective_variant(config: AppConfig, program: Program) -> str:
    """Per-program DOSBox variant, falling back to the app-wide default when
    the program hasn't opted into an override - lets one program (e.g. a
    Windows 95 install that has trouble on one variant) use a different
    emulator without changing the default for everything else."""
    return program.dosbox_variant_override or config.dosbox_variant


def dosbox_command_for(config: AppConfig, program: Program | None) -> str:
    """The actual DOSBox command to launch `program` with - resolves its
    per-program variant override (if any) to the matching configured
    command, falling back to the app-wide default command when `program` is
    None (e.g. the "Add new program" dialog, which has nothing to resolve
    against yet)."""
    variant = _effective_variant(config, program) if program is not None else config.dosbox_variant
    return config.dosbox_command_x if variant == VARIANT_X else config.dosbox_command_staging


def _hw_config_sections(variant: str, eff: _EffectiveDosboxConfig) -> str:
    # memsize ([dosbox] section) is portable across every variant - the
    # same key/section on Staging, DOSBox-X and classic DOSBox alike - so
    # it's emitted unconditionally.
    memory_section = f"[dosbox]\nmemsize = {eff.memsize}\n\n"

    if variant == VARIANT_STAGING:
        cycles = str(eff.cpu_cycles_fixed) if eff.cpu_cycles_mode == CPU_CYCLES_FIXED else "max"
        aspect = "auto" if eff.gfx_aspect else "off"
        return (
            memory_section
            + "[cpu]\n"
            f"cpu_cycles = {cycles}\n"
            "\n"
            "[render]\n"
            f"aspect = {aspect}\n"
            f"integer_scaling = {eff.gfx_integer_scaling}\n"
            "\n"
            "[midi]\n"
            f"mididevice = {eff.midi_device}\n"
            "\n"
            "[sblaster]\n"
            f"sbtype = {eff.sb_type}\n"
            f"oplmode = {eff.opl_mode}\n"
            f"irq = {eff.sb_irq}\n"
            f"dma = {eff.sb_dma}\n"
            f"hdma = {eff.sb_hdma}\n"
            "\n"
        )

    if variant == VARIANT_X:
        # DOSBox-X uses classic-DOSBox-lineage key names/values, verified
        # directly from its own source (src/dosbox.cpp, src/hardware/
        # sblaster.cpp - v2026.08.31/master) rather than assumed from
        # Staging's modernized keys:
        # - cycles takes "auto|max|fixed <n>" (not a bare number).
        # - aspect is a true/false string (not "auto"/"off").
        # - there is NO integer_scaling key at all in DOSBox-X (its own
        #   "scaler=" is a completely different pixel-scaling-algorithm
        #   selector, not analogous to Staging's integer-multiple toggle -
        #   deliberately not emitted rather than guessing a mapping; the
        #   UI grays this field out for DOSBox-X for the same reason).
        # - mididevice's own default value is the literal string
        #   "default" (not "auto" as in Staging) - translated below.
        #   "soundcanvas" (this app's Roland Sound Canvas option) has no
        #   confirmed DOSBox-X equivalent in its device list - passed
        #   through unchanged rather than guessing a substitute; if
        #   DOSBox-X rejects it, "DOSBox-Konfiguration öffnen"/"Spiel-
        #   Konfig öffnen" show exactly what was sent so it's easy to spot.
        # - sbtype/oplmode/irq/dma/hdma use the exact same key names AND
        #   value sets this app already offers (double-checked: this
        #   project's SB_TYPES/OPL_MODES/SB_IRQS/SB_DMAS/SB_HDMAS tuples
        #   are each a valid subset of DOSBox-X's own value arrays), so
        #   those five need no translation at all.
        cycles = f"fixed {eff.cpu_cycles_fixed}" if eff.cpu_cycles_mode == CPU_CYCLES_FIXED else "max"
        aspect = "true" if eff.gfx_aspect else "false"
        midi_device = "default" if eff.midi_device == "auto" else eff.midi_device
        return (
            memory_section
            + "[cpu]\n"
            f"cycles = {cycles}\n"
            "\n"
            "[render]\n"
            f"aspect = {aspect}\n"
            "\n"
            "[midi]\n"
            f"mididevice = {midi_device}\n"
            "\n"
            "[sblaster]\n"
            f"sbtype = {eff.sb_type}\n"
            f"oplmode = {eff.opl_mode}\n"
            f"irq = {eff.sb_irq}\n"
            f"dma = {eff.sb_dma}\n"
            f"hdma = {eff.sb_hdma}\n"
            "\n"
        )

    return memory_section

# Written under CONFIG_DIR (inside $HOME) rather than /tmp: DOSBox Staging is
# commonly installed as a Flatpak, whose sandbox only grants access to the
# home directory, not the host's /tmp.
_LAUNCH_CONF_PATH = CONFIG_DIR / "launch.conf"

# Tools that can extract a .rar, tried in order (first one found in PATH
# wins). Unlike zip, Python has no built-in rar support, so this always
# shells out. Each entry builds the full command for (archive, dest_dir).
_RAR_EXTRACTORS = [
    ("unrar", lambda archive, dest: ["unrar", "x", "-y", "-o+", archive, dest + "/"]),
    ("7z", lambda archive, dest: ["7z", "x", "-y", f"-o{dest}", archive]),
    ("7zz", lambda archive, dest: ["7zz", "x", "-y", f"-o{dest}", archive]),
    ("unar", lambda archive, dest: ["unar", "-force-overwrite", "-o", dest, archive]),
]


class ExtractionError(RuntimeError):
    pass


# Characters allowed in a DOS 8.3 short name (besides letters/digits).
_DOS_INVALID_CHARS = re.compile(r"[^A-Z0-9!#$%&'()\-@^_`{}~]")


def _dos_clean(name: str) -> str:
    return _DOS_INVALID_CHARS.sub("", name.upper())


def _dos_short_component(name: str, sibling_names: list[str]) -> str:
    """The DOS 8.3 short name DOSBox exposes for `name`, given the other
    real entries in the same directory (needed for ~N collision numbering:
    e.g. two folders both truncating to "3DWORL" become 3DWORL~1/3DWORL~2).
    The DOS kernel emulated by DOSBox can't address paths longer than
    8.3, so `cd`/run commands must use these short names instead of the
    long ones a modern zip/rar happens to contain."""
    base, _, ext = name.rpartition(".")
    if not base:
        base, ext = name, ""
    base_clean = _dos_clean(base)
    ext_clean = _dos_clean(ext)[:3]

    if len(base_clean) <= 8:
        short_base = base_clean
    else:
        prefix = base_clean[:6]
        index = 0
        for sibling in sorted(set(sibling_names)):
            sib_base, _, sib_ext = sibling.rpartition(".")
            if not sib_base:
                sib_base, sib_ext = sibling, ""
            sib_base_clean = _dos_clean(sib_base)
            sib_ext_clean = _dos_clean(sib_ext)[:3]
            if len(sib_base_clean) > 8 and sib_base_clean[:6] == prefix and sib_ext_clean == ext_clean:
                index += 1
                if sibling == name:
                    break
        short_base = f"{prefix}~{index or 1}"

    return f"{short_base}.{ext_clean}" if ext_clean else short_base


def _cdrom_label(name: str) -> str:
    # DOS volume labels are at most 11 characters (no extension) - reuse the
    # same character-cleaning rules as short filenames.
    label = _dos_clean(name)[:11]
    return label or "GAMECD"


def _mount_e_line(config: AppConfig, program: Program, boots_away: bool = False) -> str:
    if not program.needs_cdrom:
        return ""
    # C: is the installed game / hard-disk content, D: (if present) is the
    # update archive - the CD-ROM itself goes on a separate drive, E:, so it
    # doesn't collide with either. Exactly one of these two is expected to
    # be set (enforced in ProgramDialog); deliberately no fallback to C:'s
    # own folder - re-presenting C:'s content as a supposedly separate
    # drive doesn't reflect a real CD-ROM for games that actually need one.
    #
    # `boots_away` (true when this launch hands off to a genuinely BOOTed
    # guest OS - a boot floppy, or a raw C:/D: image booted via `boot -l`)
    # adds an IDE-attach flag: a plain drive-letter MOUNT/IMGMOUNT only
    # registers the CD in DOSBox's OWN internal DOS drive table - a
    # separately booted guest kernel has its own independent drive table
    # and can't see it at all, the same reason raw HDD images need a
    # drive-NUMBER "-fs none" mount instead of a letter. `-ide` attaches
    # the image to a virtual IDE controller instead, visible at the real
    # BIOS/ATAPI hardware level to any booted guest.
    #
    # The exact flag syntax differs by variant - confirmed directly from
    # each project's own source, not guessed (a DOSBox-X-flavored guide
    # pasted into this project once suggested "-t raw -ide 2m" for Staging,
    # which is wrong there): Staging's `-ide` (src/dos/programs/mount.cpp)
    # is a bare boolean flag with no value, auto-picking the next free IDE
    # slot, and only ever attaches when the mount is explicitly typed as
    # CD-ROM (`params.type == MountType::CdRomImage` gates the real
    # IDE_Get_Next_Cable_Slot() call - the newer unified auto-detecting
    # `mount e "<iso>"` form, no `-t`, never sets that type, so `-ide`
    # silently no-ops on it with no error at all). DOSBox-X's `-ide`
    # (src/dos/dos_programs.cpp) instead wants an explicit slot value -
    # "1m"/"1s"/"2m"/"2s" (primary/secondary, master/slave). Which slot to
    # use is "2m" (secondary master) ALWAYS on DOSBox-X, regardless of
    # whether D: is also mounted - confirmed via real hardware testing,
    # not guessed: OAKCDROM.SYS/MSCDEX (running under a genuinely booted
    # guest) reliably found the CD-ROM when it was attached at "2m", but
    # reported "No drives found, aborting installation" when a later
    # change moved it to "1s" instead (freeing "2m" for D: at the time) -
    # a real DOSBox-X IDE-emulation quirk specific to the CD-ROM ending up
    # on "1s", not a channel-sharing issue in general. D: itself (see
    # _image_mount_line) now always uses "1s" instead, precisely so it
    # never competes with the CD-ROM for "2m" - the two are deliberately
    # never swapped. Both variants also always need the explicit "-t iso"
    # mount type for this to work - Staging's unified no-"-t" form is fine
    # for DOSBox's own pre-boot shell but never valid together with
    # `-ide`, and DOSBox-X has no unified form to begin with (MOUNT itself
    # tells you to use IMGMOUNT for image files).
    #
    # The guest OS still needs its own real-mode CD-ROM driver
    # (OAKCDROM.SYS) + MSCDEX/SHSUCDX loaded from its own CONFIG.SYS/
    # AUTOEXEC.BAT to actually use it - that lives on the boot floppy/image
    # itself, nothing this app generates can inject it.
    variant = _effective_variant(config, program)
    if boots_away:
        ide_flag = " -ide" if variant == VARIANT_STAGING else " -ide 2m"
    else:
        ide_flag = ""
    if program.cdrom_iso_path:
        # A real CD image (.iso/.cue+.bin/.mds+.mdf) - always mounted via
        # explicit IMGMOUNT ... -t iso, on every variant, never via
        # Staging's newer unified auto-detecting "mount e <iso>" (no -t)
        # form. That unified form is what originally required this
        # function to special-case "-t iso" back in whenever -ide was
        # needed (it silently doesn't attach otherwise - see the -ide
        # comment above) - always using the explicit form everywhere
        # removes that whole class of footgun instead of special-casing
        # around it. IMGMOUNT still exists on Staging too (confirmed via
        # its own source, mount.cpp: invoking "Z:\IMGMOUNT.COM" is handled
        # as a compatibility layer that just prints a one-line deprecation
        # notice and then runs the exact same MOUNT implementation
        # underneath - so this is a harmless console message there, not a
        # different/riskier code path). `Program.cdrom_use_new_mount`
        # stays in the data model only (its own UI checkbox was removed
        # entirely, not just disabled - user request, after this same
        # field's confusing wording nearly led to reintroducing this exact
        # bug) so existing saved configs that have it set don't need a
        # migration - it's simply never read anymore. "-label" isn't
        # confirmed to exist for IMGMOUNT (only
        # for MOUNT's folder mounts), so it's omitted for the image case
        # either way - the image's own embedded volume label is used
        # instead.
        iso_path = config.resolve_path(program.cdrom_iso_path)
        return f'imgmount e "{iso_path}" -t iso{ide_flag}\n'
    if program.cdrom_folder_path:
        # -ide deliberately NOT applied here even when boots_away: the same
        # type=="iso" gate above means a folder mounted "-t cdrom" (type
        # CdRomImage via the "cdrom" string, not the image-mount codepath
        # MountImageIso() that actually performs the attach) is unconfirmed
        # to support IDE attachment at all - safer to leave it as a normal
        # letter mount than claim -ide support that hasn't been verified.
        folder_path = config.resolve_path(program.cdrom_folder_path)
        return f'mount e "{folder_path}" -t cdrom -label {_cdrom_label(program.name)}\n'
    return ""


def dos_short_path(root: Path, rel_path: str) -> str:
    """Converts a long relative path (as stored in a zip/rar, "/"- or
    "\\"-separated) into the DOS 8.3 short-name path DOSBox will actually
    expose once `root` is mounted as a drive - backslash-separated, ready
    to drop into an autoexec `cd`/run line."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    current_dir = root
    short_parts = []
    for part in parts:
        siblings = [p.name for p in current_dir.iterdir()] if current_dir.is_dir() else [part]
        short_parts.append(_dos_short_component(part, siblings))
        current_dir = current_dir / part
    return "\\".join(short_parts)


def dir_for_archive(archive_path: str) -> Path:
    # Extracted next to the archive (not into a hidden app cache) so a DOS
    # installer's/patcher's output survives independently of this app
    # entirely, and so the user can find/manage it directly in their file
    # manager. `archive_path` must already be resolved to an absolute path.
    p = Path(archive_path)
    return p.parent / p.stem


def _extract_rar(archive_path: str, dest_dir: Path) -> None:
    for name, build_command in _RAR_EXTRACTORS:
        if shutil.which(name) is None:
            continue
        result = subprocess.run(build_command(archive_path, str(dest_dir)), capture_output=True, text=True)
        if result.returncode != 0:
            raise ExtractionError(result.stderr.strip() or result.stdout.strip())
        return
    raise ExtractionError(
        "Kein RAR-Entpacker gefunden. Bitte 'unrar', '7z'/'7zz' (p7zip) oder 'unar' installieren."
    )


def _extract_zip(archive_path: str, dest_dir: Path) -> None:
    # Many old DOS-era zips use legacy compression (Shrink/Implode) that
    # Python's zipfile module can't decode. The `unzip` CLI (Info-ZIP) has
    # always supported those, so shell out to it instead.
    result = subprocess.run(
        ["unzip", "-o", "-q", archive_path, "-d", str(dest_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode > 1:  # 0 = ok, 1 = warning only, >=2 = real error
        raise ExtractionError(result.stderr.strip() or result.stdout.strip())


def ensure_extracted_archive(archive_path: str) -> Path:
    # `archive_path` must already be resolved to an absolute path.
    extract_dir = dir_for_archive(archive_path)
    if extract_dir.exists() and any(extract_dir.iterdir()):
        return extract_dir

    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        if archive_path.lower().endswith(".rar"):
            _extract_rar(archive_path, extract_dir)
        else:
            _extract_zip(archive_path, extract_dir)
    except ExtractionError:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise
    return extract_dir


def program_dir_for(config: AppConfig, program: Program) -> Path:
    return dir_for_archive(config.resolve_path(program.zip_path))


def ensure_extracted(config: AppConfig, program: Program) -> Path:
    return ensure_extracted_archive(config.resolve_path(program.zip_path))


def _resolve_cd_and_run(folder: Path | None, program: Program) -> tuple[str, str]:
    """cd_line + run_target for program.executable (+ executable_args),
    using real DOS 8.3 short names when a real folder is given to inspect
    (the actual mounted drive's content on disk), else falling back to the
    long name as-is - e.g. DOSBox-X's direct zip-mount case, or an
    ISO-based CD-ROM E: drive whose contents can't be inspected locally
    without mounting it."""
    if folder is not None:
        short_path = dos_short_path(folder, program.executable)
        *short_dir_parts, short_filename = short_path.split("\\")
        short_dir = "\\".join(short_dir_parts)
        cd_line = f"cd {short_dir}\n" if short_dir_parts else ""
        run_target = short_filename
    else:
        cd_line = f"cd {program.executable_dir}\n" if program.executable_dir else ""
        run_target = program.executable_name

    args = program.executable_args.strip()
    if args:
        run_target = f"{run_target} {args}"
    return cd_line, run_target


def _game_mounts(config: AppConfig, program: Program) -> tuple[str, str, dict[str, Path | None]]:
    """(mount_c_line, mount_d_line, {drive: real_folder_or_None}) for the
    original archive-based (ZIP/RAR) game mode."""
    variant = _effective_variant(config, program)
    resolved_zip = config.resolve_path(program.zip_path)

    # DOSBox-X can mount a .zip directly (PhysFS, read-only) - but not a
    # .rar (PhysFS has no rar support), and never once installed: the real
    # game then lives in the extracted folder, not the original archive.
    can_direct_mount = (
        variant == VARIANT_X and not program.installed and resolved_zip.lower().endswith(".zip")
    )
    mount_c = resolved_zip if can_direct_mount else ensure_extracted(config, program)
    mount_c_folder = None if can_direct_mount else mount_c

    mount_d_line = ""
    if program.update_zip_path:
        resolved_update = config.resolve_path(program.update_zip_path)
        can_direct_mount_d = (
            variant == VARIANT_X and not program.installed and resolved_update.lower().endswith(".zip")
        )
        mount_d = resolved_update if can_direct_mount_d else ensure_extracted_archive(resolved_update)
        mount_d_line = f'mount d "{mount_d}"\n'

    mount_c_line = f'mount c "{mount_c}"\n'
    return mount_c_line, mount_d_line, {BOOT_DRIVE_C: mount_c_folder}


def image_geometry(size_bytes: int) -> tuple[int, int, int]:
    # Matches DOSBox Staging's own IMGMAKE geometry-scaling table exactly
    # (src/dos/programs/makeimg.cpp, verified against the real source) -
    # heads scale up with size so cylinders stay within the classic
    # INT13h hard limit of 1023 (10-bit register field). Exceeding 1023
    # doesn't reject the mount, but silently corrupts BIOS-level disk
    # access (bios_disk.cpp packs cylinder into 10 bits on every real-mode
    # INT13h call) - exactly the scenario "-fs none" raw-disk mounts go
    # through (booting/installing a guest OS via BIOS calls, not DOSBox's
    # own DOS filesystem layer).
    sectors = 63
    heads = 16
    if size_bytes > 528_000_000:
        heads = 64
    if size_bytes > 1_000_000_000:
        heads = 128
    if size_bytes > 4_000_000_000:
        heads = 255
    cylinders = min(1023, max(1, (size_bytes // 512) // (heads * sectors)))
    return cylinders, heads, sectors


def _image_mount_line(config: AppConfig, program: Program, drive_number: int, image_path: str) -> str:
    # Mounted at the BIOS level (drive NUMBER + "-fs none"), not a drive
    # letter - a letter mount only gives DOSBox's own built-in DOS
    # file-level access to it, which a separately booted guest OS (e.g.
    # FreeDOS from a boot floppy, to run FDISK) can't see as a disk at
    # all. This is DOSBox Staging's own documented recipe for "bootable
    # disk images (real MS-DOS, Windows 9x, etc.)": dosbox-staging.org
    # /0.83/manual/using-dosbox-staging/storage/. Drive numbers: 0/1 are
    # floppies A:/B:, 2/3 are hard disks C:/D:.
    #
    # Geometry is always passed, not just for images that look "blank" -
    # confirmed via real DOSBox Staging behavior that a boot-sector-shaped
    # first sector (0x55AA signature + boot code, but no real partition
    # table yet) is NOT enough for DOSBox to auto-detect a usable geometry
    # on its own; DOSBox's own error for this is explicit: "Bei
    # Festplatten-Images muss die Laufwerksgeometrie angegeben werden."
    # Always computing it from the real file size is simpler and correct
    # in strictly more cases than trying to guess when it's "needed".
    variant = _effective_variant(config, program)
    path = Path(image_path)
    geometry = ""
    if path.is_file():
        cyl, heads, sectors = image_geometry(path.stat().st_size)
        if variant == VARIANT_STAGING:
            geometry = f" -chs {cyl},{heads},{sectors}"
        else:
            geometry = f" -size 512,{sectors},{heads},{cyl}"
    command = "mount" if variant == VARIANT_STAGING else "imgmount"
    # DOSBox-X's numbered-drive IMGMOUNT implicitly assigns an IDE slot from
    # the drive number itself when no "-ide" is given (dos_programs.cpp:
    # `ide_index = (tdr-'2')/2; ide_slave = (tdr-'2')&1`) - drive 2 (C:)
    # becomes primary MASTER, but drive 3 (D:) would default to primary
    # SLAVE, the SAME IDE cable as C:. Force D: onto "1s" explicitly
    # instead (primary slave - same channel as C:, just made explicit
    # rather than relying on the implicit default) - only needed for drive
    # 3 on DOSBox-X; Staging's own -fs none HDDs never touch its IDE
    # subsystem at all (confirmed separately), and drive 2 alone is
    # already fine as the implicit primary master.
    #
    # "2m" (secondary master) is deliberately reserved for the CD-ROM
    # instead (see _mount_e_line, which always uses "2m" now, unlike D:
    # here) - confirmed via real hardware testing that OAKCDROM.SYS/MSCDEX
    # (running under a genuinely booted guest) reliably finds a CD-ROM
    # attached at "2m" but reported "No drives found" when it had been
    # attached at "1s" instead (with D: then on "2m") - a real DOSBox-X
    # IDE-emulation quirk specific to which slot the CD-ROM ends up on,
    # not to D: at all. D: itself has never shown a similar detection
    # failure on "1s", so this split (D:→1s, CD-ROM→2m, never the other
    # way around) is deliberate, not arbitrary.
    ide_flag = " -ide 1s" if variant == VARIANT_X and drive_number == 3 else ""
    return f'{command} {drive_number} "{image_path}" -t hdd -fs none{geometry}{ide_flag}\n'


def _windows_mounts(config: AppConfig, program: Program) -> tuple[str, str, dict[str, Path | None]]:
    """(mount_c_line, mount_d_line, {drive: real_folder_or_None}) for a
    Windows/OS2 install. C:/D: are each either a real folder (nothing
    extracted - a brand-new C: folder is auto-created as an empty "virtual
    hard disk") or a raw disk image file (mounted as a whole - its
    contents can't be inspected locally, so short-name resolution falls
    back to the raw executable path if that drive ends up being the boot
    target)."""
    if program.windows_c_mode == "image":
        image_path = config.resolve_path(program.windows_c_image_path)
        if not Path(image_path).is_file():
            raise ExtractionError(f"Image-Datei für Laufwerk C: nicht gefunden:\n{image_path}")
        mount_c_line = _image_mount_line(config, program, 2, image_path)
        mount_c_folder = None
    else:
        mount_c = Path(config.resolve_path(program.windows_c_folder))
        mount_c.mkdir(parents=True, exist_ok=True)
        mount_c_line = f'mount c "{mount_c}"\n'
        mount_c_folder = mount_c

    mount_d_line = ""
    mount_d_folder = None
    if program.windows_d_mode == "image":
        if program.windows_d_image_path:
            image_path = config.resolve_path(program.windows_d_image_path)
            if not Path(image_path).is_file():
                raise ExtractionError(f"Image-Datei für Laufwerk D: nicht gefunden:\n{image_path}")
            mount_d_line = _image_mount_line(config, program, 3, image_path)
    elif program.windows_d_folder:
        mount_d = Path(config.resolve_path(program.windows_d_folder))
        if not mount_d.is_dir():
            raise ExtractionError(f"Setup-Ordner (Laufwerk D:) nicht gefunden:\n{mount_d}")
        mount_d_line = f'mount d "{mount_d}"\n'
        mount_d_folder = mount_d

    return mount_c_line, mount_d_line, {BOOT_DRIVE_C: mount_c_folder, BOOT_DRIVE_D: mount_d_folder}


def _floppy_mount_lines(config: AppConfig, program: Program) -> str:
    # BOOT opens the floppy image file(s) itself and populates DOSBox's
    # internal imageDiskList directly - it does NOT need (or want) a prior
    # MOUNT of the same image. Verified directly from DOSBox Staging's own
    # source (src/dos/programs/boot.cpp): BOOT's very first check is
    # `if (imageDiskList[0] || imageDiskList[1]) { WriteOut("Floppy
    # image(s) already mounted."); return; }` - so if `mount a/b ... -t
    # floppy` (which also sets imageDiskList[0]/[1], since Staging's MOUNT
    # absorbed IMGMOUNT's job) runs first, BOOT silently no-ops right
    # there. No error dialog, no crash - DOSBox just falls through to
    # whatever runs after the boot line, still on its own internal DOS.
    # That exactly matches the symptom of `ver` reporting DOSBox's built-in
    # DOS 6.22 instead of the floppy's real OS after a "successful" boot.
    # So mounting A:/B: and BOOT-ing them are mutually exclusive: skip the
    # MOUNT lines entirely whenever boot_floppy is set and let BOOT do it.
    if program.boot_floppy:
        return ""
    # DOSBox-X's MOUNT command refuses a bare image FILE outright (it only
    # ever treats its argument as a real directory/PhysFS archive) -
    # confirmed by its own real error text, seen directly in a real
    # DOSBox-X session: "Failed to mount the PhysFS drive with the archive
    # file. To mount image files, use the IMGMOUNT command, not the MOUNT
    # command." - the same MOUNT-vs-IMGMOUNT split already handled for
    # CD-ROM/HDD images elsewhere in this file, just never applied here
    # before. Staging's MOUNT, by contrast, already handles floppy image
    # files directly (this is the same "-t floppy" form documented and
    # tested working there all session), so only DOSBox-X needs the
    # IMGMOUNT form.
    command = "mount" if _effective_variant(config, program) == VARIANT_STAGING else "imgmount"
    lines = ""
    if program.floppy_a_path:
        lines += f'{command} a "{config.resolve_path(program.floppy_a_path)}" -t floppy\n'
    if program.floppy_b_path:
        lines += f'{command} b "{config.resolve_path(program.floppy_b_path)}" -t floppy\n'
    return lines


def generate_autoexec_conf(config: AppConfig, program: Program) -> str:
    """Computes the DOSBox autoexec conf text for `program` from the
    current settings (mounts, CPU/GFX/Sound, autoexec) - always freshly
    generated, ignoring any saved per-game `custom_conf` override. Used by
    build_autoexec_conf() as the default, and by the "Automatisch
    generieren" action in the config-editor dialog to get back to it."""
    if program.install_mode == INSTALL_MODE_WINDOWS:
        mount_c_line, mount_d_line, drive_folders = _windows_mounts(config, program)
        boot_drive = program.boot_drive
        d_has_content = (
            program.windows_d_image_path if program.windows_d_mode == "image" else program.windows_d_folder
        )
        if boot_drive == BOOT_DRIVE_D and not d_has_content:
            raise ExtractionError("Boot-Laufwerk ist D:, aber weder Ordner noch Image für D: angegeben.")
        if boot_drive == BOOT_DRIVE_E and not program.needs_cdrom:
            raise ExtractionError("Boot-Laufwerk ist E:, aber CD-ROM-Laufwerk (E:) ist nicht aktiviert.")
    else:
        mount_c_line, mount_d_line, drive_folders = _game_mounts(config, program)
        boot_drive = BOOT_DRIVE_C  # game mode always boots C:, regardless of any saved boot_drive

    boots_raw_image = program.install_mode == INSTALL_MODE_WINDOWS and (
        (boot_drive == BOOT_DRIVE_C and program.windows_c_mode == "image")
        or (boot_drive == BOOT_DRIVE_D and program.windows_d_mode == "image")
    )
    boots_away = bool(program.boot_floppy) or boots_raw_image

    mount_e_line = _mount_e_line(config, program, boots_away=boots_away)
    if program.needs_cdrom and program.cdrom_folder_path:
        drive_folders[BOOT_DRIVE_E] = Path(config.resolve_path(program.cdrom_folder_path))

    mount_floppy_lines = _floppy_mount_lines(config, program)

    if program.boot_floppy:
        # BOOT works directly on the image file (dosbox.com/wiki/BOOT,
        # still true per the current Staging manual for the simple floppy
        # case) - replaces the normal drive-switch/cd/run flow entirely,
        # since BOOT never returns to DOS (nothing after it would run).
        #
        # Both floppy images are passed to the SAME boot command (not just
        # the selected one) when both are configured - a real multi-disk
        # FreeDOS/DOS boot set commonly needs a second disk part-way
        # through its own boot process (loaded via the classic Ctrl+F4
        # disk-swap DOSBox supports for BOOT's own multi-image argument
        # list). Passing only one image means that swap has nothing to
        # swap to, and the boot silently stalls/half-completes - looks
        # like it booted (a prompt appears) but core parts never loaded.
        selected_path = program.floppy_a_path if program.boot_floppy == "a" else program.floppy_b_path
        if not selected_path:
            raise ExtractionError(
                f"Von Diskette {program.boot_floppy.upper()}: booten aktiviert, aber kein "
                f"Image für Laufwerk {program.boot_floppy.upper()}: angegeben."
            )
        other_path = program.floppy_b_path if program.boot_floppy == "a" else program.floppy_a_path
        boot_paths = [selected_path] + ([other_path] if other_path else [])
        boot_images = " ".join(f'"{config.resolve_path(p)}"' for p in boot_paths)
        boot_drive_line = f"boot {boot_images}\n"
        cd_line, run_line = "", ""
    elif boots_raw_image:
        # C:/D: mounted as a raw disk image (drive number + "-fs none",
        # see _image_mount_line) has no DOS drive letter to switch into -
        # DOSBox's own built-in DOS never gets filesystem access to it.
        # Once it holds an installed, bootable OS (Windows 95, real
        # MS-DOS, ...), the way to actually start it is BOOT -l <letter>,
        # same as the floppy case, and for the same reason (never returns).
        boot_drive_line = f"boot -l {boot_drive}\n"
        cd_line, run_line = "", ""
    else:
        cd_line, run_target = _resolve_cd_and_run(drive_folders.get(boot_drive), program)
        run_line = run_target if program.auto_start else ""
        boot_drive_line = f"{boot_drive}:\n"

    global_autoexec = config.global_autoexec.strip()
    global_autoexec_lines = f"{global_autoexec}\n" if global_autoexec else ""

    eff = _effective_dosbox_config(config, program)
    variant = _effective_variant(config, program)

    sdl_lines = _sdl_lines(variant, program.display_mode, eff.gfx_output)

    return _AUTOEXEC_TEMPLATE.format(
        hw_sections=_hw_config_sections(variant, eff),
        sdl_lines=sdl_lines,
        mount_c_line=mount_c_line,
        mount_d_line=mount_d_line,
        mount_e_line=mount_e_line,
        mount_floppy_lines=mount_floppy_lines,
        boot_drive_line=boot_drive_line,
        global_autoexec_lines=global_autoexec_lines,
        cd_line=cd_line,
        run_line=run_line,
    )


def build_autoexec_conf(config: AppConfig, program: Program) -> Path:
    # generate_autoexec_conf() is called unconditionally (even when a
    # custom_conf override exists) since it also performs the actual
    # archive extraction as a side effect - the override's own mount lines
    # are expected to reference that same extracted folder.
    generated = generate_autoexec_conf(config, program)
    content = program.custom_conf if program.custom_conf.strip() else generated
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _LAUNCH_CONF_PATH.write_text(content)
    return _LAUNCH_CONF_PATH


def launch_program(config: AppConfig, program: Program) -> subprocess.Popen:
    conf_path = build_autoexec_conf(config, program)
    command = shlex.split(dosbox_command_for(config, program)) + ["-conf", str(conf_path)]
    return subprocess.Popen(command)


# Floppy sizes this app offers a "Diskette erstellen" UI for - kept to just
# the two everyday ones (DD/HD) rather than every size either variant's
# create-image command supports.
FLOPPY_SIZE_720 = 720
FLOPPY_SIZE_1440 = 1440

# DOSBox Staging renamed the classic IMGMAKE command to MAKEIMG and uses
# "fd_720kb"/"fd_1440kb" as -t type names - confirmed from its own source,
# src/dos/programs/makeimg.cpp. DOSBox-X kept the original IMGMAKE name and
# "fd_720"/"fd_1440" type names (no "kb" suffix) - confirmed from its own
# wiki (Guide:Managing image files in DOSBox-X). These are two genuinely
# different commands with different type-name spelling, not just an alias
# like MOUNT/IMGMOUNT are on Staging - see [[feedback_dosbox_check_both_variants_together]].
_FLOPPY_TYPE_STAGING = {FLOPPY_SIZE_720: "fd_720kb", FLOPPY_SIZE_1440: "fd_1440kb"}
_FLOPPY_TYPE_X = {FLOPPY_SIZE_720: "fd_720", FLOPPY_SIZE_1440: "fd_1440"}

_MAKE_FLOPPY_CONF_PATH = CONFIG_DIR / "make_floppy.conf"


class FloppyCreationError(RuntimeError):
    pass


def create_floppy_image(config: AppConfig, variant: str, dest_path: str, size_kb: int) -> None:
    """Creates a new, blank, formatted floppy image (720KB or 1.44MB) at
    dest_path. Neither DOSBox variant's create-image command can be run
    from the host shell - IMGMAKE/MAKEIMG only exist inside the emulator's
    own DOS environment - so this launches DOSBox for a one-shot
    MOUNT + cd + create-image + EXIT run and waits for it to finish.
    The destination's own folder is mounted (rather than passing a host
    path straight to IMGMAKE/MAKEIMG, which only accept a DOS-side
    filename) so the resulting file lands exactly where the user picked."""
    dest = Path(dest_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Delete any pre-existing file first rather than relying on a -force
    # flag, since it sidesteps having to verify that flag behaves
    # identically (or exists at all) on both variants.
    if dest.is_file():
        dest.unlink()

    if variant == VARIANT_X:
        command_name, type_name = "IMGMAKE", _FLOPPY_TYPE_X[size_kb]
    else:
        command_name, type_name = "MAKEIMG", _FLOPPY_TYPE_STAGING[size_kb]

    conf = (
        "[autoexec]\n"
        f'MOUNT Y "{dest.parent}"\n'
        "Y:\n"
        f'{command_name} "{dest.name}" -t {type_name}\n'
        "EXIT\n"
    )
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _MAKE_FLOPPY_CONF_PATH.write_text(conf)

    dosbox_command = config.dosbox_command_x if variant == VARIANT_X else config.dosbox_command_staging
    command = shlex.split(dosbox_command) + ["-conf", str(_MAKE_FLOPPY_CONF_PATH)]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL
        )
    except subprocess.TimeoutExpired as e:
        raise FloppyCreationError(
            f"„{' '.join(command)}“ hat nach 60s nicht reagiert (abgebrochen)."
        ) from e

    if not dest.is_file():
        output = "\n".join(filter(None, (result.stdout, result.stderr))).strip()
        raise FloppyCreationError(
            f"Diskettenimage wurde nicht erstellt: {dest}\n\nAusgabe:\n{output or '(leer)'}"
        )


def dosbox_primary_conf_path(config: AppConfig, program: Program | None = None) -> Path:
    """Resolves DOSBox's own primary config file (the one it manages
    itself, layered underneath our per-launch -conf file - where settings
    not covered by this app's own UI can be edited directly and actually
    persist). Asked from the real installed binary via --printconf/
    -printconf rather than guessed: Flatpak remaps XDG_CONFIG_HOME to
    ~/.var/app/<app-id>/config/..., and DOSBox-X's filename is version-
    suffixed (dosbox-x-<version>.conf) - both make a hardcoded path
    fragile. See dosbox-staging.org/0.83/manual/using-dosbox-staging/
    command-line/ and the DOSBox-X wiki's Command-Line Options page.
    `program`, when given, resolves against its own variant override (so
    the button in a game's own Edit dialog shows the config file for the
    emulator that game actually launches with) - omitted/None falls back
    to the app-wide default variant."""
    variant = _effective_variant(config, program) if program is not None else config.dosbox_variant
    flag = "-printconf" if variant == VARIANT_X else "--printconf"
    command = shlex.split(dosbox_command_for(config, program)) + [flag]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    output = "\n".join(filter(None, (result.stdout, result.stderr)))
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(
            f"„{' '.join(command)}“ hat keinen Pfad ausgegeben.\nAusgabe: {output.strip() or '(leer)'}"
        )
    # The flag's own docs promise just the path, but be defensive about any
    # banner/version text some builds might print before it.
    return Path(lines[-1])


def cleanup_extracted(config: AppConfig, programs: list[Program]) -> None:
    # Installed programs keep their extracted folder(s) forever (they hold
    # the actual installed game / savegames); everything else is disposable
    # and gets re-extracted from its archive on next launch anyway.
    for program in programs:
        if program.install_mode == INSTALL_MODE_WINDOWS:
            # C:/D: are the user's own picked folders, never derived from an
            # archive - there's nothing here that's safe to delete.
            continue
        if program.installed:
            continue
        shutil.rmtree(program_dir_for(config, program), ignore_errors=True)
        if program.update_zip_path:
            shutil.rmtree(dir_for_archive(config.resolve_path(program.update_zip_path)), ignore_errors=True)
