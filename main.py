#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""TuxLabel – Einstiegspunkt."""

import sys

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

# Nur die Versionsnummer — tuxlabel/__init__.py importiert bewusst kein PyQt,
# damit dieser Import vor dem Anlegen der QApplication unbedenklich ist.
from tuxlabel import __version__


def _migrate_settings() -> None:
    """Übernimmt Einstellungen, die unter dem früheren Namen der App
    (»PT-Label Editor«) gespeichert wurden, damit die Umbenennung nicht den
    Darkmode, die Standardschrift und die Liste der zuletzt geöffneten
    Dateien zurücksetzt. Läuft einmalig; abgesichert über einen Marker-Key."""
    current = QSettings()
    if current.value("_migrated_from_ptlabel", False, bool):
        return
    legacy = QSettings("PT-LabelEditor", "PT-Label Editor")
    for key in legacy.allKeys():
        if not current.contains(key):
            current.setValue(key, legacy.value(key))
    current.setValue("_migrated_from_ptlabel", True)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("TuxLabel")
    app.setOrganizationName("TuxLabel")
    app.setApplicationVersion(__version__)

    # Verknüpft das Fenster mit ~/.local/share/applications/tuxlabel.desktop.
    # Ohne das behandeln Fensterleiste und Dock das laufende Programm als
    # fremdes Fenster und zeigen es getrennt vom Menüeintrag an. Unter Wayland
    # ist das die einzige Zuordnung; unter X11 muss zusätzlich StartupWMClass
    # in der .desktop-Datei zur WM_CLASS passen (siehe install_shortcut.py).
    app.setDesktopFileName("tuxlabel")

    # Programmsymbol für Fenstertitel, Alt+Tab und Fensterleiste. Wird — wie
    # alle Symbole des Programms — zur Laufzeit gezeichnet, siehe icons.py.
    from tuxlabel.icons import make_app_icon
    app.setWindowIcon(make_app_icon())

    _migrate_settings()

    # Gespeicherte Sprache laden, bevor Fenster entstehen — alle Texte
    # werden beim Aufbau der Fenster über tuxlabel.i18n.tr() nachgeschlagen.
    from tuxlabel.i18n import init_from_settings, install_qt_translations
    init_from_settings()

    # Qts eigener Katalog für die Standardknöpfe (»Speichern«, »Abbrechen«, …).
    # Muss NACH init_from_settings() laufen — er richtet sich nach der dort
    # geladenen Sprache — und vor dem ersten Dialog.
    install_qt_translations(app)

    # Gespeichertes Design (Hell / Dunkel) anwenden, bevor Fenster entstehen.
    from tuxlabel.theme import apply_saved_theme
    apply_saved_theme(app)

    # Erster Start: falls das Betriebssystem nicht auf Deutsch steht, den
    # Wechsel auf die Systemsprache (oder ersatzweise Englisch) vorschlagen.
    # Muss VOR dem Hauptfenster laufen — dessen Texte entstehen beim Aufbau.
    from tuxlabel.i18n import maybe_offer_system_language
    maybe_offer_system_language()

    # Import NACH QApplication, damit label_canvas.py beim Laden des Moduls
    # die Bildschirm-DPI abfragen kann – für physikalisch korrekte
    # Schriftdarstellung (WYSIWYG).
    from tuxlabel.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
