# 0089 – Benachrichtigungs-Framework (Katalog + Dispatcher + Backend-Settings)

## Status

Accepted (2026-07-05) · konkretisiert ADR 0087 (Punkt 2)

## Kontext

Benachrichtigungen entstanden bisher als **verstreute Ad-hoc-Mails** in diversen
Services. Für die geplanten Übersichten (BL), Rundnachrichten und die Vorwarnung vor
Statuswechseln braucht es eine **einheitliche Naht** mit im Backend einstellbaren
Betriebs-Parametern – bei gleichzeitig **sicheren, versionierten** Texten.

## Entscheidung

**Text als Code, Betrieb im Backend** (Hybrid aus ADR 0087):

- **Katalog** `booking/notify_catalog.py`: je Ereignis Betreff/Text als Vorlage mit
  `$variable`-Platzhaltern + Metadaten (audience, kind, pdf, defaults). Gerendert
  **ausschließlich** über `string.Template.safe_substitute` gegen die Vorlage – die
  Nutzer-/Kontextdaten sind reine Werte, **kein** Template-Engine auf gespeicherten
  Strings → **kein SSTI**. Fehlende Variablen bleiben stehen.
- **Backend-Settings** `NotificationSetting` (je Ereignis, lazy mit Katalog-Defaults
  angelegt): `enabled`, `recipients` (leer = Verwaltungs-Adressen), `frequency`
  (immediate/event/daily/weekly/monthly), `weekday`/`day_of_month`, `attach_pdf`,
  `lead_days`, `last_run_on` (Idempotenz). Editierbar im Backend – **Texte** ändert
  die Entwicklung (Deploy).
- **Dispatcher** `services.dispatch_event(event_key, context, member=…, recipients=…,
  attachment=…)`: rendert + verschickt über die vorhandenen Bausteine
  (`Notification` in-App + `email_member` bzw. `queue_email_many`, PDF-Anhang über die
  `OutboxEmail`-Anhangfelder). Respektiert `enabled` und `email_opt_in`.
- **Geplante Meldungen** laufen über `services.run_scheduled_notifications` (Kommando
  `send_notifications`, täglich im `run_scheduler`); jede prüft ihre eigene
  Frequenz/Idempotenz über die `NotificationSetting`.
- **Katalog-Überblick** im Backend: der `NotificationSettingAdmin` legt beim Öffnen
  alle Katalog-Ereignisse an und zeigt sie als **Liste aller automatischen
  Benachrichtigungen** (adressiert Tester-#85). Kein Hinzufügen/Löschen von Hand.

**Erster Nutzer:** die **Status-Vorwarnung** (`member_status_upcoming`, ADR 0087):
Konten mit `passive_from`/`excluded_from` in ≤ `lead_days` werden der Verwaltung
gemeldet. Die BL-Übersichten (Buchungen/Auslastung/Überfällige) und Rundnachrichten
docken als weitere Katalog-Ereignisse an (B3/B4).

## Konsequenzen

**Positiv** – eine Naht statt verstreuter Mails; sichere, versionierte Texte;
Betrieb (an/aus, Empfänger, Frequenz, PDF) im Backend; leicht erweiterbar (neuer
Katalog-Eintrag + ein `dispatch_event`-Aufruf). Wiederverwendung von Outbox/
Notification/Scheduler.

**Grenzen** – bestehende Ad-hoc-Mails werden **schrittweise** migriert (kein
Big-Bang); die Texte sind bewusst nicht online editierbar (SSTI-/Compliance-Schutz,
ADR 0087).
