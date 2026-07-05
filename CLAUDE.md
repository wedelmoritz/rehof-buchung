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

2. **Service-Layer:** `booking/services/` (Paket; früher eine `services.py`, jetzt
   fachlich aufgeteilt — ADR 0050) — die EINZIGE Brücke zwischen DB
   (Django-Modelle) und reiner Logik. Persistenz, Verfügbarkeit, Buchung,
   Stornierung, Übertragung, Kalenderaufbau, Losungs-Durchführung.
   **Hier ändern, wenn es um Datenbank-/Ablauf-Logik geht.** Das `__init__`
   re-exportiert alle Namen, daher bleibt `from booking import services as svc`
   und jeder `svc.*`-Aufruf unverändert. Submodule (azyklisch geschichtet):
   `dates`/`notify`/`slots` (Blätter: Datums-Helfer · Mails/Push · Verfügbarkeit+
   Regeln), `calendars`, `lottery_ops`, `wishes`, `booking_ops`, `dashboard`,
   `external_ops`, `beds24_ops`, `retention`. **Neue Service-Funktion ins passende
   Submodul** legen (nicht zurück in eine Sammeldatei).

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
  services/             # Brücke DB <-> Logik (gesamte Geschäftslogik; Paket, ADR 0050)
    __init__.py         #  re-exportiert alles → `svc.*` bleibt unverändert
    dates.py notify.py slots.py        #  Blätter: Datum · Mail/Push · Verfügbarkeit+Regeln
    calendars.py lottery_ops.py wishes.py booking_ops.py
    dashboard.py external_ops.py beds24_ops.py retention.py
  models.py             # alle Datenmodelle (siehe unten)
  admin.py              # Admin: Mitglieder, Buchungsregeln, Perioden/Zeiträume, Losung-Aktion
                        #  (Backend-Startseite mit Erklär-Panel + „Neue Benutzer": custom_index.html,
                        #   gesetzt über admin.site.index_template). Buchungen: Allocation.clean
                        #   erzwingt die Domänenregeln auch im Backend (keine Doppelbuchung, ADR 0045).
  admin_site.py         # RehofAdminSite: gliedert das Backend fachlich in 5 Sektionen
                        #   (get_app_list, ADR 0049). Persistenter Navigator (Suche + Bereiche) oben
                        #   auf JEDER Seite + pjax (ADR 0055): die eingebaute Seitenleiste ist AUS
  admin_apps.py         #   (enable_nav_sidebar=False). Aktiviert über booking.admin_apps.
                        #   RehofAdminConfig (default_site; meldet ungenutzte „Static devices"
                        #   ab; in INSTALLED_APPS statt django.contrib.admin). EIN warmes Theme
                        #   in ALLEN Django-Modi (Variablen mit !important, Modus-Umschalter aus;
                        #   ADR 0065) + Navigator/pjax: templates/admin/base_site.html
                        #   (+ _rehof_navigator.html). EIN gestapeltes Ein-Spalten-Layout für
                        #   ALLE Seiten (Desktop+Mobil; Float/Flex aufgehoben, ADR 0067).
                        #   Mobil: breite Listen-/Inline-Tabellen scrollen horizontal
                        #   (nowrap + Scroll-Container + sichtbarer Balken; ADR 0071).
                        #   „GESCHICHTE"/Versionen stehen auf der EINZEL-Bearbeiten-Seite
                        #   (Benutzer/Mitglied/Anteil), nicht in den Listen.
  views.py / urls.py / forms.py
  templates/booking/    # base, overview, book, wishlist, result, transfer
  templates/registration/login.html
  tests.py              # Django-Integrationstests (DB-Ebene)
  management/commands/seed_demo.py   # Demo-Daten + reale BB-Termine
config/                 # settings.py, urls.py, wsgi.py, asgi.py
tests/                  # reine pytest-Suite (ohne Django/DB)
  test_lottery.py  test_availability.py  test_rules.py
  test_fairness.py  test_beds24.py  test_validation.py
  test_templates.py  # wacht über geleakte mehrzeilige {# #}-Kommentare (s. Konventionen)
```

Modelle in `models.py`: `EquivalenceClass`, `Quarter` (+ `QuarterPrice` =
saisonale Übernachtungspreise für Externe), `Membership`
(„Mitglied"/Anteil = eine Vielleben-eG-Nummer + `kind` Voll/Teil +
Gesamt-Tagebudget), `Member` (Buchungs-Subjekt je Nutzer; **Tage**-Budget =
**Summe** der `Share`-`night_budget`; **Wunsch**-Budget = **Hälfte der Tage,
abgerundet**, ADR 0073; **Mitgliedsstatus** `passive_from`/`excluded_from` +
`status`/`can_book`, ADR 0087 – s. „Rollen"), `Rolle` (Proxy auf `auth.Group` =
„Rolle" statt „Gruppe", ADR 0087), `Share` (Through-Modell Nutzer↔Anteil mit festem
`night_budget`; ein Nutzer kann mehreren Anteilen angehören → Budgets summieren
sich, ganze Tage; `wish_night_budget` ist obsolet/abgeleitet), `BookingPeriod` (zusammengeführt: Jahres-Losung **und**
buchbarer Zeitraum, gesteuert über `status`), `Wish` (mit `submitted`/`submitted_at`
+ `membership` = zugerechneter Mitglieds-Anteil, ADR 0066), `Allocation`
(mit `persons` + `membership` = zugerechneter Mitglieds-Anteil, ADR 0066;
`special_requests` = optionale **Besonderheiten** beim Buchen [Hund/Kinder/
Zustellbett, dem Mitglied sichtbar] + `internal_note` = **interne Team-/BL-Notiz**
[nur Verwaltung, editierbar auf `verw_buchungen`, dem Mitglied NIE gezeigt];
#62/#68/#84),
`UpcomingAllocation` (Proxy für die Admin-Ansicht „Anstehende
Buchungen“), `PendingUser` (Proxy auf `User` für das geführte Onboarding neuer
Konten, ADR 0056), `LotteryRun` (Losdurchlauf; `n_allocations`/`n_losses` =
erfüllte/nicht erfüllte Wünsche fürs Dashboard), `NightTransfer` (mit `thanked_at` =
„Danke", P2.7), `DayPoolEntry` (Solidaritäts-Pool für Tage, P2.5),
`ForfeitedNights` (**Kurzfrist-Verwirkung**: Storno/Verkürzen ≤ `short_notice_days`
verwirkt die Tage; `effective` = angelegt − von anderen neu gebucht; mindert
`effective_annual_budget`; #ADR 0088), `WaitlistEntry` (Spontanbuchungs-
Warteliste), `CancellationLog` (schlanker **Storno-Nachweis** je gelöschter Buchung –
Anzeige „Zuletzt storniert" in „Meine Buchungen"; kein Soft-Delete, #30/ADR 0082),
`QuarterBlock` (**Sperrzeit** je Quartier für Reinigung/Reparatur – blockiert die
Buchbarkeit wie eine Belegung [in `quarter_is_free`/`find_gaps`/Belegungs-Tage],
Pflege auf der **eigenen** Verwaltungs-Unterseite `verw_sperrzeiten`
(`/verwaltung/sperrzeiten/`) + Backend, Anzeige als schraffierter Balken im
Belegungsplan; #61/ADR 0086),
`Notification` (In-App-Benachrichtigung), `OutboxEmail`
(E-Mail-Warteschlange), `OpsConfig` (Betriebs-Einstellungen-Singleton:
Empfänger der Verwaltungs-Mails + Reinigungsliste, Monats-Mail-Tag,
`beds24_import_enabled` = Beds24-Import an/aus),
`SwapRequest` (Unterkunfts-Tausch zwischen Mitgliedern; nur gleicher Zeitraum, bei
Zustimmung sofort ausgeführt, ADR 0077; **abschaltbar je Mitglied** über
`Member.accept_swap_requests`, Default an, #8/ADR 0078), `BookingPolicy`
(Regelwerk-Singleton mit `SeasonRule`/`SchoolHoliday` als Inlines; zusätzlich
`min_lead_days`/`allow_gap_fill`/`group_min_persons`/`winter_guideline_nights`/
`max_weekends_per_year`/`allow_undersized_units`/`max_wishes_per_period`
(0 = unbegrenzt, optionale Wunsch-Obergrenze je Periode, ADR 0078),
ADR 0075/0076), `SeasonRule`,
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
PDF, Mahnung, **Kontoabgleich** (`reconcile`) und Dashboard werden mitgenutzt. Im
Backend ist die Rechnungsliste **gesplittet**: `InvoiceAdmin` zeigt nur
Mitglieder-Rechnungen (Hofladen), das Proxy-Modell `shop.ExternalInvoice`
(`guest__isnull=False`) die Gäste-Rechnungen unter „Quartiere & Buchungssystem" (ADR 0049).
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

Frontend-Seiten (`booking/views.py`): `overview` (Community-Übersicht, aufgeräumt
nach ADR 0059): oben schlanke **Status-Chips** (Tage frei / offene Losung **mit
Einreiche-Frist** `BookingPeriod.submission_deadline`; wer noch **nichts eingereicht**
hat, sieht stattdessen einen **Warn-Chip** „Noch keine Wünsche eingereicht · bis …",
ADR 0080) + eingeklappte **Benachrichtigungen** (`<details>`); darunter die kompakte
**„Diese Woche"-Agenda** (`services.week_agenda`: je Tag An-/Abreisen + freie
Quartiere, mobil der Schnell-Überblick). **Held ist der Belegungsplan als
Tape-Chart** (`services.build_occupancy_timeline`, Option A, ADR 0083): Unterkünfte
als Zeilen – nach `Quarter.sort_order` (beds24-Reihenfolge, #38) in **Gebäude-Bänder**
gruppiert (statt Zebra, #42) –, durchgehende **Datumsachse ab wählbarem Startdatum**
über **1/2/4 Wochen** (`from`/`weeks`, #41; nicht mehr monatsgebunden), Buchungen als
Balken. Ein **Belegungswechsel** wird als **Halbtag** gerendert (Balken beginnen an
der PM-Kante des Anreise-, enden an der AM-Kante des Abreisetags) – Ab-/Anreise am
selben Tag treffen sich an der Tagesmitte statt sich zu überlappen (#40, keine
Schein-Doppelbelegung). Kopf je Tag: Wochentag · Datum · **Zahl freier Unterkünfte**;
heute markiert. **Rollen-abhängig** (`management=is_verwaltung`): die Verwaltung sieht
externe Gäste mit Klartext-Name/Personen und im Tagesdetail Kontakt (#46b/#47),
Mitglieder nur „extern"; Endreinigung als dezentes **🧹** (#46c). **Drucken als
Querformat-PDF** (nur Verwaltung, `plan_pdf`/`booking/plan_pdf.py` via WeasyPrint:
nacht-basiertes `colspan`-Raster + Listen Anreisen/Abreisen/Endreinigungen,
`services.build_plan_print`; #39). **Ein** responsiver
Plan (Media-Query vergrößert am Handy Zeilen/Tap-Flächen; `.tape` scrollt horizontal
im eigenen Container). **Umschalter „Belegung / Kalender"** schaltet aufs Monatsraster
(`?view=grid`). Klick auf Balken/Tag öffnet das **Tag-Detail im Kontext** – ein Panel
**rechts** neben dem Plan (Desktop, sticky) bzw. **darunter** am Handy (`day_detail`,
klar getrennt nach **Anreise / Abreise / Anwesenheit** = Arrivals/Departures/Stayovers;
noch frei · „An diesem Tag buchen"). **Eine** kombinierte Legende (Personen + heute +
Ferien)), `book` (Ampel-Kalender → Personen/
Barrierefrei oben einstellen, Anreise/Abreise klicken oder Datum direkt
eingeben – auch über Monatsgrenzen –, passende Quartiere wählen bzw. Warteliste;
Eignung und Mindestaufenthalt werden vorab angezeigt; **Anreise UND Abreise** sind
je eigen markiert [Fähnchen „Anreise“/„Abreise“], das gewählte Band ist deutlich,
sticky Leiste „Anreise → Abreise · N Nächte“ mit Zurücksetzen-Knopf – ebenso in
Wunsch-/Externen-Kalendern; unter dem Kalender eine **eingeklappte, hervorgehobene**
Liste **„Kurze freie Lücken zum Füllen"** [`services.short_free_gaps`, beidseitig
belegte kurze Zeiträume der **nächsten Wochen**, passend zu Personenzahl/Barrierefrei –
ideal fürs Lückenfüllen; eingeklappt (deutlich als aufklappbar markiert: getönte
Kopfleiste + „Anzeigen ⌄“/„Verbergen ⌃“-Pill), daher bleibt die Seite kompakt
(mobil-freundlich), #16b/ADR 0078; Belegung einmal geladen]), `book_confirm`
(**Bestätigungsschritt**: Unterkunft/Zeitraum prüfen, Personen + Begleitung
angeben, verbleibende Tage sehen, optional Endreinigung mitbuchen – erst
„Verbindlich buchen“ legt die `Allocation` an [der Knopf ist deaktiviert, solange
Mindestaufenthalt oder verfügbare Tage verletzt sind]; die **Personenzahl** steht in
einem eigenen `data-ajax`-GET-Formular und **prüft bei Änderung sofort neu** [zu viele
Personen → klarer „Platz für höchstens N"-Hinweis + gesperrter Knopf, Korrektur bleibt
auf der Seite statt Rauswurf zur Auswahl, #32]; gewählte Dienstleistungen
werden als offene Hofladen-Position erfasst), `wishlist` (Wünsche fürs Losverfahren –
bleiben bewusst änderbar; je gewähltem Zeitraum zeigt eine Ampel die **Nachfrage**
[`quarter_wish_counts`]; **je eingetragenem, sehr beliebtem Wunsch** steht in „Meine
Wünsche“ ein markanter **Entzerrungs-Hinweis** [`services.wish_alternatives`,
P2.4/ADR 0064] auf **weniger beliebte Alternativen mit besseren Chancen**: ein
**leicht anderer Zeitraum** für dieselbe Unterkunft UND/ODER ein
**gleichwertiges Quartier** (gleiche Äquivalenzklasse) zur gleichen Zeit, das
**weniger gefragt** ist (dort „noch keine/erst N weitere Wünsche“) – beides
anklickbar, saison-gefiltert, eigene Wünsche zählen nicht, kein Eingriff ins
Losverfahren. (Frontend-Wortwahl bewusst **positiv**: „beliebt“ statt „umkämpft/
Konflikt“, ADR 0072.) (`services.wish_deconfliction`
liefert weiter die reine Zeitraum-Verschiebung je Quartier.)),
`my_bookings` (eigene Buchungen als **kompakte Karten**: je Buchung EINE Zeile
(Quartier · Zeitraum · Personen · Quelle) + Storno; alle Details/Aktionen hinter
EINEM Aufklapper **„Details & Aktionen"** (Wer-ist-da · ändern · tauschen), #34.
Je Buchung ein **Endreinigungs-Status** (angefragt/bestätigt/abgelehnt, #33/ADR 0081)
und ein eingeklappter Abschnitt **„Zuletzt storniert"** (Storno-Nachweis, #30/ADR 0082);
Storno **mit
Rückfrage**; je Buchung drei getrennte Aufklapp-Bereiche (ADR 0077): (1) **„Wer ist
zur gleichen Zeit da?“** – rein informativ, **nur Mitglieder**, aufgeteilt in **exakt
gleiche An-/Abreise** und **nur überlappend** [`services.concurrent_split`], **ohne**
Aktion; (2) **Buchung ändern**; (3) **Unterkunft tauschen** – **nur bei exakt gleichem
Zeitraum** [`services.create_swap_request` erzwingt das]; bei Zustimmung wird der
Tausch **sofort ausgeführt** (Quartiere getauscht, konfliktfrei, unter Sperre neu
geprüft; `services.respond_swap_request`); gibt es keinen exakten Partner, verweist
ein Tipp auf „Buchung ändern“ [freie bzw. mit leicht verschobenem Zeitraum freie
Unterkünfte, `services.swap_shift_hint`]. **Buchung ändern** je Buchung
[`services.adjust_allocation`] deckt neben dem **Zeitraum** auch
**Unterkunft-Wechsel** [nur freie – `services.free_quarters_for` listet sie] und
die **Personenzahl** ab: **verlängern** spontan, solange die zusätzlichen
Nächte frei/freigeschaltet/im Budget sind, **verkürzen** solange der
Mindestaufenthalt gewahrt bleibt – **kurzfristig** (frei werdende Nächte ≤
`short_notice_days`) ist es erlaubt, die Nächte **verwirken** dann aber wie beim
Kurzfrist-Storno (ADR 0088, löst die frühere „≥7-Tage"-Sperre ab); dann In-App-Meldung
**an alle** [`_broadcast_spontaneously_free`] + E-Mail an die Warteliste; der
**Unterkunft-Wechsel** geht spontan (Umzug verwirkt nichts) und meldet das alte
Quartier ebenso als „spontan frei“ an alle; Karte **„Meine Wartelisten-Einträge“** listet die eigenen
offenen Wartelisten-Einträge), `transfer` (**zweistufig**: Empfänger:in über ein
**Typeahead-Suchfeld** wählen [ab 3 Zeichen; JSON-Endpoint `member_search` sucht
über Anzeigename/Benutzername/E-Mail/Vor-/Nachname, eigenes Konto + externe Gäste
ausgenommen; die Mitglieds-ID landet in einem versteckten Feld, der Server prüft
sie weiter], dann Vorschau mit Empfänger – Anzeigename/Benutzername/Name – und
Disclaimer, dass die Basis des Übertrags privatrechtlich zu regeln ist, dann
„verbindlich übertragen“; **erhaltene** Übertragungen kann man mit **„Danke sagen“**
einmalig quittieren – `services.thank_for_transfer`, idempotent über
`NightTransfer.thanked_at`, private Benachrichtigung an die schenkende Person, ADR 0064.
Auf derselben Seite der **Solidaritäts-Pool** [P2.5/ADR 0064]: Tage in einen
gemeinsamen Topf **spenden** und **bei Bedarf, gedeckelt entnehmen** [`DayPoolEntry`,
`services/pool.py`: `pool_donate`/`pool_withdraw`/`pool_status`; wirkt über
`Member.effective_annual_budget`; Entnahme nur bei fast aufgebrauchtem Budget
[`POOL_ELIGIBLE_REMAINING`], gedeckelt `POOL_WITHDRAW_CAP_PER_YEAR`]).
`dashboard` (Rolle Verwaltung/Admin, `/verwaltung/`) ist das operative
Verwaltungs-Dashboard (s.u. „Verwaltungs-Dashboard“), `dashboard_products` pflegt
den Hofladen-Katalog dort. Mitbuchbare Dienstleistungen sind `Product` mit
`book_with_stay=True`; sie erscheinen **nur im Buchungsabschnitt** (Bestätigungsschritt),
NICHT im Mitglieder-Hofladen-Katalog (`shop_index` blendet sie aus, der `add`-Endpoint
lehnt sie server-seitig ab, #37/ADR 0081). `unavailable_weekdays` sperrt Wochentage
(geprüft am Abreisetag, z.B. Endreinigung am Wochenende). Wird ein Wartelisten-Zeitraum durch Storno frei, erzeugt
`services.notify_waitlist_if_free` eine `Notification` **und** (über die Outbox)
eine E-Mail. **E-Mail-Benachrichtigungen:** In-App-`Notification` bleibt; parallel
stellt `services.email_member` (Opt-out je Mitglied via `Member.email_opt_in`)
eine `OutboxEmail` in die Warteschlange, die das Kommando `send_outbox` (vom
`run_scheduler` regelmäßig aufgerufen) verschickt – entkoppelt vom Request, gut
für Massenmails. Provider-neutral über `EMAIL_*`/`PUBLIC_BASE_URL` (ohne
`EMAIL_HOST` → Konsole). Ereignisse: Losergebnis, Wartelisten-Platz frei,
Rechnung erstellt, Konto-Freischaltung (Signal an `Member`-Anlage).
Profil-/Rechnungsdaten (Name, **Telefon**, Anschrift, IBAN) pflegt
das Mitglied selbst unter `profile` (Telefon = Kontakt für die BL, sichtbar in
Verwaltung→Mitglieder). Eigene Karte **„Benachrichtigungen“** bündelt
die Kanäle: **In-App** (immer), **E-Mail** (`email_opt_in`, Aktion `notify_prefs` –
getrennt aus der Profil-Form gelöst; dieselbe Aktion speichert auch
`accept_swap_requests` = Tausch-Anfragen erlauben/abschalten, #8/ADR 0078) und
**Push** je Gerät (Toggle wenn `push_enabled`, sonst Hinweis „nicht aktiviert“). Die **Anmeldedaten** (E-Mail/
Passwort ändern) stehen in einem **eingeklappten `<details>`** mit `autocomplete="off"`
– so springt Safari nicht beim Laden auf das Passwortfeld / den Mac-Passwortmanager.
Dort ändert das Mitglied **E-Mail (= Login, folgt
der E-Mail; eindeutig pro Konto) und Passwort** (`EmailChangeForm` +
Djangos `PasswordChangeForm`, `update_session_auth_hash` hält die Sitzung). Der
E-Mail-Wechsel wird mit dem **aktuellen Passwort** bestätigt (kein neues nötig);
ein neues Passwort setzt man nur, wenn man will. **Neue Konten setzen ihr Passwort
selbst:** vom Backend oder Beds24-Import angelegte Benutzer vergeben kein Passwort
durch Admins, sondern bekommen per Mail einen **Einladungs-Link**
(`services.send_account_invite`; ADR 0052). Es ist **ein** Token-Mechanismus für
Einladung **und** „Passwort vergessen": Standard-Django-Reset-Views/-Namen
(`password_reset`/`_done`/`_confirm`/`_complete`, deutsche Pfade, eigene
`registration/`-Templates); „Passwort vergessen" ist auf der Anmeldeseite verlinkt.
Die frühere `membership_number` (Mitgliedsnummer) wurde als ungenutzt **entfernt**
(Datensparsamkeit; sie floss nirgends in Rechnung/Export/PDF). Eine `help`-Seite erklärt Abläufe und die
Auslosung im Detail (verlinkt aus Übersicht/Wunschliste). **Fairness-Nachweis**
(`lottery_fairness`, `/losung-fairness/`, login-pflichtig, von der Hilfe verlinkt):
zeigt per **Monte-Carlo-Simulation** (reine Logik `booking/fairness.py` auf dem
puren `lottery`-Modul) mit **Inline-SVG-Grafen**, dass gleich gestellte Mitglieder
statistisch dieselbe Chance haben (Chi-Quadrat-Anpassungstest + Wilson-KI =
„equal treatment of equals" der RSD) und dass das Karma nachweisbar wirkt.
Konfiguriert/gestartet im Backend am Singleton `FairnessSimConfig`
(Admin-Knopf „Simulation jetzt berechnen", Ergebnis als JSON gespeichert);
Service `services.run_fairness_simulation`. **Gemeinschafts-Spiegel** (`community`,
`/gemeinschaft/`, login-pflichtig, ADR 0063): aggregierte, anonyme Transparenz –
Auslastung (**monatliche Inline-SVG-Kurve** übers Kalenderjahr
`services.year_occupancy_curve` – 12 Monatspunkte mit Wert je Monat als Hover-Titel;
löst die frühere Quartals-Kurve + separate Monatsliste ab, ADR 0074/0076/0079;
effizient: alle Belegungen des Jahres einmal geladen, 2 Abfragen statt 24;
**SVG-Text: `font-size` als CSS-LONGHAND mit `px`** (`.occ-*{font-size:9px}`, wie die
Fairness-Grafik) – NICHT als `font`-Kurzform (ignoriert Safari) und NICHT als
einheitenloses Präsentationsattribut (dann berechnen WebKit/Gecko die Glyphenbreite
falsch → nur der ERSTE Buchstabe je Label sichtbar; ADR 0079-Nachtrag/Fix),
Los-Ergebnis-
Historie, **Karma-Verteilung** (`services.community_stats`/`karma_distribution`) als
schlanke **CSS-Balken**/SVG (kein JS); in der Sekundär-Nav („Gemeinschaft"). Den
**eigenen** Ausgleichsfaktor zeigt eine Karte auf der **Wunschliste** (Karma-
Transparenz, ADR 0073). Das **Test-Szenario**
`seed_demo --testdata` (kompletter Wipe inkl. Superuser → Test-Konten
admin [Superuser] / verwaltung [Gruppe „Verwaltung“, **kein** Staff] / test
+ 50 Mitglieder, wilde Buchungen im laufenden Jahr, offene
Wunsch-Losung mit Feiertags-Ballung, offene Hofladen-Rechnungen, davon
**8 per Online-Zahldienst (Test) beglichen** für die „online bezahlt“-Ansicht,
15 externe Mo–Fr-Buchungen; Losung NICHT gezogen; **Hofladen-Terminal aktiv**
(Token `TESTTOKEN123`, einige Konten inkl. `test` freigeschaltet mit PIN `135790`)).
**Verwaltung
vereinfacht:** ein Benutzer trägt Login **und** Mitglieds-Profil in einem
Formular (Member als Inline am `User`-Admin); `Member` ist aus dem Index
ausgeblendet (nur Autocomplete). **Anlegen ohne Passwort:** das Add-Formular
(`AdminUserInviteForm`) verlangt nur Benutzername + **E-Mail (Pflicht)**; beim
Speichern geht automatisch die „Passwort setzen“-Einladung raus (ADR 0052), plus
Admin-Aktion „Einladung erneut senden“. **Mitglied ↔ Mitglieds-Anteil (ADR 0068):**
`Member` (Person/Login) und `Membership` (eG-Anteil, 50 Tage) bleiben **getrennt**,
weil ein Anteil geteilt (Tandem, n:m über `Share`) und eine Person mehrere Anteile
halten kann – aber sie sind **automatisch verknüpft**: speichert man im Benutzer-
Formular ein buchendes Profil **ohne** Anteil, legt `UserAdmin.save_related` über
`services.ensure_personal_membership` automatisch einen **vollen Anteil (50/25)** an
(idempotent; übersprungen bei vorhandenem Anteil/`is_external`; eG-Nummer nachtragen).
Das Profil zeigt eine **„Mitglieds-Anteil(e)"-Übersicht** (Anteil+Tage+Link), der
Anteil seine Nutzer (`ShareInline`) – beidseitig sichtbar. Ein **Tandem** entsteht
durch Aufteilen am Anteil (oder Wahl eines bestehenden Anteils im Onboarding).
**Beidseitig editierbar + reversibel (ADR 0070):** `MemberAdmin` ist **sichtbar** und
trägt eine **member-seitige `Share`-Inline** (Anteil wählen/wechseln, Tage-Anteil
ändern, ein Mitglied aus EINEM Anteil entfernen – nur die Zuordnung, nicht den
Anteil); das Benutzer-Formular verlinkt dorthin. `MemberAdmin` erlaubt **kein
Anlegen/hartes Löschen** (Mitglieder entstehen am Benutzer/Onboarding, Löschen via
„anonymisieren"). **`django-reversion`** versioniert Benutzer/Mitglied/Anteil/
Tage-Anteil (explizit registriert, `VersionAdmin`, follow-Graph Benutzer→Mitglied→
Tage-Anteil bzw. Anteil→Tage-Anteil): „GESCHICHTE → diese Version wiederherstellen"
(Revert, stellt auch die Tage-Anteile mit her) und „Gelöschtes wiederherstellen"
(Recover, wo Löschen erlaubt ist). **Starke Aktionen doppelt bestätigt**
(CSP-konform delegiert in `base_site.html`: großer „LÖSCHEN"-Knopf + gesetzte
„Löschen?"-Häkchen). **Betrieb:** nach dem Deploy **einmalig**
`manage.py createinitialrevisions`, damit der Bestand einen Ausgangs-Stand hat.
Alle Admin-Bereiche tragen erklärende `description`-Texte.

**Marke/Logo/Farben (EIN Farbsystem, App + Backend gleich, ADR 0054):** Das
gesamte Layout folgt **einem** durchgängigen Token-System mit klaren Rollen –
**warmes Papier-Neutral als ruhige Grundfläche, near-black Text (alles WCAG-AA-
lesbar), der Marken-Akzent BEWUSST sparsam.** Basis sind die zwei Re:hof-Marken-
farben: **Akzent Terrakotta `#BE3E23`** – ausschließlich für **Aktionen/aktiven
Zustand/Fokus** (Primär-Knöpfe, Links, aktive Nav, „Heute“), **nie** als große
Fläche – und **Sekundär Salbei `#7F8F8C`** als ruhige Stütze (Flächen/Chips/
Sekundär-Knopf, weiße Schrift darauf). **Salbei NIE als Text auf Hell** – dafür
`--sage-deep #566C68` oder `--muted #6B6259`. Tokens (in `base.html :root`,
gespiegelt im Backend-Theme `templates/admin/base_site.html`): `--bg #F6F4F1` ·
`--card #FFF` · `--ink #23201D` · `--muted #6B6259` · `--line #E4DFD8` ·
`--accent #BE3E23`/`--accent-deep #9E3119`/`--accent-soft #FBE9E4` ·
`--sage`/`--sage-deep`/`--sage-soft` · Semantik `--good #2E7D55`/`--warn #B07314`/
`--bad #B23A2A` (+ `*-soft`). Funktionale Daten-Farben bleiben bewusst eigen:
der **Ampel-Kalender** (grün=frei … rot=belegt) und die **Mitglieder-Kategorie-
farben** der Übersicht sind Daten-Visualisierung, kein Marken-Akzent. Auch
Backend-Fieldset-/Inline-Überschriften sind dunkel auf neutralem Band (lesbar
statt hellgrau). Zweifarbiger **Re:hof**-Schriftzug als SVG-Wordmark in der
Kopfzeile (`booking/static/booking/brand/wordmark.svg`; volle Variante mit
„Rutenberg“ auf der Anmeldeseite, `wordmark-full.svg`); App-Icon = ziegelrote
Kachel mit cremefarbenem „Re:“ (`icons/logo.svg` + per Pillow erzeugte PNGs
`icon-192/512/maskable/apple-touch/favicon-32`). Das System gilt **durchweg**:
Web-App, Backend, Terminal-Kiosk, Offline-Seite, Externen-Widget, Manifest/
`theme-color`.

**PWA / Mobil:** Die Web-App ist installierbar (iOS „Zum Home-Bildschirm“,
Android) und offline-fähig: Manifest (`booking/static/booking/manifest.webmanifest`),
Re:Hof-Logo/Icons (`booking/static/booking/icons/`), Service Worker (`/sw.js`,
Template `booking/sw.js`, Root-Scope) mit network-first + Offline-Fallback
(`/offline/`). Registrierung am Ende von `base.html`. **Gezieltes Offline-Verhalten
(ADR 0044):** Buchen/Wunsch (`/buchen/`, `/wunschliste/`, `/extern/buchen/`) zeigen
offline KEINE Cache-Kopie (veraltete Verfügbarkeiten), sondern „Buchen braucht eine
Verbindung"; alles andere inkl. **Hofladen-Katalog** ist offline durchblätterbar.
**Offline-Warenkorb (Hofladen):** „+ Warenkorb" funktioniert offline (lokaler Korb in
`localStorage`, Engine `window.__offlineCart` in `base.html`; Panel „Offline-Warenkorb"
in `shop/index.html` mit Mengen-/Lösch-Bearbeitung). Beim Wiederverbinden (`online`-Event)
werden die Positionen automatisch über den `add`-Endpoint an den Server-Warenkorb
übertragen und der lokale Korb geleert; **nur der Checkout** (Rechnung/Bezahlen) braucht
Netz (sonst Hinweis-Toast). Rein clientseitig, keine Server-Änderung. Übrige schreibende
POSTs offline fängt der AJAX-Layer mit Hinweis-Toast ab. **Web-Push
(ADR 0044):** `PushSubscription` je Gerät am `Member`; ein `post_save`-Signal auf
`Notification` stellt jede Benachrichtigung zusätzlich als Push zu
(`services.send_web_push` via pywebpush, best-effort über `transaction.on_commit`,
tote Abos werden entfernt). VAPID-Keys per Env (`VAPID_*`, erzeugen mit
`manage.py vapid_keys`); **ohne Keys ist Push aus** (`settings.PUSH_ENABLED`, wie
Mollie-Sandbox). Opt-in-Knopf im Profil (`window.__rehofPush`, in der
„Benachrichtigungen“-Karte neben dem E-Mail-Schalter; ohne `push_enabled` ein
Hinweis statt Knopf), Endpunkte
`push_subscribe`/`push_unsubscribe`; SW-`push`/`notificationclick` in `sw.js`.
**iOS-Hinweis (wichtig):** Web-Push läuft auf iPhone/iPad **nur in der installierten
PWA** (Home-Bildschirm, iOS 16.4+), NICHT im Safari-Tab (dort fehlt `PushManager`).
Das Profil erkennt iOS + Standalone-Modus und zeigt statt „nicht verfügbar“ eine
**konkrete Anleitung** („Zum Home-Bildschirm“ → App öffnen → aktivieren) bzw. den
iOS-16.4-Hinweis, wenn schon installiert. **Apple-Zustellung strikt:** der VAPID-
`sub`-Claim muss gültig sein – `services._vapid_sub_claim` nimmt `VAPID_ADMIN_EMAIL`
(echte Domain-Adresse!), sonst `PUBLIC_BASE_URL` (https), NIE `mailto:admin@localhost`
gegenüber Apple (sonst keine iOS-Zustellung). **Diagnose:** Profil-Push-Karte hat ein
aufklappbares „Diagnose“-Panel (`__rehofPush.diagnose()`: HTTPS/Standalone/SW/
PushManager/Berechtigung/Abo/Push-Dienst-Host, keine Geheimnisse); `enable()` markiert
den fehlgeschlagenen Schritt (`permission`/`subscribe`/`server`); serverseitig loggt
`booking.push` Abo-Speicherung und jede Zustellung (Erfolg/HTTP-Fehler von Apple/FCM).
**Wichtig (Reihenfolge):** `window.__rehofPush` wird am **Body-Ende** definiert
(nach `{% block content %}`); Verbraucher im Inhalt (Profil) starten daher erst bei
`DOMContentLoaded` – sonst liefe das Skript VOR der Modul-Definition (`__rehofPush
fehlt`). Das Modul hängt nur an `user.is_authenticated` (nicht an `user.member`).
**Navigation:** Icons als
einmaliges SVG-Sprite (`<symbol>`/`<use>`), von allen Varianten geteilt. Auf dem
**Desktop** vertikale Leiste **links** (`.sidenav`, `order:-1` im Flex-Layout;
#24/ADR 0078) mit Umschalter IN der Leiste
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
Mitglieder UND für Verwaltungs-/Admin-Konten (auch ohne Mitglieds-Profil).
**Rollen-rein (ADR 0084):** die mitglieds-eigenen Punkte (Buchen, Wunschliste, Meine
Buchungen, Tage übertragen, Hofladen, Meine Rechnungen, Profil) erscheinen nur mit
Buchungs-Profil (`{% if user.member %}`) – ein reines Verwaltungs-Konto sieht sonst
tote Links (#48); es bekommt Übersicht · Gemeinschaft · Hilfe · Verwaltung (am Handy
tritt „Verwaltung“ als Haupt-Tab an die Stelle der Mitglieds-Tabs). **Verwaltungs-
Unterpunkte (ADR 0085):** unter „Verwaltung“ stehen eingerückte Unterpunkte
(Buchungen · Reinigung · Rechnungen · Kontoabgleich · Auslastung · Hofladen-Katalog),
die auf die echten Verwaltungs-Unterseiten führen (im eingeklappten Icon-Modus
ausgeblendet, `.subnav`; am Handy im „Mehr“-Sheet). Das Verwaltungs-
Icon ist ein Klemmbrett mit Haken (nicht mehr die Sonne, #43). Das Layout ist responsiv
(Media-Query in `base.html`, Eingaben volle Breite, breite Datentabellen in
`.table-wrap` → horizontal scrollbar statt überstehend, iOS-Safe-Area).
**Kein seitliches Seiten-Scrollen am Handy:** `html`/`body` haben `overflow-x:clip`
(damit der sticky-Banner nie „abbricht“), die `.shell` ist am Handy ein **Block**
(nicht Flex-Spalte), sodass breite Inhalte (Belegungsplan `.tape`, Tabellen)
**in ihrem eigenen Wrapper** horizontal scrollen statt die Seite zu dehnen; lange
Zeichenketten (Benachrichtigungen/Meldungen) brechen um (`overflow-wrap:anywhere`).
Im **Hofladen** gibt es am Handy einen **schwebenden Warenkorb-Knopf** (`.cart-fab`,
Symbol + Anzahl + Summe), der zum Warenkorb springt (sonst steht der Korb unter dem
ganzen Katalog). `sw`/`offline` sind von der Aktivierungs-Sperre ausgenommen (das
Manifest liegt unter `/static/` und ist damit ohnehin frei).
**Bestätigungen/Meldungen:** Django-`messages` (Feedback auf eine aktive Aktion)
werden in `base.html` per JS in **fixierte Toasts** umgewandelt (sichtbar egal wie
weit gescrollt). **Nur** die Framework-Meldungen tragen `data-toast` und werden
eingesammelt (`harvest('.msg[data-toast]')`); fest im Template stehende `.msg`-Banner
(Status/Hinweise) und die Benachrichtigungs-Karte `.notif` („Aktuelle Nachrichten“
auf der Übersicht: Losergebnis/Wartelisten-Platz/Rechnung etc.) bleiben **stehen**.
POST-Formulare im `<main>` werden **progressiv per `fetch` ohne Neuladen** abgeschickt
(Antwort nach Redirect geparst, `<main>` getauscht inkl. Re-Exec der Inline-Skripte,
Scrollposition gehalten); ebenso die **GET-Kalendernavigation** (Tag Anreise→Abreise
wählen, Monat blättern, zurücksetzen) über `window.__nav` – **kein Sprung nach oben**
mehr. Trägt die Ziel-URL einen **Anker** (`#…`, z.B. das Tag-Detail der Übersicht),
scrollt `__nav`/`swap` nach dem Tausch **sanft** dorthin (statt die Position zu
halten) – so springt der **Tag-Klick in der Übersicht** ohne Reload zur Detailkarte
(Tabelle UND Belegungs-Zeitstrahl, `data-ajax` + `#tag`). Opt-in per `data-ajax` an
Links/GET-Formularen (`overview` Tag-Detail/Belegungs-Balken, `book`/`wishlist`/
`external_home` + gemeinsame `_calnav.html`; **`dashboard`** Monatswahl/Filter-Chips –
Selects via `requestSubmit()`, nicht `submit()`, sonst feuert das submit-Event nicht). Fallback =
normales Laden/Abschicken, ausgenommen `multipart`/`data-no-ajax` (Auth) und
Modifier-Klick/neuer Tab (ADR 0035). Der AJAX-Submit-Layer respektiert
`e.defaultPrevented`, sodass `onsubmit="return confirm(…)"` (Storno, Löschen,
„als bezahlt melden") bei **Abbrechen** NICHT doch per AJAX abschickt.

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
mitgebuchte Dienstleistungen (opt-in) laufen über `services.purchase_service` direkt
als bestätigter Einkauf – dabei wird `LineItem.allocation` gesetzt (verknüpft die
Reinigung mit Quartier + Abreisetag). `Product.counts_as_cleaning` markiert die
Endreinigung für die Reinigungsliste. **Bestätigungspflichtige Leistungen
(`Product.needs_approval`, ADR 0081):** die **Endreinigung** wird beim Buchen NUR
**angefragt** (`services.request_service` legt eine `shop.ServiceRequest` an, Status
`requested`, E-Mail an die Betriebsleitung) – **keine** Abrechnung, bis die BL im
Dashboard **bestätigt** (`confirm_service_request` → `purchase_service` + Reinigungs-
liste) oder **ablehnt** (`reject_service_request`); beide idempotent, benachrichtigen
das Mitglied. Das Mitglied sieht den Status („angefragt/bestätigt/abgelehnt“) in
**„Meine Buchungen“** (`Allocation.service_requests`, prefetch). Sofort-Kauf bleibt für
DLs ohne `needs_approval` (z.B. Sauna). **Entscheidung revidierbar bis zur Frist
(#45/ADR 0081-Nachtrag):** bestätigt ⇄ abgelehnt bleibt änderbar bis
`BookingPolicy.er_decision_lock_days` (Default **7 Tage vor Anreise**; 0 = jederzeit)
– danach fest; die Frist sperrt nur das **Revidieren**, eine noch offene Anfrage darf
weiter erstmalig entschieden werden (serverseitig `services.service_request_locked`).
Beim Zurücknehmen einer Bestätigung entfällt die **noch nicht abgerechnete** Position
(bereits fakturiert → nicht mehr revidierbar). Das Dashboard bündelt änderbare
Entscheidungen im eingeklappten Bereich **„Endreinigung nachträglich ändern"**
(`services.revisable_service_requests`, „änderbar bis <Datum>").
**Offene Posten:** `Invoice.due_date` (aus `ShopConfig.payment_term_days`) +
`is_overdue`; **Zahlungserinnerung** idempotent über `services.send_payment_reminder`
/ `remind_overdue` (Aktion im Admin + Dashboard, „zuletzt erinnert am“).
Stammdaten der Genossenschaft im `ShopConfig`-Singleton (Admin-Label **„Rechtliche &
Zahlungs-Einstellungen“** – bewusst übergreifend, da Rechnungen auch für externe
Gäste gelten; früher „Hofladen-Einstellungen“): `coop_name`, `coop_address`,
`tax_number`/`vat_id`, `iban`, `bic`, `invoice_prefix`, `payment_term_days`,
`allow_self_report_paid` (Selbst-Meldung „Habe ich überwiesen“ optional abschaltbar,
Default an – dann zählt allein der Kontoabgleich; server-seitig in `mark_paid`
erzwungen, #26/ADR 0078), `board`
(Vorstand), `contact_email` + USt-Schalter (`small_business`) + Impressum/Datenschutz/
AGB. Der Admin springt direkt aufs Singleton (`changelist_view`-Redirect, keine
Zwischen-Liste). Editierbar nur im Django-Admin (Admin-Rolle). Geldlogik/Tests in
`shop/services.py` bzw. `shop/tests.py`.
**Hofladen-Terminal vor Ort (`/terminal/`, ADR 0053):** ein **geteiltes Gerät** im
Laden, an dem freigeschaltete Gäste per **6-stelliger PIN** auf ihre **Monatsrechnung**
einkaufen – **offline-fähig** (im Laden kein Netz). Eigenständige, **für ältere
Menschen** gebaute Kiosk-Seite (große Schrift/Knöpfe, Emoji, Name antippen → PIN →
Artikel → bestätigen). **Kein** Mitglieder-Login/keine Django-Sitzung: das Gerät weist
sich nur per **Geräte-Token** (`TerminalConfig`, im Backend änderbar/„neu erzeugen") an
**zwei** Endpunkten aus – `terminal_data` (Roster: Benutzername/Anzeigename/**PIN-Hash**
+ Katalog) und `terminal_sync` (offline erfasste Einkäufe **idempotent** über
`Purchase.terminal_ref` auf die Monatsrechnung; **keine Zahlung**). Mehr geben die
Token-Endpunkte nicht her (keine PII/Profil/Backend) – der Schadensradius bleibt klein.
PIN-Prüfung läuft **offline im Gerät** gegen den Django-PBKDF2-Hash (Web Crypto),
Sperre nach N Fehlversuchen + Idle-Logout. `Member.terminal_enabled` ist
**standardmäßig an** (für alle); die Person vergibt die **PIN selbst im Profil**
(Aktion `terminal_prefs`: ein/aus **und** PIN; ohne PIN nicht in der Roster) und kann
die Teilnahme dort auch **ausschalten** (dann ist die PIN inaktiv). Profil + Terminal
weisen darauf hin, dass eine PIN-Änderung/ein Einkauf wegen des oft **offline** stehenden
Geräts **nicht sofort** wirkt/erscheint (Sync beim nächsten Online-Sein). Service
`services/terminal_ops.py`; SW hält `/terminal/` offline
vor (ADR 0035). **Pflicht-Gerätehärtung** (Kiosk-Mode, Festplatten-Verschlüsselung,
physische Sicherung) im Deployment-Runbook – ohne sie ist der Modus nicht freizugeben.

**Steuer-/Kassenrecht:** Abrechnung bewusst **ohne TSE** (keine Vor-Ort-Zahlung →
keine Kassenfunktion nach KassenSichV/§146a AO, ADR 0040). **Umsatzsteuer**
umschaltbar im Backend (`ShopConfig.small_business`): Regelbesteuerung (per-Artikel
`vat_rate`, Beherbergung 7 % / Zusatz 19 %) **oder** §19-Kleinunternehmer (Rechnung
ohne MwSt-Ausweis + Hinweis). Die USt-Behandlung wird je `Invoice` **beim Erstellen
gesnapshotet** (`Invoice.small_business`/`tax_note`) – nach einer Änderung des Modus
zeigen ALTE Rechnungen weiter ihren alten Snapshot; sie müssen neu erstellt werden.
Der **aktive USt-Modus** wird der Verwaltung im **Dashboard** (Abschnitt Rechnungen)
**read-only** angezeigt (Transparenz ohne Backend; ändern nur Admin, #27). USt-Status
vor Go-Live mit dem Steuerberater klären (ADR 0041, keine Rechtsberatung). **Rechtstexte** (ADR 0042): Impressum
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
`OpsConfig.notify_day`), `send_wish_reminders` (täglich, **zweistufige Wunsch-
Erinnerung** vor der Losung an Mitglieder ohne eingereichten Wunsch;
`services.send_wish_reminders`, idempotent je Stufe über
`BookingPeriod.wish_reminder1_at/2_at`; Vorlauf konfigurierbar
`BookingPolicy.wish_reminder_lead1/2`, Default 7/2 Tage, ADR 0080),
`cleanup_data` (täglich, **DSGVO-Aufräumen**).
**DSGVO/Datensparsamkeit (ADR 0043):** `cleanup_data` (Service
`services.run_data_retention`, idempotent, im `run_scheduler` täglich) löscht/
pseudonymisiert abgelaufene Daten anhand der `RETENTION_*`-Settings (per Env
überschreibbar): versendete `OutboxEmail` inkl. DB-Anhang (90 T), `Notification`
(180 T), `BankTransaction.raw` leeren (90 T), `Beds24Import` (180 T), `BankImport`
(365 T), erledigte `SwapRequest`/`WaitlistEntry` **+ `CancellationLog`** (180 T), `Wish` beendeter Perioden
(2 J), abgelaufene Sessions, `axes`-Fehlversuche (30 T). **Rechnungen/Zahlungen
(10 Jahre, §147 AO/§14b UStG) bleiben unangetastet** (`Invoice.member/guest=PROTECT`).
**Recht auf Löschung (Art. 17):** Admin-Aktion „Mitglied anonymisieren“ am
Benutzer (`services.anonymize_member`, mit Rückfrage) leert Profil-PII + Freitext
(`companions`/`note`), entfernt betrieblich kurzlebige PII und deaktiviert das
Login – die Rechnungs-Snapshots bleiben erhalten. IBAN-Verschlüsselung/Token-
Rotation bleiben offen (TBD, ADR 0037/0043). Rechnung als In-App-HTML **und PDF** (WeasyPrint):
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
`beds24_create_member` (legt für nicht zuordenbare Gäste ein Mitglied + Anteil an;
mit **E-Mail** geht automatisch die Passwort-Einladung raus, ADR 0052).
Gäste tippen ihre Namen bei Beds24 frei → es gibt **nur Vorschläge**, der Abgleich
ist **manuell** (Review-Seite mit Mitglied-/Quartier-Dropdown + „+ Mitglied"-Knopf).
**E-Mail als einziger eindeutiger Anker** (`Beds24ImportRow.match_kind`): die Gast-
E-Mail aus dem Export wird je Zeile gespeichert (`Beds24ImportRow.email`). Nur ein
**eindeutiger E-Mail-Treffer** ist 🟢 (vorausgewählt, Aktion „übernehmen" vorbelegt);
der **Namensabgleich** ist nie grün, sondern 🟡 „prüfen" – ein einzelner Treffer wird
vorgeschlagen, treffen **mehrere** den Namen (`match_kind="multi"`) wird **nichts**
vorausgewählt (Verwaltung muss wählen). Neben der
Treffer-Ampel zeigt der Abgleich zwei weitere Hinweise (`services.beds24_row_checks`,
nur Anzeige, **nicht blockierend**): **Verfügbarkeit** des Quartiers im Zeitraum
(🟢 frei / 🔴 belegt, `quarter_is_free`) und eine **Regel-Warnung** (Mindestaufenthalt,
⚠️). Aktion je Zeile: **übernehmen** (Buchung anlegen) · **überspringen** (verwerfen,
bleibt vermerkt) · **offen** (noch nichts tun).
Der Import wird i. d. R. nur einmalig beim Umzug gebraucht und ist über
`OpsConfig.beds24_import_enabled` (Betriebs-Einstellungen, Abschnitt
„Beds24-Migration“) **abschaltbar** – ausgeschaltet ist der Assistent im
Dashboard ausgeblendet und gesperrt (auch für Admins).
**Sicherheits-Härtungspaket (ADR 0061) umgesetzt:** Backend-2FA (django-otp,
`ADMIN_OTP_REQUIRED`, `manage.py admin_otp_setup`), Fail-closed `SECRET_KEY`-Wächter,
nonce-basierte **CSP** (django-csp; jedes `<script>` mit `request.csp_nonce`, keine
Inline-Handler – delegierte `data-*`-Handler in `base.html`), **Rate-Limiting**
(django-ratelimit, `RATELIMIT_ENABLE`), **pip-audit** im CI + Dependabot,
Nicht-root-Container, Permissions-Policy/CORP-Header + Anmelde-Audit-Log,
HSTS-Default 30 Tage, WeasyPrint ohne Remote-Fetch, **verschlüsseltes Backup-Skript**
`ops/backup.sh`. **IBAN-Feldverschlüsselung ist VORBEREITET, aber inaktiv**
(`booking/fieldcrypt.py`+`fields.py`, `FIELD_ENCRYPTION_KEY` leer = Klartext).
**Weiteres Hardening (Borg-Append-only-Backups, LUKS) bleibt Blueprint** in
`docs/BETRIEB-SICHERHEIT.md`.

**Verwaltungs-Dashboard (`dashboard`, Rolle Verwaltung **oder** Admin,
`/verwaltung/`):** operative
Seite fürs kleine Team. **Aufbau als Handlungsbedarf-Cockpit mit echten Unterseiten
(ADR 0085, ersetzt die Dashboard-Tabs aus ADR 0084):** `/verwaltung/` selbst ist die
**„jetzt handeln"-Übersicht** – Kompakt-Kennzahlen (Monat, inkl. KPI **„online bezahlt"**)
+ drei Karten (offene **Endreinigungs-Anfragen** mit Inline-Bestätigen/Ablehnen,
**überfällige Rechnungen**, **neue & geänderte Buchungen** der letzten 7 Tage via
`services.recent_booking_activity` = neue `Allocation` + `CancellationLog`). Jede Karte
verlinkt auf ihre **Unterseite**. Die vollen Listen/Aktionen liegen auf **eigenen
gerouteten Unterseiten mit eigenem Menü-Eintrag** (Seitenleiste + „Mehr"-Sheet, für
`is_verwaltung`, als eingerückte Unterpunkte unter „Verwaltung"):
`verw_buchungen` (`/verwaltung/buchungen/`, anstehende Buchungen; **interne Notiz**
je Buchung inline editierbar #84),
`verw_reinigung` (`/verwaltung/reinigung/`, **Reinigung inkl. Endreinigung** – s.u.),
`verw_sperrzeiten` (`/verwaltung/sperrzeiten/`, **Sperrzeiten** je Quartier #61 –
eigene Seite, nicht mehr unter Reinigung),
`verw_rechnungen` (`/verwaltung/rechnungen/`, Rechnungen + Erinnerungen),
`verw_konto` (`/verwaltung/kontoabgleich/`, Kontoabgleich),
`verw_auslastung` (`/verwaltung/auslastung/`, Statistik + Auslastungs-Ampel),
`verw_mitglieder` (`/verwaltung/mitglieder/`, Mitgliederliste mit Kontakt #65),
`dashboard_products` (`/verwaltung/produkte/`, Hofladen-Katalog). Gemeinsame Bausteine:
`verw_base.html` (Layout + gesamtes CSS, Blöcke `verw_h1`/`verw_body`),
`_verw_monthbar.html` (Monatswahl, GET+`data-ajax`) und der zentrale POST-Dispatcher
`views._verw_post` (verarbeitet alle Aktionen, leitet auf die passende Unterseite
zurück – Monat/Filter erhalten). Weiterhin **server-getrieben + CSP-treu** (GET-Nav
via `data-ajax`, keine Client-Tabs). Inhalte der Unterseiten:
**Statistik** (`services.dashboard_stats`: Anzahl **Mitglieder** und
**Benutzerkonten**, **Auslastung** der Unterkünfte [gebuchte vs. mögliche
Unterkunfts-Nächte] für **aktuellen und kommenden Monat** sowie das Ergebnis der
**letzten bestätigten Verlosung** = erfüllte vs. nicht erfüllte Wünsche) +
**Auslastung je Unterkunft** (`services.quarter_occupancy_ampel`:
gebuchte/mögliche Nächte im Monat + **statische Ziel-Ampel** gegen
`Quarter.target_occupancy` – 🟢 ab Ziel · 🟡 bis 20 %-Punkte darunter · 🔴 darunter;
#63/#64) auf `verw_auslastung`;
**Reinigung UND Endreinigung auf EINER Seite** (`verw_reinigung`, ADR 0085: kein
getrennter Menüpunkt – nach **jeder** Abreise wird unbezahlt gereinigt, die gebuchte
**bezahlpflichtige** Endreinigung ist ein Zusatz): **Reinigungsliste** (alle Abreisen
des Monats = Reinigungstage, Spalte/Filter „Endreinigung gebucht“) + „Endreinigung
freigeben" (beim Buchen angefragte, bestätigungspflichtige Leistungen,
`services.pending_service_requests`; **Bestätigen** → Abrechnung + Reinigungsliste,
**Ablehnen** → Mitglied benachrichtigt; #28/ADR 0081) samt „Nachträglich ändern" (#45)
– als kompakte, umbrechende Karten (`.er-item`, **kein horizontaler Scroll**);
**anstehende Buchungen** (`verw_buchungen`) und **offene/überfällige/online bezahlte
Rechnungen** (`verw_rechnungen`, Filter-Chip „Online bezahlt“ + Status-Spalte). Je Liste
**Export** als xlsx **und** CSV (`booking/exports.py`) und **Versand per Knopf**
(Reinigungsliste ans Reinigungsteam, Buchungen an die Verwaltung,
Zahlungserinnerung an überfällige – **alle** auf einmal ODER **je Rechnung**
[`action=remind_one`]; es gibt **keinen automatischen Konto-Abruf**, Eingänge kommen
über den Kontoabgleich, Erinnerungen stößt die BL manuell an, #36). Empfänger in `OpsConfig`
(`email_admins`/`email_cleaning`; Reinigungsteam leer = Verwaltungs-Adresse).
**Hofladen-Katalog** (`dashboard_products`,
`/verwaltung/produkte/`): Produkte/Gruppen anlegen + ändern, Preise/aktiv – für
die Verwaltung-Rolle ohne Backend. Backend-Deeplinks in den Listen nur für Admins.
Der **Beds24-Import** (`beds24_import`) ist **ins Backend gewandert** (ADR 0085): ein
Kasten auf der Backend-Startseite (`custom_index.html`, nur Superuser + solange in den
Betriebs-Einstellungen freigeschaltet), da es ein einmaliger, admin-seitiger
Umzugs-Task ist (legt echte Buchungen an). URL/View unverändert.
Abfragen/Texte/Exportzeilen in `services.py` (`arrivals_in_range`,
`departures_in_range`, `_annotate_cleaning`, `*_rows`, `*_text`,
`recent_booking_activity`).

---

## Domänenregeln (NICHT versehentlich brechen)

- **Losverfahren:** gewichtete Zufallsreihenfolge im Runden-Prinzip
  (strategiesicher, über Seed reproduzierbar). Ausweichen auf gleichwertige
  Quartiere derselben `EquivalenceClass`. Karma: +0,1 pro echtem Verlust,
  Deckel 1,5, Reset auf 1,0 bei Gewinn eines sehr beliebten Slots. **Nur
  eingereichte Wünsche (`submitted=True`) nehmen teil.** Die Strategiesicherheit
  ist deterministisch getestet (`test_strategieproof_ueber_alle_reihenfolgen`) —
  bei Änderungen am Algorithmus muss dieser Test grün bleiben. Die Losung lässt
  sich über `BookingPeriod.draw_at` terminieren; das Kommando
  `run_due_lotteries` (per Cron) führt fällige Losungen automatisch aus.
- **Verifizierbarkeit (Commit-Reveal, ADR 0062):** Der Seed ist nicht
  manipulierbar. Beim Öffnen der Wünsche legt `services.ensure_seed_commit` einen
  CSPRNG-Seed fest und veröffentlicht **nur dessen SHA-256-Prüfsumme**
  (`BookingPeriod.seed_commit`/`seed_committed_at`, im Backend read-only); nach der
  bestätigten Ziehung wird der Seed offengelegt (Ergebnisseite). Reine Logik
  `lottery.seed_commitment`/`verify_commitment`; Verifikation
  `services.verify_period_lottery` + Kommando `manage.py verify_lottery`. Anzeige
  schlank auf Wunschliste/Ergebnis (`<details>`) + Abschnitt 3 auf „Fairness-Nachweis".
  `run_period_lottery` nutzt **immer** den committeten Seed (sonst passt die Prüfsumme nicht).
- **Losung-Bestätigung (Review-Workflow):** Ein Lauf landet zunächst im Status
  `lottery_review` – die Zuteilungen sind `Allocation.provisional=True`
  (blockieren die Verfügbarkeit, sind aber für Mitglieder **unsichtbar**;
  `period_result`/`my_bookings`/Übersicht/`day_detail` filtern `provisional=False`),
  und es werden **keine** Benachrichtigungen zugestellt (nur am `LotteryRun`
  vorbereitet: `notices` – die **je Wunsch erklären**, *warum* bekommen/nicht:
  Ausweichgrund, „sehr beliebt"/Los, „ganze gleichwertige Gruppe belegt", übersprungen
  wegen Budget/Saison-Regel; P2.6/ADR 0064, gespeist aus `result.log`). Erst
  `services.confirm_lottery` veröffentlicht
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
- **Tage:** bis 50/Jahr je Mitglied (voller Anteil). Das **Wunsch-Budget** für die
  Losung ist **immer genau die Hälfte der Tage, abgerundet** (50→25, 25→12;
  `Member.wish_night_budget = annual_night_budget // 2`, abgeleitet – nicht je Anteil
  gespeichert, ADR 0073). **Kein Übertrag ins Folgejahr** (Kontingent gilt je
  Kalenderjahr frisch). Tage sind
  **an andere Mitglieder übertragbar** (`NightTransfer`) **oder in den
  Solidaritäts-Pool spendbar/daraus entnehmbar** (`DayPoolEntry`, gedeckelt, nur bei
  Bedarf; P2.5/ADR 0064). Beides fließt in `Member.effective_annual_budget` ein.
- **Kurzfrist-Storno/Verkürzen (ADR 0088):** wird eine Buchung mit Anreise ≤
  `BookingPolicy.short_notice_days` (Default 14) storniert/verkürzt, **verfallen** die
  betroffenen Tage (`ForfeitedNights`, mindert `effective_annual_budget`) – **zurück
  nur, soweit ein anderes Mitglied** den Zeitraum neu bucht (`covered_by_others`,
  dynamisch). Alle Mitglieder werden dann **in der App** informiert (kein Mail;
  `_broadcast_spontaneously_free`), Warteliste wie gehabt per Mail. Die frühere
  „≥7-Tage"-Verkürzungs-Sperre in `adjust_allocation` entfällt (Umzug/Quartier-Wechsel
  verwirkt nichts). UI-Warnung in „Meine Buchungen" (`is_short_notice`).
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
  werden bei der normalen Buchung **und in der Losung** erzwungen – und zwar **auf
  den vollen Mitglieds-Anteil** (inkl. Tandem-Partner, ADR 0066): `Allocation`/`Wish`
  tragen einen `membership`-FK (Zurechnung über `Member.membership_for`: eindeutiger/
  größter Anteil, bei Mehrfach-Tandem die Wahl). `check_booking_rules(member, …,
  membership)` zählt die schon vorhandenen Belegungen über `Allocation.objects.filter(
  membership=…)` (alle Nutzer des Anteils). `run_lottery` nimmt einen `rule_check`-
  Callback (gebaut in `run_period_lottery` aus `rules.validate_booking` + einmalig
  materialisierten Saison-Regeln) und bündelt die schon zugeteilten Zeiträume je
  **`rule_group`** (= Mitglieds-Anteil) statt je Partei – so teilen sich Tandem-
  Partner die Grenzen, das **Budget** bleibt je Partei. Ohne `rule_group` fällt die
  Gruppe auf die Partei zurück (Regression-sicher). Ein gedeckelter Wunsch
  wird **übersprungen** (kein Verlust, kein Karma – wie ein Budget-Übersprung; wahrt
  die Strategiesicherheit). Ein Skip übergeht die Partei **nicht**: der innere
  `while`-Loop prüft in **derselben Runde** sofort den nächsten Wunsch derselben
  Partei (kein „erst nächste Runde"). Der Deckel-Check sieht nur die laufeigenen
  Zuteilungen (dokumentierte Grenze, s. ADR 0009). **Die Losung selbst läuft je
  Benutzer** (eine Los-Partei = ein `Member`), nicht je Anteil/Tandem.
- **Schulferien (`SchoolHoliday`):** ebenfalls **jährlich wiederkehrend**;
  werden im Kalender angezeigt UND setzen, wenn aktiv und mit Regelfeldern
  versehen, im Zeitraum dieselben Regeln durch wie eine Saison-Regel (leere
  Regelfelder = nur Anzeige).
- **Quartiere (`Quarter`):** Merkmal `accessible` (barrierearm/-frei) und ein
  optionaler **jährlicher Buchbarkeitszeitraum** (`season_*_month/day`, leer =
  ganzjährig). Außerhalb der Quartier-Saison ist nicht buchbar (geprüft in
  `services.range_is_released`). Felder `building`/`prefer_for_groups` (ADR 0075):
  Gruppen (ab `BookingPolicy.group_min_persons`) bekommen `prefer_for_groups`-
  Wohneinheiten (z. B. Stallgebäude) **zuerst** angezeigt – sanfte Reihung, keine
  Sperre.
- **Globale Buchungsrichtlinien (`BookingPolicy`, ADR 0075):** im Backend
  einstellbar, greifen bei der **Spontanbuchung** (nicht in der Losung).
  **Spontan-Vorausfrist** (`min_lead_days`, Default 7) – Anreise frühestens in N
  Tagen (`services.lead_time_blocker`). **Lückenfüllung** (`allow_gap_fill`, an):
  füllt eine Buchung eine freie Lücke **exakt** aus (beidseitig geschlossen –
  `services.is_gap_fill`), entfallen **Mindestnächte UND Vorausfrist** (Parallel/
  Deckel bleiben; `rules.validate_booking(skip_min_nights=…)`); greift in
  `book_spontaneous` + `adjust_allocation`. **Personenzahl außerhalb des Rahmens**
  (`allow_undersized_units`, Default an, ADR 0076): erlaubt Buchung für **mehr ODER
  weniger** Personen als ausgelegt, **hart gekoppelt** an „alles Passende belegt"
  (`services.has_fitting_free_quarter` – nur wenn keine passende freie Unterkunft mehr
  existiert; sonst gesperrt + Verweis; **barrierefrei-bewusst** über
  `need_accessible`: bei einer barrierefreien Unterkunft zählen nur andere
  barrierefreie freie Unterkünfte als „passend", #17/ADR 0078) – durchgesetzt in
  `book_spontaneous`/
  `book_confirm`/`free_quarters_for` (`Allocation.clean` prüft nur den Schalter), im UI
  als „kleiner als eure Gruppe" bzw. „größer als nötig" markiert (Badge + Hinweis).
  **Gruppe** ab `group_min_persons` (Default 6).
  **Weiche Richtwerte (nur Anzeige, ADR 0076):** **Winter**
  (`winter_guideline_nights`, `services.winter_usage`) ist ein **Mindestwert pro
  vollem Anteil** (Tage Okt–März, bei Tandems anteilig; KEIN Maximum); **Wochenenden**
  (`max_weekends_per_year`, `services.weekend_usage`, reine Zählung
  `availability.weekend_keys`) ist umgekehrt ein **Höchstwert** (warnt beim
  Annähern) – beide auf Übersicht/Buchen. **Rücksichts-Hinweis** in begehrten Zeiten
  (`services.high_demand_periods` → Partial `_high_demand_note.html`, beim Buchen
  **und** Wünschen). Die **Hilfeseite** zeigt die echten Backend-Werte
  (`services.booking_policy_summary`) und erklärt (Anker `#regeln-losung`), welche
  Regeln **beim Wunsch-Eintragen** vs. **erst in der Losung** greifen und dass
  Über-Wünschen (auch mehr Wochenenden, `services.wish_weekend_usage`) **legitim**
  ist. „Eigene Nutzung/keine Weitergabe an Externe ohne Mitglied vor Ort" bleibt
  **Richtschnur** (nicht erzwingbar).

---

## Tests (nach JEDER Änderung laufen lassen)

```bash
# 1) Reine Logik (schnell, ohne DB) — erwartet: 82 passed
PYTHONPATH=. python -m pytest tests/ -q

# 2) Integrationstests inkl. Use-Cases (DB-Ebene) — erwartet: 328 passed (4 skips)
python manage.py test booking shop

# 3) E2E-Smoke-Tests (Playwright, gegen einen LAUFENDEN Stack) — optional lokal
pip install -r requirements-e2e.txt && python -m playwright install chromium
python -m pytest tests_e2e/ --base-url http://localhost:8000   # Server muss laufen
```

Die Integrationstests liegen in `booking/tests.py` (gezielte Einzelfälle) und
`booking/tests_usecases.py` (tiefgreifende End-to-End-Szenarien — **hier neue
Use-Cases ergänzen**). Die **E2E-Smoke-Tests** (`tests_e2e/`, Playwright) prüfen die
echte Browser-/Server-Naht (gunicorn/Cookies/JS) gegen einen prod-nahen Stack
(`seed_demo --testdata` liefert die Konten `test`/`admin`/`verwaltung`; ADR 0047).
„Fertig" heißt: Suiten grün, neue/­geänderte Logik durch einen Test abgedeckt,
`python manage.py makemigrations --check` zeigt keine fehlende Migration.

**CI:** `.github/workflows/tests.yml` läuft bei jedem Push/PR — Job 1 die reinen
Tests (ohne DB), Job 2 die Integrationstests gegen echtes PostgreSQL, Job 3
**Migrations-Resilienz**: migriert eine **befüllte Alt-DB** (Booking auf 0015
zurück, Duplikate + Cascade-Wunsch erzeugen) vorwärts — fängt DB-spezifische
Migrationsfehler (Unique auf Duplikaten, „pending trigger events"), die ein
frischer Testlauf NICHT sieht. Job 4 **E2E**: baut den prod-nahen Docker-Stack
(`docker-compose.ci.yml`, gunicorn + PostgreSQL), wartet auf `/healthz/` und lässt
Playwright die kritischen Pfade durchspielen. Vor dem Pull auf die VPS am grünen
Häkchen erkennbar, ob alles passt.

**Betrieb:** `docker-compose.yml` hat einen **Healthcheck** am `web`-Container
(pingt **`/healthz/`** = DB-Query, scheitert wenn Gunicorn ODER DB weg ist, z.B.
nach Migrations-Abbruch → `docker compose ps` zeigt „unhealthy" statt nur 502 bei
Caddy). **Observability (ADR 0046):** strukturierte Logs nach stdout
(`settings.LOGGING`, Level per `LOG_LEVEL`); **Sentry** nur mit `SENTRY_DSN` aktiv
(sonst aus, `send_default_pii=False` – keine PII, DSGVO); Health-Endpoint
`views.healthz` (`/healthz/`, ohne Login, von der Aktivierungs-Sperre ausgenommen)
für Container-Healthcheck **und** externes Uptime-Monitoring. **Optionales
Redis** (Cache/Sessions/Axes-Lockout) ist über `REDIS_URL` + Profil `cache`
zuschaltbar (`docker compose --profile cache up -d`); Standard bleibt DB-Sessions.
**Performance & Skalierung (>100 gleichzeitige Nutzer, ADR 0060, Sicherheit vor
Tempo):** Gunicorn läuft als **`gthread`** (gleichzeitige Requests ≈
`GUNICORN_WORKERS`×`GUNICORN_THREADS`, Default 3×8; DB-Budget workers×threads ≤
`max_connections`, sonst PgBouncer); `CONN_HEALTH_CHECKS=True` zu `conn_max_age`.
Hot-Pfade ohne N+1 (gemessen: Startseite 23, Backend Mitglieds-Anteile 14,
Rechnungen 18 Queries – via `select_related`/`prefetch`/Annotation/Indizes, u. a.
`shop.LineItem(member,purchase,invoice)`). **Geteilter Belegungs-Cache**
(`_occupied_days_by_quarter`) ist **nur mit Redis** aktiv (LocMem = pro Worker →
stale) und wird per Signal nach jeder Buchungsänderung invalidiert (`on_commit`);
gecacht werden nur ohnehin allgemein sichtbare Belegungsdaten – die Buchung prüft
IMMER frisch unter Sperre. Die **Rechnungsnummer-Vergabe** ist gegen gleichzeitige
Checkouts gesperrt (kein doppelter `HL-…`-Stand). Lasttests in `loadtest/`
(`browse`/`booking_rush`/`shop_rush`), Tiefenverteidigungs-Constraint dokumentiert
in `docs/BETRIEB-SICHERHEIT.md`.
**Server-Umzug inkl. DB:** `ops/migrate-server.sh dump|restore` (pg_dump/psql über
den `db`-Container); Voraussetzungen + Ablauf stehen im README. **Verschlüsseltes
Backup:** `ops/backup.sh backup|restore` (pg_dump → gzip → GnuPG AES-256, optional
rclone off-site; ADR 0061). **2FA + Härtung sind umgesetzt** (s.o. „Sicherheits-
Härtungspaket"); **IBAN-Feldverschlüsselung ist vorbereitet, aber inaktiv**.
**Weiteres Hardening (Borg-Append-only-Backups, LUKS) bleibt GEPLANT** –
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

**Mit uv (schneller, reproduzierbar – optional):** Abhängigkeiten + Werkzeuge
stehen in `pyproject.toml` (Quelle für `uv`; `uv.lock` pinnt die Versionen). Das
Docker-Image installiert bewusst weiter aus `requirements.txt` (gleiche Pins) –
beide synchron halten. Lokal: `uv sync --extra dev --extra test` (legt `.venv` an),
dann `uv run python manage.py …`. **Type-Check:** `mypy` (Konfiguration in
`pyproject.toml`) prüft die **Django-freie reine Logik** (lottery/availability/
rules/validation/external/beds24/fairness) – läuft auch im CI-Job „reine Logik".

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
Warte-Seite `pending` um (Verwaltungs-/Admin-Konten ausgenommen). **Damit die
Verwaltung neue Konten schnell freischaltet:** (a) bei jeder Selbstregistrierung
geht eine E-Mail an die Verwaltung (`services.notify_admins_new_user` →
`OpsConfig.admin_emails`), und (b) die **Backend-Startseite** zeigt oben den
Abschnitt **„Neue Benutzer – noch ohne Mitglieds-Anteil"** mit allen noch nicht
zugeordneten Konten (`services.users_without_membership` = aktive Konten ohne
`Share`, ohne Admin-/Staff-/Verwaltungs-Konten und ohne externe Gäste; gerendert
über `RehofAdminSite.index`-Extra-Context in `custom_index.html`). **Geführtes
Onboarding (ADR 0056):** Eigene Backend-Seite **„Neue Benutzer (Zuordnung)"**
(Proxy-Modell `PendingUser` unter „Benutzer & Mitglieder", `PendingUserAdmin` →
`templates/admin/onboarding.html`) ordnet jedes Konto in **wenigen Klicks** zu –
**als Mitglied** (`services.onboard_as_member`: Profil + `Share` an bestehendem/
neuem Anteil → kann buchen), **nur Hofladen/Terminal** (`services.onboard_as_terminal`:
Profil als Hofladen-Gast `is_external=True`+`terminal_enabled` → PIN setzt die Person
selbst, keine Buchung), oder **deaktivieren/löschen** (unbekannt; `services.
deactivate_account`). JS-frei (pjax-sicher), POST → voller Reload. Das Startseiten-
Panel verlinkt auf diese Seite. **Backend-Aufbau einheitlich (ADR 0055):** Statt
die Standard-Seitenleiste zu nutzen (aus, `enable_nav_sidebar=False`), steht oben
auf **jeder** Admin-Seite derselbe **Navigator** (Suche + die 5 fachlichen Bereiche
als kollabierbare `<details>`, aus `available_apps`) – eingehängt über
`{% block pretitle %}` in `base_site.html` (`templates/admin/_rehof_navigator.html`).
Der Navigator ist **einklappbar** (Leiste „Suche & Bereiche · <Standort>"; **per
Default AUF** – Desktop UND mobil, Wahl gemerkt; ADR 0065 kehrt den früheren
mobilen Default-Collapse um, damit man sofort sieht, was man tun kann) und arbeitet
als **Akkordeon** (immer nur EIN Bereich offen → begrenzte Höhe, ADR 0057); der
Eintrag „Neue Benutzer (Zuordnung)" trägt ein **Badge** mit der Anzahl offener Konten
(`RehofAdminSite.each_context`). Der **„Neue Benutzer"-Kasten** auf der Startseite ist
ein per Default **eingeklapptes** `<details>` mit Anzahl-Badge (Dringlichkeit sichtbar).
Der gewählte Bereich/die Liste wird **darunter** aufgebaut, beim Klick **ohne
Neuladen** (kleiner **pjax**-Layer in `base_site.html`: tauscht nur `#content` unter
dem Navigator, lädt fehlende Stylesheets nach, `pushState`/`popstate`, harter
Fallback auf normale Navigation). **Bewusst voller Reload** bei Änderungs-/Anlage-
Formularen und POSTs (jQuery/Widgets zuverlässig; Struktur bleibt durch den
server-gerenderten Navigator dennoch gleich). Cookies/Sessions
sind gehärtet (HttpOnly, SameSite=Lax, Secure in Prod). OIDC/Keycloak-Naht
bleibt in `settings.py` markiert.

**Rollen Admin/Verwaltung** (`booking/permissions.py`): zwei getrennte Rollen
statt eines einzelnen `is_staff`-Flags. **Admin** = Django-**Superuser** → volles
Backend `/admin/`, darf Buchungen ändern und Losungen starten. **Verwaltung** =
Mitglied der Rolle **„Verwaltung“** (Konstante `VERWALTUNG_GROUP`) **oder** Admin
→ nur das Dashboard `/verwaltung/` (Buchungen/Losung lesend, pflegt dort den
Hofladen-Katalog), **kein** Backend. Helfer: `is_admin`/`is_verwaltung`/
`ensure_verwaltung_group`; die Rolle legt Migration `booking/0027_verwaltung_group`
an. **„Rolle" statt „Gruppe" (ADR 0087):** im Backend heißt Djangos `auth.Group`
über das Proxy-Modell `booking.Rolle` durchgängig **„Rolle"** (die rohe „Gruppen"-
Liste ist ausgeblendet; reines Proxy, keine Migration nötig). „Admin"/„Mitglied"
sind KEINE Gruppen: Admin = Superuser-Flag, Mitglied = vorhandenes `Member`-Profil –
ein Superuser ist damit **immer** auch Verwaltung (Admin-ohne-Verwaltung gibt es
nicht). `booking/context_processors.py` stellt `is_admin`/`is_verwaltung` **plus**
`can_book`/`is_passive`/`member_has_bookings` (Mitgliedsstatus, s.u.) allen
Templates bereit – die Nav gated darüber. Zuordnung = ein Häkchen: den User im
Backend der Rolle „Verwaltung“ hinzufügen. **Rollen-Matrix getestet** in
`booking/tests_roles_status.py` (jede Kombination Admin/Verwaltung/Mitglied + Status
→ erwartete Navigation & Zugriffe).

**Mitgliedsstatus (datumsgesteuert, ADR 0087):** `Member.passive_from`/
`excluded_from` (Daten, leer = aktiv). `Member.status_on(datum)`→`active`/`passive`/
`excluded`; `status`/`can_book`/`is_passive`/`has_bookings` als Properties. **passiv**
= Login/Hofladen an, **keine neuen Buchungen/Wünsche/Losung** (serverseitig gesperrt
in `book_spontaneous`/`add_wish`/`submit_wishlist`/`run_period_lottery` + Views-Guard
`_block_if_not_bookable`), bestehende Buchungen bleiben; Nav zeigt „Meine Buchungen"/
„Übersicht" nur bei vorhandenen Buchungen. **ausgeschieden** = `User.is_active=False`
(Login aus) – der tägliche Scheduler-Schritt `apply_member_status`
(`services.apply_member_status_transitions`) vollzieht den Übergang zum
`excluded_from`-Datum. Pflege im **Backend** am Benutzer (Fieldset „Mitgliedsstatus")
mit dem **Ausscheide-Workflow** (`MemberProfileForm`): liegt „Ausgeschieden ab" vor
bestehenden Buchungen, verlangt das Formular die Freigabe „Zukünftige Buchungen …
löschen" (storniert sie) – sonst wird das Datum abgelehnt. **#71:** Mitgliedsstatus
ist der **oberste** Admin-Filter (`MemberStatusFilter`).

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
- **CSP (ADR 0061):** strikte, nonce-basierte Content-Security-Policy. **Jedes neue
  `<script>` braucht `nonce="{{ request.csp_nonce }}"`**, und **keine Inline-Event-
  Handler** (`onclick`/`onsubmit`/`onchange`) – stattdessen die delegierten
  `data-*`-Handler in `base.html` (`data-confirm`, `data-autosubmit`, `data-nav-tpl`,
  `data-pin-check`, `data-filename-target`, `data-reload`) bzw. im Backend
  `base_site.html` (`data-confirm`). Keine externen Skripte/CDNs (alles `'self'`).
  `booking/tests_csp.py` wacht über Header + nonce + handler-freie Seiten.
- **Template-Kommentare nur EINZEILIG:** Djangos `{# … #}` wird über `tag_re` **ohne**
  `re.DOTALL` erkannt – ein über mehrere Zeilen gehender `{# … #}`-Kommentar wird
  **nicht** entfernt und erscheint als sichtbarer Text. Mehrzeilige Erklärungen daher
  als `{% comment %}…{% endcomment %}` schreiben (oder mehrere einzeilige `{# … #}`).

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
  **Rechnungs-PDF (WeasyPrint) erledigt**. **Web-Push (mobil) erledigt** (ADR 0044,
  an die `Notification` gekoppelt). Offen: Losergebnis-PDF + Massenmail.
- **Losung rückgängig/bestätigen** – **erledigt** (Review-Workflow, s.o.).
- **Kontoabgleich** – **erledigt** (CSV + CAMT.053; MT940 als Parser leicht
  ergänzbar in `shop/bankimport.py`).
- **Backup & Hardening** (geplant, nicht umgesetzt): Blueprints in
  `docs/BETRIEB-SICHERHEIT.md`.
- Verwaltungs-Mails/Putzliste später optional als **Datei-Anhang** (xlsx/CSV)
  statt nur inline (OutboxEmail um Anhang erweitern).
- Drag-and-Drop der Wunschliste auf Touch-Geräten (Pfeiltasten sind Fallback).
- **Mehrere Benutzer pro Mitglied** (Mehrfach-Login, ADR 0069): Benutzer↔Mitglied ist
  heute **1:1**. Geplant: Entkopplung auf **n:1** (mehrere Logins teilen ein Mitglied
  = gleiche Wünsche/Buchungen/Budget, je Login eigene Anmeldedaten, Benachrichtigungen
  an alle Adressen) über ein Verknüpfungs-Modell + Migration der bestehenden
  1:1-Zuordnungen. Bewusst zurückgestellt (Auth-Umbau). **Kein Tage-Deckel** je
  Mitglied – Tandem-Anteile summieren sich frei (Verwaltung steuert über „frei/
  vergeben").

---

## Typischer Arbeitsablauf für Claude Code

1. Branch anlegen (`git checkout -b fix/...` bzw. `feat/...`).
2. Bei Bugs zuerst einen **reproduzierenden Test** schreiben, dann minimal fixen.
3. Beide Test-Suiten grün machen.
4. Klein und nachvollziehbar committen (deutsche Commit-Message).
