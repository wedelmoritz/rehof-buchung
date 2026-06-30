# Inbetriebnahme, Betriebsvoraussetzungen & Kosten — Re:Hof Quartier-Buchung

Dieses Dokument bündelt **was vor dem Echtbetrieb (Go-Live) gebraucht und getan
werden muss**: technische Voraussetzungen (Hardware/Server/Anbindung), die nötige
Software, eine **Schritt-für-Schritt-Checkliste**, die **Datensicherung** (Backup
der Datenbank zuerst!) und eine **Kostenübersicht**.

Es ist die **Management-/Überblicks-Ebene**. Die konkreten Befehle stehen in den
Detail-Dokumenten:

- **`docs/DEPLOYMENT.md`** — Erstinstallation, `.env`, Caddy, Updates, Redis, Umzug.
- **`docs/BETRIEB-SICHERHEIT.md`** — Härtung (Backups off-site, LUKS, Performance).
- **`docs/2FA-BACKEND.md`** — Zwei-Faktor fürs Backend.
- **`docs/DATENSCHUTZ-VORLAGE.md`** — DSGVO-Bausteine.
- **`docs/TESTEN.md`** — Test-Suiten.

> Die Kostenangaben sind **Schätzwerte** (Stand 2026, EU/Deutschland) und ersetzen
> keine Vertrags-, Rechts- oder Steuerberatung. Bei Unsicherheiten: nachfragen.

---

## 1. Technische Voraussetzungen

### 1.1 Server / Hardware

Die App läuft als **Docker-Compose-Stack** (Django/Gunicorn + PostgreSQL, optional
Redis) hinter **Caddy** (TLS) auf **einem Linux-VPS**. Es wird **kein** eigener
physischer Server gebraucht – ein gemieteter virtueller Server (z. B. Hetzner Cloud)
genügt.

**Empfohlene Dimensionierung** (Genossenschaft, Größenordnung 60–100 Mitglieder):

| Größe | vCPU | RAM | SSD | Eignung |
|-------|------|-----|-----|---------|
| Minimal | 2 | 4 GB | 40 GB | kleiner Betrieb, wenig Gleichzeitigkeit |
| **Empfohlen** | **2–3** | **4–8 GB** | **40–80 GB** | normaler Betrieb inkl. PDF/Reisespitzen |
| Komfort | 4 | 8 GB | 80–160 GB | viele gleichzeitige Nutzer, Reserve |

Faustregeln:
- **RAM** ist der knappste Faktor (Gunicorn-Worker + PostgreSQL + WeasyPrint-PDF).
  4 GB sind das praktikable Minimum, 8 GB komfortabel.
- **CPU**: Die App ist I/O-/DB-gebunden; 2–3 vCPU reichen meist. Gunicorn läuft als
  `gthread` (Default 3 Worker × 8 Threads).
- **Disk**: Datenbank + Backups + Docker-Images. 40 GB Minimum, mehr bei vielen
  Rechnungen/Jahren. SSD/NVMe (nicht HDD).
- **DB-Verbindungen beachten**: `workers × threads` ≤ PostgreSQL `max_connections`
  (Default 100). Bei mehreren Web-Containern PgBouncer davor (siehe
  BETRIEB-SICHERHEIT.md).

**Betriebssystem:** aktuelles **Ubuntu LTS** oder **Debian stable** (64-bit).

### 1.2 Netz & Anbindung

- **Domain** (z. B. `buchung.rehof-rutenberg.de`) + **DNS-Zugriff** (A-Record auf
  die Server-IPv4, optional AAAA für IPv6).
- **Öffentliche, statische IP** des VPS.
- **Offene Ports nach außen:** nur **80** (HTTP→HTTPS-Redirect) und **443** (HTTPS)
  sowie **22** (SSH, am besten auf vertrauenswürdige IPs/Key beschränkt). Die App
  selbst veröffentlicht **keinen** Host-Port (Caddy erreicht sie im Docker-Netz).
- **Ausgehend** muss der Server erreichen: Let's-Encrypt (TLS-Zertifikate),
  **SMTP-Server** (E-Mail-Versand), **Mollie-API** (Online-Zahlung), optional
  **Sentry** (Fehler-Tracking) und das **Off-site-Backup-Ziel** (z. B. Backblaze B2).
- **TLS** macht Caddy automatisch (Let's Encrypt) – kein gekauftes Zertifikat nötig.

### 1.3 Software-Stack (auf dem Server zu installieren)

- **Docker Engine** + **Docker Compose plugin** (`docker compose`).
- **Caddy** als Reverse-Proxy/TLS-Terminator (eigener Container/Dienst; erreicht
  `web:8000` im gemeinsamen Docker-Netz).
- **Git** (Repository holen/aktualisieren).
- **GnuPG** + optional **rclone** (für verschlüsselte Off-site-Backups, `ops/backup.sh`).

PostgreSQL 16 und (optional) Redis kommen **als Container** aus dem Compose-Stack –
nicht separat installieren. Die nativen PDF-Bibliotheken (Pango/Cairo/GDK-Pixbuf
für WeasyPrint) sind **im Docker-Image** enthalten (siehe `Dockerfile`).

### 1.4 Externe Dienste / Konten

| Dienst | Wofür | Pflicht? |
|--------|-------|----------|
| **VPS-Hoster** (z. B. Hetzner) | Server | ja |
| **Domain/DNS** | Adresse + TLS | ja |
| **SMTP-Versand** (eigener Server oder Anbieter wie Brevo/Mailjet/Postmark) | Benachrichtigungen, Einladungen, Rechnungs-PDF | ja (sonst nur Konsole) |
| **Mollie** | Online-Bezahlung (Karte/PayPal/SEPA) | nur wenn Online-Zahlung gewünscht (sonst Überweisung) |
| **Off-site-Speicher** (Backblaze B2, Hetzner Storage Box, …) | verschlüsselte Backups außer Haus | dringend empfohlen |
| **Sentry** | Fehler-Tracking | optional |

### 1.5 Python-Abhängigkeiten

Vollständig in **`requirements.txt`** gepinnt (Django, psycopg, gunicorn,
whitenoise, django-axes/-otp/-csp/-ratelimit/-reversion, weasyprint, pywebpush,
sentry-sdk, …). Werden **im Image** installiert – auf dem Host ist **kein** Python
nötig.

---

## 2. Test-Instanz auf eigenem Branch (Staging) — empfohlen

**Empfehlung:** Änderungen erst auf einer **Test-Instanz** erproben, nie direkt auf
der Produktivumgebung. So lässt sich alles gefahrlos „vortasten".

**Branch-Strategie**
- `main` → Produktion. `staging` (oder `test`) → Test-Instanz. Feature-Branches →
  Pull Request → CI grün → nach `staging` → erproben → nach `main` mergen.
- Die **CI** (`.github/workflows/tests.yml`) läuft bei **jedem Push/PR**: reine
  Tests, Integrationstests gegen echtes PostgreSQL, Migrations-Resilienz auf einer
  befüllten Alt-DB und **E2E** im prod-nahen Docker-Stack. Das grüne Häkchen ist die
  Freigabe vor dem Pull auf die Server.

**Test-Instanz technisch** (zwei gängige Wege):
1. **Eigener kleiner VPS / Subdomain** (`test.buchung.…`) mit eigener `.env`,
   eigenem `pgdata`-Volume und `SEED_DEMO=1`/`seed_demo --testdata` (Test-Konten
   `admin`/`verwaltung`/`test`). Sauberste Trennung.
2. **Zweiter Compose-Stack auf demselben Server** (eigenes Projektverzeichnis,
   eigener Compose-Projektname, eigene Ports/Subdomain, **eigenes** DB-Volume).
   Günstiger, aber teilt Ressourcen – Produktivdaten nie mischen.

**Wichtig:** Die Test-Instanz bekommt **eigene** Secrets, **eigene** DB und **nie**
echte Mitgliederdaten ungefragt (DSGVO). Für realistische Tests `seed_demo
--testdata` nutzen.

---

## 3. Schritt-für-Schritt vor Go-Live (Checkliste)

> Reihenfolge bewusst: **Backup zuerst** – bevor echte Daten entstehen, muss die
> Sicherung stehen und einmal **wiederhergestellt** worden sein.

- [ ] **0. Datenbank-Backup einrichten (PFLICHT, ganz zuerst).** Siehe Abschnitt 4.
      `ops/backup.sh` einrichten, **`BACKUP_PASSPHRASE` getrennt** sichern, täglichen
      Cron anlegen, Off-site-Ziel setzen **und einen Restore testen**.
- [ ] **1. Server vorbereiten:** OS-Updates, Docker + Compose, Caddy, Firewall
      (nur 80/443/22), SSH-Key-Login, automatische Sicherheitsupdates.
- [ ] **2. Secrets erzeugen:** starker `SECRET_KEY`, `POSTGRES_PASSWORD`,
      `BACKUP_PASSPHRASE` (je im Passwortmanager/Tresor, **nicht** ins Repo).
- [ ] **3. `.env` vollständig:** `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
      `PUBLIC_BASE_URL`, DB-Variablen, `TZ=Europe/Berlin` (Details DEPLOYMENT.md §4).
- [ ] **4. Stack bauen & starten:** `docker compose up -d --build`. Der Entrypoint
      wartet auf die DB, **migriert** und legt `createinitialrevisions` an.
      `docker compose ps` muss **healthy** zeigen (`/healthz/`).
- [ ] **5. Admin + 2FA:** Superuser anlegen, **Backend-2FA** einrichten
      (`manage.py admin_otp_setup`, `ADMIN_OTP_REQUIRED=1`; docs/2FA-BACKEND.md).
- [ ] **6. E-Mail-Versand:** `EMAIL_*` setzen, Testmail prüfen (ohne `EMAIL_HOST`
      geht alles nur auf die Konsole – kein echter Versand!).
- [ ] **7. Online-Bezahlung (optional):** `ShopConfig.mollie_api_key` (live ODER
      bewusst Sandbox), `payments_active`, eine Testzahlung durchspielen.
- [ ] **8. Web-Push (optional):** `manage.py vapid_keys`, `VAPID_*` in die `.env`.
- [ ] **9. Stammdaten im Backend:** Quartiere (+ `building`/`prefer_for_groups`),
      Äquivalenzklassen, **Saison-Regeln** (Mindestnächte, Parallel-Limit, Deckel),
      **Schulferien**, **Buchungsregeln** (`BookingPolicy`: Vorlauf, Lückenfüllung,
      Gruppe-ab, Winter-/Wochenend-Richtwert, kleinere Unterkünfte), Hofladen-Katalog,
      **`ShopConfig`** (Genossenschaftsdaten, IBAN, USt-Schalter, Impressum/
      Datenschutz/AGB).
- [ ] **10. Recht & Steuer:** Impressum/Datenschutz/AGB einpflegen; **USt-Status
      mit der Steuerberatung** klären (Regelbesteuerung vs. §19); siehe ADR 0041/0042.
- [ ] **11. DSGVO:** Aufbewahrung (`RETENTION_*`) prüfen, Datenschutzerklärung,
      **Auftragsverarbeitungs-Verträge** (Hoster, Mailversand, Mollie, Sentry),
      Lösch-/Anonymisierungs-Abläufe testen (docs/DATENSCHUTZ-VORLAGE.md).
- [ ] **12. Mitglieder-Onboarding:** Konten anlegen/einladen; **Beds24-Import**
      (falls Umzug von Beds24) über den Migrations-Assistenten.
- [ ] **13. Monitoring:** externes **Uptime-Monitoring auf `/healthz/`**, optional
      `SENTRY_DSN`, `LOG_LEVEL` festlegen (ADR 0046).
- [ ] **14. Performance/Skalierung:** ab vielen gleichzeitigen Nutzern **Redis**
      zuschalten (`REDIS_URL` + `--profile cache`), DB-Verbindungsbudget prüfen
      (BETRIEB-SICHERHEIT.md, ADR 0060).
- [ ] **15. Härtung:** HSTS-Stufen erhöhen, sobald dauerhaft HTTPS; optional
      Platten-Verschlüsselung (LUKS) und append-only-Backups (Borg) – Blueprints in
      BETRIEB-SICHERHEIT.md.
- [ ] **16. Abnahme:** E2E-Smoke (`tests_e2e/`) gegen die Instanz, optional Lasttest
      (`loadtest/`), kritische Abläufe (Buchen, Losung, Rechnung, Bezahlen) manuell
      durchspielen.

---

## 4. Datensicherung & Notfall

**Das Wichtigste zuerst: das Backup der Datenbank.** Hier liegen alle Buchungen,
Mitglieder, Rechnungen. Ohne funktionierendes, **wiederherstellbares** Backup darf
nicht produktiv gegangen werden.

**Umgesetzt (`ops/backup.sh`, ADR 0061):**
- Erstellt einen **PostgreSQL-Dump** aus dem laufenden `db`-Container,
- **verschlüsselt** ihn clientseitig mit **GnuPG (AES-256)** – Backups liegen **nie
  unverschlüsselt** außerhalb des Servers,
- legt ihn lokal ab und kopiert ihn optional **off-site** (rclone, z. B. Backblaze B2),
- behält die letzten N (Default 14).

**So einrichten:**
1. `BACKUP_PASSPHRASE` (starke Passphrase) in die `.env` – **getrennt** vom Backup
   im Passwortmanager/Tresor sichern. **Verlust = Backups unbrauchbar.**
2. Off-site-Ziel setzen (`BACKUP_RCLONE_REMOTE`).
3. Täglichen **Cron** anlegen, z. B.:
   `15 3 * * *  cd /opt/rehof && ./ops/backup.sh backup >> /var/log/rehof-backup.log 2>&1`
4. **Restore-Übung** (regelmäßig!): `./ops/backup.sh restore <datei>` auf der
   **Test-Instanz** einspielen und prüfen. Ein ungetestetes Backup ist kein Backup.

**Zusätzlich:**
- **Server-Umzug / Voll-Migration:** `ops/migrate-server.sh dump|restore` (pg_dump
  über den `db`-Container) – siehe DEPLOYMENT.md §12.
- **Hoster-Snapshots** des Volumes als *zusätzliche* Ebene (ersetzen das
  verschlüsselte, externe DB-Backup **nicht**).
- **Geplante Härtung** (noch offen, Blueprints in BETRIEB-SICHERHEIT.md):
  **Borg-Append-only-Backups** (Schutz gegen Ransomware/Löschen) und
  **LUKS-Plattenverschlüsselung** (Schutz bei Hardware-Zugriff). Ebenfalls offen:
  **IBAN-Feldverschlüsselung** (vorbereitet, inaktiv – ADR 0061).

---

## 5. Kosten (Schätzung, monatlich)

| Posten | Anbieter-Beispiel | Kosten/Monat | Anmerkung |
|--------|-------------------|--------------|-----------|
| **VPS** | Hetzner CX22/CPX21 (2–3 vCPU, 4 GB) | **ca. 5–15 €** | empfohlene Größe; mehr bei Komfort/Reserve |
| **Domain** | beliebiger Registrar | **ca. 1 €** | ~10–15 €/Jahr |
| **Off-site-Backup** | Backblaze B2 / Hetzner Storage Box | **ca. 1–4 €** | DB ist klein; Storage Box BX11 ~3–4 € |
| **E-Mail-Versand** | Brevo/Mailjet (Free/Starter) o. eigener SMTP | **0–10 €** | Free-Tier reicht für eine Genossenschaft oft aus |
| **Online-Bezahlung** | Mollie | **0 € Grundgebühr** | **pro Transaktion** (SEPA ~0,25 €; Karte ~0,25 € + kleiner %); fällt nur bei Nutzung an |
| **Fehler-Tracking** | Sentry (Free) | **0 €** | optional, Free-Tier genügt meist |
| **TLS-Zertifikate** | Let's Encrypt via Caddy | **0 €** | automatisch |
| **Redis** | im selben VPS-Container | **0 €** | optional, ab vielen Nutzern |

**Laufend gesamt: grob 8–25 €/Monat** (zzgl. Mollie-Transaktionsgebühren, falls
Online-Zahlung genutzt wird).

**Einmalig / gelegentlich:**
- **Einrichtung/Deployment:** in Eigenleistung 0 € (Zeitaufwand), extern je nach
  Dienstleister.
- **Optional Sicherheits-Review/Pentest** vor Go-Live (empfehlenswert, aber kein Muss).
- **Test-Instanz:** ein zweiter kleiner VPS schlägt mit weiteren ~5 €/Monat zu Buche
  (oder 0 €, wenn als zweiter Stack auf demselben Server – dann aber Ressourcen teilen).

> Alle Beträge sind grobe Richtwerte (Stand 2026) und hängen von Anbieter, Tarif und
> Nutzung ab. Vor Vertragsabschluss aktuelle Preise prüfen.

---

## 6. Offene Punkte & Empfehlungen

- **Vor Go-Live verbindlich klären:** USt-Status (Steuerberatung), Rechtstexte
  (Impressum/Datenschutz/AGB), AV-Verträge, Aufbewahrungsfristen.
- **Dringend empfohlen umzusetzen:** verschlüsseltes, off-site, **getestetes**
  DB-Backup (Abschnitt 4); Backend-2FA; Firewall/SSH-Härtung.
- **Empfohlen, mittelfristig:** Borg-Append-only-Backups, LUKS,
  IBAN-Feldverschlüsselung (Blueprints vorhanden).

**Fragen?** Bei Unklarheiten zu Dimensionierung, Anbieterwahl, Kosten oder den
einzelnen Schritten gern melden – dann gemeinsam die passende Variante festlegen.
