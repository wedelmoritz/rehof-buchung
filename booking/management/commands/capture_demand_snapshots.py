"""Hält die Nachfrage-Snapshots der Entzerrungsphase fest (ADR 0101).

Für jede nicht pausierte Periode mit Losdatum wird – je Periode genau einmal – der
„vor"-Stand (ab `review_open`) und die eingefrorene Anzeige (ab `freeze_start`, 24 h
vor der Losung) gespeichert. Idempotent; vom `run_scheduler` je Lauf aufgerufen
(bewusst im kurzen Intervall, damit der Freeze-Stand pünktlich sitzt).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import BookingPeriod
from booking.services import capture_wish_snapshots


class Command(BaseCommand):
    help = "Speichert Nachfrage-Snapshots der Entzerrungsphase (vor/eingefroren)."

    def handle(self, *args, **opts):
        now = timezone.now()
        n = 0
        for period in (BookingPeriod.objects
                       .exclude(status=BookingPeriod.SUSPENDED)
                       .filter(draw_at__isnull=False)):
            if capture_wish_snapshots(period, now):
                n += 1
                self.stdout.write(self.style.SUCCESS(
                    f"Nachfrage-Snapshot aktualisiert: {period}"))
        if not n:
            self.stdout.write("Keine neuen Snapshots.")
