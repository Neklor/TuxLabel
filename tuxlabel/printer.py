# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Druckunterstützung für TuxLabel.

Strategie
---------
Der Brother P-Touch P700 wird über einen CUPS-PPD-Treiber angesteuert.
Diese PPD definiert benannte Seitengrößen (tz-6, tz-9, tz-12, tz-18,
tz-24) und die Option »RequireMatchingLabelSize«, die standardmäßig True
ist – das heißt, der Drucker wirft einen harten Fehler, wenn die
Seitengröße des Auftrags nicht zum eingelegten Band passt.

QPrinter sendet PostScript mit einer benutzerdefinierten Seitengröße, die
der Treiber nicht erkennt, was die rote Fehleranzeige auslöst.

Daher gehen wir so vor:
  1.  Das Etikett in ein temporäres PNG mit 180 DPI rendern.
  2.  Die Datei über den Befehl ``lp`` mit der richtigen Option
      ``-o PageSize=tz-<Breite>`` an CUPS senden.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .i18n import fmt_number, tr
from .label_canvas import PRINT_HARDWARE_LEADER_MM

if TYPE_CHECKING:
    from .label_canvas import LabelScene

# P700-PPD-Seitengrößennamen für TZe-Bänder (mm → PPD-Schlüsselwort).
# Brothers PPD nennt das 3,5-mm-Band »tz-4« — dieser Name bleibt, weil
# CUPS/der Treiber ihn erwarten; nur der interne mm-Schlüssel spiegelt die
# Realität wider.
#
# HINWEIS: Diese Namen werden NICHT mehr an lp gesendet. Brothers PPD
# definiert jede tz-*-PageSize mit fester Länge (typischerweise 100 mm),
# sodass das Senden von PageSize=tz-12 jedes Etikett zwingt, 100 mm lang
# herauszukommen — kurzer Inhalt mit Leerraum aufgefüllt, langer Inhalt
# abgeschnitten. Stattdessen senden wir eine Seite mit benutzerdefinierter
# Größe (siehe _send_to_printer unten). Die Tabelle bleibt für die
# lp-Konflikt-Prüfung (`_get_printer_tape_mm`) erhalten, die den aktuell
# als Standard gesetzten tz-*-Namen des Druckers erkennen muss.
TZE_PAGE_SIZES: dict[float, str] = {
    3.5: "tz-4",
    6:   "tz-6",
    9:   "tz-9",
    12:  "tz-12",
    18:  "tz-18",
    24:  "tz-24",
}

# Druckauflösung des P700
PRINT_DPI = 180

# PostScript-Punkte pro Millimeter. PostScript & CUPS rechnen in Punkten (1/72 Zoll).
_PT_PER_MM = 72.0 / 25.4   # ≈ 2.83465

# Brothers PT-P700-PPD deklariert
#     *ParamCustomPageSize Width:  1 points 36 100000
#     *ParamCustomPageSize Height: 2 points 36 100000
# d. h. benutzerdefinierte Seitenmaße müssen ≥ 36 pt (~12,7 mm) sein. Die
# nativen TZe-Bandbreiten in Punkten (10 / 17 / 26 / 34 für 3,5/6/9/12 mm)
# liegen alle darunter — beim Senden der wörtlichen Breite wird die
# Custom-Seite stillschweigend abgelehnt, und der Treiber fällt auf
# *DefaultPageSize=tz-24 zurück, was dann entweder die Größenprüfung
# auslöst (rotes Blinken) oder, bei deaktivierter Prüfung, 24-mm-Inhalt auf
# das 12-mm-Band sprüht und endlos vorschiebt. Das Hochsetzen auf 36 pt
# behebt beides. Der Druckkopf nutzt weiterhin seine physische Bandbreite —
# die zusätzlichen 0,7 mm »Seite« bleiben einfach ungenutzt.
_PPD_CUSTOM_MIN_PT = 36


def _fmt_mm(mm: float) -> str:
    """Formatiert eine Bandbreite zur Anzeige: 12 → '12', 3.5 → '3,5'
    (Dezimaltrennzeichen aus der aktiven Sprachdatei)."""
    return fmt_number(mm)


# ---------------------------------------------------------------------------
# Hilfsfunktionen auf niedriger Ebene
# ---------------------------------------------------------------------------

def _c_locale_env() -> dict[str, str]:
    """Erbt die Umgebung des Elternprozesses, erzwingt aber die C-Locale,
    damit CUPS-Werkzeuge (lpstat, lpoptions) stets englischen Text ausgeben.
    Andernfalls wäre das erste Wort einer ``lpstat -p``-Zeile
    »Drucker«/»imprimante«/… und die Schlüsselwortprüfung müsste jede
    Übersetzung kennen."""
    return {**os.environ, "LC_ALL": "C"}


def _get_cups_printers() -> list[str]:
    """Gibt die Namen aller von lpstat gemeldeten CUPS-Drucker zurück."""
    try:
        result = subprocess.run(
            ["lpstat", "-p"],
            capture_output=True, text=True, timeout=5,
            env=_c_locale_env(),
        )
        printers: list[str] = []
        for line in result.stdout.splitlines():
            # Mit LC_ALL=C ist das erste Wort immer »printer«
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0].lower() == "printer":
                printers.append(parts[1])
        return printers
    except Exception:
        return []


def _get_printer_tape_mm(printer_name: str) -> float | None:
    """Fragt die aktuelle Standard-PageSize des Druckers über lpoptions ab.

    Gibt die Bandbreite in mm zurück (z. B. 12 oder 3.5 für das
    3,5-mm-TZe-Band, das Brothers PPD »tz-4« nennt), wenn der aktive
    Standard ein tz-*-Eintrag ist, oder None, wenn sie nicht ermittelt
    werden kann.
    """
    try:
        result = subprocess.run(
            ["lpoptions", "-p", printer_name, "-l"],
            capture_output=True, text=True, timeout=5,
            env=_c_locale_env(),
        )
        for line in result.stdout.splitlines():
            if not line.startswith("PageSize"):
                continue
            for token in line.split():
                if token.startswith("*tz-"):
                    suffix = token[4:]   # »*tz-12« → »12«
                    if suffix == "4":
                        return 3.5       # Brother-PPD: tz-4 == 3,5-mm-Band
                    try:
                        return int(suffix)
                    except ValueError:
                        return None
    except Exception:
        pass
    return None


def _binarize_image(image: QImage, threshold: int) -> QImage:
    """Wandelt ein gerendertes Etikettenbild für den Thermodruck in reines
    Schwarz/Weiß um.

    Kantengeglättete graue Pixel an Textkanten übertragen sich auf
    Thermoband schlecht. Jedes Pixel, dessen Helligkeit unter *threshold*
    liegt, wird reines Schwarz; der Rest wird reines Weiß. Höhere Schwelle →
    mehr Pixel werden schwarz → dunkler.
    """
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = gray.width(), gray.height()
    out  = QImage(w, h, QImage.Format.Format_RGB32)

    for y in range(h):
        for x in range(w):
            lum = gray.pixel(x, y) & 0xFF   # Graustufen: R == G == B == lum
            out.setPixel(x, y, 0xFF000000 if lum < threshold else 0xFFFFFFFF)

    # DPI-Metadaten kopieren, damit CUPS das Bild korrekt skaliert
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    return out


def _dither_image(image: QImage) -> QImage:
    """Wandelt mittels Floyd-Steinberg-Fehlerdiffusion in reines S/W um.

    Die Schwellwert-Binarisierung verwandelt Halbton-Inhalte (Fotos,
    schattierte Bilder) in einen flachen schwarzen Klecks — alles dunkler
    als die Schwelle wird voll schwarz. Die Fehlerdiffusion nähert Grauwerte
    über Punktmuster an und bewahrt die visuelle Form des Originalbilds auf
    einem 1-Bit-Thermodrucker weit besser. Qts QImage-Umwandlung in
    Format_Mono mit DiffuseDither setzt Floyd-Steinberg in C++ um, sodass
    dies selbst für bandfüllende Bilder schnell ist.
    """
    # In 1-Bit-Mono mit diffuser Rasterung umwandeln, dann zurück nach RGB32,
    # damit die PNG-Ausgabe unkomprimierungsfreundlich ist und zum
    # Pixel-Layout des Schwellwert-Pfads passt.
    mono = image.convertToFormat(
        QImage.Format.Format_Mono,
        Qt.ImageConversionFlag.MonoOnly | Qt.ImageConversionFlag.DiffuseDither,
    )
    out = mono.convertToFormat(QImage.Format.Format_RGB32)
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    return out


def _combine_min(a: QImage, b: QImage) -> QImage:
    """Pixelweises Abdunkeln (kanalweises Minimum) zweier Binärbilder.

    Beide Eingaben müssen identische Abmessungen haben. Jedes Pixel, das in
    EINEM der Bilder schwarz ist, wird in der Ausgabe schwarz — so stapeln
    sich die scharfe Textebene und die gerasterte Bildebene sauber, ohne
    dass eine die andere auslöscht.
    """
    out = QImage(a)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Darken)
    painter.drawImage(0, 0, b)
    painter.end()
    out.setDotsPerMeterX(a.dotsPerMeterX())
    out.setDotsPerMeterY(a.dotsPerMeterY())
    return out


def _draw_flag_middle_line(image: QImage, scene: "LabelScene") -> None:
    """Zeichnet eine dünne schwarze Linie entlang der Falzmitte eines
    Kabelfähnchen-Etiketts.

    Auf das (sonst leere) mittlere Wickelband gedruckt, markiert sie die
    exakte Mitte, sodass sich das Etikett beim Wickeln um das Kabel leicht
    ausrichten lässt."""
    if not scene.get_flag_mode():
        return
    ppmm = PRINT_DPI / 25.4
    fold_mm = scene.get_flag_width_mm() + scene.get_flag_middle_mm() / 2.0
    x = int(round(fold_mm * ppmm))
    w = max(1, int(round(0.3 * ppmm)))   # ~0,3 mm dick
    painter = QPainter(image)
    painter.fillRect(x - w // 2, 0, w, image.height(), Qt.GlobalColor.black)
    painter.end()


def _render_to_png(
    scene: "LabelScene",
    path: str,
    darkness_threshold: int = 210,
    dither: bool = False,
    vertical_offset_mm: float = 0.0,
    draw_flag_middle: bool = True,
) -> None:
    """Rendert das Etikett in ein PNG, binarisiert für den Thermodruck.

    Modi:
      - dither=False: einfache Schwellwert-Binarisierung. Scharf für Text,
        flacht Fotos aber zu vollen schwarzen Klecksen ab.
      - dither=True mit nur TextBoxes ODER nur ImageBoxes: ein Durchgang mit
        Floyd-Steinberg über die gesamte Szene.
      - dither=True mit SOWOHL Text ALS AUCH Bildern: zwei Durchgänge — nur
        Text mit Schwellwert gerendert (scharfe Glyphenkanten), nur Bild mit
        Floyd-Steinberg-Rasterung gerendert (bewahrt Fototöne), dann per
        Abdunkeln zusammengesetzt, sodass jedes schwarze Pixel aus einem der
        Durchgänge erscheint.
    """
    from .text_item import TextBox
    from .image_item import ImageBox

    if dither:
        has_text   = any(isinstance(it, TextBox)  for it in scene.items())
        has_images = any(isinstance(it, ImageBox) for it in scene.items())
        if has_text and has_images:
            # Getrennte Pipeline — Brother-artige Mischung aus scharfem Text +
            # gerastertem Bild. Der Eintrag für den Dither-Modus im Kombinationsfeld
            # verwendet threshold=0 als Platzhalter (Floyd-Steinberg braucht keine
            # Schwelle), aber der Text-Durchgang ist eine echte Schwellwert-
            # Binarisierung — auf den Standardwert »Dunkel« (215) zurückfallen,
            # damit Glyphen voll schwarz herauskommen, statt durch lum < 0
            # weggewaschen zu werden.
            text_threshold = darkness_threshold if darkness_threshold > 0 else 215
            text_only = scene.render_to_image(
                dpi=PRINT_DPI,
                item_filter=lambda it: isinstance(it, TextBox),
                vertical_offset_mm=vertical_offset_mm,
            )
            text_bin = _binarize_image(text_only, text_threshold)

            image_only = scene.render_to_image(
                dpi=PRINT_DPI,
                item_filter=lambda it: isinstance(it, ImageBox),
                vertical_offset_mm=vertical_offset_mm,
            )
            image_bin = _dither_image(image_only)

            combined = _combine_min(text_bin, image_bin)
            if draw_flag_middle:
                _draw_flag_middle_line(combined, scene)
            combined.save(path, "PNG")
            return

        # Nur ein Inhaltstyp → einfach die gesamte Szene rastern
        image = scene.render_to_image(
            dpi=PRINT_DPI, vertical_offset_mm=vertical_offset_mm,
        )
        image = _dither_image(image)
        if draw_flag_middle:
            _draw_flag_middle_line(image, scene)
        image.save(path, "PNG")
        return

    # Einfacher Schwellwert-Modus
    image = scene.render_to_image(
        dpi=PRINT_DPI, vertical_offset_mm=vertical_offset_mm,
    )
    image = _binarize_image(image, darkness_threshold)
    if draw_flag_middle:
        _draw_flag_middle_line(image, scene)
    image.save(path, "PNG")


def _send_to_printer(
    image_path: str,
    printer_name: str,
    tape_width_mm: float,
    label_length_mm: int,
    auto_cut: bool,
    require_match: bool,
) -> tuple[bool, str]:
    """Ruft lp auf, um *image_path* auf *printer_name* zu drucken.

    Die benannten tz-*-PageSize-Einträge der PPD haben eine feste Länge
    (typischerweise 100 mm), daher senden wir eine Custom-Seitengröße, deren
    Maße dem tatsächlichen Editor-Etikett entsprechen.

    Die Ausrichtung entspricht den benannten tz-*-Einträgen der PPD — diese
    sind als ``[tape_pt length_pt]`` definiert (z. B. tz-12 = ``[34 284]``),
    also folgt Custom derselben Konvention: Custom.{tape_pt}x{length_pt}.

    Beide Maße werden auf ``_PPD_CUSTOM_MIN_PT`` (36 pt ≈ 12,7 mm)
    hochgesetzt — Brothers PPD lehnt Custom-Seiten unter diesem Minimum
    stillschweigend ab und fällt auf ``*DefaultPageSize=tz-24`` zurück, was
    dann auf das jeweils eingelegte Band fehldruckt. Details siehe den
    Kommentar zur Konstante auf Modulebene. Der Druckkopf nutzt weiterhin
    seine physische Bandbreite; die zusätzlichen ~0,7 mm »Seite« bleiben
    ungenutzt.

    Empirische Kalibrierung am 02./03.06.2026 (12-mm-Band, 71-mm-Etikett):
    Seite = Etikett exakt → Drucker schnitt ~5 mm am Anfang und ~10 mm am
    Ende ab (Inhalt »as ist ein Te« statt »Das ist ein Test«), obwohl
    *HWMargins in der PPD 0 0 0 0 ist. Der Treiber/die Firmware erzwingt also
    einen versteckten Mindestrand. Wir addieren ``PRINT_HARDWARE_LEADER_MM``
    zur Seitenlänge, um CUPS Raum zu geben, das PNG zu zentrieren, ohne dass
    der Treiber in unseren Inhaltsbereich schneidet.

    Gibt (Erfolg, Meldung) zurück.
    """
    total_length_mm = label_length_mm + PRINT_HARDWARE_LEADER_MM
    width_pt  = max(_PPD_CUSTOM_MIN_PT, round(tape_width_mm   * _PT_PER_MM))
    height_pt = max(_PPD_CUSTOM_MIN_PT, round(total_length_mm * _PT_PER_MM))
    page_size = f"Custom.{width_pt}x{height_pt}"

    cmd = [
        "lp",
        "-d", printer_name,
        "-o", f"PageSize={page_size}",
        "-o", f"AutoCut={'True' if auto_cut else 'False'}",
        "-o", f"RequireMatchingLabelSize={'True' if require_match else 'False'}",
        image_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, (result.stderr or result.stdout).strip()
    except FileNotFoundError:
        return False, tr("print.lp_missing")
    except subprocess.TimeoutExpired:
        return False, "Zeitüberschreitung beim Senden des Druckauftrags."
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Druckdialog
# ---------------------------------------------------------------------------

class PrintDialog(QDialog):
    """Ein einfacher Dialog zum Drucken des Etiketts über CUPS lp."""

    def __init__(self, scene: "LabelScene", parent=None):
        super().__init__(parent)
        self._scene = scene
        self.setWindowTitle(tr("print.title"))
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        # --- Druckerauswahl ---
        self._printer_combo = QComboBox()
        printers = _get_cups_printers()
        if printers:
            self._printer_combo.addItems(printers)
            # P-Touch vorauswählen, falls vorhanden
            for i, name in enumerate(printers):
                if "p700" in name.lower() or "ptouch" in name.lower() or "pt-" in name.lower():
                    self._printer_combo.setCurrentIndex(i)
                    break
        else:
            self._printer_combo.addItem(tr("print.no_printer_item"))
            self._printer_combo.setEnabled(False)

        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip(tr("print.refresh_tip"))
        btn_refresh.clicked.connect(self._refresh_printers)

        from PyQt6.QtWidgets import QHBoxLayout
        row = QHBoxLayout()
        row.addWidget(self._printer_combo)
        row.addWidget(btn_refresh)
        form.addRow(tr("print.printer_row"), row)

        # --- Band-/Seitengrößen-Info ---
        tw = scene.get_tape_width_mm()
        ll = scene.get_label_length_mm()
        self._info_label = QLabel(
            tr("print.label_info", tape=_fmt_mm(tw), length=ll)
        )
        form.addRow(tr("print.label_row"), self._info_label)

        # --- Konfliktwarnung ---
        self._mismatch_label = QLabel()
        self._mismatch_label.setWordWrap(True)
        self._mismatch_label.setStyleSheet(
            "QLabel { background: #FFF3CD; color: #856404; border: 1px solid #FFEAA7;"
            " border-radius: 4px; padding: 6px; }"
        )
        self._mismatch_label.setVisible(False)
        layout.addWidget(self._mismatch_label)

        # ERST verbinden, nachdem das Label-Widget existiert, um einen AttributeError während addItems() zu vermeiden
        self._printer_combo.currentTextChanged.connect(self._check_tape_mismatch)
        self._check_tape_mismatch(self._printer_combo.currentText())

        # --- Optionen ---
        self._autocut_cb = QCheckBox(tr("print.autocut"))
        self._autocut_cb.setChecked(True)
        layout.addWidget(self._autocut_cb)

        self._match_cb = QCheckBox(tr("print.match"))
        # Wenn die native Breite des eingelegten Bands in PostScript-Punkten
        # unter das Custom-Seiten-Minimum der PPD (36 pt ≈ 12,7 mm) fällt,
        # müssen wir die Custom-Seitenbreite auf 36 pt hochsetzen (siehe
        # _send_to_printer). Der hochgesetzte Wert entspricht dann keiner
        # benannten tz-*-Größe mehr, sodass die Band-Übereinstimmungsprüfung
        # des Druckers fehlschlägt und er rot blinkt. Die Option in diesem Fall
        # deaktivieren, damit der Nutzer sie nicht bei jedem Druck abwählen
        # muss. Bänder ≥ 18 mm (51 pt) liegen über der Untergrenze, und die
        # Prüfung bleibt als Sicherheitsnetz sinnvoll.
        if tw * _PT_PER_MM < _PPD_CUSTOM_MIN_PT:
            self._match_cb.setChecked(False)
            self._match_cb.setEnabled(False)
            self._match_cb.setToolTip(
                tr("print.match_tip_disabled", tape=_fmt_mm(tw))
            )
        else:
            self._match_cb.setChecked(True)
            self._match_cb.setToolTip(tr("print.match_tip"))
        layout.addWidget(self._match_cb)

        # --- Druckmodus (Binarisierungsstrategie) ---
        # Jeder Eintrag speichert (»dither«-Flag, Schwellwert). Ist dither
        # True, wird der Schwellwert ignoriert (Floyd-Steinberg nutzt seinen eigenen).
        self._darkness_combo = QComboBox()
        self._darkness_combo.addItem(tr("print.mode_line_light"),     (False, 150))
        self._darkness_combo.addItem(tr("print.mode_line_normal"),    (False, 190))
        self._darkness_combo.addItem(tr("print.mode_line_dark"),      (False, 215))
        self._darkness_combo.addItem(tr("print.mode_line_very_dark"), (False, 235))
        self._darkness_combo.addItem(tr("print.mode_photo"),          (True,  0))
        self._darkness_combo.setCurrentIndex(2)   # Standard: Strich – Dunkel
        self._darkness_combo.setToolTip(tr("print.mode_tip"))
        # Dither-Modus automatisch wählen, wenn die Szene ein Bild enthält
        from .image_item import ImageBox as _ImgBox
        if any(isinstance(it, _ImgBox) for it in scene.items()):
            self._darkness_combo.setCurrentIndex(4)

        form2 = QFormLayout()
        form2.addRow(tr("print.mode_row"), self._darkness_combo)

        # --- Vertikaler Versatz (mm) ---
        # Die tz-*-PPDs des P700 legen den druckbaren Streifen leicht
        # außermittig auf das Band, sodass Inhalt, den der Editor schön
        # zentriert zeigt, auf dem gedruckten Etikett dennoch an einer Kante
        # abschneiden kann. Dieses Drehfeld lässt den Nutzer die richtige
        # Verschiebung empirisch einstellen und merkt sie sich für das nächste Mal.
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-3.0, 3.0)
        self._offset_spin.setSingleStep(0.1)
        self._offset_spin.setDecimals(1)
        self._offset_spin.setSuffix(" mm")
        self._offset_spin.setToolTip(tr("print.offset_tip"))
        saved_offset = QSettings().value("print_vertical_offset_mm", 0.0, float)
        self._offset_spin.setValue(saved_offset)
        form2.addRow(tr("print.offset_row"), self._offset_spin)

        layout.addLayout(form2)

        # --- Schaltflächen ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("print.button_print"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("print.button_cancel"))
        buttons.accepted.connect(self._do_print)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _check_tape_mismatch(self, printer_name: str = "") -> None:
        """Vergleicht die Bandbreite der Szene mit dem PPD-Standard des Druckers; warnt bei Abweichung."""
        name = printer_name or self._printer_combo.currentText()
        if not name or name.startswith("("):
            self._mismatch_label.setVisible(False)
            return

        printer_mm = _get_printer_tape_mm(name)
        scene_mm   = self._scene.get_tape_width_mm()

        if printer_mm and printer_mm != scene_mm:
            self._mismatch_label.setText(
                tr("print.mismatch",
                   printer_mm=_fmt_mm(printer_mm),
                   scene_mm=_fmt_mm(scene_mm))
            )
            self._mismatch_label.setVisible(True)
        else:
            self._mismatch_label.setVisible(False)

    def _refresh_printers(self) -> None:
        printers = _get_cups_printers()
        self._printer_combo.clear()
        if printers:
            self._printer_combo.addItems(printers)
            self._printer_combo.setEnabled(True)
        else:
            self._printer_combo.addItem(tr("print.no_printer_item"))
            self._printer_combo.setEnabled(False)
        self._check_tape_mismatch()

    def _do_print(self) -> None:
        printer_name = self._printer_combo.currentText()
        if not printer_name or printer_name.startswith("("):
            QMessageBox.warning(self, tr("print.no_printer_title"), tr("print.no_printer_body"))
            return

        # In temporäre Datei rendern
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="pt_label_")
        os.close(tmp_fd)

        dither, threshold = self._darkness_combo.currentData()
        offset_mm = self._offset_spin.value()
        QSettings().setValue("print_vertical_offset_mm", offset_mm)
        draw_flag_middle = QSettings().value(
            "flag_print_middle_line", True, bool
        )

        try:
            _render_to_png(
                self._scene, tmp_path,
                darkness_threshold=threshold,
                dither=dither,
                vertical_offset_mm=offset_mm,
                draw_flag_middle=draw_flag_middle,
            )

            ok, msg = _send_to_printer(
                image_path      = tmp_path,
                printer_name    = printer_name,
                tape_width_mm   = self._scene.get_tape_width_mm(),
                label_length_mm = self._scene.get_label_length_mm(),
                auto_cut        = self._autocut_cb.isChecked(),
                require_match   = self._match_cb.isChecked(),
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if ok:
            QMessageBox.information(
                self, tr("print.sent_title"),
                tr("print.sent_body", printer=printer_name, msg=msg),
            )
            self.accept()
        else:
            QMessageBox.critical(
                self, tr("print.error_title"),
                tr("print.error_body", msg=msg),
            )


# ---------------------------------------------------------------------------
# Einstiegspunkt, der aus main_window aufgerufen wird
# ---------------------------------------------------------------------------

def print_label(scene: "LabelScene", parent=None) -> None:
    """Öffnet den Druckdialog."""
    dialog = PrintDialog(scene, parent)
    dialog.exec()
