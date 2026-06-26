# Belastungstests – Runbook

Zwei sich ergänzende Ebenen:

1. **Korrektheit unter Gleichzeitigkeit** (ohne Lastgenerator) – beweist, dass bei
   vielen gleichzeitigen Buchungen desselben Slots **genau eine** Buchung entsteht.
   Liegt als Repo-Test vor: `booking/tests_concurrency.py` (läuft im CI-PostgreSQL-Job;
   lokal auf SQLite übersprungen, weil dort keine echten Zeilensperren greifen).
   ```bash
   DATABASE_URL=postgres://… python manage.py test booking.tests_concurrency
   ```

2. **Performance/Kapazität** (HTTP-Last mit **k6** vom Laptop gegen die Test-Instanz)
   – findet den Latenz-/Durchsatz-Knick und die heiße Stelle (Zeilensperre).

> Nur gegen die **Test-Instanz** (`rehof.wedelparlow.de`, nicht produktiv) fahren.

---

## 1. Vorbereitung

- **k6 installieren** (Laptop): siehe https://k6.io/docs (z. B. `brew install k6`,
  `winget install k6`, oder Paketmanager unter Linux).
- **Testdaten auf dem Server frisch setzen** (Slot frei, Budgets zurück, 50 Mitglieder
  `anna0…`/`demo12345`):
  ```bash
  docker compose exec web python manage.py seed_demo --testdata --yes
  ```
- **Einen freien Slot heraussuchen** für den Ansturm: auf der Seite *Buchen* einen
  freien Zeitraum wählen → die „Bestätigen“-URL enthält `?quarter=<ID>&start=…&end=…`.
  Diese `QUARTER_ID`, `START`, `END` unten einsetzen.

## 2. Lese-Last ("Stöbern")

Viele lesen parallel Übersicht/Buchen/Meine Buchungen – misst Query-Performance.
```bash
k6 run -e BASE_URL=https://rehof.wedelparlow.de -e PASS=demo12345 \
       -e MEMBERS=50 loadtest/browse.js
```

## 3. Buchungs-Ansturm auf denselben Slot (Kern-Szenario)

Viele versuchen **gleichzeitig dasselbe** Quartier/Datum – misst Contention + Latenz.
```bash
k6 run -e BASE_URL=https://rehof.wedelparlow.de -e PASS=demo12345 -e MEMBERS=50 \
       -e QUARTER_ID=1 -e START=2026-08-10 -e END=2026-08-14 \
       loadtest/booking_rush.js
```
**Vor jedem Lauf neu seeden** (Schritt 1), sonst ist der Slot schon belegt.

## 4. Mitschneiden auf dem Server (während des Laufs)

In einem zweiten Terminal auf dem VPS:
```bash
docker stats                     # CPU/RAM von web (gunicorn) UND db live
docker compose logs -f web       # Timeouts/Fehler (gunicorn timeout=60s)
```
PostgreSQL – langsamste Statements (einmalig Extension aktivieren):
```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;   -- in der App-DB
SELECT calls, round(mean_exec_time::numeric,1) AS ms_avg,
       round(total_exec_time::numeric,1) AS ms_total, left(query,80) AS q
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 15;
-- vor einem Lauf: SELECT pg_stat_statements_reset();
```

## 5. Auswertung

- **Korrektheit (wichtig!):** Nach dem Ansturm auf dem Server prüfen, dass für den
  Slot **genau eine** Buchung existiert (keine Doppelbuchung trotz HTTP-Parallelität):
  ```bash
  docker compose exec web python manage.py shell -c \
    "from booking.models import Allocation; from datetime import date; \
     print(Allocation.objects.filter(quarter_id=1, start=date(2026,8,10)).count())"
  # erwartet: 1
  ```
- **Performance:** k6 zeigt am Ende `http_req_duration` (p95/p99), `http_req_failed`
  und die Custom-Metriken (`t_book`, `book_conflict`). Den **Knick** suchen: ab welcher
  VU-Zahl steigen p95/p99 und Fehlerrate stark? Das ist die praktische Kapazität.
- **App- vs. Generator-Limit unterscheiden:** Wenn auf dem VPS `web` die CPU sättigt →
  App am Limit. Bleibt der VPS entspannt und nur dein Laptop/Upload ist am Anschlag →
  Generator-/Netzlimit (dann Stufen kleiner wählen).

## 6. SLOs (Vorschlag – in den Skripten als `thresholds` justierbar)

| Kennzahl | Ziel |
|---|---|
| Doppelbuchungen unter Contention | **0** |
| Fehlerrate (HTTP) im Normalbereich | < 2 % |
| p95 Übersicht/Buchen (leselastig) | < 0,8 s / 1,2 s |
| p95 Buchung unter Ansturm | < 2 s (p99 < 5 s) |

## 7. Erkenntnis → Verbesserungshebel

| Beobachtung | Hebel |
|---|---|
| Latenz steigt schon bei wenigen VUs, `web`-CPU < 100 % | **gunicorn-Worker erhöhen** (`GUNICORN_WORKERS`, Default **3**; Faustregel 2–4 × Kerne) |
| Viel Zeit in Session-/Wiederholungs-Queries | **Redis** für Sessions/Cache zuschalten (`docker compose --profile cache up -d`, `REDIS_URL` setzen) |
| Einzelne Statements dominieren `pg_stat_statements` | Index / `select_related`/`prefetch` (wie Dashboard 85→17 Queries) |
| Lange Sperr-Wartezeiten auf heißem Slot | Transaktion kurz halten; klares „jemand war schneller“-UX; ggf. Retry |
| Losung blockiert Web-Worker | Losdurchlauf in Scheduler/Hintergrund, Parameter deckeln |
| DB-Verbindungen werden knapp | `CONN_MAX_AGE` ist gesetzt; bei vielen Workern **PgBouncer** erwägen |

## Hinweise

- **django-axes** sperrt nach 5 **fehlgeschlagenen** Logins (User+IP) für 1 h. Die
  Skripte loggen je VU nur **einmal** mit korrekten Demo-Daten ein – keine Lockouts,
  solange Benutzernamen/Passwort stimmen (`USER_PREFIX`, `PASS`).
- Der Ansturm **verändert Daten** (eine Buchung entsteht, ein Budget sinkt) → vor jedem
  Lauf neu seeden.
- Klein anfangen (Stages reduzieren), dann hochdrehen – so findest du den Knick, ohne
  die Test-Instanz unnötig zu quälen.
