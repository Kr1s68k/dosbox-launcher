# DOSBox Launcher

Kleine GUI-Anwendung, um DOS-Programme aus ZIP-/RAR-Archiven per Doppelklick
über DOSBox Staging oder DOSBox-X zu starten.

## Funktionen

- Liste von Programmen verwalten (hinzufügen, bearbeiten, löschen, per ▲/▼ sortieren)
- Pro Programm: Name, Archiv-Datei (ZIP oder RAR) für Laufwerk C:, optional ein
  zweites Archiv für Laufwerk D: (z. B. Updates/Patches), auszuführendes
  Programm, Autostart an/aus
- Start per Doppelklick oder „Starten“-Button
- Archive werden einmalig neben die Archiv-Datei entpackt und von dort
  gemountet (DOSBox Staging kann weder ZIP noch RAR direkt mounten; DOSBox-X
  kann nur ZIP direkt mounten, RAR wird immer entpackt). Entpacken von ZIP
  läuft über `unzip` (auch ältere PKZIP-Kompressionen), RAR über `unrar`,
  `7z`/`7zz` oder `unar` (das erste gefundene Tool wird verwendet)
- „Installiertes Programm“: für Spiele, die per DOS-Setup installiert werden
  müssen – der entpackte Ordner bleibt dauerhaft erhalten statt beim Beenden
  aufgeräumt zu werden
- Automatische Cover-Art-Suche beim Hinzufügen/Bearbeiten, mit Vorschau und
  ◀/▶-Navigation durch mehrere Treffer
- Konfigurierbarer DOSBox-Staging-/DOSBox-X-Befehl (Standard:
  `flatpak run io.github.dosbox-staging` bzw. `flatpak run com.dosbox_x.DOSBox-X`)
- „Importieren…“: durchsucht einen gewählten Ordner rekursiv nach ZIP/RAR,
  schlägt Name + auszuführendes Programm pro Fund vor (abwählbar per
  Checkbox), in zwei Varianten: Dateien in den Spiele-Basisordner kopieren,
  oder nur verknüpfen (relativer Pfad, Dateien bleiben wo sie sind)

## Portabel

Die App legt ihre eigenen Daten (Einstellungen, Spieleliste, Cover-Cache)
unter `data/` **neben sich selbst** ab, nicht unter `~/.config`/`~/.local`.
Der komplette Programmordner kann also innerhalb des Home-Verzeichnisses
verschoben, umbenannt oder auf einen anderen Rechner (gleicher Benutzer)
kopiert werden und funktioniert weiter. Ältere Konfigurationen unter
`~/.config/dosbox-launcher/` werden beim ersten Start automatisch
übernommen (einmalig kopiert, Original bleibt erhalten).

Einschränkung: DOSBox Staging läuft bei den meisten Nutzern als Flatpak und
hat nur Zugriff auf das Home-Verzeichnis (`--filesystem=home`) - der
Programmordner (und die Spiele-Archive) müssen daher weiterhin irgendwo
unter `$HOME` liegen, nicht z. B. auf einem externen Laufwerk.

**Spiele-Basisordner** (Einstellungen → „Spiele-Basisordner“): Wird er
gesetzt, speichert der Programm-Dialog neu hinzugefügte Archive automatisch
als Pfad *relativ* dazu (statt als absoluten Pfad), sofern die Datei
innerhalb dieses Ordners liegt. Damit bleiben auch die Spiele-Pfade gültig,
wenn Programmordner + Spiele-Ordner zusammen verschoben werden. Archive
außerhalb des Basisordners funktionieren weiterhin über absolute Pfade.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

Für RAR-Unterstützung wird eines dieser Tools benötigt: `unrar`, `7z`/`7zz`
(p7zip) oder `unar`.

## Linux-Build (portabler Ordner)

```bash
./build_linux.sh
./install_linux.sh
```

Ergebnis liegt in `dist/dosbox-launcher/` – ein eigenständiger, portabler
Ordner (Python + PySide6 + Icons enthalten), kein `--onefile`-Exe mehr, da
sich der Programmordner selbst sonst nicht sinnvoll als fester Speicherort
für `data/` eignen würde. `install_linux.sh` kopiert **nichts** aus diesem
Ordner heraus, sondern trägt nur einen Menüeintrag ein, der auf den
aktuellen Speicherort zeigt. Wird der Ordner später verschoben,
`install_linux.sh` einfach erneut ausführen.

## Standalone-Builds für Linux, Windows und macOS (GitHub Actions)

PyInstaller kann nicht cross-kompilieren - ein `.exe` entsteht nur auf
Windows, ein `.app` nur auf einem echten Mac. `.github/workflows/build.yml`
löst das über GitHub Actions' kostenlose Runner (eine Build-Matrix aus
`ubuntu-latest`, `windows-latest`, `macos-latest`): jeder Runner baut sein
eigenes natives Paket über dieselbe `dosbox-launcher.spec`, die Ergebnisse
landen als herunterladbare Artefakte am jeweiligen Actions-Lauf - ganz ohne
eigene Windows-/Mac-Maschine.

Auslösen:

- **Manuell**: GitHub-Repo → Tab „Actions“ → „Build standalone packages“ →
  „Run workflow“
- **Automatisch**: einen Versions-Tag pushen, z. B.
  ```bash
  git tag v1.0.0
  git push origin v1.0.0
  ```

Nach dem Lauf liegen unter dem jeweiligen Workflow-Run drei Artefakte:
`dosbox-launcher-linux`, `dosbox-launcher-windows`, `dosbox-launcher-macos`
(jeweils als ZIP herunterladbar).

`dosbox-launcher.spec` wählt das Icon und ob ein evdev-Joystick-Backend
eingebunden wird automatisch je nach `sys.platform` (Linux bleibt dabei
exakt beim bisherigen Verhalten). Für macOS wird aus dem bereits
eingecheckten `resources/AppIcon.iconset/` (Apple-Squircle-Form mit
Schatten, alle 1x/2x-Größen) im Actions-Lauf selbst per `iconutil` die
`.icns`-Datei erzeugt - dieser Schritt funktioniert nur auf einem echten
Mac, weshalb er im `macos-latest`-Job und nicht lokal läuft. Das
Windows-Icon (`resources/icon.ico`) liegt dagegen schon fertig im Repo
(erzeugt mit `resources/generate_windows_icon.py`, reines Pillow, läuft auf
jedem Betriebssystem).

**Bekannte Einschränkungen:**

- Das macOS-`.app` ist unsigniert (kein Apple-Developer-Account, 99 $/Jahr) -
  macOS' Gatekeeper zeigt beim ersten Start „nicht verifizierter
  Entwickler“. Hilft: Rechtsklick → Öffnen (statt Doppelklick), oder
  `xattr -cr "DOSBox Launcher.app"` im Terminal.
- RAR-Unterstützung (`unrar`/`7z`/`unar`) muss der Nutzer unter Windows/macOS
  selbst installieren - die App sucht dynamisch in PATH, bündelt aber
  nichts davon mit.
- Die Standard-DOSBox-Befehle sind Bestmögliches, kein Garant: unter Windows/
  macOS wird der bloße Programmname (`dosbox-staging`/`dosbox-x`) als
  Default angenommen (PATH), unter Linux weiterhin der Flatpak-Aufruf - in
  Einstellungen jederzeit anpassbar, falls der tatsächliche Installationsort
  abweicht.
