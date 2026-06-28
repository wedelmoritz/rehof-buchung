# Schlankes Python-Image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Systemabhängigkeiten. psycopg[binary] braucht nichts extra; WeasyPrint
# (Rechnungs-PDF) braucht Pango/Cairo/GDK-Pixbuf + Schriften zur Laufzeit.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    libffi8 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static-Dateien einsammeln (WhiteNoise)
RUN DJANGO_SETTINGS_MODULE=config.settings SECRET_KEY=build-time-only \
    python manage.py collectstatic --noinput

# Sicherheit: NICHT als root laufen (ADR 0061). Eigener, unprivilegierter Nutzer;
# ihm gehört /app (Migrationen/collectstatic brauchen keine Schreibrechte zur
# Laufzeit, Uploads gehen in den DB/Temp). Gunicorn bindet 8000 (>1024 → ok ohne
# root). Bei einem App-Einbruch ist der Schadensradius so deutlich kleiner.
RUN useradd --system --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Entrypoint wartet auf die DB, migriert, seedet optional und startet Gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
