# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Von Hand gezeichnete Symbolleisten-Icons.

Hier gehalten (statt als PNG-Dateien), damit die App ein reines
Python-Paket ohne Binär-Abhängigkeiten bleibt. Jede Hilfsfunktion gibt ein
frisch gerendertes QIcon zurück — einmal beim Aufbau der Symbolleiste
aufrufen und eine Referenz behalten."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QBrush, QColor, QIcon, QImage, QPainter, QPalette, QPen, QPixmap, QPolygonF,
)
from PyQt6.QtWidgets import QApplication


_COLOR_INK_LIGHT_BG = QColor("#2C3E50")   # dunkles Schiefergrau — für helle Oberfläche
_COLOR_INK_DARK_BG  = QColor("#D5DCE2")   # helles Schiefergrau — für dunkle Oberfläche
_COLOR_ACCENT = QColor("#27AE60")   # grün (+-Abzeichen, Berg)
_COLOR_SKY    = QColor("#EAF4FB")   # sehr helles Blau (Bildhintergrund)
_COLOR_SUN    = QColor("#F39C12")   # orange (Sonne)
_COLOR_WHITE  = QColor("#FFFFFF")

# Farben des Programmsymbols. Bewusst FEST und unabhängig von _ink(): das
# App-Icon erscheint in Fensterleiste, Anwendungsmenü und Alt+Tab, also vor
# Hintergründen, die das Programm nicht kennt. Ein mitdrehendes Icon wäre dort
# mal unsichtbar, mal grell — deshalb bringt es seinen eigenen Untergrund mit.
_COLOR_ICON_BG   = QColor("#2C3E50")   # Untergrund (Schiefergrau, trägt auf hell und dunkel)
_COLOR_ICON_TAPE = QColor("#FFFFFF")   # das TZe-Band
_COLOR_ICON_TEXT = QColor("#2C3E50")   # Textzeilen auf dem Band
_COLOR_ICON_EDGE = QColor("#95A5A6")   # angeschnittene Bandenden links/rechts

# Größen, die das QIcon mitbringt, und die install_shortcut.py als PNG in das
# hicolor-Theme schreibt. Jede wird EINZELN gezeichnet statt herunterskaliert —
# bei 16 px entscheidet das darüber, ob man noch etwas erkennt.
APP_ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def _ink(dark: bool | None = None) -> QColor:
    """Linien-/Strichfarbe für Icons, angepasst an das aktive UI-Design.

    Bei einem Live-Wechsel des Designs *dark* explizit übergeben — die
    Palette auszulesen ist dann unzuverlässig, weil ``QApplication.setPalette``
    sich asynchron an bestehende Widgets fortpflanzt (über ein gepostetes
    PaletteChange-Event), sodass die Palette direkt nach dem Wechsel noch das
    *alte* Design meldet. Ist *dark* None (z. B. beim ersten Aufbau), ist die
    Palette maßgeblich und wird verwendet."""
    if dark is None:
        app = QApplication.instance()
        dark = (app is not None and
                app.palette().color(QPalette.ColorRole.Window).lightness() < 128)
    return _COLOR_INK_DARK_BG if dark else _COLOR_INK_LIGHT_BG


def _draw_plus_badge(p: QPainter, size: int) -> None:
    """Zeichnet ein grünes »+«-Abzeichen unten rechts auf der Icon-Fläche."""
    badge = int(size * 0.50)
    bx = size - badge
    by = size - badge

    # Weißer Rand zur Abgrenzung gegen dunkle Icon-Striche
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_COLOR_WHITE))
    p.drawEllipse(bx - 1, by - 1, badge + 2, badge + 2)

    # Grüne Scheibe
    p.setBrush(QBrush(_COLOR_ACCENT))
    p.drawEllipse(bx, by, badge, badge)

    # Weißes Plus-Zeichen
    p.setPen(QPen(_COLOR_WHITE, max(1.5, badge / 7.0),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    cx = bx + badge / 2.0
    cy = by + badge / 2.0
    arm = badge * 0.28
    p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


def make_add_text_icon(size: int = 28, dark: bool | None = None) -> QIcon:
    """Ein fettes »T« mit kleinem »+«-Abzeichen — Schaltfläche »Text hinzufügen«."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # »T« aus zwei Rechtecken gezeichnet, damit es bei kleinen Größen scharf bleibt
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_ink(dark)))

    bar_w = int(size * 0.62)
    bar_h = max(2, size * 3 // 16)
    bar_x = int(size * 0.08)
    bar_y = int(size * 0.18)
    p.drawRect(bar_x, bar_y, bar_w, bar_h)

    stem_w = max(2, size * 3 // 16)
    stem_h = int(size * 0.62)
    stem_x = bar_x + (bar_w - stem_w) // 2
    stem_y = bar_y
    p.drawRect(stem_x, stem_y, stem_w, stem_h)

    _draw_plus_badge(p, size)
    p.end()
    return QIcon(pm)


def make_print_icon(size: int = 28, dark: bool | None = None) -> QIcon:
    """Ein Drucker-Icon — Papier oben herausragend, Gehäuse darunter, Status-Punkt."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = _ink(dark)

    # Papier (oben, ragt über das Druckergehäuse hinaus)
    paper_x = int(size * 0.22)
    paper_y = int(size * 0.06)
    paper_w = int(size * 0.56)
    paper_h = int(size * 0.42)
    p.setPen(QPen(ink, max(1.0, size / 20.0)))
    p.setBrush(QBrush(_COLOR_WHITE))
    p.drawRect(paper_x, paper_y, paper_w, paper_h)
    # Textähnliche waagerechte Linien
    p.setPen(QPen(ink, max(0.7, size / 32.0)))
    for i in (1, 2):
        ly = paper_y + paper_h * i / 3
        p.drawLine(int(paper_x + 3), int(ly),
                   int(paper_x + paper_w - 3), int(ly))

    # Druckergehäuse (abgerundetes Rechteck, breiter als das Papier)
    body_x = int(size * 0.08)
    body_y = int(size * 0.45)
    body_w = int(size * 0.84)
    body_h = int(size * 0.36)
    p.setPen(QPen(ink, max(1.0, size / 18.0)))
    p.setBrush(QBrush(QColor("#7F8C8D")))   # Grau des Druckergehäuses
    p.drawRoundedRect(body_x, body_y, body_w, body_h, 3, 3)

    # Ausgabeschlitz an der Unterseite des Gehäuses
    slot_x = int(body_x + body_w * 0.18)
    slot_w = int(body_w * 0.64)
    slot_y = int(body_y + body_h - max(2, size / 14))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#34495E")))
    p.drawRect(slot_x, slot_y, slot_w, max(1, int(size / 16)))

    # Statusanzeige (grüner Punkt)
    dot_r = max(1.5, size / 16.0)
    dot_cx = body_x + body_w - dot_r * 2.5
    dot_cy = body_y + body_h / 2.0
    p.setBrush(QBrush(_COLOR_ACCENT))
    p.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)

    p.end()
    return QIcon(pm)


def make_align_icon(kind: str, size: int = 28, dark: bool | None = None) -> QIcon:
    """Icon für Absatzausrichtung (4 unregelmäßige Textzeilen).

    *kind* ist eines von "left", "center", "right", "justify". Bei "justify"
    überspannen alle Zeilen die volle Breite; andernfalls variieren die
    Zeilenlängen, um eine unregelmäßige Kante anzudeuten, die links, zentriert
    oder rechts sitzt."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    lw = max(1.5, size / 14.0)
    p.setPen(QPen(_ink(dark), lw, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))

    left  = size * 0.16
    right = size * 0.84
    full  = right - left
    ys    = [size * 0.26, size * 0.42, size * 0.58, size * 0.74]
    fracs = [1.0, 1.0, 1.0, 1.0] if kind == "justify" else [1.0, 0.6, 0.85, 0.5]

    for y, fr in zip(ys, fracs):
        w = full * fr
        if kind in ("left", "justify"):
            x0 = left
        elif kind == "center":
            x0 = left + (full - w) / 2.0
        else:  # rechts
            x0 = right - w
        p.drawLine(QPointF(x0, y), QPointF(x0 + w, y))

    p.end()
    return QIcon(pm)


def _paint_app_icon(p: QPainter, size: int) -> None:
    """Zeichnet das Programmsymbol in *size*×*size*: ein beschriftetes Band auf
    abgerundetem Untergrund.

    Bewusst schlicht gehalten. Das Symbol muss bei 16 px in der Fensterleiste
    noch lesbar sein, und dort überlebt nur eine kräftige Grundform — ein
    heller Balken auf dunklem Grund. Feinheiten (Textzeilen, Bandenden)
    kommen erst bei größeren Kantenlängen zum Tragen."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # --- Untergrund: abgerundetes Quadrat mit schmalem Rand ---
    margin = size * 0.06
    radius = size * 0.22
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_COLOR_ICON_BG))
    p.drawRoundedRect(QRectF(margin, margin,
                             size - 2 * margin, size - 2 * margin),
                      radius, radius)

    # --- Das Band, waagerecht durchlaufend ---
    # Absichtlich ein schmaler Streifen mit viel Untergrund darüber und
    # darunter: erst dieses Verhältnis liest sich als *Band*. Füllt das Weiß
    # die Fläche, wirkt das Symbol wie ein Texteingabefeld.
    tape_h = size * 0.30
    # Etwas unter die Mitte gerückt: Lineal und Band bilden zusammen die
    # Bildmarke, und die soll als Gruppe zentriert sitzen — nicht das Band
    # allein, sonst kippt die Komposition nach oben.
    tape_y = (size - tape_h) / 2.0 + size * 0.06
    tape_x = size * 0.16
    tape_w = size - 2 * tape_x
    p.setBrush(QBrush(_COLOR_ICON_TAPE))
    p.drawRect(QRectF(tape_x, tape_y, tape_w, tape_h))

    # Angeschnittene Bandenden: zwei graue Streifen, die das Band optisch
    # fortsetzen — der Eindruck einer Endlos-Kassette. Sie bleiben mit Abstand
    # innerhalb des Untergrunds, damit die abgerundete Silhouette erhalten
    # bleibt. Unter 32 px würden sie in der Kantenglättung verschmieren.
    if size >= 32:
        edge_w = size * 0.04
        p.setBrush(QBrush(_COLOR_ICON_EDGE))
        p.drawRect(QRectF(tape_x - edge_w, tape_y, edge_w, tape_h))
        p.drawRect(QRectF(tape_x + tape_w, tape_y, edge_w, tape_h))

    # --- Lineal-Skala über dem Band ---
    # Greift das Lineal auf, das im Programm über jedem Etikett steht: das
    # macht aus einem beliebigen weißen Balken ein *vermessenes* Etikett und
    # füllt die Fläche, die bei großen Kantenlängen sonst leer bliebe. Erst ab
    # 48 px sinnvoll — darunter fehlt der Platz zwischen den Strichen.
    if size >= 48:
        tick_lw = max(1.0, size / 42.0)
        p.setPen(QPen(_COLOR_ICON_EDGE, tick_lw, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.FlatCap))
        base_y = tape_y - size * 0.045          # Grundlinie, etwas über dem Band
        long_h = size * 0.075                   # Zentimeter-Strich
        short_h = long_h * 0.55                 # Zwischenstrich
        for i in range(9):
            tx = tape_x + tape_w * i / 8.0
            th = long_h if i % 2 == 0 else short_h
            p.drawLine(QPointF(tx, base_y), QPointF(tx, base_y - th))

    # --- Textzeilen auf dem Band ---
    # Ungleich lang, wie im Ausrichtungs-Icon: das liest sich als Text und
    # nicht als Muster. Die Anzahl richtet sich nach dem Platz — unter 24 px
    # bleibt der Streifen leer, weil eine Linie dort nur noch Grau ergibt.
    if size < 24:
        return
    fracs = (1.0,) if size < 40 else (1.0, 0.62)

    lw = max(1.0, size / 20.0)
    p.setPen(QPen(_COLOR_ICON_TEXT, lw, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    inset = tape_w * 0.14
    x0 = tape_x + inset
    full = tape_w - 2 * inset
    for i, fr in enumerate(fracs):
        # Zeilen gleichmäßig über die Bandhöhe verteilen
        y = tape_y + tape_h * (i + 1) / (len(fracs) + 1)
        p.drawLine(QPointF(x0, y), QPointF(x0 + full * fr, y))


def app_icon_image(size: int) -> QImage:
    """Das Programmsymbol als QImage in der gewünschten Kantenlänge.

    Absichtlich QImage und nicht QPixmap: QImage funktioniert ohne laufende
    ``QGuiApplication`` und ohne Display. Nur so kann ``install_shortcut.py``
    die PNG-Dateien für das Icon-Theme schreiben, ohne selbst eine
    Qt-Anwendung zu starten."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    _paint_app_icon(p, size)
    p.end()
    return img


def app_icon_pixmap(size: int) -> QPixmap:
    """Das Programmsymbol als QPixmap — benötigt eine laufende QGuiApplication."""
    return QPixmap.fromImage(app_icon_image(size))


def make_app_icon() -> QIcon:
    """Programmsymbol für ``QApplication.setWindowIcon``.

    Enthält alle Größen aus :data:`APP_ICON_SIZES`, jede einzeln gezeichnet.
    Qt wählt daraus die passende — für den Fenstertitel, Alt+Tab und die
    Fensterleiste, die alle unterschiedliche Kantenlängen anfragen."""
    icon = QIcon()
    for s in APP_ICON_SIZES:
        icon.addPixmap(app_icon_pixmap(s))
    return icon


def make_add_image_icon(size: int = 28, dark: bool | None = None) -> QIcon:
    """Ein kleines Bild (Rahmen, Berg, Sonne) mit »+«-Abzeichen — »Bild hinzufügen«."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Bilderrahmen
    fx = int(size * 0.10)
    fy = int(size * 0.18)
    fw = int(size * 0.72)
    fh = int(size * 0.60)
    p.setPen(QPen(_ink(dark), max(1.0, size / 18.0)))
    p.setBrush(QBrush(_COLOR_SKY))
    p.drawRect(fx, fy, fw, fh)

    # Sonne
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_COLOR_SUN))
    sun_r = max(1.5, size / 10.0)
    sun_cx = fx + fw * 0.30
    sun_cy = fy + fh * 0.32
    p.drawEllipse(QPointF(sun_cx, sun_cy), sun_r, sun_r)

    # Berg (Dreieck, an der Unterkante verankert)
    p.setBrush(QBrush(_COLOR_ACCENT))
    p.drawPolygon(QPolygonF([
        QPointF(fx + fw * 0.05, fy + fh - 1),
        QPointF(fx + fw * 0.45, fy + fh * 0.40),
        QPointF(fx + fw * 0.78, fy + fh - 1),
    ]))

    _draw_plus_badge(p, size)
    p.end()
    return QIcon(pm)
