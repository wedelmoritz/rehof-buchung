"""Reine Logik für externe Gäste (ohne Django) – Verfügbarkeits-Regeln.

Trennt bewusst „grundsätzlich für Externe erlaubt“ (diese Regeln) von „tatsächlich
frei“ (Belegung, liegt im Service-Layer). Datumsbasiert und isoliert testbar.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal


def external_allowed(
    start: date, end: date, *, today: date,
    allowed_weekdays: set[int] | None = None,
    min_nights: int = 1, max_nights: int = 0,
    lead_days: int = 0, horizon_days: int = 0,
) -> tuple[bool, str | None]:
    """Prüft die Externen-Regeln für [start, end). Gibt (ok, Fehlertext)."""
    nights = (end - start).days
    if nights <= 0:
        return False, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    if min_nights and nights < min_nights:
        return False, f"Mindestaufenthalt für Externe: {min_nights} Nächte."
    if max_nights and nights > max_nights:
        return False, f"Höchstaufenthalt für Externe: {max_nights} Nächte."
    lead = (start - today).days
    if lead < lead_days:
        return False, f"Bitte mindestens {lead_days} Tag(e) im Voraus buchen."
    if horizon_days and lead > horizon_days:
        return False, "Dieser Zeitraum liegt zu weit in der Zukunft."
    if allowed_weekdays:
        d = start
        while d < end:
            if d.weekday() not in allowed_weekdays:
                return False, ("In diesem Zeitraum sind externe Übernachtungen an "
                               "mindestens einem Tag nicht möglich (z. B. nur "
                               "Mo–Do).")
            d += timedelta(days=1)
    return True, None


def cancellation_refund(
    total, *, arrival: date, today: date,
    free_days: int = 30, partial_days: int = 7, partial_percent: int = 50,
) -> tuple[Decimal, int, str]:
    """Erstattung bei Storno gemäß Vorlauf zur Anreise (reine Logik).

    Gibt (Erstattungsbetrag, Erstattungsquote in %, Stufen-Bezeichnung).
    Staffel: bis `free_days` vor Anreise 100 %, bis `partial_days` vorher
    `partial_percent` %, danach 0 %.
    """
    total = Decimal(total)
    lead = (arrival - today).days
    if lead >= free_days:
        pct = 100
        label = "Kostenlose Stornofrist"
    elif lead >= partial_days:
        pct = int(partial_percent)
        label = "Teil-Erstattung"
    else:
        pct = 0
        label = "Keine Erstattung"
    refund = (total * Decimal(pct) / Decimal(100)).quantize(Decimal("0.01"))
    return refund, pct, label
