# 0037 – Backup und weiteres Hardening bewusst zurückgestellt

## Status

Proposed (2026-06-26) – geplant, im PoC NICHT umgesetzt

## Kontext

Die App ist eine lauffähige Proof-of-Concept. Mehrere Betriebs-/Sicherheitsmaßnahmen
sind für den **echten Wirkbetrieb** dringend nötig, im PoC aber bewusst noch nicht
umgesetzt. Diese Entscheidung soll dokumentiert sein, damit der offene Stand und das
Restrisiko sichtbar bleiben – nicht stillschweigend verschwinden.

## Entscheidung

Folgende Maßnahmen sind als **Blueprint** vorbereitet, aber **nicht aktiv**
(`docs/BETRIEB-SICHERHEIT.md`, README-Abschnitt „Datensicherung & Härtung“):

- **Off-site-Backups:** nächtlicher `pg_dump` → verschlüsselt & append-only (Borg/
  restic, Hetzner Storage Box), Retention + getesteter Restore. **Aktuell gibt es
  kein Backup.**
- **2FA für die Verwaltung** (`django-otp`).
- **IBAN-Feldverschlüsselung** (Schlüssel getrennt von der DB).
- **At-Rest-Verschlüsselung (LUKS)** der Datenpartition.
- **Secrets-Hygiene** (`.env` `chmod 600`, Rotations-Runbook).

Bereits umgesetzte, abschwächende Architektur: Die DB ist vom Netz abgeschottet
(internes Docker-Netz, kein veröffentlichter Port, ADR 0020), der Transport ist
via Caddy TLS-verschlüsselt; Login ist gehärtet (ADR 0015).

## Betrachtete Alternativen

- **Alles sofort im PoC umsetzen:** verzögert die fachliche Erprobung; mehrere
  Maßnahmen (Backup-Ziel, Schlüsselverwahrung) brauchen ohnehin betriebliche
  Entscheidungen.
- **Gar nicht dokumentieren:** das Restrisiko (v. a. fehlendes Backup) bliebe
  unsichtbar – inakzeptabel.

## Konsequenzen

**Positiv**
- Der offene Stand und das Restrisiko sind transparent; Blueprints liegen vor.
- Fachliche Erprobung wird nicht durch Betriebsthemen blockiert.

**Negativ**
- **Echtes Risiko bis zur Umsetzung:** ohne Backup droht Totalverlust; ohne
  IBAN-Verschlüsselung liegt PII in einem gestohlenen Dump offen.
- **Vor dem Wirkbetrieb zwingend** auf Accepted zu heben (Maßnahmen umsetzen).
