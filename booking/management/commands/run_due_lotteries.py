"""Führt fällige (terminierte) Losungen automatisch aus.

Für jede Buchungsperiode mit gesetztem `draw_at` in der Vergangenheit und Status
„Für Wunsch-Einträge freigegeben“ oder „Zur Auslosung freigegeben“ wird die
Losung durchgeführt (reproduzierbar über den Seed der Periode bzw. einen neu
gezogenen Zufalls-Seed).

Per Cron z.B. alle 15 Minuten aufrufen:
    */15 * * * *  cd /app && python manage.py run_due_lotteries

(Im Docker-Setup z.B. über einen kleinen Cron-Container oder einen Scheduler.)
"""
from __future__ import annotations

import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import BookingPeriod
from booking.services import run_period_lottery


class Command(BaseCommand):
    help = "Führt terminierte Losungen aus (draw_at erreicht)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Nur anzeigen, welche Perioden fällig wären.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        due = BookingPeriod.objects.filter(
            draw_at__isnull=False, draw_at__lte=now,
            status__in=[BookingPeriod.WISHES_OPEN, BookingPeriod.LOTTERY_READY],
        )
        if not due:
            self.stdout.write("Keine fälligen Losungen.")
            return
        for period in due:
            if opts["dry_run"]:
                self.stdout.write(f"[dry-run] fällig: {period} (draw_at {period.draw_at})")
                continue
            seed = period.seed if period.seed is not None else random.randrange(1, 2**31)
            run = run_period_lottery(period, seed=seed)
            self.stdout.write(self.style.SUCCESS(
                f"Losung durchgeführt: {period} – {run.summary}"
            ))
