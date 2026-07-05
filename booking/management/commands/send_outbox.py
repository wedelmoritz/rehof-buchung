"""Versendet die in der Outbox wartenden E-Mails.

Wird vom Scheduler (run_scheduler) regelmäßig aufgerufen; kann aber auch manuell
laufen. Fehlgeschlagene Mails werden bis `max-attempts` erneut versucht (beim
nächsten Lauf); der letzte Fehler wird festgehalten.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import OutboxEmail


class Command(BaseCommand):
    help = "Versendet ausstehende E-Mails aus der Outbox."

    def add_arguments(self, parser):
        parser.add_argument("--max-attempts", type=int, default=5)
        parser.add_argument("--batch", type=int, default=200)

    def handle(self, *args, **opts):
        pending = (OutboxEmail.objects
                   .filter(sent_at__isnull=True, attempts__lt=opts["max_attempts"])
                   .order_by("created_at")[:opts["batch"]])
        sent = failed = 0
        for em in pending:
            try:
                msg = EmailMultiAlternatives(
                    em.subject, em.body, settings.DEFAULT_FROM_EMAIL, [em.to_email],
                    reply_to=[em.reply_to] if em.reply_to else None)
                if em.html_body:
                    msg.attach_alternative(em.html_body, "text/html")
                if em.attachment:
                    msg.attach(em.attachment_name or "anhang",
                               bytes(em.attachment),
                               em.attachment_mime or "application/octet-stream")
                msg.send()
            except Exception as exc:  # noqa: BLE001 – Versand soll robust sein
                em.attempts += 1
                em.last_error = str(exc)[:300]
                em.save(update_fields=["attempts", "last_error"])
                failed += 1
            else:
                em.sent_at = timezone.now()
                em.last_error = ""
                em.save(update_fields=["sent_at", "last_error"])
                sent += 1
        if sent or failed:
            self.stdout.write(f"send_outbox: {sent} gesendet, {failed} Fehler.")
