# Umsetzungs-Übersicht zum Tester:innen-Feedback (Feedback2.xlsx)

Stand: 2026-07-05 · Branch `claude/friendly-meitner-b9ls5y`

Diese Übersicht ordnet **jedem** Punkt aus `Feedback2.xlsx` einen Status zu. Für die
**bewusst nicht (oder nur teilweise) umgesetzten** Punkte steht jeweils eine
**Begründung**. Legende:

- ✅ **umgesetzt** – im Code erledigt (Verweis auf ADR/Datei).
- 🟡 **teilweise / konfigurierbar** – Kern erledigt, ein Rest ist Konfiguration oder
  bewusst abgegrenzt (mit Begründung).
- ⚙️ **Datenpflege** – Funktion/Feld existiert; korrekte Werte pflegt die eG im Backend.
- ⛔ **bewusst nicht umgesetzt** – mit Begründung.
- 💬 **Lob / Frage** – keine Änderung nötig.

Die Punkte 1–26 (Judith, Perspektive Mitglied) trugen bereits einen Status von Moritz;
sie sind hier zur Vollständigkeit mit aufgeführt.

---

## Perspektive Mitglied (Judith, #2–#26)

| # | Titel | Status | Umsetzung |
|---|-------|--------|-----------|
| 2 | Mehrfach-/Überlappungswünsche gleiche Unterkunft | ✅ | Wunsch-Obergrenze je Periode `BookingPolicy.max_wishes_per_period` (Backend, ADR 0078); Überlappung derselben Person unterbunden |
| 3 | Begriff „Losungsbudget“ unklar | ✅ | Wortwahl vereinheitlicht (Wunsch-Budget = halbe Tage, ADR 0073) |
| 4 | Budget-Überschreitung ohne Feedback | 🟡 | Klare Anzeige + Backend-Regel; Kürzungs-/Skip-Logik dokumentiert |
| 5 | Wünsche an reale Verfügbarkeit koppeln | ✅ | `max_wishes_per_period` + Nachfrage-Ampel `quarter_wish_counts` |
| 6 | Visuelle Priorisierung falsch gewichtet | ✅ | Hervorhebung auf das Budget umgestellt |
| 7 | Wochenend-Richtwert ohne Konsequenz | ✅ | Erklärtext + Hilfe (`weekend_usage`, ADR 0076) |
| 8 | Wechselwünsche könnten stören | ✅ | Nur bei **exakt gleichem** Zeitraum; je Mitglied abschaltbar (`accept_swap_requests`, ADR 0077/0078) |
| 9 | Tageskontingent-Zahlen widersprüchlich | ✅ | Konsistente Budget-Rechnung |
| 10 | „3 Tage verfügbar“ ohne „Kontingent“ | ✅ | Beschriftung ergänzt |
| 11 | Interner Entwicklerkommentar sichtbar | ✅ | Mehrzeiliger `{# #}`-Leak behoben + Template-Guard `tests/test_templates.py` |
| 12 | „ggf. nicht geeignet“ umständlich | ✅ | Konkreter Grund („Für N Pers. nicht geeignet“) |
| 13 | Spontanbuchungs-Hinweis wiederholt sich | ✅ | Einmal zentral statt je Quartier |
| 14 | „Weiter“ trotz fehlender Abreise aktiv | ✅ | Button deaktiviert bei unvollständiger Auswahl |
| 15 | Kalender „9/10“ missverständlich | ✅ | „N freie Unterkünfte“ je Tag |
| 16 | Lückenbuchung/Lücken unsichtbar | ✅ | „Kurze freie Lücken zum Füllen“ + Gap-Fill (`short_free_gaps`, `allow_gap_fill`, ADR 0075/0078) |
| 17 | 2 Personen in großer Unterkunft | ✅ | `allow_undersized_units` (ADR 0076) |
| 18 | Preis Endreinigung falsch | ⚙️ | Preis im Hofladen-Katalog pflegbar (70 €) |
| 19 | Kein „Zurück“ in Bestätigung | ✅ | Zweistufiger Flow `book → book_confirm` mit Zurück |
| 20 | „Wer ist noch da“ wirkt wie DM | ✅ | Rein informativ (`concurrent_split`), Tausch klar getrennt |
| 21 | Begriff „Spontanbuchung“ unklar | ✅ | Tooltip/Erklärung |
| 22 | Solidaritäts-Pool (Lob) | 💬 | — |
| 23 | Pool-Entnahme auf Spende begrenzt | ✅ | Entnahme unabhängig von Spende, gedeckelt (`pool_withdraw`, ADR 0064) |
| 24 | Menü links statt rechts | ✅ | `.sidenav` `order:-1` (ADR 0078) |
| 25 | Automatischer Logout | ✅ | Session-/Idle-Verhalten; Terminal mit Idle-Logout |
| 26 | Zahlung nur selbst als bezahlt | 🟡 | `allow_self_report_paid` (Backend); **final bestätigt die Verwaltung** über den Kontoabgleich (#26/ADR 0078). Selbstmeldung ist optional abschaltbar |

---

## Perspektive User/Admin (Sophie, #27–#46)

| # | Titel | Status | Umsetzung |
|---|-------|--------|-----------|
| 27 | Kleinunternehmer-Regel auf Rechnung falsch | ⚙️ | USt-Modus im `ShopConfig` umschaltbar (`small_business`); **korrekte Stammdaten der Vielleben eG hinterlegen** – Snapshot je Rechnung (ADR 0041) |
| 28 | Endreinigung gehört in Buchung, nicht Hofladen | ✅ | Bestätigungspflichtige Leistung: Anfrage im Buchungsschritt → BL bestätigt/lehnt ab (`ServiceRequest`, ADR 0081); aus dem Mitglieder-Katalog ausgeblendet |
| 29 | Direkt eingegebenen Zeitraum sehen | ✅ | Sticky-Leiste „Anreise → Abreise · N Nächte“ mit Datum + Reset |
| 30 | Stornierte Buchungen nicht sichtbar | ✅ | `CancellationLog` „Zuletzt storniert“ (ADR 0082) |
| 31 | Bettenzahl (Salix) stimmt nicht | ⚙️ | `Quarter.max_occupancy` je Unterkunft pflegen |
| 32 | Fehler bei zu vielen Betten + Rauswurf | ✅ | Korrektur bleibt auf der Seite, klarer Hinweis „Platz für höchstens N“ (#32) |
| 33 | Gebuchte Endreinigung nicht dargestellt | ✅ | Status angefragt/bestätigt/abgelehnt in „Meine Buchungen“ (#33/ADR 0081) |
| 34 | Buchungen als Kalender statt Liste | ✅ | Kompakte Karten + Aufklapper „Details & Aktionen“ (#34) |
| 35 | Übertragungen (Lob) | 💬 | — |
| 36 | Zahlungserinnerung manuell auslösen | ✅ | Button je Rechnung (`remind_one`) + Sammel-Erinnerung; **kein** Auto-Konto-Abruf (#36) |
| 37 | Endreinigung raus aus Hofladen | ✅ | Siehe #28 (ADR 0081) |
| 38 | Reihenfolge wie beds24 + neue Einheiten | 🟡 | `Quarter.sort_order` (beds24-Reihenfolge, #38); **neue Einheiten (Zelt/Bully/Kaminlounge …) als Quartiere anlegen** (Datenpflege) |
| 39 | Belegungsplan drucken (1–4 Wochen) | ✅ | `plan_pdf` Querformat, wählbare Wochen (#39) |
| 40 | Doppelbelegung/Überlagerung + Breite | ✅ | Halbtag-Rendering am Wechseltag, kein Schein-Overlap; voller Tape-Chart (#40/ADR 0083) |
| 41 | Konkretes Startdatum wählen | ✅ | `from`/`weeks`, 1/2/4 Wochen (#41) |
| 42 | Zeilen zwischen Quartieren trennen | ✅ | Gebäude-Bänder statt Zebra (#42) |
| 43 | Sonne-Icon für Verwaltung irritiert | ✅ | Klemmbrett-Icon (#43) |
| 44 | Mail-Logik office/gast/team | 🟡 | Getrennte, frei konfigurierbare Rollen-Adressen: Verwaltung (`admin_emails`), Reinigung (`cleaning_emails`, leer = Verwaltung), **Kontakt BL/Technik** (`contact_email_bl/_tech`, B5/ADR 0091). Das Reinigungsteam bekommt bewusst keine Mail-Pflicht (leer lassen → geht an BL) |
| 45 | ER-Entscheidung nachträglich ändern | ✅ | `er_decision_lock_days`, revidierbar bis Frist (#45/ADR 0081) |
| 46 | Reinigungsliste als Druck statt Mail + im Plan sichtbar | 🟡 | Endreinigung im Plan als dezentes 🧹 (umgesetzt). **Reinigungsliste-Druck:** siehe #60 (Begründung unten) |

---

## Perspektive Betriebsleitung (Judith, #46b–#67)

| # | Titel | Status | Umsetzung |
|---|-------|--------|-----------|
| 46b | „X frei“ – Bezug unklar | ✅ | „N freie Unterkünfte“ je Tag im Plan-Kopf |
| 46c | „extern“ ohne Name/Kontakt | ✅ | Rollen-abhängig: Verwaltung sieht Klartext-Name/Personen/Kontakt (#46b/#47) |
| 47 | BL-Tages-Popup nicht kontextgerecht | ✅ | `day_detail` rollen-abhängig (Verwaltung: Kontakt/Anreise statt Buchen) |
| 48 | Nav „Tage übertragen/Profil“ führt ins Leere | ✅ | Rollen-reine Nav `{% if user.member %}` (B1/ADR 0084) |
| 49 | Verwaltung als eigene Rolle | ✅ | Rolle „Verwaltung“ + rollen-reine Nav/Unterpunkte (B1/ADR 0084/0085) |
| 50 | BL bucht Gäste direkt ohne Ansichtswechsel | 🟡 | **Begründung unten** – Backend-Buchung mit Audit + Mitglied-Benachrichtigung (B8/ADR 0094) statt zweitem Buchungs-Flow |
| 51 | Verwaister Satz „Beide melden sich …“ | ✅ | Dashboard-Text im Zuge ADR 0085 überarbeitet (Satz entfernt) |
| 52 | Export wirft Error 500 | ✅ | `exports.xlsx_response`/CSV mit Formel-Injektions-Schutz; Dashboard-Exporte grün (CI-getestet) |
| 53 | Rechnungs-/Auszug-Upload defekt | ✅ | Kontoabgleich `reconcile.import_bank_statement` (CSV/CAMT.053), 10 MB-Limit, XXE-Schutz |
| 54 | Mahnstatus/Verlauf fehlt | 🟡 | „zuletzt erinnert am“ + idempotentes `send_payment_reminder`. **Mehrstufige Eskalation (1./2. Mahnung)** siehe Begründung unten |
| 55 | Erinnerung vor Versand anpassen | ⛔ | **Begründung unten** |
| 56 | Externe/Reinigungs-Rechnungen fehlen | ✅ | Split: `ExternalInvoice`-Proxy (Gäste) + Mitglieder-Rechnungen (ADR 0049) |
| 57 | Rechnung anklicken/Detail | ✅ | Rechnungs-Detail als HTML + **PDF** (`shop_invoice_pdf`, Staff sieht alle) |
| 58 | „Katalog pflegen“ als Menüpunkt | ✅ | Verwaltungs-Unterpunkt „Hofladen-Katalog“ (ADR 0085) |
| 59 | Verwaltungsseite zu lang | ✅ | Eigene gerouteten Unterseiten + Menü (ADR 0085) |
| 60 | Reinigungsliste drucken | 🟡 | **Begründung unten** |
| 61 | Sperr-/Reparaturzeiten hinterlegen | ✅ | `QuarterBlock` Sperrzeit je Quartier, eigene Seite `verw_sperrzeiten` (#61/ADR 0086) |
| 62 | Zustellbett je Buchung | ✅ | `Allocation.special_requests` (#62) |
| 63 | Auslastung je Unterkunft filterbar | ✅ | `quarter_occupancy_ampel` je Unterkunft (#63) |
| 64 | Zielauslastung + Ampel | ✅ | `Quarter.target_occupancy` + 🟢🟡🔴-Ampel (#64) |
| 65 | Mitgliederliste mit Kontaktdaten für BL | ✅ | `verw_mitglieder` inkl. Telefon (B3); Profil pflegt `Member.phone` |
| 66 | Hilfesektion redaktionell bearbeiten | 🟡 | **Begründung unten** – Prosa in editierbaren Inhalts-Dateien (B7/ADR 0093) |
| 67 | Ausgehende Benachrichtigungen konfigurierbar | ✅ | Benachrichtigungs-Framework: Katalog + `NotificationSetting` (an/aus, Empfänger, Frequenz) im Backend (B2/ADR 0089) |

---

## Perspektive Admin (Judith, #68–#87)

| # | Titel | Status | Umsetzung |
|---|-------|--------|-----------|
| 68 | Hunde/Kinder bei Buchung | ✅ | `special_requests` (#68) |
| 70 | PW-Versand zu nah an Löschen/Anonymisieren | ✅ | Starke Aktionen doppelt bestätigt + optisch getrennt (`base_site.html`, CSP-konform) |
| 71 | Mitgliedsstatus als oberster Filter | ✅ | `MemberStatusFilter` (aktiv/passiv/ausgeschieden) zuoberst (#71/B1) |
| 72 | Filter „Anzahl anzeigen/verstecken“ reagiert nicht | ✅ | „Neue Benutzer“-Kasten ist ein `<details>` mit Anzahl-Badge (pjax-sicher, ADR 0055/0057) |
| 73 | Paginierung bei 56 Datensätzen | 🟡 | **Begründung unten** (Django-Admin paginiert ab 100) |
| 74 | „Gruppe“ → „Rolle“ | ✅ | `Rolle`-Proxy (verbose_name „Rolle“), Group ausgeblendet (#74/B1) |
| 75 | Verwaltung/Admin ohne MG-Unterbau | ✅ | Rollen-Konzept + rollen-reine Nav (B1/ADR 0084); Verwaltungs-Konto braucht kein Mitglieds-Profil |
| 76 | Nächte-Übertrag +/- korrekt | ✅ | `NightTransfer` → `effective_annual_budget` (test-gedeckt) |
| 77 | Benennung Konto ↔ Anteil inkonsistent | 🟡 | **Begründung unten** (Person vs. Anteil sind bewusst getrennt, ADR 0068/0070) |
| 78 | „Wunschtage“ auf Nutzerebene unklar | ✅ | Wunsch-Budget = **halbe Tage, abgerundet**, abgeleitet (nicht je Anteil gespeichert), Hilfe erklärt es (ADR 0073) |
| 79 | Wunschperiode mit Zeitraum (Lob) | 💬 | — |
| 80 | Äquivalenzklassen gruppierbar? | ✅ | `EquivalenceClass` aktiv (Ausweichen in der Losung nutzt sie) |
| 81 | Buchungsregeln (Lob) | 💬 | — |
| 82 | Saisonregeln als Von-Bis-Picker | ⛔ | **Begründung unten** |
| 83 | Tab „Zuteilungen“ vs. „Buchungen“ | 🟡 | „Zuteilung“ trägt eine erklärende `description`; „Anstehende Buchungen“ als eigener Proxy. Reine Umbenennung offen (kosmetisch) |
| 84 | Hunde/Kinder + internes Kommentarfeld | ✅ | `special_requests` + `internal_note` (nur BL/Team, #84) |
| 85 | Benachrichtigungen: Liste/Bearbeitung fehlt | ✅ | `NotificationSettingAdmin` Katalog-Übersicht aller Ereignisse (#85/B2) |
| 86 | Nur Einzelmitglied, kein Broadcast | ✅ | Rundnachricht an Rollen (`broadcast_message`, `verw_rundnachricht`, B4/ADR 0090) |
| 87 | Autom. Benachrichtigung vor Versand anpassen | ⛔ | **Begründung unten** (wie #55) |

---

## Begründungen – bewusst nicht / nur teilweise umgesetzt

**#50 – BL bucht Gäste im eigenen Frontend ohne Ansichtswechsel.**
Stellvertretende Buchungen laufen bewusst über **das Backend** (`AllocationAdmin`), nicht
über einen zweiten Buchungs-Flow im Frontend. Grund: die Domänenregeln (keine
Doppelbuchung, Personen-/Saison-/Deckel-Prüfung) greifen dort bereits vollständig
(`Allocation.clean`, ADR 0045); ein paralleler Frontend-Pfad würde diese Logik doppeln
und ist eine große Fehlerquelle. Neu ist die **Nachvollziehbarkeit + Fairness**: jede
Backend-Buchung trägt `created_by`, und das Mitglied wird über Anlage/Änderung/Storno
benachrichtigt und sieht die Marke „von der Verwaltung angelegt“ (B8/ADR 0094). Ein
echter One-Screen-BL-Buchungsdialog bleibt als späterer Ausbau möglich.

**#55 / #87 – Ausgehende Erinnerungen/Benachrichtigungen vor dem Versand einzeln
bearbeiten (Vorschau-Editor).** Bewusst zurückgestellt (Tester:innen-Priorität
„nice-to-have“). Editierbar sind **die Vorlagen** (Benachrichtigungs-Katalog + Frequenz/
Empfänger je Ereignis, B2/ADR 0089) und **Rundnachrichten** als frei getippter Text
(B4/ADR 0090). Ein Pro-Empfänger-Vorschau-/Freigabe-Schritt würde den entkoppelten
Outbox-Versand (Massenmail-tauglich, robust) aufbrechen und je Mail eine manuelle
Freigabe verlangen – Aufwand/Nutzen ungünstig. Empfehlung: bei Bedarf später ein
optionaler „Entwurf → Freigabe“-Status auf `OutboxEmail`.

**#60 / #46 – Reinigungsliste als Druckdokument.** Aktuell exportiert die Reinigungsseite
xlsx **und** CSV, und der Belegungsplan lässt sich als Querformat-PDF drucken (`plan_pdf`,
#39). Ein **dedizierter „Drucken“-Knopf für die reine Reinigungsliste** ist noch nicht
gebaut. Grund für die Zurückstellung: der Plan-PDF-Druck deckt den Aushang bereits ab,
und die xlsx/CSV-Datei lässt sich lokal drucken. Ein eigener Listen-PDF-Endpoint (analog
`plan_pdf`) ist als kleiner Folgeschritt vorgemerkt – rein additiv, ohne Logikänderung.

**#66 – Hilfesektion CMS-artig durch BL bearbeiten.** Teilweise umgesetzt (B7/ADR 0093):
die redaktionelle **Prosa** der Hilfe (Warteliste/Gemeinschaft/Hofladen/Tage) liegt jetzt
in **editierbaren Inhalts-Dateien** (`booking/help_content/*.md`), getrennt vom Markup und
**sicher** gerendert (escape-first, kein SSTI/HTML-Injektion). Damit ist eine Textänderung
ein risikoarmer Ein-Datei-Edit statt eines Eingriffs ins 500-Zeilen-Template. **Bewusst
(noch) kein Laufzeit-CMS im Backend:** eine DB-Redaktion mit Roh-HTML öffnet eine
XSS-Fläche und ist für „nice-to-have“ überdimensioniert; die Datei-Lösung ist die saubere
Vorstufe. Die algorithmisch-reichen Abschnitte (Auslosung/Formeln/SVG) bleiben im Template.

**#73 – Paginierung der Benutzerliste.** Der Django-Admin **paginiert standardmäßig ab
100 Einträgen** – bei 56 Konten erscheint korrekt eine Seite. Es besteht kein Bug; wächst
die eG über 100 Konten, genügt ein `list_per_page`-Wert (einzeilige Ergänzung). Bewusst
keine vorzeitige Änderung.

**#77 – „Tandem Vera 3“ vs. „Vera 29“ inkonsistent.** Das ist **kein Bug, sondern das
bewusste Datenmodell** (ADR 0068/0070): **Person/Login** (`Member`) und **eG-Anteil**
(`Membership`, n:m über `Share`) sind getrennt, weil ein Anteil geteilt (Tandem) und eine
Person mehrere Anteile halten kann. Die scheinbar „doppelten“ Namen sind zwei
verschiedene Objekte (Konto vs. Anteil), beidseitig verlinkt. Verbesserbar ist die
**Beschriftung** (klarere Anteils-Labels) – reine Datenpflege, keine Modelländerung.

**#82 – Saisonregeln als Von-Bis-Kalender-Picker.** Bewusst als Monat/Tag-Felder belassen:
`SeasonRule`/`SchoolHoliday` sind **jährlich wiederkehrend – ohne Jahr** (die Saison gilt
jedes Jahr neu). Ein „Von-Bis-Datum“-Picker suggeriert ein konkretes Jahr und passt
fachlich nicht; die getrennten Monat/Tag-Felder bilden die Wiederkehr korrekt ab. Ein
reiner Komfort-Picker (Monat/Tag ohne Jahr) wäre kosmetisch und ist niedrig priorisiert.

---

## Nicht in dieser Iteration (Roadmap)

Bereits in der Roadmap/README als offen dokumentiert und **nicht** Teil dieser
Feedback-Runde: Online-**Anzahlung** + automatische Storno-Erstattung (heute manuell),
Losergebnis-PDF, Mehrfach-Login je Mitglied (n:1, ADR 0069), Borg-Append-only-Backups/
LUKS, IBAN-Feldverschlüsselung (vorbereitet, inaktiv). Siehe `CLAUDE.md` → „Offene
Punkte / Roadmap“.
