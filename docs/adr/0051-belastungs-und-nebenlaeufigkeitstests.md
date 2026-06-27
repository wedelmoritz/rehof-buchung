# 0051 – Belastungs- und Nebenläufigkeitstests (k6 + Zeilensperren-Test)

## Status

Accepted (2026-06-27)

## Kontext

Die Zwei-Ebenen-Teststrategie (ADR 0022) und die E2E-Tests (ADR 0047) sichern
**Korrektheit** und **kritische Pfade** ab, sagen aber nichts über **Verhalten unter
Last** und **Gleichzeitigkeit**. Die fachlich heikelste Stelle ist der **Ansturm
mehrerer Mitglieder auf denselben freien Slot** (z.B. wenn ein begehrter Zeitraum
spontan frei wird, § 10 / § 5 im Fachkonzept): Es darf **niemals** zu einer
Doppelbuchung kommen, und die Antwortzeiten sollen auch unter Last tragbar bleiben.
Das ist mit funktionalen Tests allein nicht nachweisbar.

## Entscheidung

Zwei sich ergänzende Ebenen, bewusst getrennt von der funktionalen Suite:

1. **Korrektheit unter Gleichzeitigkeit (ohne Lastgenerator):**
   `booking/tests_concurrency.py` (`TransactionTestCase`, echte Threads + `Barrier`)
   beweist, dass bei vielen **gleichzeitigen** Buchungen desselben Slots **genau eine**
   Buchung entsteht – die Absicherung der Zeilensperre aus ADR 0013. Läuft im
   **CI-PostgreSQL-Job**; auf SQLite wird er **übersprungen** (dort greifen keine
   echten `SELECT … FOR UPDATE`-Zeilensperren).

2. **Performance/Kapazität (HTTP-Last mit [k6](https://k6.io)):** ein kleines Runbook
   `loadtest/` mit zwei Szenarien gegen die **Test-Instanz** (nie produktiv):
   - `browse.js` – **Lese-Last** (viele lesen parallel Übersicht/Buchen/Meine
     Buchungen): misst Query-Performance.
   - `booking_rush.js` – **Buchungs-Ansturm** auf **denselben** Slot: misst Contention
     und Latenz an der Zeilensperre.
   Vor jedem Lauf wird der Stand frisch gesetzt (`seed_demo --testdata --yes`).
   Mitschneiden auf dem Server mit `docker stats` und `docker compose logs -f web`;
   für die langsamsten Statements optional `pg_stat_statements`.

k6 bleibt **bewusst außerhalb** von Repo-Abhängigkeiten und CI: Last erzeugt man vom
Laptop gegen eine separate Test-Instanz, nicht im CI-Runner (irreführende Zahlen,
keine prod-nahe Hardware). Das vollständige Vorgehen steht in
[`loadtest/README.md`](../../loadtest/README.md), die Test-Ebenen im Überblick in
[`docs/TESTEN.md`](../TESTEN.md).

## Betrachtete Alternativen

- **Last im CI fahren:** verworfen – CI-Runner sind nicht prod-nah (CPU/IO geteilt),
  die Zahlen wären nicht aussagekräftig und der Lauf langsam/teuer. Nur die
  *Korrektheit* unter Gleichzeitigkeit gehört in die CI (Job 2, PostgreSQL).
- **Locust statt k6:** beide tauglich; k6 gewählt wegen schlanker, skriptbarer
  JS-Szenarien ohne Python-Abhängigkeit im Repo und guter Kennzahlen-Ausgabe.
- **Nur ein synthetischer Korrektheitstest, keine HTTP-Last:** verworfen – der
  Zeilensperren-Test beweist *Korrektheit*, nicht *Kapazität*; den Latenz-/Durchsatz-
  Knick findet man nur mit echter HTTP-Last.
- **Gegen die Produktion testen:** ausgeschlossen – Last nur gegen eine separate
  Test-Instanz mit Testdaten.

## Konsequenzen

**Positiv**
- Die kritische „genau-eine-Buchung"-Garantie ist automatisiert abgesichert (CI).
- Performance-Engpässe (heiße Zeilensperre) sind reproduzierbar messbar, bevor reale
  Mitglieder sie treffen.

**Negativ / Grenzen**
- k6-Läufe sind **manuell** (kein CI-Gate) und brauchen eine separate Test-Instanz
  sowie frisches Seeding vor jedem Lauf.
- Der Concurrency-Test braucht **PostgreSQL**; lokal auf SQLite ist er nur ein Skip,
  die Absicherung greift also erst in der CI bzw. gegen Postgres.
