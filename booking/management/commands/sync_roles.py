"""Legt die Verwaltungs-Rollen (Gruppen) idempotent an und weist die Capabilities
zu (ADR 0100). Re-runnable, reproduzierbar über alle Umgebungen – kein manuelles
Klicken im Backend.

    python manage.py sync_roles          # anlegen/abgleichen + Legacy-Mapping
    python manage.py sync_roles --no-legacy   # ohne Legacy-„Verwaltung"-Mapping

Nach Modell-/Rechte-Änderungen (neue Capability) einfach erneut ausführen.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from booking.authz import (
    ALL_PERMS, LEGACY_MAPS_TO, LEGACY_ROLE, ROLES, effective_role_perms,
)
from booking.models import VerwaltungAccess


class Command(BaseCommand):
    help = ("Verwaltungs-Rollen (Gruppen) + Capabilities idempotent anlegen/"
            "abgleichen (ADR 0100).")

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-legacy", action="store_true",
            help="Die bestehende Rolle „Verwaltung“ NICHT auf die nativen Rollen "
                 "abbilden.")

    def handle(self, *args, **opts):
        verbose = int(opts.get("verbosity", 1)) >= 2
        ct = ContentType.objects.get_for_model(VerwaltungAccess)
        perm_by_code = {p.codename: p
                        for p in Permission.objects.filter(content_type=ct)}
        # Sicherheitsnetz: fehlende Permissions anlegen (falls post_migrate sie noch
        # nicht erzeugt hat) – Meta.permissions von VerwaltungAccess ist die Quelle.
        labels = dict(VerwaltungAccess._meta.permissions)
        for code in ALL_PERMS:
            if code not in perm_by_code:
                perm_by_code[code] = Permission.objects.create(
                    content_type=ct, codename=code,
                    name=labels.get(code, code)[:255])

        # Rollen-Gruppen anlegen + Rechte exakt setzen (inkl. Superset-Vererbung).
        for role in ROLES:
            grp, _ = Group.objects.get_or_create(name=role)
            want = {perm_by_code[c] for c in effective_role_perms(role)}
            grp.permissions.set(want)     # idempotent: setzt genau diese Rechte
            if verbose:
                self.stdout.write(f"  Rolle „{role}“: {len(want)} Rechte")

        # Legacy-„Verwaltung" auf die erhaltenden Basis-Rollen abbilden.
        n_users = 0
        if not opts["no_legacy"]:
            legacy = Group.objects.filter(name=LEGACY_ROLE).first()
            if legacy:
                targets = [Group.objects.get(name=r) for r in LEGACY_MAPS_TO]
                for user in legacy.user_set.all():
                    for g in targets:
                        g.user_set.add(user)
                    n_users += 1

        self.stdout.write(self.style.SUCCESS(
            f"{len(ROLES)} Rollen abgeglichen."
            + (f" Legacy-„Verwaltung“: {n_users} Nutzer auf "
               f"{len(LEGACY_MAPS_TO)} Basis-Rollen abgebildet."
               if n_users else "")))
