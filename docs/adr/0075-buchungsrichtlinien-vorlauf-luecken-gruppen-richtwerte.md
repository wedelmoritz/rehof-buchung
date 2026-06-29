# 0075 – Buchungsrichtlinien: Spontan-Vorausfrist, Lückenfüllung, Gruppen-Reihung, Richtwerte

## Status

Accepted (2026-06-29)

> Ergänzt ADR 0009 (Saison-Regeln in Buchung & Losung) und 0024 (Buchungsfluss).

## Kontext

Die Genossenschaft hat schriftliche Buchungsrichtlinien. Ein Teil war über
`SeasonRule`/`SchoolHoliday` bereits konfigurierbar und greift in Buchung,
Wunschliste und Losung:

- **Mindestbuchung 3 / 7 Nächte (Juli/August)** → `default_min_nights` + Saison-Regel.
- **Max. 2 Wohneinheiten parallel in begehrten Zeiten** → `max_parallel_units`.
- **Sommerferien BB max. 2 Wochen je Partei** → `max_stay_nights=14`
  (Einheiten-Nächte: 2 Wochen × 1 WE = 1 Woche × 2 WE = 14).
- **Passende Wohneinheit für die Personenzahl** → `Quarter.min/max_occupancy`.

Drei Richtlinien fehlten technisch, mehrere sind bewusst **nur Richtschnur**
(nicht sinnvoll erzwingbar). Entscheidungen mit dem Auftraggeber abgestimmt.

## Entscheidung

**1) Spontan-Vorausfrist (durchgesetzt, konfigurierbar).**
`BookingPolicy.min_lead_days` (Default 7): eine **Spontanbuchung** muss mind. so
viele Tage vor der Anreise liegen. Greift in `book_spontaneous` (also im normalen
Buchungsfluss), **nicht** in Wunschliste/Losung (die vergibt das Folgejahr ohnehin
im Voraus). Reine Service-Prüfung `services.lead_time_blocker` (braucht „heute",
daher nicht im datumsreinen `rules.py`).

**2) Lückenfüllung (durchgesetzt, konfigurierbar, abschaltbar).**
`BookingPolicy.allow_gap_fill` (Default an): Füllt eine Buchung eine freie Lücke
**exakt** aus, entfallen **Mindestnächte UND Vorausfrist** (Parallel-Limit/Deckel
bleiben). „Exakt" = beidseitig geschlossen: die Nacht direkt vor `start` und direkt
nach `end` ist nicht frei buchbar (belegt oder außerhalb des freigeschalteten/
saisonalen Zeitraums) – dann lässt sich der Zeitraum nicht verlängern, er füllt die
Lücke in ihrer ganzen Länge. Reine, gezielte Prüfung `services.is_gap_fill` (wenige
DB-Abfragen, je Randnacht eine Frei-/Freigabe-Prüfung); `rules.validate_booking`
erhielt ein `skip_min_nights`-Flag. Greift in `book_spontaneous` **und**
`adjust_allocation`.

**3) Gruppen → Stallgebäude zuerst (sanfte Reihung).**
Neue Quartier-Felder `building` (Bezeichnung) und `prefer_for_groups` (Flag). Ab
`BookingPolicy.group_min_persons` (Default 3) gilt eine Buchung als Gruppe; dann
werden `prefer_for_groups`-Wohneinheiten in der Buchen-Liste **zuerst** angezeigt
(+ Badge/Hinweis). **Keine Sperre**, nur Reihenfolge (`services.is_group_booking`).

**4) Weiche Richtwerte (Anzeige + Hilfetext, kein Limit).**
- **Winter-Richtwert** `BookingPolicy.winter_guideline_nights` (Default 20 Tage
  Okt–März): `services.winter_usage` zeigt „X von N Tagen gebucht" auf Übersicht
  und Buchen.
- **Rücksichts-Hinweis in begehrten Zeiten:** `services.high_demand_periods` liefert
  die Namen überlappender Schulferien/Feiertage; ein nicht-blockierender Hinweis
  (Partial `_high_demand_note.html`) mit den Reflexionsfragen erscheint beim
  Buchen **und** Wünschen.
- **„8–9 Wochenenden", „eigene Nutzung / keine Weitergabe an Externe ohne Mitglied
  vor Ort":** rein als **Richtschnur** auf der Hilfeseite – technisch nicht
  verifizierbar (Anwesenheit, gefühlte Angewiesenheit), daher bewusst nicht
  erzwungen.

Konfiguration: alles am Singleton `BookingPolicy` (Backend) bzw. je `Quarter`;
`seed_demo` setzt die Defaults (Vorausfrist 7, Lücken an, Gruppe ab 3, Winter 20)
und markiert die „Stallgebäude"-Quartiere als `prefer_for_groups`.

## Konsequenzen

**Positiv** – die Richtlinien sind jetzt überall stimmig: harte Regeln greifen in
Buchung (und wo sinnvoll Wunschliste/Losung), weiche Richtwerte sind sichtbar, ohne
zu bevormunden. Alles ist im Backend einstellbar; wenige zusätzliche DB-Abfragen
(Lücken-Geometrie nur, wenn eine Lücke überhaupt helfen könnte; Policy-Singleton).

**Grenzen / bewusst nicht erzwungen** – „eigene Nutzung", „angewiesen-sein" und die
8–9-Wochenenden bleiben Richtschnur (nicht prüfbar). Die Vorausfrist ist im
Modell-Default 7, in den **Test-Basisklassen auf 0** gesetzt (die Alt-Tests buchen
bewusst nah/vergangen); eigene Tests (`tests_policies.py`) decken Frist +
Lückenfüllung + Richtwerte ab.
