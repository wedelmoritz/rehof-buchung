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
  admin.py              # Admin: Mitglieder, Buchungsregeln, Perioden/Zeiträume, Losung-Aktion
  views.py / urls.py / forms.py
  templates/booking/    # base, overview, book, wishlist, result, transfer
  templates/registration/login.html
  tests.py              # Django-Integrationstests (DB-Ebene)
  management/commands/seed_demo.py   # Demo-Daten + reale BB-Termine
config/                 # settings.py, urls.py, wsgi.py, asgi.py
tests/                  # reine pytest-Suite (ohne Django/DB)
  test_lottery.py  test_availability.py  test_rules.py
```

Modelle in `models.py`: `EquivalenceClass`, `Quarter`, `Member`,
`BookingPeriod` (zusammengeführt: Jahres-Losung **und** buchbarer Zeitraum,
gesteuert über `status`), `Wish` (mit `submitted`/`submitted_at`), `Allocation`
(mit `persons`), `UpcomingAllocation` (Proxy für die Admin-Ansicht „Anstehende
Buchungen“), `LotteryRun`, `NightTransfer`, `WaitlistEntry` (Spontanbuchungs-
Warteliste), `Notification` (In-App-Benachrichtigung), `BookingPolicy`
(Regelwerk-Singleton mit `SeasonRule`/`SchoolHoliday` als Inlines), `SeasonRule`,
`SchoolHoliday`. (`BookingWindow` wurde in `BookingPeriod` aufgelöst.)

Frontend-Seiten (`booking/views.py`): `overview` (Community-Monatsübersicht,
farbcodiert je Mitglied mit Name + Personenzahl), `book` (Ampel-Kalender →
Personen/Barrierefrei oben einstellen, Anreise/Abreise klicken, passende
Quartiere buchen bzw. Warteliste; Eignung wird vorab angezeigt), `wishlist`
(Wünsche fürs Losverfahren), `my_bookings` (eigene Buchungen + Storno),
`transfer`. Wird ein Wartelisten-Zeitraum durch Storno frei, erzeugt
`services.notify_waitlist_if_free` eine `Notification` (E-Mail-Versand folgt
in einer späteren Stufe).

---

## Domänenregeln (NICHT versehentlich brechen)

- **Losverfahren:** gewichtete Zufallsreihenfolge im Runden-Prinzip
  (strategiesicher, über Seed reproduzierbar). Ausweichen auf gleichwertige
  Quartiere derselben `EquivalenceClass`. Karma: +0,1 pro echtem Verlust,
  Deckel 1,5, Reset auf 1,0 bei Gewinn eines umkämpften Slots. **Nur
  eingereichte Wünsche (`submitted=True`) nehmen teil.** Die Strategiesicherheit
  ist deterministisch getestet (`test_strategieproof_ueber_alle_reihenfolgen`) —
  bei Änderungen am Algorithmus muss dieser Test grün bleiben.
- **Buchungsperiode/Zeitraum (`BookingPeriod`):** Eine Periode durchläuft den
  Lebenszyklus über ihren `status`: `draft` (Entwurf) → `wishes_open` (Wunsch-
  Einträge freigegeben) → `lottery_ready` (zur Auslosung freigegeben) →
  `lottery_done` (Auslosung beendet) → `free_booking` (freie Bebuchbarkeit im
  Zeitraum) → `ended` (beendet); `suspended` (unterbrochen) sperrt vorläufig.
  Die **normale Buchung** ist nur in Perioden mit Status `free_booking` möglich
  und gilt für den Zeitraum `[start, end)`. Schnittmengen-Semantik bleibt: ein
  Tag ist buchbar, wenn eine globale `free_booking`-Periode (`applies_to_all`)
  ihn abdeckt UND (falls für das Quartier eine spezifische Periode existiert)
  auch diese. Spezifische Perioden können nur weiter einschränken. **Die Losung
  ist bewusst NICHT durch den Zeitraum begrenzt** (sie vergibt das Folgejahr im
  Voraus, bevor dessen Zeitraum auf `free_booking` steht).
- **Tage:** 50/Jahr je Mitglied, davon max. 25 über die Wunschliste. **Kein
  Übertrag ins Folgejahr** (Kontingent gilt je Kalenderjahr frisch). Tage sind
  **an andere Mitglieder übertragbar** (`NightTransfer`).
- **Saison-Regeln (`SeasonRule`):** **jährlich wiederkehrend** (Monat/Tag, ohne
  Jahr); je Zeitraum optional `min_nights`, `max_parallel_units` (gleichzeitige
  Wohneinheiten), `max_stay_nights` (Einheiten-Nächte-Deckel). Der Service
  materialisiert sie pro Jahr zu konkreten Daten (`services._materialized_seasons`,
  Helfer `availability.recurring_range`), die reine Logik in `rules.py` bleibt
  datumsbasiert. **Aktuell nur bei der normalen Buchung erzwungen, NICHT in der
  Losung** (offener Punkt, s.u.).
- **Schulferien (`SchoolHoliday`):** ebenfalls **jährlich wiederkehrend**;
  werden im Kalender angezeigt UND setzen, wenn aktiv und mit Regelfeldern
  versehen, im Zeitraum dieselben Regeln durch wie eine Saison-Regel (leere
  Regelfelder = nur Anzeige).
- **Quartiere (`Quarter`):** Merkmal `accessible` (barrierearm/-frei) und ein
  optionaler **jährlicher Buchbarkeitszeitraum** (`season_*_month/day`, leer =
  ganzjährig). Außerhalb der Quartier-Saison ist nicht buchbar (geprüft in
  `services.range_is_released`).

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
