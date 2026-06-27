"""DSGVO-Aufräumkommando: löscht/pseudonymisiert abgelaufene Daten.

Wird vom Scheduler (run_scheduler) täglich aufgerufen, kann aber auch manuell
laufen. Idempotent. Die Fristen stehen als RETENTION_*-Settings (per Env
überschreibbar). Rechnungs-/Zahlungsdaten (10 Jahre, §147 AO / §14b UStG)
bleiben bewusst unangetastet – siehe ADR 0043.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from booking import services as svc


class Command(BaseCommand):
    help = "Löscht/pseudonymisiert abgelaufene Daten (DSGVO-Datensparsamkeit)."

    def handle(self, *args, **opts):
        counts = svc.run_data_retention()
        total = sum(counts.values())
        if total:
            parts = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
            self.stdout.write(f"cleanup_data: {parts}")
