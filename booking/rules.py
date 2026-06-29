"""
Buchungsregeln (Mindestnächte, Parallel-Limit, Aufenthaltsdeckel) – reines
Python, damit isoliert und schnell testbar.

Die konkreten Zeiträume und Schwellen werden im Admin gepflegt (Modelle
``BookingPolicy`` und ``SeasonRule``); dieses Modul enthält nur die Prüflogik.

Drei Regelarten je Saison (jeweils optional):
  * min_nights           Mindestbuchungsdauer in diesem Zeitraum
                         (Beispiel: Juli/August 7 Nächte; Standard sonst 3).
  * max_parallel_units   Höchstzahl gleichzeitig gebuchter Wohneinheiten pro
                         Mitglied (Beispiel: Schulferien/Feiertage = 2).
  * max_stay_nights      Obergrenze der Aufenthaltsnächte je Partei innerhalb
                         des Zeitraums, gezählt als Einheiten-Nächte
                         (Beispiel: BB-Sommerferien = 14, also „zwei Wochen
                         eine Einheit ODER eine Woche zwei Einheiten“).

Einheiten-Nächte: Jede Buchung belegt eine Wohneinheit; gezählt werden die in
den Zeitraum fallenden Nächte. Zwei Wochen in einer Einheit = 14; eine Woche in
zwei Einheiten = 7 + 7 = 14. Beides erreicht den Deckel von 14.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Season:
    name: str
    start: date
    end: date  # exklusiv
    min_nights: int | None = None
    max_parallel_units: int | None = None
    max_stay_nights: int | None = None
    active: bool = True


@dataclass(frozen=True)
class Stay:
    """Eine bestehende Buchung eines Mitglieds (eine Wohneinheit)."""
    start: date
    end: date  # exklusiv


def _overlap_nights(a0: date, a1: date, b0: date, b1: date) -> int:
    lo, hi = max(a0, b0), min(a1, b1)
    return max(0, (hi - lo).days)


def required_min_nights(
    seasons: list[Season], default_min: int, start: date, end: date
) -> int:
    """Strengste Mindestnächte-Vorgabe für eine Buchung [start, end)."""
    req = default_min
    for s in seasons:
        if (s.active and s.min_nights is not None
                and _overlap_nights(start, end, s.start, s.end) > 0):
            req = max(req, s.min_nights)
    return req


def validate_booking(
    seasons: list[Season],
    default_min_nights: int,
    start: date,
    end: date,
    existing: list[Stay],
    skip_min_nights: bool = False,
) -> str | None:
    """Prüft eine geplante Buchung gegen alle Regeln.

    `existing` sind die bereits bestehenden Buchungen DESSELBEN Mitglieds
    (die neue ist noch nicht enthalten). Rückgabe: Fehlertext oder None (ok).

    `skip_min_nights` hebt NUR die Mindestnächte-Prüfung auf (Parallel-Limit und
    Aufenthaltsdeckel bleiben) – genutzt für lückenfüllende Buchungen (ADR 0075),
    bei denen eine Buchung eine freie Lücke exakt ausfüllt.
    """
    nights = (end - start).days
    if nights <= 0:
        return "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."

    # (1) Mindestnächte
    if not skip_min_nights:
        req = required_min_nights(seasons, default_min_nights, start, end)
        if nights < req:
            return (f"Mindestbuchung in diesem Zeitraum: {req} Nächte "
                    f"(gewählt: {nights}).")

    # (2) Höchstzahl gleichzeitiger Wohneinheiten je Mitglied
    for s in seasons:
        if not (s.active and s.max_parallel_units is not None):
            continue
        if _overlap_nights(start, end, s.start, s.end) <= 0:
            continue
        d = max(start, s.start)
        upper = min(end, s.end)
        while d < upper:
            count = 1  # die neue Buchung
            for b in existing:
                if b.start <= d < b.end:
                    count += 1
            if count > s.max_parallel_units:
                return (f"Im Zeitraum „{s.name}“ sind höchstens "
                        f"{s.max_parallel_units} Wohneinheiten gleichzeitig "
                        f"pro Mitglied buchbar.")
            d += timedelta(days=1)

    # (3) Aufenthaltsdeckel je Saison (Einheiten-Nächte)
    for s in seasons:
        if not (s.active and s.max_stay_nights is not None):
            continue
        new_n = _overlap_nights(start, end, s.start, s.end)
        if new_n <= 0:
            continue
        old_n = sum(
            _overlap_nights(b.start, b.end, s.start, s.end) for b in existing
        )
        if old_n + new_n > s.max_stay_nights:
            return (f"Im Zeitraum „{s.name}“ sind höchstens "
                    f"{s.max_stay_nights} Nächte je Partei buchbar "
                    f"(bereits {old_n}, angefragt {new_n}).")

    return None
