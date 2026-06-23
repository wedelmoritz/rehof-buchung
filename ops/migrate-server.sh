#!/usr/bin/env bash
#
# Server-Umzug der Re:Hof-Quartierbuchung – zieht die PostgreSQL-Datenbank um.
#
# Nutzung (aus dem Repo-Wurzelverzeichnis, .env muss vorhanden sein):
#
#   ./ops/migrate-server.sh dump [datei]      Dump aus dem laufenden db-Container
#                                             (Standard: rehof-dump-DATUM.sql.gz)
#   ./ops/migrate-server.sh restore <datei>   Dump in den laufenden db-Container
#                                             einspielen (ÜBERSCHREIBT die DB!)
#
# Typischer Ablauf:
#   ALT:   ./ops/migrate-server.sh dump
#          scp rehof-dump-*.sql.gz .env  user@neu:/opt/rehof/
#   NEU:   docker compose up -d db
#          ./ops/migrate-server.sh restore rehof-dump-*.sql.gz
#          docker compose up -d
#
set -euo pipefail

# Ins Repo-Wurzelverzeichnis wechseln (eine Ebene über diesem Skript).
cd "$(dirname "$0")/.."

# Docker-Compose-Kommando ermitteln (v2 „docker compose“ bzw. altes „docker-compose“).
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "FEHLER: Docker Compose nicht gefunden." >&2
  exit 1
fi

cmd="${1:-}"
# Bei unbekanntem/leerem Kommando direkt die Kurzhilfe zeigen (auch ohne .env).
case "$cmd" in
  dump|restore) : ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac

if [ ! -f .env ]; then
  echo "FEHLER: .env nicht gefunden (mit POSTGRES_USER/POSTGRES_DB)." >&2
  exit 1
fi
# POSTGRES_* aus der .env laden.
set -a; . ./.env; set +a
: "${POSTGRES_USER:?POSTGRES_USER fehlt in .env}"
: "${POSTGRES_DB:?POSTGRES_DB fehlt in .env}"

db_running() { $DC ps --status running db 2>/dev/null | grep -q db; }

case "$cmd" in
  dump)
    out="${2:-rehof-dump-$(date +%Y-%m-%d_%H%M).sql.gz}"
    db_running || { echo "FEHLER: db-Container läuft nicht ($DC up -d db)." >&2; exit 1; }
    echo "→ Erzeuge Dump aus Datenbank '$POSTGRES_DB' …"
    # --clean --if-exists: der Dump räumt vor dem Einspielen selbst auf -> sauberer
    # Restore in eine (auch leere) Ziel-DB.
    $DC exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --clean --if-exists --no-owner --no-privileges \
      | gzip > "$out"
    echo "✓ Dump geschrieben: $out ($(du -h "$out" | cut -f1))"
    echo "  Jetzt zusammen mit der .env auf den neuen Server kopieren (Secrets!)."
    ;;

  restore)
    file="${2:-}"
    [ -n "$file" ] || { echo "Nutzung: $0 restore <datei.sql.gz|.sql>" >&2; exit 1; }
    [ -f "$file" ] || { echo "FEHLER: Datei nicht gefunden: $file" >&2; exit 1; }
    db_running || { echo "FEHLER: db-Container läuft nicht ($DC up -d db)." >&2; exit 1; }
    echo "!! ACHTUNG: Dies ÜBERSCHREIBT die Datenbank '$POSTGRES_DB'."
    printf "   Fortfahren? [tippe ja]: "; read -r ans
    [ "$ans" = "ja" ] || { echo "Abgebrochen."; exit 1; }
    echo "→ Spiele Dump ein …"
    case "$file" in
      *.gz) gunzip -c "$file" ;;
      *)    cat "$file" ;;
    esac | $DC exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null
    echo "✓ Restore abgeschlossen."
    echo "  Empfehlung: '$DC up -d' starten und ggf. '$DC exec web python manage.py migrate'."
    ;;

  *)
    sed -n '2,20p' "$0"   # Kurzhilfe (Kopf-Kommentar) ausgeben
    exit 1
    ;;
esac
