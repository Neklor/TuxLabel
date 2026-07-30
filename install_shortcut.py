#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Erstellt eine Desktop-Verknüpfung und einen Anwendungsmenü-Eintrag
für TuxLabel.

Verwendung:
    python3 install_shortcut.py
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Pfade ermitteln
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
MAIN_PY    = SCRIPT_DIR / "main.py"
PYTHON     = sys.executable          # z. B. /usr/bin/python3

# Name des Icons im hicolor-Theme (ohne Endung). Die PNG-Dateien dazu schreibt
# _install_icons() unten; das Icon selbst wird in tuxlabel/icons.py gezeichnet.
ICON_NAME  = "tuxlabel"

# Muss EXAKT der WM_CLASS des laufenden Fensters entsprechen, sonst ordnet die
# Fensterleiste das Fenster nicht dem Menüeintrag zu und zeigt es ohne Symbol
# als eigenen Eintrag. Qt setzt die Klasse aus QApplication.applicationName(),
# also »TuxLabel« — Groß-/Kleinschreibung zählt (geprüft mit
# `xprop WM_CLASS`: "main.py", "TuxLabel").
WM_CLASS = "TuxLabel"

DESKTOP_ENTRY = f"""\
[Desktop Entry]
Version=1.0
Type=Application
Name=TuxLabel
Comment=Etiketten-Editor für Brother P-Touch Drucker
Exec={PYTHON} "{MAIN_PY}"
Icon={ICON_NAME}
Terminal=false
Categories=Office;Printing;
Keywords=label;etikett;brother;p-touch;ptouch;tze;drucken;print;
StartupWMClass={WM_CLASS}
"""

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _write_desktop_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DESKTOP_ENTRY, encoding="utf-8")
    # Ausführbar machen (notwendig für .desktop-Dateien auf dem Desktop)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _trust_desktop_file(path: Path) -> None:
    """Datei in Cinnamon / GNOME als vertrauenswürdig markieren."""
    for tool in ("gio", "gvfs-set-attribute"):
        try:
            subprocess.run(
                [tool, "set", str(path), "metadata::trusted", "true"],
                capture_output=True, timeout=5,
            )
            return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue


def _install_icons() -> list[Path]:
    """Schreibt das Programmsymbol als PNG in das hicolor-Icon-Theme.

    Das Icon wird in ``tuxlabel/icons.py`` gezeichnet, nicht als Datei
    mitgeliefert. Für die ``.desktop``-Datei braucht der Desktop es aber auf
    der Platte, also rendern wir es hier einmal in allen Standardgrößen.

    Gibt die geschriebenen Pfade zurück; eine leere Liste, wenn PyQt6 fehlt —
    das ist kein Grund, die Installation der Verknüpfung abzubrechen, der
    Eintrag erscheint dann lediglich ohne eigenes Symbol."""
    try:
        from tuxlabel.icons import APP_ICON_SIZES, app_icon_image
    except ImportError:
        return []

    base = Path.home() / ".local" / "share" / "icons" / "hicolor"
    written: list[Path] = []
    for size in APP_ICON_SIZES:
        target_dir = base / f"{size}x{size}" / "apps"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{ICON_NAME}.png"
        if app_icon_image(size).save(str(target)):
            written.append(target)

    # Icon-Cache erneuern, damit das neue Symbol ohne Neuanmeldung erscheint.
    # Fehlt das Werkzeug, findet der Desktop das Icon spätestens beim nächsten
    # Start — deshalb nur ein Versuch ohne Fehlerbehandlung nach außen.
    try:
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-t", str(base)],
            capture_output=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return written


def _find_desktop_dir() -> Path | None:
    """Gibt den Desktop-Ordner zurück (per xdg-user-dir, Fallback EN/DE)."""
    try:
        result = subprocess.run(
            ["xdg-user-dir", "DESKTOP"],
            capture_output=True, text=True, timeout=5,
        )
        xdg_path = Path(result.stdout.strip())
        if xdg_path.is_dir() and xdg_path != Path.home():
            return xdg_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    for name in ("Schreibtisch", "Desktop"):
        d = Path.home() / name
        if d.is_dir():
            return d
    return None


# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def main() -> None:
    print("TuxLabel – Verknüpfung installieren")
    print("=" * 45)

    if not MAIN_PY.exists():
        print(f"FEHLER: main.py nicht gefunden unter:\n  {MAIN_PY}")
        sys.exit(1)

    created: list[str] = []
    errors:  list[str] = []

    # 1. Programmsymbol — muss VOR den .desktop-Dateien geschrieben werden,
    #    damit deren »Icon=tuxlabel« beim Aktualisieren schon etwas findet.
    icons = _install_icons()
    if icons:
        sizes = ", ".join(f"{p.parent.parent.name}" for p in icons)
        created.append(f"  Symbol:         {icons[-1].parent.parent.parent}"
                       f"\n                  Größen: {sizes}")
    else:
        errors.append("  Symbol:         PyQt6 nicht gefunden — Eintrag bleibt "
                      "ohne eigenes Icon")

    # 2. Anwendungsmenü (~/.local/share/applications/)
    apps_dir     = Path.home() / ".local" / "share" / "applications"
    menu_desktop = apps_dir / "tuxlabel.desktop"
    try:
        _write_desktop_file(menu_desktop)
        subprocess.run(
            ["update-desktop-database", str(apps_dir)],
            capture_output=True, timeout=10,
        )
        created.append(f"  Anwendungsmenü: {menu_desktop}")
    except OSError as exc:
        errors.append(f"  Anwendungsmenü: {exc}")

    # 3. Desktop-Verknüpfung
    desktop_dir = _find_desktop_dir()
    if desktop_dir:
        desktop_link = desktop_dir / "TuxLabel.desktop"
        try:
            _write_desktop_file(desktop_link)
            _trust_desktop_file(desktop_link)
            created.append(f"  Desktop:        {desktop_link}")
        except OSError as exc:
            errors.append(f"  Desktop:        {exc}")
    else:
        errors.append("  Desktop:        Ordner nicht gefunden (Desktop/Schreibtisch)")

    # Ausgabe
    if created:
        print("\nErfolgreich erstellt:")
        for line in created:
            print(line)

    if errors:
        print("\nFehler (nicht kritisch):")
        for line in errors:
            print(line)

    print(
        "\nFertig!  Beim nächsten Start sollte TuxLabel im\n"
        "Anwendungsmenü erscheinen.  Auf dem Desktop ggf. per\n"
        "Rechtsklick → 'Ausführen erlauben' bestätigen."
    )


if __name__ == "__main__":
    main()
