#!/usr/bin/env bash
set -e

echo "[entrypoint] Warte auf Datenbank …"
python - << 'PY'
import os, time, sys
import dj_database_url
import psycopg
url = os.environ.get("DATABASE_URL")
cfg = dj_database_url.parse(url)
for i in range(30):
    try:
        psycopg.connect(
            host=cfg["HOST"], port=cfg.get("PORT") or 5432,
            dbname=cfg["NAME"], user=cfg["USER"], password=cfg["PASSWORD"],
        ).close()
        print("[entrypoint] Datenbank erreichbar.")
        sys.exit(0)
    except Exception as e:
        print(f"[entrypoint]   … noch nicht ({i+1}/30): {e}")
        time.sleep(2)
print("[entrypoint] Datenbank nicht erreichbar – Abbruch.")
sys.exit(1)
PY

echo "[entrypoint] Führe Migrationen aus …"
python manage.py migrate --noinput

# Versionierte Historie (ADR 0070): Bestand einen Ausgangs-Stand geben, damit
# „GESCHICHTE → wiederherstellen" auch für vorhandene Daten greift. Idempotent
# (legt nur für Objekte OHNE Version eine an); betrifft nur die registrierten
# Identitäts-Modelle (Benutzer/Mitglied/Anteil/Tage-Anteil).
python manage.py createinitialrevisions --comment "Ausgangs-Stand (Deploy)" || true

# --- Test-/Demo-Daten (für Docker, da kein Python auf dem Host) ---------------
# Genau EINE Option setzen, Container neu starten – DANACH wieder auf 0 setzen,
# sonst läuft die Aktion bei JEDEM Neustart erneut!
#   SEED_DEMO=1   -> Demo-/Testdaten anlegen (additiv, idempotent)
#   DEMO_RESET=1  -> ALLE Daten löschen UND Demo-Daten neu anlegen
#   DEMO_WIPE=1   -> NUR ALLE Daten löschen
if [ "${DEMO_RESET:-0}" = "1" ]; then
  echo "[entrypoint] !!! DEMO_RESET=1: lösche ALLE Daten und lege Demo-Daten neu an !!!"
  python manage.py seed_demo --reset --yes || true
elif [ "${DEMO_WIPE:-0}" = "1" ]; then
  echo "[entrypoint] !!! DEMO_WIPE=1: lösche ALLE Daten !!!"
  python manage.py seed_demo --wipe --yes || true
elif [ "${SEED_DEMO:-0}" = "1" ]; then
  echo "[entrypoint] Lege Demo-/Testdaten an …"
  python manage.py seed_demo --yes || true
fi

echo "[entrypoint] Starte Gunicorn …"
# Django ist I/O-/DB-gebunden → THREADS erlauben echte Gleichzeitigkeit (viele
# Nutzer gleichzeitig) ohne pro Request einen eigenen Prozess. Gleichzeitige
# Requests ≈ workers × threads. ACHTUNG DB-Budget: jeder aktive Thread hält (mit
# conn_max_age) eine eigene PostgreSQL-Verbindung → workers×threads ≤ Postgres
# max_connections (Default 100); bei mehreren Web-Containern PgBouncer davor
# (siehe docs/BETRIEB-SICHERHEIT.md). --max-requests recycelt Worker periodisch
# (begrenzt Speicherwachstum); --jitter entzerrt die Neustarts.
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class "${GUNICORN_WORKER_CLASS:-gthread}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout 60 \
    --max-requests 1000 \
    --max-requests-jitter 100
