"""Signal-Handler der Buchungs-App."""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Member, Notification


@receiver(post_save, sender=Notification)
def notification_web_push(sender, instance: Notification, created: bool, **kwargs):
    """Jede neue In-App-Benachrichtigung wird – sofern Web-Push konfiguriert ist
    und das Mitglied ein Gerät abonniert hat – zusätzlich als Push zugestellt.
    Erst NACH dem Commit (kein Netz-Call in offener Transaktion); best-effort."""
    if not created:
        return

    def _deliver():
        from .services import send_web_push
        send_web_push(
            instance.member, "Re:Hof",
            instance.message, instance.url or "/")

    transaction.on_commit(_deliver)


@receiver(post_save, sender=Member)
def member_freischaltung_email(sender, instance: Member, created: bool, **kwargs):
    """Wird ein Mitglieds-Profil angelegt (= Verwaltung schaltet den Benutzer
    frei), bekommt die Person eine E-Mail – sofern eine Adresse hinterlegt ist."""
    if not created:
        return
    # Hat das Konto noch kein Passwort (frisch im Backend angelegt), bekommt die
    # Person ohnehin die „Passwort setzen"-Einladung – dann hier keine zweite,
    # verwirrende „du kannst jetzt buchen"-Mail (sie kann sich noch gar nicht
    # anmelden). Sie folgt automatisch, sobald das Passwort steht, nicht.
    user = getattr(instance, "user", None)
    if user is not None and not user.has_usable_password():
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
