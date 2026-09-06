# SPDX-FileCopyrightText: 2026 Christoph Krogmann
# SPDX-License-Identifier: GPL-3.0-or-later
"""TuxLabel – Etiketten-Editor für Brother P-Touch Drucker (TZe-Bänder).

``__version__`` ist die einzige Stelle, an der die Programmversion steht.
Alle anderen Stellen (Über-Dialog, ``QApplication.applicationVersion``)
lesen sie hier aus, damit ein Release nur eine Änderung braucht.
Das Dateiformat hat eine eigene, unabhängige Version — siehe
``serialization.FILE_VERSION``.
"""

__version__ = "1.0.1"
