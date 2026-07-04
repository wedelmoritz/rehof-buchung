"""Belegungsplan-Druck-PDF (WeasyPrint) für die Betriebsleitung (#39, ADR 0083).

Wie beim Rechnungs-PDF (``shop/pdf.py``) bewusst zweigeteilt:
  * ``plan_print_html`` baut nur die HTML-Zeichenkette (reines Django-Templating,
    ohne native Abhängigkeiten – gut testbar) und
  * ``plan_pdf_bytes`` rendert daraus mit WeasyPrint ein **Querformat**-PDF.

WeasyPrint (Pango/Cairo) ist nur im Docker-/CI-Image installiert; der Import von
``weasyprint`` erfolgt daher erst zur Laufzeit in ``plan_pdf_bytes``.
"""
from __future__ import annotations

from datetime import date

from django.template.loader import render_to_string


def plan_print_html(anchor: date, span_days: int, management: bool = True,
                    generated_on: date | None = None) -> str:
    """Eigenständiges Druck-HTML des Belegungsplans (ohne base.html) –
    Querformat-Raster (nacht-basiert) + Listen Anreisen/Abreisen/Reinigung."""
    from . import services as svc
    ctx = svc.build_plan_print(anchor, span_days, management=management)
    ctx["generated_on"] = generated_on or date.today()
    return render_to_string("booking/plan_pdf.html", ctx)


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


def _no_remote_fetcher(url, *args, **kwargs):
    """URL-Fetcher, der KEINE Netz-/Datei-Abrufe zulässt (nur ``data:``-URIs) –
    SSRF-Schutz analog zum Rechnungs-PDF (ADR 0061). Der Plan referenziert ohnehin
    keine externen Ressourcen."""
    if url.startswith("data:"):
        from weasyprint.urls import default_url_fetcher
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError(f"Externer Ressourcen-Abruf im Plan-PDF blockiert: {url}")


def plan_pdf_bytes(anchor: date, span_days: int, management: bool = True) -> bytes:
    """Rendert den Belegungsplan als PDF. Wirft, wenn WeasyPrint/native Libs fehlen."""
    from weasyprint import HTML
    html = plan_print_html(anchor, span_days, management=management)
    return HTML(string=html, url_fetcher=_no_remote_fetcher).write_pdf()
