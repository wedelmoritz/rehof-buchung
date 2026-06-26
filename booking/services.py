"""Service-Layer: Brücke zwischen Django-Modellen und dem reinen Losmodul.

Hier liegt bewusst die gesamte Geschäftslogik, die DB und Algorithmus
verbindet – die Views bleiben dünn, das Losmodul bleibt rein.
"""
from __future__ import annotations

import calendar as _calendar
from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import availability as A
from . import lottery as L
from . import rules as R
from .external import external_allowed, cancellation_refund
from .models import (
    Allocation, BookingPeriod, BookingPolicy, ExternalBooking, ExternalConfig,
    Guest, LotteryRun, Member, NightTransfer, Notification, OutboxEmail, Quarter,
    SchoolHoliday, SeasonRule, SwapRequest, WaitlistEntry, Wish,
)


def _quarters_payload() -> list[L.Quarter]:
    return [
        L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
        for q in Quarter.objects.filter(active=True).select_related("eq_class")
    ]


@transaction.atomic
def run_period_lottery(
    period: BookingPeriod,
    *,
    seed: int,
    factor_step: float = 0.1,
    factor_cap: float = 1.5,
    reset_on_contested_win: bool = True,
) -> LotteryRun:
    """Führt die Losung für eine Periode aus, schreibt (vorläufige) Zuteilungen,
    aktualisiert die Ausgleichsfaktoren und legt einen unbestätigten Losdurchlauf
    an. Veröffentlicht wird erst über `confirm_lottery`."""
    # Bestehenden Lauf behandeln, BEVOR die Faktoren gelesen werden: ein
    # bestätigter Lauf ist tabu; ein unbestätigter wird zurückgerollt (Faktoren
    # wiederhergestellt), damit ein erneuter Lauf das Karma nicht aufsummiert.
    existing = period.runs.first()
    if existing and existing.confirmed:
        raise ValueError(
            "Die Losung dieser Periode ist bereits bestätigt und kann nicht "
            "erneut ausgeführt werden – erst zurücknehmen ist nicht möglich.")
    if existing:
        _restore_factors(existing)
        existing.delete()
    Allocation.objects.filter(period=period, source="lottery").delete()

    members = list(Member.objects.filter(is_external=False))
    quarters = list(Quarter.objects.filter(active=True))
    # Nur eingereichte Wünsche ("im Lostopf") nehmen an der Losung teil – und nur,
    # wenn das Quartier im GANZEN Wunschzeitraum saisonal buchbar ist (sonst würde
    # die Losung eine Buchung außerhalb der Quartier-Saison erzeugen).
    wishes_qs = [
        w for w in Wish.objects.filter(period=period, submitted=True)
        .select_related("member", "quarter")
        if _in_season_range(w.quarter, w.start, w.end)
    ]

    parties = [
        L.Party(
            id=str(m.id), name=m.display_name,
            factor=m.factor, wish_night_budget=m.wish_night_budget,
        )
        for m in members
    ]
    q_payload = [
        L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
        for q in quarters
    ]
    w_payload = [
        L.Wish(
            party_id=str(w.member_id), priority=w.priority,
            quarter_id=str(w.quarter_id), start=w.start, end=w.end,
        )
        for w in wishes_qs
    ]

    result = L.run_lottery(
        parties, q_payload, w_payload,
        seed=seed, factor_step=factor_step, factor_cap=factor_cap,
        reset_on_contested_win=reset_on_contested_win,
    )

    # Faktor-Stände VOR dem Lauf festhalten (für ein sauberes Rückgängigmachen).
    old_factors = {str(m.id): m.factor for m in members}

    # Vorläufige Zuteilungen (provisional=True): blockieren die Verfügbarkeit,
    # bleiben aber für Mitglieder unsichtbar, bis bestätigt wird.
    for a in result.allocations:
        Allocation.objects.create(
            member_id=int(a.party_id),
            quarter_id=int(a.quarter_id),
            start=a.start, end=a.end,
            source="lottery", period=period,
            via_substitution=a.via_substitution, contested=a.contested,
            provisional=True,
        )

    # Faktoren aktualisieren
    for m in members:
        new_f = result.new_factors.get(str(m.id))
        if new_f is not None and new_f != m.factor:
            m.factor = new_f
            m.save(update_fields=["factor"])

    # Status zunächst nur „zur Prüfung“ – Veröffentlichung erst per Bestätigung.
    period.status = BookingPeriod.LOTTERY_REVIEW
    period.seed = seed
    period.save(update_fields=["status", "seed"])

    party_names = {str(m.id): m.display_name for m in members}
    quarter_names = {str(q.id): q.name for q in quarters}

    # Benachrichtigungen NUR vorbereiten (nicht zustellen) – das übernimmt erst
    # confirm_lottery. So bekommen Mitglieder vor der Bestätigung nichts zu sehen.
    notices = _build_lottery_notices(
        period, members, result, old_factors, quarter_names)

    log_text = L.render_log_text(result, party_names, quarter_names)
    summary = (
        f"{len(result.allocations)} Zuteilungen, "
        f"{len(result.losses)} Verluste, Seed {seed}"
    )
    return LotteryRun.objects.create(
        period=period, seed=seed, log_text=log_text, summary=summary,
        karma_snapshot=old_factors, notices=notices, confirmed=False,
        n_allocations=len(result.allocations), n_losses=len(result.losses),
    )


def _restore_factors(run) -> None:
    """Setzt die Ausgleichsfaktoren auf den vor dem Lauf gemerkten Stand zurück."""
    for mid, factor in (run.karma_snapshot or {}).items():
        Member.objects.filter(id=int(mid)).update(factor=factor)


def confirm_lottery(run) -> None:
    """Bestätigt einen Losdurchlauf: macht die Zuteilungen sichtbar und stellt
    die vorbereiteten Benachrichtigungen (In-App + E-Mail) zu. Danach ist der
    Lauf nicht mehr rücknehmbar. Idempotent."""
    if run.confirmed:
        return
    period = run.period
    Allocation.objects.filter(
        period=period, source="lottery").update(provisional=False)

    url = reverse("period_result", args=[period.id])
    Notification.objects.filter(url=url).delete()  # Idempotenz
    year = period.target_year
    for n in (run.notices or []):
        member = Member.objects.filter(id=n["member_id"]).first()
        if not member:
            continue
        Notification.objects.create(
            member=member, message=n["message"], detail=n["detail"], url=url)
        body = (f"Hallo {member.display_name},\n\n{n['message']}\n\n{n['detail']}"
                f"\n\nDetails: {absolute_url(url)}\n\nViele Grüße\nRe:Hof")
        email_member(member, f"Auslosung {year}: dein Ergebnis", body)

    run.confirmed = True
    run.confirmed_at = timezone.now()
    run.save(update_fields=["confirmed", "confirmed_at"])
    period.status = BookingPeriod.LOTTERY_DONE
    period.save(update_fields=["status"])


def rollback_lottery(run) -> tuple[bool, str | None]:
    """Macht einen UNbestätigten Losdurchlauf rückgängig: löscht die vorläufigen
    Zuteilungen, stellt das Karma wieder her, setzt die Periode zurück auf
    „zur Auslosung freigegeben“ und entfernt den Lauf. Bestätigte Läufe sind
    gesperrt."""
    if run.confirmed:
        return False, "Diese Losung ist bereits bestätigt und kann nicht mehr zurückgenommen werden."
    period = run.period
    Allocation.objects.filter(
        period=period, source="lottery", provisional=True).delete()
    _restore_factors(run)
    period.status = BookingPeriod.LOTTERY_READY
    period.save(update_fields=["status"])
    run.delete()
    return True, None


def _build_lottery_notices(period, members, result, old_factors, quarter_names):
    """Baut je Teilnehmer (mit eingereichten Wünschen) den Benachrichtigungstext
    mit Gewinnen, Verlusten und Karma-Änderung – als serialisierbare Liste, die
    am Losdurchlauf gespeichert und erst bei der Bestätigung zugestellt wird."""
    wins_by: dict[str, list] = defaultdict(list)
    losses_by: dict[str, list] = defaultdict(list)
    for a in result.allocations:
        wins_by[a.party_id].append(a)
    for w in result.losses:
        losses_by[w.party_id].append(w)

    participant_ids = {
        str(mid) for mid in Wish.objects.filter(period=period, submitted=True)
        .values_list("member_id", flat=True).distinct()
    }
    year = period.target_year
    notices: list[dict] = []

    for m in members:
        pid = str(m.id)
        if pid not in participant_ids:
            continue
        wins = wins_by.get(pid, [])
        losses = losses_by.get(pid, [])
        old_f = old_factors.get(pid, m.factor)
        new_f = result.new_factors.get(pid, old_f)

        msg = (f"Auslosung {year}: {len(wins)} Wunsch/Wünsche bekommen, "
               f"{len(losses)} leider nicht.")
        lines: list[str] = []
        if wins:
            lines.append("Du hast bekommen:")
            for a in wins:
                qn = quarter_names.get(a.quarter_id, a.quarter_id)
                sub = " (gleichwertiges Ausweichquartier)" if a.via_substitution else ""
                lines.append(f"  ✓ {qn} {a.start:%d.%m.%Y}–{a.end:%d.%m.%Y}{sub}")
        if losses:
            lines.append("Es tut uns leid – diese Wünsche waren nicht erfüllbar:")
            for w in losses:
                qn = quarter_names.get(w.quarter_id, w.quarter_id)
                lines.append(f"  ✗ {qn} {w.start:%d.%m.%Y}–{w.end:%d.%m.%Y}")
        if new_f > old_f:
            lines.append(
                f"Als Ausgleich steigt dein Ausgleichsfaktor um "
                f"+{round(new_f - old_f, 1)} auf {round(new_f, 1)} – damit hast du "
                f"bei der nächsten Auslosung bessere Chancen auf einen vorderen Platz.")
        elif new_f < old_f:
            lines.append(
                f"Dein Ausgleichsfaktor wurde nach dem Gewinn eines umkämpften "
                f"Wunsches auf {round(new_f, 1)} zurückgesetzt.")
        notices.append({
            "member_id": m.id, "message": msg, "detail": "\n".join(lines),
        })
    return notices


def _external_blocking_qs(quarter: Quarter, start: date, end: date):
    """Externe Buchungen, die [start, end) für `quarter` blockieren."""
    return ExternalBooking.objects.filter(
        quarter=quarter, status=ExternalBooking.CONFIRMED,
        start__lt=end, end__gt=start)


def quarter_is_free(quarter: Quarter, start: date, end: date) -> bool:
    """Prüft, ob ein Quartier im Zeitraum [start, end) komplett frei ist –
    berücksichtigt Mitglieder-Zuteilungen UND bestätigte externe Buchungen."""
    if Allocation.objects.filter(
            quarter=quarter, start__lt=end, end__gt=start).exists():
        return False
    return not _external_blocking_qs(quarter, start, end).exists()


def find_gaps(
    quarter: Quarter, window_start: date, window_end: date,
    min_nights: int = 1,
) -> list[tuple[date, date]]:
    """Findet freie Lücken eines Quartiers im Fenster [window_start, window_end)."""
    intervals = [
        (a.start, a.end) for a in Allocation.objects.filter(
            quarter=quarter, start__lt=window_end, end__gt=window_start)]
    intervals += [(b.start, b.end)
                  for b in _external_blocking_qs(quarter, window_start, window_end)]
    intervals.sort()
    gaps: list[tuple[date, date]] = []
    cursor = window_start
    for a_start0, a_end0 in intervals:
        a_start = max(a_start0, window_start)
        if a_start > cursor:
            if (a_start - cursor).days >= min_nights:
                gaps.append((cursor, a_start))
        cursor = max(cursor, min(a_end0, window_end))
    if cursor < window_end and (window_end - cursor).days >= min_nights:
        gaps.append((cursor, window_end))
    return gaps


@transaction.atomic
def book_spontaneous(
    member: Member, quarter: Quarter, start: date, end: date,
    persons: int = 1, source: str = "spontaneous", companions: str = "",
) -> tuple[Allocation | None, str | None]:
    """Bucht eine freie Lücke mit den verfügbaren Tagen. Gibt
    (Allocation, None) bei Erfolg zurück bzw. (None, Fehlermeldung) sonst.

    Geprüft wird in dieser Reihenfolge:
      1. gültiger Zeitraum,
      2. Personenzahl passt zur Belegung des Quartiers,
      3. liegt vollständig in einem freigeschalteten Buchungszeitraum,
      4. Quartier ist frei,
      5. genügend verfügbare Tage (inkl. erhaltener/abgegebener) im Jahr.
    """
    nights = (end - start).days
    if nights <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    persons = int(persons or 0)
    if persons < quarter.min_occupancy or persons > quarter.max_occupancy:
        return None, (f"{quarter.name} ist für {quarter.min_occupancy}–"
                      f"{quarter.max_occupancy} Personen ausgelegt "
                      f"(angegeben: {persons}).")
    if not range_is_released(quarter, start, end):
        return None, ("Dieser Zeitraum ist (noch) nicht zur Buchung "
                      "freigeschaltet.")
    # Gegen Doppelbuchung bei gleichzeitigen Anfragen: die Quartier-Zeile sperren,
    # damit Buchungen DESSELBEN Quartiers serialisiert werden (andere Quartiere
    # laufen weiter parallel). Die Belegungsprüfung danach sieht dann eine evtl.
    # gerade zuvor angelegte Buchung. (Unter SQLite ein No-Op – nur für Tests.)
    Quarter.objects.select_for_update().filter(pk=quarter.pk).first()
    if not quarter_is_free(quarter, start, end):
        return None, "Das Quartier ist in diesem Zeitraum bereits belegt."
    if member.nights_remaining_in_year(start.year) < nights:
        return None, ("Nicht genügend verfügbare Tage für diesen Zeitraum "
                      f"({member.nights_remaining_in_year(start.year)} übrig, "
                      f"{nights} benötigt).")
    # Saison-Regeln: Mindestnächte, Parallel-Limit, Aufenthaltsdeckel
    rule_error = check_booking_rules(member, start, end)
    if rule_error:
        return None, rule_error
    alloc = Allocation.objects.create(
        member=member, quarter=quarter, start=start, end=end,
        persons=persons, source=source, companions=companions.strip()[:255],
    )
    return alloc, None


# --------------------------------------------------------------------------- #
# Saison-/Sonderregeln (Mindestnächte, Parallel-Limit, Aufenthaltsdeckel)
# --------------------------------------------------------------------------- #

def _materialized_seasons(span_start: date, span_end: date) -> list[R.Season]:
    """Materialisiert die jährlich wiederkehrenden Regeln (Saison-Regeln und
    aktive Schulferien mit Regelfeldern) zu konkreten Zeiträumen, die [span_start,
    span_end) berühren. So bleibt die reine Logik in rules.py datumsbasiert."""
    out: list[R.Season] = []
    years = range(span_start.year - 1, span_end.year + 1)

    def add(name, sm, sd, em, ed, mn, mp, ms):
        for y in years:
            s, e = A.recurring_range(sm, sd, em, ed, y)
            if s < span_end and e > span_start:
                out.append(R.Season(
                    name=name, start=s, end=e, min_nights=mn,
                    max_parallel_units=mp, max_stay_nights=ms, active=True,
                ))

    for r in SeasonRule.objects.filter(active=True):
        add(r.name, r.start_month, r.start_day, r.end_month, r.end_day,
            r.min_nights, r.max_parallel_units, r.max_stay_nights)
    for h in SchoolHoliday.objects.filter(active=True):
        # Nur Schulferien mit mindestens einer gesetzten Regel wirken sich aus.
        if h.min_nights is None and h.max_parallel_units is None \
                and h.max_stay_nights is None:
            continue
        add(h.name, h.start_month, h.start_day, h.end_month, h.end_day,
            h.min_nights, h.max_parallel_units, h.max_stay_nights)
    return out


def check_booking_rules(
    member: Member, start: date, end: date,
) -> str | None:
    """Prüft eine geplante Buchung gegen die globalen + saisonalen Regeln
    (inkl. regelsetzender Schulferien). Gibt einen Fehlertext zurück oder None."""
    policy = BookingPolicy.get_solo()
    existing = [
        R.Stay(start=a.start, end=a.end) for a in member.allocations.all()
    ]
    return R.validate_booking(
        _materialized_seasons(start, end), policy.default_min_nights,
        start, end, existing,
    )


def schedule_blocker(
    member: Member, start: date, end: date,
) -> str | None:
    """Grund, warum der Zeitraum (Termin/Regeln/Budget) NICHT buchbar ist –
    ohne Personenzahl- und Belegungsprüfung. Quartiers-unabhängig, daher pro
    Auswahl nur EINMAL berechnen (nicht je Kandidat). Für die Vorab-Anzeige."""
    nights = (end - start).days
    if nights <= 0:
        return "Ungültiger Zeitraum."
    remaining = member.nights_remaining_in_year(start.year)
    if remaining < nights:
        return f"Nicht genügend Tage ({remaining} übrig, {nights} benötigt)."
    return check_booking_rules(member, start, end)


def season_min_nights(start: date, end: date) -> int:
    """Strengste Saison-Mindestnächte (SeasonRule/Schulferien) für [start, end) –
    OHNE den globalen Standard. 0, wenn keine Saison-Regel greift. Wird für externe
    Gäste genutzt: deren eigener Mindestaufenthalt steht separat in der
    ExternalConfig, die Saison-Mindestnächte gelten zusätzlich (das strengere zählt)."""
    required = 0
    for s in _materialized_seasons(start, end):
        if s.min_nights and s.start < end and s.end > start:
            required = max(required, s.min_nights)
    return required


def min_nights_for_range(start: date, end: date) -> int:
    """Effektiver Mindestaufenthalt für [start, end): Standard-Mindestnächte,
    verschärft durch überlappende Saison-/Schulferien-Regeln."""
    return max(BookingPolicy.get_solo().default_min_nights or 0,
               season_min_nights(start, end))


def wish_rule_error(start: date, end: date) -> str | None:
    """Saison-Regeln für einen EINZELNEN Wunsch: Mindestnächte (Standard + Saison)
    und der Aufenthaltsdeckel als Obergrenze einer einzelnen Buchung. Das
    **Parallel-Limit** betrifft mehrere gleichzeitige Buchungen und ist je Einzel-
    wunsch nicht prüfbar; es wird in der Losung bewusst nicht erzwungen (Beschluss:
    Saison-Regeln nur beim Eintragen/Einreichen der Wunschliste prüfen, der Los-
    Algorithmus bleibt unverändert). Gibt einen Fehlertext zurück oder None."""
    policy = BookingPolicy.get_solo()
    # Leere „existing"-Liste: prüft Mindestnächte + Einzel-Deckel, nicht das
    # (cross-buchungs-)Parallel-Limit.
    return R.validate_booking(
        _materialized_seasons(start, end), policy.default_min_nights,
        start, end, [],
    )


# --------------------------------------------------------------------------- #
# Freigeschaltete Buchungszeiträume (Perioden im Status "Freie Bebuchbarkeit")
# --------------------------------------------------------------------------- #

def _active_windows() -> list[A.Window]:
    """Lädt die zur freien Buchung freigegebenen Perioden als reine Window-
    Objekte. Buchbar ist ein Tag nur innerhalb einer Periode im Status
    „Freie Bebuchbarkeit innerhalb Zeitraum“."""
    out: list[A.Window] = []
    for p in BookingPeriod.objects.filter(status=BookingPeriod.FREE_BOOKING):
        # Genau eine Periode pro Jahr, immer global. Quartiersspezifische
        # Grenzen kommen aus der Quartier-Saison (siehe range_is_released).
        out.append(A.Window(
            start=p.start, end=p.end, applies_to_all=True, active=True,
        ))
    return out


def _in_season_range(quarter: Quarter, start: date, end: date) -> bool:
    """Ist das Quartier über den ganzen Zeitraum saisonal buchbar?"""
    d = start
    while d < end:
        if not quarter.bookable_on(d):
            return False
        d += timedelta(days=1)
    return True


def range_is_released(quarter: Quarter, start: date, end: date) -> bool:
    """Ist der Zeitraum [start, end) für das Quartier freigeschaltet UND liegt er
    im (jährlichen) Buchbarkeitszeitraum des Quartiers?"""
    return (
        A.range_released(_active_windows(), str(quarter.id), start, end)
        and _in_season_range(quarter, start, end)
    )


def find_bookable_gaps(
    quarter: Quarter, window_start: date, window_end: date,
) -> list[tuple[date, date]]:
    """Buchbare Lücken eines Quartiers: frei UND freigeschaltet."""
    occupied: set[date] = set()
    intervals = [
        (a.start, a.end) for a in Allocation.objects.filter(
            quarter=quarter, start__lt=window_end, end__gt=window_start)]
    intervals += [(b.start, b.end)
                  for b in _external_blocking_qs(quarter, window_start, window_end)]
    for i_start, i_end in intervals:
        d = max(i_start, window_start)
        upper = min(i_end, window_end)
        while d < upper:
            occupied.add(d)
            d += timedelta(days=1)
    return A.released_gaps(
        _active_windows(), str(quarter.id), occupied, window_start, window_end,
    )


def split_quarters_for_range(
    start: date, end: date,
) -> tuple[list[Quarter], list[Quarter]]:
    """Für den Zeitraum [start, end): teilt die freigeschalteten Quartiere in
    (frei buchbar, belegt). Quartiere, die im Zeitraum gar nicht freigeschaltet
    sind, tauchen in keiner der beiden Listen auf."""
    windows = _active_windows()
    free: list[Quarter] = []
    occupied: list[Quarter] = []
    if end <= start:
        return free, occupied
    for q in Quarter.objects.filter(active=True).order_by("name"):
        if not A.range_released(windows, str(q.id), start, end):
            continue
        if not _in_season_range(q, start, end):
            continue
        (free if quarter_is_free(q, start, end) else occupied).append(q)
    return free, occupied


def _occupied_days_by_quarter(first: date, last: date) -> dict[str, set[date]]:
    """Belegte Tage je Quartier-ID im Bereich [first, last]."""
    occupied: dict[str, set[date]] = defaultdict(set)
    rows = [(a.quarter_id, a.start, a.end)
            for a in Allocation.objects.filter(start__lte=last, end__gt=first)]
    rows += [(b.quarter_id, b.start, b.end) for b in ExternalBooking.objects.filter(
        status=ExternalBooking.CONFIRMED, start__lte=last, end__gt=first)]
    for qid, s, e in rows:
        d = max(s, first)
        upper = min(e, last + timedelta(days=1))
        while d < upper:
            occupied[str(qid)].add(d)
            d += timedelta(days=1)
    return occupied


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


# --------------------------------------------------------------------------- #
# Warteliste (Spontanbuchung) & In-App-Benachrichtigungen
# --------------------------------------------------------------------------- #

@transaction.atomic
def add_waitlist_entry(
    member: Member, quarter: Quarter, start: date, end: date, persons: int = 1,
) -> tuple[WaitlistEntry | None, str | None]:
    """Trägt einen Wunschzeitraum für ein belegtes Quartier in die Warteliste ein."""
    if (end - start).days <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    if not range_is_released(quarter, start, end):
        return None, "Dieser Zeitraum ist nicht (durchgängig) zur Buchung freigeschaltet."
    if quarter_is_free(quarter, start, end):
        return None, "Dieses Quartier ist in dem Zeitraum bereits frei – du kannst direkt buchen."
    existing = WaitlistEntry.objects.filter(
        member=member, quarter=quarter, start=start, end=end, fulfilled=False,
    ).exists()
    if existing:
        return None, "Du stehst für diesen Zeitraum bereits auf der Warteliste."
    entry = WaitlistEntry.objects.create(
        member=member, quarter=quarter, start=start, end=end,
        persons=int(persons or 1),
    )
    return entry, None


def waiters_for_allocation(allocation: Allocation):
    """Aktive Wartelisten-Einträge, die diese Buchung betreffen (gleiches
    Quartier, überlappender Zeitraum) – damit die Buchenden sehen, dass jemand
    wartet."""
    return list(
        WaitlistEntry.objects.filter(
            quarter=allocation.quarter, fulfilled=False,
            start__lt=allocation.end, end__gt=allocation.start,
        ).select_related("member").exclude(member=allocation.member)
    )


def notify_waitlist_if_free(quarter: Quarter, start: date, end: date) -> int:
    """Prüft offene Wartelisten-Einträge für `quarter`, die den freigewordenen
    Zeitraum [start, end) berühren: Ist ihr Wunschzeitraum jetzt komplett frei
    (und freigeschaltet), wird das Mitglied benachrichtigt. Gibt die Anzahl der
    Benachrichtigungen zurück."""
    count = 0
    candidates = WaitlistEntry.objects.filter(
        quarter=quarter, fulfilled=False, start__lt=end, end__gt=start,
    ).select_related("member", "quarter")
    for entry in candidates:
        if not quarter_is_free(quarter, entry.start, entry.end):
            continue
        if not range_is_released(quarter, entry.start, entry.end):
            continue
        entry.fulfilled = True
        entry.notified_at = timezone.now()
        entry.save(update_fields=["fulfilled", "notified_at"])
        msg = (f"{quarter.name} ist von {entry.start} bis {entry.end} "
               f"frei geworden – jetzt buchen.")
        url = f"/buchen/?start={entry.start}&end={entry.end}"
        Notification.objects.create(member=entry.member, message=msg, url=url)
        email_member(
            entry.member, "Wartelisten-Platz frei",
            f"Hallo {entry.member.display_name},\n\n{msg}\n\n"
            f"{absolute_url(url)}\n\nViele Grüße\nRe:Hof")
        count += 1
    return count


def unread_notifications(member):
    return list(member.notifications.filter(read=False)) if member else []


def mark_notifications_read(member) -> int:
    if not member:
        return 0
    return member.notifications.filter(read=False).update(read=True)


# --------------------------------------------------------------------------- #
# E-Mail-Outbox (Versand entkoppelt vom Request; send_outbox versendet)
# --------------------------------------------------------------------------- #

def absolute_url(path: str) -> str:
    """Baut aus einem Pfad eine absolute URL für E-Mails (PUBLIC_BASE_URL)."""
    from django.conf import settings
    base = getattr(settings, "PUBLIC_BASE_URL", "") or ""
    return f"{base}{path}" if base else path


def queue_email(to_email: str, subject: str, body: str, html_body: str = "",
                member=None, attachment: bytes | None = None,
                attachment_name: str = "",
                attachment_mime: str = "application/octet-stream"
                ) -> "OutboxEmail | None":
    """Stellt eine E-Mail in die Warteschlange (versendet wird sie vom Scheduler).
    Optional mit einem Datei-Anhang (z.B. Rechnungs-PDF)."""
    to_email = (to_email or "").strip()
    if not to_email:
        return None
    return OutboxEmail.objects.create(
        to_email=to_email, subject=subject, body=body, html_body=html_body,
        member=member,
        attachment=attachment if attachment else None,
        attachment_name=attachment_name if attachment else "",
        attachment_mime=attachment_mime if attachment else "")


def email_member(member, subject: str, body: str, html_body: str = "",
                 attachment: bytes | None = None, attachment_name: str = "",
                 attachment_mime: str = "application/octet-stream"):
    """Mail an ein Mitglied – nur wenn eine Adresse hinterlegt ist UND das
    Mitglied E-Mails nicht abbestellt hat (In-App-Hinweise bleiben unberührt)."""
    if not member or not getattr(member, "email_opt_in", True):
        return None
    email = (getattr(member.user, "email", "") or "").strip()
    if not email:
        return None
    return queue_email(email, subject, body, html_body, member,
                       attachment, attachment_name, attachment_mime)


def queue_email_many(recipients, subject: str, body: str, html_body: str = ""):
    """Stellt dieselbe Mail an mehrere Adressen ein (für Verwaltungs-Mails)."""
    return [em for to in recipients
            if (em := queue_email(to, subject, body, html_body))]


def email_admins(subject: str, body: str, html_body: str = ""):
    from .models import OpsConfig
    return queue_email_many(OpsConfig.get_solo().admin_list(), subject, body, html_body)


def email_cleaning(subject: str, body: str, html_body: str = ""):
    from .models import OpsConfig
    return queue_email_many(OpsConfig.get_solo().cleaning_list(), subject, body, html_body)


# --------------------------------------------------------------------------- #
# Verwaltungs-Dashboard: anstehende Buchungen, Reinigung, Exporte, Monats-Mail
# --------------------------------------------------------------------------- #

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


def _annotate_cleaning(qs):
    """Markiert je Buchung, ob eine Endreinigung mitgebucht wurde."""
    from django.db.models import Exists, OuterRef
    from shop.models import LineItem
    sq = LineItem.objects.filter(
        allocation=OuterRef("pk"), product__counts_as_cleaning=True)
    return qs.annotate(has_cleaning=Exists(sq))


class _ExtRow:
    """Adapter, damit externe Buchungen in denselben Listen/Exports/Mails wie
    Mitglieder-Zuteilungen auftauchen (Reinigung, anstehende Buchungen)."""
    def __init__(self, b: ExternalBooking):
        from types import SimpleNamespace
        self.start, self.end, self.persons = b.start, b.end, b.persons
        self.companions = ""
        self.has_cleaning = True          # externe Buchung enthält Endreinigung
        self.quarter = b.quarter
        self.member = SimpleNamespace(display_name=f"{b.guest.name} (extern)")

    @property
    def nights(self) -> int:
        return (self.end - self.start).days

    def get_source_display(self) -> str:
        return "Externer Gast"


def _external_confirmed(**flt):
    return (ExternalBooking.objects
            .filter(status=ExternalBooking.CONFIRMED, **flt)
            .select_related("quarter", "guest"))


def _month_occupancy(year: int, month: int) -> dict:
    """Auslastung eines Monats: gebuchte Unterkunfts-Nächte (Mitglieder + bestätigte
    externe Gäste) gegen die maximal möglichen (Quartiere × Tage)."""
    days = _calendar.monthrange(year, month)[1]
    m_first = date(year, month, 1)
    m_end = m_first + timedelta(days=days)
    n_quarters = Quarter.objects.count()
    possible = n_quarters * days
    booked = 0
    for a in Allocation.objects.filter(start__lt=m_end, end__gt=m_first,
                                       provisional=False):
        booked += (min(a.end, m_end) - max(a.start, m_first)).days
    for b in ExternalBooking.objects.filter(
            status=ExternalBooking.CONFIRMED, start__lt=m_end, end__gt=m_first):
        booked += (min(b.end, m_end) - max(b.start, m_first)).days
    pct = round(100 * booked / possible) if possible else 0
    return {"year": year, "month": month, "label": month_label(year, month),
            "booked": booked, "possible": possible, "pct": pct}


def dashboard_stats() -> dict:
    """Kennzahlen für die Verwaltung: Nutzer/Mitglieder, Auslastung (aktueller +
    kommender Monat) und das Ergebnis der letzten (bestätigten) Verlosung."""
    from django.contrib.auth.models import User
    today = date.today()
    ny, nm = next_month(today)
    run = (LotteryRun.objects.filter(confirmed=True).select_related("period")
           .order_by("-confirmed_at").first())
    last_lottery = None
    if run:
        last_lottery = {
            "period": run.period, "fulfilled": run.n_allocations,
            "unfulfilled": run.n_losses, "when": run.confirmed_at,
            "total": run.n_allocations + run.n_losses,
        }
    return {
        "n_users": User.objects.count(),
        "n_members": Member.objects.count(),
        "occ_current": _month_occupancy(today.year, today.month),
        "occ_next": _month_occupancy(ny, nm),
        "last_lottery": last_lottery,
    }


def arrivals_in_range(d_from: date, d_to: date):
    """Anreisen in [d_from, d_to) – Mitglieder UND externe Gäste."""
    qs = _annotate_cleaning(Allocation.objects.filter(
        start__gte=d_from, start__lt=d_to)).select_related("quarter", "member")
    rows = list(qs) + [_ExtRow(b) for b in _external_confirmed(
        start__gte=d_from, start__lt=d_to)]
    rows.sort(key=lambda a: (a.start, a.quarter.name))
    return rows


def departures_in_range(d_from: date, d_to: date):
    """Abreisen in [d_from, d_to) – Reinigungstage; Mitglieder UND externe Gäste."""
    qs = _annotate_cleaning(Allocation.objects.filter(
        end__gte=d_from, end__lt=d_to)).select_related("quarter", "member")
    rows = list(qs) + [_ExtRow(b) for b in _external_confirmed(
        end__gte=d_from, end__lt=d_to)]
    rows.sort(key=lambda a: (a.end, a.quarter.name))
    return rows


BOOKING_COLUMNS = ["Anreise", "Abreise", "Nächte", "Quartier", "Mitglied",
                   "Personen", "Begleitung", "Endreinigung", "Quelle"]


def booking_rows(allocs):
    for a in allocs:
        yield [a.start.isoformat(), a.end.isoformat(), a.nights, a.quarter.name,
               a.member.display_name, a.persons, a.companions,
               "ja" if getattr(a, "has_cleaning", False) else "nein",
               a.get_source_display()]


CLEANING_COLUMNS = ["Reinigung am", "Wochentag", "Quartier", "Mitglied",
                    "Personen", "Endreinigung gebucht"]


def cleaning_rows(deps, only_cleaning: bool = False):
    for a in deps:
        has = getattr(a, "has_cleaning", False)
        if only_cleaning and not has:
            continue
        yield [a.end.isoformat(), WEEKDAYS_DE[a.end.weekday()], a.quarter.name,
               a.member.display_name, a.persons, "ja" if has else "nein"]


def bookings_text(allocs) -> str:
    lines = []
    for a in allocs:
        clean = " · inkl. Endreinigung" if getattr(a, "has_cleaning", False) else ""
        lines.append(f"{a.start:%d.%m.}–{a.end:%d.%m.%Y}  {a.quarter.name}  "
                     f"{a.member.display_name} ({a.persons} Pers.){clean}")
    return "\n".join(lines) if lines else "— keine —"


def cleaning_text(deps, only_cleaning: bool = False) -> str:
    lines = []
    for a in deps:
        has = getattr(a, "has_cleaning", False)
        if only_cleaning and not has:
            continue
        mark = "ENDREINIGUNG" if has else "(keine Endreinigung gebucht)"
        lines.append(f"{WEEKDAYS_DE[a.end.weekday()]} {a.end:%d.%m.%Y}  "
                     f"{a.quarter.name}  – {mark}  "
                     f"({a.member.display_name}, {a.persons} Pers.)")
    return "\n".join(lines) if lines else "— keine Abreisen —"


def notify_admins_upcoming(force: bool = False) -> int:
    """Schickt der Verwaltung die Buchungen des Folgemonats. Vom Scheduler täglich
    aufgerufen; sendet idempotent nur am eingestellten Tag, einmal pro Monat.
    Gibt die Zahl der Empfänger zurück (0 = nichts gesendet)."""
    from .models import OpsConfig
    cfg = OpsConfig.get_solo()
    today = date.today()
    if not force:
        if today.day != cfg.notify_day:
            return 0
        if (cfg.last_admin_notice and cfg.last_admin_notice.year == today.year
                and cfg.last_admin_notice.month == today.month):
            return 0
    recipients = cfg.admin_list()
    if not recipients:
        return 0
    y, m = next_month(today)
    d_from, d_to = month_bounds(y, m)
    arrivals = list(arrivals_in_range(d_from, d_to))
    deps = list(departures_in_range(d_from, d_to))
    body = (f"Anstehende Buchungen – {month_label(y, m)}\n\n"
            f"ANREISEN / AUFENTHALTE ({len(arrivals)}):\n{bookings_text(arrivals)}\n\n"
            f"REINIGUNG / ABREISEN ({len(deps)}):\n{cleaning_text(deps)}\n\n"
            f"Details im Verwaltungs-Dashboard: {absolute_url('/verwaltung/')}\n")
    queue_email_many(recipients, f"Re:Hof – Buchungen {m:02d}/{y}", body)
    cfg.last_admin_notice = today
    cfg.save(update_fields=["last_admin_notice"])
    return len(recipients)


# --------------------------------------------------------------------------- #
# Tages-Detail (Übersicht) & Wechselwünsche
# --------------------------------------------------------------------------- #

def day_detail(member, day: date) -> dict:
    """Wer ist an `day` in welchem Quartier (mit Personenzahl) – und welche
    Quartiere sind an dem Tag noch frei?"""
    nxt = day + timedelta(days=1)
    occupied = [
        {
            "quarter": a.quarter.name,
            "who": a.member.display_name,
            "persons": a.persons,
            "mine": bool(member) and a.member_id == member.id,
        }
        for a in Allocation.objects.select_related("quarter", "member")
        .filter(start__lte=day, end__gt=day, provisional=False)
        .order_by("quarter__name")
    ]
    occupied += [
        {"quarter": b.quarter.name, "who": "extern", "persons": b.persons,
         "mine": False, "external": True}
        for b in ExternalBooking.objects.select_related("quarter")
        .filter(status=ExternalBooking.CONFIRMED, start__lte=day, end__gt=day)
        .order_by("quarter__name")
    ]
    free, _occ = split_quarters_for_range(day, nxt)
    return {"day": day, "occupied": occupied, "free": [q.name for q in free]}


def concurrent_allocations(allocation: Allocation):
    """Andere Buchungen (anderer Mitglieder), die zeitlich mit `allocation`
    überlappen – „wer ist zur gleichen Zeit da“."""
    return list(
        Allocation.objects.select_related("quarter", "member").filter(
            start__lt=allocation.end, end__gt=allocation.start, provisional=False,
        ).exclude(member_id=allocation.member_id).order_by("start", "quarter__name")
    )


def free_quarters_for(start: date, end: date, persons: int, exclude_id=None):
    """Quartiere, die im Zeitraum [start, end) komplett frei + freigeschaltet sind
    und zur Personenzahl passen (für den Unterkunfts-Wechsel beim Anpassen)."""
    out = []
    for q in Quarter.objects.order_by("name"):
        if exclude_id and q.id == exclude_id:
            continue
        if persons < q.min_occupancy or persons > q.max_occupancy:
            continue
        if range_is_released(q, start, end) and quarter_is_free(q, start, end):
            out.append(q)
    return out


def concurrent_split(allocation: Allocation) -> dict:
    """Wie `concurrent_allocations`, aber aufgeteilt in
    `exact` = exakt gleiche An- UND Abreise (echter Tausch sinnvoll) und
    `overlap` = nur überlappend (Tausch nur eingeschränkt/abzusprechen)."""
    exact, overlap = [], []
    for a in concurrent_allocations(allocation):
        if a.start == allocation.start and a.end == allocation.end:
            exact.append(a)
        else:
            overlap.append(a)
    return {"exact": exact, "overlap": overlap}


@transaction.atomic
def create_swap_request(from_member, from_allocation, to_allocation, message=""):
    """Legt einen Wechselwunsch an und benachrichtigt das Gegenüber."""
    if to_allocation.member_id == from_member.id:
        return None, "Das ist deine eigene Buchung."
    sr = SwapRequest.objects.create(
        from_member=from_member, to_member=to_allocation.member,
        from_allocation=from_allocation, to_allocation=to_allocation,
        message=message,
    )
    Notification.objects.create(
        member=to_allocation.member,
        message=(f"{from_member.display_name} fragt nach einem Quartier-Tausch "
                 f"({from_allocation.quarter.name} ↔ {to_allocation.quarter.name})."),
        url="/meine-buchungen/",
    )
    return sr, None


@transaction.atomic
def respond_swap_request(member, swap_id, accept: bool) -> tuple[bool, str | None]:
    """Nimmt einen eingegangenen Wechselwunsch an oder lehnt ihn ab und
    benachrichtigt die anfragende Person."""
    try:
        sr = SwapRequest.objects.select_related("from_allocation", "to_allocation") \
            .get(id=swap_id, to_member=member, status=SwapRequest.PENDING)
    except SwapRequest.DoesNotExist:
        return False, "Wechselwunsch nicht gefunden."
    sr.status = SwapRequest.ACCEPTED if accept else SwapRequest.DECLINED
    sr.responded_at = timezone.now()
    sr.save(update_fields=["status", "responded_at"])
    verb = "angenommen" if accept else "abgelehnt"
    Notification.objects.create(
        member=sr.from_member,
        message=(f"{member.display_name} hat deinen Wechselwunsch {verb} "
                 f"({sr.from_allocation.quarter.name} ↔ {sr.to_allocation.quarter.name})."),
        url="/meine-buchungen/",
    )
    return True, None


def pending_swaps_for(member):
    """Offene, an `member` gerichtete Wechselwünsche."""
    return list(
        SwapRequest.objects.filter(to_member=member, status=SwapRequest.PENDING)
        .select_related("from_member", "from_allocation__quarter",
                        "to_allocation__quarter")
    )


# --------------------------------------------------------------------------- #
# Tage an andere Mitglieder übertragen
# --------------------------------------------------------------------------- #

@transaction.atomic
def transfer_nights(
    from_member: Member, to_member: Member, nights: int, year: int,
    note: str = "",
) -> tuple[NightTransfer | None, str | None]:
    """Überträgt `nights` Tage von einem Mitglied auf ein anderes (für `year`).
    Gibt (NightTransfer, None) oder (None, Fehlermeldung) zurück."""
    if from_member.id == to_member.id:
        return None, "Empfänger muss ein anderes Mitglied sein."
    if nights <= 0:
        return None, "Die Anzahl der Tage muss positiv sein."
    remaining = from_member.nights_remaining_in_year(year)
    if remaining < nights:
        return None, (f"Nicht genügend verfügbare Tage zum Übertragen "
                      f"({remaining} übrig, {nights} angefragt).")
    t = NightTransfer.objects.create(
        from_member=from_member, to_member=to_member, nights=nights,
        year=year, note=note,
    )
    return t, None


# --------------------------------------------------------------------------- #
# Schulferien (Anzeige) & Mitglieder-Kalender
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Stornierung
# --------------------------------------------------------------------------- #

@transaction.atomic
def cancel_allocation(member: Member, allocation_id) -> tuple[bool, str | None]:
    """Storniert eine Buchung des Mitglieds. Vergangene Buchungen bleiben.
    Wird dadurch ein Wartelisten-Zeitraum frei, werden die Wartenden
    benachrichtigt."""
    try:
        a = member.allocations.get(id=allocation_id)
    except Allocation.DoesNotExist:
        return False, "Buchung nicht gefunden."
    if a.end <= date.today():
        return False, "Vergangene Buchungen können nicht storniert werden."
    quarter, start, end = a.quarter, a.start, a.end
    a.delete()
    notify_waitlist_if_free(quarter, start, end)
    return True, None


def _broadcast_spontaneously_free(quarter, start, end, exclude_member=None) -> int:
    """In-App-Benachrichtigung an ALLE Mitglieder: eine Unterkunft ist spontan
    frei geworden (z.B. durch Verkürzung). E-Mails laufen gezielt über die
    Warteliste (`notify_waitlist_if_free`), nicht an alle."""
    nights = (end - start).days
    msg = (f"Spontan frei: {quarter.name} "
           f"{start:%d.%m.}–{end:%d.%m.} ({nights} Nächte)")
    qs = Member.objects.all()
    if exclude_member is not None:
        qs = qs.exclude(id=exclude_member.id)
    Notification.objects.bulk_create([
        Notification(member=m, message=msg, url="/buchen/") for m in qs])
    return qs.count()


@transaction.atomic
def adjust_allocation(member: Member, allocation_id, new_start: date,
                      new_end: date, new_quarter=None,
                      new_persons: int | None = None) -> tuple[bool, str | None]:
    """Ändert eine eigene (zukünftige) Buchung: Zeitraum (verlängern/verkürzen),
    **Unterkunft** (Wechsel auf ein freies Quartier) und/oder **Personenzahl**.

    * Verlängern/Quartier-Wechsel: spontan möglich, solange die (zusätzlichen
      bzw. beim Wechsel alle) Nächte frei, freigeschaltet und im Tage-Budget sind.
    * Verkürzen (im selben Quartier): nur wenn die Restdauer den Mindestaufenthalt
      einhält UND die frei werdenden Nächte ≥7 Tage in der Zukunft liegen.
    Frei werdende Unterkünfte werden allen Mitgliedern gemeldet (In-App) und der
    Warteliste (E-Mail). Beim Quartier-Wechsel gilt die 7-Tage-Frist NICHT (es
    wird ja nicht das eigene Kontingent gekürzt, nur umgezogen)."""
    try:
        a = member.allocations.select_related("quarter").get(id=allocation_id)
    except Allocation.DoesNotExist:
        return False, "Buchung nicht gefunden."
    if (new_end - new_start).days <= 0:
        return False, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    if a.end <= date.today():
        return False, "Vergangene Buchungen können nicht angepasst werden."

    old_q = a.quarter
    new_q = new_quarter or old_q
    persons = new_persons if new_persons is not None else a.persons
    quarter_changed = new_q.id != old_q.id
    today = date.today()
    old_nights = (a.end - a.start).days
    new_nights = (new_end - new_start).days

    if new_start == a.start and new_end == a.end and not quarter_changed \
            and persons == a.persons:
        return False, "Keine Änderung."

    # Personenzahl muss zur (ggf. neuen) Unterkunft passen.
    if persons < new_q.min_occupancy or persons > new_q.max_occupancy:
        return False, (f"{new_q.name}: {new_q.min_occupancy}–{new_q.max_occupancy} "
                       f"Personen (gewählt {persons}).")

    # Welche Nächte müssen im (ggf. neuen) Quartier frei + freigeschaltet sein?
    if quarter_changed:
        need_free = [(new_start, new_end)]            # ganzer Zeitraum im neuen Q.
    else:
        need_free = []                                 # nur die hinzukommenden Teile
        if new_start < a.start:
            need_free.append((new_start, a.start))
        if new_end > a.end:
            need_free.append((a.end, new_end))
    for s, e in need_free:
        if not range_is_released(new_q, s, e):
            return False, "Der gewählte Zeitraum ist nicht buchbar (Saison/Freigabe)."
        if not quarter_is_free(new_q, s, e):
            return False, "Der gewählte Zeitraum ist im Quartier nicht frei."

    # Budget: nur zusätzliche Nächte zählen.
    extra = new_nights - old_nights
    if extra > 0:
        remaining = member.nights_remaining_in_year(new_start.year)
        if remaining < extra:
            return False, (f"Nicht genügend Tage ({remaining} übrig, "
                           f"{extra} zusätzlich nötig).")

    # Mindestaufenthalt der NEUEN Dauer.
    min_n = min_nights_for_range(new_start, new_end)
    if new_nights < min_n:
        return False, f"Mindestaufenthalt {min_n} Nächte (neu wären es {new_nights})."

    # Frei werdende Bereiche bestimmen + 7-Tage-Frist (nur bei Verkürzung im
    # gleichen Quartier).
    if quarter_changed:
        freed = [(old_q, a.start, a.end)]             # altes Quartier ganz frei
    else:
        freed = []
        if new_start > a.start:
            freed.append((old_q, a.start, new_start))
        if new_end < a.end:
            freed.append((old_q, new_end, a.end))
        if freed:
            earliest = min(s for _, s, _ in freed)
            if earliest < today + timedelta(days=7):
                return False, ("Verkürzen ist nur möglich, wenn die frei werdenden "
                               "Nächte mindestens eine Woche in der Zukunft liegen.")

    a.quarter, a.start, a.end, a.persons = new_q, new_start, new_end, persons
    a.save(update_fields=["quarter", "start", "end", "persons"])

    # Frei gewordene Zeiträume melden.
    for q, s, e in freed:
        _broadcast_spontaneously_free(q, s, e, exclude_member=member)
        notify_waitlist_if_free(q, s, e)
    return True, None


# --------------------------------------------------------------------------- #
# Wunschliste: Reihenfolge, Einreichen, Zurückziehen
# --------------------------------------------------------------------------- #

def _renumber_wishes(member: Member, period: BookingPeriod) -> None:
    """Setzt die Prioritäten lückenlos auf 1..N gemäß aktueller Reihenfolge."""
    wishes = list(
        Wish.objects.filter(member=member, period=period).order_by("priority", "id")
    )
    for i, w in enumerate(wishes, start=1):
        if w.priority != i:
            w.priority = i
            w.save(update_fields=["priority"])


def add_wish(member, period, quarter, start, end) -> tuple[Wish | None, str | None]:
    """Fügt einen Wunsch als Entwurf ans Ende der Liste an.

    Prüft vorab, dass das Quartier im GANZEN Wunschzeitraum saisonal buchbar ist
    – sonst könnte ein Losgewinn eine Buchung außerhalb der Quartier-Saison
    erzeugen (z.B. Anreise noch in Saison, Abreise schon außerhalb)."""
    if (end - start).days <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    if not _in_season_range(quarter, start, end):
        return None, (f"{quarter.name} ist in diesem Zeitraum nicht durchgängig "
                      "buchbar (Quartier-Saison). Bitte den gesamten Zeitraum "
                      "innerhalb der Saison wählen.")
    # Saison-Regeln (Mindestnächte/Deckel) schon beim Eintragen prüfen, damit ein
    # Losgewinn nicht an einer Regel scheitern würde.
    rule_err = wish_rule_error(start, end)
    if rule_err:
        return None, rule_err
    last = (
        Wish.objects.filter(member=member, period=period)
        .order_by("-priority").first()
    )
    next_prio = (last.priority + 1) if last else 1
    wish = Wish.objects.create(
        member=member, period=period, quarter=quarter, start=start, end=end,
        priority=next_prio, submitted=False,
    )
    return wish, None


@transaction.atomic
def move_wish(member, period, wish_id, direction: str) -> None:
    wishes = list(
        Wish.objects.filter(member=member, period=period).order_by("priority", "id")
    )
    idx = next((i for i, w in enumerate(wishes) if str(w.id) == str(wish_id)), None)
    if idx is None:
        return
    swap = idx - 1 if direction == "up" else idx + 1
    if swap < 0 or swap >= len(wishes):
        return
    a, b = wishes[idx], wishes[swap]
    a.priority, b.priority = b.priority, a.priority
    a.save(update_fields=["priority"])
    b.save(update_fields=["priority"])


@transaction.atomic
def reorder_wishes(member, period, ordered_ids: list[str]) -> None:
    by_id = {
        str(w.id): w
        for w in Wish.objects.filter(member=member, period=period)
    }
    prio = 1
    for wid in ordered_ids:
        w = by_id.get(str(wid))
        if w is None:
            continue
        if w.priority != prio:
            w.priority = prio
            w.save(update_fields=["priority"])
        prio += 1


@transaction.atomic
def delete_wish(member, period, wish_id) -> None:
    Wish.objects.filter(id=wish_id, member=member, period=period).delete()
    _renumber_wishes(member, period)


@transaction.atomic
@transaction.atomic
def submit_wishlist(member, period) -> tuple[int, str | None]:
    """Reicht alle Entwurfs-Wünsche des Mitglieds in den Lostopf ein. Prüft jeden
    Wunsch zuvor gegen die Saison-Regeln (Mindestnächte/Deckel) – verletzt einer
    eine Regel (z.B. weil eine Regel nach dem Eintragen ergänzt wurde), wird
    NICHTS eingereicht und der Grund zurückgegeben. Liefert (Anzahl, Fehler|None)."""
    drafts = list(Wish.objects.filter(
        member=member, period=period, submitted=False).select_related("quarter"))
    problems = [
        f"„{w.quarter.name} {w.start:%d.%m.}–{w.end:%d.%m.}“: {err}"
        for w in drafts
        if (err := wish_rule_error(w.start, w.end))
    ]
    if problems:
        return 0, ("Einreichen nicht möglich – bitte diese Wünsche anpassen oder "
                   "entfernen:\n" + "\n".join(problems))
    _renumber_wishes(member, period)
    n = Wish.objects.filter(
        member=member, period=period, submitted=False,
    ).update(submitted=True, submitted_at=timezone.now())
    return n, None


@transaction.atomic
def withdraw_wishlist(member, period) -> int:
    """Zieht die Wünsche aus dem Lostopf zurück (wieder Entwurf)."""
    return Wish.objects.filter(
        member=member, period=period, submitted=True,
    ).update(submitted=False, submitted_at=None)


# --------------------------------------------------------------------------- #
# Externe Gäste: Angebot, Buchung, Storno (siehe docs/EXTERNE-GAESTE.md)
# --------------------------------------------------------------------------- #

def external_quote(quarter: Quarter, start: date, end: date, cfg=None) -> dict:
    """Preis-Aufschlüsselung für eine externe Buchung (brutto) + Rechnungs-Positionen.

    Die Übernachtungen werden Nacht für Nacht zum jeweils gültigen (ggf.
    saisonalen) Quartier-Preis berechnet (siehe `QuarterPrice`). Gleiche
    Nachtpreise werden zu einer Rechnungs-Position zusammengefasst."""
    from decimal import Decimal
    cfg = cfg or ExternalConfig.get_solo()
    nights = (end - start).days
    # Nacht-für-Nacht den (saisonalen) Preis bestimmen und nach Preis bündeln.
    by_price: dict = defaultdict(int)
    d = start
    while d < end:
        by_price[quarter.price_for_night(d)] += 1
        d += timedelta(days=1)
    stay = sum((p * n for p, n in by_price.items()), Decimal("0"))
    cleaning = cfg.cleaning_fee or 0
    specs: list[dict] = []
    for price in sorted(by_price, reverse=True):
        n = by_price[price]
        specs.append({"name": f"Übernachtung – {quarter.name}", "quantity": n,
                      "unit": "Nacht", "unit_price": price, "vat_rate": cfg.stay_vat})
    if cleaning > 0:
        specs.append({"name": "Endreinigung", "quantity": 1, "unit": "Pauschale",
                      "unit_price": cleaning, "vat_rate": cfg.cleaning_vat,
                      "service_date": end})
    total = stay + cleaning
    seasonal = len(by_price) > 1
    return {"nights": nights, "stay_gross": stay, "cleaning_gross": cleaning,
            "total_gross": total, "line_specs": specs, "seasonal_price": seasonal,
            "deposit_gross": cfg.deposit_for(total),
            "cancellation_text": cfg.cancellation_text}


def external_available_quarters(start: date, end: date) -> list[tuple]:
    """Für Externe buchbare, freie Quartiere im Zeitraum + Preis-Angebot.
    Leere Liste, wenn Externe gesperrt sind oder die Regeln nicht passen."""
    cfg = ExternalConfig.get_solo()
    if not cfg.active or end <= start:
        return []
    ok, _reason = external_allowed(
        start, end, today=date.today(), allowed_weekdays=cfg.allowed_weekday_set,
        min_nights=cfg.min_nights, max_nights=cfg.max_nights,
        lead_days=cfg.lead_days, horizon_days=cfg.horizon_days)
    if not ok:
        return []
    # Konfigurierte Saison-Mindestnächte (z.B. 7 im Sommer) gelten für Externe
    # zusätzlich zu deren eigenem Mindestaufenthalt – das strengere zählt.
    if (end - start).days < season_min_nights(start, end):
        return []
    out = []
    for q in Quarter.objects.filter(
            active=True, external_bookable=True).order_by("name"):
        if not _in_season_range(q, start, end):
            continue
        if not quarter_is_free(q, start, end):
            continue
        out.append((q, external_quote(q, start, end, cfg)))
    return out


@transaction.atomic
def create_external_booking(quarter: Quarter, start: date, end: date, persons: int,
                            *, name: str, email: str, street: str = "",
                            zip_code: str = "", city: str = ""):
    """Legt eine externe Buchung an: Gast + ExternalBooking (blockiert) + Rechnung
    (wie Hofladen, Zahlung per Überweisung). Gibt (booking, None) oder (None, Fehler)."""
    cfg = ExternalConfig.get_solo()
    if not cfg.active:
        return None, "Buchungen für externe Gäste sind derzeit nicht möglich."
    if not (quarter.active and quarter.external_bookable):
        return None, "Dieses Quartier ist für externe Gäste nicht buchbar."
    if end <= start:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    ok, reason = external_allowed(
        start, end, today=date.today(), allowed_weekdays=cfg.allowed_weekday_set,
        min_nights=cfg.min_nights, max_nights=cfg.max_nights,
        lead_days=cfg.lead_days, horizon_days=cfg.horizon_days)
    if not ok:
        return None, reason
    # Konfigurierte Saison-Mindestnächte (z.B. 7 im Sommer) gelten auch für Externe.
    season_min = season_min_nights(start, end)
    if (end - start).days < season_min:
        return None, (f"Mindestaufenthalt in diesem Zeitraum: {season_min} Nächte "
                      f"(gewählt: {(end - start).days}).")
    if not _in_season_range(quarter, start, end):
        return None, f"{quarter.name} ist in diesem Zeitraum nicht buchbar."
    if persons and persons > quarter.max_occupancy:
        return None, f"{quarter.name}: maximal {quarter.max_occupancy} Personen."
    if not quarter_is_free(quarter, start, end):
        return None, f"{quarter.name} ist in diesem Zeitraum bereits belegt."
    if not (name.strip() and email.strip()):
        return None, "Bitte Name und E-Mail angeben."

    q = external_quote(quarter, start, end, cfg)
    guest = Guest.objects.create(
        name=name.strip(), email=email.strip(), street=street.strip(),
        zip_code=zip_code.strip(), city=city.strip())
    booking = ExternalBooking.objects.create(
        guest=guest, quarter=quarter, start=start, end=end,
        persons=max(1, persons or 1), status=ExternalBooking.CONFIRMED,
        total_gross=q["total_gross"], confirmed_at=timezone.now())

    # Rechnung wie im Hofladen – Zahlung per Überweisung, Abgleich via reconcile.
    from shop.services import create_invoice_for_guest
    inv = create_invoice_for_guest(guest, q["line_specs"],
                                   due_days=cfg.payment_term_days)
    booking.invoice = inv
    booking.save(update_fields=["invoice"])

    # Bestätigung + Zahlungsinfo per E-Mail (Gast hat kein Konto).
    bic = f" · BIC: {inv.bic}" if inv.bic else ""
    manage_url = absolute_url(reverse("external_manage", args=[guest.token]))
    deposit = q.get("deposit_gross") or 0
    deposit_line = (f"Anzahlung: {deposit} € (bitte zuerst überweisen).\n"
                    if deposit else "")
    queue_email(
        guest.email, f"Buchungsbestätigung – {quarter.name}",
        f"Hallo {guest.name},\n\nvielen Dank für deine Buchung:\n"
        f"{quarter.name}, {start:%d.%m.%Y} – {end:%d.%m.%Y} "
        f"({q['nights']} Nächte, {booking.persons} Pers.)\n\n"
        f"Rechnung {inv.number} über {inv.total_gross} €.\n"
        f"{deposit_line}"
        f"Bitte mit der Rechnungsnummer als Verwendungszweck überweisen auf:\n"
        f"IBAN: {inv.iban or '—'}{bic}\n"
        f"Zahlbar bis {inv.due_date:%d.%m.%Y}.\n\n"
        f"Stornobedingungen: {q.get('cancellation_text', '')}\n\n"
        f"Buchung ansehen/stornieren: {manage_url}\n\n"
        f"Viele Grüße\nRe:Hof",
        member=None)
    return booking, None


def external_cancellation_preview(booking: ExternalBooking, cfg=None) -> dict:
    """Erstattungs-Vorschau für ein Storno (ohne zu stornieren)."""
    cfg = cfg or ExternalConfig.get_solo()
    refund, pct, label = cancellation_refund(
        booking.total_gross, arrival=booking.start, today=date.today(),
        free_days=cfg.free_cancel_days, partial_days=cfg.partial_cancel_days,
        partial_percent=cfg.partial_refund_percent)
    return {"refund": refund, "percent": pct, "label": label,
            "kept": booking.total_gross - refund}


def run_fairness_simulation(cfg=None) -> dict:
    """Führt die Monte-Carlo-Fairness-Simulation aus und speichert das Ergebnis
    am Singleton. Liefert das Ergebnis-Dict (equal-chance + Karma-Effekt)."""
    from .models import FairnessSimConfig
    from . import fairness as F
    cfg = cfg or FairnessSimConfig.get_solo()
    result = {
        "equal": F.simulate_equal_chance(cfg.n_users, cfg.n_items, cfg.n_runs),
        "karma": F.simulate_karma_effect(cfg.n_users, cfg.n_items, cfg.n_runs),
    }
    cfg.last_result = result
    cfg.last_run_at = timezone.now()
    cfg.save(update_fields=["last_result", "last_run_at"])
    return result


def cancel_external_booking(booking: ExternalBooking) -> dict:
    """Storniert eine externe Buchung (gibt den Slot frei) und liefert die
    Erstattungs-Aufschlüsselung gemäß Stornobedingungen zurück."""
    preview = external_cancellation_preview(booking)
    booking.status = ExternalBooking.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    notify_waitlist_if_free(booking.quarter, booking.start, booking.end)
    return preview


def external_booking_by_token(token, booking_id) -> ExternalBooking | None:
    """Holt eine Buchung über den Gast-Magic-Link-Token (Selbstverwaltung)."""
    return ExternalBooking.objects.select_related("guest", "quarter", "invoice") \
        .filter(id=booking_id, guest__token=token).first()


def guest_bookings_by_token(token) -> list[ExternalBooking]:
    """Alle Buchungen eines Gastes zum Magic-Link-Token (neueste zuerst)."""
    return list(ExternalBooking.objects.select_related("quarter", "invoice")
                .filter(guest__token=token).order_by("-start"))


def cancel_external_booking_by_token(token, booking_id) -> tuple[dict | None, str | None]:
    """Storniert eine Gast-Buchung über den Magic-Link. Nur zukünftige Buchungen,
    die noch nicht storniert sind."""
    booking = external_booking_by_token(token, booking_id)
    if not booking:
        return None, "Buchung nicht gefunden."
    if booking.status == ExternalBooking.CANCELLED:
        return None, "Diese Buchung ist bereits storniert."
    if booking.start <= date.today():
        return None, "Vergangene oder laufende Buchungen können nicht storniert werden."
    return cancel_external_booking(booking), None


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


# --------------------------------------------------------------------------- #
# Beds24-Migrations-Assistent: CSV stagen, Vorschläge, manuell übernehmen.
# --------------------------------------------------------------------------- #

def _beds24_member_candidates():
    """Mitglieder als Match-Kandidaten mit allen Namensvarianten."""
    import re
    from . import beds24
    cands = []
    for m in Member.objects.select_related("user").all():
        full = m.user.get_full_name() if m.user_id else ""
        names = [m.legal_name, m.display_name, full,
                 getattr(m.user, "username", "")]
        # Klammer-Zusatz aus dem Anzeigenamen entfernen ("Anna (anna0)" -> "Anna").
        names = [re.sub(r"\(.*?\)", "", n).strip() for n in names if n]
        cands.append(beds24.Candidate(key=m.id, names=list(dict.fromkeys(names))))
    return cands


def _beds24_quarter_candidates():
    from . import beds24
    return [beds24.Candidate(key=q.id, names=[q.name]) for q in Quarter.objects.all()]


def beds24_stage(data: str, filename: str):
    """Parst den Beds24-CSV-Export, legt einen Import-Lauf mit Zeilen an und
    hängt automatische Vorschläge (Mitglied/Quartier) an. Liefert den Import."""
    from . import beds24
    from .models import Beds24Import, Beds24ImportRow
    rows = beds24.parse_csv(data)
    batch = Beds24Import.objects.create(filename=(filename or "")[:200],
                                        n_rows=len(rows))
    mcands = _beds24_member_candidates()
    qcands = _beds24_quarter_candidates()
    for r in rows:
        mranked = beds24.rank_candidates(r.guest_name, mcands, limit=1)
        sug_m_id, score = (mranked[0] if mranked else (None, 0.0))
        sug_m = Member.objects.filter(id=sug_m_id).first() if sug_m_id else None
        qranked = (beds24.rank_candidates(r.unit, qcands, limit=1, min_score=0.3)
                   if r.unit else [])
        sug_q = (Quarter.objects.filter(id=qranked[0][0]).first()
                 if qranked else None)
        Beds24ImportRow.objects.create(
            batch=batch, guest_name=r.guest_name[:200], arrival=r.arrival,
            departure=r.departure, unit=r.unit[:200], persons=r.persons or 1,
            ref=r.ref[:80], raw=r.raw,
            suggested_member=sug_m, suggested_score=score, suggested_quarter=sug_q,
            # Sehr sicherer Namens-Treffer wird vorausgewählt, sonst manuell.
            chosen_member=sug_m if score >= 0.7 else None,
            chosen_quarter=sug_q,
            note="" if r.valid else "Ungültige Zeile (Name/Datum prüfen)")
    return batch


def beds24_create_member(guest_name: str, email: str = "") -> Member:
    """Legt für einen nicht zuordenbaren Gastnamen ein neues Mitglied an
    (Login-Konto ohne Passwort + Voll-Anteil 50 Tage). Für den „Mitglied
    anlegen"-Knopf im Abgleich."""
    import re
    from django.contrib.auth.models import User
    from .models import Membership, Share
    base = re.sub(r"[^a-z0-9]+", "", (guest_name or "").lower()) or "gast"
    base = base[:24]
    uname, i = base, 1
    while User.objects.filter(username=uname).exists():
        i += 1
        uname = f"{base}{i}"
    user = User.objects.create(username=uname, email=(email or "").strip(),
                               first_name=guest_name[:30])
    user.set_unusable_password()
    user.save()
    member = Member.objects.create(
        user=user, display_name=guest_name[:120], legal_name=guest_name[:160])
    ms = Membership.objects.create(
        eg_number=f"IMP-{user.id}", label=guest_name[:120],
        kind=Membership.VOLL, annual_night_budget=50, wish_night_budget=25)
    Share.objects.create(membership=ms, member=member,
                         night_budget=50, wish_night_budget=25)
    return member


@transaction.atomic
def beds24_apply(batch, decisions: dict) -> dict:
    """Übernimmt die abgeglichenen Zeilen als Buchungen (`Allocation`, Quelle
    „import", ohne Rechnung – diese Buchungen sind immer bezahlt).

    `decisions` je Zeilen-ID: {"action": "import"|"skip", "member": id|None,
    "quarter": id|None, "persons": int|None}. Idempotent: bereits vorhandene
    identische Buchungen werden nicht doppelt angelegt."""
    from .models import Beds24ImportRow
    summary = {"imported": 0, "skipped": 0, "errors": []}
    for row in batch.rows.all():
        d = decisions.get(row.id) or decisions.get(str(row.id))
        if not d:
            continue
        if d.get("persons"):
            row.persons = d["persons"]
        if d.get("member") is not None:
            row.chosen_member = Member.objects.filter(id=d["member"]).first()
        if d.get("quarter") is not None:
            row.chosen_quarter = Quarter.objects.filter(id=d["quarter"]).first()
        action = d.get("action")
        if action == "skip":
            row.status = Beds24ImportRow.SKIPPED
            row.save()
            summary["skipped"] += 1
            continue
        if action != "import":
            row.save()
            continue
        if not row.valid or not row.chosen_member or not row.chosen_quarter:
            row.note = "Unvollständig: Mitglied, Quartier und Datum nötig."
            row.save()
            summary["errors"].append(f"{row.guest_name}: unvollständig")
            continue
        existing = Allocation.objects.filter(
            member=row.chosen_member, quarter=row.chosen_quarter,
            start=row.arrival, end=row.departure).first()
        if existing:
            row.allocation = existing
            row.status = Beds24ImportRow.IMPORTED
            row.note = "bereits vorhanden (nicht doppelt angelegt)"
        else:
            row.allocation = Allocation.objects.create(
                member=row.chosen_member, quarter=row.chosen_quarter,
                start=row.arrival, end=row.departure, persons=row.persons or 1,
                source="import", provisional=False)
            row.status = Beds24ImportRow.IMPORTED
        row.save()
        summary["imported"] += 1
    batch.n_imported = batch.rows.filter(status=Beds24ImportRow.IMPORTED).count()
    batch.save(update_fields=["n_imported"])
    return summary
