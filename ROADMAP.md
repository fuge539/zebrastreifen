# Roadmap / Notizen

Stand: 2026-08-29, Branch `feature/nullpunkt`

## Aufräumen (bekannte Leichen / Konflikte)

- **Rechtsklick-Lücke NP-Zone vs. linker Rand**: In der NP-Zone (linke 40%)
  bricht ein Rechtsklick ohne Diamant-Treffer einfach ab (`return`,
  app.py ~L1545) statt auf "linken Rand setzen" durchzufallen. Da der
  linke Rand aber meist genau dort sitzt (kurz nach Schlüssel/Vorzeichen),
  ist er in der Praxis über Rechtsklick kaum erreichbar.
  → Lösung geplant: löst sich durch den Y-Modus/X-Modus-Umbau (siehe unten)
  von selbst, da es dann keine räumliche Zonen-Grenze mehr braucht.

- **NP-Punkt-X ist tot**: `_np_points` speichert (x_pdf, y_pdf, orig_top),
  aber X wird nirgends im Export verwendet (Crop nutzt ausschliesslich
  `left_margin_per_page`, rechte Kante = volle Originalseite, unabhängig
  vom Export-Preset). X dient aktuell nur der Diamant-Anzeige (Hit-Testing)
  und der Einzug-Erkennung beim Auto-Füllen (`_np_calibration`).

## In Arbeit: Nullpunkt → Nullzeile

Erkenntnis: Das Feature ist konzeptionell eine **Nullzeile** (Y-Referenz,
die sich wiederholt), kein echter (X,Y)-Nullpunkt. Passt auch zum
App-Namen "zebrastreifen" (Streifen = volle Breite, kein Punkt).

Plan:
1. `feature/nullpunkt` zuerst nach GitHub pushen (Sicherung des jetzigen
   Diamant/X+Y-Stands).
2. Neuen Branch abzweigen (Vorschlag: `feature/nullzeile`).
3. Datenmodell vereinfachen: `_np_points` ohne X, nur Y/orig_top.
   Einzug-Erkennung entfällt ersatzlos (X war der einzige Nutzen).
4. Symbol ersetzen: Diamant (◆, Punkt-Charakter) → kurzer horizontaler
   Strich mit kleinem Marker, konsistent mit dem bestehenden
   Hover-Indikator (gestrichelte Linie beim Hovern, app.py ~L801-810).

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
