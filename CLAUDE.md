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

Modelle in `models.py`: `EquivalenceClass`, `Quarter`, `Membership`
(„Mitglied"/Anteil = eine Vielleben-eG-Nummer + `kind` Voll/Teil +
Gesamt-Tagebudget), `Member` (Buchungs-Subjekt je Nutzer; Tage-/Wunsch-Budget =
**Summe** der `Share`-Anteile), `Share` (Through-Modell Nutzer↔Anteil mit festem
`night_budget`; ein Nutzer kann mehreren Anteilen angehören → Budgets summieren
sich, ganze Tage), `BookingPeriod` (zusammengeführt: Jahres-Losung **und**
buchbarer Zeitraum, gesteuert über `status`), `Wish` (mit `submitted`/`submitted_at`), `Allocation`
(mit `persons`), `UpcomingAllocation` (Proxy für die Admin-Ansicht „Anstehende
Buchungen“), `LotteryRun`, `NightTransfer`, `WaitlistEntry` (Spontanbuchungs-
Warteliste), `Notification` (In-App-Benachrichtigung), `SwapRequest`
(Quartier-Wechselwunsch zwischen Mitgliedern), `BookingPolicy`
(Regelwerk-Singleton mit `SeasonRule`/`SchoolHoliday` als Inlines), `SeasonRule`,
`SchoolHoliday`. (`BookingWindow` wurde in `BookingPeriod` aufgelöst.)

Frontend-Seiten (`booking/views.py`): `overview` (Community-Monatsübersicht,
farbcodiert je Mitglied mit Name + Personenzahl; Klick auf einen Tag zeigt
unten, wer da ist und was noch frei ist), `book` (Ampel-Kalender → Personen/
Barrierefrei oben einstellen, Anreise/Abreise klicken oder Datum direkt
eingeben – auch über Monatsgrenzen –, passende Quartiere wählen bzw. Warteliste;
Eignung und Mindestaufenthalt werden vorab angezeigt), `book_confirm`
(**Bestätigungsschritt**: Unterkunft/Zeitraum prüfen, Personen + Begleitung
angeben, verbleibende Tage sehen, optional Endreinigung mitbuchen – erst
„Verbindlich buchen“ legt die `Allocation` an; gewählte Dienstleistungen werden
als offene Hofladen-Position erfasst), `wishlist` (Wünsche fürs Losverfahren –
bleiben bewusst änderbar), `my_bookings` (eigene Buchungen + Storno **mit
Rückfrage**; je Buchung „wer ist gleichzeitig da“ + Wechselwunsch an andere
Mitglieder, die zustimmen/ablehnen können), `transfer` (**zweistufig**: Vorschau
mit Empfänger – Anzeigename/Benutzername/Name – und Disclaimer, dass die Basis
des Übertrags privatrechtlich zu regeln ist, dann „verbindlich übertragen“).
Mitbuchbare Dienstleistungen sind `Product` mit `book_with_stay=True`;
`unavailable_weekdays` sperrt Wochentage (geprüft am Abreisetag, z.B.
Endreinigung am Wochenende). Wird ein Wartelisten-Zeitraum durch Storno frei, erzeugt
`services.notify_waitlist_if_free` eine `Notification` (E-Mail-Versand folgt
in einer späteren Stufe). Profil-/Rechnungsdaten (Name, Anschrift, IBAN) pflegt
das Mitglied selbst unter `profile`. Eine `help`-Seite erklärt Abläufe und die
Auslosung im Detail (verlinkt aus Übersicht/Wunschliste). **Verwaltung
vereinfacht:** ein Benutzer trägt Login **und** Mitglieds-Profil in einem
Formular (Member als Inline am `User`-Admin); `Member` ist aus dem Index
ausgeblendet (nur Autocomplete). Tage-Anteile werden am `Membership` zugeordnet.
Alle Admin-Bereiche tragen erklärende `description`-Texte.

**PWA / Mobil:** Die Web-App ist installierbar (iOS „Zum Home-Bildschirm“,
Android) und offline-fähig: Manifest (`booking/static/booking/manifest.webmanifest`),
Re:Hof-Logo/Icons (`booking/static/booking/icons/`), Service Worker (`/sw.js`,
Template `booking/sw.js`, Root-Scope) mit network-first + Offline-Fallback
(`/offline/`). Registrierung am Ende von `base.html`. Das Layout ist responsiv
(Media-Query in `base.html`, Nav als Scroll-Leiste, Eingaben volle Breite,
breite Datentabellen in `.table-wrap` → horizontal scrollbar statt überstehend,
iOS-Safe-Area). `sw`/`offline` sind von der Aktivierungs-Sperre ausgenommen
(das Manifest liegt unter `/static/` und ist damit ohnehin frei).

**Hofladen (eigene App `shop`, selber Admin/Webapp/Login):** Produktkatalog
(`ProductGroup`/`Product`; Dienstleistungen wie Sauna = `Product` mit
`kind="dienstleistung"` + `needs_date`), Einkauf mit **Preis-Snapshot**
(`LineItem`; offen = ohne `invoice`), monatliche Sammelrechnung (`Invoice`,
Nummer `HL-JJJJ-MM-NNN`, Status offen→bezahlt-gemeldet→bestätigt/archiviert,
§14-Angaben + Steuer-Aufschlüsselung). Stammdaten der Genossenschaft im
`ShopConfig`-Singleton. Geldlogik/Tests in `shop/services.py` bzw. `shop/tests.py`
(Preis-Snapshot, Rechnung, Zugriffsrechte). **Cron:** `generate_monthly_invoices`
(monatlich) und `run_due_lotteries` (terminierte Losungen). Rechnung zunächst als
In-App-HTML, PDF/Mail später.

---

## Domänenregeln (NICHT versehentlich brechen)

- **Losverfahren:** gewichtete Zufallsreihenfolge im Runden-Prinzip
  (strategiesicher, über Seed reproduzierbar). Ausweichen auf gleichwertige
  Quartiere derselben `EquivalenceClass`. Karma: +0,1 pro echtem Verlust,
  Deckel 1,5, Reset auf 1,0 bei Gewinn eines umkämpften Slots. **Nur
  eingereichte Wünsche (`submitted=True`) nehmen teil.** Die Strategiesicherheit
  ist deterministisch getestet (`test_strategieproof_ueber_alle_reihenfolgen`) —
  bei Änderungen am Algorithmus muss dieser Test grün bleiben. Die Losung lässt
  sich über `BookingPeriod.draw_at` terminieren; das Kommando
  `run_due_lotteries` (per Cron) führt fällige Losungen automatisch aus.
- **Buchungsperiode/Zeitraum (`BookingPeriod`):** **Pro Buchungsjahr genau EINE
  Periode** (`target_year` ist eindeutig). Sie durchläuft den Lebenszyklus über
  ihren `status`: `draft` (Entwurf) → `wishes_open` (Wunsch-Einträge freigegeben)
  → `lottery_ready` (zur Auslosung freigegeben) → `lottery_done` (Auslosung
  beendet) → `free_booking` (freie Bebuchbarkeit im Zeitraum) → `ended`
  (beendet); `suspended` (unterbrochen) sperrt vorläufig. Der Status wird
  normalerweise **aus den Terminen abgeleitet** (`BookingPeriod.compute_status`)
  und vom Cron-Kommando `run_due_lotteries` **vorwärts** geschaltet (nie zurück)
  — inkl. der fälligen Auslosung. Termine: `wishlist_open/close` (Wünsche),
  `draw_at` (Losung), `start/end` (buchbar ab/bis; `start` darf vor dem 1.1.
  liegen). Die **normale Buchung** ist nur im Status `free_booking` möglich und
  gilt für `[start, end)`. **Quartiersspezifische Grenzen** gibt es NICHT mehr
  über eigene Perioden, sondern nur über die **Quartier-Saison**
  (`Quarter.season_*`). **Die Losung ist bewusst NICHT durch den Zeitraum
  begrenzt** (sie vergibt das Folgejahr im Voraus, bevor dessen Zeitraum auf
  `free_booking` steht).
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
Tests (ohne DB), Job 2 die Integrationstests gegen echtes PostgreSQL, Job 3
**Migrations-Resilienz**: migriert eine **befüllte Alt-DB** (Booking auf 0015
zurück, Duplikate + Cascade-Wunsch erzeugen) vorwärts — fängt DB-spezifische
Migrationsfehler (Unique auf Duplikaten, „pending trigger events"), die ein
frischer Testlauf NICHT sieht. Vor dem Pull auf die VPS am grünen Häkchen
erkennbar, ob alles passt.

**Betrieb:** `docker-compose.yml` hat einen **Healthcheck** am `web`-Container
(scheitert, wenn Gunicorn nicht antwortet, z.B. nach Migrations-Abbruch →
`docker compose ps` zeigt „unhealthy" statt nur 502 bei Caddy). **Optionales
Redis** (Cache/Sessions/Axes-Lockout) ist über `REDIS_URL` + Profil `cache`
zuschaltbar (`docker compose --profile cache up -d`); Standard bleibt DB-Sessions.

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
der Web-Container bindet nur an `127.0.0.1`.

**Auth & Zugang:** Login per **E-Mail oder Benutzername**
(`booking/auth.py::EmailOrUsernameModelBackend`), Brute-Force-Schutz über
**django-axes** (Sperre nach 5 Fehlversuchen je Benutzer+IP, 1 h; Settings im
Axes-Block). Nutzer können sich **selbst registrieren** (`register` →
`registration/register.html`); dabei entsteht NUR ein Login-Konto. Bis die
Verwaltung ein **Mitglieds-Profil** (`Member`) zuordnet, sperrt
`booking/middleware.py::ActivationGateMiddleware` alles und leitet auf die
Warte-Seite `pending` um (Verwaltungs-/Superuser ausgenommen). Cookies/Sessions
sind gehärtet (HttpOnly, SameSite=Lax, Secure in Prod). OIDC/Keycloak-Naht
bleibt in `settings.py` markiert.

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
