# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verschiebbares und in der Größe änderbares Textfeld für die Etikett-Zeichenfläche."""

from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsTextItem, QStyle, QStyleOptionGraphicsItem,
    QApplication,
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QFontMetricsF,
    QTextCursor, QTextCharFormat, QTextBlockFormat, QKeySequence,
)

from .i18n import tr

# Werte für die horizontale Textausrichtung, die auf einer TextBox gespeichert werden.
H_ALIGN_LEFT    = "left"
H_ALIGN_CENTER  = "center"
H_ALIGN_RIGHT   = "right"
H_ALIGN_JUSTIFY = "justify"
_H_ALIGN_VALUES = (H_ALIGN_LEFT, H_ALIGN_CENTER, H_ALIGN_RIGHT, H_ALIGN_JUSTIFY)

# IDs der Griffe
HANDLE_TL = 0  # oben links (symmetrische Ecke)
HANDLE_T  = 1  # oben (asymmetrische Kante)
HANDLE_TR = 2  # oben rechts (symmetrische Ecke)
HANDLE_R  = 3  # rechts (asymmetrische Kante)
HANDLE_BR = 4  # unten rechts (symmetrische Ecke)
HANDLE_B  = 5  # unten (asymmetrische Kante)
HANDLE_BL = 6  # unten links (symmetrische Ecke)
HANDLE_L  = 7  # links (asymmetrische Kante)

CORNER_HANDLES = {HANDLE_TL, HANDLE_TR, HANDLE_BR, HANDLE_BL}

# Von LabelScene.render_to_image() auf True gesetzt, um UI-Elemente in der Druckausgabe zu unterdrücken
_PRINTING: bool = False

HANDLE_SIZE = 6
HANDLE_HALF = HANDLE_SIZE / 2

MIN_W = 40
MIN_H = 16

# Cursor-Formen für jeden Griff
HANDLE_CURSORS = {
    HANDLE_TL: Qt.CursorShape.SizeBDiagCursor,
    HANDLE_T:  Qt.CursorShape.SizeVerCursor,
    HANDLE_TR: Qt.CursorShape.SizeFDiagCursor,
    HANDLE_R:  Qt.CursorShape.SizeHorCursor,
    HANDLE_BR: Qt.CursorShape.SizeBDiagCursor,
    HANDLE_B:  Qt.CursorShape.SizeVerCursor,
    HANDLE_BL: Qt.CursorShape.SizeFDiagCursor,
    HANDLE_L:  Qt.CursorShape.SizeHorCursor,
}

# Farben
COLOR_BORDER_NORMAL   = QColor("#888888")
COLOR_BORDER_SELECTED = QColor("#0078D7")
COLOR_HANDLE_FILL     = QColor("#0078D7")
COLOR_HANDLE_BORDER   = QColor("#004080")
COLOR_BG              = QColor(255, 255, 255, 220)


def _border_pen(selected: bool) -> QPen:
    """Stift für die Umrandung eines Elements.

    Ausgewählt → eine durchgezogene 1,5-px-Linie. Nicht ausgewählt → eine
    dünne, kosmetische gestrichelte Linie mit kurzen Strichen. Der Stift ist
    kosmetisch, sodass Breite und Strichlänge unabhängig von der Elementgröße
    oder dem aktuellen Zoom konstant in Bildschirmpixeln bleiben – das
    verhindert, dass kleine Felder plump wirken.
    """
    if selected:
        return QPen(COLOR_BORDER_SELECTED, 1.5, Qt.PenStyle.SolidLine)
    pen = QPen(COLOR_BORDER_NORMAL, 1.0, Qt.PenStyle.DashLine)
    pen.setCosmetic(True)
    pen.setDashPattern([3.0, 3.0])
    return pen


class _EditableText(QGraphicsTextItem):
    """Untergeordnetes Textelement, das innerhalb einer TextBox verwendet wird.

    - Ohne Bearbeitung: ignoriert Maustasten, sodass Klicks an die
      übergeordnete TextBox durchgereicht werden (damit das ganze Feld
      greifbar ist, nicht nur der Zwischenraum zwischen Text und Rahmen).
    - Unterdrückt Qts standardmäßiges Auswahl-/Fokus-Rechteck (den
      gepunkteten/gestrichelten Rahmen, der sich sonst über die eigene
      Umrandung der TextBox legen würde).
    - Beendet den Bearbeitungsmodus, wenn der Tastaturfokus verloren geht.
      Die TextBox selbst kann das nicht, weil sie nicht fokussierbar ist.
    """

    def paint(self, painter, option, widget=None):
        # Auswahl-/Fokus-Zustand entfernen, damit QGraphicsTextItem seinen
        # eingebauten gepunkteten Rahmen nicht über die Umrandung der TextBox zeichnet.
        opt = QStyleOptionGraphicsItem(option)
        opt.state &= ~QStyle.StateFlag.State_Selected
        opt.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, opt, widget)

    def keyPressEvent(self, event):
        # Als REINEN Text einfügen. Qts Standard-Einfügen übernimmt Rich-Text,
        # der den Ausschnitt in einen eigenen Absatz packt und damit in einer
        # neuen Zeile *unterhalb* des vorhandenen Textes landet. Das Einfügen
        # von reinem Text hält ihn dagegen inline, sodass das Feld wie beim
        # Tippen nach rechts wächst.
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            if text:
                self.textCursor().insertText(text)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        # Eine etwaige Textauswahl aufheben, damit sie nicht als Markierung stehen bleibt
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        super().focusOutEvent(event)
        # Bearbeitung ist abgeschlossen — die Szene die während des Tippens
        # eingefrorenen Aktualisierungen von Fähnchenlänge / Spiegel-Overlay
        # erneut anwenden lassen.
        scene = self.scene()
        on_done = getattr(scene, "_on_text_edit_finished", None)
        if callable(on_done):
            on_done()


class TextBox(QGraphicsItem):
    """Ein Textfeld, das auf der Etikett-Zeichenfläche verschoben und in der
    Größe geändert werden kann.

    - Zum Verschieben an beliebiger Stelle des Körpers ziehen.
    - Kanten-Griff ziehen für asymmetrische Größenänderung.
    - Eck-Griff ziehen für symmetrische Größenänderung um den Mittelpunkt.
    - Doppelklick zum Bearbeiten des Textes inline.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._rect = QRectF(0, 0, 150, 60)

        # Untergeordnetes Textelement für die Inline-Bearbeitung
        self._text_item = _EditableText(self)
        self._text_item.setPlainText(str(tr("item.default_text")))
        self._text_item.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        # Klicks außerhalb der Bearbeitung nicht abfangen — sie an die
        # übergeordnete TextBox durchreichen, damit das ganze Feld zum
        # Auswählen / Ziehen anklickbar ist.
        self._text_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        # Schwarze »Tinte« unabhängig vom UI-Design erzwingen: Der Text bildet
        # ab, was auf das (weiße) Band gedruckt wird, also muss er schwarz
        # bleiben, selbst wenn die App im Darkmode läuft (dessen Palette die
        # Glyphen sonst hell einfärben und auf dem weißen Etikett unlesbar
        # machen würde).
        self._text_item.setDefaultTextColor(QColor(Qt.GlobalColor.black))
        # Qts standardmäßigen inneren 4-px-Rand entfernen, damit wir die Positionierung steuern
        self._text_item.document().setDocumentMargin(0)
        self._text_item.document().contentsChanged.connect(self._on_text_changed)

        # 0 = normal, 1 = hochgestellt, -1 = tiefgestellt
        self._vert_align: int = 0

        # Horizontale Ausrichtung der Textzeilen innerhalb des Feldes. Bleibt
        # erhalten: wird beim Ändern der Feldgröße oder beim Bearbeiten des
        # Textes weiter angewendet. Sichtbar unterscheidet sie sich nur, wenn
        # das Feld breiter als eine Zeile ist (mehrzeiliger Text oder ein Feld,
        # das breiter als sein Inhalt gezogen wurde).
        self._h_align: str = H_ALIGN_LEFT

        # Bei True (Standard) folgt die Feldbreite dem Text: Tippen verlängert
        # das Feld nach rechts, statt in eine neue Zeile umzubrechen. Das Ziehen
        # eines Breitengriffs schaltet das Feld in den Modus mit fester Breite
        # (Text bricht innerhalb um).
        self._auto_width: bool = True

        # Zustand während der Größenänderung
        self._handle_selected: int | None = None
        self._press_scene_pos: QPointF | None = None
        self._press_rect: QRectF | None = None
        self._press_item_pos: QPointF | None = None

        # _update_text_geometry zentriert das Feld bei einer Höhenänderung neu
        # um seinen vertikalen Mittelpunkt. Beim allerersten Aufruf (während
        # __init__) überspringen, wenn self._rect noch die Platzhaltergröße hat
        # und das Element vom Aufrufer noch nicht positioniert wurde.
        self._geometry_seeded = False

        # Qt-Flags
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

        self._update_text_geometry()

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def set_font(self, font: QFont) -> None:
        self._text_item.setFont(font)
        self._update_text_geometry()
        self.update()

    def get_font(self) -> QFont:
        return self._text_item.font()

    def get_text(self) -> str:
        return self._text_item.toPlainText()

    def set_text(self, text: str) -> None:
        self._text_item.setPlainText(text)
        # setPlainText baut das Dokument neu auf, daher unsere Formatierung erneut anwenden.
        self._apply_block_format()
        if self._vert_align != 0:
            self._apply_char_format()

    def set_vertical_align(self, align: int) -> None:
        """Setzt 0=normal, 1=hochgestellt, -1=tiefgestellt für das gesamte Textfeld."""
        self._vert_align = align
        self._apply_char_format()
        self._update_text_geometry()
        self.update()

    def get_vertical_align(self) -> int:
        return self._vert_align

    def set_h_align(self, align: str) -> None:
        """Setzt die horizontale Textausrichtung: links / zentriert / rechts / Blocksatz."""
        if align not in _H_ALIGN_VALUES:
            align = H_ALIGN_LEFT
        self._h_align = align
        self._apply_block_format()

        # Bei einem MEHRZEILIGEN Feld mit nicht-linker Ausrichtung dieses auf
        # eine feste Breite fixieren. Andernfalls wächst das Auto-Breite-Feld
        # beim Tippen der längsten Zeile immer weiter, und die zentrierten/
        # rechtsbündigen Zeilen springen bei jedem Tastendruck umher. Feste
        # Breite hält die Ausrichtung an Ort und Stelle und lässt zusätzlichen
        # Text stattdessen umbrechen. Linksbündige und einzeilige Felder
        # behalten die Auto-Breite (dort springt nichts, und Tippen lässt das
        # Feld weiter wachsen).
        if (self._auto_width and align != H_ALIGN_LEFT
                and self._visual_line_count() > 1):
            self._text_item.setTextWidth(-1)
            nat_w = self._text_item.document().idealWidth()
            self._auto_width = False
            self.prepareGeometryChange()
            self._rect = QRectF(0, 0, max(MIN_W, round(nat_w) + 2.0),
                                self._rect.height())

        self._update_text_geometry()
        self.update()

    def get_h_align(self) -> str:
        return self._h_align

    def get_format(self) -> dict:
        """Gibt ein dict zurück, das die komplette Formatierung dieses Feldes beschreibt."""
        return {
            "font":       QFont(self._text_item.font()),
            "vert_align": self._vert_align,
            "h_align":    self._h_align,
        }

    def apply_format(self, fmt: dict) -> None:
        """Wendet ein von get_format() erzeugtes Format-dict an."""
        if "font" in fmt:
            self.set_font(QFont(fmt["font"]))
        if "vert_align" in fmt:
            self.set_vertical_align(fmt["vert_align"])
        if "h_align" in fmt:
            self.set_h_align(fmt["h_align"])

    # ------------------------------------------------------------------
    # Interne Hilfsfunktionen
    # ------------------------------------------------------------------

    def _visual_line_count(self) -> int:
        """Gesamtzahl der SICHTBAREN Textzeilen über das gesamte Dokument.

        Zählt umgebrochene Zeilen und blockinterne Zeilentrenner (U+2028),
        sodass ein Feld mit einem einzigen Absatz, aber Zeilenumbrüchen,
        korrekt als mehrzeilig erkannt wird."""
        doc = self._text_item.document()
        n = 0
        blk = doc.firstBlock()
        while blk.isValid():
            lc = blk.layout().lineCount()
            n += lc if lc > 0 else 1
            blk = blk.next()
        return n

    def _update_text_geometry(self) -> None:
        font = self._text_item.font()
        fm   = QFontMetricsF(font)
        text = self._text_item.toPlainText()

        if self._auto_width:
            # Die natürliche (nicht umgebrochene) Breite bei ausgeschaltetem
            # Umbruch ermitteln, dann den Rahmen bei mehrzeiligem Text darauf
            # fixieren, damit die horizontale Ausrichtung Raum hat, die
            # kürzeren Zeilen darin zu verschieben. Eine einzelne Zeile bleibt
            # unbeschränkt (-1), sodass Tippen das Feld nach rechts wachsen lässt.
            #
            # SICHTBARE Zeilen zählen, keine Absätze: Enter im Editor fügt einen
            # Zeilentrenner (U+2028) ein, sodass ein mehrzeiliges Feld oft ein
            # EINZIGER Block mit mehreren Zeilen ist. Die Prüfung auf
            # blockCount() übersah diesen Fall und ließ das Feld ohne Rahmen,
            # sodass die Ausrichtung keinen Bezugsraum hatte.
            self._text_item.setTextWidth(-1)
            nat_w = self._text_item.document().idealWidth()
            if self._visual_line_count() > 1:
                self._text_item.setTextWidth(nat_w)
        else:
            # Feste Breite: den Text innerhalb der vom Nutzer gewählten Breite
            # umbrechen. 1 px horizontalen Rand zulassen (halbe Breite des
            # Rahmenstifts).
            self._text_item.setTextWidth(max(1.0, self._rect.width() - 2.0))

        # Die tatsächliche »Tinten«-Ausdehnung DIESES Textes berechnen —
        # einschließlich des i-Punkts (der über der Versalhöhe sitzt) und von
        # Akzentzeichen (Ä, Ö, …), wenn vorhanden, sowie Unterlängen nur dann,
        # wenn der Text sie tatsächlich hat. Das ergibt ein knappes Feld um die
        # sichtbaren Glyphen, sodass größere Schriften wie 24pt auf 12-mm-Band
        # passen, wenn der Text keine Unterlängen hat.
        #
        # Die zeichenweise Iteration ist ein Workaround für eine bekannte
        # Qt-Eigenheit, bei der tightBoundingRect() auf mehrzeichigen
        # Zeichenketten manchmal die Unterlänge verliert (z. B. meldet »Größe«
        # bottom=0, obwohl »gö« korrekt bottom>0 meldet).
        ink_above = 0.0   # max. »Tinten«-Höhe über der Grundlinie
        ink_below = 0.0   # max. »Tinten«-Tiefe unter der Grundlinie
        for ch in text:
            if not ch.strip():
                continue
            r = fm.tightBoundingRect(ch)
            if -r.top()    > ink_above: ink_above = -r.top()
            if  r.bottom() > ink_below: ink_below =  r.bottom()

        # Leerer Text / nur Leerzeichen: auf Versalhöhe + Unterlänge
        # zurückfallen, damit ein frisches Feld eine sinnvolle »typische«
        # Höhe hat.
        if ink_above == 0.0 and ink_below == 0.0:
            ink_above = fm.capHeight()
            ink_below = fm.descent()

        # Stapelung mehrerer Zeilen
        line_h = fm.lineSpacing()
        doc_h  = self._text_item.boundingRect().height()
        line_count = max(1, round(doc_h / line_h)) if line_h > 0 else 1

        # Auf ganze Pixel runden, damit die Feldkanten dort liegen, wo Qt die
        # »Tinte« tatsächlich setzt (Qt rundet Glyphenpositionen auf Pixel).
        th = round(ink_above + ink_below) + (line_count - 1) * round(line_h)

        # Zielbreite: im Auto-Modus der natürlichen (nicht umgebrochenen)
        # Breite des Textes folgen; im Festmodus die vom Nutzer gewählte Breite
        # unverändert lassen.
        if self._auto_width:
            doc_w = self._text_item.boundingRect().width()
            tw = max(MIN_W, round(doc_w) + 2.0)
        else:
            tw = self._rect.width()

        new_w = self._rect.width()
        new_h = self._rect.height()
        height_changed = th > 0 and abs(th - new_h) > 0.5
        width_changed  = abs(tw - new_w) > 0.5

        if height_changed or width_changed:
            old_h = new_h
            if height_changed:
                new_h = th
            if width_changed:
                new_w = tw
            self.prepareGeometryChange()
            self._rect = QRectF(0, 0, new_w, new_h)
            # Das Feld um seine vertikale Mitte wachsen / schrumpfen lassen.
            # Ohne das verlängert das Tippen von mehr Text (z. B. »Text« →
            # »Apfel« — mit neuer Unterlänge) das Feld nur nach unten, was die
            # Unterlänge über die druckbare Kante hinausschieben kann, obwohl
            # das Feld beim Platzieren optisch zentriert war. Die Breite
            # hingegen wächst nach rechts (die linke Kante bleibt stehen),
            # damit das Feld beim Tippen nicht seitlich verrutscht.
            if self._geometry_seeded and height_changed:
                self.setY(self.y() - (new_h - old_h) / 2.0)
        self._geometry_seeded = True

        # Das Textelement so positionieren, dass die »Tinten«-Oberkante mit der
        # Oberkante des Feldes fluchtet. Qt zeichnet die Grundlinie der ersten
        # Zeile bei y=ascent ab der Oberkante des Textelements, sodass die
        # »Tinten«-Oberkante bei y=(ascent-ink_above) liegt. Das Textelement um
        # diesen Betrag nach oben verschieben, damit ink_top bei Feld-y=0 landet.
        self._text_item.setPos(1.0, -round(fm.ascent() - ink_above))

    def _on_text_changed(self) -> None:
        # Textänderungen können die gerenderte Texthöhe vergrößern/verkleinern
        # (z. B. Zeilenumbruch bei Größenänderung). Das Feld synchron halten.
        self._update_text_geometry()
        self.update()

    def _apply_char_format(self) -> None:
        """Wendet die vertikale Ausrichtung auf alle Zeichen im Dokument an."""
        cursor = QTextCursor(self._text_item.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextCharFormat()
        if self._vert_align == 1:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
        elif self._vert_align == -1:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSubScript)
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        cursor.setCharFormat(fmt)

    def _qt_alignment(self):
        return {
            H_ALIGN_LEFT:    Qt.AlignmentFlag.AlignLeft,
            H_ALIGN_CENTER:  Qt.AlignmentFlag.AlignHCenter,
            H_ALIGN_RIGHT:   Qt.AlignmentFlag.AlignRight,
            H_ALIGN_JUSTIFY: Qt.AlignmentFlag.AlignJustify,
        }.get(self._h_align, Qt.AlignmentFlag.AlignLeft)

    def _apply_block_format(self) -> None:
        """Wendet die horizontale Ausrichtung auf jede Zeile des Dokuments an."""
        align = self._qt_alignment()
        doc = self._text_item.document()
        # Standardoption, damit neu getippte Zeilen die Ausrichtung erben.
        opt = doc.defaultTextOption()
        opt.setAlignment(align)
        doc.setDefaultTextOption(opt)
        # Und auf alle vorhandenen Blöcke anwenden.
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        bfmt = QTextBlockFormat()
        bfmt.setAlignment(align)
        cursor.mergeBlockFormat(bfmt)

    def _handle_rects(self) -> dict:
        # Nur die vier ECK-Griffe (zwei pro Seite). Die Höhe passt sich
        # automatisch an den Text an, sodass die Ecken zum Ändern der Breite
        # genügen; die Seiten-/Kanten-Griffe sind bewusst weggelassen, um die
        # Bedienelemente schlicht zu halten.
        # Die Griffe liegen vollständig AUSSERHALB des Rechtecks, damit die
        # gesamte Innenfläche zum Verschieben greifbar bleibt, selbst wenn das
        # Feld klein ist.
        r = self._rect
        s = HANDLE_SIZE
        return {
            HANDLE_TL: QRectF(r.left()  - s, r.top()    - s, s, s),
            HANDLE_TR: QRectF(r.right(),     r.top()    - s, s, s),
            HANDLE_BR: QRectF(r.right(),     r.bottom(),     s, s),
            HANDLE_BL: QRectF(r.left()  - s, r.bottom(),     s, s),
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
        # Im Druckmodus: hier nichts zeichnen – das untergeordnete
        # QGraphicsTextItem rendert den Text selbst und erzeugt ein sauberes
        # Etikett ohne Rahmen, Hintergrundfärbung oder Größengriffe.
        if _PRINTING:
            return

        selected = self.isSelected()

        # Hintergrund
        painter.setBrush(QBrush(COLOR_BG))
        painter.setPen(_border_pen(selected))
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
                # Eingebautes Verschieben deaktivieren, damit nur die Größenänderung erfolgt
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

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Maus auf dem Textelement aktivieren, damit der Nutzer den Cursor
            # während der Bearbeitung durch Klick in den Text positionieren kann.
            self._text_item.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
            self._text_item.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextEditorInteraction
            )
            self._text_item.setFocus()
            # Gesamten Text auswählen, damit der Nutzer sofort tippen kann, um ihn zu ersetzen
            cursor = self._text_item.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            self._text_item.setTextCursor(cursor)
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    # Logik der Größenänderung
    # ------------------------------------------------------------------

    def _do_resize(self, scene_pos: QPointF) -> None:
        # Die Höhe passt sich automatisch an den Text an – nur die Breite wird
        # vom Nutzer gesteuert. Das Ziehen eines Breitengriffs fixiert die
        # Breite, sodass das Feld den Text nun innerhalb dieser Breite umbricht,
        # statt automatisch nach rechts zu wachsen.
        self._auto_width = False
        delta  = scene_pos - self._press_scene_pos
        orig_w = self._press_rect.width()
        orig_x = self._press_item_pos.x()
        orig_y = self._press_item_pos.y()

        new_w = orig_w
        new_x = orig_x

        h = self._handle_selected

        # --- Eck-Griffe: symmetrische Breitenänderung um die Mitte ---
        if h in CORNER_HANDLES:
            orig_cx = orig_x + orig_w / 2
            if h in (HANDLE_TL, HANDLE_BL):
                new_w = max(MIN_W, orig_w - 2 * delta.x())
            else:                                       # HANDLE_TR, HANDLE_BR
                new_w = max(MIN_W, orig_w + 2 * delta.x())
            new_x = orig_cx - new_w / 2

        # --- Seitenkanten: asymmetrisch, gegenüberliegende Kante bleibt stehen ---
        elif h == HANDLE_L:
            new_w = orig_w - delta.x()
            if new_w < MIN_W:
                new_w = MIN_W
                new_x = orig_x + orig_w - MIN_W
            else:
                new_x = orig_x + delta.x()

        elif h == HANDLE_R:
            new_w = max(MIN_W, orig_w + delta.x())

        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, new_w, self._rect.height())
        self.setPos(new_x, orig_y)
        self._update_text_geometry()
        self.update()
