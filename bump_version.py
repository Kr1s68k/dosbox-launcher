#!/usr/bin/env python3
"""Bumps app/version.py's APP_VERSION by 0.01 and refreshes BUILD_NUMBER/
BUILD_DATE. Run automatically by build_linux.sh before every build, so the
About dialog always shows a fresh, distinguishable build - per explicit
request: the app stays labelled Beta (see RELEASE_STAGE in version.py,
not touched here - that's a manual decision) until every bug has been
found and fixed."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent / "app" / "version.py"


def _bump_app_version(current: str) -> str:
    return f"{float(current) + 0.01:.2f}"


def _bump_build_number(current: str, today_compact: str) -> str:
    date_part, _, suffix = current.partition(".")
    if date_part == today_compact:
        return f"{today_compact}.{int(suffix or 0) + 1}"
    return f"{today_compact}.1"


def main() -> None:
    text = VERSION_FILE.read_text()

    app_version = re.search(r'APP_VERSION = "([^"]+)"', text).group(1)
    build_number = re.search(r'BUILD_NUMBER = "([^"]+)"', text).group(1)

    today_compact = date.today().strftime("%Y%m%d")
    today_display = date.today().strftime("%d.%m.%Y")

    new_app_version = _bump_app_version(app_version)
    new_build_number = _bump_build_number(build_number, today_compact)

    text = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{new_app_version}"', text)
    text = re.sub(r'BUILD_NUMBER = "[^"]+"', f'BUILD_NUMBER = "{new_build_number}"', text)
    text = re.sub(r'BUILD_DATE = "[^"]+"', f'BUILD_DATE = "{today_display}"', text)

    VERSION_FILE.write_text(text)
    print(f"[+] Version: {app_version} -> {new_app_version} (Build {new_build_number})")


if __name__ == "__main__":
    main()
