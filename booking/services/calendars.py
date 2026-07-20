"""Service-Layer (calendars): Kalender-Aufbau (Buchen/Wunsch/Community/Belegung/Extern) und Tagesdetail.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

import calendar as _calendar
from collections import defaultdict
from datetime import date, timedelta
from .. import availability as A
from .. import popularity as POP
from ..models import (
    Allocation, ExternalBooking, ExternalConfig, Member, Quarter, QuarterBlock,
    Wish,
)
from .dates import (EXTERN_COLOR, GERMAN_MONTHS, MONTHS_DE, next_month,
                    school_holidays_in_range)
from .slots import (_active_windows, _in_season_range, _occupied_days_by_quarter,
                    split_quarters_for_range)

__all__ = [
    'build_booking_calendar', 'build_wish_calendar', 'quarter_wish_counts',
    'class_popularity_for_range',
    'wish_deconfliction', 'wish_alternatives', 'wish_demand_grid', 'wish_demand_ranking',
    'capture_wish_snapshots',
    'day_detail', 'build_member_calendar', 'build_community_calendar',
    'build_occupancy_timeline', 'build_plan_print', 'build_external_calendar', 'week_agenda',
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
    """Monatsmatrix für die Wunschliste mit Ampel nach **Beliebtheit relativ zur
    Kapazität** (ADR 0103, P0a) – statt roher Nachfrage:

      free  (grün)     – frei (keine überschneidenden Wünsche)
      many  (hellgrün) – etwas gefragt (Nachfrage < Kapazität der Klasse)
      few   (gelb)     – beliebt (Nachfrage ≈ Kapazität)
      full  (rot)      – sehr beliebt (Nachfrage ≫ Kapazität)

    Gemessen **je Äquivalenzklasse** (die Losung weicht auf gleichwertige Quartiere
    aus, ADR 0003): je Tag bestimmt die **knappste** Klasse das Signal
    (`popularity_band` × `worse_band`), Kapazität = Zahl der in diesem Fenster buchbaren
    gleichwertigen Quartiere. Reine Anzeige – die Losung bleibt unberührt. Eigene
    Wünsche werden markiert (`own_sub`).
    """
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]

    # Quartiere je Äquivalenzklasse (für kapazitätsrelative Beliebtheit). Wenige
    # Dutzend Objekte, einmal geladen; `bookable_on` nutzt die Saison-Felder.
    q_class: dict = {}
    q_by_class: dict = defaultdict(list)
    for q in Quarter.objects.filter(active=True):
        q_class[q.id] = q.eq_class_id
        q_by_class[q.eq_class_id].append(q)
    all_wishes, own = [], []
    if period:
        all_wishes = list(Wish.objects.filter(
            period=period, start__lte=last, end__gt=first))
        if member:
            own = list(Wish.objects.filter(
                period=period, member=member, start__lte=last, end__gt=first))
    hols = school_holidays_in_range(first, last + timedelta(days=1))
    today = date.today()
    free_band = POP.popularity_band(0, 0)

    grid = []
    for week in weeks:
        row = []
        for d in week:
            # Überschneidende Wünsche je Klasse an diesem Tag …
            cls_overlap: dict = defaultdict(int)
            for w in all_wishes:
                if w.start <= d < w.end:
                    cls = q_class.get(w.quarter_id)
                    if cls is not None:
                        cls_overlap[cls] += 1
            # … Beliebtheit je Klasse relativ zur an diesem Tag buchbaren Kapazität;
            # die knappste Klasse bestimmt die Tages-Ampel (positiv, ADR 0072).
            band = free_band
            demand = 0
            for cls, ov in cls_overlap.items():
                demand += ov
                cap = sum(1 for q in q_by_class.get(cls, []) if q.bookable_on(d))
                band = POP.worse_band(band, POP.popularity_band(ov, cap))
            level = band["tone"]
            # Wünsche sind ab dem Eintragen verbindlich (kein Entwurf mehr): jeder
            # eigene Wunsch ist markiert (own_sub).
            own_sub = any(w.start <= d < w.end for w in own)
            in_range = bool(
                sel_start and ((sel_end and sel_start <= d < sel_end)
                               or (not sel_end and d == sel_start)))
            row.append({
                "date": d, "iso": d.isoformat(), "day": d.day,
                "in_month": d.month == month, "is_today": d == today,
                "is_weekend": d.weekday() >= 5, "is_past": d < today,
                "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
                "level": level, "demand": demand, "band": band["label"],
                "own_sub": own_sub,
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
        period=period, start__lt=end, end__gt=start,
    ):
        counts[str(w.quarter_id)] += 1
    return counts


def class_popularity_for_range(period, start: date, end: date) -> dict:
    """Beliebtheits-Band **je Quartier** für den Zeitraum [start, end) – kapazitäts-
    relativ auf Ebene der **Äquivalenzklasse** (ADR 0103, P0b): überschneidende Wünsche
    der Klasse gegen die Zahl der (im Fenster) buchbaren gleichwertigen Quartiere. Ein
    Quartier erbt das Band seiner Klasse. Reine Anzeige (kein Los-Eingriff).

    Gibt ``{str(quarter_id): {"key","label","tone"}}`` für alle aktiven Quartiere."""
    out: dict = {}
    if not period or end <= start:
        return out
    q_class: dict = {}
    q_by_class: dict = defaultdict(list)
    for q in Quarter.objects.filter(active=True):
        q_class[q.id] = q.eq_class_id
        q_by_class[q.eq_class_id].append(q)
    cls_overlap: dict = defaultdict(int)
    for qid, ws, we in Wish.objects.filter(
            period=period, start__lt=end, end__gt=start,
    ).values_list("quarter_id", "start", "end"):
        cls = q_class.get(qid)
        if cls is not None:
            cls_overlap[cls] += 1
    free = POP.popularity_band(0, 0)
    band_by_class = {
        cls: POP.popularity_band(
            ov, sum(1 for q in q_by_class.get(cls, []) if q.bookable_on(start)))
        for cls, ov in cls_overlap.items()}
    for qid, cls in q_class.items():
        out[str(qid)] = band_by_class.get(cls, free)
    return out


def wish_demand_grid(period) -> dict:
    """**Nachfrage-Heatmap** (ADR 0101): je Quartier (Zeile) × **Monat** (Spalte) die
    Zahl der **eingetragenen** Wünsche, die den Monat berühren – zeigt auf einen Blick
    die begehrten Quartiere/Zeiten. Nur Aggregat-Zahlen (keine Namen; wer wo wünscht,
    steht je Wunsch unter „Details & Aktionen", ADR 0101 Batch 2). Eine Wunsch-Abfrage,
    Rest in Python.

    Gibt `{"rows": [{quarter, cells:[{count,pct}×12]}], "months": [kurz], "max": n}`."""
    from ..models import Quarter
    empty = {"rows": [], "months": [], "max": 0}
    if not period:
        return empty
    year = period.target_year
    bounds = [(date(year, m, 1),
               date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1))
              for m in range(1, 13)]
    quarters = list(Quarter.objects.filter(active=True).order_by("sort_order", "name"))
    qidx = {q.id: i for i, q in enumerate(quarters)}
    grid = [[0] * 12 for _ in quarters]
    for qid, ws, we in Wish.objects.filter(
            period=period).values_list("quarter_id", "start", "end"):
        i = qidx.get(qid)
        if i is None:
            continue
        for j, (ms, me) in enumerate(bounds):
            if ws < me and we > ms:
                grid[i][j] += 1
    mx = max((c for row in grid for c in row), default=0)
    rows = [{
        "quarter": q.name,
        "total": sum(grid[i]),
        "cells": [{"count": grid[i][j],
                   "pct": round(100 * grid[i][j] / mx) if mx else 0}
                  for j in range(12)],
    } for i, q in enumerate(quarters)]
    months = [MONTHS_DE[m][:3] for m in range(1, 13)]
    return {"rows": rows, "months": months, "max": mx}


def wish_demand_ranking(period, *, top: int = 8) -> dict:
    """Beliebteste **Unterkünfte** und **Zeiträume** für die Nachfrage-Ansicht
    (ADR 0101 Batch 2-Nachtrag, Feedback e): tabellarische Ranglisten aus den
    eingetragenen Wünschen. Nutzt das Heatmap-Raster (eine Wunsch-Abfrage) und rankt
    daraus – nur Aggregate, keine Namen.

    Gibt `{"quarters": [{name,count}], "slots": [{quarter,month,count}]}`."""
    grid = wish_demand_grid(period) if period else {"rows": [], "months": []}
    quarters = sorted(
        ({"name": r["quarter"], "count": r["total"]}
         for r in grid["rows"] if r["total"]),
        key=lambda x: (-x["count"], x["name"]))[:top]
    slots = []
    for r in grid["rows"]:
        for j, cell in enumerate(r["cells"]):
            if cell["count"]:
                slots.append({"quarter": r["quarter"],
                              "month": grid["months"][j], "count": cell["count"]})
    slots.sort(key=lambda x: (-x["count"], x["quarter"]))
    return {"quarters": quarters, "slots": slots[:top]}


def capture_wish_snapshots(period, now) -> bool:
    """Hält die **Nachfrage-Snapshots** der Entzerrungsphase fest (ADR 0101), idempotent
    und vom Scheduler je Lauf aufgerufen:

    * ab `review_open` den **„vor"-Stand** (Heatmap-Raster **+** Wunschzeilen für den
      Export „vor der Entzerrung"),
    * ab `freeze_start` die **eingefrorene Anzeige** (Heatmap-Raster der letzten Stunden).

    Beide werden je Periode **genau einmal** gespeichert. Gibt True zurück, wenn etwas
    Neues gespeichert wurde."""
    if not period or not period.draw_at:
        return False
    snap = dict(period.demand_snapshot or {})
    changed = False
    ro = period.review_open
    if ro and (now.date() if hasattr(now, "date") else now) >= ro \
            and "review_open" not in snap:
        from .wishes import wish_export_rows
        snap["review_open"] = {"grid": wish_demand_grid(period),
                               "rows": wish_export_rows(period)}
        changed = True
    fs = period.freeze_start
    if fs and now >= fs and "frozen" not in snap:
        snap["frozen"] = {"grid": wish_demand_grid(period), "at": now.isoformat()}
        changed = True
    if changed:
        period.demand_snapshot = snap
        period.save(update_fields=["demand_snapshot"])
    return changed


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
        period=period, start__lt=win_e, end__gt=win_s,
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
    rows = (Wish.objects.filter(period=period)
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


GERMAN_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
ALLOWED_TIMELINE_SPANS = (7, 14, 28)


def build_occupancy_timeline(member, anchor: date, span_days: int = 14,
                             management: bool = False) -> dict:
    """Belegungsplan als **Tape-Chart** (Industriestandard, an beds24 angelehnt,
    ADR 0083): Unterkünfte als Zeilen (nach `sort_order`, in Gebäude-Bänder
    gruppiert, #38/#42), eine **durchgehende Datumsachse** ab `anchor` über
    `span_days` Tage (#41 – kein Monatsraster mehr), Buchungen als Balken.

    **Wechseltag als Halbtag (#40):** je Tag ZWEI Sub-Spalten. Ein Balken beginnt
    an der PM-Kante des Anreisetags und endet an der AM-Kante des Abreisetags –
    Ab- und Anreise am selben Tag treffen sich so an der Tagesmitte statt sich zu
    überlappen (keine Schein-Doppelbelegung). Grid-Linien 1..(2·span_days+1).

    `management=True` (Verwaltung/BL, #46b): externe Gäste mit Klartext-Name +
    Personen; Mitglieder sehen nur „extern". Der Endreinigungs-Status je
    Mitglieder-Buchung (🧹, #46c) kommt über die `has_cleaning`-Annotation.

    Eine Query je Quelle (Allocation/ExternalBooking) über das Fenster – kein N+1.
    """
    from .dashboard import _annotate_cleaning
    span_days = span_days if span_days in ALLOWED_TIMELINE_SPANS else 14
    win_end = anchor + timedelta(days=span_days)      # exklusiv
    today = date.today()
    hols = school_holidays_in_range(anchor, win_end)
    own_id = member.id if member else None

    days = []
    for i in range(span_days):
        d = anchor + timedelta(days=i)
        days.append({
            "idx": i, "date": d, "day": d.day, "wd": GERMAN_WEEKDAYS[d.weekday()],
            "is_today": d == today, "is_weekend": d.weekday() >= 5,
            "first_of_month": d.day == 1,
            "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
        })

    quarters = list(Quarter.objects.filter(active=True).order_by("sort_order", "name"))
    allocs = list(_annotate_cleaning(
        Allocation.objects.select_related("quarter", "member").filter(
            start__lt=win_end, end__gt=anchor, provisional=False)).order_by("start"))
    externals = list(ExternalBooking.objects.select_related("quarter", "guest").filter(
        status=ExternalBooking.CONFIRMED, start__lt=win_end, end__gt=anchor
    ).order_by("start"))
    blocks = list(QuarterBlock.objects.filter(
        start__lt=win_end, end__gt=anchor).order_by("start"))

    by_q: dict[int, list] = {q.id: [] for q in quarters}
    occ_sets = [set() for _ in range(span_days)]   # belegte Quartiere je Tag → frei-Zahl
    any_external = False

    def add_bar(qid, start, end, who, member_id, persons, external, mine, cleaning,
                blocked=False):
        a = (start - anchor).days                  # Anreise-Offset (kann < 0 sein)
        c = (end - anchor).days                    # Abreise-Offset (kann > span sein)
        for i in range(max(a, 0), min(c, span_days)):   # Anwesenheitstage
            occ_sets[i].add(qid)
        open_l, open_r = a < 0, c > span_days
        # Sperrzeiten belegen ganze Tage (keine Halbtag-Wechsellogik).
        if blocked:
            col_start = 1 if open_l else 2 * a + 1
            col_end = (2 * span_days + 1) if open_r else 2 * c + 1
        else:
            col_start = 1 if open_l else 2 * a + 2     # PM-Kante des Anreisetags
            col_end = (2 * span_days + 1) if open_r else 2 * c + 1   # AM-Kante Abreisetag
        if col_end <= col_start:
            return
        by_q.setdefault(qid, []).append({
            "who": who, "member_id": member_id, "persons": persons,
            "external": external, "mine": mine, "has_cleaning": cleaning,
            "blocked": blocked,
            "col_start": col_start, "col_end": col_end,
            "open_left": open_l, "open_right": open_r, "start": start, "end": end,
        })

    for a in allocs:
        add_bar(a.quarter_id, a.start, a.end, a.member.display_name, a.member_id,
                a.persons, False, a.member_id == own_id,
                bool(getattr(a, "has_cleaning", False)))
    for b in externals:
        any_external = True
        who = b.guest.name if (management and b.guest_id) else "extern"
        add_bar(b.quarter_id, b.start, b.end, who, None, b.persons, True, False, False)
    for b in blocks:
        who = ("🔧 " + b.reason) if b.reason else "🔧 gesperrt"
        add_bar(b.quarter_id, b.start, b.end, who, None, 0, False, False, False,
                blocked=True)

    for d in days:
        d["free"] = len(quarters) - len(occ_sets[d["idx"]])

    # Gebäude-Bänder: fortlaufende Läufe gleichen `building` (nach sort_order), #42.
    groups: list[dict] = []
    for q in quarters:
        b = q.building or ""
        if not groups or groups[-1]["building"] != b:
            groups.append({"building": b, "rows": []})
        groups[-1]["rows"].append({"quarter": q, "bars": by_q.get(q.id, [])})

    today_idx = (today - anchor).days
    return {
        "days": days, "groups": groups, "span_days": span_days,
        "n_sub": span_days * 2, "n_quarters": len(quarters),
        "anchor": anchor, "win_last": win_end - timedelta(days=1),
        # Pfeiltasten springen bewusst genau EINE Woche (nicht das ganze Fenster),
        # freie Startwahl geht übers Datumsfeld (#Feedback BL).
        "prev": anchor - timedelta(days=7),
        "next": anchor + timedelta(days=7),
        "weeks": span_days // 7,
        "today": today,
        "today_sub": (2 * today_idx + 2) if 0 <= today_idx < span_days else None,
        "any_external": any_external, "extern_color": EXTERN_COLOR,
    }


def build_plan_print(anchor: date, span_days: int, management: bool = True) -> dict:
    """Datenaufbereitung fürs **Druck-PDF** des Belegungsplans (#39, Querformat).

    Bewusst **nacht-basiert** (jede Zelle = eine Nacht): ein sauberer
    Belegungswechsel sind damit **benachbarte Zellen** – kein Halbtags-Trick nötig,
    und die Darstellung ist als **Tabelle mit colspan-Balken** robust für WeasyPrint.
    Liefert zusätzlich die operativen Listen **Anreisen/Abreisen/Reinigung** für den
    tabellarischen Teil. Eine Query je Quelle über das Fenster (kein N+1)."""
    from .dashboard import _annotate_cleaning
    win_end = anchor + timedelta(days=span_days)
    hols = school_holidays_in_range(anchor, win_end)

    days = []
    for i in range(span_days):
        d = anchor + timedelta(days=i)
        days.append({
            "idx": i, "date": d, "day": d.day, "wd": GERMAN_WEEKDAYS[d.weekday()],
            "is_weekend": d.weekday() >= 5,
            "holiday": next((h.name for h in hols if h.start <= d < h.end), None),
        })

    quarters = list(Quarter.objects.filter(active=True).order_by("sort_order", "name"))
    allocs = list(_annotate_cleaning(
        Allocation.objects.select_related("quarter", "member").filter(
            start__lt=win_end, end__gt=anchor, provisional=False)).order_by("start"))
    externals = list(ExternalBooking.objects.select_related("quarter", "guest").filter(
        status=ExternalBooking.CONFIRMED, start__lt=win_end, end__gt=anchor
    ).order_by("start"))

    occ: dict[int, list] = {q.id: [None] * span_days for q in quarters}
    arrivals, departures = [], []

    def _mark(qid, start, end, ref):
        row = occ.setdefault(qid, [None] * span_days)
        for i in range(max((start - anchor).days, 0), min((end - anchor).days, span_days)):
            row[i] = ref

    for a in allocs:
        cleaning = bool(getattr(a, "has_cleaning", False))
        ref = {"who": a.member.display_name, "persons": a.persons,
               "external": False, "has_cleaning": cleaning}
        _mark(a.quarter_id, a.start, a.end, ref)
        if anchor <= a.start < win_end:
            arrivals.append({"date": a.start, "quarter": a.quarter.name,
                             "who": a.member.display_name, "persons": a.persons,
                             "external": False, "contact": ""})
        if anchor <= a.end < win_end:
            departures.append({"date": a.end, "quarter": a.quarter.name,
                               "who": a.member.display_name, "persons": a.persons,
                               "has_cleaning": cleaning})

    for b in externals:
        who = b.guest.name if (management and b.guest_id) else "extern"
        ref = {"who": who, "persons": b.persons, "external": True,
               "has_cleaning": False}
        _mark(b.quarter_id, b.start, b.end, ref)
        contact = b.guest.email if (management and b.guest_id) else ""
        if anchor <= b.start < win_end:
            arrivals.append({"date": b.start, "quarter": b.quarter.name, "who": who,
                             "persons": b.persons, "external": True, "contact": contact})
        if anchor <= b.end < win_end:
            departures.append({"date": b.end, "quarter": b.quarter.name, "who": who,
                               "persons": b.persons, "has_cleaning": False})

    groups: list[dict] = []
    for q in quarters:
        row = occ[q.id]
        segs, i = [], 0
        while i < span_days:
            ref = row[i]
            j = i + 1
            while j < span_days and row[j] is ref:   # gleiche Buchung (Objekt-Identität)
                j += 1
            if ref is None:
                segs.append({"kind": "free", "span": j - i})
            else:
                segs.append({"kind": "book", "span": j - i, "who": ref["who"],
                             "persons": ref["persons"], "external": ref["external"],
                             "has_cleaning": ref["has_cleaning"]})
            i = j
        b = q.building or ""
        if not groups or groups[-1]["building"] != b:
            groups.append({"building": b, "rows": []})
        groups[-1]["rows"].append({"quarter": q, "segments": segs})

    arrivals.sort(key=lambda x: (x["date"], x["quarter"]))
    departures.sort(key=lambda x: (x["date"], x["quarter"]))
    cleaning = [d for d in departures if d["has_cleaning"]]
    return {
        "days": days, "groups": groups, "span_days": span_days,
        "n_quarters": len(quarters), "anchor": anchor,
        "win_last": win_end - timedelta(days=1), "weeks": span_days // 7,
        "arrivals": arrivals, "departures": departures, "cleaning": cleaning,
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
