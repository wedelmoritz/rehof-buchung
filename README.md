# Re:Hof Quartier-Buchung

Buchungs- und Losverfahren für die Ferienquartiere der Genossenschaft – mit fairem
**Losverfahren**, Spontanbuchung, **Mitgliederverwaltung**, einem **Hofladen** mit
Rechnungen, **externen Gästen** und einem operativen Verwaltungs-Dashboard. Läuft als
Django-App per Docker (web + PostgreSQL) hinter Caddy auf einem Linux-VPS.

> **Status:** lauffähige Proof-of-Concept, mehrstufig getestet (reine Logik inkl.
> deterministischem Strategiesicherheits-Beweis · DB-Integration · Nebenläufigkeit ·
> End-to-End im Browser · Belastungstests). Backup & weiteres Hardening sind als
> Blueprint vorbereitet, aber noch nicht umgesetzt (siehe
> [`docs/BETRIEB-SICHERHEIT.md`](docs/BETRIEB-SICHERHEIT.md)).

Das Herzstück – das fachlich abgenommene **Losverfahren** – liegt als getestetes,
Django-freies Python-Modul vor; darum herum eine schlanke, server-gerenderte
Oberfläche, die als **PWA** auch mobil installierbar und teils offline nutzbar ist.

---

## Was es kann

**Für Mitglieder** (Web-App / PWA):

- **Übersicht** – Community-Kalender (wer ist wann wo) mit Umschalter Kalender/Belegung.
- **Buchen** – Ampel-Kalender, Spontanbuchung, **Warteliste**; zweistufig mit
  Bestätigung.
- **Wunschliste + faires Losverfahren** fürs Folgejahr (gewichtete Zufallsreihenfolge
  im Runden-Prinzip, Karma-Ausgleich, **nachgewiesene** Strategiesicherheit/Fairness).
- **Meine Buchungen** – Storno, **Buchung ändern** (Zeitraum/Unterkunft/Personen),
  **Wechselwunsch** an andere Mitglieder.
- **Tage übertragen** an andere Mitglieder (Typeahead-Suche).
- **Hofladen** – Warenkorb → Rechnung (PDF, §14) → **online bezahlen** (Mollie).
- **Profil**, **Benachrichtigungen** (In-App · E-Mail · optional **Web-Push**),
  installierbar & teils **offline**.

**Für externe Gäste:** öffentliche Buchung ohne Login per **Magic-Link**, inkl.
Online-Bezahlung – derselbe Rechnungs-/Zahlungsweg wie für Mitglieder.

**Für die Verwaltung:** zwei getrennte Rollen –

- **Verwaltung** (Gruppe) → operatives **Dashboard** (`/verwaltung/`): Reinigungsliste,
  anstehende Buchungen, Rechnungen mahnen, **Kontoabgleich**, Hofladen-Katalog,
  **Losung bestätigen/zurücknehmen** – mit Export (xlsx/CSV) und Versand per Knopf.
- **Admin** (Superuser) → volles **Backend** (`/admin/`, fachlich gegliedert) für
  Stammdaten, Buchungen und Losung.

**Im Betrieb:** Docker-Compose + Caddy (TLS), ein **Scheduler-Container** für die
periodischen Aufgaben (Losungen, Monatsrechnungen, E-Mail-Versand, DSGVO-Aufräumen),
**Observability** (strukturierte Logs, optional Sentry, Health-Endpoint `/healthz/`).

> Die **fachlichen Regeln** dahinter (Tagebudget, Saison-/Buchungsregeln,
> Losverfahren & Karma, Perioden-Lebenszyklus, USt, Aufbewahrungsfristen …) stehen
> gebündelt im **[Fachkonzept](docs/FACHKONZEPT.md)**.

---

## Schnellstart auf dem VPS

Voraussetzung: ein Linux-Server (Debian/Ubuntu), auf dem bereits **Caddy** läuft.
Docker/Compose/git installiert das Skript bei Bedarf.

```bash
git clone <repo-url> rehof && cd rehof

# 1) Voraussetzungen prüfen + .env mit Zufalls-Geheimnissen erzeugen
./install.sh

# 2) In .env die Domain eintragen:
#    ALLOWED_HOSTS=quartiere.deine-domain.de
#    CSRF_TRUSTED_ORIGINS=https://quartiere.deine-domain.de
#    PUBLIC_BASE_URL=https://quartiere.deine-domain.de

# 3) Stack bauen & starten (optional mit Demo-/Testdaten: --seed)
./install.sh --start

# 4) Admin-Konto anlegen
docker compose exec web python manage.py createsuperuser
```

Anschließend den Block aus [`caddy/Caddyfile.snippet`](caddy/Caddyfile.snippet) ins
Host-Caddyfile übernehmen (Domain anpassen) und `sudo systemctl reload caddy`. Caddy
terminiert TLS und proxyt im gemeinsamen Docker-Netz auf den `web`-Container (der
**keinen** Host-Port veröffentlicht).

➡️ **Die vollständige, schrittweise Anleitung** – alle Umgebungsvariablen, Web-Push/
VAPID, Monitoring-Anbindung, Mollie, Scheduler, Redis, Updates und Server-Umzug –
steht im **[Deployment-Runbook `docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**.

---

## Lokales Setup (Entwicklung, SQLite)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=config.settings DEBUG=1     # SQLite + gelockerte Sicherheit
python manage.py migrate
python manage.py seed_demo --reset                        # Demo-Daten + reale BB-Termine
python manage.py runserver
```

Demo-Login nach `--reset`: Benutzername z. B. `anna0`, Passwort `demo12345`. Ohne
`DATABASE_URL` nutzt Django SQLite (nur Dev/Test). Alternativ mit **uv**:
`uv sync --extra dev --extra test` (siehe [`docs/TESTEN.md`](docs/TESTEN.md)).

---

## Rollen

| Rolle | Zugang | Kann |
|---|---|---|
| **Mitglied** | Web-App | buchen, Wunschliste, eigene Buchungen/Rechnungen, Profil |
| **Verwaltung** | `/verwaltung/` (Gruppe „Verwaltung") | Dashboard: Listen, mahnen, Kontoabgleich, Losung bestätigen, Hofladen-Katalog – **kein** Backend |
| **Admin** | `/admin/` (Superuser) | volles Backend: Stammdaten, Buchungen, Losung |
| **Gast** (extern) | Magic-Link | eigene Buchung ansehen/stornieren/bezahlen, ohne Konto |

Eine Person wird zur **Verwaltung**, indem man sie im Backend der Gruppe
„Verwaltung" hinzufügt. Details in [Fachkonzept § 14](docs/FACHKONZEPT.md#14-rollen--rechte).

---

## Tests

Mehrstufig – schnelle reine Logik bis prod-nahe Browser-Tests:

```bash
# Reine Logik (ohne DB) – schnell
PYTHONPATH=. python -m pytest tests/ -q            # -> 68 passed

# Integration (DB-Ebene)
python manage.py test booking shop                 # -> 212 passed (3 skips)
```

Dazu kommen **Nebenläufigkeits-** (PostgreSQL), **End-to-End-** (Playwright gegen
einen prod-nahen Docker-Stack) und **Belastungstests** (k6). Alles – inkl. CI-Jobs
und Testdaten-Konten – ist im **[Test-Runbook `docs/TESTEN.md`](docs/TESTEN.md)**
beschrieben; das Belastungs-Runbook liegt in
[`loadtest/README.md`](loadtest/README.md).

---

## Dokumentation (Wegweiser)

| Thema | Dokument |
|---|---|
| **Fachliche Regeln** (Losverfahren, Tage, Saison, Perioden, USt, Aufbewahrung) | [`docs/FACHKONZEPT.md`](docs/FACHKONZEPT.md) |
| **Architektur-Entscheidungen** (technisch, mit Abwägungen) | [`docs/adr/`](docs/adr/README.md) |
| **Deployment & Betrieb** (VPS/Caddy/Docker, Env, Push, Monitoring) | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
| **Tests & Testumgebungen** | [`docs/TESTEN.md`](docs/TESTEN.md) |
| **Belastungstests (k6)** | [`loadtest/README.md`](loadtest/README.md) |
| **Externe Gäste** (Konzept) | [`docs/EXTERNE-GAESTE.md`](docs/EXTERNE-GAESTE.md) |
| **Backup & Härtung** (geplant) | [`docs/BETRIEB-SICHERHEIT.md`](docs/BETRIEB-SICHERHEIT.md) |
| **Datenschutz-Vorlage** | [`docs/DATENSCHUTZ-VORLAGE.md`](docs/DATENSCHUTZ-VORLAGE.md) |
| **Tester:innen einladen/Feedback** | [`docs/TESTER-EINLADUNG.md`](docs/TESTER-EINLADUNG.md) · [`docs/TESTER-FEEDBACK.md`](docs/TESTER-FEEDBACK.md) |
| **Code-Orientierung für Mitwirkende** | [`CLAUDE.md`](CLAUDE.md) |

---

## Projektstruktur (Kurzkarte)

```
booking/                # Kern-App: Buchung, Losung, Mitglieder, Dashboard
  lottery.py            #  reine Logik: Losverfahren (Django-frei, in tests/ testbar)
  availability.py rules.py validation.py   #  reine Logik: Zeit/Regeln/Eingaben
  services/             #  Service-Layer (Brücke DB ↔ Logik), fachlich aufgeteilt
  models.py views.py admin.py   #  Daten · dünne Views · Backend
  templates/  static/   #  server-gerenderte UI + PWA (Manifest/Service-Worker)
shop/                   # Hofladen: Produkte, Einkauf, Rechnung/PDF, Mollie, Bankimport
config/                 # settings.py, urls.py, wsgi/asgi
tests/                  # reine pytest-Suite (ohne Django/DB)
tests_e2e/              # Playwright-Smoke-Tests (gegen laufenden Stack)
loadtest/               # k6-Belastungstests (browse / booking_rush)
docs/                   # Fachkonzept, ADRs, Deployment, Tests, …
docker-compose.yml      # Prod-Stack (web + db + Scheduler, optional Redis)
caddy/Caddyfile.snippet # Reverse-Proxy-Block für den Host-Caddy
install.sh ops/         # Inbetriebnahme + Server-Umzug
```

Architektur-Prinzip (drei Schichten, strikt getrennt): **reine Logik** (`*.py`, ohne
Django) ↔ **Service-Layer** (`booking/services/`) ↔ **dünne Views/Templates**. Mehr
dazu in [ADR 0002](docs/adr/0002-drei-schichten-architektur.md) und
[`CLAUDE.md`](CLAUDE.md).

---

## Lizenz

**GNU AGPL v3** – siehe [`LICENSE`](LICENSE). Die App darf genutzt, verändert und
weitergegeben werden; wer sie (auch als gehosteten Webdienst) betreibt, muss den
Quellcode der eingesetzten Version zugänglich machen. So bleibt eine
Genossenschafts-Lösung dauerhaft offen.
