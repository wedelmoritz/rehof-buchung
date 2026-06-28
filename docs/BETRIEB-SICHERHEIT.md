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

### 4.3 IBAN-Feldverschlüsselung — *VORBEREITET (P2.5/ADR 0061), noch nicht scharf*
- **Status:** Die app-seitige Feld-Verschlüsselung liegt **fertig vorbereitet**,
  ist aber bewusst an **keinem** Modellfeld aktiv (kein Datenzugriff geändert):
  - `booking/fieldcrypt.py` – Django-freie Fernet-Naht (Round-Trip, Rotation;
    getestet in `tests/test_fieldcrypt.py`).
  - `booking/fields.py` – `EncryptedCharField` (verschlüsselt beim Schreiben,
    entschlüsselt beim Lesen; **ohne Schlüssel = Klartext** → gefahrloser Rollout;
    getestet in `booking/tests_fieldcrypt.py`).
  - `FIELD_ENCRYPTION_KEY` (Settings + docker-compose, leer = inaktiv);
    Schlüssel erzeugen mit `manage.py field_key`.
- **In Produktion scharf schalten (kleiner, gezielter Schritt):**
  1. `python manage.py field_key` → Ausgabe als `FIELD_ENCRYPTION_KEY` in die `.env`
     (GETRENNT von der DB sichern!).
  2. Das sensibelste PII-Feld (`Member.iban`, ggf. Anschrift) von `CharField` auf
     `EncryptedCharField` umstellen, `max_length` großzügig (Fernet-Token ≫ IBAN).
  3. Daten-Migration: bestehende Klartext-Werte einmalig verschlüsseln.
- **TBD (Datensparsamkeit, Profil-Audit Phase 3):** Ob `Member.iban` überhaupt
  gebraucht wird (heute im Rechnungs-Export der Verwaltung), ist weiterhin offen.
  Bis zur Klärung: minimal halten, nicht weiter ausbauen.
- **Trade-offs/Merker:** Feld wird nicht such-/sortierbar; **Schlüsselverlust =
  Datenverlust** → Schlüssel mitsichern (getrennt!). **Rotation:**
  `FIELD_ENCRYPTION_KEY=neu,alt` (erster verschlüsselt, alle entschlüsseln).
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

---

## Performance & Skalierung (>100 gleichzeitige Nutzer)

Sicherheit hat Vorrang: Zeilensperren/Constraints für Buchung & Checkout bleiben,
auch wenn sie minimal serialisieren (Integrität > Tempo); kein Cache
berechtigungspflichtiger/personenbezogener Daten über Nutzer hinweg.

**Web-Worker (Gunicorn, I/O-/DB-gebunden):** `gthread` mit Threads erlaubt echte
Gleichzeitigkeit. Gleichzeitige Requests ≈ `GUNICORN_WORKERS × GUNICORN_THREADS`
(Default 3×8 = 24). Per Env steuerbar: `GUNICORN_WORKERS`, `GUNICORN_THREADS`,
`GUNICORN_WORKER_CLASS`.

**DB-Verbindungsbudget:** Jeder aktive Thread hält mit `conn_max_age=600` eine
eigene PostgreSQL-Verbindung. Faustregel: **workers×threads (aller Web-Container)
≤ Postgres `max_connections`** (Default 100). Bei mehreren Web-Containern oder
hoher Worker-Zahl **PgBouncer** (Transaction-Pooling) davorschalten und die App
auf den Pooler zeigen lassen. `CONN_HEALTH_CHECKS=True` fängt abgelaufene
Verbindungen ab.

**Redis (empfohlen ab vielen gleichzeitigen Nutzern):** `REDIS_URL` setzen und
`docker compose --profile cache up -d`. Dann liegen **Sessions** (statt je Request
in PostgreSQL), der **Cache** und die **Axes-Brute-Force-Zähler** im gemeinsamen
Redis → spürbar weniger DB-Schreiblast. Weiterhin serverseitig (kein
Vertraulichkeitsverlust).

**Geprüfte Query-Last (lokal, 50+ Mitglieder):** Startseite 23, Buchen 17,
Hofladen 10, Dashboard 28 Queries. Hot-Pfade nutzen `select_related`/
`prefetch_related`/Annotation; die geteilte Monats-Belegung kann zusätzlich kurz
gecacht werden (nur allgemein sichtbare Daten, invalidiert bei Buchungsänderung).

**Lasttest:** `k6` (ADR 0051) gegen Startseite **und** Checkout mit ~100 VUs fahren;
p95-Latenz und Postgres-Verbindungen beobachten (`pg_stat_activity`).

### Optionale Tiefenverteidigung: DB-Constraint gegen Doppelbuchung

Die Doppelbuchung ist bereits **korrekt** über die Zeilensperre verhindert
(`book_spontaneous`: `select_for_update` auf der Quartier-Zeile + frische
`quarter_is_free`-Prüfung; getestet in `booking/tests_concurrency.py`). Wer auf
DB-Ebene zusätzlich absichern will (Belt-and-Suspenders), kann auf PostgreSQL einen
**Exclusion-Constraint** setzen, der überlappende *bestätigte* Zuteilungen je
Quartier hart unterbindet:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE booking_allocation
  ADD CONSTRAINT alloc_no_overlap
  EXCLUDE USING gist (quarter_id WITH =, daterange(start, "end") WITH &&)
  WHERE (provisional = false);
```

Bewusst **nicht** als Migration eingespielt: Postgres-spezifisch (die SQLite-
Testsuite kann ihn nicht ausführen), und er greift nur Allocation↔Allocation –
Allocation↔ExternalBooking deckt weiterhin die Sperre ab. Vor dem Setzen sicher-
stellen, dass keine bestehenden Überschneidungen vorliegen (sonst schlägt das
`ALTER TABLE` fehl). Entfernen: `ALTER TABLE booking_allocation DROP CONSTRAINT alloc_no_overlap;`

### Lasttest-Szenarien (`loadtest/`)
- `browse.js` – Lese-Last (Übersicht/Buchen/Meine Buchungen).
- `booking_rush.js` – gleichzeitige Buchungen desselben Slots (Sperre).
- `shop_rush.js` – Hofladen: Katalog/Warenkorb/Checkout unter Last (Rechnungs-
  nummer-Vergabe, Warenkorb-Schreibpfade).
