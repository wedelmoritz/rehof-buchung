# CLAUDE.md — Re:Hof Quartier-Buchung

Diese Datei orientiert Claude Code beim Start. Ziel: **gezielt an der richtigen
Stelle ändern, nie das Projekt neu bauen.** Bitte vor jeder Änderung kurz lesen.

---

## Was das ist

Django-App für die faire Buchung der Genossenschafts-Quartiere mit Losverfahren,
Spontanbuchung, Mitgliedermanagement und einem Mitglieder-Kalender. Läuft per
Docker (web + PostgreSQL) hinter Caddy auf einem Hetzner-VPS.

---

## Architektur-Prinzip (WICHTIG — bestimmt, wo geändert wird)

Drei Schichten, strikt getrennt:

1. **Reine Logik (kein Django-Import!):**
   - `booking/lottery.py` — der Losalgorithmus (gewichtete Zufallsreihenfolge im
     Runden-Prinzip, Ausweich-Logik, Karma).
   - `booking/availability.py` — freigeschaltete Buchungszeiträume + Tage-Rechnung.
   - `booking/rules.py` — Mindestnächte / Parallel-Limit / Aufenthaltsdeckel.
   Diese Module sind isoliert mit `pytest` testbar. **Hier ändern, wenn es um
   Rechenregeln geht** — und immer den passenden Test in `tests/` mitziehen.

2. **Service-Layer:** `booking/services.py` — die EINZIGE Brücke zwischen DB
   (Django-Modelle) und reiner Logik. Persistenz, Verfügbarkeit, Buchung,
   Stornierung, Übertragung, Kalenderaufbau, Losungs-Durchführung.
   **Hier ändern, wenn es um Datenbank-/Ablauf-Logik geht.**

3. **Views/Templates:** `booking/views.py` (dünn, nur Dispatch), `*/templates/`.
   **Hier ändern, wenn es um UI/Darstellung geht.**

Faustregel: Rechenregel → `*.py`-Modul + pure Test. Daten/Ablauf → `services.py`.
Darstellung → View/Template. Selten sind mehr als 2–3 Dateien betroffen.

---

## Dateistruktur (Kurzkarte)

```
booking/
  lottery.py            # reine Logik: Losverfahren
  availability.py       # reine Logik: Buchungszeiträume + Tage
  rules.py              # reine Logik: Mindestnächte/Parallel/Deckel
  services.py           # Brücke DB <-> Logik (gesamte Geschäftslogik)
  models.py             # alle Datenmodelle (siehe unten)
  admin.py              # Admin: Mitglieder, Regeln, Fenster, Losung-Aktion
  views.py / urls.py / forms.py
  templates/booking/    # base, dashboard, calendar, result, transfer
  templates/registration/login.html
  tests.py              # Django-Integrationstests (DB-Ebene)
  management/commands/seed_demo.py   # Demo-Daten + reale BB-Termine
config/                 # settings.py, urls.py, wsgi.py, asgi.py
tests/                  # reine pytest-Suite (ohne Django/DB)
  test_lottery.py  test_availability.py  test_rules.py
```

Modelle in `models.py`: `EquivalenceClass`, `Quarter`, `Member`,
`BookingPeriod`, `Wish` (mit `submitted`/`submitted_at`), `Allocation`,
`LotteryRun`, `BookingWindow`, `NightTransfer`, `BookingPolicy`, `SeasonRule`,
`SchoolHoliday`.

---

## Domänenregeln (NICHT versehentlich brechen)

- **Losverfahren:** gewichtete Zufallsreihenfolge im Runden-Prinzip
  (strategiesicher, über Seed reproduzierbar). Ausweichen auf gleichwertige
  Quartiere derselben `EquivalenceClass`. Karma: +0,1 pro echtem Verlust,
  Deckel 1,5, Reset auf 1,0 bei Gewinn eines umkämpften Slots. **Nur
  eingereichte Wünsche (`submitted=True`) nehmen teil.** Die Strategiesicherheit
  ist deterministisch getestet (`test_strategieproof_ueber_alle_reihenfolgen`) —
  bei Änderungen am Algorithmus muss dieser Test grün bleiben.
- **Buchungszeiträume (`BookingWindow`):** Schnittmengen-Semantik. Buchbar ist
  ein Tag nur, wenn ein aktives **globales** Fenster ihn abdeckt UND (falls für
  das Quartier ein **spezifisches** Fenster existiert) auch dieses. Spezifische
  Fenster können nur weiter einschränken. **Die Losung ist bewusst NICHT durch
  Fenster begrenzt** (sie vergibt das Folgejahr im Voraus).
- **Tage:** 50/Jahr je Mitglied, davon max. 25 über die Wunschliste. **Kein
  Übertrag ins Folgejahr** (Kontingent gilt je Kalenderjahr frisch). Tage sind
  **an andere Mitglieder übertragbar** (`NightTransfer`).
- **Saison-Regeln (`SeasonRule`):** je Zeitraum optional `min_nights`,
  `max_parallel_units` (gleichzeitige Wohneinheiten), `max_stay_nights`
  (Einheiten-Nächte-Deckel, z.B. Sommerferien = 14). Geprüft in `services.
  book_spontaneous` über `rules.validate_booking`. **Aktuell nur bei der
  normalen Buchung erzwungen, NICHT in der Losung** (offener Punkt, s.u.).
- **Schulferien (`SchoolHoliday`):** rein informativ (Kalender-Anzeige, Berlin),
  ohne Einfluss auf die Buchungsregeln.

---

## Tests (nach JEDER Änderung laufen lassen)

```bash
# 1) Reine Logik (schnell, ohne DB) — erwartet: 41 passed
PYTHONPATH=. python -m pytest tests/ -q

# 2) Integrationstests inkl. Use-Cases (DB-Ebene) — erwartet: 31 passed
python manage.py test booking
```

Die Integrationstests liegen in `booking/tests.py` (gezielte Einzelfälle) und
`booking/tests_usecases.py` (tiefgreifende End-to-End-Szenarien — **hier neue
Use-Cases ergänzen**). „Fertig" heißt: beide Suiten grün, neue/­geänderte Logik
durch einen Test abgedeckt, `python manage.py makemigrations --check` zeigt keine
fehlende Migration.

**CI:** `.github/workflows/tests.yml` läuft bei jedem Push/PR — Job 1 die reinen
Tests (ohne DB), Job 2 die Integrationstests gegen echtes PostgreSQL. Vor dem
Pull auf die VPS am grünen Häkchen erkennbar, ob alles passt.

---

## Lokales Setup (Entwicklung, SQLite)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # ggf. --break-system-packages
export DJANGO_SETTINGS_MODULE=config.settings
export DEBUG=1                            # SQLite + gelockerte Sicherheit
python manage.py migrate
python manage.py seed_demo --reset        # Demo-Daten + reale BB-Termine
python manage.py runserver
```

Ohne `DATABASE_URL` nutzt `settings.py` SQLite (Dev/Test). In Produktion setzt
`docker-compose.yml` `DATABASE_URL` auf PostgreSQL; TLS macht Caddy auf dem Host,
der Web-Container bindet nur an `127.0.0.1`. Auth ist Standard-Django mit
markierter OIDC/Keycloak-Naht in `settings.py`.

---

## Konventionen

- **Sprache:** Deutsch — Antworten, Commit-Messages, Code-Kommentare, UI-Texte.
- **Änderungen:** gezielte Diffs, keine Rewrites. Nur anfassen, was nötig ist.
- **Vor inhaltlichen Entscheidungen** (Regel-Semantik, Werte wie Karma-Schritt,
  Äquivalenzklassen, Texte) kurz rückfragen statt raten.
- **Migrations** bei Modelländerungen immer miterzeugen und committen.
- **Keine Geheimnisse** ins Repo (`.env` ist gitignored; `SECRET_KEY`/DB-Passwort
  erzeugt `install.sh`).
- Reine Logik bleibt Django-frei, damit `tests/` ohne DB lauffähig bleibt.

---

## Offene Punkte / Roadmap (Kandidaten für Change-Requests)

- Saison-Regeln (Parallel-Limit/Deckel) **auch in der Losung** erzwingen —
  `rules.py` ist dafür bereits entkoppelt; Einhängepunkt wäre `services.
  run_period_lottery` bzw. `lottery.run_lottery`.
- Dienste & Waren (Endreinigung, Sauna) als buchbare Posten.
- Externe Buchungen sicher ausbauen (Modell-Flag `Member.is_external`,
  `Allocation.source="external"` vorhanden).
- E-Mail-Benachrichtigungen (Anmeldeschluss, Losergebnis).
- Drag-and-Drop der Wunschliste auf Touch-Geräten (Pfeiltasten sind Fallback).

---

## Typischer Arbeitsablauf für Claude Code

1. Branch anlegen (`git checkout -b fix/...` bzw. `feat/...`).
2. Bei Bugs zuerst einen **reproduzierenden Test** schreiben, dann minimal fixen.
3. Beide Test-Suiten grün machen.
4. Klein und nachvollziehbar committen (deutsche Commit-Message).
