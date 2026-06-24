"""Online-Bezahlung (Mollie) – EIN System für Hofladen-Rechnungen UND externe
Gäste, weil beide eine `Invoice` haben.

Ohne hinterlegten Mollie-API-Key läuft alles im eingebauten **TEST-Modus**:
statt einer echten Mollie-Bezahlseite zeigen wir unsere eigene Sandbox-Seite, auf
der die Zahlung simuliert wird (bezahlt/abgebrochen) – ohne Konto, ohne Gebühren.
Sobald ein `test_…`/`live_…`-Key in den Hofladen-Einstellungen steht, wird der
echte Mollie-Dienst über dieselbe Naht angesprochen (`shop/mollie_api.py`).
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Invoice, Payment, ShopConfig


class PaymentUnavailable(Exception):
    """Online-Bezahlung ist aus/fehlkonfiguriert (z. B. Echtbetrieb ohne Key)."""


def payments_enabled() -> bool:
    """Aktiv UND korrekt konfiguriert: Test-Modus ODER ein Mollie-Key vorhanden.
    Verhindert die gefährliche Fehlkonfiguration „aktiv, Echtbetrieb, kein Key“
    (die früher still in den Simulationsmodus gefallen wäre)."""
    cfg = ShopConfig.get_solo()
    if not cfg.payments_active:
        return False
    return cfg.payments_test_mode or bool(cfg.mollie_api_key.strip())


def _abs(request, path: str) -> str:
    """Absolute URL (für Rückkehr-/Webhook-Adressen); ohne Request der Pfad."""
    return request.build_absolute_uri(path) if request is not None else path


def start_payment(invoice: Invoice, *, request=None, amount=None,
                  description: str = "") -> Payment:
    """Legt eine Zahlung an und liefert sie inkl. `checkout_url`. Im Test-Modus
    zeigt die checkout_url auf unsere Sandbox-Seite, sonst auf Mollie."""
    cfg = ShopConfig.get_solo()
    amt = Decimal(amount) if amount is not None else invoice.total_gross
    desc = (description or f"Re:Hof Rechnung {invoice.number}")[:140]
    # Sandbox NUR im expliziten Test-Modus – NICHT als stiller Fallback bei
    # fehlendem Key (sonst würden Rechnungen ohne Zahlung „bezahlt“).
    sandbox = cfg.payments_test_mode
    if not sandbox and not cfg.mollie_api_key.strip():
        raise PaymentUnavailable(
            "Echtbetrieb ohne Mollie-Key: Online-Bezahlung nicht möglich.")
    pay = Payment.objects.create(
        invoice=invoice, amount=amt, description=desc,
        is_sandbox=sandbox, provider="mollie")
    if sandbox:
        pay.checkout_url = _abs(request, reverse("payment_sandbox", args=[pay.token]))
    else:
        from . import mollie_api  # lazy – nur wenn echt bezahlt wird
        provider_id, url = mollie_api.create_payment(
            api_key=cfg.mollie_api_key.strip(), amount=amt, currency=pay.currency,
            description=desc,
            redirect_url=_abs(request, reverse("payment_return", args=[pay.token])),
            webhook_url=_abs(request, reverse("payment_webhook")),
            metadata={"token": str(pay.token), "invoice": invoice.number})
        pay.provider_id, pay.checkout_url = provider_id, url
    pay.save(update_fields=["checkout_url", "provider_id"])
    return pay


@transaction.atomic
def settle_payment(pay: Payment) -> None:
    """Verbucht eine erfolgreiche Zahlung: Rechnung gilt als online beglichen
    (Status „bestätigt/archiviert“, `payment_method`). Idempotent und gegen
    Doppelverbuchung gesperrt (Webhook + Rückkehrseite gleichzeitig)."""
    # Zeile sperren, damit nebenläufige Settler serialisieren (TOCTOU-Schutz).
    pay = Payment.objects.select_for_update().get(pk=pay.pk)
    if pay.status == Payment.PAID:
        return
    now = timezone.now()
    pay.status = Payment.PAID
    pay.paid_at = now
    pay.save(update_fields=["status", "paid_at"])
    inv = pay.invoice
    inv.payment_method = pay.provider
    inv.paid_online_at = now
    inv.status = Invoice.CONFIRMED
    inv.confirmed_at = now
    if not inv.paid_reported_at:
        inv.paid_reported_at = now
    inv.save(update_fields=["payment_method", "paid_online_at", "status",
                            "confirmed_at", "paid_reported_at"])
    _notify_paid(inv, pay)


def cancel_payment(pay: Payment, status: str = Payment.CANCELED) -> None:
    if pay.status == Payment.OPEN:
        pay.status = status
        pay.save(update_fields=["status"])


def _notify_paid(inv: Invoice, pay: Payment) -> None:
    """Bestätigung an Mitglied (In-App + Mail) bzw. Gast (Mail)."""
    subject = f"Zahlungseingang bestätigt – Rechnung {inv.number}"
    body = (f"Vielen Dank! Deine Online-Zahlung über {pay.amount} € "
            f"zur Rechnung {inv.number} ist eingegangen und bestätigt.")
    try:
        from booking import services as bsvc
        from booking.models import Notification
        if inv.member_id:
            Notification.objects.create(
                member=inv.member, message=f"Rechnung {inv.number} online bezahlt",
                detail=body, url=reverse("shop_invoice", args=[inv.id]))
            bsvc.email_member(inv.member, subject, body)
        elif inv.guest_id and (inv.guest.email or "").strip():
            bsvc.queue_email(inv.guest.email.strip(), subject, body)
    except Exception:  # noqa: BLE001 – Benachrichtigung darf die Zahlung nie kippen
        pass
