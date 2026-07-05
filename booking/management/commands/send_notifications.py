"""Verschickt die geplanten (regelmäßigen) Verwaltungs-Benachrichtigungen.

Zentraler Einstiegspunkt des Benachrichtigungs-Frameworks (ADR 0089): jede Meldung
prüft ihre eigene Frequenz/Idempotenz über die `NotificationSetting`. Läuft täglich
über den `run_scheduler` (mehrfacher Aufruf am selben Tag ist harmlos).
"""
from django.core.management.base import BaseCommand

from booking import services as svc


class Command(BaseCommand):
    help = "Verschickt fällige geplante Benachrichtigungen (ADR 0089)."

    def handle(self, *args, **opts):
        result = svc.run_scheduled_notifications()
        parts = ", ".join(f"{k}={v}" for k, v in result.items())
        self.stdout.write(f"Geplante Benachrichtigungen: {parts}")
