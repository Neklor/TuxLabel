# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dezente Prüfung, ob auf GitHub eine neuere Version vorliegt.

Entwurfsgrundsätze — die Prüfung soll nicht auffallen, solange es nichts zu
melden gibt:

* **Einwilligung.** Ohne diese Funktion baut TuxLabel überhaupt keine
  Netzwerkverbindung auf. Deshalb wird beim ersten Start einmal gefragt
  (``maybe_ask_consent``) und die Antwort gespeichert; ohne ausdrückliches Ja
  passiert nichts. Abschaltbar bleibt es jederzeit in den Einstellungen.
* **Asynchron.** ``QNetworkAccessManager`` arbeitet im Hintergrund. Ein
  langsames oder stummes Netz darf den Programmstart nicht verzögern — ein
  synchrones ``urllib`` im Hauptthread würde das Fenster blockieren, bis der
  Timeout greift.
* **Leise.** Jeder Fehler — offline, DNS tot, GitHub nicht erreichbar,
  unerwartete Antwort — führt dazu, dass nichts angezeigt wird. Nie ein
  Dialog, nie eine Fehlermeldung.
* **Nicht nervig.** Höchstens einmal am Tag, und eine Version lässt sich
  überspringen. Der Hinweis erscheint als anklickbarer Text in der
  Statusleiste, nicht als Popup.

Die manuelle Prüfung über *Hilfe → Nach Updates suchen* umgeht Tageslimit und
übersprungene Version und meldet auch, wenn alles aktuell ist — dort hat der
Nutzer ja selbst gefragt.

Aktualisieren kann dieses Modul nichts: Es verlinkt die Release-Seite. Das
``.deb`` kommt nicht aus einer Paketquelle, also bleibt das Einspielen
Handarbeit.
"""

from __future__ import annotations

import json
from datetime import date

from PyQt6.QtCore import QObject, QSettings, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import __version__
from .i18n import tr

# --- Einstellungsschlüssel -------------------------------------------------
UPDATE_CHECK_KEY  = "update_check_enabled"    # bool  — Funktion aktiv?
UPDATE_ASKED_KEY  = "update_check_asked"      # bool  — Einwilligung erfragt?
UPDATE_LAST_KEY   = "update_check_last"       # str   — Datum der letzten Prüfung (ISO)
UPDATE_SKIP_KEY   = "update_check_skip"       # str   — übersprungene Version

UPDATE_CHECK_DEFAULT = False   # ohne ausdrückliche Einwilligung aus

# --- GitHub ----------------------------------------------------------------
_REPO = "Neklor/TuxLabel"
_API_URL = f"https://api.github.com/repos/{_REPO}/releases/latest"

#: Seite, die der Hinweis verlinkt — zeigt stets das neueste Release.
RELEASES_URL = f"https://github.com/{_REPO}/releases/latest"

# Unangemeldet erlaubt die GitHub-API 60 Anfragen je Stunde und IP. Bei
# höchstens einer Prüfung pro Tag ist das weit entfernt; ein Zugriffstoken
# gehört ausdrücklich NICHT in ein Programm, das an Nutzer ausgeliefert wird.
_TIMEOUT_MS = 8000


def _parse_version(text: str) -> tuple[int, ...] | None:
    """Zerlegt »v1.4.0« oder »1.4.0« in ``(1, 4, 0)``.

    Gibt None zurück, wenn der Text keine reine Zahlenversion ist — damit
    fallen Vorabversionen wie »1.5.0-rc1« heraus, auf die nicht hingewiesen
    werden soll.
    """
    t = text.strip()
    if t.startswith(("v", "V")):
        t = t[1:]
    if not t:
        return None
    parts = t.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def is_newer(latest: str, current: str = __version__) -> bool:
    """True, wenn *latest* eine höhere Version als *current* ist.

    Verglichen wird zahlenweise, nicht als Text: »1.10.0« ist größer als
    »1.9.0«, zeichenweise wäre es kleiner.
    """
    a, b = _parse_version(latest), _parse_version(current)
    if a is None or b is None:
        return False
    # Auf gleiche Länge bringen, damit 1.4 und 1.4.0 als gleich gelten.
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def is_enabled() -> bool:
    """Ob die automatische Prüfung eingeschaltet ist."""
    return bool(QSettings().value(UPDATE_CHECK_KEY, UPDATE_CHECK_DEFAULT, bool))


def _checked_today() -> bool:
    return str(QSettings().value(UPDATE_LAST_KEY, "")) == date.today().isoformat()


def _mark_checked() -> None:
    QSettings().setValue(UPDATE_LAST_KEY, date.today().isoformat())


def skip_version(version: str) -> None:
    """Merkt sich eine Version, zu der kein Hinweis mehr erscheinen soll."""
    QSettings().setValue(UPDATE_SKIP_KEY, version)


def _is_skipped(version: str) -> bool:
    return str(QSettings().value(UPDATE_SKIP_KEY, "")) == version


def maybe_ask_consent(parent=None) -> None:
    """Fragt genau einmal, ob beim Start nach Updates gesucht werden darf.

    Muss vor dem Hauptfenster laufen. Wird die Frage abgelehnt oder der Dialog
    geschlossen, bleibt die Funktion aus; die Frage kommt nicht erneut, der
    Schalter steht aber in den Einstellungen.
    """
    s = QSettings()
    if s.value(UPDATE_ASKED_KEY, False, bool):
        return

    # Verzögert importieren: dieses Modul soll ohne QtWidgets benutzbar sein
    # (die Versionslogik oben ist reine Rechnerei und wird so testbar).
    from PyQt6.QtWidgets import QMessageBox

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(str(tr("update.consent_title")))
    box.setText(str(tr("update.consent_body")))
    yes = box.addButton(str(tr("update.consent_yes")), QMessageBox.ButtonRole.AcceptRole)
    no  = box.addButton(str(tr("update.consent_no")),  QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no)
    box.exec()

    s.setValue(UPDATE_ASKED_KEY, True)
    s.setValue(UPDATE_CHECK_KEY, box.clickedButton() is yes)


class UpdateChecker(QObject):
    """Fragt die neueste Release-Version bei GitHub ab.

    Sendet ``updateAvailable(version)``, sobald eine höhere Version vorliegt,
    und ``upToDate()`` nur bei der manuellen Prüfung. Im Fehlerfall wird nichts
    gesendet — außer bei der manuellen Prüfung, die über ``checkFailed()``
    Rückmeldung gibt, weil der Nutzer dort auf eine Antwort wartet.
    """

    updateAvailable = pyqtSignal(str)   # neue Version, z. B. »1.5.0«
    upToDate        = pyqtSignal()
    checkFailed     = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._manual = False

    def check(self, manual: bool = False) -> None:
        """Startet eine Abfrage.

        *manual* = True für *Hilfe → Nach Updates suchen*: umgeht Einwilligung,
        Tageslimit und übersprungene Version und meldet jedes Ergebnis.
        """
        if self._reply is not None:          # läuft schon
            return
        if not manual:
            if not is_enabled() or _checked_today():
                return
            _mark_checked()

        self._manual = manual
        req = QNetworkRequest(QUrl(_API_URL))
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        req.setRawHeader(b"User-Agent", f"TuxLabel/{__version__}".encode())
        req.setTransferTimeout(_TIMEOUT_MS)
        self._reply = self._nam.get(req)
        self._reply.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._fail()
                return
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                tag = str(data["tag_name"])
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                self._fail()
                return
        finally:
            reply.deleteLater()

        if _parse_version(tag) is None:      # Vorabversion o. Ä. — ignorieren
            self._fail()
            return

        latest = tag.lstrip("vV")
        if not is_newer(latest):
            if self._manual:
                self.upToDate.emit()
            return
        if not self._manual and _is_skipped(latest):
            return
        self.updateAvailable.emit(latest)

    def _fail(self) -> None:
        """Nur die manuelle Prüfung darf einen Fehlschlag zeigen."""
        if self._manual:
            self.checkFailed.emit()
