# 0002 – Drei-Schichten-Architektur: reine Logik / Service-Layer / dünne Views

## Status

Accepted (2026-06-26)

## Kontext

Die Geschäftsregeln (Losverfahren, Verfügbarkeit, Buchungsregeln) sind komplex und
müssen nachvollziehbar, testbar und gezielt änderbar bleiben. Eine Vermischung von
Rechenregeln, Datenbankzugriff und Darstellung würde Tests verlangsamen
(DB-Aufbau für jeden Fall) und Änderungen riskant machen.

## Entscheidung

Strikte Trennung in drei Schichten:

1. **Reine Logik (ohne Django-Import):** `booking/lottery.py`, `booking/availability.py`,
   `booking/rules.py`, `booking/external.py`, `booking/fairness.py`,
   `booking/beds24.py`. Sie arbeiten nur mit einfachen Datenklassen und sind
   isoliert mit `pytest` testbar (`tests/`).
2. **Service-Layer:** `booking/services/` (fachlich aufgeteiltes Paket, ADR 0050;
   früher eine einzelne `services.py`) ist die **einzige** Brücke zwischen
   Django-Modellen und reiner Logik (Persistenz, Verfügbarkeit, Buchung, Losung).
3. **Views/Templates:** `booking/views.py` bleibt dünn (Dispatch),
   Darstellung in `*/templates/`.

Faustregel: Rechenregel → reines `*.py`-Modul + Pure-Test; Daten/Ablauf →
Service-Layer (`booking/services/`); Darstellung → View/Template.

> **Fachlicher Bezug:** Die fachlichen Regeln, die diese Schichten umsetzen,
> stehen gebündelt im [Fachkonzept](../FACHKONZEPT.md). Die ADRs halten die
> technischen Entscheidungen fest.

## Betrachtete Alternativen

- **„Fat Models“/Logik in Views:** weniger Dateien, aber Logik nur mit DB testbar
  und schwer reviewbar.
- **Service-Layer ohne reine Module:** Tests bräuchten weiterhin Django/DB; die
  schnelle, DB-freie Logik-Suite entfiele.

## Konsequenzen

**Positiv**
- Schnelle, DB-freie Tests der Kernregeln (siehe ADR 0022).
- Gezielte Diffs: eine Rechenregel ändert man an genau einer Stelle.
- Gute Reviewbarkeit; reine Module sind in sich abgeschlossen.

**Negativ**
- Zwei Test-Ebenen (pure + Integration) müssen gepflegt werden.
- Etwas „Übersetzungs-Boilerplate“ im Service-Layer (Modelle ↔ Datenklassen),
  z. B. `run_period_lottery` baut `L.Party/L.Quarter/L.Wish` aus den ORM-Objekten.
