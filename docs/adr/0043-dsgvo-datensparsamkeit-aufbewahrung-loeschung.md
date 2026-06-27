# 0043 – DSGVO: Datensparsamkeit, Aufbewahrung, automatische Löschung & Anonymisierung

## Status

Accepted (2026-06-27)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 15 – Recht & Datenschutz](../FACHKONZEPT.md#15-recht--datenschutz)
> (Aufbewahrung/Löschung). Diese ADR hält die *technische* Entscheidung und ihre
> Abwägungen fest; die Regelwerte (Fristen) werden dort gepflegt, nicht hier.

## Kontext

Die App verarbeitet personenbezogene Daten (PII) von ~100 Mitgliedern und ~50
externen Gästen: Profil-/Rechnungsdaten (Name, Anschrift, IBAN), E-Mail-Adressen,
Magic-Link-Token, freie Texte (Begleitung, Notizen, Nachrichten) sowie technische
Daten (versendete E-Mails inkl. PDF-Anhang in der DB, In-App-Benachrichtigungen,
Kontoauszug-Rohzeilen, Beds24-Migrations-Rohdaten, Brute-Force-Fehlversuche).

Die DSGVO verlangt **Speicherbegrenzung** (Art. 5 Abs. 1 lit. e): Daten dürfen nur
so lange aufbewahrt werden, wie sie gebraucht werden. Bisher gab es **keine
automatische Löschung** – Daten häuften sich unbegrenzt an. Gleichzeitig sind
**Rechnungen 10 Jahre aufzubewahren** (§147 AO, §14b UStG); diese Frist darf eine
Löschautomatik nicht verletzen.

## Entscheidung

Ein **idempotentes Aufräum-Kommando** `cleanup_data` (Service
`services.run_data_retention`) löscht bzw. pseudonymisiert abgelaufene Daten anhand
konfigurierbarer Fristen. Es läuft **täglich** über den bestehenden Scheduler
(`run_scheduler`, ADR 0021), nicht über einen Extra-Dienst.

**Fristen** als `RETENTION_*`-Konstanten in `settings.py` (per Env überschreibbar –
bewusst kein Backend-UI, „möglichst simpel" für ein kleines Team). Die **konkreten
Default-Fristen** stehen in Fachkonzept § 15; hier die technische Zuordnung
Daten → Aktion (Konstanten/Modelle):

| Daten | Konstante / Modell | Aktion |
|---|---|---|
| `OutboxEmail` (versendet, inkl. DB-Anhang) | `RETENTION_OUTBOX_DAYS` | löschen |
| `Notification` (auch ungelesen) | `RETENTION_NOTIFICATION_DAYS` | löschen |
| `BankTransaction.raw` (Kontoauszug-Rohzeile) | `RETENTION_BANK_RAW_DAYS` | Rohtext leeren (Struktur bleibt) |
| `Beds24Import` (+ Zeilen) | `RETENTION_BEDS24_DAYS` | löschen |
| `BankImport` (Lauf-Metadaten) | `RETENTION_BANKIMPORT_DAYS` | löschen |
| erledigte `SwapRequest` / erfüllte `WaitlistEntry` | `RETENTION_SWAP_WAITLIST_DAYS` | löschen |
| `Wish` beendeter Perioden | `RETENTION_WISH_YEARS` | löschen |
| abgelaufene Sessions | – | löschen (`clearsessions`) |
| `axes`-Fehlversuche (`AccessAttempt`) | `RETENTION_AXES_DAYS` | löschen |

> Maßgeblich sind die `RETENTION_*`-Settings in `settings.py` (per Env
> überschreibbar); die konkreten Default-Fristen pflegt das Fachkonzept § 15.

**Bewusst NICHT angetastet (gesetzliche Aufbewahrung, Frist: Fachkonzept § 15):** `Invoice` inkl.
Empfänger-/Genossenschafts-Snapshots, `LineItem`, `Payment`, die zugehörigen
`Allocation` und `BankTransaction`-Strukturfelder. Geschützt zusätzlich durch
`Invoice.member/guest = PROTECT` (ein Mitglied/Gast lässt sich nicht löschen,
solange Rechnungen existieren).

**Recht auf Löschung (Art. 17):** Admin-Aktion **„Mitglied anonymisieren"** an der
Benutzer-Verwaltung (`services.anonymize_member`, mit Rückfrage). Sie leert die
Profil-PII (legal_name/street/zip/city/iban, display_name→„Anonymisiert #id"),
entfernt betrieblich kurzlebige personenbezogene Daten (Benachrichtigungen, Wünsche,
Warteliste, Wechselwünsche, Outbox-Mails), leert Freitext-PII in erhaltenen
Datensätzen (`Allocation.companions`, `NightTransfer.note`) und **deaktiviert das
Login-Konto** (unbrauchbares Passwort, `is_active=False`, Benutzername
`geloescht_<id>`, E-Mail leer). Die **Rechnungen bleiben** mit ihren Snapshots
erhalten – sie sind die gesetzlich nötige Kopie, unabhängig vom Mitglied.

**Datensparsamkeit (bereits umgesetzt):** Die ungenutzte `membership_number` wurde
entfernt (Phase 3); `AXES_DISABLE_ACCESS_LOG = True` verhindert dauerhaftes
IP-Logging über das Nötige hinaus.

## Betrachtete Alternativen

- **Fristen im Backend (OpsConfig) konfigurierbar:** verworfen zugunsten von
  Settings-Konstanten – weniger Aufwand/Fläche, ein kleines Team ändert Fristen
  selten und kann sie per Env setzen.
- **Eigener Cron-Dienst / Betriebssystem-Cron:** verworfen – der bestehende
  `run_scheduler` (ADR 0021) ist der etablierte Ort für wiederkehrende Jobs.
- **Harte Löschung des Mitglieds bei Art.-17-Anfrage:** nicht möglich/zulässig,
  solange aufbewahrungspflichtige Rechnungen existieren → **Anonymisierung** statt
  Löschung, Rechnungs-Snapshots bleiben.
- **Rechnungs-PDF-Anhänge dauerhaft in der DB halten:** verworfen – das PDF an der
  Outbox-Mail ist nur die Versand-Kopie; das Rechnungsoriginal wird bei Bedarf aus
  der `Invoice` neu erzeugt (ADR 0028). Daher dürfen versendete Mails inkl. Anhang
  nach 90 Tagen weg.

## Konsequenzen

**Positiv**
- Erfüllt die Speicherbegrenzung (Art. 5) ohne die 10-Jahres-Pflicht zu verletzen.
- Weniger PII „auf Halde", kleinere DB (v. a. die binären PDF-Anhänge).
- Ein klarer, getesteter Pfad fürs Recht auf Löschung (Anonymisierung).

**Negativ / offen (TBD)**
- **IBAN-Feldverschlüsselung / At-Rest (LUKS)** sind weiter **nur Blueprint**
  (ADR 0037, `docs/BETRIEB-SICHERHEIT.md` 4.3); die IBAN bleibt im Klartext und ist
  als temporäre Entscheidung markiert (Phase 3). Vor dem Wirkbetrieb erneut prüfen.
- Magic-Link-**Token-Rotation** (Guest/Payment) ist nicht umgesetzt – die Token sind
  lange gültig; eine Rotation/Ablauf ist ein möglicher Folge-Schritt.
- Die Fristen sind fachlich gesetzt, **nicht** rechtlich abschließend geprüft –
  vor Go-Live mit der Datenschutz-Verantwortlichen der Genossenschaft bestätigen.
