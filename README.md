# 🦓 zebrastreifen

Streifen aus Noten extrahieren: einzelne Notenzeilen als zugeschnittene
Streifen sauber neu zusammensetzen, z.B. für Tablet oder kompakten
Ausdruck.

## Installation

### Windows

**Aus Quellcode (empfohlen, keine vorgefertigte .exe im Repo):**

```
pip install pymupdf pillow
python app.py
```

**Eigene .exe bauen** (optional, für Weitergabe ohne Python-Installation):

```
pip install pyinstaller pymupdf pillow
pyinstaller zebrastreifen.spec
```

Die fertige `zebrastreifen.exe` liegt danach in `dist/`.

### macOS

Python 3 von [python.org](https://www.python.org/) installieren (bringt
Tkinter mit), dann:

```
pip3 install pymupdf pillow
python3 app.py
```

Eine fertige .exe funktioniert **nicht** auf macOS — der Quellcode selbst
ist aber plattformunabhängig und läuft direkt mit obigem Befehl.

## Kurzanleitung

Die Seite ist in zwei Bereiche geteilt:

- **Linke Seite — Anker**: Klick auf eine Notenzeile setzt automatisch
  einen Streifen (Ober- + Unterkante).
- **Rechte Seite — Schnitte**: Streifen manuell setzen/verschieben,
  Ctrl+Klick verbindet zwei Streifen nahtlos.

Ganz oben lässt sich per Klick auf die Labels in den **X-Modus**
umschalten, um links/rechts den Seitenrand für die ganze Seite zu
definieren (z.B. bei ungleich gescannten Kopien).

Für alle Details (Tastenkürzel, Klick-Interaktionen, Export-Formate)
das **"?"** oben rechts im Programm öffnen — dort steht die vollständige
Kurzhilfe.

## Lizenz

MIT, siehe [LICENSE](LICENSE).

© 2026 zebrastreifen / Peter Freitag
