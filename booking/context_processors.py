"""Stellt die Rollen-Flags `is_admin`/`is_verwaltung` allen Templates bereit
(für Navigation und bedingte Anzeige)."""
from .permissions import is_admin, is_verwaltung


def roles(request):
    user = getattr(request, "user", None)
    return {"is_admin": is_admin(user), "is_verwaltung": is_verwaltung(user)}
