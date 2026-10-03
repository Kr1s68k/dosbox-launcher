#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Kills every process whose command line matches $1, waiting up to 10s for
# it to actually exit before giving up (a still-running match otherwise
# just gets a warning, not a hard failure - the build continues either way).
kill_matching() {
    local pattern="$1"
    if pgrep -f "$pattern" > /dev/null 2>&1; then
        echo "Laufender Prozess gefunden ($pattern) - wird beendet..."
        pkill -f "$pattern" || true
        for _ in $(seq 1 20); do
            pgrep -f "$pattern" > /dev/null 2>&1 || break
            sleep 0.5
        done
        if pgrep -f "$pattern" > /dev/null 2>&1; then
            echo "Warnung: Prozess ($pattern) ließ sich nicht beenden, fahre trotzdem fort."
        fi
    fi
}

# A still-running launcher instance holds the old binary open and would keep
# writing to dist/dosbox-launcher/data/ while this script backs it up/
# rebuilds around it. Rather than killing it out from under the user (who
# might be mid-session with unsaved dialog state), just abort with a short
# hint - they close it themselves and re-run when ready.
if pgrep -f "$(pwd)/dist/dosbox-launcher/dosbox-launcher" > /dev/null 2>&1; then
    echo "Kann nicht bauen, Launcher noch geöffnet, bitte schließen und wiederholen."
    exit 1
fi

# Also kill any still-running DOSBox Staging/DOSBox-X instance. Both keep
# real process-level state alive for as long as they're actually running -
# confirmed for DOSBox-X specifically this session: MSCDEX's own drive
# registry (numDrives/dinfo[]) lives in file-scope static globals that are
# ONLY cleared on a genuine process exit, never by just closing/reopening a
# window that's secretly still the same backgrounded process, or by
# reloading a different autoexec - a stale CD-ROM registration from an
# earlier run can silently break the next one ("Drive-letters of multiple
# CD-ROM drives have to be continuous") with no indication the culprit is
# leftover state rather than the new config. Matches both variants' default
# Flatpak app IDs (dosbox_command_staging/dosbox_command_x in config.py) as
# well as common native binary names, so this still works if either was
# customized to a native install instead of Flatpak.
for pattern in "io.github.dosbox-staging" "com.dosbox_x.DOSBox-X" "dosbox-staging" "dosbox-x"; do
    kill_matching "$pattern"
done

# PyInstaller wipes dist/dosbox-launcher/ completely on every build. That
# folder also holds this app's own data/ (settings, game list, covers) once
# it's been run - back it up first and restore it after, so rebuilding
# never loses it.
DIST_DATA="dist/dosbox-launcher/data"
BACKUP_DIR=""
if [ -d "$DIST_DATA" ]; then
    BACKUP_DIR="$(mktemp -d)"
    mv "$DIST_DATA" "$BACKUP_DIR/data"
    echo "Bestehende App-Daten gesichert (werden nach dem Build wiederhergestellt)."
fi

.venv/bin/python3 bump_version.py

# Builds from dosbox-launcher.spec rather than passing these options
# directly on the command line: giving PyInstaller a .py script (instead of
# a .spec file) makes it silently REGENERATE dosbox-launcher.spec from
# scratch on every run, which would wipe out its per-platform icon/evdev
# logic (added for the Windows/macOS GitHub Actions builds) the next time
# this script runs. The .spec file's sys.platform == "linux" branch
# reproduces this exact CLI invocation, so the actual Linux build output is
# unchanged - only the maintenance risk is gone.
.venv/bin/pyinstaller --noconfirm dosbox-launcher.spec

if [ -n "$BACKUP_DIR" ]; then
    rm -rf "$DIST_DATA"
    mv "$BACKUP_DIR/data" "$DIST_DATA"
    rmdir "$BACKUP_DIR"
    echo "App-Daten wiederhergestellt."
fi

echo "Fertig: dist/dosbox-launcher/ (portabler Ordner - kann verschoben/kopiert werden)"
