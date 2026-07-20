# 0107 – Entzerrungs-Barometer (anonymer Community-Nudge, Umsetzung P2)

## Status

Proposed (2026-07-20) · **setzt [ADR 0103](0103-wunsch-situationsbild-beliebtheit-und-vorschlaege.md)
P2 (Barometer) um** · baut auf [ADR 0105](0105-beliebtheit-relativ-zur-kapazitaet.md)
(Beliebtheits-Logik) · Datensparsamkeit [ADR 0043](0043-dsgvo-datensparsamkeit-aufbewahrung-loeschung.md)
/ Anonymität [ADR 0063](0063-gemeinschafts-spiegel-karma-transparenz.md) · Wortwahl
[ADR 0072](0072-positive-wortwahl-frontend.md). **Umgesetzt (2026-07).**

## Kontext

Die dritte Handlungs-Frage aus ADR 0103 lautet: **„Ballen wir uns oder verteilen wir
uns?"** – ein geteiltes Lagebild, das sanft zum Ausweichen anstupst. Die einzelnen
Beliebtheits-Signale (ADR 0105/0106) zeigen das je Slot; es fehlte ein **einziger,
gemeinschaftlicher** Indikator.

## Entscheidung

**Ein anonymer Indikator „Verteilen wir uns?"** Service `entzerrung_barometer(period)`
misst den **Anteil der Wünsche, die in „sehr beliebten" Slots liegen** (0–100 %). Je Wunsch
wird die Beliebtheit seiner **Äquivalenzklasse im eigenen Zeitraum** bestimmt
(`popularity_band`, ADR 0105); „sehr beliebt" = überzeichnet. `pct = sehr-beliebte /
gesamt`, plus ein grobes Band (`good` < 20 % · `mid` < 40 % · `high` sonst).

Anzeige als schlanker **HTML/CSS-Balken** im Nachfrage-Reiter der Wunschliste (kein JS/SVG-
Text, ADR 0095): Prozentwert + Fortschrittsbalken + Einordnung „je niedriger, desto besser
verteilt – jeder Wunsch auf eine ruhigere Zeit senkt den Wert für alle". Der Wert **sinkt,
während alle entzerren** – leichtes, transparentes Nudging.

## Architektur / Sicherheit / Performanz

- **Bänder-Logik wiederverwendet** (`booking/popularity.py`, ADR 0105); Service in
  `calendars.py`, eine Wunsch-Abfrage, O(#Wünsche²) rein in Python (Dutzende bis wenige
  Hundert Wünsche – unkritisch).
- **Security/Datensparsamkeit:** **eine anonyme Aggregat-Zahl** – keine Namen, keine
  Slot-Auflistung, keine PII; escaped/CSP-treu.
- **Strategiesicherheit unberührt:** reine Anzeige; kein Los-Eingriff. Dem Nudge zu folgen
  (auf ruhigere Zeiten ausweichen) ist genau das vom Mechanismus belohnte kooperative
  Verhalten.

## Betrachtete Alternativen

- **Pro-Kopf-Rangliste „wer ballt am meisten":** verworfen (bloßstellend, gegen Anonymität/
  ADR 0072).
- **Absolutzahl statt Anteil:** verworfen – der Anteil ist über verschieden große Perioden
  vergleichbar und intuitiver als „X von Y".
- **Nur im Gemeinschafts-Spiegel:** die Wunschliste ist der Handlungsort (beim Eintragen/
  Entzerren) – dort wirkt der Nudge; eine spätere Spiegelung in `community` bleibt offen.

## Konsequenzen

**Positiv** – beantwortet die dritte Handlungs-Frage („ballen/verteilen") mit einem
verständlichen, anonymen Signal; nutzt vorhandene Logik; datensparsam; positiv formuliert.

**Negativ / Grenzen** – der Wert hängt an der Bänder-Kalibrierung (ADR 0105); als
Gemeinschafts-Mittel kann er einen einzelnen ballenden Wunsch nicht sichtbar machen (bewusst
– Anonymität). Bei sehr wenigen Wünschen ist er volatil (dokumentierte Grenze).
