"""Schaltet Buchungsperioden automatisch weiter und führt fällige Losungen aus.

Für jede nicht pausierte Periode (`status` != „Unterbrochen“) wird:
  1. die Auslosung durchgeführt, sobald der Termin `draw_at` erreicht ist und
     noch keine lief (reproduzierbar über den Seed der Periode bzw. einen neu
     gezogenen Zufalls-Seed);
  2. der Status anhand der eingestellten Termine VORWÄRTS geschaltet
     (`BookingPeriod.compute_status`) – nie zurück, damit manuelle Stände nicht
     überschrieben werden.

Per Cron z.B. alle 15 Minuten aufrufen:
    */15 * * * *  cd /app && python manage.py run_due_lotteries

(Im Docker-Setup z.B. über einen kleinen Cron-Container oder einen Scheduler.)
"""
from __future__ import annotations

import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import BookingPeriod
from booking.services import ensure_seed_commit, run_period_lottery


class Command(BaseCommand):
    help = "Schaltet Perioden weiter und führt terminierte Losungen aus."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Nur anzeigen, was passieren würde.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        dry = opts["dry_run"]
        rank = {s: i for i, s in enumerate(BookingPeriod.LIFECYCLE)}
        did_something = False

        for period in BookingPeriod.objects.exclude(status=BookingPeriod.SUSPENDED):
            # 0) Sobald die Wünsche offen sind, die Seed-Prüfsumme veröffentlichen
            # (Commit-Reveal, ADR 0062) – steht damit VOR der Ziehung fest.
            if (period.status_rank >= BookingPeriod.LIFECYCLE.index(
                    BookingPeriod.WISHES_OPEN) and not period.seed_commit):
                if dry:
                    self.stdout.write(f"[dry-run] Seed-Commit fällig: {period}")
                else:
                    ensure_seed_commit(period)
                    did_something = True

            # 1) Fällige Losung ausführen (genau einmal).
            if (period.draw_at and now >= period.draw_at
                    and not period.runs.exists()):
                did_something = True
                if dry:
                    self.stdout.write(
                        f"[dry-run] Losung fällig: {period} (draw_at {period.draw_at})")
                else:
                    seed = period.seed if period.seed is not None \
                        else random.randrange(1, 2**31)
                    run = run_period_lottery(period, seed=seed)
                    period.refresh_from_db()
                    self.stdout.write(self.style.SUCCESS(
                        f"Losung durchgeführt: {period} – {run.summary}"))

            # 2) Status anhand der Termine vorwärts schalten (nie zurück).
            # Aus dem Prüfzustand führt KEIN automatischer Weg – die Auslosung
            # muss erst manuell bestätigt (oder zurückgenommen) werden.
            if period.status == BookingPeriod.LOTTERY_REVIEW:
                continue
            desired = period.compute_status(now)
            if rank.get(desired, -1) > rank.get(period.status, -1):
                did_something = True
                if dry:
                    self.stdout.write(
                        f"[dry-run] {period}: {period.status} → {desired}")
                else:
                    period.status = desired
                    period.save(update_fields=["status"])
                    self.stdout.write(self.style.SUCCESS(
                        f"{period}: Status → {period.get_status_display()}"))

        if not did_something:
            self.stdout.write("Nichts zu tun.")
