# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Barcode-Element für die Etikett-Zeichenfläche.

Die Balken werden als Rechtecke gezeichnet, nicht als skaliertes Bild. Das ist
der Grund: Ein Bitmap-Barcode wird beim Drucken auf 180 dpi umgerechnet, und
dabei verschmieren die Kanten — ein halb getroffenes Modul macht aus einem
schmalen Strich einen grauen Balken, den kein Scanner mehr sicher liest. Als
Vektor zeichnet Qt die Kanten bei jeder Auflösung sauber.

Die helle Randzone (Quiet Zone) gehört zum Element dazu und steckt in seiner
Breite. Nur so hält die Überstandsprüfung sie frei und es kann sich kein
Textfeld direkt an die Balken schieben, was das Lesen verhindern würde.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QFontMetricsF

from . import text_item as _ti
from . import barcode as _bc
from .text_item import (
    HANDLE_TL, HANDLE_T, HANDLE_TR, HANDLE_R,
    HANDLE_BR, HANDLE_B, HANDLE_BL, HANDLE_L,
    HANDLE_SIZE, HANDLE_HALF, HANDLE_CURSORS,
    COLOR_HANDLE_FILL, COLOR_HANDLE_BORDER,
    _border_pen,
)

MIN_W = 20.0
MIN_H = 12.0


def _ppmm() -> float:
    """Szenen-Pixel je Millimeter. Spät geholt, weil label_canvas dieses
    Modul importiert — ein Import auf Modulebene wäre ein Zirkelbezug."""
    from .label_canvas import PIXELS_PER_MM
    return PIXELS_PER_MM

#: Vorgabe für die Klarschrift unter den Balken, in Punkt — dieselbe Einheit
#: wie bei Textfeldern, damit die Schriftgrößen-Auswahl der Werkzeugleiste
#: auch hier das Erwartete tut.
TEXT_PT_DEFAULT = 8.0
#: Mehr als diesen Anteil der Elementhöhe darf die Klarschrift nie belegen,
#: sonst bleiben für die Balken zu wenige Millimeter zum Lesen übrig.
_TEXT_MAX_FRAC = 0.45
#: Luft zwischen Balkenunterkante und Ziffern, als Anteil der Texthöhe.
_TEXT_GAP_FRAC = 0.12


class BarcodeBox(QGraphicsItem):
    """Ein Barcode, verschiebbar und in der Größe änderbar.

    Anders als beim Bild ist das Seitenverhältnis NICHT gekoppelt: Die Breite
    bestimmt, wie breit ein Modul wird, die Höhe ist davon unabhängig. Beides
    will man getrennt einstellen — hohe Balken auf breitem Band, flache auf
    schmalem.
    """

    def __init__(self, data: str = "", symbology: str = _bc.CODE128,
                 show_text: bool = True, parent=None):
        super().__init__(parent)
        self._data = ""
        self._symbology = symbology
        self._show_text = show_text
        self._text_pt = TEXT_PT_DEFAULT
        self._modules = ""
        self._rect = QRectF(0, 0, 90.0, 50.0)

        self._handle_selected: int | None = None
        self._press_scene_pos: QPointF | None = None
        self._press_rect: QRectF | None = None
        self._press_item_pos: QPointF | None = None

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

        self.set_content(data, symbology, show_text)

    # ------------------------------------------------------------------
    # Inhalt
    # ------------------------------------------------------------------
    def set_content(self, data: str, symbology: str | None = None,
                    show_text: bool | None = None) -> bool:
        """Setzt Nummer, Art und Klarschrift. False, wenn nicht kodierbar.

        Bei EAN-13 wird eine fehlende Prüfziffer ergänzt, damit unter dem Code
        dasselbe steht, was in ihm steckt."""
        sym = symbology if symbology is not None else self._symbology
        try:
            module = _bc.encode(data, sym)
        except _bc.BarcodeError:
            return False
        self.prepareGeometryChange()
        self._symbology = sym
        self._data = _bc.normalize(data, sym)
        self._modules = module
        if show_text is not None:
            self._show_text = bool(show_text)
        self.update()
        return True

    def get_data(self) -> str:
        return self._data

    def get_symbology(self) -> str:
        return self._symbology

    def get_show_text(self) -> bool:
        return self._show_text

    def set_show_text(self, on: bool) -> None:
        self._show_text = bool(on)
        self.update()

    def get_text_pt(self) -> float:
        return self._text_pt

    def set_text_pt(self, pt: float) -> None:
        """Schriftgröße der Klarschrift in Punkt.

        Wird von der Schriftgrößen-Auswahl der Werkzeugleiste gesetzt, genau
        wie bei einem Textfeld."""
        self._text_pt = max(4.0, float(pt))
        self.update()

    def _text_font(self) -> QFont:
        """Schrift der Klarschrift, in Szeneneinheiten statt in Punkt.

        setPixelSize statt setPointSizeF, und das ist der entscheidende
        Unterschied: Eine Punktgröße löst Qt gegen die Auflösung des
        Zielgeräts auf. Beim Messen am Bildschirm kommt dabei etwas anderes
        heraus als beim Zeichnen ins Druckbild — die Ziffern wurden dort
        größer und liefen in die Balken. Eine Pixelgröße gilt dagegen in den
        Koordinaten des Malers, also in Szeneneinheiten, und wird von dessen
        Transformation sauber mitskaliert.

        Die Punktzahl des Nutzers wird vorher in Millimeter und dann in
        Szeneneinheiten umgerechnet, damit »8 pt« dasselbe bedeutet wie bei
        einem Textfeld."""
        soll_px = self._text_pt * (25.4 / 72.0) * _ppmm()
        f = QFont()
        # setPixelSize meint die Versalhöhe, height() liegt darüber. Einmal
        # messen und nachziehen, damit soll_px wirklich die Zeilenhöhe ist.
        f.setPixelSize(max(1, round(soll_px)))
        hoehe = QFontMetricsF(f).height()
        if hoehe > 0.0:
            f.setPixelSize(max(1, round(round(soll_px) * soll_px / hoehe)))
        return f

    def module_count(self) -> int:
        """Module einschließlich beider Randzonen."""
        return len(self._modules) + 2 * _bc.quiet_zone(self._symbology)

    def module_width(self) -> float:
        """Breite eines Moduls in Szenenpixeln."""
        n = self.module_count()
        return self._rect.width() / n if n else 0.0

    def set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, max(MIN_W, float(w)), max(MIN_H, float(h)))
        self.update()

    def natural_width(self, module_px: float) -> float:
        """Breite, bei der ein Modul *module_px* breit wäre."""
        return self.module_count() * module_px

    # ------------------------------------------------------------------
    # Griffe (wie bei ImageBox)
    # ------------------------------------------------------------------
    def _handle_rects(self) -> dict:
        r = self._rect
        s, hh = HANDLE_SIZE, HANDLE_HALF
        cx, cy = r.center().x(), r.center().y()
        pts = {
            HANDLE_TL: (r.left(),  r.top()),    HANDLE_T:  (cx,        r.top()),
            HANDLE_TR: (r.right(), r.top()),    HANDLE_R:  (r.right(), cy),
            HANDLE_BR: (r.right(), r.bottom()), HANDLE_B:  (cx,        r.bottom()),
            HANDLE_BL: (r.left(),  r.bottom()), HANDLE_L:  (r.left(),  cy),
        }
        return {k: QRectF(x - hh, y - hh, s, s) for k, (x, y) in pts.items()}

    def _handle_at(self, pos: QPointF) -> int | None:
        for handle_id, rect in self._handle_rects().items():
            if rect.contains(pos):
                return handle_id
        return None

    # ------------------------------------------------------------------
    # QGraphicsItem
    # ------------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-HANDLE_SIZE, -HANDLE_SIZE,
                                   HANDLE_SIZE,  HANDLE_SIZE)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        r = self._rect
        quiet = _bc.quiet_zone(self._symbology)
        n = self.module_count()
        if n and self._modules:
            mw = r.width() / n
            bars_h = r.height()
            text_h = 0.0
            schrift = None
            if self._show_text and self._data:
                schrift = self._text_font()
                gemessen = QFontMetricsF(schrift).height()
                erlaubt = r.height() * _TEXT_MAX_FRAC
                text_h = gemessen * (1.0 + _TEXT_GAP_FRAC)
                if text_h > erlaubt:
                    # Die Schrift wirklich verkleinern, nicht nur den Platz
                    # deckeln: Sonst ragen die Ziffern unten aus dem Element
                    # heraus, wo die Überstandsprüfung sie nicht bemerkt.
                    # Über pixelSize skalieren — die Schrift trägt keine
                    # Punktgröße, pointSizeF() gäbe hier -1 zurück.
                    schrift.setPixelSize(max(
                        1, round(schrift.pixelSize() * erlaubt / text_h)))
                    gemessen = QFontMetricsF(schrift).height()
                    text_h = erlaubt
                bars_h = r.height() - text_h

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("black")))
            # Gleiche Module zusammenfassen: weniger Rechtecke, und vor allem
            # keine Fugen zwischen nebeneinander gezeichneten Balken.
            i = 0
            while i < len(self._modules):
                if self._modules[i] == "1":
                    j = i
                    while j < len(self._modules) and self._modules[j] == "1":
                        j += 1
                    x = (quiet + i) * mw
                    painter.drawRect(QRectF(x, 0.0, (j - i) * mw, bars_h))
                    i = j
                else:
                    i += 1

            if text_h > 0.0 and schrift is not None:
                painter.setFont(schrift)
                painter.setPen(QPen(QColor("black")))
                # Grundlinie an der Unterkante verankern, statt die Lage aus
                # der Texthöhe zu rechnen: So endet die Schrift garantiert am
                # Elementrand. Aus einem Rechteck heraus zentriert liefe sie
                # je nach Schriftart ein Stück darunter hinaus — und dort
                # bemerkt die Überstandsprüfung sie nicht mehr.
                fm = QFontMetricsF(schrift)
                grundlinie = r.height() - fm.descent()
                breite = fm.horizontalAdvance(self._data)
                painter.drawText(QPointF((r.width() - breite) / 2.0,
                                         grundlinie),
                                 self._data)

        if _ti._PRINTING:
            return

        selected = self.isSelected()
        painter.setPen(_border_pen(selected))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        if selected:
            painter.setBrush(QBrush(COLOR_HANDLE_FILL))
            painter.setPen(QPen(COLOR_HANDLE_BORDER, 1))
            for rect in self._handle_rects().values():
                painter.drawRect(rect)

    # ------------------------------------------------------------------
    # Maus
    # ------------------------------------------------------------------
    def hoverMoveEvent(self, event) -> None:
        handle = self._handle_at(event.pos()) if self.isSelected() else None
        self.setCursor(HANDLE_CURSORS[handle] if handle is not None
                       else Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSelected():
            handle = self._handle_at(event.pos())
            if handle is not None:
                self._handle_selected = handle
                self._press_scene_pos = event.scenePos()
                self._press_rect = QRectF(self._rect)
                self._press_item_pos = QPointF(self.pos())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._handle_selected is not None:
            self._do_resize(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._handle_selected is not None:
            self._handle_selected = None
            self._press_scene_pos = None
            self._press_rect = None
            self._press_item_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _do_resize(self, scene_pos: QPointF) -> None:
        """Freie Größenänderung. Breite und Höhe sind bewusst entkoppelt —
        die Modulbreite und die Balkenhöhe will man getrennt wählen."""
        if self._press_rect is None or self._press_scene_pos is None:
            return
        d = scene_pos - self._press_scene_pos
        r = QRectF(self._press_rect)
        p = QPointF(self._press_item_pos)
        h = self._handle_selected

        links  = h in (HANDLE_TL, HANDLE_L, HANDLE_BL)
        rechts = h in (HANDLE_TR, HANDLE_R, HANDLE_BR)
        oben   = h in (HANDLE_TL, HANDLE_T, HANDLE_TR)
        unten  = h in (HANDLE_BL, HANDLE_B, HANDLE_BR)

        w, hh = r.width(), r.height()
        if rechts:
            w = max(MIN_W, r.width() + d.x())
        elif links:
            w = max(MIN_W, r.width() - d.x())
            p.setX(p.x() + (r.width() - w))
        if unten:
            hh = max(MIN_H, r.height() + d.y())
        elif oben:
            hh = max(MIN_H, r.height() - d.y())
            p.setY(p.y() + (r.height() - hh))

        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, w, hh)
        self.setPos(p)
        self.update()
