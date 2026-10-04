# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_all

datas = [('resources', 'resources'), ('example_data', 'example_data')]
binaries = []
hiddenimports = []

# evdev (joystick input) only exists on Linux - collect_all() would fail to
# even import it on Windows/macOS, where it's never installed at all (see
# requirements.txt's platform marker on evdev-binary). Guarded so the exact
# same Linux behavior as before (datas/binaries/hiddenimports pulled in from
# evdev) stays unchanged, while Windows/macOS builds simply skip it - the
# app's own joystick_input.py already handles evdev being absent gracefully.
if sys.platform == "linux":
    tmp_ret = collect_all('evdev')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Per-platform icon: Linux keeps the exact same PNG as before. Windows uses
# the generated .ico (resources/generate_windows_icon.py). macOS uses the
# .icns built from resources/AppIcon.iconset - iconutil only runs on a real
# Mac, so the GitHub Actions macOS job generates it right before this spec
# runs (see .github/workflows/build.yml).
if sys.platform == "win32":
    app_icon = ['resources/icon.ico']
elif sys.platform == "darwin":
    app_icon = ['resources/AppIcon.icns']
else:
    app_icon = ['resources/icon-256.png']


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='dosbox-launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon,
    contents_directory='.',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='dosbox-launcher',
)

# macOS only: wrap the portable folder into a proper .app bundle (Finder/
# Launchpad expect a double-clickable .app, not a bare folder). Linux and
# Windows keep exactly the plain COLLECT() folder output as before - nothing
# added or changed for them.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name='DOSBox Launcher.app',
        icon='resources/AppIcon.icns',
        bundle_identifier='de.cholzapfel.dosbox-launcher',
    )
