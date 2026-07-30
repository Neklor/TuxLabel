# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hauptfenster der Anwendung für TuxLabel."""

from __future__ import annotations

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QSettings, QSize, QTimer
from PyQt6.QtGui import QAction, QFont, QKeySequence, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .dialogs import AboutDialog, HelpDialog, SettingsDialog, ShortcutsDialog
from .i18n import fmt_number, tr
from .theme import DARK_MODE_KEY
from .icons import (
    make_add_image_icon, make_add_text_icon, make_align_icon, make_print_icon,
)
from .image_item import ImageBox
from .label_canvas import (
    DEFAULT_LABEL_LENGTH_MM,
    TAPE_WIDTHS,
    LabelScene,
    LabelView,
)
from .printer import print_label
from .serialization import load_from_file, save_to_file, scene_to_dict, scene_from_dict
from .text_item import TextBox


# Maximale Anzahl der Einträge im Menü »Datei → Verlauf«
_RECENT_MAX = 10

# Rückgängig-Stapel: Entprellung + Obergrenze
_UNDO_DEBOUNCE_MS = 600
_UNDO_MAX_STEPS   = 50


def _fit_button_width(btn, min_w: int, pad: int = 14) -> None:
    """Feste Knopfbreite aus den Fontmetriken ableiten statt hart zu kodieren —
    übersetzte Beschriftungen (Sprachdateien!) dürfen breiter sein als die
    deutschen und würden sonst abgeschnitten."""
    w = btn.fontMetrics().horizontalAdvance(btn.text()) + pad
    btn.setFixedWidth(max(min_w, w))


def _fit_spin_width(spin, sample: str, min_w: int) -> None:
    """Wie :func:`_fit_button_width`, für Drehfelder: *sample* ist der längste
    darstellbare Inhalt (Präfix + Maximalwert + Suffix)."""
    w = spin.fontMetrics().horizontalAdvance(sample) + 36   # Pfeiltasten + Rahmen
    spin.setFixedWidth(max(min_w, w))


class _UndoController:
    """Schnappschuss-basiertes Rückgängig für die Etikett-Szene.

    Lauscht mit einer Entprellung auf ``scene.changed``, sodass ein einzelnes
    Ziehen oder ein Schwall von Änderungen zu einem Rückgängig-Schritt
    zusammenfällt. Schnappschüsse sind vollständige Szenen-Dictionaries von
    :func:`scene_to_dict`."""

    def __init__(self, scene: LabelScene):
        self._scene = scene
        self._stack: list[dict] = [scene_to_dict(scene)]
        self._suspended = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(_UNDO_DEBOUNCE_MS)
        self._timer.timeout.connect(self._maybe_push)
        scene.changed.connect(self._on_scene_changed)

    def reset(self) -> None:
        """Verwirft die Historie und erfasst den aktuellen Zustand als neue Basis."""
        self._timer.stop()
        self._stack = [scene_to_dict(self._scene)]

    def can_undo(self) -> bool:
        return len(self._stack) > 1

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self._stack.pop()
        target = self._stack[-1]
        self._suspended = True
        try:
            scene_from_dict(self._scene, target)
        finally:
            # Etwaige scene.changed-Ereignisse nach der Wiederherstellung
            # abklingen lassen, bevor wieder aktiviert wird — sonst würden wir
            # den wiederhergestellten Zustand sofort als »neuen« Schnappschuss
            # ablegen.
            QTimer.singleShot(200, self._unsuspend)
        return True

    def _unsuspend(self) -> None:
        self._suspended = False

    def _on_scene_changed(self, _regions=None) -> None:
        if self._suspended:
            return
        self._timer.start()

    def _maybe_push(self) -> None:
        if self._suspended:
            return
        snap = scene_to_dict(self._scene)
        if self._stack and snap == self._stack[-1]:
            return
        self._stack.append(snap)
        if len(self._stack) > _UNDO_MAX_STEPS:
            self._stack.pop(0)


class MainWindow(QMainWindow):
    """Das Hauptfenster: Werkzeugleiste + Etikett-Zeichenfläche."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(900, 460)

        # Szene & Ansicht
        self._scene = LabelScene()
        self._view  = LabelView(self._scene)
        self.setCentralWidget(self._view)

        self._format_clipboard: dict | None = None

        # Datei- / Änderungszustand
        self._current_path: str | None = None
        self._dirty: bool = False
        # Das Markieren als geändert unterdrücken, bis alles verdrahtet ist,
        # damit die Einrichtung von Werkzeugleiste und Szene das Dokument nicht
        # bereits als verändert meldet.
        self._suspend_dirty: bool = True

        self._build_menu()
        self._build_toolbar()
        self._restore_settings()

        # Rückgängig-Controller — NACH der Werkzeugleiste erstellt, damit der
        # anfänglich per Werkzeugleiste angewendete Zustand sein Basis-Schnappschuss ist.
        self._undo = _UndoController(self._scene)

        # Dauerhafte Widgets der Statusleiste:
        #   • kurzer Tastenkürzel-Hinweis links im dauerhaften Bereich —
        #     showMessage() zeigt vorübergehende Rückmeldungen links davon an;
        #     es überschreibt dieses Widget nie, sodass der Hinweis z. B. nach
        #     dem Einfügen eines Bildes sichtbar bleibt.
        #   • aktuelle Etikettenlänge ganz rechts.
        self._status_hint = QLabel(tr("status.hint"))
        self._status_hint.setStyleSheet("QLabel { color: #888888; }")
        self.statusBar().addPermanentWidget(self._status_hint)

        self._status_length = QLabel()
        self._style_status_length()
        self.statusBar().addPermanentWidget(self._status_length)
        self._update_status_length()

        # Auswahländerung der Szene verbinden, um den Zustand der Werkzeugleiste zu aktualisieren
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._scene.labelLengthChanged.connect(self._on_label_length_scene_changed)
        self._scene.labelLengthChanged.connect(self._update_status_length)
        # Dokument als geändert markieren, sobald sich die Szene ändert (nach dem Abklingen der Initialisierung)
        self._scene.changed.connect(self._on_scene_changed_dirty)

        self._update_title()
        # Vom Nutzer ausgelöste Szenenänderungen das Dokument als geändert markieren lassen
        QTimer.singleShot(300, self._enable_dirty_tracking)

    # ------------------------------------------------------------------
    # Werkzeugleiste
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar(tr("toolbar.title"))
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)

        # Die gesamte Werkzeugleiste ist ein einzelnes benutzerdefiniertes
        # Widget, angeordnet in drei Spalten: »Hinzufügen« links (über beide
        # Reihen), ein zweireihiger Block von Bedienelementen in der Mitte und
        # eine große Drucken-Schaltfläche rechts (ebenfalls über beide Reihen).
        bar = QWidget()
        outer = QHBoxLayout(bar)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(6)

        def _vsep() -> QFrame:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            return line

        # ── Linke Spalte: »Hinzufügen« (über beide Reihen) ──
        self._add_group = QGroupBox(tr("toolbar.group_add"))
        self._style_add_group()
        add_row = QHBoxLayout(self._add_group)
        add_row.setContentsMargins(0, 0, 0, 0)   # Innenabstand über das Stylesheet gesteuert
        add_row.setSpacing(5)

        self._btn_add_text = QPushButton()
        self._btn_add_text.setIcon(make_add_text_icon(40))
        self._btn_add_text.setIconSize(QSize(34, 34))
        self._btn_add_text.setFixedSize(50, 52)
        self._btn_add_text.setToolTip(tr("toolbar.add_text_tip"))
        self._btn_add_text.clicked.connect(self._add_text_box)
        add_row.addWidget(self._btn_add_text)

        self._btn_add_image = QPushButton()
        self._btn_add_image.setIcon(make_add_image_icon(40))
        self._btn_add_image.setIconSize(QSize(34, 34))
        self._btn_add_image.setFixedSize(50, 52)
        self._btn_add_image.setToolTip(tr("toolbar.add_image_tip"))
        self._btn_add_image.clicked.connect(self._load_image)
        add_row.addWidget(self._btn_add_image)

        outer.addWidget(self._add_group)

        # ── Mitte: zwei Reihen mit Bedienelementen ──
        mid = QWidget()
        mid_v = QVBoxLayout(mid)
        mid_v.setContentsMargins(0, 0, 0, 0)
        mid_v.setSpacing(3)
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(4)
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(4)
        mid_v.addLayout(row1)
        mid_v.addLayout(row2)
        outer.addWidget(mid, 1)

        # --- Bandbreite ---
        row1.addWidget(QLabel(tr("toolbar.tape_width")))
        self._tape_combo = QComboBox()
        for label in TAPE_WIDTHS:
            self._tape_combo.addItem(label)
        self._tape_combo.setCurrentText("12mm")
        self._tape_combo.setToolTip(tr("toolbar.tape_width_tip"))
        self._tape_combo.currentTextChanged.connect(self._on_tape_width_changed)
        row1.addWidget(self._tape_combo)

        row1.addWidget(_vsep())

        # --- Schriftart ---
        row1.addWidget(QLabel(tr("toolbar.font")))
        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(QFont("Noto Serif"))
        self._font_combo.setToolTip(tr("toolbar.font_tip"))
        self._font_combo.setMaximumWidth(200)
        self._font_combo.currentFontChanged.connect(self._on_font_family_changed)
        row1.addWidget(self._font_combo)

        # --- Schriftgröße ---
        row1.addWidget(QLabel(tr("toolbar.size")))
        self._size_combo = QComboBox()
        for pt in [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 48, 72]:
            self._size_combo.addItem(f"{pt} pt", pt)
        self._size_combo.setCurrentText("12 pt")
        self._size_combo.setToolTip(tr("toolbar.size_tip"))
        self._size_combo.currentIndexChanged.connect(self._on_font_size_changed)
        row1.addWidget(self._size_combo)

        row1.addWidget(_vsep())

        # --- Fett / Kursiv / Unterstrichen / Durchgestrichen ---
        # Die Beschriftungen (F/K/U/…) kommen aus der Sprachdatei — z. B. B/I/U
        # im Englischen; die Breite folgt daher den Fontmetriken.
        def _fmt_btn(label: str, tip: str) -> QPushButton:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            _fit_button_width(b, 28)
            return b

        self._btn_bold = _fmt_btn(tr("toolbar.bold"), tr("toolbar.bold_tip"))
        f = QFont(self._btn_bold.font()); f.setBold(True)
        self._btn_bold.setFont(f)
        self._btn_bold.clicked.connect(lambda chk: self._set_font_attr("bold", chk))
        row1.addWidget(self._btn_bold)

        self._btn_italic = _fmt_btn(tr("toolbar.italic"), tr("toolbar.italic_tip"))
        f = QFont(self._btn_italic.font()); f.setItalic(True)
        self._btn_italic.setFont(f)
        self._btn_italic.clicked.connect(lambda chk: self._set_font_attr("italic", chk))
        row1.addWidget(self._btn_italic)

        self._btn_underline = _fmt_btn(tr("toolbar.underline"), tr("toolbar.underline_tip"))
        # Unterstreichung über die Schaltflächenschrift (wie F/K) statt über ein
        # Stylesheet: Ein Stylesheet würde Qts Stylesheet-Renderer erzwingen und
        # die Schaltfläche im aktivierten Zustand hell zeichnen — unter Ignorieren
        # der Design-Palette.
        f = QFont(self._btn_underline.font()); f.setUnderline(True)
        self._btn_underline.setFont(f)
        self._btn_underline.clicked.connect(lambda chk: self._set_font_attr("underline", chk))
        row1.addWidget(self._btn_underline)

        self._btn_strike = _fmt_btn(tr("toolbar.strike"), tr("toolbar.strike_tip"))
        self._btn_strike.clicked.connect(lambda chk: self._set_font_attr("strikeout", chk))
        row1.addWidget(self._btn_strike)

        row1.addWidget(_vsep())

        # --- Horizontale Textausrichtung ---
        self._align_group = QButtonGroup(self)
        self._align_group.setExclusive(True)
        self._align_buttons: dict[str, QPushButton] = {}
        for kind in ("left", "center", "right", "justify"):
            b = QPushButton()
            b.setIcon(make_align_icon(kind, 28))
            b.setCheckable(True)
            b.setFixedWidth(30)
            b.setToolTip(tr("toolbar.align_tip", align=tr(f"toolbar.align_{kind}")))
            b.clicked.connect(lambda _chk, k=kind: self._set_text_align(k))
            self._align_group.addButton(b)
            self._align_buttons[kind] = b
            row1.addWidget(b)
        self._align_buttons["left"].setChecked(True)

        row1.addWidget(_vsep())

        # --- Hochgestellt / Tiefgestellt ---
        self._btn_super = _fmt_btn(tr("toolbar.superscript"), tr("toolbar.superscript_tip"))
        _fit_button_width(self._btn_super, 32)
        self._btn_super.clicked.connect(self._on_super_clicked)
        row1.addWidget(self._btn_super)

        self._btn_sub = _fmt_btn(tr("toolbar.subscript"), tr("toolbar.subscript_tip"))
        _fit_button_width(self._btn_sub, 32)
        self._btn_sub.clicked.connect(self._on_sub_clicked)
        row1.addWidget(self._btn_sub)

        row1.addWidget(_vsep())

        # --- Format übertragen ---
        self._btn_fmt_paint = QPushButton(tr("toolbar.format_paint"))
        self._btn_fmt_paint.setCheckable(True)
        self._btn_fmt_paint.setToolTip(tr("toolbar.format_paint_tip"))
        self._btn_fmt_paint.clicked.connect(self._toggle_format_paint)
        row1.addWidget(self._btn_fmt_paint)
        row1.addStretch(1)

        # ===== Reihe 2 (Positionierung, Etikettengröße, Fähnchen-Modus, Aktionen) =====
        # --- Auf dem Etikett zentrieren ---
        btn_vcenter = QPushButton("↕")
        btn_vcenter.setToolTip(tr("toolbar.vcenter_tip"))
        btn_vcenter.setFixedWidth(28)
        btn_vcenter.clicked.connect(self._center_vertical)
        row2.addWidget(btn_vcenter)

        btn_hcenter = QPushButton("↔")
        btn_hcenter.setToolTip(tr("toolbar.hcenter_tip"))
        btn_hcenter.setFixedWidth(28)
        btn_hcenter.clicked.connect(self._center_horizontal)
        row2.addWidget(btn_hcenter)

        row2.addWidget(_vsep())

        # --- Etikettenlänge ---
        row2.addWidget(QLabel(tr("toolbar.length")))
        self._length_spin = QSpinBox()
        self._length_spin.setRange(10, 2000)
        self._length_spin.setValue(30)
        self._length_spin.setSuffix(tr("toolbar.mm_suffix"))
        _fit_spin_width(self._length_spin, "2000" + tr("toolbar.mm_suffix"), 76)
        self._length_spin.setToolTip(tr("toolbar.length_tip"))
        self._length_spin.setEnabled(False)   # im Auto-Modus deaktiviert
        self._length_spin.valueChanged.connect(self._on_length_changed)
        row2.addWidget(self._length_spin)

        self._btn_auto_length = QPushButton(tr("toolbar.auto"))
        self._btn_auto_length.setCheckable(True)
        self._btn_auto_length.setChecked(True)
        _fit_button_width(self._btn_auto_length, 40)
        self._btn_auto_length.setToolTip(tr("toolbar.auto_tip"))
        self._btn_auto_length.clicked.connect(self._on_auto_length_toggled)
        row2.addWidget(self._btn_auto_length)

        row2.addWidget(_vsep())

        # --- Kabelfähnchen-Modus ---
        self._btn_flag = QPushButton(tr("toolbar.flag"))
        self._btn_flag.setCheckable(True)
        self._btn_flag.setToolTip(tr("toolbar.flag_tip"))
        self._btn_flag.clicked.connect(self._on_flag_toggled)
        row2.addWidget(self._btn_flag)

        self._flag_dia_spin = QDoubleSpinBox()
        self._flag_dia_spin.setRange(0.5, 50.0)
        self._flag_dia_spin.setSingleStep(0.5)
        self._flag_dia_spin.setDecimals(1)
        self._flag_dia_spin.setPrefix(tr("toolbar.flag_dia_prefix"))
        self._flag_dia_spin.setSuffix(tr("toolbar.mm_suffix"))
        _fit_spin_width(
            self._flag_dia_spin,
            tr("toolbar.flag_dia_prefix") + "50,0" + tr("toolbar.mm_suffix"), 84,
        )
        self._flag_dia_spin.setValue(self._scene.get_cable_diameter_mm())
        self._flag_dia_spin.setToolTip(tr("toolbar.flag_dia_tip"))
        self._flag_dia_spin.valueChanged.connect(self._on_flag_diameter_changed)
        row2.addWidget(self._flag_dia_spin)

        self._flag_mid_spin = QDoubleSpinBox()
        self._flag_mid_spin.setRange(0.0, 200.0)
        self._flag_mid_spin.setSingleStep(0.5)
        self._flag_mid_spin.setDecimals(1)
        self._flag_mid_spin.setPrefix(tr("toolbar.flag_mid_prefix"))
        self._flag_mid_spin.setSuffix(tr("toolbar.mm_suffix"))
        _fit_spin_width(
            self._flag_mid_spin,
            tr("toolbar.flag_mid_prefix") + "200,0" + tr("toolbar.mm_suffix"), 104,
        )
        self._flag_mid_spin.setValue(self._scene.get_flag_middle_mm())
        self._flag_mid_spin.setToolTip(tr("toolbar.flag_mid_tip"))
        self._flag_mid_spin.valueChanged.connect(self._on_flag_middle_changed)
        row2.addWidget(self._flag_mid_spin)

        self._btn_flag_copy = QPushButton(tr("toolbar.flag_copy"))
        self._btn_flag_copy.setCheckable(True)
        self._btn_flag_copy.setChecked(True)
        self._btn_flag_copy.setToolTip(tr("toolbar.flag_copy_tip"))
        self._btn_flag_copy.clicked.connect(self._on_flag_copy_toggled)
        row2.addWidget(self._btn_flag_copy)

        self._update_flag_controls_enabled()

        row2.addWidget(_vsep())

        # --- Aktuellen Zustand der Werkzeugleiste als Standard speichern ---
        btn_save_defaults = QPushButton(tr("toolbar.save_defaults"))
        btn_save_defaults.setToolTip(tr("toolbar.save_defaults_tip"))
        btn_save_defaults.clicked.connect(self._save_as_defaults)
        row2.addWidget(btn_save_defaults)
        row2.addStretch(1)

        # ── Rechte Spalte: große Drucken-Schaltfläche (über beide Reihen) ──
        self._btn_print = QPushButton()
        self._btn_print.setIcon(make_print_icon(40))
        self._btn_print.setIconSize(QSize(34, 34))
        self._btn_print.setFixedSize(58, 58)
        self._btn_print.setToolTip(tr("toolbar.print_tip"))
        self._btn_print.setShortcut(QKeySequence.StandardKey.Print)
        self._btn_print.clicked.connect(self._print)
        outer.addWidget(self._btn_print)

        tb.addWidget(bar)

    # ------------------------------------------------------------------
    # Werkzeugleisten-Slots
    # ------------------------------------------------------------------

    def _add_text_box(self) -> None:
        self._scene.add_text_box(font=self._current_font())

    def _load_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("msg.load_image_title"),
            "",
            tr("msg.image_filter"),
        )
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(
                self, tr("msg.load_image_title"),
                tr("msg.load_image_failed", path=path),
            )
            return
        self._scene.add_image_box(pixmap)

    def _on_tape_width_changed(self, text: str) -> None:
        width_mm = TAPE_WIDTHS.get(text, 12)
        self._scene.set_tape_width(width_mm)
        self._view._fit_label()

    def _on_font_family_changed(self, font: QFont) -> None:
        for item in self._target_text_boxes():
            f = item.get_font()
            f.setFamily(font.family())
            item.set_font(f)
        self._recenter_after_font_change()

    def _on_font_size_changed(self) -> None:
        pt = self._size_combo.currentData()
        if pt is None:
            return
        for item in self._target_text_boxes():
            f = item.get_font()
            f.setPointSize(pt)
            item.set_font(f)
        self._recenter_after_font_change()

    def _set_font_attr(self, attr: str, value: bool) -> None:
        for item in self._target_text_boxes():
            f = item.get_font()
            if attr == "bold":        f.setBold(value)
            elif attr == "italic":    f.setItalic(value)
            elif attr == "underline": f.setUnderline(value)
            elif attr == "strikeout": f.setStrikeOut(value)
            item.set_font(f)
        self._recenter_after_font_change()

    def _recenter_after_font_change(self) -> None:
        """Wenn sich die Schrift ändert, passt sich die Feldhöhe automatisch an,
        wodurch das Feld an seiner alten Oberkante hängen bleibt. Es vertikal im
        druckbaren Bereich neu zentrieren, damit das visuelle Layout ausgewogen
        bleibt."""
        from .label_canvas import PIXELS_PER_MM
        printable_h_px = self._scene.get_printable_height_mm() * PIXELS_PER_MM
        for item in self._target_text_boxes():
            item.setY((printable_h_px - item._rect.height()) / 2.0)

    def _on_super_clicked(self, checked: bool) -> None:
        if checked:
            self._btn_sub.setChecked(False)
        self._set_vert_align(1 if checked else 0)

    def _on_sub_clicked(self, checked: bool) -> None:
        if checked:
            self._btn_super.setChecked(False)
        self._set_vert_align(-1 if checked else 0)

    def _set_vert_align(self, align: int) -> None:
        for item in self._target_text_boxes():
            item.set_vertical_align(align)

    def _set_text_align(self, align: str) -> None:
        for item in self._target_text_boxes():
            item.set_h_align(align)

    def _toggle_format_paint(self, checked: bool) -> None:
        if checked:
            boxes = self._selected_text_boxes()
            if not boxes:
                self._btn_fmt_paint.setChecked(False)
                self.statusBar().showMessage(tr("msg.paint_select_first"), 5000)
                return
            self._view.start_paint_mode(boxes[0].get_format(), self._on_paint_done)
            self.statusBar().showMessage(tr("msg.paint_click_target"), 0)
        else:
            self._view.stop_paint_mode()

    def _on_paint_done(self) -> None:
        self._btn_fmt_paint.setChecked(False)
        self.statusBar().clearMessage()

    def _on_length_changed(self, mm: int) -> None:
        if not self._btn_auto_length.isChecked():
            self._scene.set_label_length_mm(mm)
            self._view._fit_label()

    def _on_auto_length_toggled(self, checked: bool) -> None:
        self._scene.set_auto_length(checked)
        self._length_spin.setEnabled(not checked)
        if checked:
            self._length_spin.blockSignals(True)
            self._length_spin.setValue(self._scene.get_label_length_mm())
            self._length_spin.blockSignals(False)

    # --- Kabelfähnchen-Modus ---

    def _on_flag_toggled(self, checked: bool) -> None:
        self._scene.set_flag_mode(checked)
        self._update_flag_controls_enabled()
        self._view._fit_label()

    def _on_flag_diameter_changed(self, mm: float) -> None:
        self._scene.set_cable_diameter_mm(mm)
        # Die Mittelbreite folgt dem Umfang — sie in das Mitte-Drehfeld
        # spiegeln, ohne dessen Handler erneut auszulösen.
        self._flag_mid_spin.blockSignals(True)
        self._flag_mid_spin.setValue(self._scene.get_flag_middle_mm())
        self._flag_mid_spin.blockSignals(False)
        if self._scene.get_flag_mode():
            self._view._fit_label()

    def _on_flag_middle_changed(self, mm: float) -> None:
        self._scene.set_flag_middle_mm(mm)
        if self._scene.get_flag_mode():
            self._view._fit_label()

    def _on_flag_copy_toggled(self, checked: bool) -> None:
        self._scene.set_flag_copy(checked)

    def _update_flag_controls_enabled(self) -> None:
        on = self._scene.get_flag_mode()
        self._flag_dia_spin.setEnabled(on)
        self._flag_mid_spin.setEnabled(on)
        self._btn_flag_copy.setEnabled(on)
        # Im Fähnchen-Modus wird die Länge abgeleitet (2·Fähnchen + Mitte),
        # daher gelten die Bedienelemente für manuelle Länge + Auto-Länge nicht.
        self._btn_auto_length.setEnabled(not on)
        self._length_spin.setEnabled(
            not on and not self._btn_auto_length.isChecked()
        )

    def _sync_flag_controls(self) -> None:
        """Spiegelt den Fähnchen-Zustand der Szene in die Werkzeugleiste (z. B. nach dem Laden)."""
        for w, val in (
            (self._btn_flag,      self._scene.get_flag_mode()),
            (self._btn_flag_copy, self._scene.get_flag_copy()),
            (self._flag_dia_spin, self._scene.get_cable_diameter_mm()),
            (self._flag_mid_spin, self._scene.get_flag_middle_mm()),
        ):
            w.blockSignals(True)
            if isinstance(val, bool):
                w.setChecked(val)
            else:
                w.setValue(val)
            w.blockSignals(False)
        self._update_flag_controls_enabled()

    def _on_label_length_scene_changed(self, mm: int) -> None:
        self._length_spin.blockSignals(True)
        self._length_spin.setValue(mm)
        self._length_spin.blockSignals(False)
        # Nur neu einpassen, wenn die Zeichenfläche jetzt über das sichtbare
        # Ansichtsfenster hinausragt; passt sie noch, den aktuellen Zoomgrad des
        # Nutzers beibehalten.
        scene_w   = self._scene.sceneRect().width()
        viewport_w = self._view.viewport().width()
        if scene_w * self._view.transform().m11() > viewport_w:
            self._view._fit_label()

    def _on_selection_changed(self) -> None:
        """Aktualisiert die Bedienelemente der Werkzeugleiste passend zum ersten ausgewählten Element."""
        boxes = self._selected_text_boxes()
        if not boxes:
            return
        font = boxes[0].get_font()
        va   = boxes[0].get_vertical_align()
        ha   = boxes[0].get_h_align()

        align_btns = tuple(self._align_buttons.values())
        for w in (self._font_combo, self._size_combo,
                  self._btn_bold, self._btn_italic, self._btn_underline, self._btn_strike,
                  self._btn_super, self._btn_sub, *align_btns):
            w.blockSignals(True)

        self._font_combo.setCurrentFont(font)
        target_pt = font.pointSize()
        best_idx  = 0
        best_dist = 10_000
        for i in range(self._size_combo.count()):
            d = abs(self._size_combo.itemData(i) - target_pt)
            if d < best_dist:
                best_dist = d
                best_idx  = i
        self._size_combo.setCurrentIndex(best_idx)

        self._btn_bold.setChecked(font.bold())
        self._btn_italic.setChecked(font.italic())
        self._btn_underline.setChecked(font.underline())
        self._btn_strike.setChecked(font.strikeOut())
        self._btn_super.setChecked(va == 1)
        self._btn_sub.setChecked(va == -1)
        for k, btn in self._align_buttons.items():
            btn.setChecked(k == ha)

        for w in (self._font_combo, self._size_combo,
                  self._btn_bold, self._btn_italic, self._btn_underline, self._btn_strike,
                  self._btn_super, self._btn_sub, *align_btns):
            w.blockSignals(False)

    def _save_as_defaults(self) -> None:
        s = QSettings()
        s.setValue("tape_width",    self._tape_combo.currentText())
        s.setValue("font_family",   self._font_combo.currentFont().family())
        s.setValue("font_size",     self._size_combo.currentData())
        s.setValue("font_bold",     self._btn_bold.isChecked())
        s.setValue("font_italic",   self._btn_italic.isChecked())
        s.setValue("font_underline",self._btn_underline.isChecked())
        s.setValue("font_strikeout",self._btn_strike.isChecked())
        QMessageBox.information(
            self, tr("msg.defaults_saved_title"),
            tr("msg.defaults_saved_body",
               tape=self._tape_combo.currentText(),
               font=self._font_combo.currentFont().family(),
               size=self._size_combo.currentData()),
        )

    def _print(self) -> None:
        print_label(self._scene, parent=self)

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _selected_text_boxes(self) -> list[TextBox]:
        return [
            item for item in self._scene.selectedItems()
            if isinstance(item, TextBox)
        ]

    def _target_text_boxes(self) -> list[TextBox]:
        """Felder, auf die Schrift-/Größen-/Stiländerungen der Werkzeugleiste wirken.

        Ist etwas ausgewählt → nur diese (feingranulare Kontrolle).
        Andernfalls → alle Textfelder in der Szene (damit Nutzer, die ein
        einzelnes Etikett bearbeiten, nicht daran denken müssen, erst per Klick
        auszuwählen).
        """
        selected = self._selected_text_boxes()
        if selected:
            return selected
        return [it for it in self._scene.items() if isinstance(it, TextBox)]

    def _center_vertical(self) -> None:
        """Zentriert ausgewählte Textfelder vertikal im druckbaren Bereich."""
        from .label_canvas import PIXELS_PER_MM
        printable_h_px = self._scene.get_printable_height_mm() * PIXELS_PER_MM
        for item in self._selected_text_boxes():
            item_h_px = item._rect.height()
            item.setY((printable_h_px - item_h_px) / 2)

    def _center_horizontal(self) -> None:
        """Zentriert ausgewählte Textfelder horizontal zwischen den Sicherheitsrändern."""
        from .label_canvas import PIXELS_PER_MM, MARGIN_MM
        left_px  = MARGIN_MM * PIXELS_PER_MM
        right_px = (self._scene.get_label_length_mm() - MARGIN_MM) * PIXELS_PER_MM
        for item in self._selected_text_boxes():
            item_w_px = item._rect.width()
            item.setX(left_px + (right_px - left_px - item_w_px) / 2)

    def _restore_settings(self) -> None:
        s = QSettings()
        tape = s.value("tape_width", "12mm")
        if tape in TAPE_WIDTHS:
            self._tape_combo.setCurrentText(tape)

        family = s.value("font_family", "Noto Serif")
        self._font_combo.setCurrentFont(QFont(family))

        size = s.value("font_size", 12, int)
        for i in range(self._size_combo.count()):
            if self._size_combo.itemData(i) == size:
                self._size_combo.setCurrentIndex(i)
                break

        self._btn_bold.setChecked(s.value("font_bold",      False, bool))
        self._btn_italic.setChecked(s.value("font_italic",   False, bool))
        self._btn_underline.setChecked(s.value("font_underline", False, bool))
        self._btn_strike.setChecked(s.value("font_strikeout",    False, bool))

    def _current_font(self) -> QFont:
        font = self._font_combo.currentFont()
        pt   = self._size_combo.currentData() or 12
        font.setPointSize(pt)
        font.setBold(self._btn_bold.isChecked())
        font.setItalic(self._btn_italic.isChecked())
        font.setUnderline(self._btn_underline.isChecked())
        font.setStrikeOut(self._btn_strike.isChecked())
        return font

    # ------------------------------------------------------------------
    # Menüleiste
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # --- Datei ---
        m_file = mb.addMenu(tr("menu.file"))

        act_new = QAction(tr("menu.file_new"), self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self._file_new)
        m_file.addAction(act_new)

        act_open = QAction(tr("menu.file_open"), self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._file_open)
        m_file.addAction(act_open)

        act_save = QAction(tr("menu.file_save"), self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._file_save)
        m_file.addAction(act_save)

        act_save_as = QAction(tr("menu.file_save_as"), self)
        act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        act_save_as.triggered.connect(self._file_save_as)
        m_file.addAction(act_save_as)

        m_file.addSeparator()

        act_undo = QAction(tr("menu.file_undo"), self)
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.triggered.connect(self._do_undo)
        m_file.addAction(act_undo)

        self._recent_menu = QMenu(tr("menu.file_recent"), self)
        self._recent_menu.aboutToShow.connect(self._populate_recent)
        m_file.addMenu(self._recent_menu)

        m_file.addSeparator()

        act_settings = QAction(tr("menu.file_settings"), self)
        act_settings.triggered.connect(self._open_settings)
        m_file.addAction(act_settings)

        m_file.addSeparator()

        act_quit = QAction(tr("menu.file_quit"), self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        # --- Bearbeiten ---
        m_edit = mb.addMenu(tr("menu.edit"))

        act_cut = QAction(tr("menu.edit_cut"), self)
        act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        act_cut.triggered.connect(self._edit_cut)
        m_edit.addAction(act_cut)

        act_copy = QAction(tr("menu.edit_copy"), self)
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        act_copy.triggered.connect(self._edit_copy)
        m_edit.addAction(act_copy)

        act_paste = QAction(tr("menu.edit_paste"), self)
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        act_paste.triggered.connect(self._edit_paste)
        m_edit.addAction(act_paste)

        act_delete = QAction(tr("menu.edit_delete"), self)
        act_delete.setShortcut(QKeySequence.StandardKey.Delete)
        act_delete.triggered.connect(self._edit_delete)
        m_edit.addAction(act_delete)

        m_edit.addSeparator()

        act_dup = QAction(tr("menu.edit_duplicate"), self)
        act_dup.setShortcut("Ctrl+D")
        act_dup.triggered.connect(self._edit_duplicate)
        m_edit.addAction(act_dup)

        act_all = QAction(tr("menu.edit_select_all"), self)
        act_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        act_all.triggered.connect(self._edit_select_all)
        m_edit.addAction(act_all)

        m_edit.addSeparator()

        act_dt = QAction(tr("menu.edit_datetime"), self)
        act_dt.setShortcut("F5")
        act_dt.triggered.connect(self._edit_insert_datetime)
        m_edit.addAction(act_dt)

        # --- Hilfe ---
        m_help = mb.addMenu(tr("menu.help"))

        act_help = QAction(tr("menu.help_contents"), self)
        act_help.setShortcut(QKeySequence.StandardKey.HelpContents)
        act_help.triggered.connect(self._help_contents)
        m_help.addAction(act_help)

        act_shortcuts = QAction(tr("menu.help_shortcuts"), self)
        act_shortcuts.triggered.connect(self._help_shortcuts)
        m_help.addAction(act_shortcuts)

        m_help.addSeparator()

        act_about = QAction(tr("menu.help_about"), self)
        act_about.triggered.connect(self._help_about)
        m_help.addAction(act_about)

    # ------------------------------------------------------------------
    # Aktionen des Datei-Menüs
    # ------------------------------------------------------------------

    def _file_new(self) -> None:
        if not self._maybe_save_changes():
            return
        self._suspend_dirty = True
        self._scene.clear_content()
        # Auf die Benutzervoreinstellungen zurücksetzen
        s = QSettings()
        tape = s.value("tape_width", "12mm")
        if tape in TAPE_WIDTHS:
            self._tape_combo.setCurrentText(tape)
        else:
            self._scene.set_tape_width(12)
        self._scene.set_flag_mode(False)
        self._sync_flag_controls()
        self._btn_auto_length.setChecked(True)
        self._scene.set_auto_length(True)
        self._scene.set_label_length_mm(DEFAULT_LABEL_LENGTH_MM)
        self._current_path = None
        self._dirty = False
        self._update_title()
        self._view._fit_label()
        self._undo.reset()
        QTimer.singleShot(200, self._enable_dirty_tracking)

    def _file_open(self) -> None:
        if not self._maybe_save_changes():
            return
        start_dir = os.path.dirname(self._current_path) if self._current_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("msg.open_title"), start_dir,
            tr("msg.file_filter"),
        )
        if not path:
            return
        self._load_path(path)

    def _file_save(self) -> bool:
        if self._current_path is None:
            return self._file_save_as()
        try:
            save_to_file(self._scene, self._current_path)
        except Exception as exc:
            QMessageBox.critical(
                self, tr("msg.save_failed_title"),
                tr("msg.save_failed_body", error=exc),
            )
            return False
        self._dirty = False
        self._update_title()
        self._add_recent(self._current_path)
        self.statusBar().showMessage(
            tr("msg.saved_status", name=os.path.basename(self._current_path)), 3000,
        )
        return True

    def _file_save_as(self) -> bool:
        start = self._current_path or ""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("msg.save_as_title"), start,
            tr("msg.save_filter"),
        )
        if not path:
            return False
        if not path.lower().endswith(".ptle"):
            path += ".ptle"
        self._current_path = path
        return self._file_save()

    def _load_path(self, path: str) -> None:
        self._suspend_dirty = True
        try:
            load_from_file(self._scene, path)
        except Exception as exc:
            self._suspend_dirty = False
            QMessageBox.critical(
                self, tr("msg.open_failed_title"),
                tr("msg.open_failed_body", error=exc),
            )
            return
        self._current_path = path
        self._dirty = False
        self._update_title()
        self._add_recent(path)

        # Das Band-Kombinationsfeld mit dem geladenen Wert abgleichen
        tape_mm = self._scene.get_tape_width_mm()
        for label, mm in TAPE_WIDTHS.items():
            if mm == tape_mm:
                self._tape_combo.blockSignals(True)
                self._tape_combo.setCurrentText(label)
                self._tape_combo.blockSignals(False)
                break

        self._btn_auto_length.setChecked(self._scene._auto_length)
        self._length_spin.setEnabled(not self._scene._auto_length)
        self._sync_flag_controls()
        self._view._fit_label()
        self._undo.reset()
        QTimer.singleShot(200, self._enable_dirty_tracking)
        self.statusBar().showMessage(
            tr("msg.opened_status", name=os.path.basename(path)), 3000,
        )

    # ------------------------------------------------------------------
    # Zuletzt geöffnete Dateien
    # ------------------------------------------------------------------

    def _recent_paths(self) -> list[str]:
        raw = QSettings().value("recent_files", [])
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw]
        return [str(p) for p in raw]

    def _set_recent_paths(self, paths: list[str]) -> None:
        QSettings().setValue("recent_files", paths)

    def _add_recent(self, path: str) -> None:
        paths = self._recent_paths()
        path = os.path.abspath(path)
        if path in paths:
            paths.remove(path)
        paths.insert(0, path)
        self._set_recent_paths(paths[:_RECENT_MAX])

    def _populate_recent(self) -> None:
        self._recent_menu.clear()
        paths = self._recent_paths()
        if not paths:
            act = self._recent_menu.addAction(tr("menu.recent_empty"))
            act.setEnabled(False)
            return
        for p in paths:
            name = os.path.basename(p) or p
            act = self._recent_menu.addAction(name)
            act.setToolTip(p)
            if not os.path.exists(p):
                act.setEnabled(False)
            act.triggered.connect(lambda _checked=False, path=p: self._open_recent(path))
        self._recent_menu.addSeparator()
        act_clear = self._recent_menu.addAction(tr("menu.recent_clear"))
        act_clear.triggered.connect(lambda: self._set_recent_paths([]))

    def _open_recent(self, path: str) -> None:
        if not self._maybe_save_changes():
            return
        if not os.path.exists(path):
            QMessageBox.warning(
                self, tr("msg.file_missing_title"),
                tr("msg.file_missing_body", path=path),
            )
            return
        self._load_path(path)

    # ------------------------------------------------------------------
    # Aktionen des Bearbeiten-Menüs
    # ------------------------------------------------------------------

    def _edit_cut(self) -> None:
        if self._scene.copy_selection():
            for item in list(self._scene.selectedItems()):
                if isinstance(item, (TextBox, ImageBox)):
                    self._scene.removeItem(item)

    def _edit_copy(self) -> None:
        self._scene.copy_selection()

    def _edit_paste(self) -> None:
        # Unsere eigenen kopierten Elemente bevorzugen (Textfelder / Bilder mit
        # vollständigen Metadaten); nur auf ein rohes Bitmap aus einer anderen
        # App zurückfallen.
        if not self._scene.paste_clipboard():
            self._scene.paste_image_from_clipboard()

    def _edit_delete(self) -> None:
        for item in list(self._scene.selectedItems()):
            if isinstance(item, (TextBox, ImageBox)):
                self._scene.removeItem(item)

    def _edit_duplicate(self) -> None:
        self._scene.duplicate_selection()

    def _edit_select_all(self) -> None:
        self._scene.select_all_content()

    def _edit_insert_datetime(self) -> None:
        text = datetime.now().strftime(str(tr("format.datetime")))
        self._scene.add_text_box(font=self._current_font(), initial_text=text)

    # ------------------------------------------------------------------
    # Aktionen des Hilfe-Menüs
    # ------------------------------------------------------------------

    def _help_contents(self) -> None:
        HelpDialog(self).exec()

    def _help_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

    def _help_about(self) -> None:
        AboutDialog(self).exec()

    # ------------------------------------------------------------------
    # Einstellungsdialog
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _is_dark_theme(self) -> bool:
        # Der gespeicherte Schalter ist die maßgebliche Absicht; auf die
        # Live-Palette zurückfallen, damit auch ein systemseitig dunkler Desktop
        # berücksichtigt wird.
        if QSettings().value(DARK_MODE_KEY, False, bool):
            return True
        return self.palette().color(QPalette.ColorRole.Window).lightness() < 128

    def _style_add_group(self, dark: bool | None = None) -> None:
        """Gestaltet die »Hinzufügen«-Gruppenbox. Ein Stylesheet auf der Box
        zwingt ihre untergeordneten Schaltflächen durch Qts Stylesheet-Renderer,
        der die Palette ignoriert. Beide Designs müssen daher die
        Schaltflächenfarben ausdrücklich benennen — lässt man sie undefiniert,
        fällt Qt beim Zurückwechseln von Dunkel auf Hell auf ein schwarzes
        Panel zurück (es poliert nicht sauber nach)."""
        if dark is None:
            dark = self._is_dark_theme()
        if dark:
            bg, border, hover, pressed = "#353535", "#5A5A5A", "#444444", "#2C2C2C"
        else:
            bg, border, hover, pressed = "#F2F2F2", "#ADADAD", "#FAFAFA", "#E0E0E0"
        css = (
            "QGroupBox {"
            "  font-size: 10px;"
            "  margin-top: 10px;"
            "  padding: 8px 6px 6px 6px;"   # oben, rechts, unten, links
            "  border: 1px solid #888888;"
            "  border-radius: 4px;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  subcontrol-position: top left;"
            "  left: 8px;"
            "  padding: 0 4px;"
            "}"
            "QGroupBox QPushButton {"
            f"  background-color: {bg};"
            f"  border: 1px solid {border};"
            "  border-radius: 4px;"
            "}"
            f"QGroupBox QPushButton:hover  {{ background-color: {hover}; }}"
            f"QGroupBox QPushButton:pressed {{ background-color: {pressed}; }}"
        )
        self._add_group.setStyleSheet(css)

    def _style_status_length(self, dark: bool | None = None) -> None:
        """Die dauerhafte Längenbeschriftung trägt ein Stylesheet, das ihren
        Text auf Schwarz setzt, sofern keine Farbe angegeben ist — sie je nach
        Design ausdrücklich benennen."""
        if dark is None:
            dark = self._is_dark_theme()
        color = "#B0B0B0" if dark else "#000000"
        self._status_length.setStyleSheet(
            f"QLabel {{ font-weight: bold; padding-left: 14px; color: {color}; }}"
        )

    def refresh_theme(self, dark: bool | None = None) -> None:
        """Zeichnet design-abhängige, selbstgezeichnete Elemente nach einem
        Hell-/Dunkel-Wechsel neu. Qt palettiert Standard-Widgets live neu, aber
        unsere von Hand gezeichneten Werkzeugleisten-Icons, per Stylesheet
        gestalteten Widgets und das Zeichenflächen-Umfeld brauchen eine
        ausdrückliche Auffrischung.

        *dark* wird vom Einstellungsdialog übergeben, damit wir nicht die gerade
        geänderte Palette auslesen müssen (die sich asynchron aktualisiert);
        wird es weggelassen, ermitteln wir es selbst."""
        if dark is None:
            dark = self._is_dark_theme()
        self._btn_add_text.setIcon(make_add_text_icon(40, dark))
        self._btn_add_image.setIcon(make_add_image_icon(40, dark))
        self._btn_print.setIcon(make_print_icon(40, dark))
        for kind, btn in self._align_buttons.items():
            btn.setIcon(make_align_icon(kind, 28, dark))
        self._style_add_group(dark)
        self._style_status_length(dark)
        self._scene.apply_theme_background(dark)

    # ------------------------------------------------------------------
    # Rückgängig
    # ------------------------------------------------------------------

    def _do_undo(self) -> None:
        if not self._undo.undo():
            self.statusBar().showMessage(tr("msg.nothing_to_undo"), 2000)
            return
        # Das Band-Kombinationsfeld der Werkzeugleiste mit der ggf. wiederhergestellten Breite abgleichen
        tape_mm = self._scene.get_tape_width_mm()
        for label, mm in TAPE_WIDTHS.items():
            if mm == tape_mm:
                self._tape_combo.blockSignals(True)
                self._tape_combo.setCurrentText(label)
                self._tape_combo.blockSignals(False)
                break

    # ------------------------------------------------------------------
    # Änderungsverfolgung + Fenstertitel
    # ------------------------------------------------------------------

    def _enable_dirty_tracking(self) -> None:
        self._suspend_dirty = False

    def _on_scene_changed_dirty(self, _regions=None) -> None:
        if self._suspend_dirty:
            return
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _update_status_length(self, _mm: int | None = None) -> None:
        """Frischt die dauerhafte Anzeige »Länge: X,X cm« in der Statusleiste auf."""
        cm = self._scene.get_label_length_mm() / 10.0
        self._status_length.setText(tr("status.length", cm=fmt_number(cm, 1)))

    def _update_title(self) -> None:
        base = "TuxLabel"
        if self._current_path:
            name = os.path.basename(self._current_path)
            title = f"{name} — {base}"
        else:
            title = base
        if self._dirty:
            title = "● " + title
        self.setWindowTitle(title)

    def _maybe_save_changes(self) -> bool:
        """Gibt True zurück, wenn das aktuelle Dokument verworfen werden darf.

        Fragt den Nutzer, wenn das Dokument ungespeicherte Änderungen hat UND
        mindestens ein Text- oder Bildelement enthält. Leere, ungespeicherte
        Dokumente werden stillschweigend verworfen."""
        if not self._dirty or not self._scene.has_content():
            return True

        ret = QMessageBox.question(
            self, tr("msg.unsaved_title"),
            tr("msg.unsaved_body"),
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if ret == QMessageBox.StandardButton.Save:
            return self._file_save()
        if ret == QMessageBox.StandardButton.Discard:
            return True
        return False  # Abbrechen

    def closeEvent(self, event) -> None:
        if self._maybe_save_changes():
            super().closeEvent(event)
        else:
            event.ignore()
