"""Service-Layer (retention): DSGVO: automatische Aufbewahrung/Löschung und Anonymisierung.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from datetime import date, timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from ..models import (
    Allocation, NightTransfer, Notification, OutboxEmail, SwapRequest,
    WaitlistEntry, Wish,
)

__all__ = [
    'run_data_retention', 'anonymize_member',
]

def run_data_retention(now=None) -> dict:
    """Löscht/pseudonymisiert abgelaufene Daten anhand der RETENTION_*-Fristen.
    Idempotent (mehrfach aufrufbar). Gibt je Kategorie die Anzahl der
    betroffenen Datensätze zurück."""
    from django.conf import settings
    from django.contrib.sessions.models import Session
    from shop.models import BankImport, BankTransaction
    from ..models import Beds24Import

    now = now or timezone.now()
    counts: dict[str, int] = {}

    def cutoff(days: int):
        return now - timedelta(days=days)

    # B1: versendete E-Mails inkl. DB-Anhang (das PDF ist nur die Versand-Kopie;
    #     das Rechnungsoriginal bleibt über die Invoice erhalten/on-demand).
    n, _ = OutboxEmail.objects.filter(
        sent_at__isnull=False,
        sent_at__lt=cutoff(settings.RETENTION_OUTBOX_DAYS)).delete()
    counts["outbox_emails"] = n

    # B2: In-App-Benachrichtigungen (auch ungelesene – nach der Frist veraltet).
    n, _ = Notification.objects.filter(
        created_at__lt=cutoff(settings.RETENTION_NOTIFICATION_DAYS)).delete()
    counts["notifications"] = n

    # B3: Kontoauszug-Rohzeile leeren (strukturierte Felder = Zahlungsnachweis
    #     bleiben; `raw` ist nur die redundante Originalzeile).
    counts["bank_raw_cleared"] = BankTransaction.objects.filter(
        imported_at__lt=cutoff(settings.RETENTION_BANK_RAW_DAYS)
    ).exclude(raw="").update(raw="")

    # B4: Beds24-Migrations-Importe (einmalige Migration; die übernommenen
    #     Buchungen bleiben als Allocation erhalten – Row.allocation ist SET_NULL).
    n, _ = Beds24Import.objects.filter(
        created_at__lt=cutoff(settings.RETENTION_BEDS24_DAYS)).delete()
    counts["beds24_imports"] = n

    # B5: Kontoauszug-Import-Lauf-Metadaten (Transaktionen bleiben, batch=NULL).
    n, _ = BankImport.objects.filter(
        created_at__lt=cutoff(settings.RETENTION_BANKIMPORT_DAYS)).delete()
    counts["bank_imports"] = n

    # B6: erledigte Wechselwünsche + erfüllte Wartelisten-Einträge.
    swap_cut = cutoff(settings.RETENTION_SWAP_WAITLIST_DAYS)
    n, _ = SwapRequest.objects.filter(
        status__in=[SwapRequest.ACCEPTED, SwapRequest.DECLINED],
        created_at__lt=swap_cut).delete()
    counts["swap_requests"] = n
    n, _ = WaitlistEntry.objects.filter(
        fulfilled=True, created_at__lt=swap_cut).delete()
    counts["waitlist_entries"] = n

    # B7: Wünsche längst beendeter Perioden.
    max_year = now.year - settings.RETENTION_WISH_YEARS
    n, _ = Wish.objects.filter(period__target_year__lte=max_year).delete()
    counts["wishes"] = n

    # C1: abgelaufene Sessions (entspricht `clearsessions`).
    n, _ = Session.objects.filter(expire_date__lt=now).delete()
    counts["sessions"] = n

    # C2: alte Brute-Force-Fehlversuche (django-axes).
    try:
        from axes.models import AccessAttempt
        n, _ = AccessAttempt.objects.filter(
            attempt_time__lt=cutoff(settings.RETENTION_AXES_DAYS)).delete()
        counts["axes_attempts"] = n
    except Exception:  # axes nicht installiert/migriert – überspringen
        counts["axes_attempts"] = 0

    return counts


@transaction.atomic
def anonymize_member(member) -> None:
    """Recht auf Löschung (Art. 17 DSGVO): personenbezogene Daten eines Mitglieds
    entfernen, OHNE die gesetzlich aufzubewahrenden Rechnungen anzutasten. Die
    Rechnungs-Snapshots (Name/Anschrift/IBAN) liegen auf der `Invoice` selbst und
    bleiben für die 10-Jahres-Frist erhalten; gelöscht werden nur die Profil-PII
    und betrieblich kurzlebige Daten. Das Login-Konto wird deaktiviert."""
    user = member.user

    # Betrieblich kurzlebige, personenbezogene Daten des Mitglieds entfernen.
    Notification.objects.filter(member=member).delete()
    Wish.objects.filter(member=member).delete()
    WaitlistEntry.objects.filter(member=member).delete()
    OutboxEmail.objects.filter(member=member).delete()
    member.push_subscriptions.all().delete()   # Geräte-Endpoints (personenbezogen)
    SwapRequest.objects.filter(
        Q(from_member=member) | Q(to_member=member)).delete()

    # Freitext-PII in erhaltenen Datensätzen leeren (Buchungen bleiben wegen
    # Leistungs-/Rechnungsbezug bestehen, aber ohne Begleit-/Notiz-Klartext).
    Allocation.objects.filter(member=member).exclude(companions="").update(companions="")
    NightTransfer.objects.filter(
        Q(from_member=member) | Q(to_member=member)
    ).exclude(note="").update(note="")

    # Profil-PII des Mitglieds leeren.
    member.legal_name = ""
    member.street = ""
    member.zip_code = ""
    member.city = ""
    member.iban = ""
    member.display_name = f"Anonymisiert #{member.id}"
    member.email_opt_in = False
    member.save()

    # Login-Konto deaktivieren und de-personalisieren (Benutzername eindeutig
    # halten, Anmeldung unmöglich machen).
    if user is not None:
        user.is_active = False
        user.first_name = ""
        user.last_name = ""
        user.email = ""
        user.username = f"geloescht_{user.id}"
        user.set_unusable_password()
        user.save()
