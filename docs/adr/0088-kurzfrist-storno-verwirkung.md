# 0088 – Kurzfrist-Storno/Verkürzen: Tage-Verwirkung + In-App-Aufruf

## Status

Accepted (2026-07-05)

> Wunsch der Betriebsleitung: kurzfristige Stornos/Verkürzungen sollen die
> Auslastung nicht entwerten.

## Kontext

Storniert oder verkürzt ein Mitglied eine Buchung **kurz vor der Anreise**, ist der
frei werdende Zeitraum kaum noch neu zu vergeben. Bisher bekam das Mitglied die Tage
in jedem Fall zurück (Storno) bzw. Verkürzen war unter einer starren „≥7-Tage"-Sperre
teils verboten. Das setzt falsche Anreize (kurzfristig „Tage retten") und lässt die
Wohneinheit ungenutzt.

## Entscheidung

Eine **Kurzfrist-Grenze** `BookingPolicy.short_notice_days` (Default **14 Tage** vor
Anreise, im Backend konfigurierbar) steuert eine **Verwirkung**:

- **> Grenze (langfristig):** Storno/Verkürzen wie bisher – die Tage kommen zurück,
  die Warteliste wird informiert.
- **≤ Grenze (kurzfristig):** die betroffenen Nächte **verfallen** – sie werden
  weiter vom Jahreskontingent abgezogen (`Member.effective_annual_budget` −
  `forfeited_nights_in_year`). **Zurück** gibt es sie nur, **soweit ein anderes
  Mitglied** den frei gewordenen Zeitraum (im selben Quartier) ganz/teilweise **neu
  bucht** – dann wird der gedeckte Anteil **dynamisch** wieder freigegeben.
  Zusätzlich werden **ALLE Mitglieder in der App** informiert („Spontan frei …") –
  **ohne** Mail (Mail bleibt gezielt für die Warteliste). Das Mitglied wird
  aufgefordert, den Zeitraum selbst publik zu machen.

**Modell `ForfeitedNights`** (Mitglied, Jahr, Quartier, Zeitraum, Nächte, Anlass
cancel/shorten). `effective` = angelegte Nächte − aktuell von anderen Mitgliedern im
selben Quartier/Zeitraum gebuchte Nächte (`covered_by_others`, dynamisch → korrigiert
sich auch, wenn der Neubucher wieder storniert). Additiv, kein Soft-Delete der
Buchung (die bleibt storniert, `CancellationLog` wie gehabt).

**Verkürzen:** die frühere „frei werdende Nächte ≥7 Tage in der Zukunft"-Sperre in
`adjust_allocation` **entfällt** – kurzfristiges Verkürzen ist erlaubt, verwirkt aber
(gleiche Logik). **Quartier-Wechsel (Umzug)** verwirkt nichts (es wird nicht gekürzt).

**UI:** „Meine Buchungen" markiert kurzfristige Buchungen (`is_short_notice`) mit
einer Warnung und einem verschärften Storno-Bestätigungstext (Tage verfallen, bitte
selbst Werbung machen).

## Konsequenzen

**Positiv** – fairer Anreiz (kurzfristiges „Tage retten" lohnt nicht), die
Wohneinheit wird über den In-App-Aufruf sichtbar angeboten, und wer den Slot
tatsächlich neu füllt, gibt dem stornierenden Mitglied die Tage zurück. Rein additiv
(ein Modell + ein Policy-Feld + Budget-Abzug), integriert in die bestehende
Storno-/Anpass-Naht und den vorhandenen „Spontan frei"-Broadcast.

**Grenzen** – die Rückgabe wird dynamisch aus den aktuellen Buchungen berechnet; sehr
alte Verwirkungen räumt die DSGVO-Aufbewahrung mit weg. Der Deckel-/Regel-Check der
Losung ist unberührt (Verwirkung betrifft nur das Jahreskontingent der Spontanwelt).
