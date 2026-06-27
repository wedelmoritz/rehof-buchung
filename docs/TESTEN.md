# Testen – Runbook & Test-Umgebungen

Vollständige Test-Strategie der Re:Hof Quartier-Buchung und wie man jede Ebene
fährt – lokal wie in der CI. Geerdet im echten Repo (Pfade, Befehle und erwartete
Zahlen sind gegen die Dateien geprüft). Grundlage: ADR 0002 (Schicht-Trennung),
ADR 0022 (Zwei-Ebenen-Teststrategie + CI), ADR 0047 (E2E prod-naher Stack),
ADR 0048 (uv + mypy auf der reinen Logik).

---

## 1. Überblick – die Testpyramide

Von schnell+billig (unten) zu langsam+realistisch (oben):

1. **Reine Logik** (`pytest tests/`, **ohne DB**) – Losverfahren, Verfügbarkeit,
   Regeln, Validierung, Fairness, Beds24. Sekunden-Feedback.
2. **Integration** (`manage.py test booking shop`, **DB-Ebene**) – Service-Layer,
   Buchung, Losung-Workflow, Dashboard, Hofladen, Kontoabgleich.
3. **Nebenläufigkeit/Korrektheit** (`booking/tests_concurrency.py`) – beweist „genau
   EINE Buchung" beim gleichzeitigen Ansturm auf denselben Slot (Zeilensperre).
   Läuft nur gegen PostgreSQL (CI-Integrationsjob), auf SQLite übersprungen.
4. **End-to-End** (Playwright, `tests_e2e/`) – echte Browser-/Server-Naht (gunicorn,
   WhiteNoise, Cookies, JS) gegen einen **laufenden, prod-nahen** Docker-Stack.
5. **Belastung/Performance** (k6, `loadtest/`) – Lese-Last und Buchungs-Ansturm
   gegen die **Test-Instanz**, um Kapazität/Knick zu finden.

Querschnitt: **statischer Type-Check (mypy)** auf der Django-freien reinen Logik
(ADR 0048) – läuft im selben CI-Job wie die reine Logik.

Faustregel: Rechenregel → reine Logik-Test in `tests/`. Daten/Ablauf →
Integrationstest in `booking/tests.py` / `booking/tests_usecases.py`. Echte
Browser-Naht → E2E in `tests_e2e/`.

---

## 2. Reine Logik (pytest, ohne DB)

Django-frei, ohne Datenbank, in Sekunden durch.

```bash
PYTHONPATH=. python -m pytest tests/ -q
# erwartet: 68 passed
```

Abgedeckt (Module aus `tests/`):

- `test_lottery.py` – das Losverfahren: gewichtete Zufallsreihenfolge im
  Runden-Prinzip, Ausweich-Logik, Karma. Enthält den **Strategiesicherheits-Beweis**
  `test_strategieproof_ueber_alle_reihenfolgen` (muss bei jeder Algorithmus-Änderung
  grün bleiben).
- `test_availability.py` – Buchungszeiträume + Tage-Rechnung.
- `test_rules.py` – Mindestnächte / Parallel-Limit / Aufenthaltsdeckel.
- `test_validation.py` – Plausibilität der Eingaben (Name/PLZ/Ort/IBAN mod-97/E-Mail).
- `test_fairness.py` – Monte-Carlo-Fairness-Nachweis (`booking/fairness.py`).
- `test_beds24.py` – CSV-Parsen + Namensabgleich für die Beds24-Migration.

---

## 3. Integration (Django, DB-Ebene)

Service-Layer + Modelle gegen eine echte DB (lokal SQLite, in der CI PostgreSQL).

```bash
python manage.py test booking shop
# erwartet: 212 passed (3 skips)
```

Die 3 Skips sind u.a. die PostgreSQL-only Race-Tests (siehe Abschnitt 4) – auf
SQLite übersprungen. Test-Dateien:

- `booking/tests.py` – gezielte Einzelfälle (Gate, Buchung, Losung-Workflow,
  Stornierung/Übertragung, Dashboard).
- `booking/tests_usecases.py` – tiefe End-to-End-Szenarien (**hier neue Use-Cases
  ergänzen**).
- `shop/tests.py` – Geld-/Rechnungslogik (Checkout, Rechnung, USt, Kontoabgleich).

Vor dem Commit zusätzlich (wie im CI):

```bash
python manage.py check                       # Django-System-Check
python manage.py makemigrations --check       # keine fehlende Migration
```

---

## 4. Nebenläufigkeit / Korrektheit

`booking/tests_concurrency.py` beweist die zentrale Garantie der Spontanbuchung:
Buchen **20 Mitglieder gleichzeitig** denselben Slot, entsteht **genau EINE**
`Allocation` – die übrigen werden sauber abgewiesen (kein Crash, kein Doppel). Ein
zweiter Test sichert ab, dass die Sperre **nicht fälschlich** über verschiedene
Quartiere serialisiert (10 eigene Quartiere → alle 10 gelingen).

Tragende Mechanik: `SELECT … FOR UPDATE` auf der Quartier-Zeile in
`services.book_spontaneous` (in `transaction.atomic`). Der Test nutzt
`TransactionTestCase` + echte Threads (echte Verbindungen + COMMITs).

**Wichtig:** Läuft nur gegen **PostgreSQL** (CI-Integrationsjob). Auf **SQLite** ist
`SELECT FOR UPDATE` wirkungslos und Schreibzugriffe werden ohnehin serialisiert –
der Test **überspringt** sich dort selbst (`skipTest`). Lokal gezielt gegen
PostgreSQL:

```bash
DATABASE_URL=postgres://rehof:rehof@localhost:5432/rehof_test \
  python manage.py test booking.tests_concurrency
```

---

## 5. End-to-End (Playwright)

Smoke-Tests der kritischen Pfade gegen einen **laufenden** Stack (nicht die
Django-Test-DB). Decken die Naht ab, die `manage.py test` (in-process) nicht sieht:
gunicorn, WhiteNoise/Statics, Cookies, Redirects, clientseitiges JS. Bewusst wenige,
robuste Tests (`tests_e2e/test_smoke.py`): Health, Anmeldung (richtig/falsch),
Buchungs-Kalender lädt, Geld-Pfad Hofladen (Artikel → Kasse → Rechnung
`HL-JJJJ-MM-NNN`).

Lokal gegen einen bereits laufenden Stack (Dev-Server oder Docker):

```bash
pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest tests_e2e/ --base-url http://localhost:8000
```

- Basis-URL kommt über `--base-url` (Default-Konten erwartet `seed_demo --testdata`:
  `test`/`test12345`).
- `PW_EXECUTABLE_PATH` (optional): Pfad zu einem vorinstallierten Chromium, falls
  `playwright install` nicht laufen soll. Die Fixture startet zudem mit
  `--no-sandbox` (für Container/CI).

In der **CI** läuft das vollautomatisch über `docker-compose.ci.yml` (siehe Abschnitt
8/9): Stack bauen/starten → auf `/healthz/` warten → `seed_demo --testdata --yes` →
Browser installieren → Tests.

---

## 6. Belastungstests (k6) & Performance

Zwei k6-Szenarien (Lastgenerator vom Laptop) gegen die **Test-Instanz**:

- **`loadtest/browse.js` – Lese-Last ("Stöbern"):** viele Mitglieder browsen parallel
  Übersicht (`/`), Buchen-Kalender (`/buchen/`) und Meine Buchungen
  (`/meine-buchungen/`). Misst Query-/Session-Performance, ohne den Zustand zu ändern.
  Stufen bis 60 VUs; SLOs als `thresholds` (p95 Übersicht < 800 ms, Buchen < 1200 ms,
  Fehler < 2 %).
- **`loadtest/booking_rush.js` – Buchungs-Ansturm auf DENSELBEN Slot:** viele
  versuchen gleichzeitig dasselbe Quartier/Datum über die Bestätigungsseite
  (`/buchen/bestaetigen/`) zu buchen. Macht die heiße Stelle (Zeilensperre) sichtbar
  und misst Contention/Latenz/Fehlerrate (Stufen bis 150 VUs). **Korrektheit** wird
  danach am Server geprüft: genau eine `Allocation` für den Slot.

**Warum nur gegen die Test-Instanz** (`rehof.wedelparlow.de`, **nicht produktiv**):
der Ansturm **verändert Daten** (eine Buchung entsteht, ein Budget sinkt) und treibt
CPU/DB ans Limit – das gehört nicht auf das Live-System. **Vor jedem Lauf** frisch
seeden (Slot frei, Budgets zurück):

```bash
docker compose exec web python manage.py seed_demo --testdata --yes
```

Mitschneiden während des Laufs (zweites Terminal auf dem VPS):

```bash
docker stats                  # CPU/RAM von web (gunicorn) UND db live
docker compose logs -f web    # Timeouts/Fehler
```

> **Vollständiges Runbook** (Vorbereitung, k6-Aufrufe, Auswertung, SLO-Tabelle,
> Verbesserungshebel): [`../loadtest/README.md`](../loadtest/README.md).

---

## 7. Statischer Type-Check (mypy)

`mypy` prüft die **Django-freie reine Logik** – dort fängt der Type-Checker echte
Fehler statt Framework-Fehlalarme. Konfiguration in `pyproject.toml`
(`[tool.mypy]`, `files = …`): `booking/lottery|availability|rules|validation|external|
beds24|fairness.py`. Moderate Flags (`check_untyped_defs`, `no_implicit_optional`,
`warn_unused_ignores`).

```bash
pip install mypy
mypy
```

Läuft im CI-Job „Reine Logik" als **Pflicht-Gate** (kein Soft-Fail). Der Service-/
View-Layer ist bewusst (noch) nicht typgeprüft (ADR 0048).

---

## 8. Testumgebungen & Testdaten

### `seed_demo --testdata` – das große Test-Szenario

```bash
python manage.py seed_demo --testdata --yes
```

Kompletter Wipe (inkl. Superuser) → reproduzierbare Konten und Daten:

| Konto | Passwort | Rolle |
|---|---|---|
| `admin` | `admin12345` | Superuser – volles Backend `/admin/` |
| `verwaltung` | `verwaltung12345` | Gruppe „Verwaltung" (kein Staff) – nur Dashboard `/verwaltung/` |
| `test` | `test12345` | Mitglied |
| `anna0` … `anna49` | `demo12345` | 50 Mitglieder (für Last-/Browser-Tests) |

Plus: wilde Buchungen im laufenden Jahr, offene Wunsch-Losung mit Feiertags-Ballung,
offene Hofladen-Rechnungen (davon einige per Online-Zahldienst-Test beglichen),
externe Mo–Fr-Buchungen. **Die Losung wird bewusst NICHT gezogen** (das übernehmen
die Testenden). Deterministisch → Grundlage für E2E und Lasttests.

### Unterschied zu `seed_demo --reset` (Demo)

`--reset` legt nur die **Demo-Daten** + reale BB-Termine an (Login `anna0…` /
`demo12345`), für die lokale Entwicklung (siehe `CLAUDE.md` → „Lokales Setup"). Das
große Test-Szenario `--testdata` ist umfangreicher und legt zusätzlich die benannten
Test-Konten (`admin`/`verwaltung`/`test`) sowie Hofladen-/Externen-Daten an.

### Prod-nahe E2E-Umgebung (`docker-compose.ci.yml`)

Dieselbe Kette wie in Produktion: dasselbe Image (`build: .`), derselbe Entrypoint
(warte auf DB → `migrate` → gunicorn), `DEBUG=0`, echtes PostgreSQL. Unterschiede nur
fürs Testen: **kein Caddy/TLS** (direkt über `http://localhost:8000`), Port 8000 auf
den Host veröffentlicht, Secure-Cookie-Flags aus (gehören zum TLS-Edge). Health über
`/healthz/`. Lokal nachstellen:

```bash
docker compose -f docker-compose.ci.yml up -d --build
# warten bis /healthz/ "ok" meldet, dann:
docker compose -f docker-compose.ci.yml exec -T web \
  python manage.py seed_demo --testdata --yes
python -m pytest tests_e2e/ --base-url http://localhost:8000
docker compose -f docker-compose.ci.yml down -v
```

### Lokale Entwicklung mit uv (optional, ADR 0048)

`pyproject.toml` ist die Quelle für `uv`; `uv.lock` pinnt die Versionen. Das
Docker-Image installiert weiter aus `requirements.txt` (gleiche Pins – synchron
halten).

```bash
uv sync --extra dev --extra test     # legt .venv an (mypy, pytest, pytest-django)
uv run python manage.py test booking shop
```

---

## 9. Continuous Integration

`.github/workflows/tests.yml` – Auslöser: **Push** auf `main`/`master`,
**Pull Request** und manuell (`workflow_dispatch`). Vier Jobs, **parallel**:

1. **Reine Logik (pytest, ohne DB)** – `PYTHONPATH=. python -m pytest tests/ -v`,
   danach `mypy`. Sehr schnelles Grün/Rot für die Kernregeln.
2. **Integration (Django + PostgreSQL)** – PostgreSQL 16 als Service-Container,
   `manage.py check`, `makemigrations --check --dry-run`, dann
   `manage.py test booking shop -v2`. Hier laufen auch die Race-Tests aus
   `booking/tests_concurrency.py` (PostgreSQL → nicht übersprungen). Native Libs für
   WeasyPrint (Rechnungs-PDF) werden installiert.
3. **Migration auf befüllter Alt-DB (alt → neu)** – migriert auf den aktuellen Stand,
   legt Stammdaten + einen problematischen **Altstand** an (Booking auf `0015`/Shop
   auf `0002` zurück, zwei Perioden je Jahr + Cascade-Wunsch, abgerechnete Alt-Position
   ohne Einkauf), und migriert **vorwärts**. Fängt DB-spezifische Fehler, die ein
   frischer Testlauf NICHT sieht (Unique-Index auf Duplikaten, „pending trigger
   events"). Prüft danach das Ergebnis (genau 1 Periode für 2099, Einkauf nachgetragen).
4. **E2E (Playwright, prod-naher Docker-Stack)** – `docker-compose.ci.yml` bauen/
   starten, auf `/healthz/` warten, `seed_demo --testdata --yes`, Chromium
   installieren, `pytest tests_e2e/ --base-url http://localhost:8000 -v`; Server-Logs
   bei Fehler, Stack am Ende abräumen.

Das **grüne Häkchen** ist die Freigabe **vor dem Pull auf die VPS**: reine Logik,
DB-Integration inkl. Nebenläufigkeit, Migrations-Resilienz und die echte
Browser-/Server-Naht sind abgesichert.

---

## 10. Definition of Done

„Fertig" heißt:

- **Reine Logik grün:** `PYTHONPATH=. python -m pytest tests/ -q` → 68 passed.
- **Integration grün:** `python manage.py test booking shop` → 212 passed (3 skips).
- **Neue/geänderte Logik durch einen Test gedeckt** (Rechenregel → `tests/`;
  Daten/Ablauf → `booking/tests*.py`/`shop/tests.py`; Browser-Naht → `tests_e2e/`).
- **Keine fehlende Migration:** `python manage.py makemigrations --check` ist sauber.
- Bei reiner-Logik-Änderungen zusätzlich `mypy` grün.

---

## Siehe auch

- **Betrieb / Deploy / Server-Umzug:** [`DEPLOYMENT.md`](DEPLOYMENT.md) und
  [`BETRIEB-SICHERHEIT.md`](BETRIEB-SICHERHEIT.md).
- **Architektur-Entscheidungen:** [`adr/README.md`](adr/README.md) (insb. 0002, 0022,
  0047, 0048).
- **Fachliche Regeln:** [`FACHKONZEPT.md`](FACHKONZEPT.md).
- **Belastungstests im Detail:** [`../loadtest/README.md`](../loadtest/README.md).
