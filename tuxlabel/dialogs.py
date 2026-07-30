# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Zusätzliche Dialoge: Einstellungen, Über, Tastenkürzel, Hilfe."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .i18n import (
    LANGUAGE_KEY,
    LANGUAGE_PROMPT_KEY,
    available_languages,
    lang_dir_for_user,
    tr,
)
from .label_canvas import TAPE_WIDTHS
from .theme import DARK_MODE_KEY, apply_theme


_FONT_SIZES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 48, 72]


class SettingsDialog(QDialog):
    """Programm-Einstellungen: Voreinstellungen + Darstellung + Sprache.

    Liest/schreibt dieselben QSettings-Schlüssel, die auch der
    »Standard«-Knopf in der Werkzeugleiste setzt — die beiden Wege bleiben
    damit konsistent. Der Reset-zu-Werksstandard ist hier eingebettet."""

    # Werkseinstellungen, die der »Auf Werksstandard zurücksetzen«-Knopf anwendet
    FACTORY = {
        "tape_width":     "12mm",
        "font_family":    "Noto Serif",
        "font_size":      12,
        "font_bold":      False,
        "font_italic":    False,
        "font_underline": False,
        "font_strikeout": False,
        "flag_print_middle_line": True,
        DARK_MODE_KEY:    False,
        LANGUAGE_KEY:     "de",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumWidth(460)

        # Merkt sich, ob »Auf Werksstandard zurücksetzen« gedrückt wurde —
        # wird erst beim OK wirksam (Abbrechen verwirft auch das).
        self._factory_reset_requested = False

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        layout.addWidget(tabs)
        tabs.addTab(self._defaults_tab(), tr("settings.tab_defaults"))
        tabs.addTab(self._appearance_tab(), tr("settings.tab_appearance"))
        tabs.addTab(self._language_tab(), tr("settings.tab_language"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.RestoreDefaults,
        )
        reset_btn = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        reset_btn.setText(tr("settings.reset_button"))
        reset_btn.clicked.connect(self._reset_to_factory)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _defaults_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        s = QSettings()

        self._tape_combo = QComboBox()
        for label in TAPE_WIDTHS:
            self._tape_combo.addItem(label)
        current_tape = s.value("tape_width", self.FACTORY["tape_width"])
        if current_tape in TAPE_WIDTHS:
            self._tape_combo.setCurrentText(current_tape)
        form.addRow(tr("settings.default_tape"), self._tape_combo)

        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(
            QFont(s.value("font_family", self.FACTORY["font_family"]))
        )
        form.addRow(tr("settings.default_font"), self._font_combo)

        self._size_combo = QComboBox()
        for pt in _FONT_SIZES:
            self._size_combo.addItem(f"{pt} pt", pt)
        self._set_size_combo(s.value("font_size", self.FACTORY["font_size"], int))
        form.addRow(tr("settings.default_size"), self._size_combo)

        # --- Kontrollkästchen für Schriftstil ---
        fmt_widget = QWidget()
        fmt_row = QHBoxLayout(fmt_widget)
        fmt_row.setContentsMargins(0, 0, 0, 0)
        fmt_row.setSpacing(12)

        self._cb_bold = QCheckBox(tr("settings.bold"))
        bf = self._cb_bold.font(); bf.setBold(True); self._cb_bold.setFont(bf)
        self._cb_bold.setChecked(s.value("font_bold", self.FACTORY["font_bold"], bool))
        fmt_row.addWidget(self._cb_bold)

        self._cb_italic = QCheckBox(tr("settings.italic"))
        itf = self._cb_italic.font(); itf.setItalic(True); self._cb_italic.setFont(itf)
        self._cb_italic.setChecked(s.value("font_italic", self.FACTORY["font_italic"], bool))
        fmt_row.addWidget(self._cb_italic)

        self._cb_underline = QCheckBox(tr("settings.underline"))
        self._cb_underline.setStyleSheet("QCheckBox { text-decoration: underline; }")
        self._cb_underline.setChecked(
            s.value("font_underline", self.FACTORY["font_underline"], bool)
        )
        fmt_row.addWidget(self._cb_underline)

        self._cb_strikeout = QCheckBox(tr("settings.strikeout"))
        self._cb_strikeout.setChecked(
            s.value("font_strikeout", self.FACTORY["font_strikeout"], bool)
        )
        fmt_row.addWidget(self._cb_strikeout)
        fmt_row.addStretch(1)
        form.addRow(tr("settings.default_style"), fmt_widget)

        # --- Druckoptionen für Kabelfähnchen ---
        self._cb_flag_midline = QCheckBox(tr("settings.flag_midline"))
        self._cb_flag_midline.setChecked(
            s.value("flag_print_middle_line",
                    self.FACTORY["flag_print_middle_line"], bool)
        )
        form.addRow(tr("settings.flag_row"), self._cb_flag_midline)

        hint = QLabel(tr("settings.defaults_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { color: #888888; padding-top: 8px; }")
        form.addRow(hint)
        return w

    def _set_size_combo(self, pt: int) -> None:
        for i in range(self._size_combo.count()):
            if self._size_combo.itemData(i) == pt:
                self._size_combo.setCurrentIndex(i)
                return

    def _reset_to_factory(self) -> None:
        """Setzt jedes Feld des Dialogs auf die Werkseinstellungen zurück.
        Der Nutzer muss dennoch »OK« klicken, um sie tatsächlich zu
        speichern — »Abbrechen« macht sie rückgängig."""
        self._tape_combo.setCurrentText(self.FACTORY["tape_width"])
        self._font_combo.setCurrentFont(QFont(self.FACTORY["font_family"]))
        self._set_size_combo(self.FACTORY["font_size"])
        self._cb_bold.setChecked(self.FACTORY["font_bold"])
        self._cb_italic.setChecked(self.FACTORY["font_italic"])
        self._cb_underline.setChecked(self.FACTORY["font_underline"])
        self._cb_strikeout.setChecked(self.FACTORY["font_strikeout"])
        self._cb_flag_midline.setChecked(self.FACTORY["flag_print_middle_line"])
        self._cb_dark_mode.setChecked(self.FACTORY[DARK_MODE_KEY])
        self._lang_combo.setCurrentIndex(0)   # Deutsch (eingebaut)
        self._factory_reset_requested = True

    def _appearance_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        s = QSettings()

        self._cb_dark_mode = QCheckBox(tr("settings.dark_mode"))
        self._cb_dark_mode.setChecked(
            s.value(DARK_MODE_KEY, self.FACTORY[DARK_MODE_KEY], bool)
        )
        form.addRow(tr("settings.theme_row"), self._cb_dark_mode)

        info = QLabel(tr("settings.dark_hint"))
        info.setWordWrap(True)
        info.setStyleSheet("QLabel { color: #888888; padding-top: 8px; }")
        form.addRow(info)
        return w

    def _language_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        # Alle Sprachen: eingebautes Deutsch + jede JSON-Datei im Ordner »lang«.
        # Der Sprachcode liegt als itemData hinter dem Anzeigenamen.
        self._lang_combo = QComboBox()
        current = str(QSettings().value(LANGUAGE_KEY, "de"))
        for lang in available_languages():
            self._lang_combo.addItem(lang["name"], lang["code"])
            if lang["code"] == current:
                self._lang_combo.setCurrentIndex(self._lang_combo.count() - 1)

        btn_folder = QPushButton(tr("settings.open_lang_folder"))
        btn_folder.setToolTip(tr("settings.open_lang_folder_tip"))
        btn_folder.clicked.connect(self._open_lang_folder)

        row = QHBoxLayout()
        row.addWidget(self._lang_combo, 1)
        row.addWidget(btn_folder)
        form.addRow(tr("settings.language_row"), row)

        info = QLabel(tr("settings.language_hint"))
        info.setWordWrap(True)
        info.setStyleSheet("QLabel { color: #888888; padding-top: 8px; }")
        form.addRow(info)
        return w

    def _open_lang_folder(self) -> None:
        """Öffnet den Sprachordner im Dateimanager des Systems."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(lang_dir_for_user())))

    def _on_accept(self) -> None:
        s = QSettings()
        s.setValue("tape_width",     self._tape_combo.currentText())
        s.setValue("font_family",    self._font_combo.currentFont().family())
        s.setValue("font_size",      self._size_combo.currentData())
        s.setValue("font_bold",      self._cb_bold.isChecked())
        s.setValue("font_italic",    self._cb_italic.isChecked())
        s.setValue("font_underline", self._cb_underline.isChecked())
        s.setValue("font_strikeout", self._cb_strikeout.isChecked())
        s.setValue("flag_print_middle_line", self._cb_flag_midline.isChecked())

        # Sprache: alle Texte entstehen beim Aufbau der Fenster, daher wird die
        # neue Sprache erst beim nächsten Programmstart wirksam.
        new_lang = self._lang_combo.currentData() or "de"
        old_lang = str(s.value(LANGUAGE_KEY, "de"))
        s.setValue(LANGUAGE_KEY, new_lang)
        if self._factory_reset_requested:
            # Werksstandard: den automatischen Sprachvorschlag beim nächsten
            # Start wieder zulassen.
            s.remove(LANGUAGE_PROMPT_KEY)
        if new_lang != old_lang:
            QMessageBox.information(
                self,
                tr("settings.language_restart_title"),
                tr("settings.language_restart_body"),
            )

        dark = self._cb_dark_mode.isChecked()
        s.setValue(DARK_MODE_KEY, dark)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, dark)  # sofort auf alle Fenster anwenden
        # Selbstgezeichnete Icons + Zeichenflächen-Hintergrund nachziehen.
        # Den Wert explizit übergeben — die Palette aktualisiert sich erst
        # asynchron, ein sofortiges Auslesen wäre also noch der alte Zustand.
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_theme"):
            parent.refresh_theme(dark)

        self.accept()


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)

        title = QLabel("<h2>TuxLabel</h2>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        # Version aus tuxlabel/__init__.py — die einzige Quelle der Wahrheit.
        version = QLabel(tr("about.version", version=__version__))
        version.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(version)

        body = QLabel(tr("about.body"))
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        layout.addWidget(body)

        legal = QLabel(tr("about.legal"))
        legal.setTextFormat(Qt.TextFormat.RichText)
        legal.setWordWrap(True)
        legal.setOpenExternalLinks(True)   # Projektseite im Browser öffnen
        layout.addWidget(legal)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("shortcuts.title"))
        self.setMinimumSize(440, 500)

        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setHtml(self._html())
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _html(self) -> str:
        # Die Abschnitte kommen aus der Sprachdatei als
        # [Titel, [[Kürzel, Beschreibung], …]] — auch die Kürzel selbst sind
        # übersetzbar (»Strg« ↔ »Ctrl«).
        sections = tr("shortcuts.sections")
        parts = ["<html><body style='font-family: sans-serif;'>"]
        for section, rows in sections:
            parts.append(f"<h3>{section}</h3>")
            parts.append("<table cellpadding='4' cellspacing='0'>")
            for shortcut, action in rows:
                parts.append(
                    "<tr>"
                    f"<td style='padding-right: 24px; font-family: monospace;'>"
                    f"<b>{shortcut}</b></td>"
                    f"<td>{action}</td>"
                    "</tr>"
                )
            parts.append("</table>")
        parts.append("</body></html>")
        return "".join(parts)


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("help.title"))
        self.setMinimumSize(580, 560)

        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setHtml(str(tr("help.html")))
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
