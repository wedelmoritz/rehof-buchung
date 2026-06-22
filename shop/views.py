"""Views des Hofladens. Dünn – Logik liegt in shop/services.py.

Sicherheit: Alle Mitglieds-bezogenen Queries laufen über `request.user.member`;
fremde Daten sind nicht erreichbar.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Invoice, Product, ProductGroup
from . import services as svc


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
    """Katalog (Gruppen + Produkte) und offener Warenkorb."""
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
            item, err = svc.add_item(
                member, product, request.POST.get("quantity", "1"),
                _parse_date(request.POST.get("service_date")))
            messages.success(request, f"Hinzugefügt: {item.quantity:g}× {item.name}.") \
                if item else messages.error(request, err or "Nicht möglich.")
        elif action == "remove":
            ok = svc.remove_item(member, request.POST.get("item_id"))
            messages.success(request, "Position entfernt.") if ok \
                else messages.error(request, "Position nicht gefunden.")
        return redirect("shop_index")

    q = (request.GET.get("q") or "").strip()
    groups = []
    for g in ProductGroup.objects.filter(active=True).prefetch_related("products"):
        products = [p for p in g.products.all() if p.active]
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
def invoices(request):
    """Eigene Rechnungen + offener Warenkorb; Rechnung als bezahlt melden."""
    member = _member(request)
    if request.method == "POST" and member:
        if request.POST.get("action") == "mark_paid":
            ok, err = svc.mark_paid(member, request.POST.get("invoice_id"))
            messages.success(request, "Danke! Als bezahlt gemeldet.") if ok \
                else messages.error(request, err or "Nicht möglich.")
        return redirect("shop_invoices")

    invs = list(member.invoices.all()) if member else []
    return render(request, "shop/invoices.html", {
        "member": member,
        "invoices": invs,
        "open_total": svc.open_total(member) if member else 0,
        "open_count": svc.open_items(member).count() if member else 0,
    })


@login_required
def invoice_detail(request, invoice_id: int):
    """Rechnungsansicht (HTML, §14-Angaben). Nur eigene Rechnungen."""
    member = _member(request)
    if not member:
        return redirect("shop_invoices")
    invoice = get_object_or_404(Invoice, id=invoice_id, member=member)
    return render(request, "shop/invoice_detail.html", {
        "member": member,
        "invoice": invoice,
        "items": invoice.items.all(),
        "breakdown": invoice.vat_breakdown(),
    })
