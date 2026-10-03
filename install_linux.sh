#!/usr/bin/env bash
# Registers the already-built portable app folder (dist/dosbox-launcher/) in
# the current user's app menu (no root needed, nothing copied out of it -
# the portable folder stays wherever it is; move it later and re-run this
# script so the menu entry's path stays correct).
set -euo pipefail
cd "$(dirname "$0")"

BIN_SRC="dist/dosbox-launcher/dosbox-launcher"
if [ ! -f "$BIN_SRC" ]; then
    echo "Nicht gefunden: $BIN_SRC - erst ./build_linux.sh ausführen." >&2
    exit 1
fi
ABS_BIN_SRC="$(readlink -f "$BIN_SRC")"

ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$ICON_DIR" "$APPS_DIR"

install -m 644 "resources/icon-256.png" "$ICON_DIR/dosbox-launcher.png"

# Absolute Exec path rather than relying on PATH: desktop sessions (Plasma
# etc.) often run with a leaner PATH than an interactive shell.
cat > "$APPS_DIR/dosbox-launcher.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DOSBox Launcher
Comment=DOS-Programme aus ZIP-/RAR-Archiven per Doppelklick starten
Exec=$ABS_BIN_SRC
Icon=dosbox-launcher
Terminal=false
Categories=Game;Emulator;
EOF
chmod 644 "$APPS_DIR/dosbox-launcher.desktop"

update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installiert. Menüeintrag zeigt auf: $ABS_BIN_SRC"
echo "Portabel: Der Ordner 'dist/dosbox-launcher/' kann verschoben werden -"
echo "danach dieses Skript erneut ausführen, damit der Menüeintrag den neuen Pfad kennt."
