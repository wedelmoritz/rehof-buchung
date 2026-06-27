"""Service-Layer (dates): Datums-/Kalender-Hilfen: Monats-/Wochentags-Konstanten, Monatsgrenzen, Schulferien.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from datetime import date, timedelta
from .. import availability as A
from ..models import (
    SchoolHoliday,
)

__all__ = [
    'MONTHS_DE', 'WEEKDAYS_DE', 'month_label', 'month_bounds', 'next_month',
    '_Holiday', 'school_holidays_in_range', 'GERMAN_MONTHS', 'EXTERN_COLOR',
]

MONTHS_DE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
             "August", "September", "Oktober", "November", "Dezember"]


WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def month_label(year: int, month: int) -> str:
    return f"{MONTHS_DE[month]} {year}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Erster Tag des Monats und erster Tag des Folgemonats (exklusiv)."""
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def next_month(today: date | None = None) -> tuple[int, int]:
    today = today or date.today()
    return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)


class _Holiday:
    """Materialisierte (konkrete) Schulferien-Instanz für die Kalender-Anzeige."""
    __slots__ = ("name", "start", "end", "region")

    def __init__(self, name, start, end, region):
        self.name, self.start, self.end, self.region = name, start, end, region


def school_holidays_in_range(start: date, end: date) -> list:
    """Materialisiert die jährlich wiederkehrenden Schulferien zu konkreten
    Zeiträumen, die [start, end) berühren (für die Kalender-Anzeige)."""
    out: list[_Holiday] = []
    years = range(start.year - 1, end.year + 1)
    for h in SchoolHoliday.objects.filter(active=True):
        for y in years:
            s, e = A.recurring_range(h.start_month, h.start_day,
                                     h.end_month, h.end_day, y)
            if s < end and e > start:
                out.append(_Holiday(h.name, s, e, h.region))
    out.sort(key=lambda x: x.start)
    return out


GERMAN_MONTHS = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
    "August", "September", "Oktober", "November", "Dezember",
]


# Einheitliche Farbe für externe Gäste in der Gemeinschafts-Übersicht (klar von
# den Mitglieder-Pastellfarben unterscheidbar, ohne Gastdaten preiszugeben).
EXTERN_COLOR = "#8a93a6"
