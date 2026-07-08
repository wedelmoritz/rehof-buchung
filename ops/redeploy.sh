#!/usr/bin/env bash
#
# redeploy.sh — Re:Hof im ROOTLESS-Docker-Daemon (User rehof-svc) bauen/starten.
#
# Warum dieses Skript? Der Re:Hof-Stack läuft bewusst ROOTLESS als eigener User
# (Default: rehof-svc). Wird `docker compose` versehentlich im rootful-Daemon
# gestartet (z.B. als `deploy` mit `docker compose up -d`), entsteht ein ZWEITER,
# eigenständiger Stack: eigenes – leeres – `rehof_pgdata`-Volume und Streit um den
# Host-Port 10.42.42.1:8000. Genau das gilt es zu verhindern.
#
# Das Skript spricht IMMER den rootless-Daemon des Ziel-Users an und BRICHT AB,
# falls es (aus welchem Grund auch immer) beim rootful-Daemon landen würde. Es
# darf als `deploy` laufen (git nutzt dann dessen Repo-Zugang) ODER als rehof-svc.
#
# Nutzung (aus dem Repo heraus):
#   ops/redeploy.sh              git pull  +  build  +  up -d
#   ops/redeploy.sh --no-pull    nur build + up -d (kein git pull)
#   ops/redeploy.sh --no-build   nur up -d (kein Rebuild)
#   ops/redeploy.sh --prune      nach dem Deploy alte Images aufräumen
#
# Konfiguration per Env (optional):
#   REHOF_USER   rootless-Ziel-User (Default: rehof-svc)
#   REHOF_DIR    Repo-Verzeichnis   (Default: Elternverzeichnis dieses Skripts)
#
set -euo pipefail

RL_USER="${REHOF_USER:-rehof-svc}"
REPO_DIR="${REHOF_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE="$REPO_DIR/docker-compose.yml"

DO_PULL=1 DO_BUILD=1 DO_PRUNE=0
for a in "$@"; do
  case "$a" in
    --no-pull)  DO_PULL=0 ;;
    --no-build) DO_BUILD=0 ;;
    --prune)    DO_PRUNE=1 ;;
    -h|--help)  sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $a" >&2; exit 2 ;;
  esac
done

[ -f "$COMPOSE" ] || { echo "FEHLER: $COMPOSE nicht gefunden." >&2; exit 1; }

# rootless-Umgebung des Ziel-Users bestimmen (UID -> Runtime-Dir/Socket).
RL_UID="$(id -u "$RL_USER" 2>/dev/null || true)"
[ -n "$RL_UID" ] || { echo "FEHLER: User '$RL_USER' existiert nicht." >&2; exit 1; }
XDG="/run/user/$RL_UID"
DH="unix://$XDG/docker.sock"

# docker im rootless-Daemon ausführen – ohne sudo, wenn wir schon dieser User sind.
if [ "$(id -un)" = "$RL_USER" ]; then
  rl() { env XDG_RUNTIME_DIR="$XDG" DOCKER_HOST="$DH" docker "$@"; }
else
  rl() { sudo -u "$RL_USER" env XDG_RUNTIME_DIR="$XDG" DOCKER_HOST="$DH" docker "$@"; }
fi

# --- Sicherheits-Riegel: sind wir WIRKLICH im rootless-Daemon? --------------
# Der rootless-Daemon hat sein DockerRootDir unter dem Home des Users
# (z.B. /home/rehof-svc/.local/share/docker) – der rootful unter /var/lib/docker.
root_dir="$(rl info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
case "$root_dir" in
  /home/"$RL_USER"/*|*/.local/share/docker) : ;;   # ok: rootless
  "")
    echo "ABBRUCH: rootless-Daemon von '$RL_USER' nicht erreichbar" >&2
    echo "         (Socket $DH). Läuft er? 'loginctl enable-linger $RL_USER'?" >&2
    exit 1 ;;
  *)
    echo "ABBRUCH: Ziel-Daemon ist NICHT rootless (DockerRootDir='$root_dir')." >&2
    echo "         Es würde ein zweiter Stack im rootful-Daemon entstehen." >&2
    exit 1 ;;
esac

echo "→ Ziel: rootless-Daemon von '$RL_USER' (DockerRootDir=$root_dir)"
cd "$REPO_DIR"

if [ "$DO_PULL" = 1 ]; then
  echo "→ git pull --ff-only …"
  git pull --ff-only
fi

up=(compose -f "$COMPOSE" up -d)
[ "$DO_BUILD" = 1 ] && up+=(--build)
echo "→ docker ${up[*]} …"
rl "${up[@]}"

if [ "$DO_PRUNE" = 1 ]; then
  echo "→ Alte, ungenutzte Images aufräumen …"
  rl image prune -f
fi

echo "→ Status:"
rl compose -f "$COMPOSE" ps
echo
echo "✓ Fertig. Health prüfen:"
echo "    curl -fsS http://10.42.42.1:8000/healthz/    # erwartet: ok"
echo "    ops/redeploy.sh   (dieses Skript) ist der EINZIGE Weg, Re:Hof zu deployen."
