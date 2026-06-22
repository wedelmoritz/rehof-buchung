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
# --max-requests recycelt Worker periodisch (begrenzt Speicherwachstum auf dem
# knappen VPS); --jitter verhindert, dass alle Worker gleichzeitig neu starten.
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 60 \
    --max-requests 1000 \
    --max-requests-jitter 100
