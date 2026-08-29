# Roadmap / Notizen

Stand: 2026-08-29, Branch `feature/nullzeile`

## Aufräumen (bekannte Leichen / Konflikte)

- **Linker Rand ist vorerst deaktiviert** (`LEFT_MARGIN_ENABLED = False` in
  app.py): weder per Rechtsklick-Fallback noch per Linksklick in der
  linken Streifen-Zone setzbar, auch keine Snap-Vorschau mehr. Grund:
  gehört konzeptionell zum geplanten X-Modus (siehe unten), nicht zum
  aktuellen Y/Nullzeile-Fokus — bis dahin lieber ganz weg als
  halb-funktionierend/verwirrend. Bestehende Randwerte lassen sich
  weiterhin per Rechtsklick auf die Randlinie löschen. Reaktivieren:
  Konstante zurück auf `True`.

- **Vollständige Audit-Tabelle aller Maus-Interaktionen** steht in
  `INTERAKTION.md` (Prioritätsketten pro Handler, inkl. gefundener
  Inkonsistenzen zwischen Links-/Rechtsklick in der NP-Zone). Wird noch
  gemeinsam Punkt für Punkt durchgegangen.

- ~~Offene Frage: Soll eine gesetzte Nullzeile überhaupt verschiebbar
  sein?~~ **Entschieden & umgesetzt:** "Snap to grid" — jede Nullzeile,
  die einzeln per Klick gesetzt oder direkt per Drag angefasst wird,
  gilt danach als bestätigt/fixiert (`_np_manual`) und wird nie mehr
  automatisch von einer anderen Nullzeile mitgezogen. Direktes Drag
  bleibt für jede Nullzeile jederzeit möglich (das war die anfängliche
  Verwirrung zwischen "gar nicht mehr verschiebbar" vs. "nicht mehr
  *automatisch* verschiebbar" — Letzteres war gemeint).
  Nur per "⟳ NP füllen"/"Alle Seiten" automatisch erzeugte, noch nie
  angefasste Nullzeilen bleiben "auto" und kaskadieren weiter, bis sie
  einzeln bestätigt werden. Umgesetzt in `_add_nullpunkt` (sofort
  fixiert bei Klick-Platzierung) und `_drag_np` (fixiert bei erstem
  Direkt-Drag).

- **Kalibrierung setzt einen Workflow voraus** (`_np_calibration`,
  app.py): `dy` (Zeilenabstand für "⟳ NP füllen") ist der simple
  Mittelwert über ALLE bisher auf der Seite gesetzten Abstände. Ein
  einzelner untypischer Abstand (z.B. Titel-Streifen → erstes System)
  zählt genauso schwer wie ein regulärer System-Abstand und verzerrt die
  Vorhersage für die ganze restliche Seite. Beobachtung aus der Praxis:
  je nachdem in welcher Reihenfolge/Konsistenz man Nullzeilen setzt,
  werden die Vorhersagen spürbar besser oder schlechter.
  **Leitprinzip:** kein bestimmter Workflow (z.B. "erst alle Nullzeilen
  sauber hintereinander, dann füllen") soll vorausgesetzt werden, soweit
  irgend möglich — die App soll robust bleiben, egal in welcher
  Reihenfolge/Konsistenz gesetzt wird.
  → Mögliche Ansätze: Median statt Mittelwert (Ausreißer fallen kaum
  ins Gewicht), oder nur die letzten 2-3 Abstände statt der ganzen Seite
  berücksichtigen (passt sich an graduelle Änderungen an, ignoriert
  einzelne Ausreißer wie den Titel-Abstand).

## Erledigt: Nullpunkt → Nullzeile

Erkenntnis: Das Feature ist konzeptionell eine **Nullzeile** (Y-Referenz,
die sich wiederholt), kein echter (X,Y)-Nullpunkt. Passt auch zum
App-Namen "zebrastreifen" (Streifen = volle Breite, kein Punkt). Grund:
die X-Koordinate der Nullpunkte floss nirgends in den Export ein.

Umgesetzt auf `feature/nullzeile` (abgezweigt von `feature/nullpunkt`,
welcher zur Sicherung vorher nach GitHub gepusht wurde):
- Datenmodell vereinfacht: `_np_points` ohne X, nur (y_pdf, orig_top).
  Einzug-Erkennung ersatzlos entfernt (war der einzige Nutzen von X).
- Platzierung auf 1 Klick vereinfacht (kein Drag zum X-Setzen mehr).
- Symbol ersetzt: Diamant (◆) → horizontale Linie + Kreis, konsistent
  zum Hover-Indikator (`_draw_snap_indicator`).
- Hit-Testing/Drag nur noch Y-basiert (+ NP-Zonen-Zugehörigkeit).

## Später: Y-Modus / X-Modus (Tablet-Kante)

Idee (statt räumlicher NP-Zone): globaler Umschalter zwischen zwei
Ansichten, gleiche Klick-/Drag-/Snap-Logik, nur auf verschiedene Achse
angewendet:
- **Y-Modus** (Standard): Streifen setzen — das, was gerade zur
  Nullzeile wird.
- **X-Modus**: linke/rechte Kante für Tablet-Ansicht präzise setzen
  (die eigentliche Motivation hinter der ursprünglichen NP-X-Idee).

Vorteil: keine Erkennung mehr nötig, "wo genau wurde geklickt" — jeder
Klick bedeutet im aktiven Modus immer dasselbe. Löst auch das
Rechtsklick-Problem oben.

Nicht blockierend für den Nullzeile-Umbau — eigenständiges späteres
Feature.

## Später: weitere Ideen

- **Überlappende Streifen sind bereits heute technisch möglich** (die
  Unterkante eines Streifens lässt sich schon jetzt beliebig weit über
  die nächste Oberkante hinausziehen, keine Sperre im Code). Idee: tiefe
  Töne (z.B. Klavierbass) bleiben so noch im oberen System zählbar,
  Akkord/Folgesystem beginnt trotzdem sauber darunter. Ob's optisch
  überzeugt, noch nicht an echtem Notenbild getestet.

- ~~Shift-Hover-Lock für Linien-Drag im normalen Bereich~~ **Umgesetzt &
  getestet.** Shift halten → Ziel wird nicht über Pixel-Nähe bestimmt,
  sondern über die **Hälfte** des Zwischenraums: die zwei Linien, die
  den Cursor direkt einschliessen (nächste oberhalb + nächste
  unterhalb, unabhängig davon zu welchem Streifen sie gehören —
  funktioniert so auch bei überlappenden Streifen), plus deren
  Mittelpunkt als Umschaltschwelle. Bleibt gesperrt, auch wenn man sich
  beim Ziehen über die Schwelle hinaus bewegt. Cursor zeigt Richtung
  zur gesperrten Linie (↑ Oberkante-Ziel, ↓ Unterkante-Ziel) statt dem
  generischen ↕. Funktioniert auch bei einer noch dangelnden Oberkante
  ohne Unterkante. Implementiert in `_find_shift_lock_target`,
  `on_mouse_move`, `on_mouse_down`.

- ~~"Doppelkante" per Ctrl+Klick im normalen Bereich~~ **Umgesetzt &
  getestet.** Ctrl+Klick auf leere Fläche → normales Verhalten
  (Oberkante wie gehabt). Ctrl+Klick, während eine Oberkante auf eine
  Unterkante wartet → setzt an der Klickposition gleichzeitig die
  Unterkante des aktuellen Streifens *und* die Oberkante des nächsten,
  exakt auf derselben Höhe (nahtlos aneinander, keine Lücke;
  implementiert als zwei Cuts mit identischem Y — kein neues
  Datenmodell nötig). Eigene Farbe (orange `#e67e22`) statt rot/grün,
  zwei Labels ("unten N" grün oberhalb, "oben N+1" rot unterhalb).
  Shift-Lock trennt sie gezielt (obere Hälfte → Unterkante-Rolle,
  untere Hälfte → Oberkante-Rolle) — dafür musste
  `_find_shift_lock_target` um einen Koinzidenz-Sonderfall ergänzt
  werden (zwei Cuts exakt an derselben Stelle wurden vorher immer auf
  denselben Index aufgelöst, unabhängig von der Cursor-Seite).
  Spätere, noch vagere Erweiterung: "Prognose" — analog zur
  Nullzeilen-Füllfunktion weitere Doppelkanten automatisch
  extrapolieren, basierend auf dem Abstand der ersten gesetzten. Eigener
  Schritt, nicht Teil des Kern-Features.

- **"Radiergummi" für den Export** — noch vage: vermutlich ein Werkzeug,
  um im Export-Ausschnitt gezielt Bereiche (z.B. ungewollt mit
  reingerutschte Notenreste des Nachbarsystems bei überlappenden
  Streifen) manuell zu übermalen/entfernen. Muss noch genauer
  spezifiziert werden.
