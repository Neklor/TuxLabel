# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verschiebbares und in der Größe änderbares Bildelement für die Etikett-Zeichenfläche."""

from PyQt6.QtWidgets import QGraphicsItem
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QPixmap

from . import text_item as _ti
from .text_item import (
    HANDLE_TL, HANDLE_T, HANDLE_TR, HANDLE_R,
    HANDLE_BR, HANDLE_B, HANDLE_BL, HANDLE_L,
    CORNER_HANDLES,
    HANDLE_SIZE, HANDLE_HALF,
    HANDLE_CURSORS,
    COLOR_HANDLE_FILL, COLOR_HANDLE_BORDER,
    _border_pen,
)

MIN_W = 8
MIN_H = 8


class ImageBox(QGraphicsItem):
    """Ein Bitmap-Bild, das auf der Etikett-Zeichenfläche verschoben und in
    der Größe geändert werden kann.

    - Körper ziehen zum Verschieben.
    - Eck-Griff ziehen: proportionale Größenänderung (Seitenverhältnis bleibt erhalten).
    - Kanten-Griff ziehen: freie Größenänderung auf dieser Achse (Bild wird gedehnt).
    """

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        if pixmap.isNull():
            raise ValueError("ImageBox: pixmap is null")

        self._pixmap = pixmap
        self._rect = QRectF(0, 0, float(pixmap.width()), float(pixmap.height()))

        # Zustand während der Größenänderung
        self._handle_selected: int | None = None
        self._press_scene_pos: QPointF | None = None
        self._press_rect: QRectF | None = None
        self._press_item_pos: QPointF | None = None

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, max(MIN_W, float(w)), max(MIN_H, float(h)))
        self.update()

    def get_pixmap(self) -> QPixmap:
        return self._pixmap

    def native_aspect(self) -> float:
        if self._pixmap.height() <= 0:
            return 1.0
        return self._pixmap.width() / self._pixmap.height()

    # ------------------------------------------------------------------
    # Griffe
    # ------------------------------------------------------------------

    def _handle_rects(self) -> dict:
        # Ecken (proportionale Größenänderung) PLUS die vier Kanten-Griffe
        # (freies, nicht-proportionales Dehnen auf einer Achse). Bilder
        # behalten die Kanten-Griffe, damit sie bei Bedarf verzerrt werden
        # können.
        # Die Griffe liegen vollständig AUSSERHALB des Rechtecks, damit die
        # gesamte Innenfläche zum Verschieben greifbar bleibt, selbst wenn das
        # Bild klein ist.
        r = self._rect
        cx = r.center().x()
        cy = r.center().y()
        h = HANDLE_HALF
        s = HANDLE_SIZE
        return {
            HANDLE_TL: QRectF(r.left()  - s, r.top()    - s, s, s),
            HANDLE_T:  QRectF(cx - h,        r.top()    - s, s, s),
            HANDLE_TR: QRectF(r.right(),     r.top()    - s, s, s),
            HANDLE_R:  QRectF(r.right(),     cy - h,         s, s),
            HANDLE_BR: QRectF(r.right(),     r.bottom(),     s, s),
            HANDLE_B:  QRectF(cx - h,        r.bottom(),     s, s),
            HANDLE_BL: QRectF(r.left()  - s, r.bottom(),     s, s),
            HANDLE_L:  QRectF(r.left()  - s, cy - h,         s, s),
        }

    def _handle_at(self, pos: QPointF) -> int | None:
        for handle_id, rect in self._handle_rects().items():
            if rect.contains(pos):
                return handle_id
        return None

    # ------------------------------------------------------------------
    # Überschriebene QGraphicsItem-Methoden
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-HANDLE_SIZE, -HANDLE_SIZE,
                                   HANDLE_SIZE,  HANDLE_SIZE)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        # Das Bild selbst immer zeichnen (es IST der druckbare Inhalt)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self._rect, self._pixmap, QRectF(self._pixmap.rect()))

        # Im Druckmodus sämtliche UI-Elemente unterdrücken
        if _ti._PRINTING:
            return

        selected = self.isSelected()

        # Rahmen
        painter.setPen(_border_pen(selected))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._rect)

        # Größengriffe (nur bei Auswahl)
        if selected:
            painter.setBrush(QBrush(COLOR_HANDLE_FILL))
            painter.setPen(QPen(COLOR_HANDLE_BORDER, 1))
            for rect in self._handle_rects().values():
                painter.drawRect(rect)

    def hoverMoveEvent(self, event) -> None:
        handle = self._handle_at(event.pos())
        if handle is not None:
            self.setCursor(HANDLE_CURSORS[handle])
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._handle_selected = self._handle_at(event.pos())
            if self._handle_selected is not None:
                # Eingebautes Verschieben blockieren, damit nur die Größenänderung erfolgt
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                self._press_scene_pos = event.scenePos()
                self._press_rect      = QRectF(self._rect)
                self._press_item_pos  = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._handle_selected is not None:
            self._do_resize(event.scenePos())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._handle_selected is not None:
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._handle_selected = None
            self._press_scene_pos = None
            self._press_rect      = None
            self._press_item_pos  = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Logik der Größenänderung
    # ------------------------------------------------------------------

    def _do_resize(self, scene_pos: QPointF) -> None:
        delta  = scene_pos - self._press_scene_pos
        orig_w = self._press_rect.width()
        orig_h = self._press_rect.height()
        orig_x = self._press_item_pos.x()
        orig_y = self._press_item_pos.y()

        h = self._handle_selected
        aspect = orig_w / orig_h if orig_h > 0 else 1.0

        # ---------- Seitenkanten: freies Dehnen auf einer Achse ----------
        if h == HANDLE_L:
            new_w = max(MIN_W, orig_w - delta.x())
            new_h = orig_h
            new_x = orig_x + (orig_w - new_w)
            new_y = orig_y
        elif h == HANDLE_R:
            new_w = max(MIN_W, orig_w + delta.x())
            new_h = orig_h
            new_x = orig_x
            new_y = orig_y
        elif h == HANDLE_T:
            new_w = orig_w
            new_h = max(MIN_H, orig_h - delta.y())
            new_x = orig_x
            new_y = orig_y + (orig_h - new_h)
        elif h == HANDLE_B:
            new_w = orig_w
            new_h = max(MIN_H, orig_h + delta.y())
            new_x = orig_x
            new_y = orig_y

        # ---------- Eck-Griffe: Größenänderung mit festem Seitenverhältnis ----------
        elif h in CORNER_HANDLES:
            # Delta unabhängig von der Ecke in »nach außen« (dw, dh) umrechnen
            if   h == HANDLE_TR: dw, dh =  delta.x(), -delta.y()
            elif h == HANDLE_TL: dw, dh = -delta.x(), -delta.y()
            elif h == HANDLE_BR: dw, dh =  delta.x(),  delta.y()
            else:  # HANDLE_BL
                dw, dh = -delta.x(),  delta.y()

            cand_w = orig_w + dw
            cand_h = orig_h + dh

            # Die Achse, die sich (relativ zu ihrer Dimension) stärker bewegt
            # hat, als Führung wählen; die andere Achse folgt dem Seitenverhältnis.
            if abs(dw) * orig_h >= abs(dh) * orig_w:
                new_w = cand_w
                new_h = new_w / aspect
            else:
                new_h = cand_h
                new_w = new_h * aspect

            # Mindestgrößen erzwingen und dabei das Seitenverhältnis wahren
            if new_w < MIN_W:
                new_w = MIN_W
                new_h = new_w / aspect
            if new_h < MIN_H:
                new_h = MIN_H
                new_w = new_h * aspect

            # So platzieren, dass die gegenüberliegende Ecke fixiert bleibt
            if h == HANDLE_TR:    # gegenüber = BL
                new_x = orig_x
                new_y = orig_y + (orig_h - new_h)
            elif h == HANDLE_TL:  # gegenüber = BR
                new_x = orig_x + (orig_w - new_w)
                new_y = orig_y + (orig_h - new_h)
            elif h == HANDLE_BR:  # gegenüber = TL
                new_x = orig_x
                new_y = orig_y
            else:                 # HANDLE_BL, gegenüber = TR
                new_x = orig_x + (orig_w - new_w)
                new_y = orig_y
        else:
            return

        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, new_w, new_h)
        self.setPos(new_x, new_y)
        self.update()
