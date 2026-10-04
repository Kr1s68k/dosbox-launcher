"""Builds resources/demo.gif - a short animated tour of the app (game list,
edit dialog, built-in mini-game) for the README. Uses fictional placeholder
game entries/covers, never the developer's real library, since this ends up
committed to a public repo (same reasoning as example_data/'s placeholder
cover - no real/copyrighted game names or box art in anything public).

Must run with QT_QPA_PLATFORM=offscreen. On this particular sandboxed dev
machine, PySide6.QtMultimedia (imported transitively via app.starfield) also
needs a handful of system Kerberos libs that aren't present here - see
LD_LIBRARY_PATH in the project's own session notes. A normal Linux desktop
doesn't need that workaround at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtWidgets import QApplication

RESOURCES_DIR = Path(__file__).parent
PROJECT_DIR = RESOURCES_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

CANVAS = (900, 640)
BG_COLOR = (18, 22, 29)
FRAME_HOLD_MS = {
    "list_0": 1400,
    "list_1": 1100,
    "list_2": 1100,
    "edit": 2200,
    "minigame": 1800,
}

DEMO_GAMES = [
    # (name, rating, cover_color, cover_label)
    ("Star Raider", 10, (196, 60, 60), "STAR\nRAIDER"),
    ("Crystal Quest", 8, (60, 130, 196), "CRYSTAL\nQUEST"),
    ("Rally Masters", 6, (60, 170, 110), "RALLY\nMASTERS"),
    ("Dungeon Trek", 9, (196, 150, 50), "DUNGEON\nTREK"),
]


def make_cover(color: tuple, label: str) -> Image.Image:
    img = Image.new("RGB", (250, 250), color)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=26)
    lines = label.split("\n")
    total_h = len(lines) * 32
    y = (250 - total_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((250 - w) // 2, y), line, fill=(255, 255, 255), font=font)
        y += 32
    return img


def build_demo_config(scratch_dir: Path):
    import app.config as cfgmod
    import app.cover_art as cover_mod

    cfgmod.CONFIG_DIR = scratch_dir / "data"
    cfgmod.CONFIG_FILE = cfgmod.CONFIG_DIR / "programs.json"
    cfgmod._LEGACY_CONFIG_FILE = scratch_dir / "no_legacy.json"
    cfgmod._EXAMPLE_DATA_DIR = scratch_dir / "no_example_data"
    cover_mod.COVERS_DIR = cfgmod.CONFIG_DIR / "covers"
    cover_mod.COVERS_DIR.mkdir(parents=True, exist_ok=True)

    from app.config import AppConfig, Program
    from app.cover_art import cover_path_for

    programs = []
    for name, rating, color, label in DEMO_GAMES:
        zip_path = f"demo/{name.lower().replace(' ', '-')}.zip"
        prog = Program(
            name=name,
            zip_path=zip_path,
            executable="START.EXE",
            rating=rating,
            website_label="Info" if rating >= 9 else "",
            website_url="https://example.com" if rating >= 9 else "",
            notes="Demo-Eintrag." if rating == 8 else "",
        )
        programs.append(prog)
        make_cover(color, label).save(cover_path_for(prog.identity_path))

    config = AppConfig()
    config.programs = programs
    return config


_FRAME_TMP_COUNTER = [0]


def center_on_canvas(pix, scratch_dir: Path) -> Image.Image:
    _FRAME_TMP_COUNTER[0] += 1
    tmp_path = scratch_dir / f"_frame_tmp_{_FRAME_TMP_COUNTER[0]}.png"
    pix.toImage().save(str(tmp_path))
    frame = Image.open(tmp_path).convert("RGB")
    # The edit dialog is taller than the main window (935px vs. 640px) - scale
    # it DOWN to fit the shared canvas (preserving aspect ratio) rather than
    # cropping it, so every frame still shows its full content (incl. the
    # cover preview near the bottom of the dialog).
    scale = min(CANVAS[0] / frame.width, CANVAS[1] / frame.height, 1.0)
    if scale < 1.0:
        frame = frame.resize((int(frame.width * scale), int(frame.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", CANVAS, BG_COLOR)
    x = (CANVAS[0] - frame.width) // 2
    y = (CANVAS[1] - frame.height) // 2
    canvas.paste(frame, (max(0, x), max(0, y)))
    return canvas


def main() -> None:
    import tempfile

    scratch_dir = Path(tempfile.mkdtemp(prefix="dosbox_launcher_demo_gif_"))

    app = QApplication(sys.argv)

    config = build_demo_config(scratch_dir)

    import app.main_window as mw
    from app.starfield import _Asteroid, _make_asteroid_shape

    mw.load_config = lambda: config
    win = mw.MainWindow()
    win.resize(*CANVAS)
    win.show()

    frames: list[tuple[str, Image.Image]] = []

    for i in range(3):
        win.list_widget.setCurrentRow(i)
        frames.append((f"list_{i}", center_on_canvas(win.grab(), scratch_dir)))

    win.toggle_game_btn.setChecked(True)
    sw = win.starfield_widget
    sw._ship_x, sw._ship_y = 120, 420
    sw._asteroids = [
        _Asteroid(x=350, y=250, radius=26, hits=1, shape=_make_asteroid_shape(26)),
        _Asteroid(x=250, y=480, radius=22, hits=0, shape=_make_asteroid_shape(22)),
    ]
    sw._beams = [[sw._ship_x + 38, 300], [sw._ship_x + 38, 200]]
    frames.append(("minigame", center_on_canvas(win.grab(), scratch_dir)))
    win.toggle_game_btn.setChecked(False)

    from app.program_dialog import ProgramDialog

    dlg = ProgramDialog(config, program=config.programs[1])
    dlg.resize(640, dlg.sizeHint().height())
    dlg.show()
    frames.append(("edit", center_on_canvas(dlg.grab(), scratch_dir)))

    pil_frames = [f for _name, f in frames]
    durations = [FRAME_HOLD_MS[name] for name, _f in frames]

    dest = RESOURCES_DIR / "demo.gif"
    pil_frames[0].save(
        dest,
        save_all=True,
        append_images=pil_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Wrote {dest} ({len(pil_frames)} frames)")


if __name__ == "__main__":
    main()
