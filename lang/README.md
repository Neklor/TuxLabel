# TuxLabel-Sprachdateien / TuxLabel language files

*(English version below)*

## Eigene Übersetzung erstellen

1. `en.json` kopieren und nach dem Sprachcode benennen, z. B. `fr.json`
   (der Dateiname ist nur ein Vorschlag — maßgeblich ist der `code` im
   `_meta`-Block).
2. Den `_meta`-Block anpassen:

   ```json
   "_meta": {
     "name": "Français",     ← Anzeigename im Einstellungsdialog
     "code": "fr",           ← eindeutiger Sprachcode
     "author": "Ihr Name",
     "version": 1
   }
   ```

3. Alle Werte (rechts vom Doppelpunkt) übersetzen — die Schlüssel (links)
   unverändert lassen.
4. Die Datei in diesen Ordner legen **oder** nach
   `~/.config/TuxLabel/lang/` (praktisch, wenn der Programmordner nicht
   beschreibbar ist).
5. TuxLabel starten → *Datei → Einstellungen → Sprache* → Sprache wählen
   → Neustart.

## Regeln

* **Fehlende Schlüssel sind erlaubt:** Für jeden nicht übersetzten
  Schlüssel wird der eingebaute deutsche Text angezeigt. Eine
  unvollständige Datei funktioniert also immer.
* **Platzhalter erhalten:** Texte wie `{name}`, `{path}`, `{cm}` werden
  zur Laufzeit ersetzt und müssen in der Übersetzung unverändert
  vorkommen (die Position im Satz darf sich ändern).
* **Mehrzeilige Texte:** Entweder `\n` in einer Zeichenkette verwenden
  oder den Wert als Liste von Zeichenketten schreiben — die Einträge
  werden mit Zeilenumbrüchen verbunden:

  ```json
  "toolbar.auto_tip": ["Zeile 1", "Zeile 2"]
  ```

* **`&` in Menüeinträgen** markiert den Buchstaben für die
  Tastatur-Navigation (Alt+Buchstabe), z. B. `"&File"` → Alt+F.
* **`format.decimal`** ist das Dezimaltrennzeichen der Sprache
  (`","` bzw. `"."`), **`format.datetime`** das Datumsformat für
  *Bearbeiten → Datum und Uhrzeit einfügen*
  (Python-`strftime`-Platzhalter).
* **`shortcuts.sections`** ist eine verschachtelte Liste:
  `[Abschnittstitel, [[Tastenkürzel, Beschreibung], …]]`.
  Auch die Kürzel selbst sind übersetzbar (»Strg« ↔ »Ctrl«).
* **Kurz halten:** Schaltflächen wachsen zwar automatisch mit dem Text,
  aber sehr lange Beschriftungen machen die Werkzeugleiste breit.
  Ausführliche Erklärungen gehören in die `…_tip`-Schlüssel (Tooltips).
* Deutsch ist fest ins Programm eingebaut; eine `de.json` wird ignoriert.

---

## Creating your own translation (English)

1. Copy `en.json` and name it after your language code, e.g. `fr.json`
   (the file name is only a convention — the `code` in the `_meta` block
   is what counts).
2. Edit the `_meta` block: `name` is shown in the settings dialog,
   `code` must be unique.
3. Translate all values (right of the colon); keep the keys unchanged.
4. Put the file in this folder **or** in `~/.config/TuxLabel/lang/`.
5. Start TuxLabel → *File → Settings → Language* → pick your language
   → restart.

Rules: missing keys fall back to the built-in German text, so partial
translations always work. Placeholders like `{name}` must be kept.
Multi-line texts can be written as a list of strings (joined with line
breaks). `&` in menu entries marks the Alt shortcut letter. Keep button
labels short — long explanations belong in the `…_tip` (tooltip) keys.
German is built into the program; a `de.json` file is ignored.
