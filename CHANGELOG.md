# Changelog

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
* **Installation:** `install_shortcut.py` legt Anwendungsmenü-Eintrag und
  Desktop-Verknüpfung an.

