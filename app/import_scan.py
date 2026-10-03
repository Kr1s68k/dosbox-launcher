"""Scans a folder tree for DOS-game archives and guesses a name/executable
for each one, for the bulk import dialog."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .program_dialog import find_runnables

ARCHIVE_SUFFIXES = (".zip", ".rar")


@dataclass
class ArchiveCandidate:
    path: Path
    guessed_name: str
    guessed_executable: str


def _guess_name(archive_path: Path) -> str:
    name = archive_path.stem
    name = name.replace("_", " ").replace("-", " ")
    while "  " in name:
        name = name.replace("  ", " ")
    return name.strip() or archive_path.stem


def _guess_executable(runnables: list[str]) -> str:
    if not runnables:
        return ""

    def score(path: str):
        name = Path(path).name.upper()
        base, _, ext = name.rpartition(".")
        ext_rank = {"EXE": 0, "BAT": 1, "COM": 2}.get(ext, 3)
        depth = path.replace("\\", "/").count("/")
        has_keyword = any(k in base for k in ("START", "RUN", "PLAY", "GAME"))
        return (0 if has_keyword else 1, depth, ext_rank, len(path))

    return min(runnables, key=score)


def scan_archives(folder: Path) -> list[ArchiveCandidate]:
    candidates = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ARCHIVE_SUFFIXES:
            continue
        runnables = find_runnables(str(path))
        candidates.append(
            ArchiveCandidate(
                path=path,
                guessed_name=_guess_name(path),
                guessed_executable=_guess_executable(runnables),
            )
        )
    return candidates
