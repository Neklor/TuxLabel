# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sprachverwaltung für TuxLabel.

Deutsch ist fest im Programm eingebaut (die Tabelle ``_DEFAULTS`` unten).
Weitere Sprachen werden als JSON-Dateien aus dem Unterordner »lang« geladen
(neben ``main.py``); zusätzlich wird ``~/.config/TuxLabel/lang`` durchsucht,
damit Nutzer ohne Schreibrechte im Programmordner eigene Übersetzungen
ablegen können.

Aufbau einer Sprachdatei (siehe auch lang/README.md):

    {
      "_meta": { "name": "English", "code": "en", "author": "..." },
      "menu.file": "&File",
      "help.html": ["<html>", "  ...", "</html>"]
    }

Regeln:
  • Fehlende Schlüssel fallen automatisch auf Deutsch zurück — unvollständige
    Übersetzungen bleiben dadurch benutzbar.
  • Ein Wert darf eine Liste von Zeichenketten sein; sie wird beim Nachschlagen
    mit Zeilenumbrüchen verbunden (angenehmer für lange Texte in JSON).
  • Platzhalter wie ``{name}`` müssen in der Übersetzung erhalten bleiben.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt6.QtCore import QLibraryInfo, QSettings, QTranslator

# QSettings-Schlüssel für die gewählte Sprache (Sprachcode, z. B. "de", "en")
LANGUAGE_KEY = "ui_language"

# QSettings-Schlüssel: wurde der automatische Sprachvorschlag beim Start schon
# beantwortet? Wird nur durch »Auf Werksstandard zurücksetzen« wieder gelöscht.
LANGUAGE_PROMPT_KEY = "language_prompt_done"

# ---------------------------------------------------------------------------
# Eingebaute deutsche Standardtexte — die maßgebliche Schlüsselliste.
# Jede Sprachdatei übersetzt diese Schlüssel; fehlende fallen hierauf zurück.
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, object] = {
    # --- Zahlen-/Datumsformate ---
    "format.decimal":  ",",
    "format.datetime": "%d.%m.%Y %H:%M",

    # --- Sprachvorschlag beim ersten Start ---
    # Diese Texte werden in der ZIELsprache angezeigt (der Dialog schlägt ja
    # gerade den Wechsel dorthin vor); die deutschen Fassungen hier sind nur
    # der Fallback für Sprachdateien, denen die Schlüssel fehlen.
    "startup.lang_title": "Sprache wechseln?",
    "startup.lang_body": ("Ihr Betriebssystem ist auf {language} eingestellt.\n"
                          "Möchten Sie TuxLabel ebenfalls auf {language} umstellen?\n\n"
                          "(Später jederzeit änderbar unter "
                          "Datei → Einstellungen → Sprache.)"),
    "startup.lang_body_fallback": ("TuxLabel ist in Ihrer Systemsprache nicht "
                                   "verfügbar.\n"
                                   "Möchten Sie von Deutsch auf Englisch umstellen?\n\n"
                                   "(Später jederzeit änderbar unter "
                                   "Datei → Einstellungen → Sprache.)"),

    # --- Statusleiste ---
    "status.hint": ("Doppelklick: Text bearbeiten  |  Strg+V: Bild einfügen  |  "
                    "Entf: löschen  |  Strg+Rad: Zoom"),
    "status.length": "Länge: {cm} cm",

    # --- Werkzeugleiste ---
    "toolbar.title":            "Werkzeuge",
    "toolbar.group_add":        "Hinzufügen",
    "toolbar.add_text_tip":     "Text einfügen — neues Textfeld auf dem Etikett",
    "toolbar.add_image_tip":    ("Bild einfügen — aus Datei laden\n"
                                 "Tipp: Bilder aus der Zwischenablage mit Strg+V einfügen"),
    "toolbar.tape_width":       "Bandbreite: ",
    "toolbar.tape_width_tip":   "Breite des eingelegten TZe-Bandes",
    "toolbar.font":             " Schriftart: ",
    "toolbar.font_tip":         "Schriftart der markierten Textfelder ändern",
    "toolbar.size":             " Größe: ",
    "toolbar.size_tip":         "Schriftgröße der markierten Textfelder ändern",
    "toolbar.bold":             "F",
    "toolbar.bold_tip":         "Fett",
    "toolbar.italic":           "K",
    "toolbar.italic_tip":       "Kursiv",
    "toolbar.underline":        "U",
    "toolbar.underline_tip":    "Unterstrichen",
    "toolbar.strike":           "S̶",
    "toolbar.strike_tip":       "Durchgestrichen",
    "toolbar.align_left":       "Linksbündig",
    "toolbar.align_center":     "Zentriert",
    "toolbar.align_right":      "Rechtsbündig",
    "toolbar.align_justify":    "Blocksatz",
    "toolbar.align_tip":        "Text {align} ausrichten",
    "toolbar.superscript":      "x²",
    "toolbar.superscript_tip":  "Hochgestellt",
    "toolbar.subscript":        "x₂",
    "toolbar.subscript_tip":    "Tiefgestellt",
    "toolbar.format_paint":     "Format ↷",
    "toolbar.format_paint_tip": ("Format übertragen:\n"
                                 "Ein Textfeld auswählen → Klick → auf Zielfeld klicken.\n"
                                 "Abbrechen: Escape oder erneut klicken."),
    "toolbar.vcenter_tip":      "Markierte Textfelder vertikal auf dem Band zentrieren",
    "toolbar.hcenter_tip":      "Markierte Textfelder horizontal auf dem Etikett zentrieren",
    "toolbar.length":           " Länge: ",
    "toolbar.length_tip":       "Länge des Etiketts in mm",
    "toolbar.mm_suffix":        " mm",
    "toolbar.auto":             "Auto",
    "toolbar.auto_tip":         ("Länge automatisch erweitern, wenn Inhalt nicht mehr passt.\n"
                                 "Deaktivieren für feste Etikettlänge."),
    "toolbar.flag":             "Fähnchen",
    "toolbar.flag_tip":         ("Kabelfähnchen-Modus: das Band wird in linkes Fähnchen · "
                                 "Mittelbalken (Kabelumschlingung) · rechtes Fähnchen geteilt.\n"
                                 "Der Mittelbalken ergibt sich aus dem Kabeldurchmesser (Umfang)."),
    "toolbar.flag_dia_prefix":  "⌀ ",
    "toolbar.flag_dia_tip":     ("Kabeldurchmesser. Der Mittelbalken wird auf den Umfang "
                                 "(π × Durchmesser) gesetzt, damit der Text nicht auf dem Kabel liegt."),
    "toolbar.flag_mid_prefix":  "Mitte ",
    "toolbar.flag_mid_tip":     ("Breite des Mittelbalkens in mm. Folgt dem Kabeldurchmesser, "
                                 "kann aber manuell angepasst werden."),
    "toolbar.flag_copy":        "Spiegeln",
    "toolbar.flag_copy_tip":    ("Linkes Fähnchen automatisch auf das rechte kopieren (gleiche "
                                 "Ausrichtung).\nDeaktivieren, um beiden Hälften unterschiedlichen "
                                 "Text zu geben."),
    "toolbar.save_defaults":    "★ Standard",
    "toolbar.save_defaults_tip": ("Aktuelle Bandbreite, Schriftart, Schriftgröße und Schriftstil\n"
                                  "als Voreinstellung speichern (entspricht Datei → Einstellungen)"),
    "toolbar.print_tip":        "Etikett drucken (Strg+P)",

    # --- Menüleiste ---
    "menu.file":            "&Datei",
    "menu.file_new":        "&Neu",
    "menu.file_open":       "&Öffnen…",
    "menu.file_save":       "&Speichern",
    "menu.file_save_as":    "Speichern &unter…",
    "menu.file_undo":       "&Rückgängig",
    "menu.file_recent":     "&Verlauf",
    "menu.file_settings":   "&Einstellungen…",
    "menu.file_quit":       "&Beenden",
    "menu.edit":            "&Bearbeiten",
    "menu.edit_cut":        "&Ausschneiden",
    "menu.edit_copy":       "&Kopieren",
    "menu.edit_paste":      "&Einfügen",
    "menu.edit_delete":     "&Löschen",
    "menu.edit_duplicate":  "&Verdoppeln",
    "menu.edit_select_all": "Alles &markieren",
    "menu.edit_datetime":   "&Datum und Uhrzeit einfügen",
    "menu.help":            "&Hilfe",
    "menu.help_contents":   "&Inhalt",
    "menu.help_shortcuts":  "&Tastenkürzel",
    "menu.help_about":      "&Über",
    "menu.recent_empty":    "(leer)",
    "menu.recent_clear":    "Verlauf leeren",

    # --- Meldungen des Hauptfensters ---
    "msg.load_image_title":    "Bild laden",
    "msg.image_filter":        ("Bilder (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;"
                                "Alle Dateien (*.*)"),
    "msg.load_image_failed":   "Das Bild konnte nicht geladen werden:\n{path}",
    "msg.paint_select_first":  ("Format übertragen: Bitte zuerst ein Quell-Textfeld auswählen, "
                                "dann erneut auf »Format« klicken."),
    "msg.paint_click_target":  ("Format übertragen: Jetzt auf das Ziel-Textfeld klicken "
                                "(Escape zum Abbrechen)."),
    "msg.defaults_saved_title": "Voreinstellungen gespeichert",
    "msg.defaults_saved_body": ("Die aktuellen Einstellungen wurden als Startvoreinstellung "
                                "gespeichert:\n\n"
                                "  Bandbreite:   {tape}\n"
                                "  Schriftart:   {font}\n"
                                "  Schriftgröße: {size} pt"),
    "msg.open_title":          "Etikett öffnen",
    "msg.file_filter":         "TuxLabel-Datei (*.ptle);;Alle Dateien (*.*)",
    "msg.save_as_title":       "Etikett speichern unter",
    "msg.save_filter":         "TuxLabel-Datei (*.ptle)",
    "msg.save_failed_title":   "Speichern fehlgeschlagen",
    "msg.save_failed_body":    "Die Datei konnte nicht gespeichert werden:\n\n{error}",
    "msg.saved_status":        "Gespeichert: {name}",
    "msg.open_failed_title":   "Öffnen fehlgeschlagen",
    "msg.open_failed_body":    "Die Datei konnte nicht geöffnet werden:\n\n{error}",
    "msg.opened_status":       "Geöffnet: {name}",
    "msg.file_missing_title":  "Datei nicht gefunden",
    "msg.file_missing_body":   "Die Datei existiert nicht mehr:\n{path}",
    "msg.nothing_to_undo":     "Nichts mehr rückgängig zu machen.",
    "msg.unsaved_title":       "Änderungen speichern?",
    "msg.unsaved_body":        ("Das aktuelle Etikett hat ungespeicherte Änderungen.\n\n"
                                "Möchten Sie die Änderungen speichern?"),

    # --- Elemente ---
    "item.default_text": "Text",

    # --- Einstellungsdialog ---
    "settings.title":          "Einstellungen",
    "settings.tab_defaults":   "Voreinstellungen",
    "settings.tab_appearance": "Darstellung",
    "settings.tab_language":   "Sprache",
    "settings.reset_button":   "Auf Werksstandard zurücksetzen",
    "settings.default_tape":   "Standard-Bandbreite:",
    "settings.default_font":   "Standard-Schriftart:",
    "settings.default_size":   "Standard-Schriftgröße:",
    "settings.default_style":  "Standard-Schriftstil:",
    "settings.bold":           "Fett",
    "settings.italic":         "Kursiv",
    "settings.underline":      "Unterstrichen",
    "settings.strikeout":      "Durchgestrichen",
    "settings.flag_row":       "Fähnchen:",
    "settings.flag_midline":   ("Mittellinie (Falzlinie) drucken — hilft beim mittigen "
                                "Aufkleben"),
    "settings.defaults_hint":  ("Diese Werte gelten beim Programmstart und beim Klick auf "
                                "»Neu«. Sie entsprechen dem »Standard«-Knopf in der "
                                "Werkzeugleiste."),
    "settings.theme_row":      "Design:",
    "settings.dark_mode":      "Dunkles Design (Darkmode) verwenden",
    "settings.dark_hint":      ("Der Darkmode betrifft nur die Programmoberfläche. Das Etikett "
                                "selbst bleibt weiß, da es das physische TZe-Band abbildet."),
    "settings.language_row":   "Sprache:",
    "settings.language_hint":  ("Sprachdateien sind JSON-Dateien im Ordner »lang« neben dem "
                                "Programm (zusätzlich wird ~/.config/TuxLabel/lang durchsucht). "
                                "Eigene Übersetzungen: en.json kopieren, übersetzen und hier "
                                "auswählen — eine Anleitung steht in lang/README.md."),
    "settings.open_lang_folder":     "Ordner öffnen",
    "settings.open_lang_folder_tip": ("Öffnet den Sprachordner im Dateimanager — "
                                      "eigene Sprachdateien (JSON) hier ablegen."),
    "settings.language_restart_title": "Sprache geändert",
    "settings.language_restart_body":  ("Die neue Sprache wird nach einem Neustart von "
                                        "TuxLabel wirksam."),

    # --- Über-Dialog ---
    "about.title": "Über TuxLabel",
    # {version} wird aus tuxlabel.__version__ gefüllt. »Version« schreibt sich
    # in allen mitgelieferten Sprachen gleich — ein Übersetzen ist optional.
    "about.version": "<p>Version {version}</p>",
    "about.body":  ("<p>Editor für Brother PT-P700 Etiketten (TZe-Bänder).</p>"
                    "<p><b>Autor:</b> Christoph Krogmann</p>"),
    # Eigener Schlüssel statt Teil von about.body: so erscheint der Hinweis
    # auch in Sprachen, deren JSON-Datei nur about.body übersetzt hat.
    "about.legal": ("<p>Lizenz: GPL-3.0-or-later<br>"
                    "<a href=\"https://github.com/Neklor/TuxLabel\">"
                    "github.com/Neklor/TuxLabel</a></p>"),

    # --- Tastenkürzel-Dialog ---
    "shortcuts.title": "Tastenkürzel",
    # Struktur: Liste von [Abschnittstitel, [[Kürzel, Beschreibung], …]]
    "shortcuts.sections": [
        ["Datei", [
            ["Strg+N",          "Neues Etikett"],
            ["Strg+O",          "Etikett öffnen"],
            ["Strg+S",          "Speichern"],
            ["Strg+Umschalt+S", "Speichern unter"],
            ["Strg+Z",          "Rückgängig"],
            ["Strg+Q",          "Beenden"],
        ]],
        ["Bearbeiten", [
            ["Strg+X", "Ausschneiden"],
            ["Strg+C", "Kopieren"],
            ["Strg+V", "Einfügen"],
            ["Entf",   "Löschen"],
            ["Strg+D", "Verdoppeln"],
            ["Strg+A", "Alles markieren"],
            ["F5",     "Datum und Uhrzeit einfügen"],
        ]],
        ["Bewegen", [
            ["Pfeiltaste",      "1 mm verschieben"],
            ["Strg+Pfeiltaste", "0,1 mm fein verschieben"],
        ]],
        ["Ansicht", [
            ["Strg+Mausrad", "Zoom"],
        ]],
        ["Drucken", [
            ["Strg+P", "Drucken"],
        ]],
    ],

    # --- Hilfe-Dialog ---
    "help.title": "Hilfe",
    "help.html": """
    <html><body style='font-family: sans-serif;'>
    <h2>TuxLabel — Kurzanleitung</h2>

    <h3>Etikett bearbeiten</h3>
    <ul>
      <li><b>Text einfügen:</b> Im Werkzeugbereich <i>Hinzufügen</i> auf
          das <b>T</b>-Symbol (mit grünem +) klicken. Doppelklick auf ein
          Textfeld öffnet den Inline-Editor.</li>
      <li><b>Bild einfügen:</b> Im Werkzeugbereich <i>Hinzufügen</i> auf
          das <b>Bild-Symbol</b> (mit grünem +) klicken, um eine Bilddatei
          zu laden. Mit <i>Strg+V</i> lassen sich Bilder direkt aus der
          Zwischenablage einfügen.</li>
      <li><b>Verschieben:</b> Element mit der Maus ziehen oder mit den
          Pfeiltasten verschieben (Strg = Feinschritt 0,1&nbsp;mm).</li>
      <li><b>Größe ändern:</b> Element auswählen und an einem der blauen
          Griffe ziehen.</li>
      <li><b>Format übertragen:</b> Quelltextfeld markieren, Schaltfläche
          <i>Format</i> klicken, dann auf das Zielfeld klicken.</li>
    </ul>

    <h3>Bandbreite und Länge</h3>
    <p>Die im Werkzeugkasten eingestellte Bandbreite muss dem eingelegten
       TZe-Band entsprechen – sonst blinkt der PT-P700 rot. Das Lineal
       oberhalb des Etiketts zeigt die aktuelle Länge in Zentimetern; mit
       der Schaltfläche <b>Auto</b> wächst die Etikettenlänge automatisch
       mit dem Inhalt.</p>

    <h3>Datei verwalten</h3>
    <ul>
      <li><b>Datei → Speichern</b> sichert das Etikett als
          <code>.ptle</code>-Datei (Text, Bilder, Bandeinstellung).</li>
      <li><b>Datei → Verlauf</b> bietet schnellen Zugriff auf zuletzt
          geöffnete Etiketten.</li>
      <li><b>Datei → Rückgängig</b> nimmt die letzte Änderung am Etikett
          zurück (bis zu 50 Schritte).</li>
    </ul>

    <h3>Drucken</h3>
    <p>Schaltfläche <i>Drucken</i> öffnet den Druckdialog. Wählen Sie den
       CUPS-Drucker (PT-P700), prüfen Sie Bandbreite und Druckmodus
       (Strich = Text, Dithering = Foto) und starten Sie den Druck.</p>

    <p>Eine vollständige Liste der Tastenkürzel finden Sie unter
       <i>Hilfe → Tastenkürzel</i>.</p>
    </body></html>
    """,

    # --- Druckdialog ---
    "print.title":            "Etikett drucken",
    "print.printer_row":      "Drucker:",
    "print.refresh_tip":      "Druckerliste aktualisieren",
    "print.no_printer_item":  "(Kein Drucker gefunden)",
    "print.label_row":        "Etikett:",
    "print.label_info":       "Band: {tape} mm  ·  Etikettlänge: <b>{length} mm</b>",
    "print.autocut":          "Automatisch schneiden (AutoCut)",
    "print.match":            "Nur drucken wenn Bandbreite übereinstimmt",
    "print.match_tip_disabled": ("Für {tape} mm Band automatisch deaktiviert.\n\n"
                                 "Custom-Page-Größen <12,7 mm Breite werden von der PPD\n"
                                 "auf 12,7 mm aufgerundet — die »Bandbreite passt«-Prüfung\n"
                                 "schlägt dann fehl und der P700 blinkt rot."),
    "print.match_tip":        ("Deaktivieren, um auf einem abweichend breiten Band zu drucken.\n"
                               "Bei Mismatch blinkt der P700 rot – deaktivieren behebt das."),
    "print.mode_row":         "Druckmodus:",
    "print.mode_line_light":     "Strich – Hell",
    "print.mode_line_normal":    "Strich – Normal",
    "print.mode_line_dark":      "Strich – Dunkel  (empfohlen für Text)",
    "print.mode_line_very_dark": "Strich – Sehr dunkel",
    "print.mode_photo":          "Foto / Dithering (Floyd-Steinberg)",
    "print.mode_tip":         ("Strich-Modus: jedes Pixel wird per Helligkeitsschwelle "
                               "schwarz oder weiß. Beste Wahl für Text.\n\n"
                               "Foto-Modus (Dithering): Grauwerte werden durch Punktmuster "
                               "angenähert (Floyd-Steinberg). Beste Wahl für Bilder/Fotos; "
                               "Textkanten können dabei leicht körnig wirken."),
    "print.offset_row":       "Vertikaler Versatz:",
    "print.offset_tip":       ("Verschiebt den gedruckten Inhalt vertikal auf dem Band.\n"
                               "Negativ = nach oben, Positiv = nach unten.\n\n"
                               "Wenn am unteren Bandrand abgeschnitten wird (z.B. 'p'-Unterlängen):\n"
                               "kleinen negativen Wert probieren (-0.3 bis -0.8 mm).\n\n"
                               "Der zuletzt eingestellte Wert wird gespeichert."),
    "print.button_print":     "Drucken",
    "print.button_cancel":    "Abbrechen",
    "print.mismatch":         ("⚠  Bandbreiten-Konflikt: Drucker zuletzt mit "
                               "<b>{printer_mm} mm</b> konfiguriert, Editor auf "
                               "<b>{scene_mm} mm</b> eingestellt.\n"
                               "Stellen Sie sicher, dass das eingelegte Band mit der "
                               "Editor-Einstellung übereinstimmt – sonst blinkt der P700 rot.\n"
                               "Tipp: Deaktivieren Sie 'Nur drucken wenn Bandbreite "
                               "übereinstimmt' um trotzdem zu drucken."),
    "print.no_printer_title": "Kein Drucker",
    "print.no_printer_body":  "Bitte einen Drucker auswählen.",
    "print.sent_title":       "Druckauftrag gesendet",
    "print.sent_body":        "Der Druckauftrag wurde an '{printer}' gesendet.\n{msg}",
    "print.error_title":      "Druckfehler",
    "print.error_body":       "Druckauftrag fehlgeschlagen:\n\n{msg}",
    "print.lp_missing":       "Das Programm 'lp' wurde nicht gefunden (CUPS nicht installiert?).",
}


# ---------------------------------------------------------------------------
# Laufzeitzustand
# ---------------------------------------------------------------------------

# Aktive Übersetzungen (leer = eingebautes Deutsch)
_strings: dict[str, object] = {}
_current_code: str = "de"


def _lang_dirs() -> list[Path]:
    """Die Ordner, in denen nach Sprachdateien gesucht wird (in dieser Reihenfolge)."""
    return [
        Path(__file__).resolve().parent.parent / "lang",         # neben main.py
        Path(os.path.expanduser("~/.config/TuxLabel/lang")),      # nutzereigene Dateien
    ]


def lang_dir_for_user() -> Path:
    """Der Sprachordner, den der Einstellungsdialog öffnet.

    Bevorzugt den »lang«-Ordner neben dem Programm (dort liegen en.json und
    README.md als Vorlage); existiert er nicht und lässt er sich nicht
    anlegen (Programmordner schreibgeschützt), stattdessen den nutzereigenen
    Ordner unter ~/.config/TuxLabel/lang anlegen und zurückgeben.

    Entscheidend ist die SCHREIBBARKEIT, nicht bloß die Existenz: bei einer
    Installation über das .deb-Paket liegt der Programmordner unter
    /usr/lib/tuxlabel und ist für den Nutzer nur lesbar. Ein »Ordner öffnen«,
    das dorthin führt, wäre eine Sackgasse — dort lässt sich keine eigene
    Übersetzung ablegen."""
    primary, fallback = _lang_dirs()
    if primary.is_dir():
        if os.access(primary, os.W_OK):
            return primary
    else:
        try:
            primary.mkdir(parents=True)
            return primary
        except OSError:
            pass
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return fallback


def available_languages() -> list[dict]:
    """Listet alle wählbaren Sprachen auf.

    Rückgabe: Liste von ``{"code", "name", "path"}``; das eingebaute Deutsch
    steht immer an erster Stelle (``path`` ist dann ``None``). Dateien mit dem
    Code »de« werden übersprungen — Deutsch ist fest eingebaut."""
    languages = [{"code": "de", "name": "Deutsch", "path": None}]
    seen = {"de"}
    for directory in _lang_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                meta = data.get("_meta", {})
                code = str(meta.get("code", path.stem)).lower()
                name = str(meta.get("name", path.stem))
            except (OSError, json.JSONDecodeError, AttributeError):
                continue   # defekte Datei stillschweigend überspringen
            if code in seen:
                continue
            seen.add(code)
            languages.append({"code": code, "name": name, "path": str(path)})
    return languages


def load_language(code: str) -> None:
    """Aktiviert die Sprache *code*. »de« oder unbekannte Codes ⇒ eingebautes Deutsch."""
    global _strings, _current_code
    code = (code or "de").lower()
    if code != "de":
        for lang in available_languages():
            if lang["code"] == code and lang["path"]:
                try:
                    with open(lang["path"], encoding="utf-8") as fh:
                        data = json.load(fh)
                    data.pop("_meta", None)
                    _strings = data
                    _current_code = code
                    return
                except (OSError, json.JSONDecodeError):
                    break
    _strings = {}
    _current_code = "de"


def init_from_settings() -> None:
    """Lädt die in den Einstellungen gespeicherte Sprache (Aufruf beim Programmstart)."""
    load_language(str(QSettings().value(LANGUAGE_KEY, "de")))


def current_language() -> str:
    return _current_code


# Referenz auf den geladenen Qt-Übersetzer. Muss auf Modulebene liegen: Qt
# hält nur einen C++-Zeiger, und ohne Python-Referenz kann der Übersetzer
# eingesammelt werden — die Knöpfe fielen dann still ins Englische zurück.
_qt_translator: QTranslator | None = None


def install_qt_translations(app) -> bool:
    """Lädt Qts eigene Übersetzungen für die aktive Sprache.

    Die Beschriftungen der Standardknöpfe von QMessageBox und
    QDialogButtonBox (»Speichern«, »Verwerfen«, »Abbrechen«, »OK«, …) stammen
    nicht aus unseren Sprachdateien, sondern aus Qts mitgeliefertem Katalog.
    Ohne diesen Aufruf bleiben sie englisch, auch wenn die übrige Oberfläche
    deutsch ist.

    Maßgeblich ist die in TuxLabel eingestellte Sprache, ausdrücklich NICHT
    die des Betriebssystems: sonst zeigte ein auf Spanisch gestelltes
    TuxLabel auf einem deutschen System deutsche Knöpfe. Für Sprachen ohne
    Qt-Katalog — etwa selbst erstellte Übersetzungen — passiert nichts, die
    Knöpfe bleiben dann englisch.

    Gibt zurück, ob ein Katalog geladen wurde."""
    global _qt_translator
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load(f"qtbase_{_current_code}", path):
        return False
    if not app.installTranslator(translator):
        return False
    _qt_translator = translator
    return True


def system_language_code() -> str:
    """Sprachcode des Betriebssystems (»de«, »en«, »fr«, …)."""
    from PyQt6.QtCore import QLocale
    return QLocale.system().name().split("_")[0].lower()


def maybe_offer_system_language(parent=None) -> None:
    """Schlägt beim ersten Start den Wechsel auf die Systemsprache vor.

    Greift nur, wenn der Vorschlag noch nie beantwortet wurde, aktuell Deutsch
    aktiv ist und das Betriebssystem nicht auf Deutsch steht. Gibt es die
    Systemsprache als Sprachdatei, wird sie angeboten — der Dialog erscheint
    dann in dieser Sprache. Gibt es sie nicht, wird auf Englisch gefragt, ob
    auf Englisch gewechselt werden soll. Die Antwort wird gespeichert und bei
    späteren Starts nicht erneut abgefragt, egal welche Sprache der Nutzer
    danach einstellt; erst »Auf Werksstandard zurücksetzen« im
    Einstellungsdialog löscht den Marker wieder."""
    s = QSettings()
    if s.value(LANGUAGE_PROMPT_KEY, False, bool):
        return
    if str(s.value(LANGUAGE_KEY, "de")).lower() != "de":
        # Der Nutzer hat bereits selbst eine andere Sprache gewählt —
        # als beantwortet markieren, damit ein späterer Rückwechsel auf
        # Deutsch die Frage nicht plötzlich auslöst.
        s.setValue(LANGUAGE_PROMPT_KEY, True)
        return
    sys_code = system_language_code()
    if sys_code == "de":
        # Systemsprache ist Deutsch — nichts vorzuschlagen. Bewusst KEIN
        # Marker: stellt der Nutzer sein System später um, greift der
        # Vorschlag dann.
        return
    languages = {lang["code"]: lang for lang in available_languages()}
    target = languages.get(sys_code) or languages.get("en")
    if target is None or target["code"] == "de":
        # Keine passende Sprachdatei (auch kein Englisch) — es gibt nichts
        # anzubieten; beim nächsten Start erneut prüfen.
        return
    body_key = ("startup.lang_body" if target["code"] == sys_code
                else "startup.lang_body_fallback")

    # Den Dialog in der Zielsprache anzeigen: probeweise laden und bei
    # Ablehnung wieder auf Deutsch zurückschalten.
    load_language(target["code"])
    from PyQt6.QtWidgets import QMessageBox
    ret = QMessageBox.question(
        parent,
        str(tr("startup.lang_title")),
        str(tr(body_key, language=target["name"])),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    s.setValue(LANGUAGE_PROMPT_KEY, True)
    if ret == QMessageBox.StandardButton.Yes:
        s.setValue(LANGUAGE_KEY, target["code"])
    else:
        load_language("de")


def tr(key: str, **kwargs) -> object:
    """Schlägt den Text zu *key* nach; fehlende Schlüssel fallen auf Deutsch zurück.

    Listen aus lauter Zeichenketten werden mit ``\\n`` verbunden (erlaubt
    mehrzeilige Texte in JSON). Mit *kwargs* werden ``{platzhalter}`` per
    ``str.format`` gefüllt; schlägt das fehl (z. B. Tippfehler im Platzhalter
    einer Sprachdatei), wird der rohe Text zurückgegeben statt abzustürzen."""
    value = _strings.get(key, _DEFAULTS.get(key, key))
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        value = "\n".join(value)
    if kwargs and isinstance(value, str):
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return value


def fmt_number(value: float, decimals: int | None = None) -> str:
    """Formatiert eine Zahl mit dem Dezimaltrennzeichen der aktiven Sprache.

    Ohne *decimals* wird ``%g`` benutzt (12 → »12«, 3.5 → »3,5«)."""
    text = f"{value:g}" if decimals is None else f"{value:.{decimals}f}"
    return text.replace(".", str(tr("format.decimal")))
