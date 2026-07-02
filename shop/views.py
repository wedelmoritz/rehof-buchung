"""Views des Hofladens. Dünn – Logik liegt in shop/services.py.

Ablauf: Warenkorb (offene Positionen) → Checkout (bestätigter Einkauf) →
Rechnung (monatlich oder sofort). Sicherheit: Alle Mitglieds-bezogenen Queries
laufen über `request.user.member`; fremde Daten sind nicht erreichbar.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .models import Invoice, Payment, Product, ProductGroup, ShopConfig
from . import payments, services as svc


def _member(request):
    return getattr(request.user, "member", None)


def _parse_date(s):
    from datetime import date
    try:
        return date.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


@login_required
def shop_index(request):
    """Katalog (Gruppen + Produkte) und Warenkorb (Menge änderbar)."""
    member = _member(request)

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        if action == "add":
            try:
                product = Product.objects.get(
                    id=request.POST.get("product"), active=True)
            except (Product.DoesNotExist, ValueError, TypeError):
                messages.error(request, "Produkt nicht gefunden.")
                return redirect("shop_index")
            if product.book_with_stay:
                # Server-seitig absichern (#37): solche Leistungen werden nur beim
                # Buchen angefragt, nicht über den Hofladen-Warenkorb gekauft.
                messages.error(request, "Diese Leistung (z.B. Endreinigung) wird "
                                "direkt beim Buchen einer Unterkunft angefragt, "
                                "nicht über den Hofladen.")
                return redirect("shop_index")
            item, err = svc.add_item(
                member, product, request.POST.get("quantity", "1"),
                _parse_date(request.POST.get("service_date")))
            messages.success(request, f"Hinzugefügt: {item.quantity:g}× {item.name}.") \
                if item else messages.error(request, err or "Nicht möglich.")
        elif action == "set_qty":
            ok, err = svc.set_cart_quantity(
                member, request.POST.get("item_id"), request.POST.get("quantity", "0"))
            if not ok:
                messages.error(request, err or "Nicht möglich.")
        elif action == "remove":
            ok = svc.remove_item(member, request.POST.get("item_id"))
            messages.success(request, "Position entfernt.") if ok \
                else messages.error(request, "Position nicht gefunden.")
        return redirect("shop_index")

    q = (request.GET.get("q") or "").strip()
    groups = []
    for g in ProductGroup.objects.filter(active=True).prefetch_related("products"):
        # „Beim Buchen anbieten“-Leistungen (z.B. Endreinigung) gehören in den
        # Buchungsabschnitt, NICHT in den Hofladen-Katalog (#37/ADR 0081): hier
        # ausblenden, damit sie nicht als eigenständiger Kauf erscheinen.
        products = [p for p in g.products.all()
                    if p.active and not p.book_with_stay]
        if q:
            products = [p for p in products if q.lower() in p.name.lower()]
        if products:
            groups.append({"group": g, "products": products})

    items = list(svc.open_items(member)) if member else []
    return render(request, "shop/index.html", {
        "member": member,
        "groups": groups,
        "q": q,
        "items": items,
        "total": svc.open_total(member) if member else 0,
    })


@login_required
def checkout(request):
    """Bestätigungsschritt: Warenkorb prüfen und verbindlich kaufen – optional
    gleich abrechnen."""
    member = _member(request)
    if not member:
        return redirect("shop_index")

    if request.method == "POST":
        if request.POST.get("action") == "confirm":
            purchase, err = svc.checkout(member)
            if not purchase:
                messages.error(request, err or "Nicht möglich.")
                return redirect("shop_index")
            if request.POST.get("invoice_now"):
                inv, _err = svc.generate_invoice_now(member)
                if inv:
                    messages.success(
                        request, f"Einkauf bestätigt – Rechnung {inv.number} erstellt.")
                    return redirect("shop_invoice", inv.id)
            messages.success(
                request, "Einkauf bestätigt. Er erscheint auf deiner Rechnung.")
            return redirect("shop_invoices")
        return redirect("shop_checkout")

    items = list(svc.open_items(member))
    return render(request, "shop/checkout.html", {
        "member": member, "items": items, "total": svc.open_total(member),
    })


@login_required
def invoices(request):
    """Eigene Rechnungen + bestätigte (noch offene) Einkäufe; sofort abrechnen
    oder Rechnung als bezahlt melden."""
    member = _member(request)
    if request.method == "POST" and member:
        action = request.POST.get("action")
        if action == "mark_paid":
            ok, err = svc.mark_paid(member, request.POST.get("invoice_id"))
            messages.success(request, "Danke! Als bezahlt gemeldet.") if ok \
                else messages.error(request, err or "Nicht möglich.")
        elif action == "invoice_now":
            inv, err = svc.generate_invoice_now(member)
            messages.success(request, f"Rechnung {inv.number} erstellt.") if inv \
                else messages.error(request, err or "Nicht möglich.")
        return redirect("shop_invoices")

    invs = list(member.invoices.all()) if member else []
    return render(request, "shop/invoices.html", {
        "member": member,
        "invoices": invs,
        "unbilled": list(svc.unbilled_purchases(member)) if member else [],
        "unbilled_total": svc.unbilled_total(member) if member else 0,
        "open_total": svc.open_total(member) if member else 0,
        "open_count": svc.open_items(member).count() if member else 0,
        # Selbst-Meldung „Habe ich überwiesen" optional abschaltbar (#26/ADR 0078).
        "allow_self_report": ShopConfig.get_solo().allow_self_report_paid,
    })


@login_required
def invoice_detail(request, invoice_id: int):
    """Rechnungsansicht (HTML, §14-Angaben). Nur eigene Rechnungen.
    Positionen nach Einkauf (Datum) gruppiert."""
    member = _member(request)
    if not member:
        return redirect("shop_invoices")
    invoice = get_object_or_404(Invoice, id=invoice_id, member=member)
    return render(request, "shop/invoice_detail.html", {
        "member": member,
        "invoice": invoice,
        "purchase_groups": invoice.purchase_groups(),
        "breakdown": invoice.vat_breakdown(),
        # Selbst-Meldung „Habe ich überwiesen" optional abschaltbar (#26/ADR 0078).
        "allow_self_report": ShopConfig.get_solo().allow_self_report_paid,
    })


@login_required
def invoice_pdf(request, invoice_id: int):
    """Rechnung als PDF (WeasyPrint). Mitglied: eigene; Verwaltung: alle."""
    member = _member(request)
    from booking.permissions import is_verwaltung
    if is_verwaltung(request.user):
        invoice = get_object_or_404(Invoice, id=invoice_id)
    elif member:
        invoice = get_object_or_404(Invoice, id=invoice_id, member=member)
    else:
        return redirect("shop_invoices")
    from . import pdf
    if not pdf.weasyprint_available():
        return HttpResponse(
            "PDF-Erzeugung ist auf diesem Server nicht verfügbar.", status=503)
    resp = HttpResponse(pdf.invoice_pdf_bytes(invoice), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{invoice.number}.pdf"'
    return resp


# --------------------------------------------------------------------------- #
# Online-Bezahlung (Mollie) – für Mitglieder (hier) und Gäste (booking/external)
# --------------------------------------------------------------------------- #

@login_required
def pay_invoice(request, invoice_id: int):
    """Mitglied startet die Online-Bezahlung einer eigenen Rechnung."""
    member = _member(request)
    if not member:
        return redirect("shop_invoices")
    invoice = get_object_or_404(Invoice, id=invoice_id, member=member)
    if not payments.payments_enabled():
        messages.error(request, "Online-Bezahlung ist derzeit deaktiviert.")
        return redirect("shop_invoice", invoice.id)
    if not invoice.is_payable:
        messages.info(request, "Diese Rechnung ist bereits beglichen.")
        return redirect("shop_invoice", invoice.id)
    try:
        pay = payments.start_payment(invoice, request=request)
    except payments.PaymentUnavailable:
        messages.error(request, "Online-Bezahlung ist derzeit nicht möglich.")
        return redirect("shop_invoice", invoice.id)
    return redirect(pay.checkout_url)


def payment_sandbox(request, token):
    """Eingebaute TEST-Bezahlseite (kein Mollie-Konto/keine Gebühren). Simuliert
    eine Zahlung; login-frei, da über den unfälschbaren Token geschützt."""
    pay = get_object_or_404(Payment, token=token)
    if request.method == "POST":
        if pay.status == Payment.OPEN:
            if request.POST.get("action") == "pay":
                payments.settle_payment(pay)
            else:
                payments.cancel_payment(pay)
        return redirect("payment_return", token=pay.token)
    return render(request, "shop/payment_sandbox.html",
                  {"pay": pay, "invoice": pay.invoice})


def payment_return(request, token):
    """Rückkehrseite nach der Bezahlung (Mollie oder Sandbox)."""
    pay = get_object_or_404(Payment, token=token)
    # Echtes Mollie: Status nachziehen, falls der Webhook noch nicht durch ist.
    if not pay.is_sandbox and pay.status == Payment.OPEN and pay.provider_id:
        _refresh_mollie(pay)
    inv = pay.invoice
    back_url = None
    if inv.member_id:
        back_url = reverse("shop_invoice", args=[inv.id])
    elif inv.guest_id:
        back_url = reverse("external_manage", args=[inv.guest.token])
    return render(request, "shop/payment_return.html",
                  {"pay": pay, "invoice": inv, "back_url": back_url})


@csrf_exempt
def payment_webhook(request):
    """Mollie-Webhook (nur Echtbetrieb): meldet eine Zahlungs-ID, wir fragen den
    Status sicher serverseitig nach."""
    if request.method != "POST":
        return HttpResponse(status=405)
    pid = request.POST.get("id")
    if pid:
        try:
            _refresh_mollie(Payment.objects.get(provider_id=pid))
        except Payment.DoesNotExist:
            pass
    return HttpResponse("ok")


def _refresh_mollie(pay: Payment) -> None:
    try:
        from . import mollie_api
        from .models import ShopConfig
        st = mollie_api.payment_status(
            ShopConfig.get_solo().mollie_api_key.strip(), pay.provider_id)
        if st == "paid":
            payments.settle_payment(pay)
        elif st in ("expired", "failed", "canceled"):
            payments.cancel_payment(pay, status=st)
    except Exception:  # noqa: BLE001
        pass
