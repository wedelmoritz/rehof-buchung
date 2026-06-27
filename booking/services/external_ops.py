"""Service-Layer (external_ops): Externe Gäste: Angebot/Verfügbarkeit, Buchung/Storno, Magic-Link-Zugriff.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from .. import validation as V
from ..external import external_allowed, cancellation_refund
from ..models import (
    ExternalBooking, ExternalConfig, Guest, Quarter,
)
from .notify import absolute_url, queue_email
from .slots import _in_season_range, external_min_nights, quarter_is_free
from .booking_ops import notify_waitlist_if_free

__all__ = [
    'external_quote', 'external_available_quarters',
    'create_external_booking', 'external_cancellation_preview',
    'cancel_external_booking', 'external_booking_by_token',
    'guest_bookings_by_token', 'cancel_external_booking_by_token',
]

def external_quote(quarter: Quarter, start: date, end: date, cfg=None) -> dict:
    """Preis-Aufschlüsselung für eine externe Buchung (brutto) + Rechnungs-Positionen.

    Die Übernachtungen werden Nacht für Nacht zum jeweils gültigen (ggf.
    saisonalen) Quartier-Preis berechnet (siehe `QuarterPrice`). Gleiche
    Nachtpreise werden zu einer Rechnungs-Position zusammengefasst."""
    from decimal import Decimal
    cfg = cfg or ExternalConfig.get_solo()
    nights = (end - start).days
    # Nacht-für-Nacht den (saisonalen) Preis bestimmen und nach Preis bündeln.
    by_price: dict = defaultdict(int)
    d = start
    while d < end:
        by_price[quarter.price_for_night(d)] += 1
        d += timedelta(days=1)
    stay = sum((p * n for p, n in by_price.items()), Decimal("0"))
    cleaning = cfg.cleaning_fee or 0
    specs: list[dict] = []
    for price in sorted(by_price, reverse=True):
        n = by_price[price]
        specs.append({"name": f"Übernachtung – {quarter.name}", "quantity": n,
                      "unit": "Nacht", "unit_price": price, "vat_rate": cfg.stay_vat})
    if cleaning > 0:
        specs.append({"name": "Endreinigung", "quantity": 1, "unit": "Pauschale",
                      "unit_price": cleaning, "vat_rate": cfg.cleaning_vat,
                      "service_date": end})
    total = stay + cleaning
    seasonal = len(by_price) > 1
    return {"nights": nights, "stay_gross": stay, "cleaning_gross": cleaning,
            "total_gross": total, "line_specs": specs, "seasonal_price": seasonal,
            "deposit_gross": cfg.deposit_for(total),
            "cancellation_text": cfg.cancellation_text}


def external_available_quarters(start: date, end: date) -> list[tuple]:
    """Für Externe buchbare, freie Quartiere im Zeitraum + Preis-Angebot.
    Leere Liste, wenn Externe gesperrt sind oder die Regeln nicht passen."""
    cfg = ExternalConfig.get_solo()
    if not cfg.active or end <= start:
        return []
    ok, _reason = external_allowed(
        start, end, today=date.today(), allowed_weekdays=cfg.allowed_weekday_set,
        min_nights=external_min_nights(start, end, cfg), max_nights=cfg.max_nights,
        lead_days=cfg.lead_days, horizon_days=cfg.horizon_days)
    if not ok:
        return []
    out = []
    for q in Quarter.objects.filter(
            active=True, external_bookable=True).order_by("name"):
        if not _in_season_range(q, start, end):
            continue
        if not quarter_is_free(q, start, end):
            continue
        out.append((q, external_quote(q, start, end, cfg)))
    return out


@transaction.atomic
def create_external_booking(quarter: Quarter, start: date, end: date, persons: int,
                            *, name: str, email: str, street: str = "",
                            zip_code: str = "", city: str = ""):
    """Legt eine externe Buchung an: Gast + ExternalBooking (blockiert) + Rechnung
    (wie Hofladen, Zahlung per Überweisung). Gibt (booking, None) oder (None, Fehler)."""
    cfg = ExternalConfig.get_solo()
    if not cfg.active:
        return None, "Buchungen für externe Gäste sind derzeit nicht möglich."
    if not (quarter.active and quarter.external_bookable):
        return None, "Dieses Quartier ist für externe Gäste nicht buchbar."
    if end <= start:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    ok, reason = external_allowed(
        start, end, today=date.today(), allowed_weekdays=cfg.allowed_weekday_set,
        min_nights=external_min_nights(start, end, cfg), max_nights=cfg.max_nights,
        lead_days=cfg.lead_days, horizon_days=cfg.horizon_days)
    if not ok:
        return None, reason
    if not _in_season_range(quarter, start, end):
        return None, f"{quarter.name} ist in diesem Zeitraum nicht buchbar."
    if persons and persons > quarter.max_occupancy:
        return None, f"{quarter.name}: maximal {quarter.max_occupancy} Personen."
    if not quarter_is_free(quarter, start, end):
        return None, f"{quarter.name} ist in diesem Zeitraum bereits belegt."
    # Plausibilität der Gastdaten (Name/E-Mail Pflicht; Adresse, wenn angegeben).
    err = (V.name_error(name, field="Name", max_len=160)
           or V.email_error(email, required=True)
           or V.street_error(street, required=False)
           or V.plz_error(zip_code, required=False)
           or V.city_error(city, required=False))
    if err:
        return None, err

    q = external_quote(quarter, start, end, cfg)
    guest = Guest.objects.create(
        name=name.strip(), email=email.strip(), street=street.strip(),
        zip_code=zip_code.strip(), city=city.strip())
    booking = ExternalBooking.objects.create(
        guest=guest, quarter=quarter, start=start, end=end,
        persons=max(1, persons or 1), status=ExternalBooking.CONFIRMED,
        total_gross=q["total_gross"], confirmed_at=timezone.now())

    # Rechnung wie im Hofladen – Zahlung per Überweisung, Abgleich via reconcile.
    from shop.services import create_invoice_for_guest
    inv = create_invoice_for_guest(guest, q["line_specs"],
                                   due_days=cfg.payment_term_days)
    booking.invoice = inv
    booking.save(update_fields=["invoice"])

    # Bestätigung + Zahlungsinfo per E-Mail (Gast hat kein Konto).
    bic = f" · BIC: {inv.bic}" if inv.bic else ""
    manage_url = absolute_url(reverse("external_manage", args=[guest.token]))
    deposit = q.get("deposit_gross") or 0
    deposit_line = (f"Anzahlung: {deposit} € (bitte zuerst überweisen).\n"
                    if deposit else "")
    queue_email(
        guest.email, f"Buchungsbestätigung – {quarter.name}",
        f"Hallo {guest.name},\n\nvielen Dank für deine Buchung:\n"
        f"{quarter.name}, {start:%d.%m.%Y} – {end:%d.%m.%Y} "
        f"({q['nights']} Nächte, {booking.persons} Pers.)\n\n"
        f"Rechnung {inv.number} über {inv.total_gross} €.\n"
        f"{deposit_line}"
        f"Bitte mit der Rechnungsnummer als Verwendungszweck überweisen auf:\n"
        f"IBAN: {inv.iban or '—'}{bic}\n"
        f"Zahlbar bis {inv.due_date:%d.%m.%Y}.\n\n"
        f"Stornobedingungen: {q.get('cancellation_text', '')}\n\n"
        f"Buchung ansehen/stornieren: {manage_url}\n\n"
        f"Viele Grüße\nRe:Hof",
        member=None)
    return booking, None


def external_cancellation_preview(booking: ExternalBooking, cfg=None) -> dict:
    """Erstattungs-Vorschau für ein Storno (ohne zu stornieren)."""
    cfg = cfg or ExternalConfig.get_solo()
    refund, pct, label = cancellation_refund(
        booking.total_gross, arrival=booking.start, today=date.today(),
        free_days=cfg.free_cancel_days, partial_days=cfg.partial_cancel_days,
        partial_percent=cfg.partial_refund_percent)
    return {"refund": refund, "percent": pct, "label": label,
            "kept": booking.total_gross - refund}


def cancel_external_booking(booking: ExternalBooking) -> dict:
    """Storniert eine externe Buchung (gibt den Slot frei) und liefert die
    Erstattungs-Aufschlüsselung gemäß Stornobedingungen zurück."""
    preview = external_cancellation_preview(booking)
    booking.status = ExternalBooking.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    notify_waitlist_if_free(booking.quarter, booking.start, booking.end)
    return preview


def external_booking_by_token(token, booking_id) -> ExternalBooking | None:
    """Holt eine Buchung über den Gast-Magic-Link-Token (Selbstverwaltung)."""
    return ExternalBooking.objects.select_related("guest", "quarter", "invoice") \
        .filter(id=booking_id, guest__token=token).first()


def guest_bookings_by_token(token) -> list[ExternalBooking]:
    """Alle Buchungen eines Gastes zum Magic-Link-Token (neueste zuerst)."""
    return list(ExternalBooking.objects.select_related("quarter", "invoice")
                .filter(guest__token=token).order_by("-start"))


def cancel_external_booking_by_token(token, booking_id) -> tuple[dict | None, str | None]:
    """Storniert eine Gast-Buchung über den Magic-Link. Nur zukünftige Buchungen,
    die noch nicht storniert sind."""
    booking = external_booking_by_token(token, booking_id)
    if not booking:
        return None, "Buchung nicht gefunden."
    if booking.status == ExternalBooking.CANCELLED:
        return None, "Diese Buchung ist bereits storniert."
    if booking.start <= date.today():
        return None, "Vergangene oder laufende Buchungen können nicht storniert werden."
    return cancel_external_booking(booking), None
