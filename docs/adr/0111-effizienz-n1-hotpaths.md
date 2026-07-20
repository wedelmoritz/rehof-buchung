# 0111 – Effizienz: N+1 in den Verfügbarkeits-Hot-Paths beseitigen

## Status

Accepted (2026-07-20) · härtet [ADR 0060](0060-performance-skalierung.md)
(Performance/Skalierung) · nutzt den Belegungs-Cache aus ADR 0060
(`_occupied_days_by_quarter`). **Umgesetzt (2026-07)** – Ergebnis des
vollständigen Effizienz-Reviews.

## Kontext

Der Effizienz-Teil des Voll-App-Reviews fand ein klares N+1-Muster in den
Verfügbarkeits-Hot-Paths:

- `range_is_released(quarter, start, end)` lud die freigeschalteten Perioden
  über `_active_windows()` (eine DB-Abfrage) bei **jedem** Aufruf neu.
- `quarter_is_free(quarter, start, end)` feuerte je Aufruf bis zu **drei**
  `.exists()`-Abfragen (Zuteilung, Sperrzeit, externe Buchung).
- `free_quarters_for(start, end, persons)` ruft beide **je Quartier** in einer
  Schleife auf → ~4×N Abfragen pro Aufruf.
- Die Ansicht **„Meine Buchungen"** ruft `free_quarters_for` **je bevorstehender
  Buchung** auf → in Summe mehrere hundert Abfragen bei wenigen Buchungen.
- Zusätzlich summiert die **Rechnungsliste** (`shop_invoices`) je Rechnung
  `Invoice.total_gross` über die Positionen – ohne Prefetch eine Abfrage je
  Rechnung.

## Entscheidung

**Vorab laden statt je Quartier neu abfragen – ohne die Buchungs-Semantik zu
ändern.** Beide reinen Prüf-Funktionen bekommen einen **optionalen**
Vorab-Daten-Parameter; der frische DB-Pfad bleibt der Default (u. a. für die
Buchung unter Zeilensperre, ADR 0013):

- `quarter_is_free(…, occupied_days=…)` – mit den belegten Tagen des Quartiers
  (aus `_occupied_days_by_quarter`, `set[date]`) prüft die Funktion rein in
  Python gegen die Menge statt drei `.exists()`-Abfragen. Die Menge deckt
  Zuteilungen, bestätigte Externe **und** Sperrzeiten ab (identisch zum DB-Pfad).
- `range_is_released(…, windows=…)` – mit den vorab geladenen Perioden entfällt
  die `_active_windows()`-Abfrage.

`free_quarters_for` lädt Perioden **und** Belegung nun **einmal** vorab und reicht
sie je Quartier durch (statt je Quartier neu abzufragen); zusätzlich filtert es –
wie alle anderen Quartier-Listen – auf `active=True`. `shop_invoices` lädt die
Positionen mit `prefetch_related("items")`.

## Architektur / Sicherheit / Performanz

- Kleine, additive Diffs (nur neue **keyword-only** Parameter, alte Aufrufer
  unverändert); keine Verhaltensänderung für legitime Abläufe.
- **Sicherheit/Korrektheit:** die eigentliche Buchung prüft weiterhin **frisch
  unter Sperre** (kein Vorab-Argument im Schreibpfad) – der Vorab-Pfad ist reine
  Anzeige-Beschleunigung, exakt wie der bestehende Belegungs-Cache (ADR 0060).
- **Wirkung:** `free_quarters_for` fällt von ~4×N auf wenige **konstante**
  Abfragen (unabhängig von der Quartier-Anzahl); die Rechnungsliste bleibt bei
  konstanter Abfragezahl unabhängig von der Rechnungs-Anzahl.
- Regressionstests `booking/tests_efficiency.py` (`CaptureQueriesContext`):
  Abfragezahl von `free_quarters_for` bleibt bei 3 vs. 15 Quartieren gleich;
  Rechnungsliste bleibt bei 2 vs. 10 Rechnungen gleich; belegtes Quartier fällt
  weiter korrekt aus dem Ergebnis.

## Konsequenzen

**Positiv** – die teuersten Anzeige-Pfade skalieren nicht mehr mit der Quartier-/
Rechnungs-Anzahl; das N+1-Muster ist durch Tests abgesichert.

**Negativ / Grenzen** – der Vorab-Pfad setzt voraus, dass die Aufrufer die
Belegung über einen Bereich laden, der den Prüf-Zeitraum abdeckt (in
`free_quarters_for` gekapselt). Wer die Parameter selbst nutzt, muss den Bereich
passend wählen; der DB-Default bleibt für alle anderen der sichere Weg.
