"""
Freischaltung von Buchungszeiträumen und Tage-Rechnung – reines Python.

Wie das Losmodul ist auch dieses Modul bewusst frei von Django, damit die
Regeln isoliert und schnell testbar sind.

Zwei Themen:

1) Freigeschaltete Buchungszeiträume ("Fenster"). Der Admin legt fest, in
   welchen Zeiträumen normal gebucht werden darf – global für alle Quartiere
   und optional enger für einzelne Quartiere.

   Semantik (Schnittmenge mit globaler Grundfreigabe):
     Ein Quartier ist an einem Tag buchbar, wenn
       (a) ein aktives GLOBALES Fenster diesen Tag abdeckt  (Grundfreigabe),  UND
       (b) das Quartier in KEINEM aktiven spezifischen Fenster genannt ist
           ODER ein aktives spezifisches Fenster dieses Quartiers den Tag abdeckt.
     -> Spezifische Fenster können nur WEITER EINSCHRÄNKEN, nie über die
        globale Freigabe hinaus erweitern.

   Das Losverfahren nutzt diese Fenster bewusst NICHT: Es vergibt das nächste
   Jahr im Voraus, dessen Buchungszeitraum noch gar nicht freigeschaltet ist.

2) Verfügbare Tage. Tage werden NICHT ins Folgejahr übertragen, können aber an
   andere Mitglieder übertragen werden. Der Rest eines Jahres ergibt sich aus
   Jahreskontingent + erhaltene − abgegebene − bereits verbrauchte Tage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


# --------------------------------------------------------------------------- #
# 1) Buchungszeiträume
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Window:
    """Ein freigeschalteter Buchungszeitraum [start, end). `applies_to_all`
    True = globales Fenster (alle Quartiere); sonst gilt es nur für die in
    `quarter_ids` genannten Quartiere."""
    start: date
    end: date
    applies_to_all: bool
    quarter_ids: frozenset[str] = field(default_factory=frozenset)
    active: bool = True

    def covers(self, day: date) -> bool:
        return self.active and self.start <= day < self.end


def is_released(windows: list[Window], quarter_id: str, day: date) -> bool:
    """Ist `quarter_id` am `day` buchbar? (Schnittmengen-Semantik, s.o.)"""
    global_ok = any(w.covers(day) for w in windows if w.applies_to_all)
    if not global_ok:
        return False
    specific = [
        w for w in windows
        if (not w.applies_to_all) and w.active and quarter_id in w.quarter_ids
    ]
    if not specific:
        return True
    return any(w.start <= day < w.end for w in specific)


def range_released(
    windows: list[Window], quarter_id: str, start: date, end: date
) -> bool:
    """Ist der ganze Zeitraum [start, end) für das Quartier freigeschaltet?"""
    if end <= start:
        return False
    d = start
    while d < end:
        if not is_released(windows, quarter_id, d):
            return False
        d += timedelta(days=1)
    return True


def released_gaps(
    windows: list[Window],
    quarter_id: str,
    occupied: set[date],
    window_start: date,
    window_end: date,
) -> list[tuple[date, date]]:
    """Liefert die buchbaren Lücken eines Quartiers: zusammenhängende Tage im
    Fenster [window_start, window_end), die FREI (nicht in `occupied`) UND
    freigeschaltet sind."""
    spans: list[tuple[date, date]] = []
    cur: date | None = None
    d = window_start
    while d < window_end:
        bookable = (d not in occupied) and is_released(windows, quarter_id, d)
        if bookable and cur is None:
            cur = d
        elif not bookable and cur is not None:
            spans.append((cur, d))
            cur = None
        d += timedelta(days=1)
    if cur is not None:
        spans.append((cur, window_end))
    return spans


# --------------------------------------------------------------------------- #
# 2) Verfügbare Tage (ohne Übertrag ins Folgejahr, mit Übertrag an Mitglieder)
# --------------------------------------------------------------------------- #

def recurring_range(
    start_month: int, start_day: int, end_month: int, end_day: int, year: int,
) -> tuple[date, date]:
    """Konkrete [start, end) eines jährlich wiederkehrenden Zeitraums im `year`
    (Ende exklusiv). Liegt das Ende (Monat/Tag) am oder vor dem Start, läuft der
    Zeitraum über den Jahreswechsel ins Folgejahr (z.B. Weihnachten/Silvester)."""
    start = date(year, start_month, start_day)
    if (end_month, end_day) <= (start_month, start_day):
        end = date(year + 1, end_month, end_day)
    else:
        end = date(year, end_month, end_day)
    return start, end


def weekend_keys(start: date, end: date) -> set[tuple[int, int]]:
    """ISO-(Jahr, Woche) jeder Wochenend-Nacht in [start, end) – gewertet werden
    die Nächte von **Freitag und Samstag** (man schläft Fr→Sa bzw. Sa→So). So
    zählt ein Aufenthalt, der ein Wochenende berührt, genau einmal je Wochenende
    (reine Logik, ohne Django; für den Wochenend-Richtwert, ADR 0076)."""
    keys: set[tuple[int, int]] = set()
    d = start
    while d < end:
        if d.weekday() in (4, 5):          # Freitag, Samstag
            iso = d.isocalendar()
            keys.add((iso[0], iso[1]))
        d += timedelta(days=1)
    return keys


def remaining_nights(
    annual_budget: int, used: int, received: int = 0, given: int = 0
) -> int:
    """Verbleibende Tage in einem Jahr:
       Jahreskontingent + erhaltene − abgegebene − verbrauchte Tage.
    Hinweis: Es gibt bewusst KEINEN Übertrag aus dem Vorjahr; das Kontingent
    gilt je Kalenderjahr frisch."""
    return annual_budget + received - given - used
