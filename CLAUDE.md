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
                        #  (Backend-Startseite mit Erklär-Panel: templates/admin/custom_index.html,
                        #   gesetzt über admin.site.index_template)
  views.py / urls.py / forms.py
  templates/booking/    # base, overview, book, wishlist, result, transfer
  templates/registration/login.html
  tests.py              # Django-Integrationstests (DB-Ebene)
  management/commands/seed_demo.py   # Demo-Daten + reale BB-Termine
config/                 # settings.py, urls.py, wsgi.py, asgi.py
tests/                  # reine pytest-Suite (ohne Django/DB)
  test_lottery.py  test_availability.py  test_rules.py
```

Modelle in `models.py`: `EquivalenceClass`, `Quarter` (+ `QuarterPrice` =
saisonale Übernachtungspreise für Externe), `Membership`
(„Mitglied"/Anteil = eine Vielleben-eG-Nummer + `kind` Voll/Teil +
Gesamt-Tagebudget), `Member` (Buchungs-Subjekt je Nutzer; Tage-/Wunsch-Budget =
**Summe** der `Share`-Anteile), `Share` (Through-Modell Nutzer↔Anteil mit festem
`night_budget`; ein Nutzer kann mehreren Anteilen angehören → Budgets summieren
sich, ganze Tage), `BookingPeriod` (zusammengeführt: Jahres-Losung **und**
buchbarer Zeitraum, gesteuert über `status`), `Wish` (mit `submitted`/`submitted_at`), `Allocation`
(mit `persons`), `UpcomingAllocation` (Proxy für die Admin-Ansicht „Anstehende
Buchungen“), `LotteryRun`, `NightTransfer`, `WaitlistEntry` (Spontanbuchungs-
Warteliste), `Notification` (In-App-Benachrichtigung), `OutboxEmail`
(E-Mail-Warteschlange), `OpsConfig` (Betriebs-Einstellungen-Singleton:
Empfänger der Verwaltungs-Mails + Reinigungsliste, Monats-Mail-Tag),
`SwapRequest` (Quartier-Wechselwunsch zwischen Mitgliedern), `BookingPolicy`
(Regelwerk-Singleton mit `SeasonRule`/`SchoolHoliday` als Inlines), `SeasonRule`,
`SchoolHoliday`. (`BookingWindow` wurde in `BookingPeriod` aufgelöst.)
**Externe Gäste** (`docs/EXTERNE-GAESTE.md`): `Guest` (Bucher ohne Login, mit
`token` für den Magic-Link), `ExternalConfig` (Singleton: Regeln Mo–Do/
Mindestnächte/Vorlauf, Reinigung, USt **+ Anzahlung `deposit_percent`, Storno-
Staffel `free/partial_cancel_days`+`partial_refund_percent`, `late_fee`, `terms`**),
`ExternalBooking` (Reservierung; blockiert die Verfügbarkeit; verknüpft mit einer
`shop.Invoice`). `Quarter` hat `external_bookable`/`price_per_night`; **saisonale
Preise** über `QuarterPrice` (jährlich wiederkehrende Staffel, `Quarter.price_for_night(day)`
greift sie pro Nacht, sonst Basispreis). Die Abrechnung läuft über die
**generalisierte `shop.Invoice`** (Member ODER Guest; `Invoice.recipient_label`) –
PDF, Mahnung, **Kontoabgleich** (`reconcile`) und Dashboard werden mitgenutzt.
Reine Regel-Logik in `booking/external.py` (`external_allowed`,
`cancellation_refund`), Services in `booking/services.py` (`external_quote`
[saisonale Preise pro Nacht + Anzahlung/Storno-Text]/`external_available_quarters`/
`create_external_booking`/`cancel_external_booking`/`build_external_calendar`/
Magic-Link `*_by_token`); Verfügbarkeit (`quarter_is_free` & Belegungs-Helfer)
berücksichtigt bestätigte `ExternalBooking`s. Öffentlicher Einstieg ohne Login:
View `external_home` (`/extern/`, mit grün/grau-**Verfügbarkeitskalender**
`build_external_calendar`, ohne Gastdaten) + `external_manage`
(`/extern/verwalten/<token>/`, ansehen/stornieren). In der internen `overview`
werden externe Gäste in **einer** Farbe (`services.EXTERN_COLOR`) nur als „extern“
gezeigt. **Online-Bezahlung (Mollie) ist als Naht vorbereitet, noch nicht aktiv**
(Status `pending`/`hold_expires_at`; im Bezahlbereich steht ein Platzhalter
„Online-Direktbezahlung aktuell noch nicht möglich“).

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
`dashboard` (nur Staff, `/verwaltung/`) ist das operative Verwaltungs-Dashboard
(s.u. „Verwaltungs-Dashboard“). Mitbuchbare Dienstleistungen sind `Product` mit `book_with_stay=True`;
`unavailable_weekdays` sperrt Wochentage (geprüft am Abreisetag, z.B.
Endreinigung am Wochenende). Wird ein Wartelisten-Zeitraum durch Storno frei, erzeugt
`services.notify_waitlist_if_free` eine `Notification` **und** (über die Outbox)
eine E-Mail. **E-Mail-Benachrichtigungen:** In-App-`Notification` bleibt; parallel
stellt `services.email_member` (Opt-out je Mitglied via `Member.email_opt_in`)
eine `OutboxEmail` in die Warteschlange, die das Kommando `send_outbox` (vom
`run_scheduler` regelmäßig aufgerufen) verschickt – entkoppelt vom Request, gut
für Massenmails. Provider-neutral über `EMAIL_*`/`PUBLIC_BASE_URL` (ohne
`EMAIL_HOST` → Konsole). Ereignisse: Losergebnis, Wartelisten-Platz frei,
Rechnung erstellt, Konto-Freischaltung (Signal an `Member`-Anlage).
Profil-/Rechnungsdaten (Name, Anschrift, IBAN) pflegt
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
(`/offline/`). Registrierung am Ende von `base.html`. **Navigation:** Icons als
einmaliges SVG-Sprite (`<symbol>`/`<use>`), von allen Varianten geteilt. Auf dem
**Desktop** vertikale Leiste rechts (`.sidenav`) mit Umschalter IN der Leiste
(Kopf „Menü“ + Chevron `#navToggle`), die zur schmalen Icon-Leiste einklappt –
Zustand in `localStorage`, schon im `<head>` gesetzt (kein FOUC). Auf dem
**Smartphone** stattdessen eine feste **untere Tab-Leiste** (`.tabbar`,
daumenfreundlich) mit 4 Hauptpunkten (Übersicht, Buchen, Meine Buchungen,
Hofladen) + Knopf „Mehr“ (`#moreBtn`), der ein **Bottom-Sheet** (`.sheet` +
`.sheet-backdrop`) mit den übrigen Punkten öffnet (Wunschliste, Tage übertragen,
Rechnungen, Profil, Hilfe, Verwaltung, Backend). Für Staff gibt es zwei eigene
Nav-Punkte: **Verwaltung** (`/verwaltung/`, Dashboard) und **Backend** (`/admin/`,
Django-Admin/Stammdaten). Die Navigation erscheint für Mitglieder
UND für Verwaltungs-/Superuser (auch ohne Mitglieds-Profil). Das Layout ist responsiv
(Media-Query in `base.html`, Eingaben volle Breite, breite Datentabellen in
`.table-wrap` → horizontal scrollbar statt überstehend, iOS-Safe-Area).
`sw`/`offline` sind von der Aktivierungs-Sperre ausgenommen (das Manifest liegt
unter `/static/` und ist damit ohnehin frei).

**Hofladen (eigene App `shop`, selber Admin/Webapp/Login):** Produktkatalog
(`ProductGroup`/`Product`; Dienstleistungen wie Sauna = `Product` mit
`kind="dienstleistung"` + `needs_date`). **Lebenszyklus einer Position
(`LineItem`, Preis-Snapshot):** Warenkorb (`purchase`+`invoice` leer; gleiche
Artikel werden in `add_item` zusammengefasst, Menge per `set_cart_quantity`
änderbar) → **Checkout** (`services.checkout` legt einen `Purchase`/Einkauf an;
danach gesperrt, in der Verwaltung als read-only `PurchaseAdmin`) → **Rechnung**
(`Invoice`, Nummer `HL-JJJJ-MM-NNN`, Status offen→bezahlt-gemeldet→bestätigt/
archiviert, §14-Angaben + Steuer-Aufschlüsselung; Positionen nach Einkauf
gruppiert via `Invoice.purchase_groups`). Rechnung **monatlich**
(`generate_monthly_invoices`, Cron) **oder sofort** (`generate_invoice_now`,
Button „Jetzt abrechnen“ bzw. „sofort abrechnen“ beim Checkout). Beim Buchen
mitgebuchte Dienstleistungen (Endreinigung, opt-in) laufen über
`services.purchase_service` direkt als bestätigter Einkauf – dabei wird
`LineItem.allocation` gesetzt (verknüpft die Reinigung mit Quartier + Abreisetag).
`Product.counts_as_cleaning` markiert die Endreinigung für die Reinigungsliste.
**Offene Posten:** `Invoice.due_date` (aus `ShopConfig.payment_term_days`) +
`is_overdue`; **Zahlungserinnerung** idempotent über `services.send_payment_reminder`
/ `remind_overdue` (Aktion im Admin + Dashboard, „zuletzt erinnert am“).
Stammdaten der Genossenschaft im `ShopConfig`-Singleton. Geldlogik/Tests in
`shop/services.py` bzw. `shop/tests.py`. **Cron:** `generate_monthly_invoices`
(monatlich), `run_due_lotteries` (Perioden/Losungen), `notify_admins_upcoming`
(Monats-Mail an die Verwaltung mit den Buchungen des Folgemonats, idempotent am
`OpsConfig.notify_day`). Rechnung als In-App-HTML **und PDF** (WeasyPrint):
`shop/pdf.py` (`invoice_html` rein/testbar getrennt von `invoice_pdf_bytes`),
Druckvorlage `shop/templates/shop/invoice_pdf.html`, Endpoint `shop_invoice_pdf`
(eigene; Staff alle). Das PDF hängt als Anhang an der „Rechnung erstellt“-Mail
(`OutboxEmail` um `attachment*`-Felder erweitert, `send_outbox` schickt es mit).
Native Libs (Pango/Cairo) im `Dockerfile`; CI-Integrationsjob testet `booking shop`.
**Kontoabgleich:** Kontoauszug im Dashboard hochladen (`reconcile.import_bank_statement`);
Parser je Format in `shop/bankimport.py` (normalisierte `ParsedTxn`; `csv` flexibel
über Header-Stichwörter, `camt` = CAMT.053-XML; MT940 später trivial ergänzbar).
`shop/reconcile.py` legt `BankTransaction`/`BankImport` an (Dedup über
`fingerprint`) und verbucht **eindeutige** Treffer (Rechnungsnummer im
Verwendungszweck + exakter Betrag) automatisch: `confirm_invoice` → `confirmed`,
Verknüpfung + In-App-/E-Mail-Benachrichtigung ans Mitglied. Nicht eindeutige
Eingänge bleiben offen (in `BankTransactionAdmin` manuell zuzuordnen + Aktion
„verbuchen“); Rechnungsstatus bleibt manuell änderbar.
**Backup/Hardening sind GEPLANT, nicht umgesetzt** – Blueprints in
`docs/BETRIEB-SICHERHEIT.md`.

**Verwaltungs-Dashboard (`dashboard`, nur Staff, `/verwaltung/`):** operative
Seite fürs kleine Team – Kennzahlen, **Reinigungsliste** (alle Abreisen des
gewählten Monats = Reinigungstage, Spalte/Filter „Endreinigung gebucht“),
**anstehende Buchungen** und **offene/überfällige Rechnungen**. Je Liste
**Export** als xlsx **und** CSV (`booking/exports.py`) und **Versand per Knopf**
(Reinigungsliste ans Reinigungsteam, Buchungen an die Verwaltung,
Zahlungserinnerung an überfällige). Empfänger in `OpsConfig`
(`email_admins`/`email_cleaning`; Reinigungsteam leer = Verwaltungs-Adresse).
Die Nav „Verwaltung“ zeigt aufs Dashboard, die Nav „Backend“ direkt ins
Django-Admin (beide nur für Staff).
Abfragen/Texte/Exportzeilen in `services.py` (`arrivals_in_range`,
`departures_in_range`, `_annotate_cleaning`, `*_rows`, `*_text`).

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
- **Losung-Bestätigung (Review-Workflow):** Ein Lauf landet zunächst im Status
  `lottery_review` – die Zuteilungen sind `Allocation.provisional=True`
  (blockieren die Verfügbarkeit, sind aber für Mitglieder **unsichtbar**;
  `period_result`/`my_bookings`/Übersicht/`day_detail` filtern `provisional=False`),
  und es werden **keine** Benachrichtigungen zugestellt (nur am `LotteryRun`
  vorbereitet: `notices`). Erst `services.confirm_lottery` veröffentlicht
  (Zuteilungen sichtbar, Benachrichtigungen + Mails raus, Status `lottery_done`) –
  danach **kein Undo**. `services.rollback_lottery` (nur unbestätigt) löscht die
  vorläufigen Zuteilungen, stellt das Karma aus `LotteryRun.karma_snapshot`
  wieder her und setzt zurück auf `lottery_ready`. Admin-Aktionen mit Rückfrage
  an `LotteryRunAdmin` (Bestätigen/Zurücknehmen); der Cron schaltet NIE
  automatisch aus `lottery_review` heraus. Ein erneuter `run_period_lottery`
  rollt einen vorhandenen unbestätigten Lauf erst zurück (kein Karma-Aufsummieren).
- **Buchungsperiode/Zeitraum (`BookingPeriod`):** **Pro Buchungsjahr genau EINE
  Periode** (`target_year` ist eindeutig). Sie durchläuft den Lebenszyklus über
  ihren `status`: `draft` (Entwurf) → `wishes_open` (Wunsch-Einträge freigegeben)
  → `lottery_ready` (zur Auslosung freigegeben) → `lottery_review` (Auslosung
  gelaufen, **unbestätigt**) → `lottery_done` (bestätigt/veröffentlicht) →
  `free_booking` (freie Bebuchbarkeit im Zeitraum) → `ended`
  (beendet); `suspended` (unterbrochen) sperrt vorläufig. Der Status wird
  normalerweise **aus den Terminen abgeleitet** (`BookingPeriod.compute_status`,
  die nur bis `lottery_review` führt) und vom Cron-Kommando `run_due_lotteries`
  **vorwärts** geschaltet (nie zurück, nie aus `lottery_review` heraus). Termine:
  `wishlist_open/close` (Wünsche),
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
**Server-Umzug inkl. DB:** `ops/migrate-server.sh dump|restore` (pg_dump/psql über
den `db`-Container); Voraussetzungen + Ablauf stehen im README. **Backup/Hardening
(Backups, 2FA, IBAN-Feldverschlüsselung, LUKS) sind GEPLANT, nicht umgesetzt** –
Risiken/Blueprints im README-Abschnitt „Datensicherung & Härtung“ und in
`docs/BETRIEB-SICHERHEIT.md`.

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
  `Allocation.source="external"` vorhanden). **Konzept** zur Nutzung der App
  für externe Gäste (buchen + zahlen via Mollie, Hybrid-Einstieg, Gast-Checkout) in
  `docs/EXTERNE-GAESTE.md`.
- E-Mail-Fundament steht (Outbox + `send_outbox`, mit Datei-Anhängen);
  **Rechnungs-PDF (WeasyPrint) erledigt**. Offen: Losergebnis-PDF + Massenmail,
  Web-Push (mobil).
- **Losung rückgängig/bestätigen** – **erledigt** (Review-Workflow, s.o.).
- **Kontoabgleich** – **erledigt** (CSV + CAMT.053; MT940 als Parser leicht
  ergänzbar in `shop/bankimport.py`).
- **Backup & Hardening** (geplant, nicht umgesetzt): Blueprints in
  `docs/BETRIEB-SICHERHEIT.md`.
- Verwaltungs-Mails/Putzliste später optional als **Datei-Anhang** (xlsx/CSV)
  statt nur inline (OutboxEmail um Anhang erweitern).
- Drag-and-Drop der Wunschliste auf Touch-Geräten (Pfeiltasten sind Fallback).

---

## Typischer Arbeitsablauf für Claude Code

1. Branch anlegen (`git checkout -b fix/...` bzw. `feat/...`).
2. Bei Bugs zuerst einen **reproduzierenden Test** schreiben, dann minimal fixen.
3. Beide Test-Suiten grün machen.
4. Klein und nachvollziehbar committen (deutsche Commit-Message).
