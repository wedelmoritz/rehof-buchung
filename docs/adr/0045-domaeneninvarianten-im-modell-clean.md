# 0045 – Domänen-Invarianten am Modell (`clean`) erzwingen, nicht nur im Service

## Status

Accepted (2026-06-27)

## Kontext

Die Geschäftslogik (Verfügbarkeit, Überlappungsfreiheit, Personenzahl) lag bisher
ausschließlich im Service-Layer (`booking/services.py`, z.B. `book_spontaneous` →
`quarter_is_free`). Der **Django-Admin** umgeht diesen Layer aber: er schreibt über
`ModelForm`/`Model.save()` direkt in die DB. Dadurch ließ sich im Backend eine
**Doppelbuchung** anlegen (zwei Zuteilungen für dieselbe Unterkunft im selben
Zeitraum) – eine verletzte Kern-Invariante, die im normalen Buchungsfluss unmöglich
ist. Das ist ein Datenintegritäts-Risiko, kein bloßer Schönheitsfehler.

## Entscheidung

Die **harten Invarianten einer Buchung** werden zusätzlich am Modell in
`Allocation.clean()` geprüft:

- gültiger Zeitraum (`end > start`),
- Personenzahl im Rahmen des Quartiers (`min_occupancy..max_occupancy`),
- **keine Überschneidung** mit einer anderen `Allocation` oder einer **bestätigten**
  `ExternalBooking` im selben Quartier (sich selbst beim Bearbeiten ausgenommen).

`Model.clean()` wird von Djangos `full_clean()` aufgerufen – und das nutzt jede
`ModelForm`, also auch der Admin. Damit weist das Backend eine Doppelbuchung beim
Speichern als Formularfehler ab. Der Service-Layer ruft `full_clean()` **nicht**
auf (er erzeugt über `.create()`/`.save()` und validiert selbst, fachlich reicher);
die `clean`-Prüfung ist daher ein **zusätzliches Sicherheitsnetz** für die manuelle
Pflege, kein Ersatz und keine Verhaltensänderung im Buchungsfluss.

Die Prüfung lebt im Modell (nicht im Service), weil sie nur Modelldaten braucht
(`Allocation`, `ExternalBooking`) und so **ohne Layer-Inversion** (models → services)
auskommt und überall dort greift, wo `full_clean` läuft.

## Betrachtete Alternativen

- **DB-Constraint (Exclusion Constraint / `btree_gist`):** sauberste Garantie, aber
  PostgreSQL-spezifisch, in SQLite (Dev/Test) nicht verfügbar und mit der bestehenden
  Zwei-DB-Teststrategie (ADR 0022) umständlich. `clean()` ist portabel und testbar.
- **Validierung nur in einer Admin-`ModelForm`:** verworfen – am Modell greift es für
  jeden `full_clean`-Pfad, nicht nur im aktuell registrierten Admin.
- **Admin für Buchungen entfernen / read-only:** erwogen (das Team nutzt ohnehin das
  `/verwaltung/`-Dashboard, ADR 0018), aber Admin/Superuser brauchen Korrektur-
  möglichkeiten. Regeln erzwingen schlägt „Werkzeug wegnehmen".
- **Mindestnächte/Saison/Budget ebenfalls im Admin erzwingen:** bewusst NICHT – diese
  Regeln sind kontextabhängig und für legitime Backend-Korrekturen (z.B. Importe,
  Kulanz) zu streng. `clean()` deckt nur die **integritätskritischen** Invarianten ab.

## Konsequenzen

**Positiv**
- Doppelbuchungen sind auch im Backend ausgeschlossen; eine Kern-Invariante gilt
  unabhängig vom Eingabeweg.
- Portabel (Postgres wie SQLite), durch Tests abgesichert (`AdminBuchungsregelnTests`).

**Negativ / Grenzen**
- Keine DB-Garantie auf Storage-Ebene: ein direkter `bulk_create`/SQL-Insert umgeht
  `clean()` weiterhin. Für „mit großer Kraft kommt große Verantwortung" (direkter
  DB-Zugriff) bleibt das akzeptiert; ein Exclusion-Constraint wäre die nächste Stufe.
- Nur `Allocation` ist abgedeckt. Analoge Absicherung von `ExternalBooking` im Admin
  ist ein möglicher Folge-Schritt.
