"""Signal-Handler der Buchungs-App."""
from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Member


@receiver(post_save, sender=Member)
def member_freischaltung_email(sender, instance: Member, created: bool, **kwargs):
    """Wird ein Mitglieds-Profil angelegt (= Verwaltung schaltet den Benutzer
    frei), bekommt die Person eine E-Mail – sofern eine Adresse hinterlegt ist."""
    if not created:
        return
    # Lazy-Import: services importiert models, daher hier erst zur Laufzeit.
    from .services import email_member, absolute_url
    email_member(
        instance,
        "Re:Hof: Konto freigeschaltet",
        f"Hallo {instance.display_name},\n\n"
        f"dein Konto wurde freigeschaltet – du kannst jetzt Quartiere buchen, "
        f"Wünsche fürs Losverfahren eintragen und den Hofladen nutzen.\n\n"
        f"{absolute_url('/')}\n\nViele Grüße\nRe:Hof")
