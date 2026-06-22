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

if [ "${SEED_DEMO:-0}" = "1" ]; then
  echo "[entrypoint] Lege Demo-Daten an …"
  python manage.py seed_demo || true
fi

echo "[entrypoint] Starte Gunicorn …"
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 60
