"""Prüft die Verifizierbarkeit einer Losung (Commit-Reveal, ADR 0062).

    python manage.py verify_lottery <period_id>
    python manage.py verify_lottery --all

Bestätigt für jede gelaufene Losung:
  1. die veröffentlichte Seed-Prüfsumme passt zum offengelegten Seed (der Seed
     stand also schon vor der Ziehung fest), und
  2. ein erneuter Lauf mit Seed + Eingaben reproduziert exakt die Zuteilungen.

Exit-Code 0 = alles verifiziert, 1 = mindestens eine Abweichung.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from booking.models import BookingPeriod
from booking.services import verify_period_lottery


class Command(BaseCommand):
    help = "Verifiziert Losungen (Seed-Prüfsumme + reproduzierbares Ergebnis)."

    def add_arguments(self, parser):
        parser.add_argument("period_id", nargs="?", type=int,
                            help="ID der Buchungsperiode.")
        parser.add_argument("--all", action="store_true",
                            help="Alle Perioden mit gelaufener Losung prüfen.")

    def handle(self, *args, **opts):
        if opts["all"]:
            periods = list(BookingPeriod.objects.filter(runs__isnull=False).distinct())
        elif opts["period_id"]:
            periods = list(BookingPeriod.objects.filter(id=opts["period_id"]))
            if not periods:
                raise CommandError(f"Keine Periode mit ID {opts['period_id']}.")
        else:
            raise CommandError("Bitte eine period_id angeben oder --all.")

        all_ok = True
        for p in periods:
            r = verify_period_lottery(p)
            if not r.get("ok"):
                all_ok = False
                self.stdout.write(self.style.ERROR(
                    f"✗ {p}: {r.get('reason', '')}"
                    f" Prüfsumme={r.get('commit_ok')} Reproduktion={r.get('replay_ok')}"
                    f" ({r.get('n_replay')} vs. {r.get('n_stored')} Zuteilungen)"))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"✓ {p}: Seed-Prüfsumme passt, Ergebnis reproduzierbar "
                    f"({r['n_stored']} Zuteilungen, Seed {r['seed']})."))
                if not r.get("commit_timely"):
                    self.stdout.write(self.style.WARNING(
                        "  ⚠ Hinweis: Die Prüfsumme wurde erst spät (nach Wunschschluss) "
                        "veröffentlicht – die Vorab-Garantie ist dann schwächer."))
        if not all_ok:
            raise CommandError("Mindestens eine Losung ließ sich nicht verifizieren.")
