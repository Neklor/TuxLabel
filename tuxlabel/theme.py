# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Programm-Design (Hell / Dunkel).

Der Darkmode betrifft nur die App-Oberfläche (Menü, Werkzeugleiste,
Dialoge, Statusleiste). Das Etikett auf der Zeichenfläche bleibt bewusst
weißes »Band« — es bildet das physische TZe-Band ab und darf sich nicht
mit dem Design ändern.

Umschalten geschieht über die Einstellungen; ``apply_theme`` wirkt sofort
auf alle geöffneten Fenster, weil Qt eine geänderte Anwendungspalette live
an alle Top-Level-Widgets weiterreicht.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

DARK_MODE_KEY = "dark_mode"

# Beim ersten Aufruf festgehalten, damit sich der native Hell-Look
# verlustfrei wiederherstellen lässt.
_default_palette: QPalette | None = None
_default_style_name: str | None = None


def _dark_palette() -> QPalette:
    text     = QColor("#E0E0E0")
    disabled = QColor("#7A7A7A")
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor("#2B2B2B"))
    p.setColor(QPalette.ColorRole.WindowText,      text)
    p.setColor(QPalette.ColorRole.Base,            QColor("#232323"))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor("#2F2F2F"))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor("#2B2B2B"))
    p.setColor(QPalette.ColorRole.ToolTipText,     text)
    p.setColor(QPalette.ColorRole.Text,            text)
    p.setColor(QPalette.ColorRole.Button,          QColor("#353535"))
    p.setColor(QPalette.ColorRole.ButtonText,      text)
    p.setColor(QPalette.ColorRole.BrightText,      QColor("#FF5555"))
    p.setColor(QPalette.ColorRole.Link,            QColor("#3D9BE0"))
    p.setColor(QPalette.ColorRole.Highlight,       QColor("#2A6BB3"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)

    for role in (QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    p.setColor(QPalette.ColorGroup.Disabled,
               QPalette.ColorRole.Highlight, QColor("#444444"))
    p.setColor(QPalette.ColorGroup.Disabled,
               QPalette.ColorRole.HighlightedText, disabled)
    return p


def apply_theme(app: QApplication, dark: bool) -> None:
    """Wendet Hell- oder Dunkel-Design auf die gesamte Anwendung an."""
    global _default_palette, _default_style_name
    if _default_palette is None:
        # Native Voreinstellung einmalig sichern.
        _default_palette = QPalette(app.palette())
        _default_style_name = app.style().objectName()

    if dark:
        # »Fusion« zeichnet die Palette plattformübergreifend zuverlässig.
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
    else:
        if _default_style_name:
            app.setStyle(_default_style_name)
        if _default_palette is not None:
            app.setPalette(_default_palette)


def apply_saved_theme(app: QApplication) -> None:
    """Liest den gespeicherten Darkmode-Schalter und wendet ihn an."""
    dark = QSettings().value(DARK_MODE_KEY, False, bool)
    apply_theme(app, dark)
