"""Reine Logik für externe Gäste (ohne Django) – Verfügbarkeits-Regeln.

Trennt bewusst „grundsätzlich für Externe erlaubt“ (diese Regeln) von „tatsächlich
frei“ (Belegung, liegt im Service-Layer). Datumsbasiert und isoliert testbar.
"""
from __future__ import annotations

from datetime import date, timedelta


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
