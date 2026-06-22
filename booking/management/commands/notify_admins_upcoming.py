"""Schickt der Verwaltung die Buchungen des Folgemonats (anstehende Buchungen +
Reinigung). Vom Scheduler täglich aufgerufen; sendet idempotent nur am in den
Betriebs-Einstellungen gewählten Tag, einmal pro Monat. Mit --force sofort.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from booking.services import notify_admins_upcoming


class Command(BaseCommand):
    help = "Verwaltungs-Mail mit den Buchungen des Folgemonats."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Sofort senden, unabhängig vom eingestellten Tag.")

    def handle(self, *args, **opts):
        n = notify_admins_upcoming(force=opts["force"])
        if n:
            self.stdout.write(f"notify_admins_upcoming: an {n} Empfänger gesendet.")
