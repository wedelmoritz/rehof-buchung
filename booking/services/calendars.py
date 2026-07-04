"""Service-Layer (calendars): Kalender-Aufbau (Buchen/Wunsch/Community/Belegung/Extern) und Tagesdetail.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

import calendar as _calendar
from collections import defaultdict
from datetime import date, timedelta
from .. import availability as A
from ..models import (
    Allocation, ExternalBooking, ExternalConfig, Member, Quarter, Wish,
)
from .dates import EXTERN_COLOR, GERMAN_MONTHS, next_month, school_holidays_in_range
from .slots import (_active_windows, _in_season_range, _occupied_days_by_quarter,
                    split_quarters_for_range)

__all__ = [
    'build_booking_calendar', 'build_wish_calendar', 'quarter_wish_counts',
    'wish_deconfliction', 'wish_alternatives',
    'day_detail', 'build_member_calendar', 'build_community_calendar',
    'build_occupancy_timeline', 'build_external_calendar', 'week_agenda',
]


def week_agenda(member, start: date, days: int = 7) -> list[dict]:
    """Kompakte „Diese Woche"-Agenda ab `start`: je Tag die An-/Abreisen
    (Mitglieder UND externe Gäste) und die Zahl freier Quartiere. Für die
    aufgeräumte Übersicht (schneller Wochenblick, mobil-tauglich)."""
    end = start + timedelta(days=days)
    allocs = list(
        Allocation.objects.select_related("quarter", "member")
        .filter(provisional=False, start__lt=end, end__gt=start))
    exts = list(
        ExternalBooking.objects.filter(
            status=ExternalBooking.CONFIRMED, start__lt=end, end__gt=start)
        .select_related("quarter"))
    mid = member.id if member else None
    # Belegte Tage je Quartier einmalig aus den bereits geladenen Buchungen
    # bilden – KEINE per-Tag-Abfragen (sonst N+1 auf der Startseite, ADR 0060).
    occ: dict = defaultdict(set)
    for bk in allocs + exts:
        d = max(bk.start, start)
        upper = min(bk.end, end)
        while d < upper:
            occ[bk.quarter_id].add(d)
            d += timedelta(days=1)
    windows = _active_windows()                 # 1 Abfrage für die ganze Woche
    quarters = list(Quarter.objects.all())      # 1 Abfrage
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        nxt = d + timedelta(days=1)
        arrivals, departures = [], []
        for a in allocs:
            if a.start == d:
                arrivals.append({"who": a.member.display_name, "quarter": a.quarter.name,
                                 "persons": a.persons, "mine": a.member_id == mid})
            if a.end == d:
                departures.append({"who": a.member.display_name, "quarter": a.quarter.name,
                                   "mine": a.member_id == mid})
        for b in exts:
            if b.start == d:
                arrivals.append({"who": "extern", "quarter": b.quarter.name,
                                 "persons": b.persons, "mine": False, "external": True})
            if b.end == d:
                departures.append({"who": "extern", "quarter": b.quarter.name,
                                   "mine": False, "external": True})
        # frei = freigeschaltet (Periode + Quartier-Saison) UND an dem Tag unbelegt
        free_count = sum(
            1 for q in quarters
            if d not in occ[q.id]
            and A.range_released(windows, str(q.id), d, nxt)
            and _in_season_range(q, d, nxt))
        out.append({"date": d, "is_today": d == start,
                    "arrivals": arrivals, "departures": departures,
                    "free_count": free_count})
    return out

def build_booking_calendar(
    member, year: int, month: int,
    sel_start: date | None = None, sel_end: date | None = None,
) -> dict:
    """Monatsmatrix für die Buchung mit Ampel-Färbung je Tag:

      free  (grün)      – noch gar nichts belegt
      many  (hellgrün)  – noch viele Quartiere frei (> 50 %)
      few   (gelb)      – nur noch wenige frei
      full  (rot)       – nichts mehr frei
      none  (neutral)   – an diesem Tag ist nichts freigeschaltet

    `sel_start`/`sel_end` markieren die aktuelle Auswahl im Kalender.
    """
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    windows = _active_windows()
    quarters = list(Quarter.objects.filter(active=True))
    qmap = {str(q.id): q for q in quarters}
    qids = list(qmap)
    occupied = _occupied_days_by_quarter(first, last)
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    own_days: set[date] = set()
    if member:
        for a in member.allocations.filter(
                start__lte=last, end__gt=first, provisional=False):
            d = max(a.start, first)
            upper = min(a.end, last + timedelta(days=1))
            while d < upper:
                own_days.add(d)
                d += timedelta(days=1)
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            released = [
                qid for qid in qids
                if A.is_released(windows, qid, d) and qmap[qid].bookable_on(d)
            ]
            total = len(released)
            free = sum(1 for qid in released if d not in occupied[qid])
            if total == 0:
                level = "none"
            elif free == total:
                level = "free"
            elif free == 0:
                level = "full"
            elif free * 2 > total:
                level = "many"
            else:
                level = "few"
            in_range = bool(
                sel_start and (
                    (sel_end and sel_start <= d < sel_end)
                    or (not sel_end and d == sel_start)
                )
            )
            row.append({
                "date": d,
                "iso": d.isoformat(),
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "is_past": d < today,
                "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
                "level": level,
                "free": free,
                "total": total,
                "mine": d in own_days,
                "in_range": in_range,
                "is_start": sel_start == d,
                "is_end": bool(sel_end) and sel_end == d,
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "weeks": grid,
        "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year, "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


def build_wish_calendar(
    member, period, year: int, month: int,
    sel_start: date | None = None, sel_end: date | None = None,
) -> dict:
    """Monatsmatrix für die Wunschliste mit Ampel nach Wunsch-Nachfrage:

      free  (grün)     – noch keine eingereichten Wünsche
      many  (hellgrün) – wenig Nachfrage
      few   (gelb)     – mittlere Nachfrage
      full  (rot)      – mehr Wünsche als Quartiere → hart umkämpft

    Eigene Wünsche werden markiert (eingereicht vs. Entwurf).
    """
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    n_quarters = max(1, Quarter.objects.filter(active=True).count())
    submitted, own = [], []
    if period:
        submitted = list(Wish.objects.filter(
            period=period, submitted=True, start__lte=last, end__gt=first))
        if member:
            own = list(Wish.objects.filter(
                period=period, member=member, start__lte=last, end__gt=first))
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            demand = sum(1 for w in submitted if w.start <= d < w.end)
            if demand == 0:
                level = "free"
            elif demand <= n_quarters // 2 or demand == 1:
                level = "many"
            elif demand <= n_quarters:
                level = "few"
            else:
                level = "full"
            own_sub = any(w.start <= d < w.end for w in own if w.submitted)
            own_draft = any(w.start <= d < w.end for w in own if not w.submitted)
            in_range = bool(
                sel_start and ((sel_end and sel_start <= d < sel_end)
                               or (not sel_end and d == sel_start)))
            row.append({
                "date": d, "iso": d.isoformat(), "day": d.day,
                "in_month": d.month == month, "is_today": d == today,
                "is_weekend": d.weekday() >= 5, "is_past": d < today,
                "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
                "level": level, "demand": demand,
                "own_sub": own_sub, "own_draft": own_draft,
                "in_range": in_range, "is_start": sel_start == d,
                "is_end": bool(sel_end) and sel_end == d,
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "weeks": grid, "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year, "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


def quarter_wish_counts(period, start: date, end: date) -> dict[str, int]:
    """Anzahl eingereichter Wünsche je Quartier, die [start, end) überlappen –
    zeigt, welche Quartiere im Wunschzeitraum besonders umkämpft sind."""
    counts: dict[str, int] = defaultdict(int)
    if not period or end <= start:
        return counts
    for w in Wish.objects.filter(
        period=period, submitted=True, start__lt=end, end__gt=start,
    ):
        counts[str(w.quarter_id)] += 1
    return counts


def wish_deconfliction(period, start: date, end: date, *, max_shift: int = 2) -> dict:
    """Unverbindliche Ausweich-Vorschläge (P2.4, ADR 0064): pro Quartier die nahe
    Zeitraum-Verschiebung (gleiche Länge, ±`max_shift` Tage) mit der GERINGSTEN
    Konkurrenz – sofern besser als der gewählte Zeitraum.

    Nur Hinweise: keine Buchung, keine Änderung am Losverfahren, kein Schreibpfad.
    EINE DB-Abfrage (alle eingereichten Wünsche im Fenster), Rest in Python; gibt
    `{quarter_id: {"base": n, "best": {start,end,count,shift}}}` für umkämpfte
    Quartiere zurück."""
    out: dict[str, dict] = {}
    if not period or end <= start:
        return out
    length = (end - start).days
    win_s = start - timedelta(days=max_shift)
    win_e = end + timedelta(days=max_shift)
    by_q: dict[str, list] = defaultdict(list)
    for qid, ws, we in Wish.objects.filter(
        period=period, submitted=True, start__lt=win_e, end__gt=win_s,
    ).values_list("quarter_id", "start", "end"):
        by_q[str(qid)].append((ws, we))

    def contention(spans, s, e) -> int:
        return sum(1 for (ws, we) in spans if ws < e and s < we)

    for qid, spans in by_q.items():
        base = contention(spans, start, end)
        if base == 0:
            continue
        best = None
        for d in range(-max_shift, max_shift + 1):
            if d == 0:
                continue
            s = start + timedelta(days=d)
            e = s + timedelta(days=length)
            c = contention(spans, s, e)
            if c < base and (best is None or c < best["count"]
                             or (c == best["count"] and abs(d) < abs(best["shift"]))):
                best = {"start": s, "end": e, "count": c, "shift": d}
        if best:
            out[qid] = {"base": base, "best": best}
    return out


def wish_alternatives(period, member, wishes, *, max_shift: int = 2) -> dict:
    """Unverbindliche Entzerrungs-Hinweise JE eingetragenem Wunsch (P2.4-Erweiterung,
    ADR 0064): zeigt für umkämpfte Wünsche, wie sich Konflikte mit Wünschen
    ANDERER Mitglieder vermeiden lassen – auf zwei Wegen:

      * ``time``    – dieselbe Unterkunft, leicht verschobener Zeitraum (gleiche
                      Länge, ±``max_shift`` Tage) mit weniger/keiner Konkurrenz,
      * ``quarter`` – ein **gleichwertiges** Quartier (gleiche Äquivalenzklasse) zur
                      GLEICHEN Zeit mit weniger/keiner Konkurrenz.

    „Konflikt" = ein eingereichter Wunsch eines ANDEREN Mitglieds, der sich mit
    diesem Quartier+Zeitraum überschneidet (eigene Wünsche zählen NICHT). Nur
    Hinweise – kein Schreibpfad, keine Änderung am Losverfahren. Effizient: EINE
    Abfrage für die Konkurrenz, EINE für die Quartiere; der Rest läuft in Python.
    Gibt ``{wish_id: {"base", "time"|None, "quarter"|None}}`` für umkämpfte Wünsche
    zurück (umkämpft = mindestens ein fremder Wunsch überschneidet sich)."""
    out: dict = {}
    if not period or not member or not wishes:
        return out
    rows = (Wish.objects.filter(period=period, submitted=True)
            .exclude(member_id=member.id)
            .values_list("quarter_id", "start", "end"))
    by_q: dict[int, list] = defaultdict(list)
    for qid, ws, we in rows:
        by_q[qid].append((ws, we))

    quarters = list(Quarter.objects.filter(active=True))
    q_by_id = {q.id: q for q in quarters}
    siblings: dict[int, list] = defaultdict(list)
    for q in quarters:
        siblings[q.eq_class_id].append(q)

    def contention(spans, s, e) -> int:
        return sum(1 for (ws, we) in spans if ws < e and s < we)

    for w in wishes:
        q = q_by_id.get(w.quarter_id)
        if q is None:
            continue
        length = (w.end - w.start).days
        base = contention(by_q.get(w.quarter_id, ()), w.start, w.end)
        if base <= 0:
            continue                      # nicht umkämpft -> kein Hinweis
        # (a) gleiche Unterkunft, leicht anderer Zeitraum (saison-gültig)
        time_alt = None
        for d in range(-max_shift, max_shift + 1):
            if d == 0:
                continue
            s = w.start + timedelta(days=d)
            e = s + timedelta(days=length)
            if not _in_season_range(q, s, e):
                continue
            c = contention(by_q.get(w.quarter_id, ()), s, e)
            if c < base and (time_alt is None or c < time_alt["count"]
                             or (c == time_alt["count"] and abs(d) < abs(time_alt["shift"]))):
                time_alt = {"start": s, "end": e, "count": c, "shift": d}
        # (b) gleichwertiges Quartier (gleiche Klasse), GLEICHE Zeit (saison-gültig)
        quarter_alt = None
        for sib in siblings.get(q.eq_class_id, ()):
            if sib.id == q.id or not _in_season_range(sib, w.start, w.end):
                continue
            c = contention(by_q.get(sib.id, ()), w.start, w.end)
            if c < base and (quarter_alt is None or c < quarter_alt["count"]
                             or (c == quarter_alt["count"] and sib.name < quarter_alt["name"])):
                quarter_alt = {"quarter_id": sib.id, "name": sib.name, "count": c}
        if time_alt or quarter_alt:
            out[w.id] = {"base": base, "time": time_alt, "quarter": quarter_alt}
    return out


def day_detail(member, day: date, management: bool = False) -> dict:
    """Tagesdetail, klar getrennt nach **Anreise / Abreise / Anwesenheit** – der
    Standard professioneller Buchungssysteme (Arrivals/Departures/Stayovers).

    `management=True` (Verwaltung/BL, #47): bei externen Gästen zusätzlich
    **Klartext-Name + Kontakt (E-Mail)** und je Abreise der Endreinigungs-Status
    (#46b/#46c). Mitglieder sehen externe Gäste weiterhin nur als „extern".

    Klassifikation je Buchung am Tag (Abreisetag = `end`, checkout-exklusiv):
      • `start == day`  → **Anreise** (kommt an, ist die Nacht da)
      • `end == day`    → **Abreise** (reist ab, war die Nacht davor da)
      • sonst           → **anwesend** (bleibt). Eine Buchung ist an einem Tag
        immer genau eines davon (mind. 1 Nacht).
    `occupied` (Rückwärtskompatibilität) = Anreisen + Anwesende = wer die Nacht da
    ist. Effizient: eine Query je Quelle über die Tageskante, kein N+1."""
    from .dashboard import _annotate_cleaning
    nxt = day + timedelta(days=1)
    own = member.id if member else None
    arrivals, departures, present = [], [], []

    allocs = _annotate_cleaning(
        Allocation.objects.select_related("quarter", "member")
        .filter(start__lte=day, end__gte=day, provisional=False)
        .order_by("quarter__sort_order", "quarter__name"))
    for a in allocs:
        row = {"quarter": a.quarter.name, "who": a.member.display_name,
               "persons": a.persons, "mine": a.member_id == own,
               "external": False, "contact": "",
               "has_cleaning": bool(getattr(a, "has_cleaning", False))}
        (arrivals if a.start == day else
         departures if a.end == day else present).append(row)

    exts = (ExternalBooking.objects.select_related("quarter", "guest")
            .filter(status=ExternalBooking.CONFIRMED, start__lte=day, end__gte=day)
            .order_by("quarter__sort_order", "quarter__name"))
    for b in exts:
        who = b.guest.name if (management and b.guest_id) else "extern"
        contact = b.guest.email if (management and b.guest_id) else ""
        row = {"quarter": b.quarter.name, "who": who, "persons": b.persons,
               "mine": False, "external": True, "contact": contact,
               "has_cleaning": True}   # externe Buchung enthält die Endreinigung
        (arrivals if b.start == day else
         departures if b.end == day else present).append(row)

    free, _occ = split_quarters_for_range(day, nxt)
    return {
        "day": day, "arrivals": arrivals, "departures": departures,
        "present": present, "occupied": arrivals + present,
        "free": [q.name for q in free],
    }


def build_member_calendar(member: Member, year: int, month: int) -> dict:
    """Baut die Monatsmatrix (Wochen × 7 Tage) mit Ferien- und Buchungs-Infos.

    Rückgabe enthält die Wochen, die Monatsbezeichnung und die Navigations-
    Ziele (Vor-/Folgemonat)."""
    cal = _calendar.Calendar(firstweekday=0)  # Montag zuerst
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    hols = school_holidays_in_range(first, last + timedelta(days=1))
    allocs = []
    if member:
        allocs = list(
            member.allocations.select_related("quarter").filter(
                start__lte=last, end__gt=first,
            )
        )
    today = date.today()

    grid = []
    for week in weeks:
        row = []
        for d in week:
            holiday = next((h.name for h in hols if h.start <= d < h.end), None)
            day_allocs = [a for a in allocs if a.start <= d < a.end]
            row.append({
                "date": d,
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "holiday": holiday,
                "allocations": day_allocs,
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "weeks": grid,
        "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year,
        "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
    }


def build_community_calendar(member, year, month) -> dict:
    """Monatsmatrix mit ALLEN Buchungen der Gemeinschaft (wer ist wann wo).
    Die eigenen Buchungen des angemeldeten Mitglieds werden markiert."""
    cal = _calendar.Calendar(firstweekday=0)  # Montag zuerst
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    allocs = list(
        Allocation.objects.select_related("quarter", "member").filter(
            start__lte=last, end__gt=first, provisional=False,
        ).order_by("quarter__name")
    )
    # Externe Gäste werden in EINER neutralen Farbe und nur als „extern“ gezeigt
    # (keine Gastdaten in der Mitglieder-Übersicht).
    externals = list(
        ExternalBooking.objects.select_related("quarter").filter(
            status=ExternalBooking.CONFIRMED, start__lte=last, end__gt=first,
        ).order_by("quarter__name")
    )
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    own_id = member.id if member else None
    today = date.today()
    any_external = False

    grid = []
    for week in weeks:
        row = []
        for d in week:
            holiday = next((h.name for h in hols if h.start <= d < h.end), None)
            bookings = [
                {
                    "quarter": a.quarter.name,
                    "who": a.member.display_name,
                    "persons": a.persons,
                    "member_id": a.member_id,
                    "mine": a.member_id == own_id,
                }
                for a in allocs if a.start <= d < a.end
            ]
            for b in externals:
                if b.start <= d < b.end:
                    any_external = True
                    bookings.append({
                        "quarter": b.quarter.name, "who": "extern",
                        "persons": b.persons, "member_id": None,
                        "mine": False, "external": True, "color": EXTERN_COLOR,
                    })
            row.append({
                "date": d,
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "is_weekend": d.weekday() >= 5,
                "holiday": holiday,
                "bookings": bookings,
                "has_mine": any(b["mine"] for b in bookings),
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return {
        "weeks": grid,
        "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year,
        "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "holidays": hols,
        "any_external": any_external,
        "extern_color": EXTERN_COLOR,
    }


def build_occupancy_timeline(member, year, month) -> dict:
    """Belegungs-Zeitstrahl: pro Quartier EINE Zeile, jede Buchung als Balken über
    die Tage des Monats (Anreise→Abreise). Beantwortet „von wann bis wann ist wer
    in welcher Unterkunft" auf einen Blick. Nutzt dieselben Daten wie die
    Monatsmatrix (keine zusätzlichen Buchungs-Queries pro Tag)."""
    days_in_month = _calendar.monthrange(year, month)[1]
    m_first = date(year, month, 1)
    m_end = m_first + timedelta(days=days_in_month)   # exklusiv
    today = date.today()
    hols = school_holidays_in_range(m_first, m_end)

    days = []
    for i in range(days_in_month):
        d = m_first + timedelta(days=i)
        days.append({
            "date": d, "day": d.day, "is_today": d == today,
            "is_weekend": d.weekday() >= 5,
            "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
        })

    allocs = list(Allocation.objects.select_related("quarter", "member").filter(
        start__lt=m_end, end__gt=m_first, provisional=False).order_by("start"))
    externals = list(ExternalBooking.objects.select_related("quarter").filter(
        status=ExternalBooking.CONFIRMED, start__lt=m_end, end__gt=m_first
    ).order_by("start"))
    own_id = member.id if member else None
    quarters = list(Quarter.objects.order_by("name"))
    by_q: dict[int, list] = {q.id: [] for q in quarters}
    any_external = False

    def add_bar(qid, start, end, who, member_id, persons, external, mine):
        cs = max(start, m_first)
        ce = min(end, m_end)
        span = (ce - cs).days
        if span <= 0:
            return
        by_q.setdefault(qid, []).append({
            "who": who, "member_id": member_id, "persons": persons,
            "external": external, "mine": mine,
            "col": (cs - m_first).days + 1, "span": span,   # 1-basierter Tag
            "start": cs, "end": ce,
        })

    for a in allocs:
        add_bar(a.quarter_id, a.start, a.end, a.member.display_name, a.member_id,
                a.persons, False, a.member_id == own_id)
    for b in externals:
        any_external = True
        add_bar(b.quarter_id, b.start, b.end, "extern", None, b.persons, True, False)

    rows = [{"quarter": q, "bars": by_q.get(q.id, [])} for q in quarters]
    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "days": days, "rows": rows, "days_in_month": days_in_month,
        "label": f"{GERMAN_MONTHS[month]} {year}", "year": year, "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
        "any_external": any_external, "extern_color": EXTERN_COLOR,
    }


def build_external_calendar(year: int, month: int, cfg=None) -> dict:
    """Öffentlicher Monatskalender für externe Gäste: je Tag nur GRÜN (für Externe
    buchbar) oder GRAU (nicht verfügbar) – ohne preiszugeben, wer da ist.

    „Buchbar“ heißt: mindestens ein für Externe freigegebenes Quartier ist an dem
    Tag frei, der Tag ist ein erlaubter Übernachtungs-Wochentag, liegt im Vorlauf-/
    Horizont-Fenster und in der Quartier-Saison."""
    cfg = cfg or ExternalConfig.get_solo()
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]
    today = date.today()

    quarters = list(Quarter.objects.filter(active=True, external_bookable=True))
    occupied = _occupied_days_by_quarter(first, last)
    wd_ok = cfg.allowed_weekday_set
    horizon = cfg.horizon_days

    grid = []
    for week in weeks:
        row = []
        for d in week:
            lead = (d - today).days
            day_ok = (
                cfg.active and d >= today and lead >= cfg.lead_days
                and (not horizon or lead <= horizon)
                and (not wd_ok or d.weekday() in wd_ok)
                and any(q.bookable_on(d) and d not in occupied[str(q.id)]
                        for q in quarters)
            )
            row.append({
                "date": d, "day": d.day, "iso": d.isoformat(),
                "in_month": d.month == month,
                "is_today": d == today, "is_weekend": d.weekday() >= 5,
                "is_past": d < today,
                "available": bool(day_ok),
            })
        grid.append(row)

    prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "weeks": grid, "label": f"{GERMAN_MONTHS[month]} {year}",
        "year": year, "month": month,
        "prev": {"year": prev_month[0], "month": prev_month[1]},
        "next": {"year": next_month[0], "month": next_month[1]},
    }
