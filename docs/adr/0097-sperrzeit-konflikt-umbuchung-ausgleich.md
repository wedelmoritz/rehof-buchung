# 0097 – Sperrzeit-Konflikte: Absprache, dringende Umbuchung, Ausgleich

## Status

Accepted (2026-07-05) · erweitert ADR 0086 (Sperrzeiten)

## Kontext

Eine Sperrzeit (`QuarterBlock`) blockiert die Buchbarkeit wie eine Belegung – konnte
aber **still über eine bestehende Buchung** gelegt werden. Das ist falsch: eine
Sperrzeit über einer Buchung ist ein Konflikt, der kenntlich gemacht und – außer im
dringenden Notfall – verhindert werden muss. Für echte Notfälle (Wasserrohrbruch)
braucht es dennoch einen spontanen Weg inkl. fairer Umbuchung/Entschädigung.

## Entscheidung

**Sperrzeit über Buchung wird standardmäßig abgelehnt** und mit klarer Meldung + den
**betroffenen Mitgliedern** (Name, Zeitraum, Personen, Kontakt) angezeigt. Zusätzlich
schlägt das System die **nächste freie Zeit** gleicher Länge im Quartier vor
(`suggest_block_window`).

**14-Tage-Schwelle** (`BookingPolicy.block_min_notice_days`, Default 14): Regulär soll
die BL den Konflikt **vorab mit den Mitgliedern klären** (nur mit diesem Vorlauf
möglich). Startet die Sperrung früher, greift der **dringende** Weg.

**Dringender Workflow** (mit WARNUNG, `force`):
1. Die Sperrzeit wird **trotz** Buchungen gesetzt (`create_quarter_block(force=True)`).
2. Jede kollidierende Buchung erscheint unter **„Umbuchung nötig"** (aus den Daten
   abgeleitet – verschwindet automatisch, sobald der Fall geklärt ist).
3. Die BL schlägt eine **freie Ersatz-Unterkunft** vor (`propose_relocation` →
   `RelocationRequest`): passende zuerst, sonst **zu kleine** ausdrücklich als
   „kleiner als Gruppe" markiert. Das Mitglied bekommt In-App + Mail und kann in
   „Meine Buchungen" **annehmen** (Buchung zieht sofort um, unter Sperre geprüft) oder
   **ablehnen** (die BL wird informiert).
4. Ist **keine** Unterkunft frei – oder das Mitglied lehnt ab – kann die BL die Buchung
   **stornieren & sich entschuldigen** (`cancel_with_apology`): die gebuchten Tage
   kommen **normal zurück** (kein Verfall – die BL verursacht es), optional plus bis zu
   `BookingPolicy.max_compensation_days` (Default 2) **Ausgleichs-Tage**
   (`CompensationGrant`, additiv zum `effective_annual_budget`); das Mitglied bekommt
   eine Entschuldigung mit Grund.

**Modelle:** `RelocationRequest` (proposed/accepted/rejected/cancelled),
`CompensationGrant` (member/year/days/reason). Reine Logik + Services in
`booking/services/blocks.py`; Konflikt-Panel + „Umbuchung nötig" auf `verw_sperrzeiten`,
Mitglied-Antwort in `my_bookings`.

## Konsequenzen

**Positiv** – keine stillen Doppelbelegungen mehr; die BL sieht sofort, wen es betrifft,
und hat einen fairen, nachvollziehbaren Weg (Absprache → Umbuchung → Entschuldigung +
Ausgleich). Mitglieder behalten die Kontrolle (annehmen/ablehnen) und werden bei
Notfällen fair entschädigt.

**Grenzen** – externe Gäste können nicht per In-App-Anfrage umgebucht werden (sie
erscheinen im Konflikt, die BL klärt sie direkt). Lehnt ein Mitglied ab, entscheidet die
BL manuell (erneut vorschlagen oder stornieren+entschuldigen) – bewusst kein Automatismus.
