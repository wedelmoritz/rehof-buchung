# 0092 – „Nicht verfügbar“-Quartiere sichtbar machen + Mobil-Umbruch der Plan-Namen

## Status

Accepted (2026-07-05) · konkretisiert ADR 0087 (Punkt 7)

## Kontext

Auf der Buchen-Seite verschwanden Unterkünfte, die für den gewählten Zeitraum nicht
freigeschaltet oder außerhalb ihrer Saison sind, **kommentarlos** aus der Liste – das
Mitglied konnte nicht unterscheiden „gibt es nicht“ von „gerade nicht buchbar“.
Zusätzlich schnitt der Belegungsplan (Tape-Chart) lange Unterkunftsnamen am Handy mit
`…` ab (`--qw:7rem`), sodass ähnliche Namen ununterscheidbar wurden.

## Entscheidung

1. **Nicht-buchbare Quartiere ausgrauen statt verstecken.**
   `services.unavailable_quarters_for_range(start, end)` liefert die **aktiven**
   Quartiere, die im Zeitraum **weder frei noch belegt** sind, mit einem
   **Grund-Text**: „Nur saisonal buchbar (<von>–<bis>)“ (aus dem neuen
   `Quarter.season_label`) bzw. „Für diesen Zeitraum noch nicht freigeschaltet“.
   `book.html` zeigt sie unter „Nicht verfügbar“ als ausgegraute, nicht anklickbare
   Zeile (Größe/Personen + Grund rechts). Reine Anzeige – die Buchbarkeit selbst
   (`split_quarters_for_range`, `range_is_released`) ist unverändert.

2. **Lange Plan-Namen am Handy auf 2 Zeilen umbrechen** statt abschneiden:
   `.tape-qname` bekommt in der `max-width:680px`-Media-Query `white-space:normal` +
   `-webkit-line-clamp:2` (Desktop bleibt einzeilig mit Ellipse).

## Konsequenzen

**Positiv** – transparenter: das Mitglied sieht, *warum* eine Unterkunft fehlt (Saison
mit konkretem Zeitraum), und kann den Termin entsprechend wählen; am Handy bleiben
Unterkünfte im Plan unterscheidbar.

**Grenzen** – die „Nicht verfügbar“-Liste wächst mit vielen saisonalen Quartieren;
sie steht bewusst unter den buchbaren/belegten, damit sie nicht ablenkt.
