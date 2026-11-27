# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""Barcode-Kodierung: Code 128 und EAN-13.

Dieses Modul rechnet nur — es kennt weder Qt noch Millimeter. Heraus kommt
eine Folge von Modulen (0 = hell, 1 = dunkel), die ``barcode_item`` als
Balken zeichnet. So lässt sich die Kodierung ohne Oberfläche prüfen, und das
ist nötig: Ein Tippfehler in den Tabellen fällt sonst erst auf, wenn ein
Scanner das gedruckte Etikett nicht liest.

Deshalb prüft ``_selbsttest`` beim Import die Tabellen gegen die Regeln der
Norm (Modulsummen, Paritäten). Das kostet beim Start nichts Messbares und
fängt genau die Fehler ab, die man im Code nicht sieht.

Eine Bibliothek wäre eine Abhängigkeit mehr: Weder Ubuntu noch Mint führen
python3-barcode in ihren Quellen, das `.deb` käme also ohne pip nicht mehr
aus. Für zwei Symbologien lohnt das nicht.
"""

from __future__ import annotations

# --- Code 128 ---------------------------------------------------------------
# Je Zeichen sechs Breiten: Strich, Lücke, Strich, Lücke, Strich, Lücke.
# Die Summe ist bei jedem Zeichen 11 Module — darauf prüft der Selbsttest.
_C128_WIDTHS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232", "233111",
]
#: Stoppzeichen — als einziges 13 Module breit (sieben Breiten statt sechs).
_C128_STOP = "2331112"

_C128_START_B = 104      # Zeichensatz B: Ziffern, Groß- und Kleinbuchstaben
_C128_START_C = 105      # Zeichensatz C: Ziffernpaare, halb so breit
_C128_CODE_B  = 100      # Umschalten nach B
_C128_CODE_C  = 99       # Umschalten nach C

# --- EAN-13 -----------------------------------------------------------------
_EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
          "0110001", "0101111", "0111011", "0110111", "0001011"]
_EAN_R = ["".join("1" if c == "0" else "0" for c in m) for m in _EAN_L]
_EAN_G = ["".join(reversed(m)) for m in _EAN_R]

#: Welche der sechs linken Ziffern in L- bzw. G-Kodierung stehen, bestimmt
#: die erste Ziffer. Sie selbst wird nicht als Balken gedruckt.
_EAN_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
               "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]

_EAN_GUARD  = "101"
_EAN_MIDDLE = "01010"

#: Kennungen, wie sie in der ``.ptle`` stehen.
CODE128 = "code128"
EAN13   = "ean13"
SYMBOLOGIES = (CODE128, EAN13)


class BarcodeError(ValueError):
    """Die Eingabe passt nicht zur gewählten Barcode-Art.

    Trägt einen Übersetzungsschlüssel statt eines fertigen Satzes: Die
    Meldung landet im Dialog und muss daher in allen Sprachen erscheinen,
    dieses Modul kennt die Übersetzung aber nicht."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


# ---------------------------------------------------------------------------
# Code 128
# ---------------------------------------------------------------------------
def _c128_values(text: str) -> list[int]:
    """Zerlegt *text* in Code-128-Werte und wechselt dabei den Zeichensatz.

    Ziffernpaare laufen in Satz C (zwei Ziffern je Zeichen, also halb so
    breit), alles andere in Satz B. Gewechselt wird nur, wenn sich das lohnt:
    mindestens vier Ziffern am Stück, am Anfang und Ende auch zwei — darunter
    kostet das Umschaltzeichen mehr, als das Paaren einspart."""
    for ch in text:
        if not (32 <= ord(ch) <= 126):
            raise BarcodeError("barcode.err_char", char=ch)

    def ziffern_ab(i: int) -> int:
        n = 0
        while i + n < len(text) and text[i + n].isdigit():
            n += 1
        return n

    werte: list[int] = []
    satz: str | None = None
    i = 0
    while i < len(text):
        n = ziffern_ab(i)
        # Gerade Anzahl nehmen; ein ungerader Rest geht in Satz B.
        paare = n // 2 * 2
        lohnt = paare >= 4 or (paare >= 2 and (i == 0 or i + n == len(text)))
        if lohnt:
            if satz != "C":
                werte.append(_C128_START_C if satz is None else _C128_CODE_C)
                satz = "C"
            for k in range(i, i + paare, 2):
                werte.append(int(text[k:k + 2]))
            i += paare
        else:
            if satz != "B":
                werte.append(_C128_START_B if satz is None else _C128_CODE_B)
                satz = "B"
            werte.append(ord(text[i]) - 32)
            i += 1
    if not werte:
        raise BarcodeError("barcode.err_empty")
    return werte


def _code128_modules(text: str) -> str:
    werte = _c128_values(text)
    # Prüfzeichen: Startwert plus gewichtete Summe, modulo 103.
    pruef = werte[0]
    for pos, v in enumerate(werte[1:], start=1):
        pruef += pos * v
    werte.append(pruef % 103)

    module = []
    for v in werte:
        breiten = _C128_WIDTHS[v]
        dunkel = True
        for b in breiten:
            module.append(("1" if dunkel else "0") * int(b))
            dunkel = not dunkel
    dunkel = True
    for b in _C128_STOP:
        module.append(("1" if dunkel else "0") * int(b))
        dunkel = not dunkel
    return "".join(module)


# ---------------------------------------------------------------------------
# EAN-13
# ---------------------------------------------------------------------------
def ean13_check_digit(zwoelf: str) -> str:
    """Prüfziffer zu zwölf Ziffern. Gewichte 1 und 3 im Wechsel."""
    if len(zwoelf) != 12 or not zwoelf.isdigit():
        raise BarcodeError("barcode.err_ean_len")
    summe = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(zwoelf))
    return str((10 - summe % 10) % 10)


def _ean13_modules(text: str) -> str:
    if not text.isdigit():
        raise BarcodeError("barcode.err_ean_digits")
    if len(text) == 12:
        text += ean13_check_digit(text)
    if len(text) != 13:
        raise BarcodeError("barcode.err_ean_len")
    if text[12] != ean13_check_digit(text[:12]):
        raise BarcodeError("barcode.err_ean_check",
                           digit=ean13_check_digit(text[:12]))

    parity = _EAN_PARITY[int(text[0])]
    teile = [_EAN_GUARD]
    for ziffer, p in zip(text[1:7], parity):
        teile.append(_EAN_L[int(ziffer)] if p == "L" else _EAN_G[int(ziffer)])
    teile.append(_EAN_MIDDLE)
    for ziffer in text[7:]:
        teile.append(_EAN_R[int(ziffer)])
    teile.append(_EAN_GUARD)
    return "".join(teile)


# ---------------------------------------------------------------------------
# Öffentlich
# ---------------------------------------------------------------------------
def normalize(text: str, symbology: str) -> str:
    """Die Zeichenfolge, die tatsächlich kodiert wird.

    Bei EAN-13 wird eine fehlende Prüfziffer ergänzt, damit unter dem Code
    das steht, was auch darin steckt."""
    text = (text or "").strip()
    if symbology == EAN13:
        if len(text) == 12 and text.isdigit():
            return text + ean13_check_digit(text)
        return text
    return text


def encode(text: str, symbology: str) -> str:
    """Modulfolge als Zeichenkette aus '0' und '1'; '1' ist ein dunkles Modul.

    Wirft ``BarcodeError``, wenn die Eingabe nicht passt."""
    text = (text or "").strip()
    if not text:
        raise BarcodeError("barcode.err_empty")
    if symbology == EAN13:
        return _ean13_modules(text)
    if symbology == CODE128:
        return _code128_modules(text)
    raise BarcodeError("barcode.err_kind")


def quiet_zone(symbology: str) -> int:
    """Nötige helle Randzone links und rechts, in Modulen.

    Ohne sie findet der Scanner den Anfang nicht. Die Norm verlangt für
    Code 128 zehn Module, für EAN-13 elf links und sieben rechts; hier wird
    der größere Wert für beide Seiten genommen."""
    return 11 if symbology == EAN13 else 10


def check_input(text: str, symbology: str):
    """None, wenn *text* kodierbar ist, sonst (Schlüssel, Parameter)."""
    try:
        encode(text, symbology)
        return None
    except BarcodeError as e:
        return e.key, e.params


# ---------------------------------------------------------------------------
# Selbsttest der Tabellen
# ---------------------------------------------------------------------------
def _selbsttest() -> None:
    """Prüft die Tabellen gegen die Regeln der Norm.

    Ein vertippter Eintrag erzeugt sonst einen Barcode, der auf dem Bildschirm
    völlig normal aussieht und am Scanner durchfällt."""
    if len(_C128_WIDTHS) != 107:
        raise AssertionError(f"Code 128: {len(_C128_WIDTHS)} statt 107 Zeichen")
    for i, w in enumerate(_C128_WIDTHS):
        if len(w) != 6:
            raise AssertionError(f"Code 128, Zeichen {i}: {len(w)} statt 6 Breiten")
        if sum(int(c) for c in w) != 11:
            raise AssertionError(f"Code 128, Zeichen {i} ({w}): "
                                 f"Summe {sum(int(c) for c in w)} statt 11")
    if sum(int(c) for c in _C128_STOP) != 13:
        raise AssertionError("Code 128: Stoppzeichen nicht 13 Module breit")

    for name, tab, parity_gerade in (("L", _EAN_L, False),
                                     ("G", _EAN_G, True),
                                     ("R", _EAN_R, True)):
        for d, m in enumerate(tab):
            if len(m) != 7:
                raise AssertionError(f"EAN {name}[{d}]: {len(m)} statt 7 Module")
            if (m.count("1") % 2 == 0) != parity_gerade:
                raise AssertionError(f"EAN {name}[{d}] ({m}): falsche Parität")
    if len(_EAN_PARITY) != 10 or any(len(p) != 6 for p in _EAN_PARITY):
        raise AssertionError("EAN: Paritätstabelle fehlerhaft")


_selbsttest()
