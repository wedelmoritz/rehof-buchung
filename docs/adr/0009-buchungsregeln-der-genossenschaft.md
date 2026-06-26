# 0009 – Buchungsregeln der Genossenschaft umgesetzt

## Status

Accepted (2026-06-26) – teilweise umgesetzt (Saison-Regeln noch nicht in der Losung)

## Kontext

Die Genossenschaft Re:Hof gibt verbindliche Buchungsregeln vor. Diese sind **keine
Entscheidung des Entwicklungsteams**, sondern **Vorgabe der Genossenschaft**, die die
App abbilden muss:

- **Tage-Kontingent:** 50 Nächte pro Mitglied und Kalenderjahr, davon höchstens 25
  über die Wunschliste (Losung). **Kein Übertrag ins Folgejahr** – das Kontingent
  gilt je Kalenderjahr frisch.
- **Saison-Regeln je Zeitraum (jeweils optional):** Mindestnächte (z. B. Juli/August
  7), Höchstzahl gleichzeitig gebuchter Wohneinheiten pro Mitglied, Aufenthaltsdeckel
  in Einheiten-Nächten (z. B. BB-Sommerferien 14).

Konkrete Termine (Schulferien, Brückentage) verschieben sich jährlich und dürfen
nicht im Code stehen.

## Entscheidung

Wir setzen die Vorgaben als **prüfbare Regel-Logik plus konfigurierbare Stammdaten** um:

- **Reine Regel-Logik** in `booking/rules.py` (`validate_booking`,
  `required_min_nights`): datumsbasiert, Django-frei, isoliert getestet
  (`tests/test_rules.py`). Drei Regelarten je `Season`: `min_nights`,
  `max_parallel_units`, `max_stay_nights` (Einheiten-Nächte). „Parallel“ = zeitliche
  Überschneidung.
- **Konfigurierbare Daten** im Admin: `BookingPolicy` (Standard-Mindestnächte) mit
  `SeasonRule` als jährlich wiederkehrende Zeiträume (Monat/Tag, ohne Jahr). Der
  Service materialisiert sie pro Jahr zu Daten (`services._materialized_seasons`,
  Helfer `availability.recurring_range`).
- **Tage-Kontingent** als Budget am Mitglied/Anteil (`Member`/`Share`,
  `wish_night_budget` = 25 im Lostopf); Rest-Nächte über
  `booking/availability.py:remaining_nights`. Das Wunsch-Budget greift auch in der
  Losung (`lottery.Party.wish_night_budget`, Default 25). Kein Übertrag, weil die
  Rechnung je Kalenderjahr neu erfolgt.

**Offener Punkt:** Die Saison-Regeln (Parallel-Limit/Deckel) werden **aktuell nur
bei der normalen Buchung** erzwungen (`services.validate_booking`-Pfad), **noch
nicht in der Losung** (`run_period_lottery` ruft `rules.py` nicht auf). `rules.py`
ist dafür bereits entkoppelt; Einhängepunkt wäre `run_period_lottery`.

## Betrachtete Alternativen

- **Regeln im Code festverdrahtet:** jede jährliche Terminverschiebung erforderte
  ein Release; die Genossenschaft könnte ihre Vorgaben nicht selbst pflegen.
- **Übertrag ungenutzter Tage ins Folgejahr:** widerspricht der Vorgabe; würde
  Kontingente anhäufen.

## Konsequenzen

**Positiv**
- Vorgaben der Genossenschaft sind eingehalten und im Admin pflegbar.
- Regel-Logik schnell und isoliert testbar.

**Negativ**
- Inkonsistenz, solange die Saison-Regeln in der Losung fehlen (siehe Offener Punkt) –
  ein bewusst dokumentierter Rückstand.
- Pflege der jährlichen Termine bleibt eine wiederkehrende Verwaltungsaufgabe.
