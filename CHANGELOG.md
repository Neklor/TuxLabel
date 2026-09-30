# Changelog

Jede Version steht hier zuerst auf Deutsch, direkt darunter auf Englisch.
*Each version is listed in German first, followed by English.*

## [1.2.0] — 2026-09-30

### Neu

* **Schatten je Textfeld**, ein Knopf in der Werkzeugleiste. Die Schrift
  bekommt einen grauen Schatten, der auch auf dem Band grau erscheint —
  die Buchstaben selbst bleiben scharf. Je größer die Schrift, desto
  deutlicher wirkt der Effekt.

  Der Schatten lässt sich mit allen Schriftrichtungen kombinieren und wird
  in der `.ptle`-Datei gespeichert. Ältere Dateien laden unverändert ohne
  Schatten.

### Geändert

* **Format übertragen** überträgt jetzt auch Schriftrichtung und Schatten.
  Bisher blieben sie beim Zielfeld unverändert stehen.

### New *(English)*

* **Per-text-box shadow**, one button in the toolbar. The text gets a grey
  shadow that also comes out grey on the tape, while the letters themselves
  stay crisp. The larger the font, the clearer the effect.

  The shadow combines with every writing direction and is stored in the
  `.ptle` file. Older files load unchanged, without a shadow.

### Changed *(English)*

* **Format painter** now carries the writing direction and the shadow as
  well. Previously both were left untouched on the target box.

## [1.1.0] — 2026-09-14

### Neu

* **Schriftrichtung je Textfeld.** Für Bänder, die hochkant aufgeklebt werden
  — Kabel, Ordnerrücken, Schalterleisten — gibt es jetzt drei neue
  Einstellungen in der Werkzeugleiste:
  * **Waagerecht** — unverändert
  * **Vertikal** — die Zeichen stehen einzeln aufrecht untereinander.
    Die Kette wächst entlang der Bandlänge, die Textlänge ist also unbegrenzt.
  * **Gekippt** — der ganze Textblock kippt um 90°. Die Zeile läuft quer
    über das Band und muss daher kürzer als dessen druckbare Höhe sein;
    sinnvoll für kurze Texte auf breitem Band.

  Die Einstellung wird in der `.ptle`-Datei gespeichert. Ältere Dateien
  laden unverändert als waagerechter Text.

### New *(English)*

* **Per-text-box writing direction.** For tapes applied vertically — cables,
  folder spines, switch panels — there are now three new settings in the
  toolbar:
  * **Horizontal** — unchanged
  * **Vertical** — the characters sit one below the other, each upright.
    The chain grows along the tape, so the text length is unlimited.
  * **Tilted** — the whole text block is tilted by 90°. The line then runs
    across the tape and must be shorter than its printable height; useful
    for short text on wide tape.

  The setting is stored in the `.ptle` file. Older files load unchanged as
  horizontal text.

## [1.0.1] — 2026-09-06

### Behoben

* **Bandbreite 18 mm war nicht auswählbar.** Die Breite war intern bereits
  vollständig hinterlegt — druckbare Höhe (13,0 mm) und PPD-Name (`tz-18`)
  waren vorhanden —, fehlte aber in der Auswahlliste der Werkzeugleiste.
  TZe-Bänder mit 18 mm ließen sich dadurch nicht bedrucken.

### Fixed *(English)*

* **The 18 mm tape width could not be selected.** Everything else was already
  in place — the printable height (13.0 mm) and the PPD name (`tz-18`) — but
  the width was missing from the toolbar's list, so 18 mm TZe tapes could not
  be printed.

## [1.0.0] — 2026-07-29

Erste öffentliche Veröffentlichung.

### Enthalten

* **Editor:** Textfelder mit freier Schriftart, -größe und -stil, vier
  Ausrichtungen, Inline-Bearbeitung per Doppelklick; Bilder aus Datei oder
  Zwischenablage; Verschieben per Maus und Pfeiltasten (1 mm bzw. 0,1 mm mit
  `Strg`), Größenänderung über Anfasser; Format übertragen; vertikales und
  horizontales Zentrieren; Rückgängig bis zu 50 Schritte; Einfügen von Datum
  und Uhrzeit.
* **Band und Etikett:** Bandbreiten 3,5 / 6 / 9 / 12 / 24 mm mit Brothers
  druckbaren Höhen, Lineal in Zentimetern, Zoom über `Strg`+Mausrad, feste
  oder automatisch mitwachsende Etikettenlänge.
* **Kabelfähnchen-Modus:** Aufteilung in linkes Fähnchen, Mittelbalken und
  rechtes Fähnchen; Breite des Mittelbalkens aus dem Kabelumfang
  (π × Durchmesser) berechnet, manuell übersteuerbar; optionales Spiegeln der
  linken auf die rechte Hälfte und druckbare Falzlinie.
* **Drucken:** Rendern mit 180 dpi und Übergabe an CUPS über `lp`, Linien- und
  Dithering-Modus, Abgleich der eingestellten mit der am Drucker
  voreingestellten Bandbreite.
* **Dateien:** Format `.ptle` (JSON, Koordinaten in Millimetern, Dateiversion
  1), Verlauf der zuletzt geöffneten Dateien, Warnung bei ungespeicherten
  Änderungen.
* **Oberfläche:** helles und dunkles Design, zur Laufzeit gezeichnete Symbole
  (keine Bilddateien nötig), speicherbare Voreinstellungen mit Rücksetzen auf
  Werkszustand, Hilfe- und Tastenkürzel-Dialog.
* **Sprachen:** Deutsch fest eingebaut; Englisch, Spanisch und Französisch als
  JSON-Dateien; eigene Übersetzungen aus `lang/` oder
  `~/.config/TuxLabel/lang/`; Vorschlag der Systemsprache beim ersten Start.
* **Installation:** `.deb`-Paket für Ubuntu, Linux Mint und Debian;
  `install_shortcut.py` legt bei der Installation aus dem Quellcode
  Anwendungsmenü-Eintrag und Desktop-Verknüpfung an.

### Included *(English)*

* **Editor:** Text boxes with any font, size and style, four alignments,
  inline editing by double-click; images from file or clipboard; moving with
  the mouse and arrow keys (1 mm, or 0.1 mm with `Ctrl`), resizing via
  handles; format painter; vertical and horizontal centring; undo up to 50
  steps; inserting date and time.
* **Tape and label:** Tape widths 3.5 / 6 / 9 / 12 / 24 mm using Brother's
  printable heights, ruler in centimetres, zoom with `Ctrl`+mouse wheel,
  fixed or automatically growing label length.
* **Cable-flag mode:** Splits the tape into a left flag, a centre bar and a
  right flag; the centre bar width is derived from the cable circumference
  (π × diameter) and can be overridden manually; optional mirroring of the
  left half onto the right, plus a printable fold line.
* **Printing:** Rendering at 180 dpi and handover to CUPS via `lp`, line and
  dithering modes, and a check of the configured tape width against the one
  preset on the printer.
* **Files:** `.ptle` format (JSON, coordinates in millimetres, file version
  1), recent-files list, warning about unsaved changes.
* **Interface:** Light and dark theme, icons drawn at runtime (no image files
  required), storable defaults with a reset to factory settings, help and
  keyboard-shortcut dialogs.
* **Languages:** German built in; English, Spanish and French as JSON files;
  custom translations loaded from `lang/` or `~/.config/TuxLabel/lang/`;
  system-language suggestion on first start.
* **Installation:** `.deb` package for Ubuntu, Linux Mint and Debian;
  `install_shortcut.py` adds an application-menu entry and a desktop shortcut
  when installing from source.
