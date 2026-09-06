# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Etikett-Zeichenfläche: QGraphicsScene + QGraphicsView für den Bearbeitungsbereich des Etiketts.

WYSIWYG-Schriftgröße
--------------------
Qt rendert Schriften in *logischen* Koordinaten anhand der logischen DPI des
Bildschirms. Damit eine Schrift in der korrekten physischen Größe gedruckt
wird, brauchen wir:

    PIXELS_PER_MM = screen_logical_dpi / 25.4

Mit diesem Wert ist der Skalierungsfaktor von Szene → Druckbild:

    scale = (print_dpi / 25.4) / PIXELS_PER_MM
          = (print_dpi / 25.4) / (screen_dpi / 25.4)
          = print_dpi / screen_dpi

Eine in der Szene gerenderte 12-pt-Schrift belegt  12 * screen_dpi/72  Szenenpixel.
Nach der Skalierung wird daraus  12 * screen_dpi/72 * print_dpi/screen_dpi
                              = 12 * print_dpi/72  Gerätepixel  ✓

PIXELS_PER_MM wird beim Erzeugen der LabelScene vom primären Bildschirm
abgefragt (nachdem QApplication existiert – siehe main.py).
"""

from __future__ import annotations

import json
import math

from PyQt6.QtCore import (
    Qt, QRectF, QPointF, QTimer, QByteArray, QMimeData, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QPainter, QPalette, QPen,
    QBrush, QPixmap, QPolygonF,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
)

from .text_item import TextBox
from .image_item import ImageBox

# Benutzerdefinierter MIME-Typ, um kopierte Etikettenelemente in die
# System-Zwischenablage zu legen. Das mitgeführte eigene JSON lässt Strg+C /
# Strg+V Textfelder UND Bilder (mit Größe, Schrift und Position) über die echte
# Zwischenablage hin- und herreichen.
PTLABEL_MIME = "application/x-ptlabel-items"

# ---------------------------------------------------------------------------
# Skalierung auf Modulebene – in LabelScene.__init__ aus der Bildschirm-DPI überschrieben
# ---------------------------------------------------------------------------
PIXELS_PER_MM: float = 96.0 / 25.4   # ≈ 3.779 px/mm  (Fallback = 96 DPI)

# Sicherheitsrand, der an jedem Ende des Etiketts angezeigt wird (mm)
MARGIN_MM: int = 5

# Standard-Zeichenflächenlänge (mm) – sichtbarer Bereich, nicht die Drucklänge
DEFAULT_LABEL_LENGTH_MM = 30

# Verfügbare Bandbreiten (Beschriftungstext → mm). Das 3,5-mm-Band ist ein
# echtes Brother-Produkt (TZe-2xx-Serie); Brothers CUPS-PPD nennt es lediglich
# »tz-4« — siehe TZE_PAGE_SIZES in printer.py.
TAPE_WIDTHS: dict[str, float] = {
    "3.5mm": 3.5,
    "6mm":   6,
    "9mm":   9,
    "12mm":  12,
    "18mm":  18,
    "24mm":  24,
}

# Druckbare Höhe (mm) für jede Brother-PT-P700-Bandbreite — Brothers
# Spezifikationswerte für die maximale Druckhöhe pro Band. Da die
# Render-to-Image-Pipeline unten ein PNG erzeugt, das GENAU der Größe des
# druckbaren Bereichs entspricht (keine weiße Auffüllung bis zu den
# Bandrändern), hat CUPS keinen »Auto-Fit«-Spielraum mehr, um unseren Inhalt
# aufs Band zu skalieren — der Inhalt wird in seiner wörtlichen physischen
# Größe auf den druckbaren Streifen des Druckers gedruckt.
TAPE_PRINTABLE_MM: dict[float, float] = {
    3.5: 2.2,
    6:   3.0,
    9:   6.0,
    12:  8.5,
    18:  13.0,
    24:  17.5,
}


def _printable_mm(tape_mm: float) -> float:
    """Gibt die druckbare Höhe (mm) für eine gegebene Bandbreite zurück."""
    return TAPE_PRINTABLE_MM.get(tape_mm, float(tape_mm))


# Zusätzlicher Sicherheitseinzug (mm) beim automatischen Platzieren von
# BILD-Elementen innerhalb des druckbaren Bereichs. Die TAPE_PRINTABLE_MM-Werte
# enthalten bereits Brothers Spezifikationspuffer, aber randbündiger Bildinhalt
# wird durch mechanische Toleranz dennoch um ein, zwei Pixel beschnitten. Text
# hat natürlichen Leerraum über/unter der Glyphen-»Tinte« und stößt daher
# selten an den Rand — Bilder, die die volle druckbare Höhe ausfüllen, tun das,
# daher erhalten sie standardmäßig diesen zusätzlichen Abstand. Der Nutzer kann
# das Bild über die Griffe größer ziehen.
IMAGE_INSET_MM: float = 0.5

# Zusätzliche Custom-Seitenlänge, die zum Editor-Etikett addiert wird, damit der
# Drucker den Inhalt nicht abschneidet. Empirische Ergebnisse auf PT-P700 +
# Open-Source-ptouch-Treiber-PPD (02.06.2026):
#
#   Vorlauf = 21,6 mm → Band ≈ Etikett + 22 mm, Inhalt stets vollständig.
#   Vorlauf = 0    mm → Band ≈ Etikett, aber Inhalt an BEIDEN Enden
#                       abgeschnitten (~5 mm am Anfang + ~10 mm am Ende).
#                       Der Drucker/Treiber erzwingt also einen Mindestrand,
#                       obwohl *HWMargins in der PPD 0 0 0 0 ist.
#
# 10 mm ist ein Kompromiss, der über dem erzwungenen Mindestrand liegen sollte
# und das Band dennoch nahe an der Editor-Länge hält. Falls 10 mm noch
# abschneidet, Richtung 15–20 mm erhöhen; falls es passt, beim nächsten Mal
# 5 mm probieren, um weiter zu verkleinern.
PRINT_HARDWARE_LEADER_MM: float = 10.0


def _image_safe_mm(tape_mm: float) -> float:
    """Standard-Bildhöhe (mm) — druckbarer Bereich minus Sicherheitseinzug oben
    und unten."""
    return max(1.0, _printable_mm(tape_mm) - 2 * IMAGE_INSET_MM)

# Visuelle Farben
_COLOR_SCENE_BG          = QColor("#6B6B6B")   # Zeichenflächen-Umfeld, helle Oberfläche
_COLOR_SCENE_BG_DARK     = QColor("#3A3A3A")   # Zeichenflächen-Umfeld, dunkle Oberfläche
_COLOR_LABEL_BG          = Qt.GlobalColor.white
_COLOR_LABEL_BORDER      = QColor("#444444")
_COLOR_MARGIN_FILL       = QColor(255, 200, 200, 100)   # hellrote Tönung (horiz. Sicherheitsränder)
_COLOR_MARGIN_LINE       = QColor("#BB3333")            # gestrichelte Begrenzungslinie
_COLOR_UNPRINTABLE_FILL  = QColor("#E0E0E0")            # hellgrau für vert. nicht druckbare Streifen
_COLOR_UNPRINTABLE_LINE  = QColor("#999999")            # Grenze zwischen druckbar/nicht druckbar
_COLOR_RULER_BG          = QColor("#F5F5F5")
_COLOR_RULER_LINE        = QColor("#333333")
_COLOR_RULER_TICK_MINOR  = QColor("#9A9A9A")
_COLOR_RULER_TICK_HALF   = QColor("#5A5A5A")
_COLOR_RULER_TICK_MAJOR  = QColor("#222222")
_COLOR_RULER_LENGTH      = QColor("#0078D7")
_COLOR_RULER_INDICATOR   = QColor("#D7372D")
_COLOR_FLAG_MIDDLE_FILL  = QColor(120, 170, 230, 70)    # hellblaues Band: Kabel-Wickelzone
_COLOR_FLAG_MIDDLE_LINE  = QColor("#2C6BB3")            # Falzlinie in der Mitte des Bandes
_COLOR_FLAG_COPY_FILL    = QColor(120, 230, 170, 45)    # zarte grüne Tönung über der gespiegelten Hälfte
_SHADOW_OFFSET           = 4

# Supersampling-Faktor für das Live-Pixmap des Fähnchen-Spiegel-Overlays, damit
# es beim Hineinzoomen der Zeichenfläche scharf bleibt.
_FLAG_OVERLAY_SCALE      = 3


class RulerItem(QGraphicsItem):
    """Zentimeter-Lineal, das über dem Band angezeigt wird.

    Rendert mm-/Halb-cm-/cm-Teilstriche, cm-Zahlen, die Gesamtlänge des
    Etiketts in cm am rechten Ende sowie rote vertikale Markierungsstriche für
    die linke und rechte Kante jedes aktuell ausgewählten Inhaltselements —
    damit der Nutzer beim Verschieben exakte Positionen ablesen kann."""

    HEIGHT_PX = 16.0   # Höhe der Linealleiste in Szenenpixeln
    GAP_PX    = 4.0    # Abstand zwischen Linealunterkante und Bandoberkante
    RIGHT_PAD = 70.0   # zusätzlicher Platz für die »X,XX cm«-Gesamtlängenbeschriftung

    def __init__(self):
        super().__init__()
        self._width_px: float = 0.0
        self._indicator_xs: list[float] = []
        self.setZValue(-0.3)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def set_geometry(self, label_width_px: float, tape_top_y: float) -> None:
        self.prepareGeometryChange()
        self._width_px = label_width_px
        # Die Unterkante des Lineals sitzt GAP_PX über der Bandoberkante
        self.setPos(0, tape_top_y - self.GAP_PX - self.HEIGHT_PX)
        self.update()

    def set_indicators(self, xs: list[float]) -> None:
        new = list(xs)
        if new != self._indicator_xs:
            self._indicator_xs = new
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-2, 0, self._width_px + self.RIGHT_PAD, self.HEIGHT_PX)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        h = self.HEIGHT_PX
        w = self._width_px
        if w <= 0:
            return

        # --- Hintergrundleiste + untere Ankerlinie ---
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(_COLOR_RULER_BG))
        painter.drawRect(QRectF(0, 0, w, h))
        painter.setPen(QPen(_COLOR_RULER_LINE, 1))
        painter.drawLine(QPointF(0, h), QPointF(w, h))

        # --- Teilstriche (jeder mm), mit cm-Zahlen ---
        mm_count = int(round(w / PIXELS_PER_MM))

        font = QFont(painter.font())
        font.setPointSizeF(6.5)
        painter.setFont(font)
        fm = QFontMetricsF(font)

        # Oben einen Streifen für die cm-Zahlen reservieren, damit die langen
        # Hauptteilstriche (die von der unteren Linie aufsteigen) knapp
        # unterhalb der Ziffern enden, statt in sie hineinzuragen.
        num_band  = round(fm.ascent()) + 2
        tick_area = h - num_band

        pen_minor = QPen(_COLOR_RULER_TICK_MINOR, 0.6)
        pen_half  = QPen(_COLOR_RULER_TICK_HALF,  0.8)
        pen_major = QPen(_COLOR_RULER_TICK_MAJOR, 1.0)
        text_pen  = QPen(_COLOR_RULER_TICK_MAJOR)

        for mm in range(mm_count + 1):
            x = mm * PIXELS_PER_MM
            if mm % 10 == 0:
                painter.setPen(pen_major)
                tick_h = tick_area
            elif mm % 5 == 0:
                painter.setPen(pen_half)
                tick_h = tick_area * 0.6
            else:
                painter.setPen(pen_minor)
                tick_h = tick_area * 0.32
            painter.drawLine(QPointF(x, h), QPointF(x, h - tick_h))

            if mm % 10 == 0 and mm > 0:
                painter.setPen(text_pen)
                txt = str(mm // 10)
                tw = fm.horizontalAdvance(txt)
                painter.drawText(QPointF(x - tw / 2, fm.ascent()), txt)

        # --- Gesamtlänge (cm) am rechten Ende ---
        total_cm = w / PIXELS_PER_MM / 10.0
        font2 = QFont(painter.font())
        font2.setPointSizeF(8.0)
        font2.setBold(True)
        painter.setFont(font2)
        fm2 = QFontMetricsF(font2)
        label = f"{total_cm:.2f} cm".replace(".", ",")
        painter.setPen(QPen(_COLOR_RULER_LENGTH))
        painter.drawText(QPointF(w + 4, h - (h - fm2.ascent()) / 2 - 1), label)

        # --- Positionsmarkierungen ---
        if self._indicator_xs:
            painter.setPen(QPen(_COLOR_RULER_INDICATOR, 1.5))
            painter.setBrush(QBrush(_COLOR_RULER_INDICATOR))
            for x in self._indicator_xs:
                painter.drawLine(QPointF(x, 0), QPointF(x, h))
                tri = QPolygonF([
                    QPointF(x - 3.5, h),
                    QPointF(x + 3.5, h),
                    QPointF(x,       h - 6),
                ])
                painter.drawPolygon(tri)


class LabelScene(QGraphicsScene):
    """Szene, die das weiße Etikett-Rechteck und alle TextBox-Elemente enthält."""

    labelLengthChanged = pyqtSignal(int)   # ausgelöst, wenn sich die Zeichenflächenlänge ändert

    def __init__(self, parent=None):
        super().__init__(parent)

        # Echte Bildschirm-DPI abfragen, damit Schriften auf dem Bildschirm
        # physisch korrekt sind und zu jeder Druck-DPI korrekt skalieren.
        global PIXELS_PER_MM
        screen = QApplication.primaryScreen()
        if screen:
            PIXELS_PER_MM = screen.logicalDotsPerInch() / 25.4

        self._tape_width_mm   = 12
        self._label_length_mm = DEFAULT_LABEL_LENGTH_MM
        self._auto_length     = True   # Zeichenfläche erweitern, wenn Inhalt überläuft
        self._rebuilding      = False  # Schutz gegen re-entrante Neuaufbauten

        # --- Kabelfähnchen-Modus ---
        # Der Streifen wickelt sich in der Mitte um ein Kabel; die beiden Enden
        # bilden ein lesbares Fähnchen. Das linke Fähnchen enthält den Inhalt,
        # das mittlere Band ist die Wickelzone (auf das Kabel dimensioniert),
        # und das rechte Fähnchen dupliziert das linke (gleiche Ausrichtung),
        # sofern _flag_copy nicht aus ist.
        self._flag_mode          = False
        self._cable_diameter_mm  = 5.0
        self._flag_middle_mm     = math.pi * self._cable_diameter_mm
        self._flag_width_mm      = MARGIN_MM * 2 + 5.0   # Halbfähnchenbreite (wächst passend mit)
        self._flag_copy          = True
        self._flag_overlay: QGraphicsPixmapItem | None = None
        self._flag_overlay_sig   = None
        self._flag_overlay_timer = QTimer(self)
        self._flag_overlay_timer.setSingleShot(True)
        self._flag_overlay_timer.setInterval(80)
        self._flag_overlay_timer.timeout.connect(self._refresh_flag_overlay)

        # Von uns verwaltete Elemente (bei Bandbreitenänderung neu aufgebaut)
        self._shadow_item:  QGraphicsRectItem | None = None
        self._label_item:   QGraphicsRectItem | None = None
        self._ruler_item:   RulerItem | None = None
        self._bg_items:     list = []          # Randzonen + Linien

        # Wie oft der aktuelle Zwischenablageninhalt eingefügt wurde; dient dem
        # kaskadierenden Einfüge-Versatz. Bei jedem Kopieren auf 0 zurückgesetzt.
        self._paste_count: int = 0

        # Entprell-Timer für die Auto-Erweiterung, damit schnelle Bewegungen _rebuild_label nicht überlasten
        self._expand_timer = QTimer(self)
        self._expand_timer.setSingleShot(True)
        self._expand_timer.setInterval(120)
        self._expand_timer.timeout.connect(self._do_auto_expand)
        self.changed.connect(self._schedule_auto_expand)
        # Die Positionsmarkierungen des Lineals live aktualisieren, sobald sich
        # ein Element bewegt oder die Auswahl ändert. set_indicators bricht ab,
        # wenn sich die Werte nicht geändert haben, daher ist dies günstig.
        self.changed.connect(self._update_ruler_indicators)
        self.selectionChanged.connect(self._update_ruler_indicators)
        # Das Fähnchen-Spiegel-Overlay mit Bearbeitungen am linken Fähnchen synchron halten.
        self.changed.connect(self._schedule_flag_overlay)

        self.apply_theme_background()
        self._rebuild_label()

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def apply_theme_background(self, dark: bool | None = None) -> None:
        """Wählt die Farbe des Zeichenflächen-Umfelds passend zum aktiven
        UI-Design.

        Bei einem Live-Wechsel *dark* explizit übergeben; die Palette direkt
        nach ``setPalette`` auszulesen ist unzuverlässig (sie pflanzt sich
        asynchron fort). Das Etikett selbst bleibt weiß (es bildet das physische
        Band ab); nur der Bereich darum herum verdunkelt sich im Darkmode für
        ein ruhigeres Erscheinungsbild."""
        if dark is None:
            app = QApplication.instance()
            dark = (app is not None and
                    app.palette().color(QPalette.ColorRole.Window).lightness() < 128)
        self.setBackgroundBrush(
            QBrush(_COLOR_SCENE_BG_DARK if dark else _COLOR_SCENE_BG)
        )

    def set_tape_width(self, width_mm: float) -> None:
        self._tape_width_mm = width_mm
        self._rebuild_label()

    def get_tape_width_mm(self) -> float:
        return self._tape_width_mm

    def get_printable_height_mm(self) -> float:
        """Nutzbare Druckhöhe (mm) für das aktuelle Band – kleiner als die
        physische Bandbreite, weil der Druckkopf des P700 nicht das ganze Band
        überspannt."""
        return _printable_mm(self._tape_width_mm)

    # ---- Kabelfähnchen-Modus ----

    def set_flag_mode(self, on: bool) -> None:
        on = bool(on)
        if on == self._flag_mode:
            return
        self._flag_mode = on
        if on:
            # Die Halbfähnchenbreite aus dem bereits vorhandenen Inhalt ableiten.
            self._flag_width_mm = self._flag_needed_width_mm()
            self._label_length_mm = self._flag_total_length_mm()
        self._safe_rebuild()
        self._refresh_flag_overlay()
        self.labelLengthChanged.emit(self._label_length_mm)

    def get_flag_mode(self) -> bool:
        return self._flag_mode

    def set_cable_diameter_mm(self, mm: float) -> None:
        """Setzt den Kabeldurchmesser; das mittlere Band folgt dem Umfang."""
        self._cable_diameter_mm = max(0.1, float(mm))
        self.set_flag_middle_mm(math.pi * self._cable_diameter_mm)

    def get_cable_diameter_mm(self) -> float:
        return self._cable_diameter_mm

    def set_flag_middle_mm(self, mm: float) -> None:
        self._flag_middle_mm = max(0.0, float(mm))
        if self._flag_mode:
            self._label_length_mm = self._flag_total_length_mm()
            self._safe_rebuild()
            self._refresh_flag_overlay()
            self.labelLengthChanged.emit(self._label_length_mm)

    def get_flag_middle_mm(self) -> float:
        return self._flag_middle_mm

    def set_flag_copy(self, on: bool) -> None:
        self._flag_copy = bool(on)
        self._safe_rebuild()
        self._refresh_flag_overlay()

    def get_flag_copy(self) -> bool:
        return self._flag_copy

    def get_flag_width_mm(self) -> float:
        return self._flag_width_mm

    def _flag_total_length_mm(self) -> int:
        # AUFrunden, damit die ganzzahlige Etikettenlänge das rechte Fähnchen
        # stets vollständig abdeckt (2·Fähnchen + Mitte kann gebrochen sein);
        # andernfalls würde der letzte Millimeterbruchteil des rechten
        # Fähnchens vom Druck abgeschnitten.
        return int(math.ceil(2 * self._flag_width_mm + self._flag_middle_mm))

    def _flag_needed_width_mm(self) -> float:
        """Halbfähnchenbreite, die nötig ist, um den aktuellen Inhalt aufzunehmen.

        Elemente des linken Fähnchens werden ab x=0 gemessen; Elemente des
        rechten Fähnchens (nur vorhanden, wenn die Auto-Kopie aus ist) werden ab
        dem Ursprung des rechten Fähnchens gemessen, damit beide Hälften
        symmetrisch bleiben. Gibt nie weniger als ein sinnvolles Minimum zurück.
        """
        floor_mm    = MARGIN_MM * 2 + 5.0
        middle      = self._flag_middle_mm
        center_mm   = self._flag_width_mm + middle / 2.0
        right_org   = self._flag_width_mm + middle
        left_extent = 0.0
        right_over  = 0.0
        for item in self.items():
            if not isinstance(item, (TextBox, ImageBox)):
                continue
            left_mm  = item.pos().x() / PIXELS_PER_MM
            right_mm = (item.pos().x() + item._rect.width()) / PIXELS_PER_MM
            if (left_mm + right_mm) / 2.0 < center_mm:
                left_extent = max(left_extent, right_mm)
            else:
                right_over = max(right_over, right_mm - right_org)
        return max(floor_mm, left_extent + MARGIN_MM, right_over + MARGIN_MM)

    def _flag_recompute(self) -> None:
        """Vergrößert die Halbfähnchenbreite passend zum Inhalt und aktualisiert die Länge."""
        if not self._flag_mode:
            return
        needed = self._flag_needed_width_mm()
        if needed > self._flag_width_mm + 0.01:   # nur wachsen (keine Oszillation)
            self._flag_width_mm = needed
        new_len = self._flag_total_length_mm()
        if new_len != self._label_length_mm:
            self._label_length_mm = new_len
            self._safe_rebuild()
            self.labelLengthChanged.emit(self._label_length_mm)

    def get_label_length_mm(self) -> int:
        """Anzeigelänge des Zeichenflächen-Etiketts (nicht die Drucklänge)."""
        return self._label_length_mm

    def get_print_length_mm(self) -> float:
        """Mindest-Etikettenlänge für den aktuellen Inhalt zuzüglich Sicherheitsränder.

        = linker Rand (5 mm) + rechteste Inhaltskante + rechter Rand (5 mm)
        """
        max_right_px = 0.0
        for item in self.items():
            if isinstance(item, (TextBox, ImageBox)):
                right_px = item.pos().x() + item._rect.width()
                if right_px > max_right_px:
                    max_right_px = right_px

        content_right_mm = max_right_px / PIXELS_PER_MM
        # Mindestens: zwei Ränder + ein winziger Inhaltsstreifen
        return max(content_right_mm + MARGIN_MM, MARGIN_MM * 2 + 5)

    def set_auto_length(self, auto: bool) -> None:
        self._auto_length = auto
        if auto:
            self._do_auto_expand()

    def set_label_length_mm(self, mm: int) -> None:
        self._label_length_mm = mm
        self._safe_rebuild()
        self.labelLengthChanged.emit(self._label_length_mm)

    def _schedule_auto_expand(self) -> None:
        if self._rebuilding:
            return
        if self._flag_mode or self._auto_length:
            self._expand_timer.start()

    def _is_text_editing(self) -> bool:
        """True, solange ein Textfeld im Inline-Bearbeitungsmodus ist.

        Fähnchen-Neuaufbauten und das Rendern des Spiegel-Overlays schalten die
        Sichtbarkeit von Elementen um und rendern die Szene neu, was dem gerade
        bearbeiteten Textfeld den Tastaturfokus entziehen würde. Daher frieren
        wir diese Aktualisierungen während der Bearbeitung ein und wenden sie in
        _on_text_edit_finished() erneut an."""
        f = self.focusItem()
        return (isinstance(f, QGraphicsTextItem) and
                bool(f.textInteractionFlags() &
                     Qt.TextInteractionFlag.TextEditorInteraction))

    def _on_text_edit_finished(self) -> None:
        """Von einem _EditableText aufgerufen, wenn es den Fokus verliert —
        die während der Bearbeitung eingefrorene Fähnchenlänge / das Overlay
        erneut anwenden."""
        if not self._flag_mode:
            return
        self._flag_recompute()
        self._refresh_flag_overlay()

    def _do_auto_expand(self) -> None:
        if self._rebuilding:
            return
        # Im Fähnchen-Modus wird die Länge aus den Fähnchenhälften + Mitte abgeleitet.
        if self._flag_mode:
            if not self._is_text_editing():
                self._flag_recompute()
            return
        if not self._auto_length:
            return
        # get_print_length_mm addiert bereits einen 5-mm-Rechtsrand; auf den nächsten mm aufrunden
        needed_mm = int(self.get_print_length_mm()) + 1
        if needed_mm > self._label_length_mm:
            self._label_length_mm = needed_mm
            self._safe_rebuild()
            self.labelLengthChanged.emit(self._label_length_mm)

    def _schedule_flag_overlay(self) -> None:
        if self._rebuilding:
            return
        if self._flag_mode and self._flag_copy:
            self._flag_overlay_timer.start()

    def _safe_rebuild(self) -> None:
        self._rebuilding = True
        try:
            self._rebuild_label()
        finally:
            self._rebuilding = False

    def add_text_box(self, font=None, initial_text: str | None = None) -> TextBox:
        """Fügt eine neue TextBox hinzu, an die Schrift angepasst und vertikal
        im druckbaren Bereich zentriert.

        Ist *initial_text* angegeben, wird das Feld so verbreitert, dass dieser
        Text in eine einzige Zeile passt, sodass der Aufrufer die Größe nicht
        nachträglich anpassen muss (genutzt von »Datum und Uhrzeit einfügen«)."""
        item = TextBox()
        if font is not None:
            item.set_font(font)

        if initial_text:
            fm = QFontMetricsF(item.get_font())
            box_w_px = max(fm.horizontalAdvance(initial_text) + 4,
                           20 * PIXELS_PER_MM, 40.0)
        else:
            # Breite: bequemer Standard; die Höhe wird von den Schriftmetriken in
            # TextBox._update_text_geometry bestimmt, daher setzen wir hier nur einen Startwert.
            box_w_px = max(20 * PIXELS_PER_MM, 40.0)

        item._rect = QRectF(0, 0, box_w_px, 1.0)
        item._update_text_geometry()           # rastet die Höhe auf die Texthöhe ein
        box_h_px = item._rect.height()

        printable_h_px = _printable_mm(self._tape_width_mm) * PIXELS_PER_MM
        x = MARGIN_MM * PIXELS_PER_MM
        y = (printable_h_px - box_h_px) / 2.0

        item.setPos(x, y)
        self.addItem(item)
        if initial_text:
            item.set_text(initial_text)
        self.clearSelection()
        item.setSelected(True)
        return item

    def add_image_box(self, pixmap: QPixmap) -> ImageBox | None:
        """Fügt ein Bild hinzu, automatisch auf die druckbare Bereichshöhe
        skaliert (abzüglich eines kleinen Sicherheitseinzugs, damit die Kanten
        am Drucker nicht abschneiden).

        Das Pixmap wird in 8-Bit-Graustufen umgewandelt, damit die
        Editor-Vorschau widerspiegelt, was der Thermodrucker tatsächlich
        erzeugen kann — Farben wie die grünen Blätter eines roten Apfels haben
        sehr unterschiedliche Helligkeit, und der Nutzer sähe sonst eine
        irreführende Farbvorschau, die im Druck zu einem flachen schwarzen
        Klecks wird.

        Gibt None zurück, wenn das Pixmap null/ungültig ist.
        """
        if pixmap is None or pixmap.isNull():
            return None

        gray_img = pixmap.toImage().convertToFormat(
            QImage.Format.Format_Grayscale8
        )
        pixmap = QPixmap.fromImage(gray_img)

        item = ImageBox(pixmap)

        printable_h_px = _printable_mm(self._tape_width_mm) * PIXELS_PER_MM
        safe_h_px      = _image_safe_mm(self._tape_width_mm) * PIXELS_PER_MM
        inset_px       = (printable_h_px - safe_h_px) / 2.0

        img_w = pixmap.width()
        img_h = pixmap.height()
        if img_h > 0:
            scale = safe_h_px / img_h
            item.set_size(img_w * scale, safe_h_px)

        # Am linken Sicherheitsrand platzieren, vertikal im druckbaren Bereich
        # zentriert (sodass der Einzug oben und unten gespiegelt ist).
        x = MARGIN_MM * PIXELS_PER_MM
        item.setPos(x, inset_px)
        self.addItem(item)
        self.clearSelection()
        item.setSelected(True)
        return item

    def paste_image_from_clipboard(self) -> bool:
        """Fügt ein Bild aus der System-Zwischenablage ein. Gibt bei Erfolg True zurück."""
        cb = QApplication.clipboard()
        img = cb.image()
        if img.isNull():
            return False
        pixmap = QPixmap.fromImage(img)
        return self.add_image_box(pixmap) is not None

    def copy_selection(self) -> bool:
        """Kopiert die ausgewählten Textfelder und Bilder in die System-Zwischenablage.

        Gibt True zurück, wenn etwas kopiert wurde. Beide Elementtypen werden
        als JSON unter PTLABEL_MIME gespeichert; Textfelder stellen ihren Text
        zusätzlich als reinen Text bereit, sodass er in andere Anwendungen
        eingefügt werden kann."""
        from . import serialization as _ser

        items = [it for it in self.selectedItems()
                 if isinstance(it, (TextBox, ImageBox))]
        if not items:
            return False

        payload = {"items": [d for it in items
                             if (d := _ser.item_to_dict(it)) is not None]}
        mime = QMimeData()
        mime.setData(PTLABEL_MIME,
                     QByteArray(json.dumps(payload).encode("utf-8")))

        texts = [it.get_text() for it in items if isinstance(it, TextBox)]
        if texts:
            mime.setText("\n".join(texts))

        # Das erste ausgewählte Bild zusätzlich als echtes Bitmap bereitstellen,
        # damit andere Apps und Zwischenablage-Manager (z. B. Diodon) es als Bild
        # erkennen. Unser eigenes Einfügen bevorzugt weiterhin PTLABEL_MIME, dies
        # ist also rein additiv und beeinträchtigt die Einfügetreue in der App nicht.
        imgs = [it for it in items if isinstance(it, ImageBox)]
        if imgs:
            mime.setImageData(imgs[0].get_pixmap().toImage())

        QApplication.clipboard().setMimeData(mime)
        self._paste_count = 0   # das nächste Einfügen startet eine frische Versatz-Kaskade
        return True

    def duplicate_selection(self) -> bool:
        """Dupliziert ausgewählte TextBox-/ImageBox-Elemente an Ort und Stelle
        mit kleinem Versatz. Rührt die interne Kopieren/Einfügen-Zwischenablage
        nicht an."""
        sources = [it for it in self.selectedItems()
                   if isinstance(it, (TextBox, ImageBox))]
        if not sources:
            return False
        self.clearSelection()
        offset = 10.0
        for src in sources:
            if isinstance(src, TextBox):
                new_item = TextBox()
                new_item._auto_width = src._auto_width
                new_item._rect = QRectF(src._rect)
                new_item._update_text_geometry()
                new_item.set_font(src.get_font())
                new_item.set_vertical_align(src.get_vertical_align())
                new_item.set_text(src.get_text())
            else:
                new_item = ImageBox(src.get_pixmap())
                new_item.set_size(src._rect.width(), src._rect.height())
            new_item.setPos(src.pos().x() + offset, src.pos().y())
            self.addItem(new_item)
            new_item.setSelected(True)
        return True

    def clear_content(self) -> None:
        """Entfernt alle TextBox-/ImageBox-Elemente und lässt die Szenen-Bedienelemente unangetastet."""
        for item in list(self.items()):
            if isinstance(item, (TextBox, ImageBox)):
                self.removeItem(item)

    def select_all_content(self) -> None:
        for item in self.items():
            if isinstance(item, (TextBox, ImageBox)):
                item.setSelected(True)

    def has_content(self) -> bool:
        return any(isinstance(it, (TextBox, ImageBox)) for it in self.items())

    def paste_clipboard(self) -> bool:
        """Fügt Etikettenelemente aus der System-Zwischenablage ein. Gibt True
        zurück, wenn unsere eigenen Elementdaten (PTLABEL_MIME) vorhanden waren
        und eingefügt wurden, sonst False, damit der Aufrufer ersatzweise ein
        rohes Bild aus der Zwischenablage einfügen kann."""
        from . import serialization as _ser

        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(PTLABEL_MIME):
            return False
        try:
            data = json.loads(bytes(mime.data(PTLABEL_MIME)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return False
        entries = data.get("items", [])
        if not entries:
            return False

        # Jedes weitere Einfügen etwas weiter versetzen, damit wiederholtes
        # Strg+V diagonal stapelt, statt exakt auf dem letzten Einfügen zu landen.
        self._paste_count = getattr(self, "_paste_count", 0) + 1
        offset = 10.0 * self._paste_count

        self.clearSelection()
        pasted = False
        for entry in entries:
            item = _ser.item_from_dict(entry)
            if item is None:
                continue
            item.setPos(item.pos().x() + offset, item.pos().y() + offset)
            self.addItem(item)
            item.setSelected(True)
            pasted = True
        return pasted

    def render_to_image(
        self,
        dpi: int = 180,
        item_filter=None,
        vertical_offset_mm: float = 0.0,
    ) -> QImage:
        """Rendert das Etikett (mit automatisch angepasster Länge) in ein
        QImage mit *dpi* DPI.

        Alle UI-Bedienelemente (Auswahlgriffe, Textfeldrahmen,
        Randmarkierungen) werden unterdrückt, sodass das Bild nur druckbaren
        Inhalt enthält.

        *item_filter* ist ein optionales ``callable(QGraphicsItem) -> bool``.
        Ist es angegeben, wird jede TextBox oder ImageBox, für die der Filter
        False zurückgibt, für diesen Render-Durchgang vorübergehend
        ausgeblendet. Die Druck-Pipeline nutzt dies, um Nur-Text- und
        Nur-Bild-Durchgänge getrennt zu rendern (sodass jeder mit dem für
        diesen Inhaltstyp besten Algorithmus binarisiert werden kann) und die
        Ergebnisse zu kombinieren.

        *vertical_offset_mm* verschiebt den gerenderten Inhalt innerhalb des
        bandfüllenden PNG. Negative Werte verschieben den Inhalt auf dem Band
        nach OBEN, positive nach UNTEN. Zum Ausgleich von Druckern, deren
        tatsächlicher druckbarer Bereich nicht symmetrisch auf dem Band liegt
        (z. B. scheint das tz-12 des P700 um einige Zehntelmillimeter zur
        Oberkante verschoben zu sein und schneidet Unterlängen unten ab).
        """
        import tuxlabel.text_item as _ti

        selected = self.selectedItems()
        self.clearSelection()

        # Inhaltselemente, die der Aufrufer ausschließen möchte, vorübergehend ausblenden
        extra_hidden: list = []
        if item_filter is not None:
            for item in self.items():
                if isinstance(item, (TextBox, ImageBox)) and not item_filter(item):
                    if item.isVisible():
                        item.setVisible(False)
                        extra_hidden.append(item)

        # Randzonen / Begrenzungslinien ausblenden (nur UI, nicht gedruckt)
        for item in self._bg_items:
            item.setVisible(False)

        # Schlagschatten ausblenden (halbtransparentes Schwarz; blutet nach der Binarisierung als dunkle Linie an den Kanten aus)
        if self._shadow_item:
            self._shadow_item.setVisible(False)

        # Lineal ausblenden (UI-Element, nie Teil des Drucks)
        if self._ruler_item:
            self._ruler_item.setVisible(False)

        # Das Live-Spiegel-Overlay ausblenden — das rechte Fähnchen wird
        # stattdessen unten durch einen exakten Pixel-Blit in voller
        # Druckauflösung reproduziert.
        _overlay_was_visible = False
        if self._flag_overlay is not None and self._flag_overlay.isVisible():
            self._flag_overlay.setVisible(False)
            _overlay_was_visible = True

        # Etikettenrahmen ausblenden, damit er nicht als dunkle Linie an den Bandrändern druckt
        _saved_label_pen = None
        if self._label_item:
            _saved_label_pen = self._label_item.pen()
            self._label_item.setPen(QPen(Qt.PenStyle.NoPen))

        # Szenenhintergrund auf Weiß setzen, damit die graue Szenenfarbe nicht in die Randpixel ausblutet
        _saved_bg = self.backgroundBrush()
        self.setBackgroundBrush(QBrush(Qt.GlobalColor.white))

        # TextBox.paint() anweisen, alle Verzierungen zu überspringen (Rahmen, Griffe, Tönung)
        _ti._PRINTING = True

        try:
            # PNG-Maße = nur druckbarer Bereich (NICHT das ganze Band).
            #
            # Früher erzeugte dies ein bandfüllendes PNG mit weißer Auffüllung
            # über/unter dem druckbaren Bereich, in der Hoffnung, der Drucker
            # würde diese weißen Ränder respektieren. In der Praxis passte
            # CUPS/der P700-Treiber unseren Inhalt automatisch in seinen
            # abbildbaren Bereich ein: je kleiner das Verhältnis von Inhalt zu
            # PNG, desto aggressiver die Dehnung — bei TAPE_PRINTABLE_MM=6 eines
            # 12-mm-Bands sprengte die 2×-Dehnung (oder schlimmer) 14-pt-Text
            # über die Bandränder hinaus.
            #
            # Indem das PNG exakt auf den druckbaren Bereich dimensioniert wird,
            # füllt der Inhalt das PNG, der Drucker hat keine Auffüllung zum
            # Einpassen auf die Seite, und der Inhalt druckt in seiner wörtlichen
            # physischen Größe (oder mit einer bekannten, festen Dehnung aus dem
            # abbildbaren Bereich der PPD, die zumindest vorhersehbar ist).
            print_length_mm = float(self._label_length_mm)
            printable_mm    = _printable_mm(self._tape_width_mm)
            px_per_mm       = dpi / 25.4

            # Das PNG wird nur auf die Etikettenlänge des Editors dimensioniert —
            # der ~21,6-mm-Hardware-Vorlauf des P700 wird NICHT ins PNG
            # gerendert, sondern nur in der Custom-Seitenlänge berücksichtigt,
            # die wir an CUPS senden (siehe _send_to_printer in printer.py).
            w_px       = max(1, round(print_length_mm * px_per_mm))
            h_print_px = max(1, round(printable_mm    * px_per_mm))

            # vertical_offset_mm verschiebt den Inhalt innerhalb des erfassten
            # Quellbereichs: positiv = Inhalt bewegt sich im Druck nach unten.
            source_y_offset = -vertical_offset_mm * PIXELS_PER_MM

            image = QImage(w_px, h_print_px, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.white)

            # Die Druck-DPI in den Bild-Metadaten speichern (PNG / EXIF)
            dpm = round(dpi / 0.0254)
            image.setDotsPerMeterX(dpm)
            image.setDotsPerMeterY(dpm)

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            source_rect = QRectF(
                0, source_y_offset,
                print_length_mm * PIXELS_PER_MM,
                printable_mm    * PIXELS_PER_MM,
            )
            target_rect = QRectF(0, 0, w_px, h_print_px)
            self.render(painter, target_rect, source_rect)
            painter.end()

            # Fähnchen-Auto-Kopie: den »Tinten«-Block des linken Fähnchens auf
            # das rechte Fähnchen spiegeln, an der Falzlinie gespiegelt (sodass
            # die Hälften symmetrisch sind), aber mit aufrechten, lesbaren
            # Glyphen (der Streifen wird nicht umgeklappt). Das Arbeiten mit der
            # »Tinten«-Ausdehnung hält den SICHTBAREN Text auch dann symmetrisch,
            # wenn er innerhalb eines breiteren Feldes ausgerichtet ist.
            if self._flag_mode and self._flag_copy:
                img_scale  = w_px / (print_length_mm * PIXELS_PER_MM)
                flag_w_img = self._flag_width_mm * PIXELS_PER_MM * img_scale
                right_org  = ((self._flag_width_mm + self._flag_middle_mm)
                              * PIXELS_PER_MM * img_scale)
                bounds = self._ink_col_bounds(
                    image, int(round(flag_w_img)), h_print_px,
                    lambda px: (px & 0xFFFFFF) != 0xFFFFFF,   # jedes nicht-weiße Pixel
                )
                if bounds is not None:
                    c0, c1 = bounds
                    strip  = image.copy(c0, 0, c1 - c0, h_print_px)
                    dest_x = int(round(right_org + (flag_w_img - c1)))
                    blit = QPainter(image)
                    blit.drawImage(dest_x, 0, strip)
                    blit.end()
        finally:
            # Den UI-Zustand immer wiederherstellen, selbst wenn das Rendern eine Ausnahme wirft
            _ti._PRINTING = False
            self.setBackgroundBrush(_saved_bg)
            if self._shadow_item:
                self._shadow_item.setVisible(True)
            if self._ruler_item:
                self._ruler_item.setVisible(True)
            if _overlay_was_visible and self._flag_overlay is not None:
                self._flag_overlay.setVisible(True)
            if self._label_item and _saved_label_pen is not None:
                self._label_item.setPen(_saved_label_pen)
            for item in self._bg_items:
                item.setVisible(True)
            for item in extra_hidden:
                item.setVisible(True)
            for item in selected:
                item.setSelected(True)

        return image

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _clear_bg_items(self) -> None:
        for item in self._bg_items:
            self.removeItem(item)
        self._bg_items.clear()
        if self._flag_overlay is not None:
            self.removeItem(self._flag_overlay)
            self._flag_overlay = None
        if self._shadow_item:
            self.removeItem(self._shadow_item)
            self._shadow_item = None
        if self._label_item:
            self.removeItem(self._label_item)
            self._label_item = None
        if self._ruler_item:
            self.removeItem(self._ruler_item)
            self._ruler_item = None

    def _update_ruler_indicators(self) -> None:
        if self._ruler_item is None:
            return
        xs: list[float] = []
        for item in self.selectedItems():
            if isinstance(item, (TextBox, ImageBox)):
                left  = item.pos().x()
                right = left + item._rect.width()
                xs.append(left)
                xs.append(right)
        self._ruler_item.set_indicators(xs)

    # ------------------------------------------------------------------
    # Fähnchen-Spiegel-Overlay (Live-Vorschau links → rechts)
    # ------------------------------------------------------------------

    def _flag_content_signature(self):
        """Günstige Signatur des Inhalts des linken Fähnchens + Fähnchengeometrie.

        Dient dazu, Overlay-Neuaufbauten zu überspringen, wenn sich nichts
        Relevantes geändert hat, was auch die Rückkopplungsschleife
        changed→refresh→changed durchbricht (das Aktualisieren des
        Overlay-Elements löst ``changed`` aus, lässt diese Signatur aber
        unverändert)."""
        sig: list = [
            round(self._flag_width_mm, 2),
            round(self._flag_middle_mm, 2),
            self._flag_copy,
        ]
        for item in self.items():
            if isinstance(item, TextBox):
                sig.append((
                    "t", round(item.pos().x(), 1), round(item.pos().y(), 1),
                    round(item._rect.width(), 1), round(item._rect.height(), 1),
                    item.get_text(), item.get_font().toString(),
                    item.get_h_align(), item.get_vertical_align(),
                ))
            elif isinstance(item, ImageBox):
                sig.append((
                    "i", round(item.pos().x(), 1), round(item.pos().y(), 1),
                    round(item._rect.width(), 1), round(item._rect.height(), 1),
                    id(item),
                ))
        return tuple(sig)

    def _render_left_flag_pixmap(self) -> QPixmap | None:
        """Rendert nur den Inhalt des LINKEN Fähnchens in ein transparentes,
        supersampletes Pixmap, damit es als Live-Kopie in das rechte Fähnchen
        gezeichnet werden kann."""
        import tuxlabel.text_item as _ti

        flag_w_px = self._flag_width_mm * PIXELS_PER_MM
        h_px      = _printable_mm(self._tape_width_mm) * PIXELS_PER_MM
        if flag_w_px < 1 or h_px < 1:
            return None

        f = _FLAG_OVERLAY_SCALE
        out_w = max(1, int(round(flag_w_px * f)))
        out_h = max(1, int(round(h_px * f)))
        boundary_px = (self._flag_width_mm + self._flag_middle_mm / 2.0) * PIXELS_PER_MM

        # Für diesen Durchgang alles ausblenden, was kein Inhalt des linken
        # Fähnchens ist. Nur Top-Level-Elemente anfassen: untergeordnete
        # Elemente (z. B. das innere Textelement einer TextBox, das die Glyphen
        # tatsächlich zeichnet) folgen der Sichtbarkeit ihres Elternteils,
        # sodass ihr Ausblenden hier genau den Inhalt löschen würde, den wir
        # kopieren wollen.
        hidden: list = []
        for it in self.items():
            if it.parentItem() is not None:
                continue
            if isinstance(it, (TextBox, ImageBox)):
                cx = it.pos().x() + it._rect.width() / 2.0
                keep = cx < boundary_px
            else:
                keep = False   # Bedienelemente, Lineal, das Overlay selbst, …
            if not keep and it.isVisible():
                it.setVisible(False)
                hidden.append(it)

        _ti._PRINTING = True
        # Mit transparentem Hintergrund rendern, damit das Overlay NUR den
        # Inhalt des linken Fähnchens (Text/Bilder) trägt. Andernfalls füllt
        # scene.render() das Pixmap mit dem grauen Szenenhintergrund und
        # verdeckt den weißen Streifen des rechten Fähnchens hinter einem
        # deckenden Block.
        _saved_bg = self.backgroundBrush()
        self.setBackgroundBrush(QBrush(Qt.GlobalColor.transparent))
        img = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        try:
            painter = QPainter(img)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self.render(
                painter,
                QRectF(0, 0, out_w, out_h),
                QRectF(0, 0, flag_w_px, h_px),
            )
            painter.end()
        finally:
            _ti._PRINTING = False
            self.setBackgroundBrush(_saved_bg)
            for it in hidden:
                it.setVisible(True)

        return QPixmap.fromImage(img)

    @staticmethod
    def _ink_col_bounds(image: QImage, x_max: int, h: int, is_ink) -> tuple[int, int] | None:
        """Linkeste/rechteste Spalten (in [0, x_max)), die »Tinte« enthalten.

        *is_ink(pixel)* entscheidet, ob ein Pixel als gezeichneter Inhalt zählt."""
        c0 = c1 = None
        for x in range(min(x_max, image.width())):
            for y in range(0, h, 2):
                if is_ink(image.pixel(x, y)):
                    if c0 is None:
                        c0 = x
                    c1 = x + 1
                    break
        if c0 is None:
            return None
        return c0, c1

    def _reflect_to_right_pixmap(self, left_pm: QPixmap) -> QPixmap:
        """Baut das Pixmap des rechten Fähnchens, indem der »Tinten«-Block des
        linken Fähnchens an der Falzlinie (Spiegelposition) gespiegelt wird,
        wobei die Glyphen aufrecht und lesbar bleiben (der Streifen selbst wird
        NICHT umgeklappt).

        Die Verwendung der »Tinten«-Ausdehnung — statt der Textfeldgrenzen —
        hält den SICHTBAREN Text auch dann symmetrisch, wenn er innerhalb eines
        breiteren Feldes ausgerichtet ist."""
        out_w, out_h = left_pm.width(), left_pm.height()
        right = QPixmap(out_w, out_h)
        right.fill(Qt.GlobalColor.transparent)
        bounds = self._ink_col_bounds(
            left_pm.toImage(), out_w, out_h,
            lambda px: (px >> 24) & 0xFF > 20,   # jedes nicht-transparente Pixel
        )
        if bounds is not None:
            c0, c1 = bounds
            painter = QPainter(right)
            strip = left_pm.copy(c0, 0, c1 - c0, out_h)
            painter.drawPixmap(out_w - c1, 0, strip)   # gespiegeltes x, aufrechte Glyphen
            painter.end()
        return right

    def _refresh_flag_overlay(self) -> None:
        """Erzeugt / aktualisiert / entfernt das Spiegel-Overlay-Element des rechten Fähnchens."""
        if not (self._flag_mode and self._flag_copy):
            if self._flag_overlay is not None:
                self.removeItem(self._flag_overlay)
                self._flag_overlay = None
                self._flag_overlay_sig = None
            return

        # Nicht rendern, während der Nutzer tippt — das Umschalten der
        # Elementsichtbarkeit für den Render-Durchgang würde dem Textfeld den
        # Fokus entziehen. Das Overlay wird in _on_text_edit_finished()
        # aktualisiert.
        if self._is_text_editing():
            return

        sig = self._flag_content_signature()
        if self._flag_overlay is not None and sig == self._flag_overlay_sig:
            return

        left_pm = self._render_left_flag_pixmap()
        if left_pm is None:
            return
        # Den linken Inhalt an der Falzung spiegeln, damit die beiden
        # Fähnchenhälften spiegelsymmetrisch sind (Text nach links → die Kopie
        # nach rechts).
        pixmap = self._reflect_to_right_pixmap(left_pm)

        if self._flag_overlay is None:
            self._flag_overlay = QGraphicsPixmapItem()
            self._flag_overlay.setZValue(0.0)
            self._flag_overlay.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            self._flag_overlay.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._flag_overlay.setTransformationMode(
                Qt.TransformationMode.SmoothTransformation)
            self.addItem(self._flag_overlay)

        self._flag_overlay.setPixmap(pixmap)
        self._flag_overlay.setScale(1.0 / _FLAG_OVERLAY_SCALE)
        right_org_px = (self._flag_width_mm + self._flag_middle_mm) * PIXELS_PER_MM
        self._flag_overlay.setPos(right_org_px, 0.0)
        self._flag_overlay_sig = sig

    def _rebuild_label(self) -> None:
        """Erzeugt Etikettenhintergrund, Schlagschatten und Randmarkierungen neu.

        Feldkoordinaten verwenden den *druckbaren* Streifen als Bezugsrahmen:
        y=0 ist die Oberkante des druckbaren Bereichs, y=printable_h die
        Unterkante. Die nicht druckbaren Streifen darüber (negatives y) und
        darunter (y > printable_h) werden in Hellgrau angezeigt, damit der
        Nutzer das ganze physische Band sieht.
        """
        self._clear_bg_items()

        w           = self._label_length_mm * PIXELS_PER_MM
        h_printable = _printable_mm(self._tape_width_mm) * PIXELS_PER_MM
        h_full      = self._tape_width_mm * PIXELS_PER_MM
        margin      = (h_full - h_printable) / 2.0     # vertikaler nicht druckbarer Streifen (je Seite)
        m           = MARGIN_MM * PIXELS_PER_MM        # horizontaler Sicherheitsrand
        scene_margin = max(30, m)

        # Zusätzlicher Platz über dem Band, damit die Linealleiste (plus etwas
        # Luft) in sceneRect passt.
        ruler_above = RulerItem.HEIGHT_PX + RulerItem.GAP_PX + 8
        above_tape  = max(scene_margin, ruler_above)
        # Zusätzlicher Platz rechts, damit die »X,XX cm«-Gesamtlängenbeschriftung
        # am Ende des Lineals nicht abgeschnitten wird.
        right_pad   = max(scene_margin, RulerItem.RIGHT_PAD)

        # Das Szenenrechteck deckt vertikal das ganze physische Band + Lineal darüber ab.
        self.setSceneRect(
            -scene_margin, -margin - above_tape,
            w + scene_margin + right_pad, h_full + above_tape + scene_margin,
        )

        # --- Schlagschatten (unter dem ganzen Band) ---
        self._shadow_item = self.addRect(
            _SHADOW_OFFSET, -margin + _SHADOW_OFFSET, w, h_full,
            QPen(Qt.PenStyle.NoPen),
            QBrush(QColor(0, 0, 0, 60)),
        )
        self._shadow_item.setZValue(-2)

        # --- Weißer druckbarer Streifen (wo der Druckkopf tatsächlich schreiben kann) ---
        self._label_item = self.addRect(
            0, 0, w, h_printable,
            QPen(_COLOR_LABEL_BORDER, 1),
            QBrush(_COLOR_LABEL_BG),
        )
        self._label_item.setZValue(-1)
        self._label_item.setFlag(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False
        )

        # --- Nicht druckbare Streifen (hellgrau, über und unter dem druckbaren Bereich) ---
        if margin > 0.5:
            for y0 in (-margin, h_printable):
                r = self.addRect(
                    0, y0, w, margin,
                    QPen(_COLOR_UNPRINTABLE_LINE, 0.5),
                    QBrush(_COLOR_UNPRINTABLE_FILL),
                )
                r.setZValue(-1.5)
                r.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
                self._bg_items.append(r)

        # --- Sicherheitsrandzonen (hellrote Tönung, horizontaler Anfang/Ende) ---
        def _add_zone(x, width):
            r = self.addRect(
                x, 0, width, h_printable,
                QPen(Qt.PenStyle.NoPen),
                QBrush(_COLOR_MARGIN_FILL),
            )
            r.setZValue(-0.5)
            r.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
            self._bg_items.append(r)

        _add_zone(0,     m)          # linker Rand
        _add_zone(w - m, m)          # rechter Rand

        # --- Gestrichelte Begrenzungslinien (horizontale Sicherheitsränder) ---
        dash_pen = QPen(_COLOR_MARGIN_LINE, 0.5, Qt.PenStyle.DashLine)
        for x in (m, w - m):
            line = self.addLine(x, 0, x, h_printable, dash_pen)
            line.setZValue(-0.5)
            self._bg_items.append(line)

        # --- Kabelfähnchen-Hilfslinien (mittleres Wickelband + Falzlinie + Kopie-Tönung) ---
        # Alle Fähnchen-Hilfslinien kommen in _bg_items, damit sie im
        # Druck-Rendering ausgeblendet werden (das gedruckte Band trägt nur den
        # Fähncheninhalt, nicht die Markierungen der Wickelzone).
        if self._flag_mode:
            flag_w_px  = self._flag_width_mm  * PIXELS_PER_MM
            middle_px  = self._flag_middle_mm * PIXELS_PER_MM
            mid_left   = flag_w_px
            right_org  = flag_w_px + middle_px

            # Mittleres Wickelband (hellblau)
            band = self.addRect(
                mid_left, 0, middle_px, h_printable,
                QPen(Qt.PenStyle.NoPen),
                QBrush(_COLOR_FLAG_MIDDLE_FILL),
            )
            band.setZValue(-0.5)
            band.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
            self._bg_items.append(band)

            # Falzlinie in der Mitte des Bandes
            fold_x   = mid_left + middle_px / 2.0
            fold_pen = QPen(_COLOR_FLAG_MIDDLE_LINE, 0.8, Qt.PenStyle.DashLine)
            fold = self.addLine(fold_x, 0, fold_x, h_printable, fold_pen)
            fold.setZValue(-0.4)
            self._bg_items.append(fold)

            # Zarte Tönung über dem rechten Fähnchen, während es das linke
            # spiegelt, um zu signalisieren »diese Hälfte wird automatisch erzeugt«.
            if self._flag_copy:
                tint = self.addRect(
                    right_org, 0, flag_w_px, h_printable,
                    QPen(Qt.PenStyle.NoPen),
                    QBrush(_COLOR_FLAG_COPY_FILL),
                )
                tint.setZValue(-0.5)
                tint.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
                self._bg_items.append(tint)

        # --- Lineal (cm-Skala, Gesamtlänge, Positionsmarkierungen) ---
        self._ruler_item = RulerItem()
        self.addItem(self._ruler_item)
        self._ruler_item.set_geometry(w, -margin)
        self._update_ruler_indicators()

        # Das Spiegel-Overlay wurde von _clear_bg_items entfernt; nach dem
        # Abschluss dieses (synchronen) Neuaufbaus neu aufbauen. Der Timer
        # feuert, sobald _rebuilding wieder False ist.
        if self._flag_mode and self._flag_copy:
            self._flag_overlay_sig = None   # ein frisches Rendern erzwingen
            self._flag_overlay_timer.start()


class LabelView(QGraphicsView):
    """Ansichtsfenster, das die Etikett-Zeichenfläche anzeigt und scrollt."""

    def __init__(self, scene: LabelScene, parent=None):
        super().__init__(scene, parent)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self._paint_mode: bool = False
        self._paint_format: dict | None = None
        self._paint_done_cb = None
        self._initial_fit_done = False

    # ------------------------------------------------------------------
    # Format-Painter mode
    # ------------------------------------------------------------------

    def start_paint_mode(self, fmt: dict, done_callback) -> None:
        self._paint_mode   = True
        self._paint_format = fmt
        self._paint_done_cb = done_callback
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self._fit_label)

    def stop_paint_mode(self) -> None:
        self._paint_mode   = False
        self._paint_format = None
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        if self._paint_done_cb:
            self._paint_done_cb()
        self._paint_done_cb = None

    def mousePressEvent(self, event) -> None:
        if self._paint_mode and self._paint_format is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                pos  = self.mapToScene(event.position().toPoint())
                item = self.scene().itemAt(pos, self.transform())
                # Zum übergeordneten TextBox hochlaufen (Klick kann untergeordnetes QGraphicsTextItem treffen)
                while item is not None and not isinstance(item, TextBox):
                    item = item.parentItem()
                if isinstance(item, TextBox):
                    item.apply_format(self._paint_format)
            self.stop_paint_mode()
            event.accept()
            return
        super().mousePressEvent(event)

    def _fit_label(self) -> None:
        """Passt das Etikett mit einem sinnvollen Zoom in die Ansicht ein.

        Berechnet die Skalierung direkt aus der Größe des Ansichtsfensters,
        statt fitInView() zu verwenden (das falsche Ergebnisse liefert, wenn es
        aufgerufen wird, bevor das Widget sein endgültiges Layout hat). Die
        Bandhöhe auf dem Bildschirm wird zwischen 60 px (lesbar) und 80 px
        (bei schmalen Bändern nicht überzoomt) begrenzt.
        """
        scene = self.scene()
        if scene is None:
            return

        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        if vp_w <= 0 or vp_h <= 0:
            return

        # So skalieren, dass das ganze physische Band (druckbare + graue nicht
        # druckbare Streifen) bequem auf dem Bildschirm sichtbar ist.
        tape_h_scene = scene.get_tape_width_mm() * PIXELS_PER_MM
        if tape_h_scene <= 0:
            return

        scene_w = scene.sceneRect().width()
        min_scale = 60.0 / tape_h_scene
        max_scale = 80.0 / tape_h_scene

        scale_for_width = (vp_w / scene_w) if scene_w > 0 else min_scale
        target = max(min_scale, min(max_scale, scale_for_width))

        self.resetTransform()
        self.scale(target, target)
        self.centerOn(scene.sceneRect().center())

    def keyPressEvent(self, event) -> None:
        # Während ein Textfeld bearbeitet wird, gehören alle Tasten dem
        # Textcursor (Pfeile bewegen die Einfügemarke, Entf löscht ein Zeichen,
        # Strg+C/V kopiert/fügt Text ein). Qt sie an das fokussierte
        # Textelement weiterleiten lassen, statt das ganze Objekt zu
        # verschieben / zu löschen.
        focus = self.scene().focusItem()
        if (isinstance(focus, QGraphicsTextItem) and
                focus.textInteractionFlags() &
                Qt.TextInteractionFlag.TextEditorInteraction):
            super().keyPressEvent(event)
            return

        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        arrow_keys = (Qt.Key.Key_Left, Qt.Key.Key_Right,
                      Qt.Key.Key_Up,   Qt.Key.Key_Down)
        # Kopieren / Einfügen / Löschen werden von den QActions des
        # Bearbeiten-Menüs des Fensters gesteuert (Strg+C / Strg+V / Entf),
        # damit sie überall funktionieren und wir sie hier nicht doppelt
        # behandeln. Diese Ansicht ergänzt nur das Verschieben per Pfeiltasten.
        if self._paint_mode and event.key() == Qt.Key.Key_Escape:
            self.stop_paint_mode()
            event.accept()
        elif event.key() in arrow_keys:
            selected = [it for it in self.scene().selectedItems()
                        if isinstance(it, (TextBox, ImageBox))]
            if not selected:
                super().keyPressEvent(event)
                return
            step_mm = 0.1 if ctrl else 1.0
            step_px = step_mm * PIXELS_PER_MM
            dx = dy = 0.0
            if event.key() == Qt.Key.Key_Left:    dx = -step_px
            elif event.key() == Qt.Key.Key_Right: dx =  step_px
            elif event.key() == Qt.Key.Key_Up:    dy = -step_px
            elif event.key() == Qt.Key.Key_Down:  dy =  step_px
            for item in selected:
                item.setPos(item.pos().x() + dx, item.pos().y() + dy)
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        """Strg+Mausrad zoomt; einfaches Mausrad scrollt."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)
