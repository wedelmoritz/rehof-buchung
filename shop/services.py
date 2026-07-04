"""Geschäftslogik des Hofladens: Warenkorb (offene Positionen), Checkout
(bestätigter Einkauf), monatliche bzw. sofortige Sammelrechnung, Statuswechsel.
Reines Django-ORM, serverseitige Validierung."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from booking.models import Member
from .models import Invoice, LineItem, Product, Purchase, ShopConfig

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
               "Samstag", "Sonntag"]


# --------------------------------------------------------------------------- #
# Warenkorb (offene, noch nicht bestätigte Positionen)
# --------------------------------------------------------------------------- #

def open_items(member: Member):
    """Der Warenkorb: erfasste, aber noch nicht bestätigte Positionen."""
    return (member.shop_items
            .filter(purchase__isnull=True, invoice__isnull=True)
            .order_by("created_at"))


def open_total(member: Member) -> Decimal:
    return sum((i.gross for i in open_items(member)), Decimal(0))


def _check_purchasable(product: Product, quantity, service_date):
    """Gemeinsame Validierung (Menge/Raster/Verfügbarkeit). Gibt (qty, None)
    oder (None, Fehlertext)."""
    try:
        qty = Decimal(str(quantity))
    except Exception:
        return None, "Ungültige Menge."
    if qty <= 0:
        return None, "Die Menge muss größer als 0 sein."
    step = product.quantity_step
    if qty % step != 0:
        hinweis = "in 0,1-Schritten" if step == Decimal("0.1") else "in ganzen Schritten"
        return None, (f"{product.get_unit_display()} bitte {hinweis} angeben "
                      f"(Vielfaches von {step}).")
    if not product.active:
        return None, "Dieses Produkt ist nicht verfügbar."
    if product.needs_date and not service_date:
        return None, "Für diese Dienstleistung bitte ein Datum angeben."
    if service_date and not product.available_on(service_date):
        return None, (f"{product.name} ist am {WEEKDAYS_DE[service_date.weekday()]} "
                      "nicht möglich. Bitte einen anderen Termin wählen.")
    return qty, None


@transaction.atomic
def add_item(member, product: Product, quantity, service_date=None):
    """Legt eine Warenkorb-Position mit Preis-Snapshot an. Gleiche Artikel (selbes
    Produkt, Preis, MwSt, Termin) werden zusammengefasst (Menge addiert)."""
    qty, err = _check_purchasable(product, quantity, service_date)
    if err:
        return None, err
    sdate = service_date if product.needs_date else None
    existing = open_items(member).filter(
        product=product, unit_price=product.price, vat_rate=product.vat_rate,
        service_date=sdate).first()
    if existing:
        existing.quantity = existing.quantity + qty
        existing.save(update_fields=["quantity"])
        return existing, None
    item = LineItem.objects.create(
        member=member, product=product, name=product.name, unit=product.unit,
        unit_price=product.price, vat_rate=product.vat_rate, quantity=qty,
        service_date=sdate,
    )
    return item, None


@transaction.atomic
def set_cart_quantity(member, item_id, quantity) -> tuple[bool, str | None]:
    """Ändert die Menge einer Warenkorb-Position (0 oder weniger entfernt sie)."""
    item = open_items(member).filter(id=item_id).first()
    if not item:
        return False, "Position nicht gefunden."
    try:
        qty = Decimal(str(quantity))
    except Exception:
        return False, "Ungültige Menge."
    if qty <= 0:
        item.delete()
        return True, None
    step = item.product.quantity_step if item.product else Decimal("1")
    if qty % step != 0:
        return False, f"Menge muss ein Vielfaches von {step} sein."
    item.quantity = qty
    item.save(update_fields=["quantity"])
    return True, None


@transaction.atomic
def remove_item(member, item_id) -> bool:
    """Entfernt eine Position aus dem Warenkorb (nur solange unbestätigt)."""
    deleted, _ = open_items(member).filter(id=item_id).delete()
    return bool(deleted)


# --------------------------------------------------------------------------- #
# Checkout: aus dem Warenkorb wird ein bestätigter Einkauf
# --------------------------------------------------------------------------- #

@transaction.atomic
def checkout(member) -> tuple[Purchase | None, str | None]:
    """Bestätigt den Warenkorb als Einkauf. Danach ist er gesperrt und liegt in
    der Verwaltung; abgerechnet wird er monatlich oder sofort."""
    items = list(open_items(member))
    if not items:
        return None, "Dein Warenkorb ist leer."
    purchase = Purchase.objects.create(member=member)
    LineItem.objects.filter(id__in=[i.id for i in items]).update(purchase=purchase)
    return purchase, None


@transaction.atomic
def purchase_service(member, product: Product, quantity=1, service_date=None,
                     allocation=None):
    """Direkt bestätigter Einkauf einer einzelnen Dienstleistung (z.B.
    Endreinigung beim Buchen) – ohne Umweg über den Warenkorb. `allocation`
    verknüpft die Leistung mit der Buchung (Quartier + Abreisetag)."""
    qty, err = _check_purchasable(product, quantity, service_date)
    if err:
        return None, err
    purchase = Purchase.objects.create(member=member)
    item = LineItem.objects.create(
        member=member, product=product, name=product.name, unit=product.unit,
        unit_price=product.price, vat_rate=product.vat_rate, quantity=qty,
        service_date=service_date if product.needs_date else None,
        purchase=purchase, allocation=allocation,
    )
    return item, None


# --------------------------------------------------------------------------- #
# Bestätigungspflichtige Dienstleistungen (z.B. Endreinigung, ADR 0081)
# --------------------------------------------------------------------------- #

def request_service(member, product: Product, allocation, service_date):
    """Legt eine **Anfrage** für eine bestätigungspflichtige Dienstleistung an
    (statt sie sofort abzurechnen) und benachrichtigt die Betriebsleitung.
    Idempotent je Buchung+Produkt (Schutz gegen Doppelklick)."""
    from .models import ServiceRequest
    existing = ServiceRequest.objects.filter(
        allocation=allocation, product=product,
        status=ServiceRequest.REQUESTED).first()
    if existing:
        return existing, None
    sr = ServiceRequest.objects.create(
        member=member, product=product, allocation=allocation,
        service_date=service_date)
    from booking import services as bsvc
    q = allocation.quarter.name
    bsvc.email_admins(
        f"Re:Hof: Anfrage {product.name} – {q} ({service_date:%d.%m.%Y})",
        f"{member.display_name} hat beim Buchen „{product.name}“ angefragt.\n\n"
        f"Unterkunft: {q}\nTermin (Abreise): {service_date:%d.%m.%Y}\n\n"
        f"Bitte im Verwaltungs-Dashboard bestätigen oder ablehnen:\n"
        f"{bsvc.absolute_url('/verwaltung/#d-anfragen')}\n")
    return sr, None


def _notify_member_service(sr, confirmed: bool) -> None:
    from booking import services as bsvc
    from booking.models import Notification
    q = sr.allocation.quarter.name
    name = sr.product.name if sr.product else "Dienstleistung"
    if confirmed:
        msg = (f"Deine Anfrage „{name}“ für {q} "
               f"({sr.service_date:%d.%m.%Y}) wurde bestätigt.")
    else:
        extra = f" Grund: {sr.note}" if sr.note else ""
        msg = (f"Deine Anfrage „{name}“ für {q} "
               f"({sr.service_date:%d.%m.%Y}) wurde abgelehnt.{extra}")
    Notification.objects.create(member=sr.member, message=msg,
                                url="/meine-buchungen/")
    bsvc.email_member(sr.member, "Re:Hof: Rückmeldung zu deiner Anfrage", msg + "\n")


@transaction.atomic
def service_request_lock_date(sr):
    """Datum, ab dem eine ER-Entscheidung NICHT mehr geändert werden darf
    (Anreise − `er_decision_lock_days`), oder None wenn kein Lock (Frist 0). #45."""
    from booking.models import BookingPolicy
    from datetime import timedelta
    days = BookingPolicy.get_solo().er_decision_lock_days
    if not days:
        return None
    return sr.allocation.start - timedelta(days=days)


def service_request_locked(sr) -> bool:
    """Ist die ER-Entscheidung fixiert (Frist erreicht/überschritten)? #45."""
    lock = service_request_lock_date(sr)
    return lock is not None and date.today() >= lock


@transaction.atomic
def confirm_service_request(sr, by_user=None) -> tuple[bool, str | None]:
    """Betriebsleitung bestätigt eine Anfrage → es entsteht die Rechnungs-Position
    (`purchase_service`). **Revidierbar** (auch aus „abgelehnt“) bis zur Frist
    `er_decision_lock_days` vor Anreise (#45). Idempotent."""
    from .models import ServiceRequest
    if sr.product is None:
        return False, "Dienstleistung nicht mehr vorhanden."
    if sr.status == ServiceRequest.CONFIRMED and sr.line_item_id:
        return True, None  # schon bestätigt – nichts zu tun
    # Die Frist sperrt nur das REVIDIEREN einer bereits getroffenen Entscheidung –
    # eine noch offene (angefragte) darf die BL weiterhin erstmalig entscheiden (#45).
    if sr.status == ServiceRequest.REJECTED and service_request_locked(sr):
        lock = service_request_lock_date(sr)
        return False, (f"Frist abgelaufen – seit {lock:%d.%m.%Y} ist die "
                       f"Entscheidung fest (Anreise {sr.allocation.start:%d.%m.%Y}).")
    item, err = purchase_service(sr.member, sr.product, 1,
                                 service_date=sr.service_date,
                                 allocation=sr.allocation)
    if err:
        return False, err
    sr.status = ServiceRequest.CONFIRMED
    sr.line_item = item
    sr.note = ""
    sr.decided_at = timezone.now()
    sr.decided_by = by_user
    sr.save(update_fields=["status", "line_item", "note", "decided_at", "decided_by"])
    _notify_member_service(sr, confirmed=True)
    return True, None


@transaction.atomic
def reject_service_request(sr, by_user=None, reason: str = "") -> tuple[bool, str | None]:
    """Betriebsleitung lehnt ab → keine Abrechnung. **Revidierbar** (auch aus
    „bestätigt“ – die noch nicht abgerechnete Position wird dann entfernt) bis zur
    Frist `er_decision_lock_days` vor Anreise (#45). Idempotent."""
    from .models import ServiceRequest
    if sr.status == ServiceRequest.REJECTED:
        if reason and reason[:255] != sr.note:
            sr.note = reason[:255]
            sr.save(update_fields=["note"])
        return True, None  # schon abgelehnt
    # Frist sperrt nur das Revidieren einer bereits BESTÄTIGTEN Entscheidung (#45).
    if sr.status == ServiceRequest.CONFIRMED and service_request_locked(sr):
        lock = service_request_lock_date(sr)
        return False, (f"Frist abgelaufen – seit {lock:%d.%m.%Y} ist die "
                       f"Entscheidung fest (Anreise {sr.allocation.start:%d.%m.%Y}).")
    # War die Anfrage bestätigt, die zugehörige Position aber noch NICHT abgerechnet,
    # wird sie zurückgenommen. Bereits fakturiert → nicht mehr revidierbar.
    if sr.line_item_id:
        li = sr.line_item
        if li.invoice_id:
            return False, ("Die Endreinigung ist bereits abgerechnet – sie kann "
                           "nicht mehr abgelehnt werden.")
        purchase = li.purchase
        li.delete()
        if purchase and not purchase.items.exists():
            purchase.delete()
        sr.line_item = None
    sr.status = ServiceRequest.REJECTED
    sr.note = (reason or "")[:255]
    sr.decided_at = timezone.now()
    sr.decided_by = by_user
    sr.save(update_fields=["status", "line_item", "note", "decided_at", "decided_by"])
    _notify_member_service(sr, confirmed=False)
    return True, None


def pending_service_requests():
    """Offene Dienstleistungs-Anfragen fürs Verwaltungs-Dashboard (wenige Abfragen)."""
    from .models import ServiceRequest
    return (ServiceRequest.objects.filter(status=ServiceRequest.REQUESTED)
            .select_related("member", "product", "allocation",
                            "allocation__quarter")
            .order_by("service_date"))


def revisable_service_requests():
    """Bereits entschiedene ER-Anfragen, die sich noch revidieren lassen (Anreise in
    der Zukunft und Frist noch nicht erreicht) – fürs Dashboard, damit die BL einen
    Verklicker korrigieren kann (#45). Die Frist-Prüfung erfolgt final serverseitig
    in confirm/reject; hier nur die Vorauswahl fürs UI."""
    from .models import ServiceRequest
    qs = (ServiceRequest.objects
          .filter(status__in=[ServiceRequest.CONFIRMED, ServiceRequest.REJECTED],
                  allocation__start__gte=date.today())
          .select_related("member", "product", "allocation", "allocation__quarter")
          .order_by("allocation__start"))
    return [sr for sr in qs if not service_request_locked(sr)]


def unbilled_purchases(member):
    """Bestätigte, aber noch nicht abgerechnete Einkäufe."""
    return (Purchase.objects.filter(member=member, items__invoice__isnull=True)
            .distinct().prefetch_related("items"))


def unbilled_total(member: Member) -> Decimal:
    items = member.shop_items.filter(purchase__isnull=False, invoice__isnull=True)
    return sum((i.gross for i in items), Decimal(0))


# --------------------------------------------------------------------------- #
# Rechnungen (monatlich oder sofort)
# --------------------------------------------------------------------------- #

def _next_number(prefix: str, year: int, month: int) -> str:
    # Nummernvergabe GLOBAL serialisieren: die Singleton-Konfig-Zeile in der
    # laufenden Transaktion sperren, damit bei gleichzeitigem Checkout nicht
    # zweimal dieselbe Nummer entsteht (sonst bräche der unique-Constraint einen
    # der Checkouts mit IntegrityError ab). Aufrufer laufen in @transaction.atomic;
    # unter SQLite (Tests) ist select_for_update ein No-Op.
    list(ShopConfig.objects.select_for_update().all()[:1])
    n = Invoice.objects.filter(year=year, month=month).count() + 1
    return f"{prefix}-{year}-{month:02d}-{n:03d}"


@transaction.atomic
def _invoice_items(member, items, year: int, month: int) -> Invoice | None:
    """Erzeugt eine Rechnung aus konkreten (bestätigten, noch offenen) Positionen."""
    items = list(items)
    if not items:
        return None
    cfg = ShopConfig.get_solo()
    addr = "\n".join(p for p in [
        member.street, f"{member.zip_code} {member.city}".strip()] if p.strip())
    from datetime import timedelta
    due = date.today() + timedelta(days=int(cfg.payment_term_days or 14))
    inv = Invoice.objects.create(
        member=member, number=_next_number(cfg.invoice_prefix, year, month),
        year=year, month=month, due_date=due,
        recipient_name=member.legal_name or member.display_name,
        recipient_address=addr,
        coop_name=cfg.coop_name, coop_address=cfg.coop_address,
        tax_number=cfg.tax_number, iban=cfg.iban, bic=cfg.bic,
        small_business=cfg.small_business,
        tax_note=cfg.small_business_note if cfg.small_business else "",
    )
    LineItem.objects.filter(id__in=[i.id for i in items]).update(invoice=inv)
    # Benachrichtigung per E-Mail (Outbox). Lazy-Import vermeidet Zirkularität.
    from booking.services import email_member, absolute_url
    url = absolute_url(f"/hofladen/rechnung/{inv.id}/")
    # Rechnungs-PDF als Anhang (best effort – fehlt WeasyPrint, geht die Mail
    # trotzdem raus, nur ohne Anhang).
    pdf_bytes = None
    try:
        from . import pdf as pdf_mod
        if pdf_mod.weasyprint_available():
            pdf_bytes = pdf_mod.invoice_pdf_bytes(inv)
    except Exception:
        pdf_bytes = None
    email_member(
        member, f"Neue Rechnung {inv.number}",
        f"Hallo {member.display_name},\n\ndeine Hofladen-Rechnung {inv.number} "
        f"über {inv.total_gross} € ist da{' (PDF im Anhang)' if pdf_bytes else ''}.\n\n{url}\n\n"
        f"Bitte mit der Rechnungsnummer als Verwendungszweck überweisen.\n\n"
        f"Viele Grüße\nRe:Hof",
        attachment=pdf_bytes, attachment_name=f"{inv.number}.pdf",
        attachment_mime="application/pdf")
    return inv


@transaction.atomic
def generate_monthly_invoices(year: int, month: int) -> list[Invoice]:
    """Je Mitglied mit bestätigten, noch nicht abgerechneten Einkäufen (bis
    Monatsende) eine Sammelrechnung. Der Warenkorb (unbestätigt) bleibt außen vor."""
    if month == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month + 1, 1)
    boundary = timezone.make_aware(datetime.combine(next_start, time.min))

    member_ids = (
        LineItem.objects.filter(
            invoice__isnull=True, purchase__isnull=False,
            purchase__confirmed_at__lt=boundary)
        .values_list("member_id", flat=True).distinct()
    )
    created: list[Invoice] = []
    for mid in member_ids:
        member = Member.objects.get(id=mid)
        items = LineItem.objects.filter(
            member_id=mid, invoice__isnull=True, purchase__isnull=False,
            purchase__confirmed_at__lt=boundary)
        inv = _invoice_items(member, items, year, month)
        if inv:
            created.append(inv)
    return created


@transaction.atomic
def generate_invoice_now(member) -> tuple[Invoice | None, str | None]:
    """Sofort eine Rechnung über alle bestätigten, noch offenen Einkäufe."""
    today = date.today()
    items = member.shop_items.filter(invoice__isnull=True, purchase__isnull=False)
    if not items.exists():
        return None, "Keine bestätigten Einkäufe zum Abrechnen."
    inv = _invoice_items(member, items, today.year, today.month)
    return inv, None


@transaction.atomic
def create_invoice_for_guest(guest, line_specs, due_days: int = 14) -> Invoice:
    """Rechnung für einen externen Gast (kein Mitglied). `line_specs` ist eine
    Liste von Positionen: {name, quantity, unit, unit_price (brutto), vat_rate,
    service_date?}. Nutzt dieselbe Invoice-/PDF-/Abgleich-Infrastruktur wie der
    Hofladen."""
    cfg = ShopConfig.get_solo()
    today = date.today()
    inv = Invoice.objects.create(
        guest=guest, number=_next_number(cfg.invoice_prefix, today.year, today.month),
        year=today.year, month=today.month,
        due_date=today + timedelta(days=int(due_days or 14)),
        recipient_name=guest.name, recipient_address=guest.address,
        coop_name=cfg.coop_name, coop_address=cfg.coop_address,
        tax_number=cfg.tax_number, iban=cfg.iban, bic=cfg.bic,
        small_business=cfg.small_business,
        tax_note=cfg.small_business_note if cfg.small_business else "",
    )
    for s in line_specs:
        LineItem.objects.create(
            guest=guest, invoice=inv, name=s["name"],
            unit=s.get("unit", "Nacht"), unit_price=s["unit_price"],
            vat_rate=s["vat_rate"], quantity=s["quantity"],
            service_date=s.get("service_date"))
    return inv


@transaction.atomic
def mark_paid(member, invoice_id) -> tuple[bool, str | None]:
    """Mitglied meldet eine eigene Rechnung als bezahlt."""
    # Selbst-Meldung optional abschaltbar (#26/ADR 0078): dann zählt allein der
    # Kontoabgleich bzw. die Online-Zahlung. Server-seitig erzwungen (nicht nur UI).
    if not ShopConfig.get_solo().allow_self_report_paid:
        return False, ("Die Selbst-Meldung ist deaktiviert – der Zahlungseingang "
                       "wird über den Kontoabgleich bestätigt. Alternativ online bezahlen.")
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


# --------------------------------------------------------------------------- #
# Offene Posten / Zahlungserinnerung (Mahnwesen, idempotent)
# --------------------------------------------------------------------------- #

def open_invoices(qs=None):
    """Alle offenen (noch nicht als bezahlt gemeldeten) Rechnungen.
    `prefetch_related("items")` vermeidet N+1 beim Summieren von `total_gross`."""
    qs = qs if qs is not None else Invoice.objects.all()
    return (qs.filter(status=Invoice.OPEN)
            .select_related("member", "guest").prefetch_related("items"))


def overdue_invoices(qs=None):
    """Offene Rechnungen, deren Zahlungsziel überschritten ist."""
    return open_invoices(qs).filter(due_date__lt=date.today())


def reminder_due(invoice: Invoice, now=None) -> bool:
    """Darf diese Rechnung (erneut) erinnert werden? Nur offene Rechnungen und
    frühestens `ShopConfig.reminder_interval_days` nach der letzten Erinnerung –
    so lässt sich nicht versehentlich sofort ein zweites Mal mahnen (#54)."""
    if invoice.status != Invoice.OPEN:
        return False
    if not invoice.reminded_at:
        return True
    now = now or timezone.now()
    interval = max(0, ShopConfig.get_solo().reminder_interval_days)
    return (now - invoice.reminded_at).days >= interval


def send_payment_reminder(invoice: Invoice) -> bool:
    """Stellt eine Zahlungserinnerung in die Outbox. Eskaliert die Mahnstufe
    (`reminder_count`) und respektiert den Mindestabstand (#54). Gibt True zurück,
    wenn eine Erinnerung erzeugt wurde."""
    now = timezone.now()
    if not reminder_due(invoice, now):
        return False
    from booking.services import email_member, absolute_url
    stufe = invoice.reminder_count + 1
    # Empfänger-neutral: Mitglied per E-Mail-Opt-in, Gast über die Gast-Adresse.
    empf = invoice.recipient_label
    betreff = (f"Zahlungserinnerung zu Rechnung {invoice.number}" if stufe == 1
               else f"{stufe}. Zahlungserinnerung (Mahnung) zu Rechnung {invoice.number}")
    faellig = (f" (fällig am {invoice.due_date:%d.%m.%Y})"
               if invoice.due_date else "")
    url = absolute_url(f"/hofladen/rechnung/{invoice.id}/") if invoice.member_id else ""
    body = (
        f"Hallo {empf},\n\nzu Rechnung {invoice.number} über "
        f"{invoice.total_gross} €{faellig} haben wir noch keinen Zahlungseingang "
        f"verbucht. Bitte überweise mit der Rechnungsnummer als Verwendungszweck."
        + (f"\n\n{url}" if url else "")
        + "\n\nFalls sich das überschnitten hat, ignoriere diese Nachricht bitte."
        "\n\nViele Grüße\nRe:Hof")
    sent = email_member(invoice.member, betreff, body) if invoice.member_id else False
    invoice.reminded_at = now
    invoice.reminder_count = stufe
    invoice.save(update_fields=["reminded_at", "reminder_count"])
    return bool(sent) or True  # auch ohne Opt-in/Adresse als „erinnert“ markieren


def remind_overdue(qs=None) -> int:
    """Schickt allen überfälligen Rechnungen eine Erinnerung. Anzahl zurück."""
    n = 0
    for inv in overdue_invoices(qs):
        if send_payment_reminder(inv):
            n += 1
    return n


# --------------------------------------------------------------------------- #
# Export (xlsx / CSV) – abgleichfreundlich
# --------------------------------------------------------------------------- #

INVOICE_COLUMNS = [
    "Nummer", "Empfänger", "Typ", "Jahr", "Monat", "Status", "Erstellt",
    "Fällig am", "Netto", "MwSt", "Brutto", "Überfällig", "Zuletzt erinnert",
    "IBAN",
]


def invoice_export_rows(qs):
    # `select_related("member", "guest")` deckt BEIDE Empfänger-Typen ab – eine
    # Rechnung gehört einem Mitglied ODER einem externen Gast (member=None).
    # `recipient_label`/`inv.iban` (Rechnungs-Snapshot) sind für beide sicher; ein
    # direkter `inv.member.…`-Zugriff crasht sonst bei Gäste-Rechnungen (#52).
    for inv in qs.select_related("member", "guest"):
        yield [
            inv.number, inv.recipient_label,
            "Gast" if inv.guest_id else "Mitglied",
            inv.year, inv.month, inv.get_status_display(),
            inv.created_at.date().isoformat(),
            inv.due_date.isoformat() if inv.due_date else "",
            float(inv.total_net), float(inv.total_vat), float(inv.total_gross),
            "ja" if inv.is_overdue else "nein",
            inv.reminded_at.date().isoformat() if inv.reminded_at else "",
            inv.iban,
        ]
