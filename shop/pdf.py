"""Rechnungs-PDF (WeasyPrint).

Bewusst zweigeteilt:
  * `invoice_html` baut nur die HTML-Zeichenkette (reines Django-Templating,
    ohne native Abhängigkeiten – damit gut testbar) und
  * `invoice_pdf_bytes` rendert daraus mit WeasyPrint ein PDF.

WeasyPrint braucht native Bibliotheken (Pango/Cairo), die im Docker-Image
installiert sind. In einer Umgebung ohne diese Libs schlägt erst der Aufruf von
`invoice_pdf_bytes` fehl, nicht schon der Import dieses Moduls – `weasyprint`
wird daher absichtlich erst zur Laufzeit importiert.
"""
from __future__ import annotations

from django.template.loader import render_to_string

from .models import Invoice, ShopConfig


def invoice_context(invoice: Invoice) -> dict:
    cfg = ShopConfig.get_solo()
    return {
        "invoice": invoice,
        "purchase_groups": invoice.purchase_groups(),
        "breakdown": invoice.vat_breakdown(),
        "payment_term_days": cfg.payment_term_days,
    }


def invoice_html(invoice: Invoice) -> str:
    """Eigenständiges Druck-HTML der Rechnung (ohne base.html)."""
    return render_to_string("shop/invoice_pdf.html", invoice_context(invoice))


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


def _no_remote_fetcher(url, *args, **kwargs):
    """URL-Fetcher für WeasyPrint, der KEINE Netz-/Datei-Abrufe zulässt (nur
    `data:`-URIs). Das Rechnungs-PDF referenziert ohnehin keine externen
    Ressourcen; so kann selbst eingeschleuster Inhalt WeasyPrint nicht zu einem
    Abruf interner URLs verleiten (SSRF-Schutz, ADR 0061)."""
    if url.startswith("data:"):
        from weasyprint.urls import default_url_fetcher
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError(f"Externer Ressourcen-Abruf im Rechnungs-PDF blockiert: {url}")


def invoice_pdf_bytes(invoice: Invoice) -> bytes:
    """Rendert die Rechnung als PDF. Wirft, wenn WeasyPrint/native Libs fehlen."""
    from weasyprint import HTML
    return HTML(string=invoice_html(invoice),
                url_fetcher=_no_remote_fetcher).write_pdf()
