"""Rollen-Helfer – klare Trennung der beiden Verwaltungsrollen.

* **Admin** = Django-Superuser: voller Zugriff auf das Backend (`/admin/`),
  darf Buchungen ändern und Losungen starten.
* **Verwaltung** = Mitglied der Gruppe „Verwaltung" (ODER Admin): sieht das
  operative Dashboard unter `/verwaltung/` (Buchungen/Losung nur lesend) und
  pflegt dort den Hofladen-Katalog. **Kein** Django-Backend.

Die Zuordnung ist bewusst einfach: ein Häkchen „Verwaltung"-Gruppe genügt –
es braucht keine einzelnen Django-Rechte.
"""
from __future__ import annotations

VERWALTUNG_GROUP = "Verwaltung"


def is_admin(user) -> bool:
    """Admin = Superuser (volles Backend, darf alles ändern)."""
    return bool(getattr(user, "is_authenticated", False) and user.is_superuser)


def is_verwaltung(user) -> bool:
    """Verwaltung = **irgendeine** native Verwaltungsrolle ODER Admin (Superuser)
    ODER (Übergang) die Legacy-Rolle „Verwaltung" (ADR 0100). Reines **Bereichs-Gate**
    fürs Dashboard; welche Unterseite jemand sehen/aufrufen darf, entscheidet die
    Capability der Rolle (`booking.authz`, Durchsetzung per `requires_capability`).
    Bewusst NICHT an `is_staff` gekoppelt."""
    from . import authz
    return authz.is_any_verwaltung(user)


def ensure_verwaltung_group():
    """Legt die Gruppe „Verwaltung" an, falls sie fehlt (idempotent)."""
    from django.contrib.auth.models import Group
    grp, _ = Group.objects.get_or_create(name=VERWALTUNG_GROUP)
    return grp
