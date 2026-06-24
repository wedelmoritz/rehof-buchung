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
    """Verwaltung = Gruppe „Verwaltung" ODER Admin ODER (Bestandsschutz) Staff.
    Berechtigt zum Verwaltungs-Dashboard – ändert aber Buchungen/Losung nicht."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name=VERWALTUNG_GROUP).exists()


def ensure_verwaltung_group():
    """Legt die Gruppe „Verwaltung" an, falls sie fehlt (idempotent)."""
    from django.contrib.auth.models import Group
    grp, _ = Group.objects.get_or_create(name=VERWALTUNG_GROUP)
    return grp
