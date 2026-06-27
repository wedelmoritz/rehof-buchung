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
   - `booking/validation.py` — Plausibilitäts-Prüfungen der Benutzereingaben
     (Name/PLZ/Ort/Straße/IBAN mit Mod-97/E-Mail; `*_error`→Fehlertext|None,
     `strip_controls` für Freitext). Angebunden in `forms.py` + `services.py`.
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
  validation.py         # reine Logik: Plausibilität der Eingaben (Name/PLZ/IBAN…)
  exports.py            # CSV/xlsx-Export (mit Formel-Injektions-Schutz)
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
  test_fairness.py  test_beds24.py  test_validation.py
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
Buchungen“), `LotteryRun` (Losdurchlauf; `n_allocations`/`n_losses` =
erfüllte/nicht erfüllte Wünsche fürs Dashboard), `NightTransfer`, `WaitlistEntry` (Spontanbuchungs-
Warteliste), `Notification` (In-App-Benachrichtigung), `OutboxEmail`
(E-Mail-Warteschlange), `OpsConfig` (Betriebs-Einstellungen-Singleton:
Empfänger der Verwaltungs-Mails + Reinigungsliste, Monats-Mail-Tag,
`beds24_import_enabled` = Beds24-Import an/aus),
`SwapRequest` (Quartier-Wechselwunsch zwischen Mitgliedern), `BookingPolicy`
(Regelwerk-Singleton mit `SeasonRule`/`SchoolHoliday` als Inlines), `SeasonRule`,
`SchoolHoliday`, `FairnessSimConfig` (Singleton: Parameter + letztes Ergebnis
des Fairness-Nachweises). (`BookingWindow` wurde in `BookingPeriod` aufgelöst.)
**Externe Gäste** (`docs/EXTERNE-GAESTE.md`): `Guest` (Bucher ohne Login, mit
`token` für den Magic-Link), `ExternalConfig` (Singleton: Regeln Mo–Do/
Mindestaufenthalt [`min_nights_follow_internal` = wie intern inkl. Saison, Default
an; sonst eigener `min_nights`]/Vorlauf, Reinigung, USt **+ Anzahlung
`deposit_percent`, Storno-Staffel
`free/partial_cancel_days`+`partial_refund_percent`, `late_fee`, `terms`**),
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
berücksichtigt bestätigte `ExternalBooking`s. Öffentlicher Einstieg ohne Login (zweistufig wie intern `book→book_confirm`):
`external_home` (`/extern/`, grün/grau-**Verfügbarkeitskalender**
`build_external_calendar` + freie Unterkünfte, ohne Gastdaten; enthält einen
aufklappbaren Bereich **„Hilfe & Infos für Gäste“**: So buchst du / Bezahlung
[online via Mollie oder Überweisung] / Stornieren / Kontakt aus
`ShopConfig.contact_email`) → `external_book`
(`/extern/buchen/`, **Bestätigungs-/Datenseite**: prüfen, Gastdaten, Preis/Storno/
Anzahlung, erst dann verbindlich buchen) → `external_confirm`;
dazu `external_manage` (`/extern/verwalten/<token>/`, ansehen/stornieren),
`external_pay` (Gast bezahlt seine `Invoice` online über den Magic-Link – „Jetzt
bezahlen“ aus Bestätigung/Verwaltung) und das
einbettbare Website-Widget `external_embed` (`/extern/widget/`,
`@xframe_options_exempt`: Kalender + nach Zeitraum-Wahl freie Unterkünfte, „Buchen“
führt auf die Buchungsseite). In der internen `overview`
werden externe Gäste in **einer** Farbe (`services.EXTERN_COLOR`) nur als „extern“
gezeigt. Die **Online-Bezahlung (Mollie)** ist aktiv (s. „Hofladen“ →
Online-Bezahlung) und gilt für Gäste wie Mitglieder gleichermaßen.

Frontend-Seiten (`booking/views.py`): `overview` (Community-Monatsübersicht,
farbcodiert je Mitglied mit Name + Personenzahl; Klick auf einen Tag zeigt
unten, wer da ist und was noch frei ist; **Umschalter „Kalender / Belegung“** –
„Belegung“ zeigt pro Unterkunft EINE Zeile mit Balken Anreise→Abreise [Farbe je
Mitglied, externe Gäste neutral], also „von wann bis wann ist wer wo“ auf einen
Blick; Service `services.build_occupancy_timeline`; das Monatsraster bleibt
Standard), `book` (Ampel-Kalender → Personen/
Barrierefrei oben einstellen, Anreise/Abreise klicken oder Datum direkt
eingeben – auch über Monatsgrenzen –, passende Quartiere wählen bzw. Warteliste;
Eignung und Mindestaufenthalt werden vorab angezeigt; **Anreise UND Abreise** sind
je eigen markiert [Fähnchen „Anreise“/„Abreise“], das gewählte Band ist deutlich,
sticky Leiste „Anreise → Abreise · N Nächte“ mit Zurücksetzen-Knopf – ebenso in
Wunsch-/Externen-Kalendern), `book_confirm`
(**Bestätigungsschritt**: Unterkunft/Zeitraum prüfen, Personen + Begleitung
angeben, verbleibende Tage sehen, optional Endreinigung mitbuchen – erst
„Verbindlich buchen“ legt die `Allocation` an [der Knopf ist deaktiviert, solange
Mindestaufenthalt oder verfügbare Tage verletzt sind]; gewählte Dienstleistungen
werden als offene Hofladen-Position erfasst), `wishlist` (Wünsche fürs Losverfahren –
bleiben bewusst änderbar), `my_bookings` (eigene Buchungen + Storno **mit
Rückfrage**; je Buchung „wer ist gleichzeitig da“ – aufgeteilt in **exakt gleiche
An-/Abreise** und **nur überlappend** [`services.concurrent_split`] – mit
Wechselwunsch an andere Mitglieder [auch bei Überlappung möglich, mit Hinweis;
Empfänger:in stimmt zu/lehnt ab]; **Buchung ändern** je Buchung
[`services.adjust_allocation`] deckt neben dem **Zeitraum** auch
**Unterkunft-Wechsel** [nur freie – `services.free_quarters_for` listet sie] und
die **Personenzahl** ab: **verlängern** spontan, solange die zusätzlichen
Nächte frei/freigeschaltet/im Budget sind, **verkürzen** nur wenn der
Mindestaufenthalt gewahrt bleibt UND die frei werdenden Nächte ≥7 Tage entfernt
sind – dann In-App-Meldung **an alle** [`_broadcast_spontaneously_free`] + E-Mail
an die Warteliste; der **Unterkunft-Wechsel** geht spontan und meldet das alte
Quartier ebenso als „spontan frei“ an alle (die 7-Tage-Frist gilt nur fürs reine
Verkürzen im selben Quartier); Karte **„Meine Wartelisten-Einträge“** listet die eigenen
offenen Wartelisten-Einträge), `transfer` (**zweistufig**: Vorschau
mit Empfänger – Anzeigename/Benutzername/Name – und Disclaimer, dass die Basis
des Übertrags privatrechtlich zu regeln ist, dann „verbindlich übertragen“).
`dashboard` (Rolle Verwaltung/Admin, `/verwaltung/`) ist das operative
Verwaltungs-Dashboard (s.u. „Verwaltungs-Dashboard“), `dashboard_products` pflegt
den Hofladen-Katalog dort. Mitbuchbare Dienstleistungen sind `Product` mit `book_with_stay=True`;
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
Auslosung im Detail (verlinkt aus Übersicht/Wunschliste). **Fairness-Nachweis**
(`lottery_fairness`, `/losung-fairness/`, login-pflichtig, von der Hilfe verlinkt):
zeigt per **Monte-Carlo-Simulation** (reine Logik `booking/fairness.py` auf dem
puren `lottery`-Modul) mit **Inline-SVG-Grafen**, dass gleich gestellte Mitglieder
statistisch dieselbe Chance haben (Chi-Quadrat-Anpassungstest + Wilson-KI =
„equal treatment of equals" der RSD) und dass das Karma nachweisbar wirkt.
Konfiguriert/gestartet im Backend am Singleton `FairnessSimConfig`
(Admin-Knopf „Simulation jetzt berechnen", Ergebnis als JSON gespeichert);
Service `services.run_fairness_simulation`. Das **Test-Szenario**
`seed_demo --testdata` (kompletter Wipe inkl. Superuser → Test-Konten
admin [Superuser] / verwaltung [Gruppe „Verwaltung“, **kein** Staff] / test
+ 50 Mitglieder, wilde Buchungen im laufenden Jahr, offene
Wunsch-Losung mit Feiertags-Ballung, offene Hofladen-Rechnungen, davon
**8 per Online-Zahldienst (Test) beglichen** für die „online bezahlt“-Ansicht,
15 externe Mo–Fr-Buchungen; Losung NICHT gezogen). **Verwaltung
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
Rechnungen, Profil, Hilfe, Verwaltung, Backend). Zwei Staff-Nav-Punkte,
rollenabhängig (s. „Rollen Admin/Verwaltung“): **Verwaltung** (`/verwaltung/`,
Dashboard – für Gruppe „Verwaltung“ **und** Admin) und **Backend** (`/admin/`,
Django-Admin/Stammdaten – **nur Admin/Superuser**). Die Navigation erscheint für
Mitglieder UND für Verwaltungs-/Admin-Konten (auch ohne Mitglieds-Profil). Das Layout ist responsiv
(Media-Query in `base.html`, Eingaben volle Breite, breite Datentabellen in
`.table-wrap` → horizontal scrollbar statt überstehend, iOS-Safe-Area).
**Kein seitliches Seiten-Scrollen am Handy:** `html`/`body` haben `overflow-x:clip`
(damit der sticky-Banner nie „abbricht“), die `.shell` ist am Handy ein **Block**
(nicht Flex-Spalte), sodass breite Inhalte (Belegungs-Zeitstrahl `.occ`, Tabellen)
**in ihrem eigenen Wrapper** horizontal scrollen statt die Seite zu dehnen; lange
Zeichenketten (Benachrichtigungen/Meldungen) brechen um (`overflow-wrap:anywhere`).
Im **Hofladen** gibt es am Handy einen **schwebenden Warenkorb-Knopf** (`.cart-fab`,
Symbol + Anzahl + Summe), der zum Warenkorb springt (sonst steht der Korb unter dem
ganzen Katalog). `sw`/`offline` sind von der Aktivierungs-Sperre ausgenommen (das
Manifest liegt unter `/static/` und ist damit ohnehin frei).

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
Stammdaten der Genossenschaft im `ShopConfig`-Singleton (Admin-Label **„Rechtliche &
Zahlungs-Einstellungen“** – bewusst übergreifend, da Rechnungen auch für externe
Gäste gelten; früher „Hofladen-Einstellungen“): `coop_name`, `coop_address`,
`tax_number`/`vat_id`, `iban`, `bic`, `invoice_prefix`, `payment_term_days`, `board`
(Vorstand), `contact_email` + USt-Schalter (`small_business`) + Impressum/Datenschutz/
AGB. Der Admin springt direkt aufs Singleton (`changelist_view`-Redirect, keine
Zwischen-Liste). Editierbar nur im Django-Admin (Admin-Rolle). Geldlogik/Tests in
`shop/services.py` bzw. `shop/tests.py`.
**Steuer-/Kassenrecht:** Abrechnung bewusst **ohne TSE** (keine Vor-Ort-Zahlung →
keine Kassenfunktion nach KassenSichV/§146a AO, ADR 0040). **Umsatzsteuer**
umschaltbar im Backend (`ShopConfig.small_business`): Regelbesteuerung (per-Artikel
`vat_rate`, Beherbergung 7 % / Zusatz 19 %) **oder** §19-Kleinunternehmer (Rechnung
ohne MwSt-Ausweis + Hinweis). Die USt-Behandlung wird je `Invoice` gesnapshotet
(`Invoice.small_business`/`tax_note`); USt-Status vor Go-Live mit dem Steuerberater
klären (ADR 0041, keine Rechtsberatung). **Rechtstexte** (ADR 0042): Impressum
(Pflicht, §5 DDG), Datenschutz (DSGVO) und AGB sind im `ShopConfig` konfigurierbar,
öffentliche Seiten `imprint`/`privacy`/`terms` (`/impressum/`, `/datenschutz/`,
`/agb/`), auf jeder Seite im Fuß verlinkt (Context-Processor `legal` + `base.html`).
**Online-Bezahlung (Mollie, EIN System für Hofladen UND externe Gäste):** auf
`Invoice`-Ebene (Mitglied wie Gast haben eine `Invoice`). Reine Naht in
`shop/payments.py` (`start_payment`/`settle_payment`/`cancel_payment`,
`payments_enabled`), echte Anbindung in `shop/mollie_api.py` (nur mit Key). **Ohne
API-Key: eingebauter TEST-/Sandbox-Modus** (simulierte Bezahlseite, ohne Konto/
Gebühren); `test_…`-Key = Mollie-Testumgebung, `live_…`-Key = echt. Modell
`shop.Payment` (token-geschützte, login-freie Bezahl-/Rückkehr-URLs);
`Invoice.payment_method`/`paid_online_at` + Properties `paid_online`/`is_payable`.
Mitglied: „Online bezahlen“ in `shop_invoices`; Gast: `external_pay` über den
Magic-Link. **Online bezahlt ⇒ Rechnung sofort bestätigt/archiviert** (kein
Kontoabgleich) + Benachrichtigung. Konfiguriert am `ShopConfig` (`payments_active`,
`mollie_api_key`).
**Cron:** `generate_monthly_invoices`
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
**Härtung:** Auszug- und Beds24-CSV-Uploads sind auf **10 MB** begrenzt; der
CAMT-Parser lehnt `DOCTYPE`/`ENTITY` ab (Schutz vor Entity-Expansion).
`shop/reconcile.py` legt `BankTransaction`/`BankImport` an (Dedup über
`fingerprint`) und verbucht **eindeutige** Treffer (Rechnungsnummer im
Verwendungszweck + exakter Betrag) automatisch: `confirm_invoice` → `confirmed`,
Verknüpfung + In-App-/E-Mail-Benachrichtigung ans Mitglied. Nicht eindeutige
Eingänge bleiben offen (in `BankTransactionAdmin` manuell zuzuordnen + Aktion
„verbuchen“); Rechnungsstatus bleibt manuell änderbar.
**Beds24-Migrations-Assistent** (`beds24_import`, `/verwaltung/beds24-import/`,
**nur Admin** – legt echte Buchungen an): bestehende Beds24-Buchungen per
**CSV-Upload** übernehmen. Reine Logik in `booking/beds24.py` (flexibles CSV-Parsen
über Header-Stichwörter + unscharfer Namensabgleich `name_score`/`rank_candidates`,
Django-frei testbar). Service `services.beds24_stage` (parst + legt `Beds24Import`
mit `Beds24ImportRow`-Zeilen an und hängt Vorschläge Mitglied/Quartier an),
`beds24_apply` (übernimmt abgeglichene Zeilen als `Allocation`, Quelle **„import"**,
**ohne** Rechnung – diese Buchungen sind immer bezahlt; idempotent/dedupe) und
`beds24_create_member` (legt für nicht zuordenbare Gäste ein Mitglied + Anteil an).
Gäste tippen ihre Namen bei Beds24 frei → es gibt **nur Vorschläge**, der Abgleich
ist **manuell** (Review-Seite mit Mitglied-/Quartier-Dropdown + „+ Mitglied"-Knopf).
Der Import wird i. d. R. nur einmalig beim Umzug gebraucht und ist über
`OpsConfig.beds24_import_enabled` (Betriebs-Einstellungen, Abschnitt
„Beds24-Migration“) **abschaltbar** – ausgeschaltet ist der Assistent im
Dashboard ausgeblendet und gesperrt (auch für Admins).
**Backup/Hardening sind GEPLANT, nicht umgesetzt** – Blueprints in
`docs/BETRIEB-SICHERHEIT.md`.

**Verwaltungs-Dashboard (`dashboard`, Rolle Verwaltung **oder** Admin,
`/verwaltung/`):** operative
Seite fürs kleine Team – Kennzahlen (inkl. KPI **„online bezahlt (Monat)“**),
**Statistik** (`services.dashboard_stats`: Anzahl **Mitglieder** und
**Benutzerkonten**, **Auslastung** der Unterkünfte [gebuchte vs. mögliche
Unterkunfts-Nächte] für **aktuellen und kommenden Monat** sowie das Ergebnis der
**letzten bestätigten Verlosung** = erfüllte vs. nicht erfüllte Wünsche),
**Reinigungsliste** (alle Abreisen des
gewählten Monats = Reinigungstage, Spalte/Filter „Endreinigung gebucht“),
**anstehende Buchungen** und **offene/überfällige/online bezahlte Rechnungen**
(Filter-Chip „Online bezahlt“ + Status-Spalte). Je Liste
**Export** als xlsx **und** CSV (`booking/exports.py`) und **Versand per Knopf**
(Reinigungsliste ans Reinigungsteam, Buchungen an die Verwaltung,
Zahlungserinnerung an überfällige). Empfänger in `OpsConfig`
(`email_admins`/`email_cleaning`; Reinigungsteam leer = Verwaltungs-Adresse).
**Hofladen-Katalog im Dashboard pflegen** (`dashboard_products`,
`/verwaltung/produkte/`): Produkte/Gruppen anlegen + ändern, Preise/aktiv – für
die Verwaltung-Rolle ohne Backend. Backend-Deeplinks im Dashboard nur für Admins.
Der **Beds24-Import** (`beds24_import`) ist im Dashboard verlinkt, aber **nur für
Admins** sichtbar/erreichbar (legt Buchungen an).
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
  datumsbasiert. **Mindestnächte** (+ Einzel-Aufenthaltsdeckel) werden bei der
  normalen Buchung, **beim Eintragen/Einreichen der Wunschliste**
  (`services.wish_rule_error` in `add_wish`/`submit_wishlist`) **und bei externen
  Buchungen** erzwungen. Der Externen-Mindestaufenthalt ist im Backend einstellbar
  (`services.external_min_nights`): **Default identisch zu intern** (inkl. Saison),
  per `ExternalConfig.min_nights_follow_internal` auf einen abweichenden festen Wert
  umstellbar. **Parallel-Limit** und **Aufenthaltsdeckel über mehrere Buchungen**
  werden bei der normalen Buchung **und in der Losung** erzwungen: `run_lottery`
  nimmt einen `rule_check`-Callback (gebaut in `run_period_lottery` aus
  `rules.validate_booking` + einmalig materialisierten Saison-Regeln) und führt je
  Partei die schon zugeteilten Zeiträume (`party_stays`). Ein gedeckelter Wunsch
  wird **übersprungen** (kein Verlust, kein Karma – wie ein Budget-Übersprung; wahrt
  die Strategiesicherheit). Ein Skip übergeht die Partei **nicht**: der innere
  `while`-Loop prüft in **derselben Runde** sofort den nächsten Wunsch derselben
  Partei (kein „erst nächste Runde"). Der Deckel-Check sieht nur die laufeigenen
  Zuteilungen (dokumentierte Grenze, s. ADR 0009).
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
# 1) Reine Logik (schnell, ohne DB) — erwartet: 69 passed
PYTHONPATH=. python -m pytest tests/ -q

# 2) Integrationstests inkl. Use-Cases (DB-Ebene) — erwartet: 186 passed (3 skips)
python manage.py test booking shop
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
Warte-Seite `pending` um (Verwaltungs-/Admin-Konten ausgenommen). Cookies/Sessions
sind gehärtet (HttpOnly, SameSite=Lax, Secure in Prod). OIDC/Keycloak-Naht
bleibt in `settings.py` markiert.

**Rollen Admin/Verwaltung** (`booking/permissions.py`): zwei getrennte Rollen
statt eines einzelnen `is_staff`-Flags. **Admin** = Django-**Superuser** → volles
Backend `/admin/`, darf Buchungen ändern und Losungen starten. **Verwaltung** =
Mitglied der Gruppe **„Verwaltung“** (Konstante `VERWALTUNG_GROUP`) **oder** Admin
→ nur das Dashboard `/verwaltung/` (Buchungen/Losung lesend, pflegt dort den
Hofladen-Katalog), **kein** Backend. Helfer: `is_admin`/`is_verwaltung`/
`ensure_verwaltung_group`; die Gruppe legt Migration `booking/0027_verwaltung_group`
an. `booking/context_processors.py` stellt `is_admin`/`is_verwaltung` allen
Templates bereit (registriert in `config/settings.py`) – die Nav zeigt darüber
„Verwaltung“ (Gruppe) und „Backend“ (nur Admin). Zuordnung = ein Häkchen: den User
im Backend der Gruppe „Verwaltung“ hinzufügen.

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

- Saison-Regeln gelten jetzt vollständig auch für Wunschliste/Losung: **Mindest-
  nächte** beim Einreichen, **Parallel-Limit/Aufenthaltsdeckel** im Los-Algorithmus
  (`run_lottery`-`rule_check`, gedeckelte Wünsche werden übersprungen) sowie für
  externe Buchungen (**erledigt**, s. ADR 0009).
- **Zahlungsanbindung:** Voll-Bezahlung der Rechnung ist umgesetzt (Mollie/Sandbox).
  **Offen:** Online-**Anzahlung** (heute informativ) und automatische **Storno-
  Erstattung** (heute manuell) – Konzept/Naht in ADR 0038, `shop/mollie_api.py` um
  `create_refund` + `payments.refund_payment` zu erweitern.
- Dienste & Waren (Endreinigung, Sauna) als buchbare Posten.
- Externe Gäste (buchen + zahlen via Mollie, Gast-Checkout) – **erledigt**
  (Buchung + Online-Bezahlung aktiv, s.o.); Konzept in `docs/EXTERNE-GAESTE.md`.
- **Online-Bezahlung (Mollie) für Hofladen + Externe** – **erledigt**
  (`shop/payments.py`, `shop/mollie_api.py`, `Payment`; Sandbox-Default).
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
