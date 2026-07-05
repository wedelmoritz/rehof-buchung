# 0087 – Benachrichtigungs-System, Mitgliedsstatus, Rollen & Kontakt (Konzept-Anker)

## Status

Accepted (2026-07-05) · Anker für die Batches B1–B7 (jede Batch ergänzt ggf. einen eigenen ADR)

> Tester-Feedback #44, #49/#74/#75, #55/#67/#85/#86, #71, #82 sowie neue Wünsche aus
> der Abstimmung (datumsgesteuerter Status, Kontaktweg, Nicht-buchbar-UI).

## Kontext

Aus dem BL-/Admin-Feedback ergaben sich mehrere verwandte Themen rund um
Benachrichtigungen, Rollen und Mitgliedsstatus. Statt Einzellösungen legen wir ein
**gemeinsames Fundament** und dokumentieren die Grundsatz-Entscheidungen hier.

## Entscheidungen

### 1. Editierbarkeit: Hybrid (Text = Code, Betrieb = Backend)
- **Vorlagen-TEXT** (Betreff/Body/Formatierung/Variablen) liegt **als Konfigurations-
  Datei im Repo** – versioniert, review-/rollback-fähig, testbar. Ändern selten; BL
  wünscht Änderung → wird eingepflegt → Deploy. Gilt genauso für **Hilfetexte** (B7).
- **Betriebs-Parameter** (Empfänger-Adressen, an/aus je Ereignis, Frequenz/Tag,
  PDF-Anhang, Vorlauftage) liegen **im Backend** (Daten, kein Injection-Risiko, BL-
  Self-Service).
- **Variablen sicher**: `string.Template.safe_substitute` gegen eine feste Allow-List
  je Ereignis – **kein** Template-Engine auf gespeicherten Strings (SSTI-frei).
- Begründung: SSTI-/Compliance-Risiko der Online-Bearbeitung vermeiden; Formatierung
  lebt beim Code; billige Deploys; konsistent mit der ADR-/reine-Logik-Kultur.

### 2. Benachrichtigungs-Framework (B2)
- **Katalog-Registry** (Config-Datei) je `event_key`: Betreff, Body, erlaubte
  Variablen, Standard-Empfänger, optionaler PDF-Typ.
- **Ein Dispatcher** rendert sicher, hängt ggf. PDF an, stellt in die **Outbox**
  (asynchron/gechunkt – gut bei parallelen Zugriffen) und legt In-App-`Notification`
  an. Ereignis-getrieben via `transaction.on_commit`; geplante Übersichten im
  `run_scheduler` **idempotent je Periode**.
- **Backend-Settings** je Ereignis (an/aus, Empfänger, Frequenz, Tag, PDF).

### 3. Mitgliedsstatus (B1, datumsgesteuert)
- `Member.passive_from` / `Member.excluded_from` (Daten, optional). Effektiver Status
  berechnet: `heute ≥ excluded_from → ausgeschieden` · `≥ passive_from → passiv` ·
  sonst `aktiv`.
- **passiv**: Login an, Hofladen an, **keine neuen Buchungen/Wünsche/Losung**,
  bestehende Buchungen bleiben; Nav zeigt „Meine Buchungen"/„Übersicht" nur, wenn
  Buchungen existieren.
- **ausgeschieden**: `User.is_active=False` (Login aus); ein täglicher Scheduler-
  Schritt vollzieht den Übergang zum `excluded_from`-Datum.
- **Ausscheiden mit Zukunftsbuchungen**: Backend zeigt/fragt (löschen? → Storno-
  Service; ablehnen → Ausschluss zu diesem Datum nicht möglich). Bei „passiv"
  informativ (Buchungen bleiben).
- **Vorwarnung**: BL-Benachrichtigung, wenn ein Statuswechsel in ≤ N Tagen greift.
- Löst zugleich **#71** (Status als oberster Admin-Filter). Durchsetzung
  serverseitig (nicht nur Nav).

### 4. „Gruppe" → „Rolle" (B1)
- Proxy-Modell `Rolle` auf `auth.Group` (verbose_name „Rolle"), im Backend als
  „Rollen" geführt; die rohe „Gruppen"-Liste ausgeblendet. Rein kosmetisch, kein
  Datenumbau. Getrennte Rollen-Accounts (#75) bleiben **abgelehnt**.

### 5. Rundnachrichten & Kontakt (B4/B5)
- **Ausgehend (staff→Rolle, B4):** Broadcast-Werkzeug an *aktive / alle inkl. passiv
  / BL / Admins* über In-App + E-Mail (Opt-in) + Push, via Outbox. Nur Admin/BL.
- **Eingehend an Mitglieder-Verteiler:** **NICHT in der App** (Mailinglisten-Server =
  Spam/Spoof/Loop/Moderation/Abuse-Risiko). Stattdessen **externe Verteilerlisten**
  beim Mailprovider; die App liefert einen **Rollen-Empfänger-Export** zum Sync.
- **User→Staff-Kontakt (B5):** **In-App-Kontaktformular** (in der Hilfeseite) mit
  Betreff-Routing an **konfigurierbare Rollen-Aliase** + Anzeige der Adressen +
  Fuß-Link „Kontakt". Kein Rendering von Nutzertext (Plaintext) → **keine SSTI**;
  abzusichern sind Header-Injection (CR/LF), Auth-only und Rate-Limit.

### 6. Nicht-buchbare Quartiere sichtbar machen (B6)
- `split_quarters_for_range` liefert `frei / belegt / nicht_verfügbar[grund]`. Die
  Buchen-Seite zeigt nicht buchbare Quartiere **ausgegraut, klein, unten** mit
  prägnantem Grund (außerhalb Saison / vorübergehend gesperrt / noch nicht
  freigegeben). Wünsche bleiben serverseitig gesperrt (bereits umgesetzt). Kleiner
  „buchbar von–bis"-Hinweis je Quartier. Mobiler Umbruch langer Quartiernamen im
  Belegungsplan.

### 7. Saisonregeln (#82) – abgelehnt
`SeasonRule` wird als Monat/Tag getippt (kein Kalender-Picker). Der Buchbarkeits-
Zeitraum je Quartier (`Quarter.season_*`) existiert und wird durchgesetzt; er wird
den Nutzern nun sichtbarer gemacht (B6).

## Querschnitt (Leitplanken)
Effizienz/Parallelität (Outbox asynchron, eine Query je Rolle, idempotente Jobs,
`on_commit`), Security (SSTI-frei, kein In-App-Inbound, serverseitige Gates,
Rate-Limit), moderne Architektur (Dispatcher + Katalog + Settings, Wiederverwendung
Outbox/Scheduler/WeasyPrint), moderne UX (rollen-reine Nav, ausgegraute Zustände).

## Batch-Reihenfolge
B1 Rolle+Status · B2 Framework · B3 BL-Übersichten+Nähe-Logik · B4 Rundnachrichten+
Export · B5 Kontaktformular · B6 Nicht-buchbar-UI+Mobil · B7 Hilfetexte auslagern.
