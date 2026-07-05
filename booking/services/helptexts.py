"""Service-Layer (helptexts): lädt die **ausgelagerten Hilfetexte** (ADR 0093) aus
den Inhalts-Dateien `booking/help_content/*.md` und rendert sie **sicher** über den
Django-freien `booking.helptext.render_markup` (escape-first, kein SSTI).

So liegt die redaktionelle Hilfe-Prosa in editierbaren Text-Dateien getrennt vom
Template-Markup (Feedback #66): eine Textänderung ist ein risikoarmer Ein-Datei-Edit,
ohne die Template-Struktur/CSP zu berühren. URLs kommen als `$url_*`-Platzhalter aus
`reverse()` (keine Template-Tags in den Inhalts-Dateien).
"""
from __future__ import annotations

from pathlib import Path

from ..helptext import render_markup

__all__ = ["HELP_SECTION_KEYS", "help_sections"]

HELP_CONTENT_DIR = Path(__file__).resolve().parent.parent / "help_content"

# Ausgelagerte Abschnitte (Datei help_content/<key>.md, erste Zeile „# Titel").
# Der `key` ist zugleich der Anker (#<key>) in der Hilfe-Seite/TOC.
HELP_SECTION_KEYS = ["warteliste", "gemeinschaft", "hofladen", "tage"]


def _help_context() -> dict:
    from django.urls import reverse
    return {
        "url_my_bookings": reverse("my_bookings"),
        "url_shop": reverse("shop_index"),
        "url_transfer": reverse("transfer"),
    }


def help_sections() -> dict:
    """Liefert die ausgelagerten Hilfe-Abschnitte als Dict
    ``{key: {"title": str, "html": str}}`` (HTML bereits sicher gerendert)."""
    ctx = _help_context()
    out: dict = {}
    for key in HELP_SECTION_KEYS:
        try:
            raw = (HELP_CONTENT_DIR / f"{key}.md").read_text(encoding="utf-8")
        except OSError:
            continue
        lines = raw.splitlines()
        title = ""
        body = raw
        if lines and lines[0].startswith("# "):
            title = lines[0][2:].strip()
            body = "\n".join(lines[1:])
        out[key] = {"title": title, "html": render_markup(body, ctx)}
    return out
