# Schlankes Python-Image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Systemabhängigkeiten (psycopg[binary] braucht i.d.R. nichts extra)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static-Dateien einsammeln (WhiteNoise)
RUN DJANGO_SETTINGS_MODULE=config.settings SECRET_KEY=build-time-only \
    python manage.py collectstatic --noinput

EXPOSE 8000

# Entrypoint wartet auf die DB, migriert, seedet optional und startet Gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
