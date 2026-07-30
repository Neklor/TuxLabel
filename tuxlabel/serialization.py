# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON-basiertes Speichern/Laden von .ptle-Dateien (TuxLabel).

Koordinaten werden in Millimetern gespeichert, damit die Dateien
unabhängig von einer abweichenden Bildschirm-DPI auf dem nächsten
Rechner robust bleiben.
"""

from __future__ import annotations

import base64
import json

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PyQt6.QtGui import QFont, QPixmap

from . import label_canvas as _lc
from .text_item import TextBox
from .image_item import ImageBox

FILE_VERSION = 1


def _pixmap_to_b64(pixmap: QPixmap) -> str:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return base64.b64encode(bytes(data)).decode("ascii")


def _b64_to_pixmap(b64: str) -> QPixmap:
    raw = base64.b64decode(b64)
    pixmap = QPixmap()
    pixmap.loadFromData(raw, "PNG")
    return pixmap


def item_to_dict(item) -> dict | None:
    """Serialisiert eine einzelne TextBox / ImageBox in ein einfaches dict
    (mm-Koordinaten).

    Gibt None für alles zurück, das kein Inhaltselement ist. Wird sowohl
    beim Speichern von Dateien als auch beim Kopieren in die Zwischenablage
    genutzt, damit beide synchron bleiben."""
    ppmm = _lc.PIXELS_PER_MM
    if isinstance(item, TextBox):
        font = item.get_font()
        return {
            "type":        "text",
            "x_mm":        item.pos().x() / ppmm,
            "y_mm":        item.pos().y() / ppmm,
            "w_mm":        item._rect.width() / ppmm,
            "auto_width":  item._auto_width,
            "text":        item.get_text(),
            "font_family": font.family(),
            "font_size_pt": font.pointSize(),
            "bold":        font.bold(),
            "italic":      font.italic(),
            "underline":   font.underline(),
            "strikeout":   font.strikeOut(),
            "vert_align":  item.get_vertical_align(),
            "h_align":     item.get_h_align(),
        }
    if isinstance(item, ImageBox):
        return {
            "type":         "image",
            "x_mm":         item.pos().x() / ppmm,
            "y_mm":         item.pos().y() / ppmm,
            "w_mm":         item._rect.width()  / ppmm,
            "h_mm":         item._rect.height() / ppmm,
            "data_png_b64": _pixmap_to_b64(item.get_pixmap()),
        }
    return None


def item_from_dict(entry: dict):
    """Erzeugt eine TextBox / ImageBox aus einem von item_to_dict()
    erstellten dict.

    Das Element wird erzeugt und positioniert, aber KEINER Szene
    hinzugefügt. Gibt None zurück, wenn der Eintrag nicht rekonstruiert
    werden kann."""
    ppmm = _lc.PIXELS_PER_MM
    kind = entry.get("type")
    if kind == "text":
        font = QFont(entry.get("font_family", "Noto Serif"),
                     int(entry.get("font_size_pt", 12)))
        font.setBold     (bool(entry.get("bold",      False)))
        font.setItalic   (bool(entry.get("italic",    False)))
        font.setUnderline(bool(entry.get("underline", False)))
        font.setStrikeOut(bool(entry.get("strikeout", False)))

        tb = TextBox()
        tb._auto_width = bool(entry.get("auto_width", True))
        w_px = float(entry.get("w_mm", 20)) * ppmm
        tb._rect = QRectF(0, 0, w_px, 1.0)
        tb._update_text_geometry()
        tb.set_font(font)
        tb.set_vertical_align(int(entry.get("vert_align", 0)))
        tb.set_h_align(entry.get("h_align", "left"))
        tb.set_text(entry.get("text", ""))
        tb.setPos(float(entry.get("x_mm", 0)) * ppmm,
                  float(entry.get("y_mm", 0)) * ppmm)
        return tb

    if kind == "image":
        pixmap = _b64_to_pixmap(entry.get("data_png_b64", ""))
        if pixmap.isNull():
            return None
        ib = ImageBox(pixmap)
        ib.set_size(float(entry.get("w_mm", 10)) * ppmm,
                    float(entry.get("h_mm", 10)) * ppmm)
        ib.setPos(float(entry.get("x_mm", 0)) * ppmm,
                  float(entry.get("y_mm", 0)) * ppmm)
        return ib

    return None


def scene_to_dict(scene) -> dict:
    items = [d for item in scene.items() if (d := item_to_dict(item)) is not None]
    # scene.items() liefert von vorne nach hinten; umkehren, damit die
    # gespeicherte Reihenfolge stabil bleibt
    items.reverse()

    return {
        "version":           FILE_VERSION,
        "tape_width_mm":     scene.get_tape_width_mm(),
        "label_length_mm":   scene.get_label_length_mm(),
        "auto_length":       scene._auto_length,
        "flag_mode":         scene.get_flag_mode(),
        "cable_diameter_mm": scene.get_cable_diameter_mm(),
        "flag_middle_mm":    scene.get_flag_middle_mm(),
        "flag_copy":         scene.get_flag_copy(),
        "items":             items,
    }


def scene_from_dict(scene, data: dict) -> None:
    # Vorhandene Inhaltselemente entfernen (Hintergrund/Lineal/etc. behalten)
    for item in list(scene.items()):
        if isinstance(item, (TextBox, ImageBox)):
            scene.removeItem(item)

    # Band + Länge zuerst anwenden, damit die Koordinaten im richtigen
    # druckbaren Bereich landen. Auto-Länge vorübergehend deaktivieren,
    # damit eine explizit gespeicherte Länge berücksichtigt wird.
    scene.set_tape_width(data.get("tape_width_mm", 12))
    scene.set_auto_length(False)
    scene.set_label_length_mm(int(data.get("label_length_mm", 30)))

    for entry in data.get("items", []):
        item = item_from_dict(entry)
        if item is not None:
            scene.addItem(item)

    scene.set_auto_length(bool(data.get("auto_length", True)))

    # Kabelfähnchen-Einstellungen erst wiederherstellen, nachdem die Elemente
    # existieren (damit die Fähnchenbreite zum Inhalt passt). Zuerst den
    # Durchmesser setzen (der die Mitte anhand des Umfangs neu berechnet),
    # dann die gespeicherte Mitte anwenden, um eine manuelle Anpassung zu
    # berücksichtigen, und zuletzt den Fähnchen-Modus umschalten, der die
    # Länge ableitet.
    scene.set_cable_diameter_mm(float(data.get("cable_diameter_mm", 5.0)))
    scene.set_flag_middle_mm(
        float(data.get("flag_middle_mm", scene.get_flag_middle_mm()))
    )
    scene.set_flag_copy(bool(data.get("flag_copy", True)))
    scene.set_flag_mode(bool(data.get("flag_mode", False)))


def save_to_file(scene, path: str) -> None:
    data = scene_to_dict(scene)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_from_file(scene, path: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    scene_from_dict(scene, data)
