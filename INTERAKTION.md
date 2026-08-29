# Maus-Interaktion: Ist-Zustand (Entscheidungstabelle)

Stand: 2026-08-29. Zweck: **erst verstehen, was der Code aktuell tut**,
bevor wir weiter etwas ändern. Extrahiert direkt aus `app.py` (kein
Soll-Zustand, reine Bestandsaufnahme der Prioritäts-Reihenfolge in jedem
Handler).

Alle Prüfungen sind **Prioritätsketten**: die erste zutreffende Bedingung
gewinnt, alle folgenden werden nicht mehr geprüft.

## Linksklick (`on_mouse_down`)

Reihenfolge:

1. Ist x_canvas in NP-Zone (linke 50%) UND nah (≤6px) an einer
   Nullzeilen-Marker-Y? → Drag-Modus für diese Nullzeile starten.
2. Sonst: ist y_canvas nah (≤6px) an **irgendeiner** bestehenden
   Schnittlinie (unabhängig von X, auch innerhalb NP-Zone!)? → Drag-Modus
   für diese Linie starten (erkennt zusätzlich, ob es eine
   Nullzeilen-Ober-/Untergrenze ist, für spätere Propagation).
3. Sonst: ist x_canvas in NP-Zone? →
   - Ist y_canvas innerhalb eines bestehenden Streifens (X-unabhängig)?
     → abbrechen, Meldung "nur ausserhalb setzen".
   - Sonst: neue Nullzeile sofort setzen.
4. Sonst (normaler Bereich, kein Treffer oben): Zone im Streifen bestimmen
   (`_strip_zone`, X-abhängig via `left_margin_per_page`):
   - `left` → linken Rand setzen.
   - `bottom` (= innerhalb Streifen) → Unterkante verschieben.
   - `None` (grauer Bereich) → neuen Schnitt anhängen.

## Drag (`on_drag`, während Maustaste gehalten)

1. War Schritt 1 oben aktiv (Nullzeilen-Marker)? → `_drag_np`: Y erneut
   snappen (jetzt fix bei `NP_SCAN_X=0`), Nullzeile + Folge-Nullzeilen
   (falls nicht manuell) vertikal mitziehen, Untergrenze des
   Vorgänger-Streifens mitziehen.
2. Sonst, war Schritt 2 oben aktiv (beliebige Linie)? → Linie auf neue
   Y setzen. Falls es eine Nullzeilen-Ober-/Untergrenze war: Propagation
   an nachfolgende Auto-Nullzeilen (`_propagate_np_top`/`_bot`).
3. Sonst: nichts.

## Loslassen (`on_mouse_up`)

- Drag-State zurücksetzen. Falls eine Nullzeilen-Obergrenze gezogen
  wurde: als "manuell" markieren (wird künftig nicht mehr automatisch
  von Nachbarn mitgezogen). Cursor neu bestimmen.

## Rechtsklick (`on_right_click`)

Reihenfolge:

0. Ist x_canvas in NP-Zone? →
   - Treffer auf Nullzeilen-Marker (≤6px Y)? → Nullzeile entfernen
     (Schnittlinien bleiben stehen).
   - **Kein Treffer? → sofort abbrechen, keine weitere Prüfung.**
1. *(nur falls nicht in NP-Zone)* Nah an horizontaler Schnittlinie? →
   - Ist es eine Nullzeilen-Obergrenze *mit* zugehöriger Nullzeile?
     - Manuell (durchgezogen)? → nur Manuell-Flag zurücksetzen (wird
       wieder Auto/gestrichelt).
     - Sonst (schon Auto/gestrichelt)? → Nullzeile + Streifen ganz
       löschen.
   - Sonst: Linie einfach löschen.
2. *(nur falls nicht in NP-Zone)* Nah an linker Randlinie? → Rand
   entfernen.
3. *(nur falls nicht in NP-Zone)* Sonst: linken Rand an dieser
   X-Position neu setzen.

## Hover (`on_mouse_move` / `_update_cursor`, keine Taste gedrückt)

- In NP-Zone: Y-Snap-Vorschau einblenden (jetzt fix bei `NP_SCAN_X=0`).
  Cursor: `sb_v_double_arrow` auf Marker, sonst `plus`.
- Ausserhalb NP-Zone: X-Snap-Vorschau für linken Rand einblenden
  (überall, nicht nur in Streifen). Cursor je nach Treffer: `hand2`
  (Taktzahl-Label) → `sb_v_double_arrow` (Schnittlinie) →
  `sb_h_double_arrow` (Randlinie) → `left_side`/`bottom_side` (im
  Streifen) → `crosshair` (grauer Bereich).

## Entschieden & umgesetzt

**Leitprinzip:** NP-Zone (links) = ausschliesslich Nullzeilen-Dinge
(Marker setzen/verschieben/löschen). Alles Linien-Bezogene (neue
Schnitte, Ober-/Unterkante feinjustieren) macht man im normalen Bereich
rechts — Linien sind zwar page-weit sichtbar/gezeichnet, aber nur
ausserhalb der NP-Zone tatsächlich anklickbar. Klare Trennung statt
Vermischung.

1. ~~Links- vs. Rechtsklick prüften NP-Zone in unterschiedlicher
   Reihenfolge.~~ **Gefixt:** Linksklick (`on_mouse_down`) prüft jetzt
   wie Rechtsklick zuerst "bin ich in der NP-Zone" und bricht/handelt
   dort ausschliesslich Nullzeilen-Dinge ab, bevor `_find_nearby_line`
   je zum Zug kommt.
   Konkreter Bug, der dadurch mit gefixt wurde: nach Löschen einer
   Nullzeile (Marker weg, Schnittlinien bleiben stehen) liess sich an
   selber Stelle keine neue Nullzeile setzen, weil die generelle
   Linien-Erkennung den Klick zuerst abgefangen hat.

2. ~~`_find_nearby_line` war in der NP-Zone erreichbar.~~ **Gefixt**
   durch denselben Umbau wie Punkt 1 — Linien sind jetzt nur noch
   ausserhalb der NP-Zone anfassbar (Fein-Justierung z.B. der roten
   Oberkante weiterhin möglich, einfach am selben Y auf der rechten
   Seite klicken statt in der Zone).

3. **Rechtsklick in NP-Zone ohne Treffer = totaler Leerlauf** — bewusst
   so belassen (folgt direkt aus Punkt 1/2: NP-Zone tut grundsätzlich
   nichts ausser Nullzeilen-Dingen).
