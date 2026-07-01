"""Schlanker Dauer-Scheduler für den `cron`-Container (ersetzt klassischen Cron).

Läuft als eigener Dienst im selben Image und führt regelmäßig aus:
  * `run_due_lotteries` – schaltet Perioden weiter und führt fällige Losungen aus
    (jedes Intervall, Standard alle 15 Min),
  * `send_outbox` – verschickt wartende E-Mails (jedes Intervall),
  * `run_monthly_invoices` – erstellt am Monatsanfang die Hofladen-Rechnungen
    (einmal pro Tag; idempotent, rechnet den Vormonat ab),
  * `send_wish_reminders` – zweistufige Erinnerung an noch nicht eingereichte
    Wünsche vor der Auslosung (einmal pro Tag; idempotent, je Stufe einmal),
  * `cleanup_data` – DSGVO-Aufräumen: löscht/pseudonymisiert abgelaufene Daten
    anhand der RETENTION_*-Fristen (einmal pro Tag; idempotent).

Beide Kommandos sind idempotent, ein Neustart schadet also nicht. Fehler eines
Laufs werden geloggt und beenden den Scheduler nicht.

Aufruf im Dauerbetrieb:        python manage.py run_scheduler
Ein einzelner Durchlauf:       python manage.py run_scheduler --once
  (praktisch, falls man stattdessen eine Host-Cron nutzen möchte)
"""
from __future__ import annotations

import os
import time
import traceback
from datetime import date

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Dauer-Scheduler: fällige Losungen + monatliche Hofladen-Rechnungen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true",
            help="Nur einen Durchlauf ausführen, dann beenden (z.B. für Host-Cron).")
        parser.add_argument(
            "--interval", type=int, default=None,
            help="Sekunden zwischen den Läufen (Standard: CRON_INTERVAL_SECONDS oder 900).")

    def handle(self, *args, **opts):
        if opts["once"]:
            self._safe("run_due_lotteries")
            self._safe("run_monthly_invoices")
            self._safe("notify_admins_upcoming")
            self._safe("send_wish_reminders")
            self._safe("cleanup_data")
            self._safe("send_outbox")
            return

        interval = opts["interval"] or int(os.environ.get("CRON_INTERVAL_SECONDS", "900"))
        self.stdout.write(f"[scheduler] Start – Intervall {interval}s.")
        last_daily: date | None = None
        while True:
            self._safe("run_due_lotteries")
            today = date.today()
            if today != last_daily:
                self._safe("run_monthly_invoices")
                self._safe("notify_admins_upcoming")  # idempotent (eigener Tag)
                self._safe("send_wish_reminders")     # Wunsch-Erinnerung (zweistufig)
                self._safe("cleanup_data")            # DSGVO-Aufräumen (täglich)
                last_daily = today
            self._safe("send_outbox")           # wartende E-Mails verschicken
            time.sleep(interval)

    def _safe(self, command: str, *cmd_args):
        try:
            call_command(command, *cmd_args)
        except Exception:
            self.stderr.write(f"[scheduler] Fehler in '{command}':\n{traceback.format_exc()}")
