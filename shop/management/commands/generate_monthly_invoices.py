"""Erzeugt die monatlichen Sammelrechnungen des Hofladens.

Ohne Argumente wird der VORMONAT abgerechnet (für den Cron-Aufruf am
Monatsanfang). Mit --year/--month gezielt ein Monat.

Cron-Beispiel (am 1. jeden Monats um 02:00):
    0 2 1 * *  cd /app && python manage.py generate_monthly_invoices
"""
from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from shop.services import generate_monthly_invoices


class Command(BaseCommand):
    help = "Erzeugt monatliche Sammelrechnungen (Standard: Vormonat)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int)
        parser.add_argument("--month", type=int)

    def handle(self, *args, **opts):
        year, month = opts.get("year"), opts.get("month")
        if not (year and month):
            today = date.today()
            year = today.year - 1 if today.month == 1 else today.year
            month = 12 if today.month == 1 else today.month - 1
        invoices = generate_monthly_invoices(year, month)
        self.stdout.write(self.style.SUCCESS(
            f"{len(invoices)} Rechnung(en) für {month:02d}/{year} erzeugt."))
        for inv in invoices:
            self.stdout.write(f"  {inv.number} – {inv.member} – {inv.total_gross} €")
