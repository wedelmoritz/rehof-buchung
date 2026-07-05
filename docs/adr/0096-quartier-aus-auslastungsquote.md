# 0096 – Quartiere aus der Auslastungs-Quote ausschließen (Camping/Gemeinschaft)

## Status

Accepted (2026-07-05)

## Kontext

Nicht jede buchbare Einheit gehört in die Auslastungs-Statistik: **Camping- und
Gemeinschaftsflächen** verzerren die Quote (sie sind selten „voll" belegt und haben
kein sinnvolles Auslastungsziel). Bisher half sich die BL mit einer **Ziel-Auslastung
von 0 %** – ein Behelf, der die Fläche aber weiter in Kapazität und gebuchte Nächte
einrechnete.

## Entscheidung

Ein **eigenes Kästchen** am Quartier: `Quarter.count_in_occupancy` (BooleanField,
Default **True**, „In Auslastungs-Quote einbeziehen"). Aus = die Einheit zählt **weder
in die Kapazität noch in die gebuchten Nächte** der Auslastungs-Auswertung – bleibt
aber ganz normal **buchbar**.

Wirkt an allen aggregierten/statistischen Stellen:
- `year_occupancy_curve` (Gemeinschafts-Balkendiagramm) – Kapazität **und** Nächte
  gefiltert (`quarter__count_in_occupancy=True`; unverändert 3 Abfragen).
- `_month_occupancy` (Dashboard-Kennzahl aktueller/kommender Monat).
- `quarter_occupancy_ampel` – ausgeschlossene Einheiten erscheinen nicht in der
  Ziel-Ampel (sie haben kein sinnvolles Ziel).

Der **Belegungsplan** (Tape-Chart) und die Buchbarkeit sind unberührt – die Fläche
wird weiter angezeigt und ist buchbar; sie fällt nur aus der **Prozent-Statistik**.

**Bestandsdaten:** Eine Datenmigration übernimmt den bisherigen Behelf – Quartiere mit
Ziel-Auslastung **exakt 0 %** werden auf `count_in_occupancy=False` gesetzt (die BL
muss das Häkchen für bereits so gepflegte Flächen nicht neu setzen).

## Konsequenzen

**Positiv** – die Auslastungs-Quote spiegelt nur die echten Wohn-Einheiten; Camping/
Gemeinschaft verwässern sie nicht mehr. Explizites Kästchen statt Zahlen-Behelf
(klarer, unabhängig vom Ziel-Auslastungs-Feld). Buchbarkeit/Plan bleiben unberührt.

**Grenzen** – die Einordnung ist eine bewusste Pflege-Entscheidung je Einheit; neu
angelegte Quartiere zählen per Default mit (opt-out).
