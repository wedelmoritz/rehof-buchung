#!/usr/bin/env bash
#
# Install-Skript für die Re:Hof Quartier-Buchung.
#
# Prüft die Voraussetzungen (Docker, Docker Compose, git) und installiert sie
# bei Bedarf (Debian/Ubuntu). Erzeugt eine .env mit zufälligen Geheimnissen
# und kann den Stack direkt bauen und starten.
#
# Aufruf:
#   ./install.sh            # prüfen, ggf. installieren, .env anlegen
#   ./install.sh --start    # zusätzlich: Stack bauen & starten
#   ./install.sh --seed     # wie --start, aber mit Demo-Daten beim ersten Start
#
# Das Skript ist idempotent: Mehrfaches Ausführen schadet nicht.

set -euo pipefail

# ----------------------------------------------------------------------------
# Hilfsausgaben
# ----------------------------------------------------------------------------
GRUEN='\033[0;32m'; GELB='\033[0;33m'; ROT='\033[0;31m'; AUS='\033[0m'
info()  { echo -e "${GRUEN}[ok]${AUS}  $*"; }
warn()  { echo -e "${GELB}[!]${AUS}   $*"; }
fehler(){ echo -e "${ROT}[fehler]${AUS} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DO_START=0
DO_SEED=0
for arg in "$@"; do
  case "$arg" in
    --start) DO_START=1 ;;
    --seed)  DO_START=1; DO_SEED=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) warn "Unbekanntes Argument: $arg" ;;
  esac
done

# ----------------------------------------------------------------------------
# 0. Rechte / sudo bestimmen
# ----------------------------------------------------------------------------
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    warn "Kein root und kein sudo gefunden – eine Installation von Paketen kann fehlschlagen."
  fi
fi

# ----------------------------------------------------------------------------
# 1. git prüfen / installieren
# ----------------------------------------------------------------------------
if command -v git >/dev/null 2>&1; then
  info "git ist vorhanden ($(git --version))."
else
  warn "git fehlt – versuche Installation …"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq git
    info "git installiert."
  else
    fehler "Kein apt-get gefunden. Bitte git manuell installieren."
    exit 1
  fi
fi

# ----------------------------------------------------------------------------
# 2. Docker prüfen / installieren
# ----------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  info "Docker ist vorhanden ($(docker --version))."
else
  warn "Docker fehlt – installiere über das offizielle Convenience-Skript …"
  # Offizielles Docker-Installationsskript (Debian/Ubuntu u.a.)
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  $SUDO sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
  info "Docker installiert."
  # Aktuellen Nutzer der docker-Gruppe hinzufügen (wirkt nach Re-Login)
  if [ "$(id -u)" -ne 0 ]; then
    $SUDO usermod -aG docker "$USER" || true
    warn "Du wurdest der Gruppe 'docker' hinzugefügt. Bitte einmal ab- und neu anmelden,"
    warn "damit 'docker' ohne sudo läuft (oder den Stack vorerst mit sudo starten)."
  fi
fi

# Docker-Daemon ggf. starten
if command -v systemctl >/dev/null 2>&1; then
  if ! $SUDO systemctl is-active --quiet docker; then
    warn "Docker-Daemon ist nicht aktiv – starte ihn …"
    $SUDO systemctl enable --now docker || true
  fi
fi

# ----------------------------------------------------------------------------
# 3. Docker Compose prüfen / installieren
# ----------------------------------------------------------------------------
if docker compose version >/dev/null 2>&1; then
  info "Docker Compose (Plugin) ist vorhanden ($(docker compose version | head -1))."
elif command -v docker-compose >/dev/null 2>&1; then
  warn "Nur das alte 'docker-compose' (v1) gefunden. Empfohlen ist das v2-Plugin."
else
  warn "Docker Compose fehlt – installiere das Plugin …"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq docker-compose-plugin
    info "docker-compose-plugin installiert."
  else
    fehler "Konnte Docker Compose nicht automatisch installieren. Bitte manuell nachrüsten."
    exit 1
  fi
fi

# Hilfsfunktion: passendes Compose-Kommando wählen
compose() {
  if docker compose version >/dev/null 2>&1; then
    $SUDO docker compose "$@"
  else
    $SUDO docker-compose "$@"
  fi
}

# ----------------------------------------------------------------------------
# 4. .env anlegen und Geheimnisse generieren
# ----------------------------------------------------------------------------
gen_secret() {
  # 50 Zeichen, URL-sicher – bevorzugt openssl, sonst Python
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-50
  else
    python3 -c "import secrets; print(secrets.token_urlsafe(48)[:50])"
  fi
}

if [ -f .env ]; then
  info ".env ist bereits vorhanden – wird nicht überschrieben."
else
  warn ".env wird aus .env.example erzeugt …"
  cp .env.example .env

  SECRET_VALUE="$(gen_secret)"
  DBPASS_VALUE="$(gen_secret)"

  # Werte eintragen (nur die leeren Felder; portabel via Python, um sed-Quoting
  # mit Sonderzeichen zu vermeiden)
  python3 - "$SECRET_VALUE" "$DBPASS_VALUE" << 'PY'
import sys, pathlib
secret, dbpass = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env")
lines = p.read_text().splitlines()
out = []
for line in lines:
    if line.startswith("SECRET_KEY="):
        out.append(f"SECRET_KEY={secret}")
    elif line.startswith("POSTGRES_PASSWORD="):
        out.append(f"POSTGRES_PASSWORD={dbpass}")
    else:
        out.append(line)
p.write_text("\n".join(out) + "\n")
PY
  info ".env erzeugt und mit zufälligem SECRET_KEY + DB-Passwort befüllt."
  warn "Bitte in .env noch ALLOWED_HOSTS und CSRF_TRUSTED_ORIGINS auf deine Domain setzen."
fi

if [ "$DO_SEED" = "1" ]; then
  # SEED_DEMO in .env auf 1 setzen
  python3 - << 'PY'
import pathlib
p = pathlib.Path(".env"); lines = p.read_text().splitlines(); out=[]
done=False
for line in lines:
    if line.startswith("SEED_DEMO="):
        out.append("SEED_DEMO=1"); done=True
    else:
        out.append(line)
if not done: out.append("SEED_DEMO=1")
p.write_text("\n".join(out) + "\n")
PY
  info "SEED_DEMO=1 gesetzt (Demo-Daten werden beim ersten Start angelegt)."
fi

# ----------------------------------------------------------------------------
# 5. Optional: bauen & starten
# ----------------------------------------------------------------------------
if [ "$DO_START" = "1" ]; then
  info "Baue und starte den Stack …"
  compose up -d --build
  echo
  info "Stack läuft. Status:"
  compose ps
  echo
  warn "Noch zu tun:"
  echo "  1) Admin-Konto anlegen:"
  echo "       $( [ -n \"$SUDO\" ] && echo sudo )docker compose exec web python manage.py createsuperuser"
  echo "  2) Domain in .env (ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS) eintragen, dann:"
  echo "       $( [ -n \"$SUDO\" ] && echo sudo )docker compose up -d"
  echo "  3) Caddy konfigurieren (siehe caddy/Caddyfile.snippet) und neu laden."
  echo "       Caddy muss am selben Docker-Netz hängen wie 'web' (networks.caddy)."
else
  echo
  info "Voraussetzungen geprüft und .env vorbereitet."
  warn "Nächste Schritte:"
  echo "  1) .env prüfen (Domain in ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS eintragen)"
  echo "  2) Starten:        ./install.sh --start    (oder mit Demo-Daten: ./install.sh --seed)"
  echo "  3) Admin anlegen:  docker compose exec web python manage.py createsuperuser"
  echo "  4) Caddy:          siehe caddy/Caddyfile.snippet"
fi
