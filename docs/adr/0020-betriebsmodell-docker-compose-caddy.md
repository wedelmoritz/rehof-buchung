# 0020 – Betriebsmodell: Docker-Compose (web + PostgreSQL) hinter separatem Caddy

## Status

Accepted (2026-06-26)

## Kontext

Die App läuft auf einem einzelnen Hetzner-VPS. Betrieb und Updates müssen einfach und
reproduzierbar sein. TLS soll zentral und automatisch (Zertifikate) terminiert
werden, ohne die App damit zu belasten. Die Datenbank darf nicht von außen
erreichbar sein.

## Entscheidung

Ein **Docker-Compose-Stack** mit den Diensten `web` (Django/Gunicorn) und `db`
(PostgreSQL 16); TLS terminiert ein **separater Caddy-Container** über ein
gemeinsames externes Docker-Netz (`docker-compose.yml`).

- **`web` spricht nur HTTP** und hat **keinen** Host-Port (`expose: 8000` statt
  `ports:`); erreichbar nur für Caddy im Netz `compose_web` (feste IP
  `10.42.42.20`).
- **`db` hängt bewusst NICHT am Caddy-Netz** (`networks: internal`), ist also nicht
  öffentlich erreichbar.
- **Hinter Caddy:** Django erkennt HTTPS über `SECURE_PROXY_SSL_HEADER` und baut URLs
  unter der öffentlichen Domain (`USE_X_FORWARDED_HOST`), TLS-Redirect macht Caddy
  (`config/settings.py:204-222`).
- **Start-Ablauf** in `entrypoint.sh`: auf DB warten → `migrate` → optional seeden →
  Gunicorn (3 Worker, `--timeout 60`, `--max-requests` zum Recyceln).
- **Healthchecks** an `web` und `db` machen einen kaputten Start (z. B. abgebrochene
  Migration) sofort an `docker compose ps` sichtbar (`unhealthy`).
- **Optionales Redis** (Cache/Sessions/Axes) über Profil `cache` zuschaltbar.

## Betrachtete Alternativen

- **TLS in der App / Gunicorn:** Zertifikatsverwaltung und HTTP/2 im App-Container –
  mehr Komplexität; Caddy macht das automatisch.
- **Reverse Proxy nginx + certbot:** funktioniert, aber mehr Konfiguration als Caddys
  Auto-TLS.
- **DB als Managed Service:** zusätzlicher Kosten-/Betriebsfaktor; auf einem VPS ist
  der Container ausreichend (Umzug per `ops/migrate-server.sh`).

## Konsequenzen

**Positiv**
- Einfacher, reproduzierbarer Betrieb; automatisches TLS via Caddy.
- DB nicht öffentlich; klare Netz-Trennung (`internal` vs. `caddy`).
- Kaputte Starts sofort erkennbar (Healthchecks).

**Negativ**
- Single-VPS ohne horizontale Skalierung; Kapazität hängt an Worker-Zahl/DB (siehe
  `loadtest/`).
- Caddy muss als externer Container im erwarteten Netz laufen (Kopplung über
  `compose_web`).
