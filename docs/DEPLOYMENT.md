# Deployment & Betrieb — Re:Hof Quartier-Buchung

Schritt-für-Schritt-Runbook für **Inbetriebnahme und Betrieb auf einem Linux-VPS**
mit **Caddy (TLS am Host) + Docker Compose**. Grundlage ist der mitgelieferte
`docker-compose.yml`, `install.sh`, `caddy/Caddyfile.snippet` und `.env.example`.

> Konventionen: Alle Kommandos laufen aus dem **Repo-Wurzelverzeichnis** und
> nutzen das Compose-v2-Plugin (`docker compose …`). Läuft Docker nur mit `sudo`,
> jedem Kommando ein `sudo` voranstellen.

---

## 1. Überblick

Der Betriebs-Stack besteht aus vier Diensten (ADR 0020, ADR 0021):

```
            HTTPS (Let's Encrypt, TLS am Host)
  Browser ───────────────► Caddy ───── HTTP ─────► web  (Django/Gunicorn, :8000)
                           (Container)                    │
                                                          ▼
                                                          db   (PostgreSQL 16)
                                                          ▲
                                              cron (Scheduler) ┘
                                          (optional) redis  ── Cache/Sessions
```

- **`web`** — Django unter Gunicorn, lauscht im Container auf `0.0.0.0:8000`.
  Es wird **kein Host-Port veröffentlicht** (`ports:` fehlt bewusst). Caddy
  erreicht den Dienst über das **gemeinsame Docker-Netz** `compose_web` unter der
  festen IP **`10.42.42.20:8000`** (alternativ `web:8000`). TLS terminiert
  ausschließlich **Caddy am Host** — daher braucht die App keinen eigenen Port
  nach außen und spricht intern nur HTTP.
- **`db`** — PostgreSQL 16 (`postgres:16-alpine`), nur am internen Netz, **nicht**
  am Caddy-Netz erreichbar. Daten liegen im benannten Volume `pgdata`.
- **`cron`** — derselbe Image-Build, aber mit Entrypoint
  `python manage.py run_scheduler`. Ersetzt klassischen Cron (Losungen, Rechnungen,
  Mail-Versand, DSGVO-Aufräumen). Startet erst, wenn `web` **healthy** ist.
- **`redis`** *(optional, Profil `cache`)* — Cache/Sessions/Brute-Force-Zähler.
  Standardmäßig **aus** (DB-Sessions).

`web` und `db` haben **Healthchecks**; `docker compose ps` zeigt damit sofort
`unhealthy`, wenn Gunicorn oder die DB weg sind (statt nur eines 502 bei Caddy).

*(`docker-compose.ci.yml` ist NICHT für Produktion — es ist der prod-nahe Stack
für die E2E-Tests in der CI: kein Caddy/TLS, Port 8000 am Host, Secure-Cookies
aus. Siehe ADR 0022/0047.)*

---

## 2. Voraussetzungen

- **Linux-Server** (Debian/Ubuntu empfohlen) mit Root- oder `sudo`-Zugang.
- **Caddy läuft bereits** als Container/Dienst auf dem Host und holt die
  TLS-Zertifikate automatisch (Let's Encrypt). Der Caddy-Container muss am selben
  externen Docker-Netz hängen wie `web` (siehe `docker-compose.yml: networks.caddy`,
  Name `compose_web`).
- **Docker, Docker Compose (v2-Plugin), git** — `install.sh` prüft das und
  installiert es bei Bedarf (über `get.docker.com` bzw. `docker-compose-plugin`).
- **DNS** der Domain zeigt auf den Server (für die Caddy-Zertifikate).

---

## 3. Erstinstallation

### 3.1 Repository holen

```bash
git clone <repo-url> rehof && cd rehof
```

### 3.2 Voraussetzungen prüfen und `.env` erzeugen

```bash
./install.sh
```

Das Skript ist **idempotent** und tut:

- prüft/installiert git, Docker und das Compose-Plugin,
- startet ggf. den Docker-Daemon,
- erzeugt `.env` aus `.env.example` und füllt **`SECRET_KEY`** und
  **`POSTGRES_PASSWORD`** mit zufälligen Geheimnissen (50 Zeichen).

> Eine bereits vorhandene `.env` wird **nicht** überschrieben.

### 3.3 Domain in `.env` eintragen

Vor dem ersten Start die Domain setzen (siehe auch Abschnitt 4):

```dotenv
ALLOWED_HOSTS=quartiere.example.de,10.42.42.20
CSRF_TRUSTED_ORIGINS=https://quartiere.example.de
PUBLIC_BASE_URL=https://quartiere.example.de
DEFAULT_FROM_EMAIL=Re:Hof <noreply@quartiere.example.de>
```

- `ALLOWED_HOSTS` — kommagetrennt; die Container-IP `10.42.42.20` erlaubt den
  internen Health-Check (Loopback `127.0.0.1`/`localhost` ergänzt Django ohnehin
  automatisch).
- `CSRF_TRUSTED_ORIGINS` — muss als **https-Origin** angegeben werden (CSRF hinter
  dem TLS-terminierenden Caddy).

### 3.4 Stack bauen und starten

```bash
./install.sh --start          # baut & startet (docker compose up -d --build)
# ODER mit Demo-/Testdaten beim ersten Start:
./install.sh --seed           # setzt zusätzlich SEED_DEMO=1 in der .env
```

`--seed` setzt `SEED_DEMO=1`. **Wichtig:** Diese Demo-Flags (`SEED_DEMO`,
`DEMO_RESET`, `DEMO_WIPE`) wirken **bei jedem Start erneut** — nach dem einmaligen
Befüllen in der `.env` wieder auf `0` setzen, sonst werden die Daten bei jedem
Neustart neu angelegt bzw. (bei `DEMO_RESET`/`DEMO_WIPE`) **gelöscht**.

Migrationen laufen automatisch beim Container-Start (Entrypoint: warten auf DB →
`migrate` → Gunicorn).

### 3.5 Admin-Konto anlegen

```bash
docker compose exec web python manage.py createsuperuser
```

Der Superuser ist die **Admin-Rolle** (volles Backend `/admin/`). Eine separate
**Verwaltung**-Rolle (Dashboard `/verwaltung/`, kein Backend) entsteht, indem ein
Nutzer im Backend der Gruppe „Verwaltung" hinzugefügt wird (ADR 0014).

> ⚠️ **Wichtig – Backend-2FA (ADR 0061):** In Produktion (`DEBUG=0`) verlangt das
> Backend einen zweiten Faktor (TOTP). **Direkt nach `createsuperuser`** ein
> TOTP-Gerät einrichten, sonst sperrt sich der Admin selbst aus:
> ```bash
> docker compose exec web python manage.py admin_otp_setup --user <name>
> ```
> Den ausgegebenen QR-Code in einer Authenticator-App (Aegis/FreeOTP/…) scannen;
> beim nächsten Backend-Login zusätzlich den 6-stelligen Code eingeben. Notnagel,
> falls man sich ausgesperrt hat: `ADMIN_OTP_REQUIRED=0` in der `.env`, Stack neu
> starten, Gerät einrichten, wieder auf `1`/leer setzen.

### 3.6 Caddy konfigurieren

Den Block aus `caddy/Caddyfile.snippet` ins Caddyfile übernehmen, Domain anpassen:

```caddy
quartiere.example.de {
    encode gzip
    reverse_proxy 10.42.42.20:8000
}
```

Dann neu laden:

```bash
sudo systemctl reload caddy        # oder: caddy reload --config /etc/caddy/Caddyfile
```

> **Warum bindet `web` nur intern?** TLS macht **Caddy am Host**. `web`
> veröffentlicht keinen Host-Port, sondern ist nur im Docker-Netz `compose_web`
> unter `10.42.42.20:8000` (bzw. `web:8000`) erreichbar — Caddy proxyt dorthin per
> HTTP. So ist Gunicorn nie direkt aus dem Internet exponiert.

Der Caddy-Container **muss** am Netz `compose_web` hängen. Mit
`docker network ls` / `docker inspect <caddy>` prüfen; ggf. den Netznamen in
`docker-compose.yml` (`networks.caddy.name`) an die eigene Umgebung anpassen.

---

## 4. Umgebungsvariablen (`.env`)

Alle Variablen stammen aus `.env.example`. Pflicht = muss gesetzt sein; sonst
greifen die genannten Defaults aus `config/settings.py` / `docker-compose.yml`.

### Django-Kern

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `SECRET_KEY` | **ja** | Django-Geheimnis. Von `install.sh` erzeugt. |
| `ALLOWED_HOSTS` | **ja** | Erlaubte Hostnamen, kommagetrennt. `127.0.0.1`/`localhost` werden automatisch ergänzt. |
| `CSRF_TRUSTED_ORIGINS` | **ja** | https-Origin(s) der Domain (CSRF hinter Caddy). |
| `SECURE_HSTS_SECONDS` | optional | HSTS-Dauer; **Default 2592000 (30 Tage)**, `0` = aus. |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | optional | Default `0`. Erst `1`, wenn **alle** Subdomains dauerhaft HTTPS sind (schwer rückgängig). |
| `SECURE_HSTS_PRELOAD` | optional | Default `0`. Nur `1` für die Browser-Preload-Liste (irreversibel). |
| `TZ` | optional | Zeitzone für Logs/Monatswechsel. Default `Europe/Berlin`. |

> Hinter Caddy gesetzt (in `settings.py`, greifen bei `DEBUG=0`):
> `SECURE_PROXY_SSL_HEADER` (X-Forwarded-Proto), `USE_X_FORWARDED_HOST`,
> Secure-Cookies an, `X_FRAME_OPTIONS=DENY`, Axes-Proxy-Count 1.

### Sicherheits-Härtung (ADR 0061)

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `ADMIN_OTP_REQUIRED` | optional | Backend-2FA erzwingen. Default: **an in Produktion** (`not DEBUG`). Vor dem ersten Login `manage.py admin_otp_setup` ausführen! |
| `FIELD_ENCRYPTION_KEY` | optional | Schlüssel für die (noch inaktive) Feld-Verschlüsselung. Leer = aus. Mit `manage.py field_key` erzeugen, getrennt sichern. |
| `RATELIMIT_ENABLE` | optional | Rate-Limiting sensibler Endpunkte. Default: **an in Produktion**. |
| `CSP_REPORT_ONLY` | optional | `1` = CSP nur melden statt durchsetzen (vorsichtiger Rollout). Default: durchsetzen. |
| `BACKUP_PASSPHRASE` | für Backup | Passphrase für `ops/backup.sh` (AES-256). Getrennt vom Backup aufbewahren – Verlust = Backups unwiederbringlich. |
| `BACKUP_DIR` / `BACKUP_KEEP` / `BACKUP_RCLONE_REMOTE` | optional | Backup-Ziel / lokale Rotation / Off-site-Ziel (rclone). |

### Datenbank

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `POSTGRES_DB` | **ja** | DB-Name. Default `rehof`. |
| `POSTGRES_USER` | **ja** | DB-Benutzer. Default `rehof`. |
| `POSTGRES_PASSWORD` | **ja** | DB-Passwort. Von `install.sh` erzeugt. |

`docker-compose.yml` baut daraus `DATABASE_URL=postgres://USER:PASS@db:5432/DB`.
**Fehlt `DATABASE_URL`, nutzt Django SQLite** — das ist nur für lokale
Entwicklung/Tests, **nicht** für den Server.

### Gunicorn / Scheduler

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `GUNICORN_WORKERS` | optional | Anzahl Gunicorn-Worker. Default `3`. |
| `CRON_INTERVAL_SECONDS` | optional | Scheduler-Intervall in Sekunden. Default `900` (15 Min). |

### E-Mail

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `PUBLIC_BASE_URL` | empfohlen | Basis-URL für Links in E-Mails (z. B. `https://quartiere.example.de`). |
| `DEFAULT_FROM_EMAIL` | optional | Absender. Default `Re:Hof <noreply@localhost>`. |
| `EMAIL_HOST` | optional | SMTP-Host. **Leer = Konsolen-Backend** (Mails landen im Container-Log). |
| `EMAIL_PORT` | optional | Default `587`. |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | optional | SMTP-Zugangsdaten. |
| `EMAIL_USE_TLS` | optional | Default `1`. |
| `EMAIL_USE_SSL` | optional | Default `0`. |

### Observability (ADR 0046)

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `LOG_LEVEL` | optional | `DEBUG`/`INFO`/`WARNING`. Default `INFO` (Logs nach stdout). |
| `SENTRY_DSN` | optional | **Leer = Sentry aus.** Mit DSN aktiv, ohne PII. |
| `SENTRY_ENVIRONMENT` | optional | Umgebungs-Tag. Default `production`. |
| `SENTRY_TRACES_SAMPLE_RATE` | optional | Performance-Sampling; `0` = aus, z. B. `0.1`. |

### Web-Push / VAPID (ADR 0044)

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `VAPID_PUBLIC_KEY` | optional | **Ohne Schlüsselpaar ist Push aus** (`PUSH_ENABLED`). |
| `VAPID_PRIVATE_KEY` | optional | Privater Schlüssel (geheim halten). |
| `VAPID_ADMIN_EMAIL` | optional | Kontakt im VAPID-Claim (mailto:). |

### Optional: Redis / Demo

| Variable | Pflicht | Bedeutung / Default |
|---|---|---|
| `REDIS_URL` | optional | **Leer = aus** (DB-Sessions). Aktivieren: s. Abschnitt 10. |
| `SEED_DEMO` | optional | `1` = Demo-/Testdaten **additiv** anlegen. Default `0`. |
| `DEMO_RESET` | optional | `1` = **alle** Daten löschen **und** Demo neu. Vorsicht! Default `0`. |
| `DEMO_WIPE` | optional | `1` = **nur** alle Daten löschen. Vorsicht! Default `0`. |

> Die `RETENTION_*`-Fristen (DSGVO-Aufräumen) sind ebenfalls per Env
> überschreibbar, haben aber sinnvolle Defaults (siehe `config/settings.py` /
> ADR 0043) und müssen normalerweise nicht gesetzt werden.

---

## 5. Web-Push / VAPID einrichten

Push ist **optional** und standardmäßig aus. Schlüsselpaar erzeugen:

```bash
docker compose exec web python manage.py vapid_keys
```

Die ausgegebenen Werte in die `.env` übernehmen und neu starten:

```dotenv
VAPID_PUBLIC_KEY=…
VAPID_PRIVATE_KEY=…
VAPID_ADMIN_EMAIL=admin@quartiere.example.de
```

```bash
docker compose up -d        # WICHTIG: neu hochfahren, sonst greift die neue .env nicht
```

> **Häufige Stolperfalle:** Nach dem Eintragen in die `.env` muss der Container
> **neu erstellt** werden (`docker compose up -d` – nicht nur „restart“), damit die
> neuen Variablen ankommen. `compose.yml` reicht `VAPID_*` an **web und cron** durch.
> Prüfen lässt es sich am schnellsten so:
> ```bash
> docker compose exec web python -c "from django.conf import settings; print('PUSH_ENABLED', settings.PUSH_ENABLED)"
> ```
> `True` = der Server ist bereit; im Profil erscheint dann der Aktivieren-Knopf statt
> „auf diesem Server nicht aktiviert“.

Erst wenn **beide** Schlüssel gesetzt sind, ist `PUSH_ENABLED` aktiv.
`VAPID_ADMIN_EMAIL` ist nur der Kontakt im VAPID-Claim – es genügt eine **gültige
`mailto:`-Adresse im Format** (ein echtes Postfach ist nicht nötig).

**Auf dem iPhone** zusätzlich nötig (iOS-Vorgaben): iOS **16.4+**, die App per Safari
**„Zum Home-Bildschirm“** hinzufügen und **aus diesem Symbol** öffnen – Push gibt es
nur in der installierten PWA, nicht im Safari-Tab. Danach im Profil aktivieren und im
Dialog **Erlauben**. (Bedien-Schritte für Mitglieder stehen auch in der Hilfe.)

Mitglieder aktivieren Push **pro Gerät** über den Opt-in-Knopf im Profil; jede In-App-
Benachrichtigung wird dann zusätzlich als Web-Push zugestellt (best-effort).

---

## 6. Monitoring & Observability (ADR 0046)

**(a) Health-Endpoint `/healthz/`** — ohne Login, prüft eine DB-Query, liefert
`HTTP 200`, wenn Gunicorn **und** DB erreichbar sind. Genutzt vom
Container-Healthcheck **und** für externes Uptime-Monitoring:

```
GET https://quartiere.example.de/healthz/   →  erwartet HTTP 200
```

Beim Uptime-Dienst (z. B. UptimeRobot, Healthchecks.io) auf diese URL prüfen.

**(b) Strukturierte Logs** nach stdout — Docker sammelt sie:

```bash
docker compose logs -f web      # Live-Logs des Web-Containers
docker compose logs -f cron     # Scheduler-Logs
```

Ausführlichkeit über `LOG_LEVEL` (`DEBUG`/`INFO`/`WARNING`).

**(c) Sentry** — nur mit gesetztem `SENTRY_DSN` aktiv, **ohne PII**
(`send_default_pii=False`, DSGVO). `SENTRY_ENVIRONMENT` taggt die Umgebung,
`SENTRY_TRACES_SAMPLE_RATE` steuert das Performance-Sampling.

**(d) Container-Zustand:**

```bash
docker compose ps              # zeigt healthy/unhealthy je Dienst
```

`unhealthy` an `web` heißt: Gunicorn antwortet nicht oder die DB ist weg (z. B.
nach abgebrochener Migration) — sichtbar, bevor Caddy nur 502 liefert.

---

## 7. E-Mail-Versand

- **Ohne `EMAIL_HOST`** läuft das **Konsolen-Backend**: Mails landen im
  Container-Log (gut für Tests, kein Versand).
- **Für echten Versand** die `EMAIL_*`-Variablen in der `.env` setzen (s. Abschnitt 4).
- E-Mails laufen über eine **Outbox** (Modell `OutboxEmail`): die App stellt Mails
  in die Warteschlange, der **Scheduler** verschickt sie regelmäßig per
  `send_outbox` (jedes Intervall). Rechnungs-PDFs hängen als Anhang an.

---

## 8. Online-Bezahlung (Mollie)

Online-Bezahlung gilt für Hofladen-Rechnungen **und** externe Gäste (eine
`Invoice` je Empfänger). Konfiguriert wird sie **im Backend** am `ShopConfig`-
Singleton, **nicht** über die `.env`:

- `payments_active` ein/aus, `mollie_api_key` eintragen.
- **Ohne API-Key:** eingebauter **Test-/Sandbox-Modus** (simulierte Bezahlseite,
  kein Konto/keine Gebühren).
- `test_…`-Key = Mollie-Testumgebung, `live_…`-Key = echte Zahlungen.

Details in `CLAUDE.md` (Abschnitt „Online-Bezahlung") und ADR 0017.

---

## 9. Hintergrund-Aufgaben (Scheduler/Cron)

Der **`cron`-Container** ersetzt klassischen Cron (`python manage.py run_scheduler`,
ADR 0021). Er läuft im Dauerbetrieb und führt aus:

- **jedes Intervall** (`CRON_INTERVAL_SECONDS`, Default 900 s):
  - `run_due_lotteries` — fällige Losungen ausführen / Perioden weiterschalten,
  - `send_outbox` — wartende E-Mails verschicken;
- **einmal pro Tag** (idempotent):
  - `run_monthly_invoices` — am Monatsanfang die Hofladen-Rechnungen erstellen,
  - `notify_admins_upcoming` — Monats-Mail an die Verwaltung,
  - `cleanup_data` — DSGVO-Aufräumen anhand der `RETENTION_*`-Fristen.

Alle Kommandos sind **idempotent**; ein Neustart schadet nicht. Fehler eines Laufs
werden geloggt und beenden den Scheduler nicht. Einzeln manuell auslösbar:

```bash
docker compose exec web python manage.py run_due_lotteries
docker compose exec web python manage.py send_outbox
docker compose exec web python manage.py cleanup_data
# Ein einzelner Scheduler-Durchlauf (statt Dauerbetrieb):
docker compose exec web python manage.py run_scheduler --once
```

---

## 10. Redis aktivieren (Cache/Sessions/Axes) – empfohlen ab vielen Nutzern

**Standard ist bewusst DB-only** (nur PostgreSQL → minimaler, robuster Stack).
**Wann einschalten?** Sobald viele gleichzeitige Nutzer erwartet werden
(Richtwert ab ~50–100): Redis nimmt die **Session-Lese-Last bei jedem Request**
sowie die **Brute-Force-Zähler** aus der DB und macht den **geteilten Belegungs-
Cache** (ADR 0060) erst wirksam (mit nur einem Worker-Prozess wäre er „stale“).

### Aktivieren in zwei Schritten

1. In der `.env` setzen:
   ```dotenv
   REDIS_URL=redis://redis:6379/0
   ```
2. Stack inkl. Redis-Dienst (Profil `cache`) neu starten:
   ```bash
   docker compose --profile cache up -d
   ```

> Damit das Profil **bei jedem** `docker compose …` mitläuft (z.B. künftige
> Updates), dauerhaft setzen: `COMPOSE_PROFILES=cache` in der `.env` – dann genügt
> wieder `docker compose up -d`.

### Prüfen

```bash
docker compose ps                                   # redis: „healthy“
docker compose exec web python manage.py shell -c \
  "from django.conf import settings as s; print(s.SESSION_ENGINE, s.CACHES['default']['BACKEND'])"
# erwartet: django.contrib.sessions.backends.cached_db … RedisCache
docker compose exec redis redis-cli ping            # PONG
```

### Was passiert dabei (sicher per Default)

- **Sitzungen: `cached_db`** – gelesen aus Redis (DB-Entlastung), aber **persistent
  in der DB**. Ein Redis-Neustart/-Ausfall loggt **niemanden** aus (nur kurz wieder
  DB-Lesen). Bestehende DB-Sitzungen werden weitergelesen → **nahtloser Umstieg**,
  kein Logout beim Aktivieren.
- **Eviction `volatile-lru` + `--save ""`**: Redis hält keine Platte vor (reiner
  Cache) und verdrängt unter Speicherdruck nur Schlüssel **mit Ablauf** – nie
  versehentlich dauerhafte Daten. 256 MB genügen für eine Genossenschaft.
- **Axes (Brute-Force) im Cache**: weniger DB-Schreibzugriffe beim Login.

### Sicherheit

- Redis läuft **nur im internen Docker-Netz** und veröffentlicht **keinen
  Host-Port** – nicht ändern, nicht exponieren (Redis hat hier keine Auth).
- Im Cache liegen nur **Sitzungs-/Belegungs-/Zähler-Daten**, keine Geheimnisse;
  Belegungsdaten sind ohnehin allen Mitgliedern sichtbar (kein Vertraulichkeits-
  verlust). Buchung/Checkout prüfen weiterhin **immer frisch unter Sperre** – der
  Cache ist reine Anzeige-/Sitzungs-Beschleunigung.

### Wieder ausschalten (zurück zu DB-only)

`REDIS_URL` in der `.env` leeren (bzw. `COMPOSE_PROFILES` entfernen) und
`docker compose up -d` – die App nutzt wieder DB-Sessions; die in der DB
gespeicherten Sitzungen bleiben gültig.

> Siehe auch `docs/BETRIEB-SICHERHEIT.md` → „Performance & Skalierung“ (Worker-/
> DB-Verbindungsbudget, PgBouncer) und ADR 0060.

---

## 11. Updates / Upgrades

```bash
git pull
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose ps                 # auf "healthy" prüfen
```

- Vor dem Pull am **grünen CI-Häkchen** orientieren (Tests + Migrations-Resilienz
  + E2E laufen pro Push/PR, siehe ADR 0022/0047).
- Nach dem Hochfahren `docker compose ps` prüfen — `web` muss `healthy` werden
  (Startfenster `start_period` 40 s für Warten-auf-DB + Migration + Start).
- `python manage.py makemigrations --check` darf keine fehlende Migration zeigen
  (im CI abgesichert).

---

## 12. Backup & Server-Umzug

Datenbank-Dump/-Restore über `ops/migrate-server.sh` (nutzt `pg_dump`/`psql` im
laufenden `db`-Container). `.env` muss vorhanden sein (liefert `POSTGRES_*`).

**Auf dem alten Server:**

```bash
./ops/migrate-server.sh dump                 # -> rehof-dump-DATUM.sql.gz
scp rehof-dump-*.sql.gz .env  user@neu:/opt/rehof/
```

**Auf dem neuen Server** (im Repo, `.env` mitgebracht):

```bash
docker compose up -d db
./ops/migrate-server.sh restore rehof-dump-*.sql.gz   # ÜBERSCHREIBT die DB (Rückfrage „ja")
docker compose up -d
docker compose exec web python manage.py migrate
```

Der Dump nutzt `--clean --if-exists --no-owner --no-privileges`, räumt also vor dem
Einspielen selbst auf (sauberer Restore auch in eine leere DB).

**Verschlüsseltes Backup (ADR 0061):** für regelmäßige, off-site gesicherte Backups
`ops/backup.sh` nutzen (pg_dump → gzip → GnuPG AES-256, optional rclone). Per
Host-Cron einplanen (Beispiel im Skriptkopf):

```bash
BACKUP_PASSPHRASE=… ./ops/backup.sh backup          # erzeugt rehof-DATUM.sql.gz.gpg
BACKUP_PASSPHRASE=… ./ops/backup.sh restore <datei> # spielt es wieder ein
```

> **Weiteres Hardening (Borg-Append-only-Backups, LUKS) bleibt GEPLANT** —
> 2FA, CSP, Rate-Limiting, Audit, Nicht-root u. a. sind umgesetzt (ADR 0061);
> Risiken/Blueprints in [`BETRIEB-SICHERHEIT.md`](BETRIEB-SICHERHEIT.md).

---

## 13. Fehlersuche

| Symptom | Vorgehen |
|---|---|
| Seite nicht erreichbar, **502 bei Caddy** | `web` ist weg/unhealthy. `docker compose ps`, dann `docker compose logs -f web`. |
| `docker compose ps` zeigt **`unhealthy`** | Gunicorn antwortet nicht oder DB weg (z. B. abgebrochene Migration). Logs prüfen, ggf. `docker compose up -d` / `migrate`. |
| Health-Check rot | `curl -fsS https://quartiere.example.de/healthz/` (erwartet 200) bzw. intern `docker compose exec web curl -fsS http://127.0.0.1:8000/healthz/`. |
| Caddy erreicht `web` nicht | Hängt Caddy am Netz `compose_web`? `docker network inspect compose_web` — `web` muss `10.42.42.20` haben. |
| CSRF-Fehler beim Login/POST | `CSRF_TRUSTED_ORIGINS` als `https://…` gesetzt? Domain in `ALLOWED_HOSTS`? |
| Mails kommen nicht an | Ohne `EMAIL_HOST` Konsolen-Backend (nur Log). `EMAIL_*` setzen; `docker compose logs -f cron` für `send_outbox`. |
| Demo-Daten erscheinen wieder | `SEED_DEMO`/`DEMO_RESET`/`DEMO_WIPE` in der `.env` auf `0` zurücksetzen. |

---

## 14. Hofladen-Terminal vor Ort (ADR 0053)

Ein **geteiltes Gerät** (Tablet/PC) im Hofladen, an dem freigeschaltete Gäste per
**PIN** auf ihre **Monatsrechnung** einkaufen. Läuft **offline** (kein WLAN/Mobilfunk
im Laden nötig). **Die Sicherheit hängt zu gleichen Teilen an App UND Gerätehärtung –
ohne die folgenden Betriebsschritte ist der Modus NICHT freizugeben.**

**Einrichten:**

1. Im Backend **„Hofladen-Terminal-Einstellungen"** öffnen → **aktivieren**; ein
   **Token** ist gesetzt (sonst Aktion „Neues Token erzeugen"). Idle-Timeout/PIN-Sperre
   nach Bedarf.
2. Personen freischalten: am Benutzer das **Mitglieds-Profil → „Hofladen-Terminal
   erlaubt"** anhaken. Die Person setzt ihre **PIN selbst** im Profil (online/zuhause).
3. Gerät **einmalig online** auf `https://<domain>/terminal/` öffnen → **„Einrichten"**
   → Token einfügen. Das Gerät lädt Roster+Katalog und arbeitet danach **offline**
   weiter; Einkäufe werden bei nächster Verbindung automatisch nachgereicht.

**Pflicht-Härtung des Geräts (Betrieb):**

- **OS-/Browser-Kiosk-Mode**: nur die Seite `/terminal/`, kein Wechsel zu anderen Apps/
  URLs, kein Einstellungszugriff (z. B. iPad „Geführter Zugriff", Android Kiosk-Launcher,
  Chrome/Edge Kiosk).
- **Festplatten-Verschlüsselung** (FileVault/BitLocker/LUKS) – auf dem Gerät liegen
  Roster (Namen + PIN-Hashes) und der Token; ohne FDE bei Diebstahl lesbar.
- **Physische Sicherung** (Halterung/Schloss), **Sichtschutz** für die PIN-Eingabe.
- **Auto-Update** des OS/Browsers.

**Bei Verlust/Diebstahl des Geräts:** im Backend **„Neues Token erzeugen"** – das alte
Token ist sofort ungültig (kein Gerät kann mehr Roster/Sync nutzen). Betroffene PINs
ggf. neu setzen lassen. (Hintergrund/Bedrohungsmodell: ADR 0053 und
[`HOFLADEN-KIOSK-KONZEPT.md`](HOFLADEN-KIOSK-KONZEPT.md).)

---

## Weiterführend

- **Fachliche Regeln** (Losverfahren, Buchungsregeln, Perioden) → [`FACHKONZEPT.md`](FACHKONZEPT.md)
- **Hofladen-Terminal (Konzept/Sicherheit)** → [`HOFLADEN-KIOSK-KONZEPT.md`](HOFLADEN-KIOSK-KONZEPT.md)
- **Architektur-Entscheidungen** → [`adr/README.md`](adr/README.md)
- **Tests & Testumgebung** → [`TESTEN.md`](TESTEN.md)
- **Belastungstests** → [`../loadtest/README.md`](../loadtest/README.md)
- **Backup & Härtung (geplant)** → [`BETRIEB-SICHERHEIT.md`](BETRIEB-SICHERHEIT.md)
- **Externe Gäste** → [`EXTERNE-GAESTE.md`](EXTERNE-GAESTE.md)
