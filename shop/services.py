"""Geschäftslogik des Hofladens: Warenkorb (offene Positionen), monatliche
Sammelrechnung, Statuswechsel. Reines Django-ORM, serverseitige Validierung."""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from booking.models import Member
from .models import Invoice, LineItem, Product, ShopConfig


def open_items(member: Member):
    """Noch nicht abgerechnete Positionen des Mitglieds (der „Warenkorb“)."""
    return member.shop_items.filter(invoice__isnull=True).order_by("-created_at")


def open_total(member: Member) -> Decimal:
    return sum((i.gross for i in open_items(member)), Decimal(0))


@transaction.atomic
def add_item(member, product: Product, quantity, service_date=None):
    """Legt eine Position mit Preis-Snapshot an. Gibt (LineItem, None) oder
    (None, Fehlertext)."""
    try:
        qty = Decimal(str(quantity))
    except Exception:
        return None, "Ungültige Menge."
    if qty <= 0:
        return None, "Die Menge muss größer als 0 sein."
    # Mengen-Raster erzwingen: kg in 0,1-Schritten, alles andere ganzzahlig.
    step = product.quantity_step
    if qty % step != 0:
        einheit = product.get_unit_display()
        hinweis = "in 0,1-Schritten" if step == Decimal("0.1") else "in ganzen Schritten"
        return None, f"{einheit} bitte {hinweis} angeben (Vielfaches von {step})."
    if not product.active:
        return None, "Dieses Produkt ist nicht verfügbar."
    if product.needs_date and not service_date:
        return None, "Für diese Dienstleistung bitte ein Datum angeben."
    item = LineItem.objects.create(
        member=member, product=product, name=product.name, unit=product.unit,
        unit_price=product.price, vat_rate=product.vat_rate, quantity=qty,
        service_date=service_date if product.needs_date else None,
    )
    return item, None


@transaction.atomic
def remove_item(member, item_id) -> bool:
    """Entfernt eine noch offene Position des Mitglieds."""
    deleted, _ = member.shop_items.filter(
        id=item_id, invoice__isnull=True).delete()
    return bool(deleted)


def _next_number(prefix: str, year: int, month: int) -> str:
    n = Invoice.objects.filter(year=year, month=month).count() + 1
    return f"{prefix}-{year}-{month:02d}-{n:03d}"


@transaction.atomic
def generate_monthly_invoices(year: int, month: int) -> list[Invoice]:
    """Erzeugt je Mitglied mit offenen Positionen (bis Monatsende) eine
    Sammelrechnung für (year, month). Idempotent: bereits abgerechnete
    Positionen werden nicht erneut erfasst."""
    if month == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month + 1, 1)
    boundary = timezone.make_aware(datetime.combine(next_start, time.min))
    cfg = ShopConfig.get_solo()

    member_ids = (
        LineItem.objects.filter(invoice__isnull=True, created_at__lt=boundary)
        .values_list("member_id", flat=True).distinct()
    )
    created: list[Invoice] = []
    for mid in member_ids:
        member = Member.objects.get(id=mid)
        items = list(LineItem.objects.filter(
            member_id=mid, invoice__isnull=True, created_at__lt=boundary))
        if not items:
            continue
        addr = "\n".join(p for p in [
            member.street, f"{member.zip_code} {member.city}".strip()] if p.strip())
        inv = Invoice.objects.create(
            member=member, number=_next_number(cfg.invoice_prefix, year, month),
            year=year, month=month,
            recipient_name=member.legal_name or member.display_name,
            recipient_address=addr,
            coop_name=cfg.coop_name, coop_address=cfg.coop_address,
            tax_number=cfg.tax_number, iban=cfg.iban, bic=cfg.bic,
        )
        LineItem.objects.filter(id__in=[i.id for i in items]).update(invoice=inv)
        created.append(inv)
    return created


@transaction.atomic
def mark_paid(member, invoice_id) -> tuple[bool, str | None]:
    """Mitglied meldet eine eigene Rechnung als bezahlt."""
    try:
        inv = member.invoices.get(id=invoice_id)
    except Invoice.DoesNotExist:
        return False, "Rechnung nicht gefunden."
    if inv.status != Invoice.OPEN:
        return False, "Diese Rechnung ist bereits gemeldet/bestätigt."
    inv.status = Invoice.PAID
    inv.paid_reported_at = timezone.now()
    inv.save(update_fields=["status", "paid_reported_at"])
    return True, None


@transaction.atomic
def confirm_invoice(invoice: Invoice) -> None:
    """Verwaltung bestätigt den Zahlungseingang → archiviert."""
    invoice.status = Invoice.CONFIRMED
    invoice.confirmed_at = timezone.now()
    invoice.save(update_fields=["status", "confirmed_at"])
