# 0009 – Buchungsregeln der Genossenschaft umgesetzt

## Status

Accepted (2026-06-26) – vollständig umgesetzt: Mindestnächte überall, Parallel-Limit
und Aufenthaltsdeckel jetzt auch in der Losung (siehe „Geltungsbereich der Regeln")

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
- **Parallel-Limit** und **Aufenthaltsdeckel über mehrere Buchungen** werden jetzt
  **auch in der Losung** erzwungen: `lottery.run_lottery` nimmt einen optionalen
  `rule_check`-Callback und führt je Partei die im Lauf bereits zugeteilten
  Zeiträume (`party_stays`). `run_period_lottery` baut den Callback aus
  `rules.validate_booking` + einmalig materialisierten Saison-Regeln (keine
  N+1-Queries). Würde ein Wunsch den Deckel überschreiten, wird er **terminal
  übersprungen** – wie ein Budget-Übersprung, **kein** echter Verlust und **kein**
  Karma-Bonus. Das ist bewusst gewählt: Würde der Deckel als Verlust zählen,
  ließe sich durch absichtliches Über-Wünschen überlappender Einheiten Karma
  „farmen" – die Strategiesicherheit bliebe so erhalten (siehe ADR 0003).
- **Runden-Verhalten (wichtig für die Fairness):** Ein übersprungener Wunsch –
  ob Deckel, Budget oder echter Verlust – **übergeht die Partei nicht**. Die Losung
  prüft in **derselben Runde** sofort den **nächsten Wunsch (niedrigere Priorität)
  derselben Partei** weiter (innerer `while`-Loop in `run_lottery`, jeder Skip macht
  `pointer += 1; continue`). Die Partei verliert also ihren Zug nicht; erst eine
  erfolgreiche Buchung beendet ihre Runde. Beispiel: Prio 1 ist gedeckelt → die
  Partei bekommt in derselben Runde ggf. Prio 2 zugeteilt. Belegt durch
  `tests/test_lottery.py::test_rule_skip_prueft_naechste_prioritaet_in_gleicher_runde`
  und den Integrationstest `LosungDeckelReihenfolgeTests`.
- **Grenze (dokumentiert):** Der Deckel-Check betrachtet nur die **innerhalb des
  Losdurchlaufs** zugeteilten Zeiträume – konsistent zum „leeren Start" der Losung
  (sie lädt auch für die Verfügbarkeit keine bestehenden Buchungen). Zum
  Losungszeitpunkt (Folgejahr im Voraus) existieren normalerweise noch keine
  anderen Buchungen der Partei.

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
- Die Regeln werden an mehreren Stellen geprüft (Buchung, Wunsch-Eintrag,
  Wunsch-Einreichen, Losung, extern) – die gemeinsame Logik liegt zentral in
  `rules.py`, muss aber überall konsistent eingebunden bleiben.
- Der Deckel-Check in der Losung sieht nur die laufeigenen Zuteilungen, nicht
  bereits bestehende Buchungen der Partei (dokumentierte Grenze, in der Praxis
  unkritisch).
- Pflege der jährlichen Termine bleibt eine wiederkehrende Verwaltungsaufgabe.
