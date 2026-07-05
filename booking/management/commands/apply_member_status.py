"""Vollzieht datumsgesteuerte Mitglieds-Status-Übergänge (ADR 0087).

Deaktiviert das Login von Mitgliedern, die ihr „Ausgeschieden ab"-Datum erreicht
haben. Läuft täglich über den `run_scheduler` (idempotent).
"""
from django.core.management.base import BaseCommand

from booking import services as svc


class Command(BaseCommand):
    help = "Deaktiviert Logins ausgeschiedener Mitglieder (excluded_from erreicht)."

    def handle(self, *args, **opts):
        n = svc.apply_member_status_transitions()
        self.stdout.write(f"{n} ausgeschiedene Konten deaktiviert.")
