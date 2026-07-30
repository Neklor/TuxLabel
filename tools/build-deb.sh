#!/bin/bash
# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Baut ein installierbares .deb-Paket von TuxLabel.
#
#   ./tools/build-deb.sh
#
# Ergebnis: dist/tuxlabel_<version>_all.deb
#
# Die Versionsnummer wird aus tuxlabel/__init__.py gelesen — es gibt also
# keine zweite Stelle, die beim Release nachgezogen werden muss.
#
# Voraussetzungen: dpkg-deb (Paket »dpkg«), python3 mit PyQt6 (nur zum
# Rendern der Icons). Beides ist auf Debian/Ubuntu/Mint vorhanden.

set -euo pipefail

# --- Paket-Metadaten -------------------------------------------------------
# ACHTUNG: Der Maintainer-Eintrag ist in jedem gebauten Paket sichtbar
# (dpkg -I tuxlabel.deb). Hier auf eine Adresse ändern, die öffentlich
# stehen darf.
MAINTAINER="Christoph Krogmann <ch.krogmann@outlook.de>"
HOMEPAGE="https://github.com/Neklor/TuxLabel"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

VERSION="$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' tuxlabel/__init__.py)"
if [ -z "$VERSION" ]; then
    echo "FEHLER: __version__ nicht aus tuxlabel/__init__.py lesbar." >&2
    exit 1
fi

PKG="tuxlabel"
DEB="dist/${PKG}_${VERSION}_all.deb"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "TuxLabel $VERSION — .deb bauen"
echo "======================================"

# --- Programmdateien -------------------------------------------------------
# Nach /usr/lib/<paket>/, weil es ein Programm ist und keine importierbare
# Bibliothek: nichts davon gehört in den Python-Suchpfad des Systems.
# i18n.py löst den Sprachordner relativ zu tuxlabel/ auf, deshalb müssen
# main.py, tuxlabel/ und lang/ ihre bisherige Anordnung behalten.
APPDIR="$STAGE/usr/lib/$PKG"
install -d "$APPDIR"
install -m 644 main.py "$APPDIR/main.py"
cp -r tuxlabel "$APPDIR/"
cp -r lang     "$APPDIR/"
# Übersetzungs-Anleitung und Caches gehören nicht ins Paket
find "$APPDIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$APPDIR" -name '*.pyc' -delete
echo "  Programmdateien -> /usr/lib/$PKG"

# --- Starter ---------------------------------------------------------------
# install_shortcut.py kommt NICHT mit: Menüeintrag und Icons liefert das
# Paket selbst, das Skript ist nur für die Installation aus dem Quellcode.
install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<EOF
#!/bin/sh
# Starter für TuxLabel (aus dem Debian-Paket)
exec python3 /usr/lib/$PKG/main.py "\$@"
EOF
chmod 755 "$STAGE/usr/bin/$PKG"
echo "  Starter         -> /usr/bin/$PKG"

# --- Menüeintrag -----------------------------------------------------------
# StartupWMClass muss der WM_CLASS des Fensters entsprechen (Qt setzt sie aus
# QApplication.applicationName()), sonst ordnet die Fensterleiste das laufende
# Fenster nicht dem Menüeintrag zu. Siehe auch install_shortcut.py.
install -d "$STAGE/usr/share/applications"
cat > "$STAGE/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=TuxLabel
GenericName=Etiketten-Editor
GenericName[en]=Label Editor
Comment=Etiketten für Brother P-Touch Drucker gestalten und drucken
Comment[en]=Design and print labels for Brother P-Touch printers
Exec=$PKG
Icon=$PKG
Terminal=false
Categories=Office;Printing;
Keywords=label;etikett;brother;p-touch;ptouch;tze;drucken;print;
StartupWMClass=TuxLabel
EOF
echo "  Menüeintrag     -> /usr/share/applications/$PKG.desktop"

# --- Icons -----------------------------------------------------------------
# Zur Bauzeit aus tuxlabel/icons.py gerendert — im Repository liegen bewusst
# keine Bilddateien. QImage braucht dafür weder Display noch QGuiApplication.
python3 - "$STAGE" "$PKG" <<'PYEOF'
import sys, pathlib
stage, pkg = pathlib.Path(sys.argv[1]), sys.argv[2]
from tuxlabel.icons import APP_ICON_SIZES, app_icon_image
for size in APP_ICON_SIZES:
    d = stage / f"usr/share/icons/hicolor/{size}x{size}/apps"
    d.mkdir(parents=True, exist_ok=True)
    if not app_icon_image(size).save(str(d / f"{pkg}.png")):
        sys.exit(f"FEHLER: Icon {size}px konnte nicht geschrieben werden.")
print(f"  Icons           -> hicolor, {len(APP_ICON_SIZES)} Größen "
      f"({', '.join(str(s) for s in APP_ICON_SIZES)})")
PYEOF

# --- AppStream-Metadaten ---------------------------------------------------
# Ohne diese Datei zeigt die Anwendungsverwaltung (Mint, GNOME Software,
# KDE Discover) nur Name und Icon aus der .desktop-Datei und meldet »keine
# Bildschirmfotos verfügbar«.
#
# Wichtig: Bildschirmfotos werden NICHT ins Paket gelegt, sondern per URL
# eingebunden — die Anwendungsverwaltung lädt sie beim Anzeigen nach. Die
# URL muss also öffentlich erreichbar sein; sie zeigt auf docs/screenshot.png
# im GitHub-Repository.
APPID="io.github.neklor.TuxLabel"

# Veröffentlichungsdatum aus dem CHANGELOG zur passenden Version ziehen, damit
# es keine zweite zu pflegende Stelle gibt. Notfalls das heutige Datum.
REL_DATE="$(sed -n "s/^## \[$VERSION\].*[—-] *\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\).*/\1/p" CHANGELOG.md | head -1)"
REL_DATE="${REL_DATE:-$(date +%F)}"

install -d "$STAGE/usr/share/metainfo"
cat > "$STAGE/usr/share/metainfo/$APPID.metainfo.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>$APPID</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>

  <name>TuxLabel</name>
  <summary>Design and print labels for Brother P-Touch printers</summary>
  <summary xml:lang="de">Etiketten für Brother P-Touch Drucker gestalten und drucken</summary>

  <developer id="io.github.neklor">
    <name>Christoph Krogmann</name>
  </developer>

  <description>
    <p>
      TuxLabel designs labels for Brother P-Touch label printers (TZe tapes)
      and prints them through CUPS. The preview is true to scale, so the
      printed size matches what you see on screen.
    </p>
    <p>
      Text boxes use any installed font; images can be loaded from a file or
      pasted from the clipboard. Tape widths from 3.5 to 24 mm are supported,
      and the label length can grow automatically with the content.
    </p>
    <p>
      A dedicated cable-flag mode splits the tape into a left flag, a centre
      bar and a right flag, sizing the centre bar from the cable
      circumference so the text never ends up wrapped around the cable.
    </p>
    <p xml:lang="de">
      TuxLabel gestaltet Etiketten für Brother P-Touch Etikettendrucker
      (TZe-Bänder) und druckt sie über CUPS aus. Die Vorschau ist
      maßstabsgetreu, die gedruckte Größe entspricht also der angezeigten.
    </p>
    <p xml:lang="de">
      Textfelder nutzen jede installierte Schriftart; Bilder lassen sich aus
      einer Datei laden oder aus der Zwischenablage einfügen. Unterstützt
      werden Bandbreiten von 3,5 bis 24 mm, und die Etikettenlänge kann
      automatisch mit dem Inhalt wachsen.
    </p>
    <p xml:lang="de">
      Ein eigener Kabelfähnchen-Modus teilt das Band in linkes Fähnchen,
      Mittelbalken und rechtes Fähnchen; die Breite des Mittelbalkens ergibt
      sich aus dem Kabelumfang, damit die Beschriftung nicht auf dem
      umschlungenen Kabel liegt.
    </p>
  </description>

  <launchable type="desktop-id">$PKG.desktop</launchable>

  <screenshots>
    <screenshot type="default">
      <image>https://raw.githubusercontent.com/Neklor/TuxLabel/main/docs/screenshot.png</image>
      <caption>Main window with a 12 mm label</caption>
      <caption xml:lang="de">Hauptfenster mit einem 12-mm-Etikett</caption>
    </screenshot>
  </screenshots>

  <url type="homepage">$HOMEPAGE</url>
  <url type="bugtracker">$HOMEPAGE/issues</url>
  <url type="donation">https://paypal.me/CKrogmann</url>
  <url type="translate">$HOMEPAGE/blob/main/lang/README.md</url>

  <categories>
    <category>Office</category>
  </categories>

  <keywords>
    <keyword>label</keyword>
    <keyword>brother</keyword>
    <keyword>p-touch</keyword>
    <keyword>tze</keyword>
    <keyword xml:lang="de">Etikett</keyword>
    <keyword xml:lang="de">Beschriftung</keyword>
  </keywords>

  <content_rating type="oars-1.1"/>

  <releases>
    <release version="$VERSION" date="$REL_DATE"/>
  </releases>
</component>
EOF
echo "  AppStream       -> /usr/share/metainfo/$APPID.metainfo.xml (Release $REL_DATE)"

# --- Dokumentation und Lizenz ---------------------------------------------
DOCDIR="$STAGE/usr/share/doc/$PKG"
install -d "$DOCDIR"
install -m 644 README.md "$DOCDIR/"
[ -f CHANGELOG.md ] && install -m 644 CHANGELOG.md "$DOCDIR/"
install -m 644 lang/README.md "$DOCDIR/README.translations.md"

# Debian erwartet eine copyright-Datei; der GPL-Volltext wird nicht kopiert,
# sondern auf /usr/share/common-licenses/GPL-3 verwiesen (Debian Policy 12.5).
cat > "$DOCDIR/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: TuxLabel
Source: $HOMEPAGE

Files: *
Copyright: 2026 Christoph Krogmann
License: GPL-3+

License: GPL-3+
 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 .
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 .
 On Debian systems, the complete text of the GNU General Public
 License version 3 can be found in "/usr/share/common-licenses/GPL-3".
EOF
echo "  Doku + Lizenz   -> /usr/share/doc/$PKG"

# --- Steuerdateien ---------------------------------------------------------
install -d "$STAGE/DEBIAN"

# Installierte Größe in KiB — apt zeigt sie vor der Installation an.
INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"

# python3 (>= 3.10): der Code nutzt »X | None«-Annotationen ohne
# from __future__ import annotations (install_shortcut.py, tuxlabel/icons.py).
# cups-client nur als Recommends: es liefert »lp«, das printer.py zum Drucken
# aufruft — Etiketten entwerfen und speichern geht auch ohne.
#
# qt6-translations-l10n liefert die Beschriftungen der Qt-Standardknöpfe
# (»Speichern«, »Abbrechen«, …), siehe i18n.install_qt_translations(). Es käme
# ohnehin über libqt6core6t64 mit, aber nur als dessen Empfehlung — hier
# ausdrücklich genannt, damit sichtbar ist, dass TuxLabel es wirklich braucht.
# Fehlt es, bleiben diese Knöpfe englisch; das Programm läuft trotzdem.
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyqt6
Recommends: cups-client, qt6-translations-l10n
Installed-Size: $INSTALLED_SIZE
Maintainer: $MAINTAINER
Homepage: $HOMEPAGE
Description: Etiketten-Editor für Brother P-Touch Drucker
 TuxLabel gestaltet Etiketten für Brother P-Touch Etikettendrucker
 (TZe-Bänder) und druckt sie über CUPS aus. Die Vorschau ist
 maßstabsgetreu, sodass die gedruckte Größe der angezeigten entspricht.
 .
 Funktionen: Textfelder mit freier Schriftwahl, Bilder aus Datei oder
 Zwischenablage, Bandbreiten von 3,5 bis 24 mm, automatisch mitwachsende
 Etikettenlänge sowie ein eigener Modus für Kabelfähnchen, dessen
 Mittelbalken sich aus dem Kabelumfang berechnet.
 .
 Die Oberfläche ist auf Deutsch, Englisch, Spanisch und Französisch
 verfügbar; weitere Sprachen lassen sich ohne Programmierkenntnisse als
 JSON-Datei ergänzen.
EOF

# Vorkompilieren, damit der Start nicht jedes Mal übersetzen muss —
# /usr/lib ist für den Nutzer nicht schreibbar, Python könnte den Cache
# sonst nirgends ablegen.
cat > "$STAGE/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e
if [ "\$1" = "configure" ]; then
    python3 -m compileall -q /usr/lib/$PKG >/dev/null 2>&1 || true
fi
exit 0
EOF

# Die beim Vorkompilieren entstandenen Dateien kennt dpkg nicht; ohne dieses
# Aufräumen bleiben nach dem Entfernen leere Ordner unter /usr/lib zurück.
cat > "$STAGE/DEBIAN/prerm" <<EOF
#!/bin/sh
set -e
find /usr/lib/$PKG -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
exit 0
EOF

# --- Rechte normalisieren --------------------------------------------------
# Muss NACH allen Kopier- und Schreibschritten laufen. »cp -r« erbt die Rechte
# des Quellbaums, und der liegt hier auf 775/777 — gruppenschreibbare und
# ausführbare Datendateien in /usr sind ein Sicherheitsmangel, den lintian
# zu Recht meldet. Das Wurzelverzeichnis erbt zudem die 700 von mktemp.
chmod 755 "$STAGE"
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f -exec chmod 644 {} +
# Die Ausnahmen: alles, was wirklich ausgeführt wird.
chmod 755 "$STAGE/usr/bin/$PKG" "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"
echo "  Rechte          -> Ordner 755, Dateien 644, Starter/Skripte 755"

# --- Bauen -----------------------------------------------------------------
mkdir -p dist
# --root-owner-group: alle Dateien gehören root:root, ohne dass fakeroot
# nötig ist (dpkg >= 1.19).
dpkg-deb --root-owner-group --build "$STAGE" "$DEB" > /dev/null

echo "======================================"
echo "Fertig: $DEB  ($(du -h "$DEB" | cut -f1))"
echo
echo "Installieren:    sudo apt install ./$DEB"
echo "Entfernen:       sudo apt remove $PKG"
echo "Inhalt prüfen:   dpkg -c $DEB"
