"""Erzeugt die Hofladen-Sammelrechnungen für den Vormonat.

Gedacht für den Monatswechsel (Scheduler/Cron). Idempotent: bereits abgerechnete
Einkäufe werden nicht erneut erfasst. Ohne Argumente wird der VORMONAT abgerechnet
(passend zum Aufruf am Monatsanfang).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from shop.services import generate_monthly_invoices


class Command(BaseCommand):
    help = "Erzeugt die Hofladen-Sammelrechnungen (Standard: Vormonat)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, help="Jahr (Standard: Vormonat)")
        parser.add_argument("--month", type=int, help="Monat 1–12 (Standard: Vormonat)")

    def handle(self, *args, **opts):
        if opts.get("year") and opts.get("month"):
            year, month = opts["year"], opts["month"]
        else:
            last_prev = date.today().replace(day=1) - timedelta(days=1)
            year, month = last_prev.year, last_prev.month
        invoices = generate_monthly_invoices(year, month)
        self.stdout.write(self.style.SUCCESS(
            f"{len(invoices)} Rechnung(en) für {month:02d}/{year} erstellt."))
