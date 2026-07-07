"""Entfernt die von `fill_bookings` angelegten Test-Daten wieder.

Löscht **nur** die als Testfüllung markierten Buchungen (interne Notiz
`FILL_MARKER`) **sowie** die als Testfüllung markierten Wunsch-Perioden (Name mit
`WISH_FILL_MARKER`) samt ihrer Wünsche – echte Buchungen/Losungen bleiben
unangetastet. Hartes Löschen (kein Storno-Workflow, keine Verwirkung/
Benachrichtigung): es ist reines Aufräumen von Testdaten.

    python manage.py clear_filled_bookings              # alle Testfüllungen
    python manage.py clear_filled_bookings --year 2026  # nur eines Jahres
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from booking.models import Allocation, BookingPeriod, Wish
from booking.management.commands.fill_bookings import FILL_MARKER, WISH_FILL_MARKER


class Command(BaseCommand):
    help = ("Entfernt die von fill_bookings angelegten Test-Buchungen und "
            "-Wunsch-Perioden (Markierungen).")

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None,
                            help="Nur Buchungen mit Anreise / Wunsch-Perioden dieses "
                                 "Jahres löschen.")

    def handle(self, *args, **opts):
        year = opts["year"]

        # 1) Test-Buchungen (interne Notiz-Markierung).
        qs = Allocation.objects.filter(internal_note=FILL_MARKER)
        if year:
            qs = qs.filter(start__year=year)
        n_alloc = qs.count()
        qs.delete()

        # 2) Test-Wunsch-Perioden (Name-Markierung) samt Wünschen (CASCADE).
        pqs = BookingPeriod.objects.filter(name__contains=WISH_FILL_MARKER)
        if year:
            pqs = pqs.filter(target_year=year)
        n_wish = Wish.objects.filter(period__in=pqs).count()
        n_period = pqs.count()
        pqs.delete()

        if not (n_alloc or n_period):
            self.stdout.write("Keine Test-Daten gefunden – nichts zu tun.")
            return
        self.stdout.write(self.style.SUCCESS(
            f"{n_alloc} Test-Buchung(en) und {n_period} Test-Wunsch-Periode(n) "
            f"mit {n_wish} Wunsch/Wünschen entfernt."))
