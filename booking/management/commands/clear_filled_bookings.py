"""Entfernt die von `fill_bookings` angelegten Test-Buchungen wieder.

Löscht **nur** die als Testfüllung markierten Buchungen (interne Notiz
`FILL_MARKER`) – echte Buchungen bleiben unangetastet. Hartes Löschen (kein
Storno-Workflow, keine Verwirkung/Benachrichtigung): es ist reines Aufräumen von
Testdaten.

    python manage.py clear_filled_bookings              # alle Testfüllungen
    python manage.py clear_filled_bookings --year 2026  # nur eines Jahres
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from booking.models import Allocation
from booking.management.commands.fill_bookings import FILL_MARKER


class Command(BaseCommand):
    help = ("Entfernt die von fill_bookings angelegten Test-Buchungen "
            "(interne Notiz-Markierung).")

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None,
                            help="Nur Buchungen mit Anreise in diesem Jahr löschen.")

    def handle(self, *args, **opts):
        qs = Allocation.objects.filter(internal_note=FILL_MARKER)
        if opts["year"]:
            qs = qs.filter(start__year=opts["year"])
        n = qs.count()
        if not n:
            self.stdout.write("Keine Test-Buchungen gefunden – nichts zu tun.")
            return
        qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f"{n} Test-Buchung(en) entfernt."))
