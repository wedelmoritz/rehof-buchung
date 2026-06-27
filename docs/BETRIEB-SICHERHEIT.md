# Betrieb & Sicherheit — Blueprints (Phase 2 & 4)

> **Status: GEPLANT — NICHT UMGESETZT.** Dieses Dokument ist ein **Merker mit dem
> genauen Wie**. Im aktuellen PoC ist nichts davon aktiv. Reihenfolge der
> Umsetzung: **1) Rechnungs-PDF (erledigt) → 3) Losung rückgängig/bestätigen →
> C) Kontoabgleich**; **Phase 2 (Backup)** und **Phase 4 (Hardening)** folgen,
> wenn der PoC in den echten Betrieb geht.

Ausgangslage (Ist): PostgreSQL 16 im Docker-Volume `pgdata`, nur im internen
Docker-Netz (kein Host-Port), Caddy terminiert TLS. **Kein Backup, keine
At-Rest-Verschlüsselung.** → Beides ist der eigentliche Schutzbedarf.

---

## Phase 2 — Backups (off-site, unveränderbar, 14 Tage)

**Ziel:** 14 Tage zurückspringen können; **separat** gespeichert, sodass ein
DB-Verlust/-Angriff die Sicherung **nicht** mitnimmt (3-2-1-Regel).
**Aufwand:** gering. **Voraussetzung:** eine **Hetzner Storage Box** (günstig).

**Ansatz:** nächtlicher `pg_dump` → **verschlüsselt** mit **Borg im
Append-only-Modus** auf die Storage Box. Append-only heißt: der Server darf neue
Backups schreiben, aber bestehende **nicht löschen/ändern** → ransomware-resistent.
Zusätzlich Storage-Box-**ZFS-Snapshots** (selbst per SSH nicht änderbar).

### Genau so (beim Aktivieren):

1. **Storage Box** anlegen, SSH-Key des Servers dort hinterlegen, Sub-Account mit
   **append-only** einrichten.
2. `.env` (nicht ins Repo): `BORG_REPO=ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./rehof`
   und `BORG_PASSPHRASE=<langes Geheimnis>`.
3. **Backup-Container** in `docker-compose.yml` — standardmäßig **aus** über ein
   Profil, läuft nur mit `docker compose --profile backup up -d`:

   ```yaml
   # NOCH NICHT AKTIV — Blueprint
   backup:
     image: postgres:16-alpine     # bringt pg_dump passend zur DB mit
     restart: unless-stopped
     profiles: ["backup"]
     depends_on: [db]
     environment:
       PGPASSWORD: ${POSTGRES_PASSWORD}
       BORG_REPO: ${BORG_REPO}
       BORG_PASSPHRASE: ${BORG_PASSPHRASE}
     volumes:
       - ./ops/backup.sh:/backup.sh:ro
       - backup-ssh:/root/.ssh
     entrypoint: ["sh", "-c", "apk add --no-cache borgbackup openssh && crond -f"]
     networks: [internal]
   ```

4. **`ops/backup.sh`** (nächtlich per Cron/`crond`):

   ```sh
   #!/bin/sh
   set -e
   STAMP=$(date +%Y-%m-%d_%H%M)
   pg_dump -h db -U "$POSTGRES_USER" "$POSTGRES_DB" \
     | borg create --stdin-name rehof-$STAMP.sql "::rehof-$STAMP" -
   # Retention: 14 tägliche behalten (append-only erlaubt prune nur serverseitig
   # bzw. via separatem, NICHT-append-only Schlüssel im Wartungsfenster)
   borg prune --keep-daily=14 --glob-archives 'rehof-*' || true
   ```

5. **Restore-Runbook** (bewusst **am Server**, nicht aus der Web-App):

   ```sh
   borg list ::                      # verfügbare Snapshots (14 Tage)
   borg extract ::rehof-2026-06-20_0300
   # in eine FRISCHE DB einspielen und erst nach Prüfung umschalten:
   psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" < rehof-2026-06-20_0300.sql
   ```

   **Wichtig:** Restore gehört absichtlich **nicht** in die Web-Verwaltung — ein
   kompromittierter Admin-Account könnte sonst Daten zurückrollen/zerstören. Im
   Dashboard ist später höchstens eine **read-only Statuskachel** sinnvoll
   („letztes Backup: …, 14 Snapshots"). **Test-Restore** regelmäßig durchführen —
   ein nie getestetes Backup ist kein Backup.

6. **Später optional:** PITR (RPO Sekunden) via `pgBackRest`/WAL-G statt
   nächtlichem Dump (mehr Aufwand; für eine Genossenschafts-App selten nötig).

---

## Phase 4 — Hardening

> **Status: GEPLANT — NICHT UMGESETZT.** Priorisiert nach realem Bedrohungsmodell:
> geleakte Secrets, kompromittierter Admin, gestohlene Backups, VPS-Root.

### 4.1 Secrets-Hygiene (sofort, sobald produktiv) — *Aufwand: minimal*
- `.env` mit `chmod 600`, nie ins Repo (ist bereits gitignored).
- **Rotations-Runbook** für `SECRET_KEY` und DB-Passwort dokumentieren
  (SECRET_KEY-Wechsel invalidiert Sessions — unkritisch).

### 4.2 2-Faktor für die Verwaltung — *Aufwand: gering*
- `django-otp` + `django_otp.plugins.otp_totp`, `OTPMiddleware`, Admin auf
  `OTPAdminSite` umstellen (oder `admin.site.login` per OTP absichern).
- Nur **Staff/Superuser** betroffen; Mitglieder bleiben unberührt.
- Optional zusätzlich: Admin-Zugriff über Caddy auf bestimmte IPs/VPN
  beschränken (`@admin` matcher → `remote_ip`).

### 4.3 IBAN-Feldverschlüsselung — *Aufwand: mittel, bewusst klein halten*
- **TBD / temporäre Entscheidung (Profil-Audit Phase 3):** `Member.iban` wird
  **vorerst weiter erhoben und gespeichert**, weil es heute im Rechnungs-Export
  der Verwaltung auftaucht (`shop.services.invoice_export_rows`). Es ist aber das
  sensibelste PII im System; ob es wirklich gebraucht wird (oder die Anschrift als
  Rechnungsadresse genügt), ist **offen** und im Zuge der Datensparsamkeit (Phase 4
  DSGVO) erneut zu prüfen. Bis dahin gilt: minimal halten, nicht weiter ausbauen.
- **Nur** das sensibelste PII verschlüsseln: `Member.iban` (ggf. Anschrift).
- App-seitig mit **Fernet** (z.B. `django-cryptography` oder eigenes
  `EncryptedCharField`); Schlüssel in `.env` (`FIELD_ENCRYPTION_KEY`), **getrennt**
  von der DB.
- **Trade-offs/Merker:** Feld wird nicht such-/sortierbar; **Schlüsselverlust =
  Datenverlust** → Schlüssel mitsichern (getrennt!). Migration: bestehende Werte
  beim Deploy einmalig ver­schlüsseln (Daten-Migration).
- **64 % der DB-Breaches** kommen aus schlechtem **Key-Management**, nicht aus
  schwacher Krypto — deshalb Schlüsselablage/-rotation sauber dokumentieren.

### 4.4 At-Rest-Verschlüsselung der Platte (LUKS) — *Aufwand: Infra*
- LUKS/dm-crypt auf der Datenpartition schützt gegen **Plattendiebstahl/
  Außerbetriebnahme** der VPS — **nicht** gegen Live-Root-Kompromiss (dann ist
  alles entschlüsselt gemountet). Auf Hetzner-VPS kontrolliert der Provider den
  Host; LUKS bleibt dennoch eine solide Basismaßnahme.

### 4.5 Sonstiges Härten — *Aufwand: gering, laufend*
- Abhängigkeiten aktuell halten (Dependabot/Renovate).
- Security-Header/CSP via Caddy ergänzen; `SECURE_HSTS_SECONDS` setzen, sobald
  dauerhaft HTTPS.
- `django-axes` (Brute-Force) ist bereits aktiv.

---

## Was am meisten bringt (Kurzfassung)

1. **Off-site-Backups (Phase 2)** — größtes Sicherheitsnetz, deckt zugleich den
   „14-Tage-Rückspielbar"-Wunsch.
2. **Secrets-Hygiene + 2FA (4.1/4.2)** — gegen die häufigsten realen Vektoren.
3. **IBAN-Feldverschlüsselung + LUKS (4.3/4.4)** — gezielte Tiefenverteidigung.
