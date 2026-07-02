"""Erinnert zweistufig an noch nicht eingereichte Wünsche vor der Auslosung (ADR 0080).

Vom `run_scheduler` täglich aufgerufen; idempotent (jede Stufe genau einmal je
Periode). Manuell: `python manage.py send_wish_reminders [--force]`.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from booking import services as svc


class Command(BaseCommand):
    help = "Zweistufige Erinnerung an noch nicht eingereichte Wünsche vor der Losung."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Erste Stufe sofort auslösen (Zeitfenster ignorieren), sofern "
                 "noch nicht versendet – für manuellen Anstoß/Tests.")

    def handle(self, *args, **opts):
        n = svc.send_wish_reminders(force=opts["force"])
        self.stdout.write(f"[wish_reminders] {n} Erinnerung(en) versendet.")
