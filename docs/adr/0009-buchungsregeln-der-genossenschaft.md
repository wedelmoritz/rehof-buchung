# 0009 – Buchungsregeln der Genossenschaft umgesetzt

## Status

Accepted (2026-06-26) – Mindestnächte überall erzwungen; Parallel-Limit/Deckel über
mehrere Buchungen bleiben bewusst auf die normale Buchung beschränkt (siehe Offener
Punkt)

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

**Geltungsbereich der Regeln:**
- **Mindestnächte** (+ Einzel-Aufenthaltsdeckel als Obergrenze einer einzelnen
  Buchung) werden überall erzwungen: normale Buchung (`check_booking_rules`),
  **Wunschliste/Losung** beim Eintragen/Einreichen
  (`services.wish_rule_error` in `add_wish`/`submit_wishlist` – ein zu kurzer
  Wunsch lässt sich nicht einreichen, ein Losgewinn scheitert also nicht daran)
  und **externe Buchungen**. Für Externe ist der Mindestaufenthalt im Backend
  konfigurierbar (`services.external_min_nights`): **Default = wie intern** (inkl.
  Saison-Mindestnächte), per Schalter `ExternalConfig.min_nights_follow_internal`
  auf einen eigenen, abweichenden Wert umstellbar (siehe ADR 0023).
- **Offener Punkt:** Das **Parallel-Limit** und der **Aufenthaltsdeckel über
  mehrere Buchungen** wirken nur bei der normalen Buchung. Sie betreffen mehrere
  gleichzeitige Einheiten je Mitglied und sind je Einzelwunsch nicht entscheidbar;
  der Los-Algorithmus (`lottery.run_lottery`) bleibt deshalb bewusst unverändert
  (Beschluss: Saison-Regeln nur beim Einreichen prüfen). Eine vollständige
  Durchsetzung in der Losung selbst bliebe ein möglicher Ausbau (Einhängepunkt
  `run_period_lottery`).

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
- Das Parallel-Limit/der Mehrfach-Deckel greifen nicht in der Losung (siehe Offener
  Punkt) – bewusst, da je Einzelwunsch nicht entscheidbar.
- Mindestnächte werden an mehreren Stellen geprüft (Buchung, Wunsch-Eintrag,
  Wunsch-Einreichen, extern) – die gemeinsame Logik liegt zentral in
  `services`/`rules.py`, muss aber konsistent eingebunden bleiben.
- Pflege der jährlichen Termine bleibt eine wiederkehrende Verwaltungsaufgabe.
