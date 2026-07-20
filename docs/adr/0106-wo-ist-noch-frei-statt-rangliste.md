# 0106 – „Wo ist noch frei?" statt Beliebtheits-Rangliste (Umsetzung P1)

## Status

Proposed (2026-07-20) · **setzt [ADR 0103](0103-wunsch-situationsbild-beliebtheit-und-vorschlaege.md)
P1 um** · baut auf [ADR 0105](0105-beliebtheit-relativ-zur-kapazitaet.md) (Beliebtheits-
Logik) · Wortwahl [ADR 0072](0072-positive-wortwahl-frontend.md) · löst die Ranglisten aus
[ADR 0101](0101-entzerrungsphase-vor-losung.md) ab. **Umgesetzt (2026-07).**

## Kontext

Der Nachfrage-Reiter zeigte **Ranglisten** der „beliebtesten Unterkünfte/Zeiträume". Das
lenkt den Blick auf die **umkämpften** Dinge (Herding) und beantwortet nicht die
Handlungs-Frage der Gemeinschaft: **wo ist noch etwas frei, damit mein Wunsch aufgeht?**
(ADR 0103, P1a). Die kapazitätsrelative Beliebtheit steht seit ADR 0105 bereits **im
Eintrag-Kalender** am Entscheidungspunkt (P1b ist damit erfüllt).

## Entscheidung

**Rangliste raus, „Wo ist noch frei?" rein.** Service `freest_slots(period, top)` bestimmt je
**ISO-Woche** des Buchungszeitraums die Beliebtheit **je Äquivalenzklasse**
(`popularity_band`, ADR 0105) und listet – nur in **tatsächlich gefragten Wochen** (irgendeine
Klasse beliebt/sehr beliebt) – die noch **freien / etwas gefragten** gleichwertigen Klassen
als **Ausweich-Tipp** („hier bekommst du fast sicher etwas"). Chronologisch, gedeckelt,
mit Beispiel-Unterkünften je Klasse. Nur **buchbare** Klassen (Kapazität > 0 in der Woche).

Die **Nachfrage-Heatmap** (Quartier × Monat) bleibt als Gesamtüberblick (ADR 0103: „der
Nachfrage-Reiter bleibt für den Gesamtüberblick"). Die alte `wish_demand_ranking` entfällt
ersatzlos (samt Test).

**P1b (Heatmap am Entscheidungspunkt)** ist durch die **kapazitätsrelative Kalender-Ampel**
aus ADR 0105 bereits erfüllt (Beliebtheit „in place" beim Datum-Wählen); dieser ADR ergänzt
die **positive, umsetzbare** Gegenliste im Nachfrage-Reiter.

## Architektur / Sicherheit / Performanz

- **Reine Bänder-Logik** wiederverwendet (`booking/popularity.py`, ADR 0105); `freest_slots`
  ist ein Service (iteriert Wochen/Quartiere), eine Wunsch-Abfrage, Rest in Python
  (wenige Dutzend Quartiere × ~52 Wochen).
- **Security/Datensparsamkeit:** ausschließlich **anonyme Aggregate** (Klassen-Bänder,
  Beispiel-Quartiersnamen; **keine** Mitgliedsnamen); escaped gerendert; CSP-treu.
- **Strategiesicherheit unberührt:** reine Anzeige; die RSD-Losung bleibt gleich.

## Betrachtete Alternativen

- **Ranglisten behalten + freest ergänzen:** verworfen – die Rangliste fördert Herding und
  ist die Frage, die ADR 0103 bewusst ablöst.
- **freest je Woche für ALLE Wochen (auch ohne Nachfrage):** verworfen – flutet die Liste
  mit trivialen „alles frei"-Wochen; der Nutzen liegt im **Kontrast** in gefragten Wochen.
- **Quartier × Woche statt Klasse × Woche:** verworfen – die Losung weicht auf die **Klasse**
  aus (ADR 0003); die Klasse ist die ehrliche Chance-Einheit.

## Konsequenzen

**Positiv** – der Nachfrage-Reiter beantwortet die Handlungs-Frage („wo ist frei") statt
„was ist beliebt"; positiv/umsetzbar; nutzt die vorhandene Bänder-Logik; kein neues Modell.

**Negativ / Grenzen** – `freest_slots` zeigt nur Wochen **mit** Nachfrage-Kontrast (bei sehr
geringer Gesamtnachfrage bleibt die Liste leer → dann Hinweis „überall gute Chancen"); die
Kapazität nimmt den Wochen-Montag als Repräsentant (kleine Vereinfachung an Saison-Rändern,
nur Anzeige).
