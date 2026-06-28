#!/usr/bin/env bash
#
# Verschlüsseltes Off-site-Backup der Re:Hof-Quartierbuchung (ADR 0061, P3.10).
#
# Erzeugt einen PostgreSQL-Dump aus dem laufenden db-Container, verschlüsselt ihn
# clientseitig mit GnuPG (AES-256, symmetrisch) und legt ihn lokal ab; optional
# wird er off-site hochgeladen (rclone). So liegen Backups NIE unverschlüsselt
# außerhalb des Servers – Schlüssel (Passphrase) bleibt getrennt vom Dump.
#
# Nutzung (aus dem Repo-Wurzelverzeichnis, .env muss vorhanden sein):
#
#   ./ops/backup.sh backup            Dump erzeugen, verschlüsseln, (optional) hochladen
#   ./ops/backup.sh restore <datei>   Verschlüsseltes Backup wieder einspielen (ÜBERSCHREIBT!)
#
# Voraussetzungen / Umgebung (in der .env oder Shell):
#   BACKUP_PASSPHRASE      (PFLICHT) – starke Passphrase für die Verschlüsselung.
#                          GETRENNT vom Backup aufbewahren (Passwortmanager/Tresor);
#                          Verlust = die Backups sind unwiederbringlich.
#   BACKUP_DIR             Zielverzeichnis (Default: ./backups).
#   BACKUP_KEEP            Anzahl lokal zu behaltender Backups (Default: 14).
#   BACKUP_RCLONE_REMOTE   optional: rclone-Ziel (z.B. "b2:rehof-backups"). Gesetzt →
#                          das verschlüsselte File wird zusätzlich dorthin kopiert.
#
# Cron-Beispiel (täglich 3:15, Logzeile ans Syslog):
#   15 3 * * *  cd /opt/rehof && ./ops/backup.sh backup >> /var/log/rehof-backup.log 2>&1
#
set -euo pipefail

cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "FEHLER: Docker Compose nicht gefunden." >&2
  exit 1
fi

cmd="${1:-}"
case "$cmd" in
  backup|restore) : ;;
  *) sed -n '2,33p' "$0"; exit 1 ;;
esac

[ -f .env ] || { echo "FEHLER: .env nicht gefunden." >&2; exit 1; }
set -a; . ./.env; set +a
: "${POSTGRES_USER:?POSTGRES_USER fehlt in .env}"
: "${POSTGRES_DB:?POSTGRES_DB fehlt in .env}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE fehlt (starke Passphrase, getrennt sichern!)}"

command -v gpg >/dev/null || { echo "FEHLER: gpg nicht installiert." >&2; exit 1; }

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
db_running() { $DC ps --status running db 2>/dev/null | grep -q db; }

case "$cmd" in
  backup)
    db_running || { echo "FEHLER: db-Container läuft nicht ($DC up -d db)." >&2; exit 1; }
    mkdir -p "$BACKUP_DIR"
    ts="$(date +%Y-%m-%d_%H%M)"
    out="$BACKUP_DIR/rehof-$ts.sql.gz.gpg"
    echo "→ Dump aus '$POSTGRES_DB' erzeugen, verschlüsseln (AES-256) …"
    # Pipe: pg_dump → gzip → gpg. Der Klartext landet NIE auf der Platte.
    $DC exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        --clean --if-exists --no-owner --no-privileges \
      | gzip \
      | gpg --batch --yes --symmetric --cipher-algo AES256 \
            --passphrase "$BACKUP_PASSPHRASE" -o "$out"
    echo "✓ Verschlüsseltes Backup: $out ($(du -h "$out" | cut -f1))"

    if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
      command -v rclone >/dev/null || { echo "FEHLER: rclone nicht installiert." >&2; exit 1; }
      echo "→ Off-site hochladen nach $BACKUP_RCLONE_REMOTE …"
      rclone copy "$out" "$BACKUP_RCLONE_REMOTE"
      echo "✓ Off-site-Kopie abgelegt."
    else
      echo "  (Kein BACKUP_RCLONE_REMOTE gesetzt → nur lokal. Für echtes Off-site setzen.)"
    fi

    # Aufräumen: nur die jüngsten BACKUP_KEEP behalten.
    ls -1t "$BACKUP_DIR"/rehof-*.sql.gz.gpg 2>/dev/null | tail -n +"$((BACKUP_KEEP+1))" \
      | while read -r old; do echo "  entferne altes Backup: $old"; rm -f "$old"; done
    ;;

  restore)
    file="${2:-}"
    [ -n "$file" ] || { echo "Nutzung: $0 restore <datei.sql.gz.gpg>" >&2; exit 1; }
    [ -f "$file" ] || { echo "FEHLER: Datei nicht gefunden: $file" >&2; exit 1; }
    db_running || { echo "FEHLER: db-Container läuft nicht ($DC up -d db)." >&2; exit 1; }
    echo "!! ACHTUNG: Dies ÜBERSCHREIBT die Datenbank '$POSTGRES_DB'."
    printf "   Fortfahren? [tippe ja]: "; read -r ans
    [ "$ans" = "ja" ] || { echo "Abgebrochen."; exit 1; }
    echo "→ Entschlüsseln und einspielen …"
    gpg --batch --yes --decrypt --passphrase "$BACKUP_PASSPHRASE" "$file" \
      | gunzip -c \
      | $DC exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null
    echo "✓ Restore abgeschlossen. Empfehlung: '$DC exec web python manage.py migrate'."
    ;;
esac
