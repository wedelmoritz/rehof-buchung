"""Views der Buchungs-App. Bewusst dünn – Logik liegt im Service-Layer.

Seitenstruktur:
  * overview  – Community-Übersicht (wer ist wann da), eigene hervorgehoben.
  * book      – „Buchen“: eigener Kalender + Spontanbuchung + eigene Buchungen.
  * wishlist  – „Wunschliste fürs nächste Jahr“: Wünsche fürs Losverfahren.
  * transfer  – Tage an ein anderes Mitglied übertragen.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib.auth.forms import PasswordChangeForm
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from csp.decorators import csp_replace
from django_ratelimit.decorators import ratelimit

from .forms import (
    EmailChangeForm, ProfileForm, RegistrationForm, TransferForm, WishForm,
)
from .models import Allocation, BookingPeriod, Member, Quarter, Wish
from . import services as svc
from . import authz
from .validation import strip_controls


# Obergrenze für hochgeladene Dateien (Kontoauszug/Beds24-CSV) – Schutz vor
# versehentlichem Speicher-DoS durch riesige Uploads.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Pastell-Palette zur Unterscheidung der Mitglieder in der Übersicht.
MEMBER_COLORS = [
    "#cfe6c7", "#f6dcc0", "#d9e3f3", "#f3d9e2", "#e7dcf0", "#cfe7e6",
    "#f7eccc", "#e0e8c8", "#f1d7d0", "#d6e6da", "#ecd9c4", "#dde0ee",
]


def healthz(request):
    """Health-Check für Container-Healthcheck und externes Uptime-Monitoring:
    prüft die DB-Erreichbarkeit (ein trivialer Query). Ohne Login, ohne
    Aktivierungs-Sperre. 200 = ok, 503 = DB nicht erreichbar."""
    from django.db import connection
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


def _current_member(request) -> Member | None:
    return getattr(request.user, "member", None)


def _block_if_not_bookable(request):
    """Defense-in-depth (ADR 0087): passive/ausgeschiedene Mitglieder dürfen die
    Buchungs-Seiten (Buchen/Wunschliste/Übertragen) NICHT nutzen – auch nicht über
    die direkte URL. Gibt ein Redirect-Response zurück, wenn gesperrt, sonst None."""
    member = _current_member(request)
    if member is not None and not member.can_book:
        messages.info(request, "Dein Konto ist derzeit nicht buchungsberechtigt "
                      "(passives/ausgeschiedenes Mitglied). Der Hofladen steht dir "
                      "weiterhin offen.")
        return redirect("overview" if member.has_bookings else "shop_index")
    return None


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def _parse_booking_post(request):
    """Liest quarter/start/end/persons aus einem Buchungs- oder Warteformular."""
    try:
        quarter = Quarter.objects.get(id=request.POST.get("quarter"), active=True)
    except (Quarter.DoesNotExist, ValueError, TypeError):
        return None, None, None, None, "Quartier nicht gefunden."
    start = _parse_date(request.POST.get("start"))
    end = _parse_date(request.POST.get("end"))
    if not start or not end:
        return None, None, None, None, "Ungültiger Zeitraum."
    try:
        persons = int(request.POST.get("persons", "1"))
    except (TypeError, ValueError):
        persons = 0
    return quarter, start, end, persons, None


def _month_from_request(request, today, default_year=None, default_month=None):
    """Liest year/month aus GET (oder POST); Fallback auf den angegebenen
    Standardmonat bzw. den aktuellen Monat."""
    dy = default_year or today.year
    dm = default_month or today.month
    src = request.POST if request.method == "POST" else request.GET
    try:
        year = int(src.get("year", dy))
        month = int(src.get("month", dm))
        if not (1 <= month <= 12):
            year, month = dy, dm
    except (TypeError, ValueError):
        year, month = dy, dm
    return year, month


def _cal_nav(cal) -> dict:
    """Monats-/Jahres-Listen für das einheitliche Kalender-Navigations-Dropdown."""
    if not cal:
        return {"months": [], "years": []}
    months = [{"num": i, "name": svc.GERMAN_MONTHS[i]} for i in range(1, 13)]
    yr = cal["year"]
    return {"months": months, "years": list(range(yr - 2, yr + 3))}


def _redirect_month(name: str, year, month):
    return redirect(f"{reverse(name)}?year={year}&month={month}")


# --------------------------------------------------------------------------- #
# Übersicht (Community)
# --------------------------------------------------------------------------- #

@login_required
def overview(request):
    """Wer hat im Monat was gebucht? Eigene Buchungen sind hervorgehoben;
    über die Navigation lassen sich auch die kommenden Monate ansehen."""
    member = _current_member(request)
    today = date.today()
    if request.method == "POST" and member and \
            request.POST.get("action") == "read_notifications":
        svc.mark_notifications_read(member)
        return redirect("overview")
    year, month = _month_from_request(request, today)
    cal = svc.build_community_calendar(member, year, month)
    from .permissions import is_verwaltung
    is_mgmt = is_verwaltung(request.user)
    # Belegungsplan (Tape-Chart) ist der Standard (ADR 0083); das Monatsraster gibt
    # es weiter über ?view=grid (ADR 0059).
    view_mode = "grid" if request.GET.get("view") == "grid" else "timeline"

    # Jedem vorkommenden Mitglied eine feste Pastellfarbe geben (Gemeinschaftsaspekt).
    # Nur zum Einfärben der Balken – KEINE separate Legende mehr (der Name steht auf
    # dem Balken + Tooltip + Klick fürs Tagesdetail; die Legende war redundant).
    color_map: dict[int, str] = {}

    def _assign(mid, who, mine):
        if mid not in color_map:
            color_map[mid] = MEMBER_COLORS[len(color_map) % len(MEMBER_COLORS)]
        return color_map[mid]

    # Tape-Chart-Achse: Startdatum + Bereich 1/2/4 Wochen (#41). Default ist der
    # **Vortag** (heute − 1), damit der Belegungs-Übergang (gestern → heute) direkt
    # sichtbar ist; ein explizites `from`/„Heute" nutzt weiterhin genau dieses Datum.
    anchor = _parse_date(request.GET.get("from")) or (today - timedelta(days=1))
    try:
        weeks = int(request.GET.get("weeks", 2))
    except (TypeError, ValueError):
        weeks = 2
    weeks = weeks if weeks in (1, 2, 4) else 2

    timeline = None
    if view_mode == "timeline":
        timeline = svc.build_occupancy_timeline(
            member, anchor, weeks * 7, management=is_mgmt)
        for grp in timeline["groups"]:
            for row in grp["rows"]:
                for bar in row["bars"]:
                    bar["color"] = (timeline["extern_color"] if bar["external"]
                                    else _assign(bar["member_id"], bar["who"], bar["mine"]))
    else:
        for week in cal["weeks"]:
            for d in week:
                for b in d["bookings"]:
                    if b.get("external"):
                        continue  # Externe: feste Farbe (in services gesetzt)
                    b["color"] = _assign(b["member_id"], b["who"], b["mine"])

    # Query-String, der die Plan-Position (Zeitstrahl vs. Monat) beim Tag-Klick hält.
    if view_mode == "timeline":
        plan_qs = f"from={anchor:%Y-%m-%d}&weeks={weeks}"
    else:
        plan_qs = f"year={cal['year']}&month={cal['month']}&view=grid"

    sel_day = _parse_date(request.GET.get("day"))
    detail = svc.day_detail(member, sel_day, management=is_mgmt) if sel_day else None
    # Wunsch-Fenster ODER Entzerrungsphase (ADR 0101) – in beiden zeigt die Übersicht
    # den Los-Status-Chip und (falls nichts eingereicht) den Erinnerungs-Chip.
    open_period = BookingPeriod.objects.filter(status__in=[
        BookingPeriod.WISHES_OPEN, BookingPeriod.WISHES_REVIEW]).first()
    return render(request, "booking/overview.html", {
        "member": member,
        "cal": cal,
        "timeline": timeline,
        "view_mode": view_mode,
        "today": today,
        "year": today.year,
        "sel_day": sel_day,
        "detail": detail,
        "is_mgmt": is_mgmt,
        "plan_qs": plan_qs,
        "weeks": weeks,
        "nav_qs": "&view=grid" if view_mode == "grid" else "",
        "show_today": True,
        "agenda": svc.week_agenda(member, today, 7),
        **_cal_nav(cal),
        "winter": svc.winter_usage(member) if member else None,
        "weekend": svc.weekend_usage(member) if member else None,
        "nights_remaining": (
            member.nights_remaining_in_year(today.year) if member else 0
        ),
        "notifications": svc.unread_notifications(member),
        "open_period": open_period,
        "review_phase": bool(open_period
                             and open_period.status == BookingPeriod.WISHES_REVIEW),
        # Hat DIESES Mitglied schon Wünsche eingereicht? Wenn nicht, weist die
        # Übersicht bis zum Losdatum darauf hin (ADR 0080).
        "wish_submitted": bool(member and open_period and Wish.objects.filter(
            member=member, period=open_period, submitted=True).exists()),
        "released_windows": BookingPeriod.objects.filter(
            status=BookingPeriod.FREE_BOOKING, end__gte=today).order_by("start"),
    })


# --------------------------------------------------------------------------- #
# Buchen
# --------------------------------------------------------------------------- #

def _book_redirect(year, month, persons, accessible):
    url = f"{reverse('book')}?year={year}&month={month}&persons={persons}"
    if accessible:
        url += "&accessible=1"
    return redirect(url)


@login_required
def book_confirm(request):
    """Bestätigungsschritt vor der Buchung: Unterkunft & Zeitraum prüfen,
    Personen/Begleitung angeben, optional Endreinigung mitbuchen, verbleibende
    Tage sehen – erst „Bestätigen“ legt die Buchung an."""
    from shop.models import Product
    from shop import services as shop_svc
    if (blocked := _block_if_not_bookable(request)) is not None:
        return blocked

    member = _current_member(request)
    if not member:
        return redirect("overview")

    src = request.POST if request.method == "POST" else request.GET
    quarter = Quarter.objects.filter(id=src.get("quarter"), active=True).first()
    start = _parse_date(src.get("start"))
    end = _parse_date(src.get("end"))
    try:
        persons = int(src.get("persons") or 0)
    except (TypeError, ValueError):
        persons = 0

    if not quarter or not start or not end or end <= start:
        messages.error(request, "Buchung nicht möglich – bitte Auswahl wiederholen.")
        return redirect("book")

    nights = (end - start).days
    if not svc.range_is_released(quarter, start, end):
        messages.error(request, "Dieser Zeitraum ist nicht (durchgängig) buchbar.")
        return redirect("book")
    if not svc.quarter_is_free(quarter, start, end):
        messages.error(request, f"{quarter.name} ist in diesem Zeitraum bereits belegt.")
        return redirect("book")

    allow_under = svc.undersized_allowed()
    # Ohne Richtlinie auf den ausgelegten Rahmen klemmen; mit Richtlinie bleibt die
    # gewählte Personenzahl erhalten (außerhalb des Rahmens, deutlich markiert).
    if not allow_under:
        persons = max(quarter.min_occupancy, min(persons, quarter.max_occupancy))
    persons = max(1, persons)
    outside = not (quarter.min_occupancy <= persons <= quarter.max_occupancy)
    # Harte Kopplung (ADR 0076): außerhalb des Rahmens nur, wenn nichts Passendes
    # mehr frei ist – sonst Buchung sperren und auf die passende Unterkunft verweisen.
    person_block = None
    undersized = False
    if outside:
        # Barrierefrei-Bedarf berücksichtigen (#17/ADR 0078): bei einer barrierefreien
        # Unterkunft zählen nur andere barrierefreie freie Unterkünfte als „passend".
        if svc.has_fitting_free_quarter(start, end, persons,
                                        need_accessible=quarter.accessible):
            person_block = ("Für diese Personenzahl ist noch eine passende "
                            "Unterkunft frei – bitte diese buchen.")
        else:
            undersized = True

    remaining_now = member.nights_remaining_in_year(start.year)
    # Mitbuchbare Dienstleistungen (z.B. Endreinigung) – Verfügbarkeit am Abreisetag.
    offers = [
        {"p": p, "available": p.available_on(end)}
        for p in Product.objects.filter(active=True, book_with_stay=True)
        .order_by("sort_order", "name")
    ]

    # Mitglieds-Anteile des Nutzers: nur bei Mehrfach-Tandem (>1) muss die Person
    # wählen, welchem Anteil die Buchung zugerechnet wird (ADR 0066). Sonst
    # automatisch (eindeutiger Anteil).
    memberships = member.memberships if member else []

    if request.method == "POST" and request.POST.get("action") == "confirm":
        companions = request.POST.get("companions", "").strip()
        special = request.POST.get("special_requests", "").strip()
        alloc, err = svc.book_spontaneous(
            member, quarter, start, end, persons, companions=companions,
            membership_id=request.POST.get("membership") or None,
            special_requests=special)
        if not alloc:
            messages.error(request, err or "Buchung nicht möglich.")
        else:
            added, requested = [], []
            for o in offers:
                if request.POST.get(f"service_{o['p'].id}") and o["available"]:
                    if o["p"].needs_approval:
                        # Bestätigungspflichtig (z.B. Endreinigung, ADR 0081):
                        # nur ANFRAGEN – die Betriebsleitung bestätigt/lehnt ab.
                        sr, _serr = shop_svc.request_service(
                            member, o["p"], alloc, end)
                        if sr:
                            requested.append(o["p"].name)
                    else:
                        # Direkt als bestätigter Einkauf (nicht im Warenkorb),
                        # verknüpft mit der Buchung (für die Reinigungsliste).
                        item, _serr = shop_svc.purchase_service(
                            member, o["p"], 1, service_date=end, allocation=alloc)
                        if item:
                            added.append(o["p"].name)
            msg = f"Gebucht: {quarter.name}, {start} – {end} ({persons} Pers.)."
            if added:
                msg += (" Zusätzlich gebucht: " + ", ".join(added)
                        + " (wird über den Hofladen abgerechnet).")
            if requested:
                msg += (" Angefragt (Bestätigung durch die Betriebsleitung): "
                        + ", ".join(requested) + ".")
            messages.success(request, msg)
            return redirect("my_bookings")

    # Lückenfüllung hebt Mindestnächte + Spontan-Vorausfrist auf (ADR 0075).
    gap_fill = svc.gap_fill_allowed(quarter, start, end)
    block_reason = svc.schedule_blocker(
        member, start, end, skip_min_nights=gap_fill, skip_lead=gap_fill)
    return render(request, "booking/book_confirm.html", {
        "member": member, "quarter": quarter, "start": start, "end": end,
        "nights": nights, "persons": persons,
        "remaining_now": remaining_now,
        "remaining_after": remaining_now - nights,
        "enough_days": remaining_now >= nights,
        "min_nights": svc.min_nights_for_range(start, end),
        "gap_fill": gap_fill,
        "block_reason": block_reason,
        "person_block": person_block,
        "can_book": block_reason is None and person_block is None,
        "high_demand": svc.high_demand_periods(start, end),
        "undersized": undersized,
        "allow_under": allow_under,
        "offers": offers,
        "memberships": memberships,
    })


@login_required
def book(request):
    """Klick-Buchung: Personen + Barrierefrei oben einstellen, im Ampel-Kalender
    Anreise/Abreise wählen, dann passendes Quartier buchen (oder Warteliste)."""
    if (blocked := _block_if_not_bookable(request)) is not None:
        return blocked
    member = _current_member(request)
    today = date.today()
    year, month = _month_from_request(request, today)

    try:
        persons = max(1, int(request.GET.get("persons") or request.POST.get("persons") or 2))
    except (TypeError, ValueError):
        persons = 2
    need_accessible = (request.GET.get("accessible") == "1") or \
        (request.POST.get("accessible") == "1")

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        p_year = request.POST.get("year", year)
        p_month = request.POST.get("month", month)

        if action == "book":
            quarter, start, end, persons_in, err0 = _parse_booking_post(request)
            if err0:
                messages.error(request, err0)
            else:
                alloc, err = svc.book_spontaneous(member, quarter, start, end, persons_in)
                messages.success(
                    request,
                    f"Gebucht: {quarter.name}, {start} – {end} ({persons_in} Pers.).") \
                    if alloc else messages.error(request, err or "Buchung nicht möglich.")
            return _book_redirect(p_year, p_month, persons, need_accessible)

        if action == "waitlist":
            quarter, start, end, persons_in, err0 = _parse_booking_post(request)
            if err0:
                messages.error(request, err0)
            else:
                entry, err = svc.add_waitlist_entry(member, quarter, start, end, persons_in)
                messages.success(
                    request,
                    f"Auf die Warteliste gesetzt: {quarter.name}, {start} – {end}. "
                    f"Du wirst benachrichtigt, sobald der Zeitraum frei wird.") \
                    if entry else messages.error(request, err or "Warteliste nicht möglich.")
            return _book_redirect(p_year, p_month, persons, need_accessible)

        if action == "read_notifications":
            svc.mark_notifications_read(member)
            return _book_redirect(p_year, p_month, persons, need_accessible)

        return _book_redirect(p_year, p_month, persons, need_accessible)

    # --- GET: Kalender + Auswahl ---
    sel_start = _parse_date(request.GET.get("start"))
    sel_end = _parse_date(request.GET.get("end"))
    if sel_start and sel_end and sel_end <= sel_start:
        sel_end = None
    cal = svc.build_booking_calendar(member, year, month, sel_start, sel_end) \
        if member else None

    # Query-Suffix, der Personenzahl/Filter UND Auswahl über die Monats-
    # Navigation hinweg erhält (damit auch Buchungen über Monatsgrenzen gehen).
    sel_qs = f"&persons={persons}"
    if need_accessible:
        sel_qs += "&accessible=1"
    if sel_start:
        sel_qs += f"&start={sel_start.isoformat()}"
    if sel_end:
        sel_qs += f"&end={sel_end.isoformat()}"

    eff_start = sel_start if member else None    # für die Auswahl-Leiste
    eff_end = None
    suitable, maybe_unsuitable, occ_quarters, unavail_quarters = [], [], [], []
    range_min_nights = 0
    too_short = False
    not_enough_days = False
    days_remaining_year = 0
    high_demand = []
    is_group = False
    range_reason = None
    # Kandidaten erst zeigen, wenn BEIDE Daten gewählt sind (Feedback #14): mit nur
    # der Anreise gäbe es sonst eine irreführende 1-Nacht-Vorschau.
    if member and sel_start and sel_end:
        eff_start, eff_end = sel_start, sel_end
        nights = (eff_end - eff_start).days
        range_min_nights = svc.min_nights_for_range(eff_start, eff_end)
        too_short = nights < range_min_nights
        days_remaining_year = member.nights_remaining_in_year(eff_start.year)
        not_enough_days = nights > days_remaining_year
        high_demand = svc.high_demand_periods(eff_start, eff_end)
        is_group = svc.is_group_booking(persons)
        free_quarters, occ_quarters = svc.split_quarters_for_range(eff_start, eff_end)
        # Nicht-buchbare Quartiere (Saison/nicht freigeschaltet) ausgegraut zeigen (B6).
        unavail_quarters = svc.unavailable_quarters_for_range(eff_start, eff_end)
        # Termin-/Regel-/Budget-Grund ist quartiers-unabhängig → einmal berechnen,
        # plus die Variante ohne Mindestnächte/Vorausfrist für Lückenfüller (ADR 0075).
        reason = svc.schedule_blocker(member, eff_start, eff_end)
        range_reason = reason        # quartiers-unabhängig → einmal oben anzeigen (#13)
        waived = svc.schedule_blocker(member, eff_start, eff_end,
                                      skip_min_nights=True, skip_lead=True)
        # Lückenfüllung kann nur helfen, wenn der allgemeine Grund eben gerade
        # Mindestnächte/Vorausfrist ist (sonst bleibt der Grund bestehen).
        gap_relevant = reason is not None and waived is None
        allow_under = svc.undersized_allowed()
        # Außerhalb des Rahmens nur, wenn KEINE passende Unterkunft frei ist (harte
        # Kopplung „alles andere belegt", ADR 0076). free_quarters ist bereits die
        # freigeschaltete+freie Menge → kein zusätzlicher DB-Zugriff.
        has_fitting = any(q.min_occupancy <= persons <= q.max_occupancy
                          for q in free_quarters)
        for q in free_quarters:
            fits_persons = q.min_occupancy <= persons <= q.max_occupancy
            # Außerhalb des Rahmens (zu viele ODER zu wenige) buchbar, wenn erlaubt
            # UND nichts Passendes mehr frei ist.
            undersized = (not fits_persons) and allow_under and not has_fitting
            fits_access = (not need_accessible) or q.accessible
            gap_fill = gap_relevant and svc.gap_fill_allowed(q, eff_start, eff_end)
            q_reason = waived if gap_fill else reason
            info = {
                "q": q, "reason": q_reason, "gap_fill": gap_fill,
                "group_pref": is_group and q.prefer_for_groups,
                "fits_persons": fits_persons, "fits_access": fits_access,
                "undersized": undersized,
                # Buchbar trotz zu kleiner Unterkunft (mit Hinweis); zu große
                # Unterkunft (zu wenige Personen) bleibt gesperrt.
                "bookable": q_reason is None and (fits_persons or undersized),
            }
            if fits_persons and fits_access and q_reason is None:
                suitable.append(info)
            else:
                maybe_unsuitable.append(info)
        # Gruppen: Wohnungen des Stallgebäudes zuerst anbieten (sanft, ADR 0075).
        if is_group:
            suitable.sort(key=lambda i: (not i["group_pref"], i["q"].name))
    has_group_pref = is_group and any(i["group_pref"] for i in suitable)
    # Kurze, beidseitig geschlossene freie Lücken zum Lückenfüllen (#16b/ADR 0078):
    # anklickbar, passend zu Personenzahl/Barrierefrei. Die nächsten Wochen ab heute
    # (nicht nur der laufende Monat). Wenige Abfragen (Belegung einmal geladen); die
    # Liste steht eingeklappt, daher bleibt die Seite trotzdem kompakt.
    short_gaps = svc.short_free_gaps(persons, need_accessible) if member else []

    return render(request, "booking/book.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "persons": persons,
        "need_accessible": need_accessible,
        "sel_qs": sel_qs,
        "nav_qs": sel_qs,
        "show_today": True,
        **_cal_nav(cal),
        "sel_start": sel_start,
        "sel_end": sel_end,
        "eff_start": eff_start,
        "eff_end": eff_end,
        "nights_selected": (eff_end - eff_start).days if eff_start and eff_end else 0,
        "range_min_nights": range_min_nights,
        "too_short": too_short,
        "not_enough_days": not_enough_days,
        "range_reason": range_reason,
        "days_remaining_year": days_remaining_year,
        "suitable": suitable,
        "maybe_unsuitable": maybe_unsuitable,
        "occ_quarters": occ_quarters,
        "unavail_quarters": unavail_quarters,
        "high_demand": high_demand,
        "is_group": is_group,
        "has_group_pref": has_group_pref,
        "short_gaps": short_gaps,
        "winter": svc.winter_usage(member) if member else None,
        "weekend": svc.weekend_usage(member) if member else None,
        "nights_remaining": member.nights_remaining_in_year(today.year) if member else 0,
        "notifications": svc.unread_notifications(member),
        "released_windows": BookingPeriod.objects.filter(
            status=BookingPeriod.FREE_BOOKING, end__gte=today).order_by("start"),
    })


@login_required
def my_bookings(request):
    """Eigene Buchungen: bevorstehende (mit Storno) und vergangene."""
    member = _current_member(request)
    today = date.today()

    if request.method == "POST" and member:
        action = request.POST.get("action", "")
        if action == "cancel":
            ok, err = svc.cancel_allocation(member, request.POST.get("allocation_id"))
            messages.success(request, "Buchung storniert.") if ok \
                else messages.error(request, err or "Stornierung nicht möglich.")
        elif action == "adjust":
            ns = _parse_date(request.POST.get("new_start"))
            ne = _parse_date(request.POST.get("new_end"))
            nq = None
            qid = request.POST.get("new_quarter")
            if qid:
                from .models import Quarter
                try:
                    nq = Quarter.objects.get(id=qid)
                except (Quarter.DoesNotExist, ValueError, TypeError):
                    nq = None
            try:
                npers = int(request.POST.get("new_persons") or 0) or None
            except (ValueError, TypeError):
                npers = None
            if not ns or not ne:
                messages.error(request, "Bitte An- und Abreise angeben.")
            else:
                ok, err = svc.adjust_allocation(
                    member, request.POST.get("allocation_id"), ns, ne,
                    new_quarter=nq, new_persons=npers)
                messages.success(request, "Buchung angepasst.") if ok \
                    else messages.error(request, err or "Anpassung nicht möglich.")
        elif action == "read_notifications":
            svc.mark_notifications_read(member)
        elif action == "swap_request":
            try:
                mine = member.allocations.get(id=request.POST.get("from_allocation"))
                other = Allocation.objects.select_related("quarter", "member").get(
                    id=request.POST.get("to_allocation"))
            except Allocation.DoesNotExist:
                messages.error(request, "Buchung nicht gefunden.")
            else:
                sr, err = svc.create_swap_request(
                    member, mine, other, request.POST.get("message", "").strip())
                messages.success(request, f"Wechselwunsch an {other.member.display_name} gesendet.") \
                    if sr else messages.error(request, err or "Nicht möglich.")
        elif action == "swap_respond":
            ok, err = svc.respond_swap_request(
                member, request.POST.get("swap_id"),
                request.POST.get("decision") == "accept")
            messages.success(request, "Antwort gesendet.") if ok \
                else messages.error(request, err or "Nicht möglich.")
        elif action == "reloc_respond":
            ok, err = svc.respond_relocation(
                member, request.POST.get("request_id"),
                request.POST.get("decision") == "accept")
            if ok:
                messages.success(request, "Antwort gesendet.")
            else:
                messages.error(request, err or "Nicht möglich.")
        return redirect("my_bookings")

    upcoming, past = [], []
    incoming_swaps = []
    submitted_wishes = []
    my_waitlist = []
    cancellations = []
    wish_period = None
    if member:
        # Dienstleistungs-Anfragen (z.B. Endreinigung) je Buchung mitladen, damit der
        # Status (angefragt/bestätigt/abgelehnt) angezeigt werden kann (#33; 1 Query).
        for a in member.allocations.select_related("quarter").filter(
                provisional=False).order_by("start").prefetch_related(
                "service_requests__product"):
            (upcoming if a.end > today else past).append(a)
        for a in upcoming:
            # Kurzfrist-Storno/Verkürzen (Anreise ≤ Kurzfrist-Grenze): Tage verfallen,
            # falls andere den Zeitraum nicht neu buchen (ADR 0088) – steuert die Warnung.
            a.short_notice = svc.is_short_notice(a.start, today)
            a.service_reqs = list(a.service_requests.all())
            a.waiters = svc.waiters_for_allocation(a)
            a.concurrent = svc.concurrent_split(a)
            a.concurrent_count = len(a.concurrent["exact"]) + len(a.concurrent["overlap"])
            a.min_nights = svc.min_nights_for_range(a.start, a.end)
            # Andere Quartiere, die für den AKTUELLEN Zeitraum + Personen frei
            # sind (für den Unterkunfts-Wechsel im „Buchung ändern“-Bereich).
            a.switch_options = svc.free_quarters_for(
                a.start, a.end, a.persons, exclude_id=a.quarter_id)
            # Unterkunfts-Tausch nur mit exakt gleichem Zeitraum (ADR 0077); der
            # Verschiebe-Tipp wird nur berechnet, wenn weder Tausch- noch freie
            # Wechsel-Option besteht (spart Abfragen). Mitglieder mit Opt-out
            # (#8/ADR 0078) fallen als Tausch-Partner raus – member ist bereits
            # select_related geladen (0 zusätzliche Abfragen).
            a.swap_exact = [c for c in a.concurrent["exact"]
                            if c.member.accept_swap_requests]
            a.swap_shift = None
            if not a.swap_exact and not a.switch_options:
                a.swap_shift = svc.swap_shift_hint(a)
        incoming_swaps = svc.pending_swaps_for(member)
        my_waitlist = list(
            member.waitlist_entries.filter(fulfilled=False, end__gte=today)
            .select_related("quarter").order_by("start"))
        wish_period = BookingPeriod.objects.filter(status__in=[
            BookingPeriod.WISHES_OPEN, BookingPeriod.WISHES_REVIEW,
            BookingPeriod.LOTTERY_READY]).first()
        if wish_period:
            submitted_wishes = list(
                Wish.objects.filter(member=member, period=wish_period, submitted=True)
                .select_related("quarter").order_by("priority", "id"))
        # Kürzlich stornierte Buchungen (#30): zur Sicherheit sichtbar, dass sie raus
        # sind. Nur die jüngsten (90 Tage) – ältere räumt die Aufbewahrung ab.
        cancellations = list(member.cancellations.filter(
            cancelled_at__date__gte=today - timedelta(days=90))[:20])

    y = today.year
    budget_info = None
    if member:
        budget_info = {
            "nominal": member.annual_night_budget,
            "effective": member.effective_annual_budget(y),
            "received": member.nights_received_in_year(y),
            "given": member.nights_given_in_year(y),
            "donated": member.pool_donated_in_year(y),
            "withdrawn": member.pool_received_in_year(y),
        }
    return render(request, "booking/my_bookings.html", {
        "member": member,
        "today": today,
        "booking_year": today.year,
        "nights_remaining": member.nights_remaining_in_year(today.year) if member else 0,
        "nights_used": member.nights_used_in_year(today.year) if member else 0,
        "annual_budget": member.annual_night_budget if member else 0,
        "budget_info": budget_info,
        "upcoming": upcoming,
        "past": past,
        "incoming_swaps": incoming_swaps,
        "relocations": svc.pending_relocation_requests(member) if member else [],
        "submitted_wishes": submitted_wishes,
        "my_waitlist": my_waitlist,
        "cancellations": cancellations,
        "wish_period": wish_period,
        "notifications": svc.unread_notifications(member),
    })


# --------------------------------------------------------------------------- #
# Wunschliste fürs nächste Jahr
# --------------------------------------------------------------------------- #

@login_required
def wishlist(request):
    """Wunschliste fürs Losverfahren der nächsten Periode. Anders als beim
    Buchen dürfen Wünsche bewusst miteinander kollidieren."""
    if (blocked := _block_if_not_bookable(request)) is not None:
        return blocked
    member = _current_member(request)
    today = date.today()
    # Wunsch-Fenster ODER Entzerrungsphase (ADR 0101): in beiden ist die Wunschliste
    # bearbeitbar (in der Review-Phase zum Anpassen/Entzerren).
    period = BookingPeriod.objects.filter(status__in=[
        BookingPeriod.WISHES_OPEN, BookingPeriod.WISHES_REVIEW]).first()
    # Der Wunsch-Kalender startet beim Zeitraum der Periode (nicht „heute“).
    dy = period.start.year if period else None
    dm = period.start.month if period else None
    year, month = _month_from_request(request, today, dy, dm)

    if request.method == "POST" and member and \
            request.POST.get("action") == "read_notifications":
        svc.mark_notifications_read(member)
        return _redirect_month("wishlist", request.POST.get("year", year),
                               request.POST.get("month", month))

    if request.method == "POST" and member and period:
        action = request.POST.get("action", "")
        p_year = request.POST.get("year", year)
        p_month = request.POST.get("month", month)
        is_submitted = Wish.objects.filter(
            member=member, period=period, submitted=True).exists()

        if action == "add_wish" and not is_submitted:
            form = WishForm(request.POST)
            if form.is_valid():
                _wish, werr = svc.add_wish(
                    member, period, form.cleaned_data["quarter"],
                    form.cleaned_data["start"], form.cleaned_data["end"],
                    membership_id=request.POST.get("membership") or None)
                if werr:
                    messages.error(request, werr)
                else:
                    messages.success(
                        request,
                        f"Wunsch „{_wish.quarter.name}“ eingetragen "
                        f"({_wish.start:%d.%m.}–{_wish.end:%d.%m.}). "
                        "Noch nicht eingereicht – unten in der Wunschliste "
                        "ordnen und am Ende einreichen.")
            else:
                messages.error(request, "Bitte einen gültigen Wunsch eingeben.")
            # Auswahl im Kalender erhalten, damit man weitere Wünsche eintragen kann
            url = f"{reverse('wishlist')}?year={p_year}&month={p_month}"
            if request.POST.get("start"):
                url += f"&start={request.POST['start']}"
            if request.POST.get("end"):
                url += f"&end={request.POST['end']}"
            return redirect(url)

        if action == "delete_wish" and not is_submitted:
            svc.delete_wish(member, period, request.POST.get("wish_id"))
            return _redirect_month("wishlist", p_year, p_month)

        if action == "move_wish" and not is_submitted:
            svc.move_wish(member, period, request.POST.get("wish_id"),
                          request.POST.get("direction", "up"))
            return _redirect_month("wishlist", p_year, p_month)

        if action == "reorder" and not is_submitted:
            ids = [x for x in request.POST.get("order", "").split(",") if x]
            svc.reorder_wishes(member, period, ids)
            return _redirect_month("wishlist", p_year, p_month)

        if action == "submit_wishlist" and not is_submitted:
            n, serr = svc.submit_wishlist(member, period)
            if serr:
                messages.error(request, serr)
            else:
                messages.success(
                    request, f"{n} Wunsch/Wünsche in den Lostopf eingereicht.")
            return _redirect_month("wishlist", p_year, p_month)

        if action == "withdraw_wishlist":
            svc.withdraw_wishlist(member, period)
            messages.info(request, "Wünsche zurückgezogen – wieder bearbeitbar.")
            return _redirect_month("wishlist", p_year, p_month)

        return _redirect_month("wishlist", p_year, p_month)

    wishes = []
    wishlist_submitted = False
    wish_nights = 0
    if member and period:
        wishes = list(
            Wish.objects.filter(member=member, period=period)
            .select_related("quarter", "membership").order_by("priority", "id")
        )
        wishlist_submitted = any(w.submitted for w in wishes) and len(wishes) > 0
        wish_nights = sum(w.nights for w in wishes)
        # Entzerrungs-Hinweis JE WUNSCH (P2.4-Erweiterung): für jeden sehr beliebten
        # Wunsch zeigt ein markanter Hinweis weniger beliebte Alternativen mit
        # besseren Chancen – ein leicht anderer Zeitraum für dieselbe Unterkunft
        # UND/ODER ein gleichwertiges Quartier zur gleichen Zeit (Frontend-Wortwahl
        # positiv, ADR 0072). Nur solange änderbar. Effizient: 2 Abfragen gesamt.
        if not wishlist_submitted:
            alts = svc.wish_alternatives(period, member, wishes)
            for w in wishes:
                w.alt = alts.get(w.id)
        # Gewinn-Prognose je eingereichtem Wunsch (ADR 0101): realistische Chance als
        # qualitatives Band. Nur sinnvoll für eingereichte Wünsche (die im Lostopf
        # sind) und im Wunsch-Fenster/der Entzerrungsphase (kurz gecacht, ein Aufruf).
        if wishlist_submitted:
            prog = svc.wish_prognosis(period)
            for w in wishes:
                w.prognosis = prog.get(w.id) if w.submitted else None
        # Sanfter Hinweis JE WUNSCH bei überlappenden Wünschen fürs SELBE Quartier
        # (Feedback #2b): überlappende Wünsche bleiben bewusst zulässig (das
        # Losverfahren berücksichtigt jeweils nur einen), aber ein Hinweis macht die
        # Doppelung sichtbar. Rein aus den bereits geladenen Wünschen (0 Abfragen).
        for w in wishes:
            w.overlap_same_quarter = any(
                o.id != w.id and o.quarter_id == w.quarter_id
                and o.start < w.end and o.end > w.start for o in wishes)

    # Kalender + Auswahl (analog zum Buchen, aber Wünsche dürfen kollidieren)
    sel_start = _parse_date(request.GET.get("start"))
    sel_end = _parse_date(request.GET.get("end"))
    if sel_start and sel_end and sel_end <= sel_start:
        sel_end = None
    cal = svc.build_wish_calendar(member, period, year, month, sel_start, sel_end) \
        if (member and period) else None
    sel_qs = ""
    if sel_start:
        sel_qs += f"&start={sel_start.isoformat()}"
    if sel_end:
        sel_qs += f"&end={sel_end.isoformat()}"

    # Optionale Wunsch-Obergrenze je Periode (Feedback #5, ADR 0078): 0 = unbegrenzt
    # (Standard). Nur ein Singleton-Zugriff, sichtbar gemacht in „Meine Wünsche".
    from .models import BookingPolicy
    wish_cap = BookingPolicy.get_solo().max_wishes_per_period if member and period else 0

    eff_start = eff_end = None
    candidates = []
    high_demand = []
    wish_weekends = svc.wish_weekend_usage(member, period) if member and period else None
    wish_winter = svc.wish_winter_usage(member, period) if member and period else None
    if member and period and sel_start:
        eff_start = sel_start
        eff_end = sel_end if sel_end else sel_start + timedelta(days=1)
        high_demand = svc.high_demand_periods(eff_start, eff_end)
        counts = svc.quarter_wish_counts(period, eff_start, eff_end)
        # Der Entzerrungs-Tipp (P2.4) steht jetzt JE WUNSCH in „Meine Wünsche" –
        # erst wenn ein Wunsch wirklich aufgenommen wurde (verständlicher als unter
        # den Kandidaten). Hier nur noch die Nachfrage-Ampel je Quartier.
        for q in Quarter.objects.filter(active=True).order_by("name"):
            candidates.append({"q": q, "count": counts.get(str(q.id), 0)})

    return render(request, "booking/wishlist.html", {
        "member": member,
        "today": today,
        "period": period,
        "cal": cal,
        "sel_qs": sel_qs,
        "nav_qs": sel_qs,
        "show_today": False,
        **_cal_nav(cal),
        "sel_start": sel_start,
        "sel_end": sel_end,
        "eff_start": eff_start,
        "eff_end": eff_end,
        "nights_selected": (eff_end - eff_start).days if eff_start and eff_end else 0,
        "candidates": candidates,
        "high_demand": high_demand,
        "wish_weekends": wish_weekends,
        "wish_winter": wish_winter,
        "wish_form": WishForm(),
        "memberships": member.memberships if member else [],
        "wishes": wishes,
        "wishlist_submitted": wishlist_submitted,
        # Wunsch-Nachbarn für private Absprachen (ADR 0101): nur bei eingereichten
        # Wünschen; nur Mitglieder, die die Sichtbarkeit nicht abgeschaltet haben.
        "wish_neighbors": (svc.wish_neighbors(period, member)
                           if member and period and wishlist_submitted else []),
        "coordination_opt_out": bool(member and member.coordination_opt_out),
        "wish_nights": wish_nights,
        "wish_budget": member.wish_night_budget if member else 0,
        "wish_cap": wish_cap,
        # Entzerrungsphase (ADR 0101): Phasen-Marken für den Status-Hinweis.
        "review_phase": bool(period and period.status == BookingPeriod.WISHES_REVIEW),
        # Anonyme Nachfrage-Heatmap (ADR 0101): welche Quartiere/Monate sind begehrt.
        "demand_grid": svc.wish_demand_grid(period) if period else None,
        "submission_deadline": period.submission_deadline if period else None,
        "draw_at": period.draw_at if period else None,
        "freeze_start": period.freeze_start if period else None,
        "display_frozen": period.display_frozen(timezone.now()) if period else False,
        "notifications": svc.unread_notifications(member),
    })


# --------------------------------------------------------------------------- #
# Tage übertragen
# --------------------------------------------------------------------------- #

# Registrierung gegen Konto-Spam: max. 10 POSTs/Stunde je IP (ADR 0061).
@ratelimit(key="ip", rate="10/h", method="POST", block=True)
def register(request):
    """Selbstregistrierung. Legt nur ein Login-Konto an; das Buchungs-Profil
    (Member) vergibt anschließend die Verwaltung. Bis dahin: Warte-Seite."""
    if request.user.is_authenticated:
        return redirect("overview")
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Die Verwaltung benachrichtigen: neues Konto wartet auf Zuordnung
            # eines Mitglieds-Anteils (sonst kann die Person nicht buchen).
            svc.notify_admins_new_user(user)
            login(request, user,
                  backend="booking.auth.EmailOrUsernameModelBackend")
            return redirect("pending")
    else:
        form = RegistrationForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def pending(request):
    """Warte-Seite für noch nicht freigeschaltete Konten (kein Mitglieds-Profil)."""
    from .permissions import is_verwaltung
    if _current_member(request) or is_verwaltung(request.user):
        return redirect("overview")
    return render(request, "registration/pending.html", {})


# --------------------------------------------------------------------------- #
# Rechtstexte (öffentlich, ohne Login): Impressum (Pflicht, §5 DDG),
# Datenschutz (DSGVO) und AGB – Inhalte aus den „Rechtliche & Zahlungs-Einstellungen“.
# --------------------------------------------------------------------------- #

def imprint(request):
    from shop.models import ShopConfig
    return render(request, "booking/imprint.html", {"cfg": ShopConfig.get_solo()})


def privacy(request):
    from shop.models import ShopConfig
    cfg = ShopConfig.get_solo()
    return render(request, "booking/legal_text.html", {
        "page_title": "Datenschutzerklärung", "body": cfg.privacy_policy, "cfg": cfg})


def terms(request):
    from shop.models import ShopConfig
    cfg = ShopConfig.get_solo()
    return render(request, "booking/legal_text.html", {
        "page_title": "Allgemeine Geschäftsbedingungen (AGB)",
        "body": cfg.terms_agb, "cfg": cfg})


@login_required
def help_page(request):
    """Erklärseite: Abläufe, Auslosung im Detail, Tage & Anteile, Hofladen.
    Die Buchungsregel-Werte kommen aus der Backend-Konfiguration (ADR 0076)."""
    return render(request, "booking/help.html", {
        "member": _current_member(request),
        "p": svc.booking_policy_summary(),
        "contact_categories": svc.CONTACT_CATEGORIES,
        "help": svc.help_sections(),        # ausgelagerte Prosa (ADR 0093)
    })


@login_required
@require_POST
@ratelimit(key="user", rate="5/h", method="POST", block=True)
def contact_send(request):
    """Kontaktformular (ADR 0091): ein eingeloggtes Mitglied schickt eine Nachricht
    an die passende Rollen-Adresse. Der Text wird literal verschickt (keine SSTI),
    Reply-To ist die eigene Adresse. Rate-limitiert gegen Missbrauch."""
    category = request.POST.get("category", "general")
    message = request.POST.get("message", "")
    if not (message or "").strip():
        messages.error(request, "Bitte gib eine Nachricht ein.")
        return redirect(reverse("help") + "#kontakt")
    mail = svc.send_contact_message(request.user, category, message)
    if mail is None:
        # Nachricht war vorhanden, aber es ist keine Empfänger-Adresse hinterlegt.
        messages.error(
            request, "Im Moment ist keine Kontaktadresse hinterlegt. Bitte wende "
            "dich direkt an die Betriebsleitung.")
    else:
        messages.success(
            request, "Danke! Deine Nachricht ist unterwegs – wir melden uns bei dir.")
    return redirect(reverse("help") + "#kontakt")


@login_required
def profile(request):
    """Eigene Profil-/Rechnungsdaten (Name, Anschrift, IBAN) selbst pflegen sowie
    E-Mail (= Login) und Passwort ändern. Nur die eigenen Daten."""
    member = _current_member(request)
    if not member:
        return redirect("overview")
    form = ProfileForm(instance=member)
    email_form = EmailChangeForm(user=request.user,
                                 initial={"email": request.user.email})
    pw_form = PasswordChangeForm(request.user)
    if request.method == "POST":
        action = request.POST.get("action", "profile")
        if action == "change_email":
            email_form = EmailChangeForm(request.POST, user=request.user)
            if email_form.is_valid():
                email_form.save()
                messages.success(
                    request, "E-Mail geändert. Bitte künftig mit der neuen "
                    "E-Mail anmelden.")
                return redirect("profile")
        elif action == "change_password":
            pw_form = PasswordChangeForm(request.user, request.POST)
            if pw_form.is_valid():
                user = pw_form.save()
                # Session-Hash auffrischen, sonst wird der Nutzer ausgeloggt.
                update_session_auth_hash(request, user)
                messages.success(request, "Passwort geändert.")
                return redirect("profile")
        elif action == "notify_prefs":
            # E-Mail-Benachrichtigungen an/aus (Checkbox). In-App bleibt immer an.
            member.email_opt_in = bool(request.POST.get("email_opt_in"))
            # Tausch-Anfragen an/aus (#8/ADR 0078): steuert, ob andere Mitglieder
            # dieses Konto als Tausch-Partner anfragen dürfen.
            member.accept_swap_requests = bool(request.POST.get("accept_swap_requests"))
            # Absprachen-Sichtbarkeit in der Entzerrungsphase (ADR 0101): Checkbox
            # „sichtbar sein" → opt_out = NICHT angehakt. Default sichtbar.
            member.coordination_opt_out = not bool(
                request.POST.get("coordination_visible"))
            member.save(update_fields=["email_opt_in", "accept_swap_requests",
                                       "coordination_opt_out"])
            messages.success(request, "Einstellungen gespeichert.")
            return redirect("profile")
        elif action == "terminal_prefs":
            # Teilnahme am Hofladen-Terminal selbst an/aus + optional PIN setzen.
            pin = (request.POST.get("pin") or "").strip()
            if pin and not (len(pin) == 6 and pin.isdigit()):
                messages.error(request, "Die PIN muss genau 6 Ziffern haben.")
                return redirect("profile")
            member.terminal_enabled = bool(request.POST.get("terminal_enabled"))
            fields = ["terminal_enabled"]
            if pin:
                member.set_terminal_pin(pin)
                fields.append("terminal_pin")
            member.save(update_fields=fields)
            if not member.terminal_enabled:
                messages.success(request, "Hofladen-Terminal ausgeschaltet – eine "
                                 "gesetzte PIN ist damit inaktiv.")
            elif pin:
                messages.success(request, "Hofladen-Terminal-PIN gespeichert.")
            else:
                messages.success(request, "Einstellung gespeichert.")
            return redirect("profile")
        else:
            form = ProfileForm(request.POST, instance=member)
            if form.is_valid():
                form.save()
                messages.success(request, "Profil gespeichert.")
                return redirect("profile")
    return render(request, "booking/profile.html", {
        "member": member, "form": form,
        "email_form": email_form, "pw_form": pw_form,
    })


@login_required
@require_POST
def push_subscribe(request):
    """Speichert ein Web-Push-Abo (vom Browser per `pushManager.subscribe`).
    Ein Eintrag je Endpoint/Gerät; erneutes Abonnieren aktualisiert die Keys."""
    import json
    from .models import PushSubscription
    member = _current_member(request)
    if not member:
        return JsonResponse({"ok": False}, status=403)
    try:
        data = json.loads(request.body or "{}")
        endpoint = data["endpoint"]
        keys = data.get("keys", {})
        p256dh, auth = keys["p256dh"], keys["auth"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "ungültige Daten"}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"member": member, "p256dh": p256dh, "auth": auth,
                  "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300]})
    import logging
    from urllib.parse import urlsplit
    logging.getLogger("booking.push").info(
        "Push-Abo gespeichert: %s (Mitglied %s).", urlsplit(endpoint).netloc, member.pk)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_unsubscribe(request):
    """Entfernt ein Web-Push-Abo (Browser hat sich abgemeldet)."""
    import json
    from .models import PushSubscription
    member = _current_member(request)
    if not member:
        return JsonResponse({"ok": False}, status=403)
    try:
        endpoint = json.loads(request.body or "{}").get("endpoint", "")
    except ValueError:
        endpoint = ""
    if endpoint:
        # Nur das EIGENE Abo entfernen – kein Löschen fremder Geräte über einen
        # (erratenen) Endpoint (ADR 0061, P3.9).
        PushSubscription.objects.filter(endpoint=endpoint, member=member).delete()
    return JsonResponse({"ok": True})


@login_required
def transfer(request):
    """Tage an ein anderes Mitglied übertragen bzw. in den Solidaritäts-Pool spenden.

    Passive/ausgeschiedene Mitglieder dürfen diese Seite bewusst nutzen, um ihre
    (sonst verfallenden) Tage **abzugeben** – Spenden in den Pool und Übertragen an
    aktive Mitglieder. Nur **Entnehmen** aus dem Pool ist ihnen verwehrt (ADR 0099,
    im Pool-Service erzwungen); Buchen/Wünsche bleiben über `_block_if_not_bookable`
    gesperrt."""
    member = _current_member(request)
    year = date.today().year
    if not member:
        return redirect("overview")

    pending = None
    # P2.7: „Danke sagen" für eine erhaltene Übertragung (idempotent).
    if request.method == "POST" and request.POST.get("action") == "thank":
        ok, err = svc.thank_for_transfer(member, request.POST.get("transfer_id"))
        messages.success(request, "Dein Dank wurde übermittelt. 🌻") if ok \
            else messages.error(request, err or "Nicht möglich.")
        return redirect("transfer")
    # P2.5: Solidaritäts-Pool – spenden / (bei Bedarf, gedeckelt) entnehmen.
    if request.method == "POST" and request.POST.get("action") in ("pool_donate",
                                                                    "pool_withdraw"):
        nights = request.POST.get("nights")
        if request.POST["action"] == "pool_donate":
            _e, err = svc.pool_donate(member, nights, year)
            ok_msg = "Danke! Deine Tage liegen jetzt im Solidaritäts-Pool. 🌻"
        else:
            _e, err = svc.pool_withdraw(member, nights, year)
            ok_msg = "Tage aus dem Pool entnommen – sie stehen dir nun zur Verfügung."
        messages.success(request, ok_msg) if _e \
            else messages.error(request, err or "Nicht möglich.")
        return redirect("transfer")
    form = TransferForm(exclude_member=member)
    if request.method == "POST":
        form = TransferForm(request.POST, exclude_member=member)
        if form.is_valid():
            to_member = form.cleaned_data["to_member"]
            nights = form.cleaned_data["nights"]
            note = form.cleaned_data.get("note", "")
            if request.POST.get("action") == "confirm":
                t, err = svc.transfer_nights(member, to_member, nights, year, note=note)
                if t:
                    messages.success(
                        request, f"{t.nights} Tage an {t.to_member} übertragen.")
                    return redirect("transfer")
                messages.error(request, err or "Übertragung nicht möglich.")
            else:
                # Vorschau: erst bestätigen lassen (Empfänger + Disclaimer zeigen).
                remaining = member.nights_remaining_in_year(year)
                if nights > remaining:
                    messages.error(
                        request, f"Du hast nur noch {remaining} Tage übrig.")
                else:
                    pending = {"to_member": to_member, "nights": nights, "note": note}

    outgoing = member.transfers_out.filter(year=year).select_related("to_member")
    incoming = member.transfers_in.filter(year=year).select_related("from_member")
    return render(request, "booking/transfer.html", {
        "form": form, "member": member, "year": year,
        "remaining": member.nights_remaining_in_year(year),
        "outgoing": outgoing, "incoming": incoming, "pending": pending,
        "pool": svc.pool_status(member, year),
        "my_pool_entries": member.pool_entries.filter(year=year),
    })


@login_required
# Typeahead-Suche gegen Verzeichnis-Scraping bremsen (je angemeldetem Konto).
@ratelimit(key="user", rate="60/m", block=True)
def member_search(request):
    """Typeahead für „Tage übertragen": passende Mitglieder ab 3 Zeichen.
    Sucht über Anzeigename, Benutzername, E-Mail, Vor- und Nachname (das eigene
    Konto und externe Gäste ausgenommen)."""
    from django.db.models import Q
    member = _current_member(request)
    q = (request.GET.get("q") or "").strip()
    if not member or len(q) < 3:
        return JsonResponse({"results": []})
    # Nur AKTIVE Mitglieder als Empfänger:in vorschlagen (ADR 0087).
    base = Member.objects.filter(is_external=False).exclude(id=member.id)
    qs = (Member.active_members(base=base)
          .filter(Q(display_name__icontains=q)
                  | Q(user__username__icontains=q)
                  | Q(user__email__icontains=q)
                  | Q(user__first_name__icontains=q)
                  | Q(user__last_name__icontains=q))
          .select_related("user").order_by("display_name")[:20])
    results = [{
        "id": m.id,
        "name": m.display_name,
        "username": m.user.username if m.user_id else "",
        "full_name": m.user.get_full_name() if m.user_id else "",
    } for m in qs]
    return JsonResponse({"results": results})


# --------------------------------------------------------------------------- #
# Verwaltungs-Dashboard: Zugriff je Unterseite über die Capability der Rolle
# (booking.authz, ADR 0100) – Enforcement per @requires_capability an den Views.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Verwaltung: Handlungsbedarf-Dashboard + eigene Unterseiten (ADR 0085).
# Statt Tabs auf einer langen Seite ist jede Sektion eine echte Seite (eigener
# Menü-Eintrag); das Dashboard fasst nur „jetzt handeln" zusammen.
# --------------------------------------------------------------------------- #

def _verw_month(request):
    today = date.today()
    ny, nm = svc.next_month(today)
    year, month = _month_from_request(request, today, ny, nm)
    m_from, m_to = svc.month_bounds(year, month)
    only_cleaning = (request.GET.get("only_cleaning") == "1"
                     or request.POST.get("only_cleaning") == "1")
    return today, year, month, m_from, m_to, only_cleaning


def _verw_nav_ctx(request, today, year, month):
    """Gemeinsamer Kontext für Monatswahl + Backend-Deeplink."""
    from .models import OpsConfig
    return {
        "today": today, "year": year, "month": month,
        "month_label": svc.month_label(year, month),
        "months": [{"num": i, "name": svc.MONTHS_DE[i]} for i in range(1, 13)],
        "years": list(range(today.year - 1, today.year + 3)),
        "beds24_enabled": OpsConfig.get_solo().beds24_import_enabled,
    }


def _serialize_block_conflict(q, s, e, reason, info):
    """Packt den Sperrzeit-Konflikt in ein session-taugliches Dict (ADR 0097) für das
    Konflikt-Panel auf der Sperrzeiten-Seite (POST→Redirect→GET)."""
    sug = info["suggestion"]
    return {
        "quarter_id": q.id, "quarter": q.name,
        "start": s.isoformat(), "end": e.isoformat(), "reason": reason,
        "within_notice": info["within_notice"],
        "notice_days": svc.block_min_notice_days(),
        "suggestion": [sug[0].isoformat(), sug[1].isoformat()] if sug else None,
        "allocs": [{"member": a.member.display_name,
                    "start": a.start.isoformat(), "end": a.end.isoformat(),
                    "persons": a.persons,
                    "phone": getattr(a.member, "phone", "") or "",
                    "email": (getattr(a.member.user, "email", "") or "")}
                   for a in info["allocs"]],
        "ext": [{"start": b.start.isoformat(), "end": b.end.isoformat()}
                for b in info["ext"]],
    }


def _verw_post(request, year, month, m_from, m_to, only_cleaning):
    """Zentrale POST-Verarbeitung aller Verwaltungs-Aktionen; leitet danach auf die
    passende Unterseite zurück (Monat/Filter erhalten)."""
    from shop import services as shop_svc
    from shop.models import Invoice
    action = request.POST.get("action")
    target, extra = "dashboard", ""
    if action == "send_cleaning":
        deps = list(svc.departures_in_range(m_from, m_to))
        body = (f"Reinigungsliste {svc.month_label(year, month)}\n"
                f"(Abreisetag = Reinigungstag)\n\n"
                f"{svc.cleaning_text(deps, only_cleaning=only_cleaning)}\n")
        recips = svc.email_cleaning(f"Re:Hof – Reinigungsliste {month:02d}/{year}", body)
        messages.success(request, f"Reinigungsliste an {len(recips)} Empfänger gesendet."
                         if recips else "Keine Empfänger hinterlegt (Betriebs-Einstellungen).")
        target = "verw_reinigung"
    elif action == "send_upcoming":
        allocs = list(svc.arrivals_in_range(m_from, m_to))
        body = (f"Anstehende Buchungen {svc.month_label(year, month)}\n\n"
                f"{svc.bookings_text(allocs)}\n")
        recips = svc.email_admins(f"Re:Hof – Buchungen {month:02d}/{year}", body)
        messages.success(request, f"Übersicht an {len(recips)} Empfänger gesendet."
                         if recips else "Keine Empfänger hinterlegt (Betriebs-Einstellungen).")
        target = "verw_buchungen"
    elif action == "remind_overdue":
        n = shop_svc.remind_overdue()
        messages.success(request, f"{n} Zahlungserinnerung(en) verschickt.")
        target, extra = "verw_rechnungen", f"&inv={request.POST.get('inv', 'overdue')}"
    elif action == "remind_one":
        inv = Invoice.objects.filter(id=request.POST.get("invoice_id")).first()
        if inv and shop_svc.send_payment_reminder(inv):
            messages.success(request, f"{inv.reminder_count}. Zahlungserinnerung zu "
                             f"{inv.number} verschickt.")
        elif inv and not shop_svc.reminder_due(inv):
            messages.info(request, f"Zu {inv.number} wurde erst kürzlich erinnert – "
                          "eine erneute Mahnung ist erst nach dem eingestellten "
                          "Mindestabstand möglich.")
        else:
            messages.info(request, "Erinnerung nicht möglich (Rechnung/Status?).")
        target, extra = "verw_rechnungen", f"&inv={request.POST.get('inv', 'overdue')}"
    elif action in ("confirm_service", "reject_service"):
        from shop.models import ServiceRequest
        sr = ServiceRequest.objects.filter(
            id=request.POST.get("request_id")).select_related(
            "member", "product", "allocation").first()
        if not sr:
            messages.error(request, "Anfrage nicht gefunden.")
        elif action == "confirm_service":
            ok, err = shop_svc.confirm_service_request(sr, by_user=request.user)
            messages.success(request, f"Bestätigt: {sr.product.name} für "
                             f"{sr.member.display_name}.") if ok \
                else messages.error(request, err or "Nicht möglich.")
        else:
            ok, err = shop_svc.reject_service_request(
                sr, by_user=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, f"Abgelehnt: {sr.product.name} für "
                             f"{sr.member.display_name}.") if ok \
                else messages.error(request, err or "Nicht möglich.")
        # Von der Dashboard-Schnellfreigabe zurück aufs Dashboard, sonst zur Reinigung.
        nxt = request.POST.get("next", "")
        target = nxt if nxt in ("dashboard", "verw_reinigung") else "verw_reinigung"
    elif action == "set_note":
        from .models import Allocation
        from . import validation as V
        a = Allocation.objects.filter(id=request.POST.get("alloc_id")).first()
        if a:
            a.internal_note = V.strip_controls(request.POST.get("internal_note", ""),
                                               max_len=500)
            a.save(update_fields=["internal_note"])
            messages.success(request, "Interne Notiz gespeichert.")
        target = "verw_buchungen"
    elif action == "add_block":
        from .models import Quarter
        q = Quarter.objects.filter(id=request.POST.get("quarter")).first()
        s = _parse_date(request.POST.get("start"))
        e = _parse_date(request.POST.get("end"))
        reason = request.POST.get("reason", "")
        request.session.pop("block_conflict", None)
        if not q or not s or not e:
            messages.error(request, "Bitte Quartier, Von- und Bis-Datum angeben.")
        elif e <= s:
            messages.error(request, "Das Bis-Datum muss nach dem Von-Datum liegen.")
        else:
            info = svc.create_quarter_block(q, s, e, reason, actor=request.user)
            if info["block"] is None:
                # Konflikt: NICHT anlegen – Panel-Zustand für die Seite merken.
                request.session["block_conflict"] = _serialize_block_conflict(
                    q, s, e, reason, info)
            else:
                messages.success(request, f"{q.name} vom {s:%d.%m.%Y} bis "
                                 f"{e:%d.%m.%Y} gesperrt (nicht mehr buchbar).")
        target = "verw_sperrzeiten"
    elif action == "force_block":
        from .models import Quarter
        q = Quarter.objects.filter(id=request.POST.get("quarter")).first()
        s = _parse_date(request.POST.get("start"))
        e = _parse_date(request.POST.get("end"))
        request.session.pop("block_conflict", None)
        if q and s and e and e > s:
            info = svc.create_quarter_block(q, s, e, request.POST.get("reason", ""),
                                            force=True, actor=request.user)
            n = len(info["allocs"])
            messages.warning(
                request, f"⚠ {q.name} wurde trotz {n} Buchung(en) gesperrt (dringend). "
                "Bitte die betroffenen Mitglieder unten umbuchen oder – wenn kein "
                "Platz frei ist – stornieren und entschuldigen.")
        target = "verw_sperrzeiten"
    elif action == "propose_reloc":
        from .models import Allocation, Quarter
        a = Allocation.objects.filter(id=request.POST.get("allocation_id")).first()
        to_q = Quarter.objects.filter(id=request.POST.get("to_quarter")).first()
        if a and to_q:
            svc.propose_relocation(a, to_q, request.POST.get("reason", ""),
                                   actor=request.user)
            messages.success(request, f"Umbuchungs-Vorschlag ({to_q.name}) an "
                             f"{a.member.display_name} gesendet.")
        else:
            messages.error(request, "Buchung oder Zielquartier nicht gefunden.")
        target = "verw_sperrzeiten"
    elif action == "apologize_block":
        from .models import Allocation
        a = Allocation.objects.filter(id=request.POST.get("allocation_id")).first()
        if a:
            name = a.member.display_name
            res = svc.cancel_with_apology(
                a, request.POST.get("reason", ""),
                int(request.POST.get("compensation_days") or 0), actor=request.user)
            messages.success(request, f"Buchung von {name} storniert und entschuldigt "
                             f"(+{res['compensation']} Ausgleichstage).")
        target = "verw_sperrzeiten"
    elif action == "edit_block":
        from .models import QuarterBlock
        from . import validation as V
        b = QuarterBlock.objects.filter(id=request.POST.get("block_id")).first()
        s = _parse_date(request.POST.get("start"))
        e = _parse_date(request.POST.get("end"))
        if not b:
            messages.error(request, "Sperrzeit nicht gefunden.")
        elif not s or not e:
            messages.error(request, "Bitte Von- und Bis-Datum angeben.")
        elif e <= s:
            messages.error(request, "Das Bis-Datum muss nach dem Von-Datum liegen.")
        else:
            b.start, b.end = s, e
            b.reason = V.strip_controls(request.POST.get("reason", ""), max_len=200)
            b.save(update_fields=["start", "end", "reason"])
            messages.success(request, f"Sperrzeit für {b.quarter.name} geändert "
                             f"({s:%d.%m.%Y}–{e:%d.%m.%Y}).")
        target = "verw_sperrzeiten"
    elif action == "delete_block":
        from .models import QuarterBlock
        b = QuarterBlock.objects.filter(id=request.POST.get("block_id")).first()
        if b:
            name = b.quarter.name
            b.delete()
            messages.success(request, f"Sperrzeit für {name} aufgehoben.")
        target = "verw_sperrzeiten"
    elif action == "import_bank":
        from shop import reconcile
        f = request.FILES.get("statement")
        fmt = request.POST.get("fmt", "csv")
        if not f:
            messages.error(request, "Bitte eine Datei auswählen.")
        elif f.size and f.size > MAX_UPLOAD_BYTES:
            messages.error(request, "Datei zu groß (max. 10 MB).")
        else:
            try:
                batch = reconcile.import_bank_statement(f.read(), fmt, f.name)
                messages.success(request, f"Kontoauszug „{batch.filename}“: "
                                 f"{batch.n_imported} neue Eingänge übernommen, "
                                 f"{batch.n_matched} Rechnung(en) automatisch als "
                                 f"bezahlt verbucht.")
            except Exception as exc:  # noqa: BLE001 – Nutzerfehler freundlich melden
                messages.error(request, f"Import nicht möglich: {exc}")
        target = "verw_konto"
    return redirect(f"{reverse(target)}?year={year}&month={month}"
                    + ("&only_cleaning=1" if only_cleaning else "") + extra)


@authz.requires_capability("dashboard")
def dashboard(request):
    """Handlungsbedarf-Übersicht der Verwaltung: was ist reingekommen / muss jetzt
    getan werden (Endreinigungs-Anfragen, überfällige Rechnungen, neue/geänderte
    Buchungen, Kennzahlen). Die vollen Listen liegen auf den Unterseiten."""
    from shop import services as shop_svc
    from shop.models import Invoice
    from decimal import Decimal
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    if request.method == "POST":
        return _verw_post(request, year, month, m_from, m_to, only_cleaning)

    open_inv = list(shop_svc.open_invoices())
    overdue = sorted((i for i in open_inv if i.is_overdue),
                     key=lambda i: (i.due_date or today, i.number))
    arrivals = list(svc.arrivals_in_range(m_from, m_to))
    n_cleaning = sum(1 for a in svc.departures_in_range(m_from, m_to)
                     if getattr(a, "has_cleaning", False))
    online_qs = Invoice.objects.exclude(payment_method="")
    online_month = [i for i in online_qs
                    if i.paid_online_at and i.paid_online_at.year == year
                    and i.paid_online_at.month == month]
    ctx = _verw_nav_ctx(request, today, year, month)
    service_requests = list(shop_svc.pending_service_requests())
    ctx.update({
        "service_requests": service_requests,
        "overdue": overdue[:8], "overdue_count": len(overdue),
        "overdue_sum": sum((i.total_gross for i in overdue), Decimal(0)),
        "activity": svc.recent_booking_activity(7),
        "kpi": {"arrivals": len(arrivals), "cleaning": n_cleaning,
                "open": len(open_inv),
                "open_sum": sum((i.total_gross for i in open_inv), Decimal(0)),
                "overdue": len(overdue), "online": len(online_month)},
        # Mobiles Bereiche-Raster (nur ≤720px sichtbar): direkter Sprung zu allen
        # Verwaltungs-Unterseiten, mit „Handlungsbedarf"-Badges an den relevanten.
        "tiles": [
            {"url": "verw_buchungen", "label": "Buchungen", "icon": "ic-mybookings"},
            {"url": "verw_wuensche", "label": "Wünsche & Losung", "icon": "ic-wish"},
            {"url": "verw_reinigung", "label": "Reinigung", "icon": "ic-clean",
             "badge": len(service_requests), "level": "warn"},
            {"url": "verw_sperrzeiten", "label": "Sperrzeiten", "icon": "ic-lock",
             "badge": svc.count_relocations_needed(today), "level": "warn"},
            {"url": "verw_rechnungen", "label": "Rechnungen", "icon": "ic-invoices",
             "badge": len(overdue), "level": "bad"},
            {"url": "verw_konto", "label": "Kontoabgleich", "icon": "ic-bank"},
            {"url": "verw_auslastung", "label": "Auslastung", "icon": "ic-community"},
            {"url": "verw_mitglieder", "label": "Mitglieder", "icon": "ic-profile"},
            {"url": "verw_rundnachricht", "label": "Rundnachricht", "icon": "ic-mail"},
            {"url": "dashboard_products", "label": "Hofladen-Katalog", "icon": "ic-shop"},
        ],
    })
    # Bereiche-Kacheln rollengefiltert: nur Seiten, die der Nutzer aufrufen darf
    # (deckungsgleich mit der Nav, ADR 0100).
    _allowed = {c.url_name for c in authz.allowed_capabilities(request.user)}
    ctx["tiles"] = [t for t in ctx["tiles"] if t["url"] in _allowed]
    return render(request, "booking/verw_dashboard.html", ctx)


@authz.requires_capability("buchungen")
def verw_buchungen(request):
    """Unterseite: anstehende Buchungen des Monats (Ansehen/Export/Versand). Trägt
    für die **erweiterte** Buchungs-Verwaltung zusätzlich das Formular „Buchung für
    Mitglied anlegen" (BL-Buchung, ADR 0100)."""
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    if request.method == "POST":
        return _verw_post(request, year, month, m_from, m_to, only_cleaning)
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx["arrivals"] = list(svc.arrivals_in_range(m_from, m_to))
    # BL-Buchung (nur mit Recht book_for_member): Mitglieds- und Quartierwahl.
    if authz.user_can(request.user, authz.P_BOOK_FOR_MEMBER):
        ctx["can_book_for_member"] = True
        ctx["bl_members"] = list(Member.objects.filter(is_external=False)
                                 .select_related("user").order_by("display_name"))
        ctx["bl_quarters"] = list(Quarter.objects.order_by("sort_order", "name"))
    return render(request, "booking/verw_buchungen.html", ctx)


@authz.requires(authz.P_BOOK_FOR_MEMBER)
@ratelimit(key="user", rate="30/m", method="POST", block=True)
def verw_book_for_member(request):
    """Legt eine Buchung im Namen eines Mitglieds an (BL-Buchung, ADR 0100). Strikt
    wie eine Eigenbuchung; mit „Regeln übergehen" als auditierte BL-Ausnahme. Das
    Recht `book_for_member` wird hier UND im Service geprüft (Defense in depth)."""
    if request.method != "POST":
        return redirect("verw_buchungen")
    today, year, month, *_ = _verw_month(request)
    back = f"{reverse('verw_buchungen')}?year={year}&month={month}"
    m = Member.objects.filter(pk=request.POST.get("member_id"),
                              is_external=False).first()
    q = Quarter.objects.filter(pk=request.POST.get("quarter_id")).first()
    start = _parse_date(request.POST.get("start"))
    end = _parse_date(request.POST.get("end"))
    if not (m and q and start and end):
        messages.error(request, "Bitte Mitglied, Quartier, Anreise und Abreise wählen.")
        return redirect(back)
    try:
        persons = int(request.POST.get("persons") or 1)
    except ValueError:
        persons = 0
    override = request.POST.get("override") == "on"
    reason = (request.POST.get("reason") or "").strip()
    alloc, err = svc.book_for_member(
        request.user, m, q, start, end, persons, override=override, reason=reason,
        special_requests=(request.POST.get("special_requests") or "").strip())
    if err:
        messages.error(request, err)
    else:
        note = " (BL-Ausnahme)" if override else ""
        messages.success(request, f"Buchung für {m.display_name} angelegt{note}: "
                         f"{q.name}, {start:%d.%m.%Y}–{end:%d.%m.%Y}. Das Mitglied "
                         "wurde benachrichtigt.")
    return redirect(back)


def _lottery_period():
    """Die aktuell relevante Los-Periode (offen/in Entzerrung/zur Auslosung) für die
    Verwaltungs-Wunschseite; sonst die jüngste."""
    q = BookingPeriod.objects.filter(status__in=[
        BookingPeriod.WISHES_OPEN, BookingPeriod.WISHES_REVIEW,
        BookingPeriod.LOTTERY_READY]).order_by("draw_at").first()
    return q or BookingPeriod.objects.order_by("-target_year").first()


@authz.requires_capability("wuensche")
@ratelimit(key="user", rate="30/m", method="POST", block=True)
def verw_wuensche(request):
    """Unterseite: **Wünsche & Losung** (ADR 0101). Zeigt den eingereichten Lostopf,
    erlaubt den **Wunsch-Export** (xlsx/CSV; Recht `export_wishes`) und – mit dem Recht
    `add_wish_for_member` – das **stellvertretende Nachtragen** eines Wunsches für ein
    Mitglied (auditiert)."""
    from . import exports
    period = _lottery_period()
    if request.method == "POST":
        return _verw_wuensche_post(request, period)
    exp = request.GET.get("export")
    if exp in ("csv", "xlsx") and period:
        rows = svc.wish_export_rows(period)
        return exports.table_response(
            exp, f"wuensche-{period.target_year}", f"Wünsche {period.target_year}",
            svc.WISH_EXPORT_COLUMNS, rows)
    today = date.today()
    ny, nm = svc.next_month(today)
    year, month = _month_from_request(request, today, ny, nm)
    ctx = _verw_nav_ctx(request, today, year, month)
    wishes = []
    if period:
        wishes = list(Wish.objects.filter(period=period, submitted=True)
                      .select_related("member", "quarter", "created_by")
                      .order_by("member__display_name", "priority"))
    can_add = authz.user_can(request.user, authz.P_ADD_WISH_FOR_MEMBER)
    ctx.update({
        "lot_period": period, "wishes": wishes, "wish_count": len(wishes),
        "can_add_wish": can_add,
        "bl_members": (list(Member.objects.filter(is_external=False)
                            .select_related("user").order_by("display_name"))
                       if can_add else []),
        "bl_quarters": (list(Quarter.objects.filter(active=True)
                             .order_by("sort_order", "name")) if can_add else []),
    })
    return render(request, "booking/verw_wuensche.html", ctx)


def _verw_wuensche_post(request, period):
    """Verarbeitet das stellvertretende Nachtragen eines Wunsches (Recht wird in der
    View über die Capability UND im Service geprüft – Defense in depth)."""
    back = reverse("verw_wuensche")
    if not authz.user_can(request.user, authz.P_ADD_WISH_FOR_MEMBER):
        raise PermissionDenied
    if not period:
        messages.error(request, "Keine offene Los-Periode.")
        return redirect(back)
    m = Member.objects.filter(pk=request.POST.get("member_id"),
                              is_external=False).first()
    q = Quarter.objects.filter(pk=request.POST.get("quarter_id")).first()
    start = _parse_date(request.POST.get("start"))
    end = _parse_date(request.POST.get("end"))
    if not (m and q and start and end):
        messages.error(request, "Bitte Mitglied, Quartier, Anreise und Abreise wählen.")
        return redirect(back)
    wish, err = svc.add_wish_for_member(request.user, m, period, q, start, end)
    if err:
        messages.error(request, err)
    else:
        messages.success(request, f"Wunsch für {m.display_name} nachgetragen und "
                         f"eingereicht: {q.name}, {start:%d.%m.}–{end:%d.%m.}.")
    return redirect(back)


@authz.requires_capability("reinigung")
def verw_reinigung(request):
    """Unterseite: **Reinigung** – alle Abreisen (= Reinigungstage) UND die
    bezahlpflichtige Endreinigung (Freigabe #28 + Revidieren #45) auf EINER Seite.
    Kein getrennter Menüpunkt: die normale Reinigung nach jeder Abreise und die
    gebuchte Endreinigung gehören zusammen."""
    from shop import services as shop_svc
    from .models import BookingPolicy
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    if request.method == "POST":
        return _verw_post(request, year, month, m_from, m_to, only_cleaning)
    departures = list(svc.departures_in_range(m_from, m_to))
    cleaning = [a for a in departures if getattr(a, "has_cleaning", False)]
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx.update({
        "cleaning_view": cleaning if only_cleaning else departures,
        "only_cleaning": only_cleaning, "n_cleaning": len(cleaning),
        "service_requests": list(shop_svc.pending_service_requests()),
        "revisable_requests": [
            {"sr": sr, "lock": shop_svc.service_request_lock_date(sr)}
            for sr in shop_svc.revisable_service_requests()],
        "er_lock_days": BookingPolicy.get_solo().er_decision_lock_days,
    })
    return render(request, "booking/verw_reinigung.html", ctx)


@authz.requires_capability("sperrzeiten")
def verw_sperrzeiten(request):
    """Unterseite: **Sperrzeiten** je Quartier (Reinigung/Reparatur, #61/ADR 0086) –
    eigene Seite (nicht mehr unter „Reinigung"): Sperren sind Planung, kein tägliches
    Handeln. Anlegen/Aufheben über den zentralen POST-Dispatcher."""
    from .models import Quarter, QuarterBlock
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    if request.method == "POST":
        return _verw_post(request, year, month, m_from, m_to, only_cleaning)
    from .models import RelocationRequest
    blocks = list(QuarterBlock.objects.filter(end__gte=today)
                  .select_related("quarter").order_by("start", "quarter__sort_order"))
    # Buchungen, die aktuell mit einer Sperrzeit kollidieren → brauchen Umbuchung
    # oder eine Storno-mit-Entschuldigung (ADR 0097). Aus den Daten abgeleitet, damit
    # der Abschnitt automatisch verschwindet, sobald ein Fall geklärt ist.
    reloc_needed = []
    for b in blocks:
        allocs, _ext = svc.block_conflicts(b.quarter, b.start, b.end)
        for a in allocs:
            pending = next((r for r in a.relocation_requests.all()
                            if r.status == RelocationRequest.PROPOSED), None)
            rejected = any(r.status == RelocationRequest.REJECTED
                           for r in a.relocation_requests.all())
            reloc_needed.append({
                "alloc": a, "block": b, "pending": pending, "rejected": rejected,
                "options": None if pending else svc.relocation_options(a),
            })
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx.update({
        "quarters": list(Quarter.objects.filter(active=True).order_by("sort_order", "name")),
        "blocks": blocks,
        "block_conflict": request.session.pop("block_conflict", None),
        "reloc_needed": reloc_needed,
        "max_comp_days": svc.max_compensation_days(),
    })
    return render(request, "booking/verw_sperrzeiten.html", ctx)


@authz.requires_capability("rechnungen")
def verw_rechnungen(request):
    """Unterseite: Rechnungen (filterbar) + Zahlungserinnerungen."""
    from shop import services as shop_svc
    from shop.models import Invoice, ShopConfig
    from decimal import Decimal
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    if request.method == "POST":
        return _verw_post(request, year, month, m_from, m_to, only_cleaning)
    open_inv = list(shop_svc.open_invoices().order_by("due_date", "number"))
    overdue = [i for i in open_inv if i.is_overdue]
    online_qs = (Invoice.objects.exclude(payment_method="")
                 .select_related("member", "guest").prefetch_related("items"))
    online_total_count = online_qs.count()
    # Externe Gäste-Rechnungen sind bereits in open_invoices()/Invoice.objects
    # enthalten (recipient_label unterscheidet); ein eigener Filter macht sie
    # gezielt auffindbar (#56).
    guest_count = Invoice.objects.filter(guest__isnull=False).count()
    inv_filter = request.GET.get("inv", "open")
    if inv_filter == "overdue":
        invoices_view = sorted(overdue, key=lambda i: (i.due_date or today, i.number))
    elif inv_filter == "paid":
        invoices_view = list(Invoice.objects.filter(status=Invoice.PAID)
                             .select_related("member", "guest")
                             .prefetch_related("items").order_by("-paid_reported_at"))
    elif inv_filter == "online":
        invoices_view = list(online_qs.order_by("-paid_online_at"))
    elif inv_filter == "extern":
        invoices_view = list(Invoice.objects.filter(guest__isnull=False)
                             .select_related("member", "guest")
                             .prefetch_related("items")
                             .order_by("-year", "-month", "number"))
    elif inv_filter == "all":
        invoices_view = list(Invoice.objects.select_related("member", "guest")
                             .prefetch_related("items")
                             .order_by("-year", "-month", "number"))
    else:
        inv_filter, invoices_view = "open", open_inv
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx.update({
        "open_invoices": open_inv, "overdue": overdue,
        "invoices_view": invoices_view, "inv_filter": inv_filter,
        "inv_view_sum": sum((i.total_gross for i in invoices_view), Decimal(0)),
        "online_total_count": online_total_count, "guest_count": guest_count,
        "shop_small_business": ShopConfig.get_solo().small_business,
    })
    return render(request, "booking/verw_rechnungen.html", ctx)


@authz.requires_capability("konto")
def verw_konto(request):
    """Unterseite: Kontoabgleich (Zahlungseingänge importieren)."""
    from shop.models import BankImport, BankTransaction
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    if request.method == "POST":
        return _verw_post(request, year, month, m_from, m_to, only_cleaning)
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx.update({
        "recent_imports": list(BankImport.objects.all()[:8]),
        "unmatched_count": BankTransaction.objects.filter(
            matched_invoice__isnull=True, amount__gt=0).count(),
    })
    return render(request, "booking/verw_konto.html", ctx)


@authz.requires_capability("auslastung")
def verw_auslastung(request):
    """Unterseite: Statistik + Auslastung je Unterkunft (Ziel-Ampel)."""
    today, year, month, m_from, m_to, only_cleaning = _verw_month(request)
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx.update({"stats": svc.dashboard_stats(),
                "quarter_occupancy": svc.quarter_occupancy_ampel(year, month)})
    return render(request, "booking/verw_auslastung.html", ctx)


@authz.requires_capability("mitglieder")
@ratelimit(key="user", rate="30/m", method="POST", block=True)
def verw_mitglieder(request):
    """Unterseite: **native Mitglieder-Verwaltung** (shallow, ADR 0100). Vereint die
    Freischaltung neuer Konten (Onboarding-Warteschlange), die Mitgliederliste mit
    Status-Chips und Kontaktdaten (#65) und die flache Status-Aktion passiv/aktiv.
    Tiefe Änderungen (PII, Anteile umbauen, Ausscheiden, Löschen) bleiben dem
    Superuser-Backend vorbehalten."""
    from .models import Member, Membership
    if request.method == "POST":
        return _verw_mitglieder_post(request)
    q = (request.GET.get("q") or "").strip()
    members = (Member.objects.filter(is_external=False)
               .select_related("user")
               .prefetch_related("shares__membership")
               .order_by("display_name"))
    if q:
        from django.db.models import Q
        members = members.filter(
            Q(display_name__icontains=q) | Q(legal_name__icontains=q)
            | Q(user__email__icontains=q) | Q(user__username__icontains=q)
            | Q(city__icontains=q) | Q(phone__icontains=q))
    members = list(members)
    # Onboarding-Warteschlange: frisch registrierte Konten ohne Mitglieds-Anteil.
    pending = list(svc.users_without_membership().select_related("member"))
    for u in pending:
        u.suggested_name = (u.get_full_name() or u.username).strip()
    memberships = list(Membership.objects.order_by("label", "eg_number")
                       .prefetch_related("shares"))
    for ms in memberships:
        ms.free_nights = ms.annual_night_budget - ms.allocated_budget
    default_budget = Membership.suggest_budget()
    today = date.today()
    ny, nm = svc.next_month(today)
    year, month = _month_from_request(request, today, ny, nm)
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx.update({"members": members, "q": q, "member_count": len(members),
                "pending": pending, "memberships": memberships,
                "default_budget": default_budget})
    return render(request, "booking/verw_mitglieder.html", ctx)


def _verw_mitglieder_post(request):
    """Verarbeitet die flachen Mitglieder-Aktionen (Onboarding + Status). Jede Aktion
    prüft ihr Ziel erneut serverseitig (Defense in depth): Onboarding/Deaktivieren
    nur für Konten OHNE Anteil, passiv/aktiv nur für buchende Mitglieder."""
    from .models import Member, Membership
    from urllib.parse import urlencode
    action = request.POST.get("action")
    back = reverse("verw_mitglieder")
    q = (request.POST.get("q") or "").strip()
    if q:
        back = f"{back}?{urlencode({'q': q})}"

    if action in ("passive", "active"):
        m = Member.objects.filter(pk=request.POST.get("member_id"),
                                  is_external=False).first()
        if not m:
            messages.error(request, "Mitglied nicht gefunden.")
        elif m.status == "excluded":
            messages.error(request, "Ausgeschiedene Mitglieder werden im Backend "
                           "verwaltet.")
        else:
            changed = svc.set_member_passive(m, passive=(action == "passive"))
            if changed and action == "passive":
                messages.success(request, f"{m.display_name} ist jetzt passiv "
                                 "(kann nicht mehr neu buchen; Hofladen/Login bleiben).")
            elif changed:
                messages.success(request, f"{m.display_name} ist wieder aktiv.")
            else:
                messages.info(request, "Status war bereits so gesetzt.")
        return redirect(back)

    # Onboarding-Aktionen: das Ziel MUSS ein Konto ohne Anteil sein.
    user = svc.users_without_membership().filter(pk=request.POST.get("user_id")).first()
    if not user:
        messages.error(request, "Konto nicht gefunden oder schon zugeordnet.")
        return redirect(back)
    name = (user.get_full_name() or user.username).strip()
    display_name = (request.POST.get("display_name") or "").strip() or user.username
    try:
        if action == "member":
            mid = request.POST.get("membership") or ""
            membership_id = mid if mid and mid != "new" else None
            nb = int(request.POST.get("night_budget") or 0)
            svc.onboard_as_member(
                user, display_name=display_name, night_budget=nb,
                wish_night_budget=nb // 2, membership_id=membership_id,
                new_label=(request.POST.get("new_label") or "").strip())
            messages.success(request, f"{name} wurde als Mitglied zugeordnet und "
                             "kann jetzt buchen.")
        elif action == "terminal":
            svc.onboard_as_terminal(user, display_name=display_name)
            messages.success(request, f"{name} ist jetzt Hofladen-/Terminal-Gast. "
                             "Die PIN setzt die Person selbst im Profil.")
        elif action == "deactivate":
            svc.deactivate_account(user)
            messages.success(request, f"Konto {name} deaktiviert (Login gesperrt; "
                             "reversibel im Backend).")
        else:
            messages.error(request, "Unbekannte Aktion.")
    except Membership.DoesNotExist:
        messages.error(request, "Der gewählte Anteil existiert nicht (mehr).")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(back)


@authz.requires_capability("rundnachricht")
def verw_rundnachricht(request):
    """Unterseite: **Rundnachricht** an eine Rolle (In-App + Mail + Push) und
    **Rollen-Export** (CSV für externe Verteilerlisten) – ADR 0090/B4."""
    import csv as _csv
    # Export je Rolle als CSV (für externe Verteilerlisten).
    exp = request.GET.get("export")
    if exp:
        rows = svc.role_recipients(exp)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="empfaenger-{exp}.csv"'
        resp.write("﻿")     # BOM für Excel
        w = _csv.writer(resp, delimiter=";")
        w.writerow(["Name", "E-Mail"])
        for name, email in rows:
            w.writerow([name, email])
        return resp
    today = date.today()
    ny, nm = svc.next_month(today)
    year, month = _month_from_request(request, today, ny, nm)
    if request.method == "POST" and request.POST.get("action") == "broadcast":
        audience = request.POST.get("audience", "")
        subject = (request.POST.get("subject") or "").strip()
        body = (request.POST.get("body") or "").strip()
        valid_aud = {a for a, _ in svc.BROADCAST_AUDIENCES}
        if audience not in valid_aud or not subject or not body:
            messages.error(request, "Bitte Zielgruppe, Betreff und Text angeben.")
        else:
            res = svc.broadcast_message(audience, subject, body)
            messages.success(request, f"Rundnachricht gesendet: {res['inapp']} In-App, "
                             f"{res['mail']} E-Mail(s).")
        return redirect(f"{reverse('verw_rundnachricht')}?year={year}&month={month}")
    ctx = _verw_nav_ctx(request, today, year, month)
    ctx["audiences"] = [
        {"key": a, "label": lbl, "count": len(svc.role_recipients(a))}
        for a, lbl in svc.BROADCAST_AUDIENCES]
    return render(request, "booking/verw_rundnachricht.html", ctx)


@authz.requires(authz.P_BUCHUNGEN)
def plan_pdf(request):
    """Belegungsplan als Druck-PDF (Querformat) – nur Verwaltung/BL (#39, ADR 0083).
    Liest denselben Datums-Anker/Bereich wie der Plan (`from`/`weeks`)."""
    from . import plan_pdf as pp
    today = date.today()
    anchor = _parse_date(request.GET.get("from")) or today
    try:
        weeks = int(request.GET.get("weeks", 2))
    except (TypeError, ValueError):
        weeks = 2
    weeks = weeks if weeks in (1, 2, 4) else 2
    if not pp.weasyprint_available():
        return HttpResponse(
            "PDF-Erzeugung ist auf diesem Server nicht verfügbar.", status=503)
    data = pp.plan_pdf_bytes(anchor, weeks * 7, management=True)
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = (
        f'inline; filename="belegungsplan-{anchor:%Y-%m-%d}-{weeks}w.pdf"')
    return resp


@login_required
def dashboard_export(request, kind: str, fmt: str):
    """Export der Dashboard-Listen als xlsx oder CSV (Buchungen, Reinigung,
    Rechnungen) – je Liste das passende Recht (Buchungen/Reinigung → Buchungs-,
    Rechnungen → Rechnungs-Verwaltung)."""
    _EXPORT_PERM = {"buchungen": authz.P_BUCHUNGEN, "reinigung": authz.P_BUCHUNGEN,
                    "rechnungen": authz.P_RECHNUNGEN}
    if kind not in _EXPORT_PERM or not authz.user_can(request.user, _EXPORT_PERM[kind]):
        raise PermissionDenied
    from . import exports
    from shop import services as shop_svc
    from shop.models import Invoice

    today = date.today()
    ny, nm = svc.next_month(today)
    year, month = _month_from_request(request, today, ny, nm)
    m_from, m_to = svc.month_bounds(year, month)
    tag = f"{year}-{month:02d}"

    if kind == "buchungen":
        allocs = svc.arrivals_in_range(m_from, m_to)
        return exports.table_response(
            fmt, f"buchungen-{tag}", f"Buchungen {tag}",
            svc.BOOKING_COLUMNS, svc.booking_rows(allocs))
    if kind == "reinigung":
        only = request.GET.get("only_cleaning") == "1"
        deps = svc.departures_in_range(m_from, m_to)
        return exports.table_response(
            fmt, f"reinigung-{tag}", f"Reinigung {tag}",
            svc.CLEANING_COLUMNS, svc.cleaning_rows(deps, only_cleaning=only))
    if kind == "rechnungen":
        status = request.GET.get("status", "open")
        if status == "overdue":
            qs = shop_svc.overdue_invoices()
        elif status == "paid":
            qs = Invoice.objects.filter(status=Invoice.PAID).select_related("member")
        elif status == "all":
            qs = Invoice.objects.select_related("member")
        else:
            status, qs = "open", shop_svc.open_invoices()
        qs = qs.order_by("due_date", "number")
        return exports.table_response(
            fmt, f"rechnungen-{status}", f"Rechnungen {status}",
            shop_svc.INVOICE_COLUMNS, shop_svc.invoice_export_rows(qs))
    return redirect("dashboard")


@authz.requires_capability("produkte")
def dashboard_products(request):
    """Hofladen-Katalog im Verwaltungs-Dashboard pflegen (Verwaltung-Rolle):
    Produkte anlegen/ändern/aktiv schalten und Gruppen anlegen – ohne Backend."""
    from decimal import Decimal, InvalidOperation
    from shop.models import Product, ProductGroup

    def _price(raw, fallback="0"):
        return Decimal(str(raw or fallback).replace(",", ".").strip())

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_group":
                name = strip_controls(request.POST.get("name"), max_len=80).strip()
                if name:
                    ProductGroup.objects.get_or_create(
                        name=name,
                        defaults={"emoji": strip_controls(
                            request.POST.get("emoji"), max_len=8).strip()})
                    messages.success(request, f"Gruppe „{name}“ angelegt.")
                else:
                    messages.error(request, "Bitte einen Gruppennamen angeben.")
            elif action == "add_product":
                grp = ProductGroup.objects.get(id=request.POST.get("group"))
                name = strip_controls(request.POST.get("name"), max_len=120).strip()
                if not name:
                    raise ValueError("kein Name")
                Product.objects.create(
                    group=grp, name=name, price=_price(request.POST.get("price")),
                    unit=request.POST.get("unit", "stueck"),
                    vat_rate=int(request.POST.get("vat_rate", 7)),
                    kind=request.POST.get("kind", "ware"))
                messages.success(request, f"Produkt „{name}“ angelegt.")
            elif action == "update_product":
                p = Product.objects.get(id=request.POST.get("product"))
                p.name = (strip_controls(request.POST.get("name"), max_len=120).strip()
                          or p.name)
                p.price = _price(request.POST.get("price"), str(p.price))
                p.unit = request.POST.get("unit", p.unit)
                p.vat_rate = int(request.POST.get("vat_rate", p.vat_rate))
                p.active = bool(request.POST.get("active"))
                p.save()
                messages.success(request, f"„{p.name}“ gespeichert.")
        except (ProductGroup.DoesNotExist, Product.DoesNotExist):
            messages.error(request, "Eintrag nicht gefunden.")
        except (ValueError, InvalidOperation, TypeError):
            messages.error(request, "Eingaben bitte prüfen (Name/Preis).")
        return redirect("dashboard_products")

    groups = [{"group": g, "products": list(g.products.all())}
              for g in ProductGroup.objects.prefetch_related("products")]
    return render(request, "booking/dashboard_products.html", {
        "groups": groups, "all_groups": list(ProductGroup.objects.all()),
        "units": Product.UNITS, "vat_choices": Product.VAT_CHOICES,
        "kinds": Product.KIND})


@login_required
def beds24_import(request):
    """Migrations-Assistent: bestehende Beds24-Buchungen per CSV importieren.
    Nur Admin (legt echte Buchungen an). Ablauf: CSV hochladen → automatischer
    Vorschlag je Zeile → manuell Mitglied/Quartier abgleichen → übernehmen."""
    from .permissions import is_admin
    if not is_admin(request.user):
        messages.error(request, "Der Import ist der Admin-Rolle vorbehalten.")
        return redirect("dashboard")
    from .models import Beds24Import, Beds24ImportRow, OpsConfig
    if not OpsConfig.get_solo().beds24_import_enabled:
        messages.info(request, "Der Beds24-Import ist deaktiviert "
                               "(Betriebs-Einstellungen im Backend).")
        return redirect("dashboard")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "upload":
            f = request.FILES.get("csv")
            if not f:
                messages.error(request, "Bitte eine CSV-Datei auswählen.")
                return redirect("beds24_import")
            if f.size and f.size > MAX_UPLOAD_BYTES:
                messages.error(request, "Datei zu groß (max. 10 MB).")
                return redirect("beds24_import")
            try:
                raw = f.read()
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            batch = svc.beds24_stage(text, f.name)
            messages.success(
                request, f"{batch.n_rows} Buchungszeilen gelesen. Bitte abgleichen.")
            return redirect(f"{reverse('beds24_import')}?batch={batch.id}")

        batch = get_object_or_404(Beds24Import, id=request.POST.get("batch"))
        if action == "create_member":
            row = get_object_or_404(Beds24ImportRow, id=request.POST.get("row"),
                                    batch=batch)
            row_email = row.email or (row.raw.get("email", "") if row.raw else "")
            member = svc.beds24_create_member(row.guest_name, row_email)
            row.chosen_member = member
            row.save(update_fields=["chosen_member"])
            extra = (" Eine Einladung zum Passwort-Setzen ist unterwegs."
                     if row_email else
                     " Hinweis: ohne E-Mail kann die Person noch kein Passwort setzen.")
            messages.success(request, f"Mitglied „{member.display_name}“ angelegt "
                                      "und der Zeile zugeordnet." + extra)
            return redirect(f"{reverse('beds24_import')}?batch={batch.id}")
        if action == "apply":
            decisions = {}
            for row in batch.rows.all():
                rid = row.id
                act = request.POST.get(f"action_{rid}", "")
                if act not in ("import", "skip"):
                    continue
                def _int(name):
                    v = request.POST.get(name)
                    return int(v) if v and v.isdigit() else None
                decisions[rid] = {
                    "action": act, "member": _int(f"member_{rid}"),
                    "quarter": _int(f"quarter_{rid}"),
                    "persons": _int(f"persons_{rid}")}
            res = svc.beds24_apply(batch, decisions)
            msg = (f"{res['imported']} Buchung(en) übernommen, "
                   f"{res['skipped']} übersprungen.")
            if res["errors"]:
                msg += f" {len(res['errors'])} unvollständig (übersprungen)."
            messages.success(request, msg)
            return redirect(f"{reverse('beds24_import')}?batch={batch.id}")
        return redirect("beds24_import")

    # GET
    batch_id = request.GET.get("batch")
    batch = Beds24Import.objects.filter(id=batch_id).first() if batch_id else None
    context = {"recent": list(Beds24Import.objects.all()[:8])}
    if batch:
        members = list(Member.objects.select_related("user").order_by("display_name"))
        quarters = list(Quarter.objects.order_by("name"))
        rows = list(batch.rows.select_related(
            "suggested_member", "suggested_quarter",
            "chosen_member", "chosen_quarter").all())
        # Zusatz-Ampeln (Verfügbarkeit) + Regel-Warnung je Zeile annotieren.
        checks = svc.beds24_row_checks(batch)
        for r in rows:
            c = checks.get(r.id, {})
            r.free = c.get("free")
            r.conflict = c.get("conflict", "")
            r.rule_warning = c.get("rule_warning", "")
        context.update({
            "batch": batch, "rows": rows,
            "members": members, "quarters": quarters})
    return render(request, "booking/beds24_import.html", context)


@login_required
def period_result(request, period_id: int):
    period = get_object_or_404(BookingPeriod, id=period_id)
    member = _current_member(request)
    run = period.runs.first()
    confirmed = bool(run and run.confirmed)
    from .permissions import is_verwaltung
    is_staff = is_verwaltung(request.user)  # Verwaltung sieht Vorschau (nur lesend)
    # Vor der Bestätigung ist das Ergebnis für Mitglieder nicht sichtbar; nur die
    # Verwaltung sieht eine Vorschau.
    if not confirmed and not is_staff:
        return render(request, "booking/result.html", {
            "period": period, "run": run, "not_published": True,
            "member": member, "allocations": [], "my_allocations": [],
            "my_note": None,
        })
    allocations = (
        Allocation.objects.filter(period=period, source="lottery")
        .select_related("member", "quarter").order_by("start", "quarter__name")
    )
    # Eigenes Ergebnis hervorheben; die ausführliche Auslosungs-Erklärung steht
    # in der zugehörigen Benachrichtigung (Gewinne/Verluste/Karma).
    my_allocations = [a for a in allocations if member and a.member_id == member.id]
    my_note = None
    if member:
        my_note = member.notifications.filter(
            url=reverse("period_result", args=[period.id])
        ).order_by("-created_at").first()
    return render(request, "booking/result.html", {
        "period": period, "run": run, "allocations": allocations,
        "member": member, "my_allocations": my_allocations, "my_note": my_note,
        "not_published": False, "preview": not confirmed and is_staff,
    })


# --------------------------------------------------------------------------- #
# Öffentlicher Bereich für externe Gäste (ohne Login)
# --------------------------------------------------------------------------- #

def external_home(request):
    """Öffentlicher Einstieg für externe Gäste: Verfügbarkeit anzeigen und ein
    freies Quartier auswählen. Der Klick auf „Auswählen“ führt auf die separate
    Bestätigungs-/Datenseite (`external_book`). Kein Login nötig."""
    from .models import ExternalConfig
    from shop.models import ShopConfig
    from shop import payments as pay_svc
    cfg = ExternalConfig.get_solo()
    shop_cfg = ShopConfig.get_solo()

    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    try:
        persons = int(request.GET.get("persons") or 2)
    except (TypeError, ValueError):
        persons = 2
    offers = (svc.external_available_quarters(start, end)
              if (cfg.active and start and end) else [])
    today = date.today()
    year, month = _month_from_request(request, today)
    cal = svc.build_external_calendar(year, month, cfg) if cfg.active else None
    # Mindestaufenthalt für die Gäste-Hilfe: „wie intern" zeigt den internen
    # Standard (in der Hauptsaison ggf. mehr), sonst den eigenen festen Wert.
    if cfg.min_nights_follow_internal:
        from .models import BookingPolicy, SchoolHoliday, SeasonRule
        ext_min_base = BookingPolicy.get_solo().default_min_nights
        ext_min_seasonal = (
            SeasonRule.objects.filter(active=True, min_nights__gt=ext_min_base).exists()
            or SchoolHoliday.objects.filter(
                active=True, min_nights__gt=ext_min_base).exists())
    else:
        ext_min_base = cfg.min_nights
        ext_min_seasonal = False
    return render(request, "booking/external_home.html", {
        "cfg": cfg, "shop_cfg": shop_cfg, "today": today,
        "start": start, "end": end,
        "persons": persons, "offers": offers,
        "searched": bool(start and end),
        "ext_min_base": ext_min_base, "ext_min_seasonal": ext_min_seasonal,
        "payments_active": pay_svc.payments_enabled(),
        "cancellation_text": cfg.cancellation_text,
        "cal": cal, "nav_qs": _ext_nav_qs(start, end, persons),
        **(_cal_nav(cal) if cal else {"months": [], "years": []}),
    })


def external_book(request):
    """Bestätigungsschritt für externe Gäste (wie das interne `book_confirm`):
    Quartier + Zeitraum prüfen, Gast-/Rechnungsdaten eintragen, Preis/Anzahlung/
    Stornobedingungen sehen – erst „Verbindlich buchen“ legt die Buchung an."""
    from .models import ExternalConfig
    cfg = ExternalConfig.get_solo()
    src = request.POST if request.method == "POST" else request.GET
    quarter = Quarter.objects.filter(
        id=src.get("quarter"), active=True, external_bookable=True).first()
    start = _parse_date(src.get("start"))
    end = _parse_date(src.get("end"))
    try:
        persons = int(src.get("persons") or 1)
    except (TypeError, ValueError):
        persons = 1

    if not (cfg.active and quarter and start and end):
        messages.error(request, "Bitte Auswahl wiederholen.")
        return redirect("external_home")

    if request.method == "POST" and request.POST.get("action") == "book":
        booking, err = svc.create_external_booking(
            quarter, start, end, persons,
            name=request.POST.get("name", ""),
            email=request.POST.get("email", ""),
            street=request.POST.get("street", ""),
            zip_code=request.POST.get("zip_code", ""),
            city=request.POST.get("city", ""))
        if booking:
            from shop import payments as pay_svc
            return render(request, "booking/external_confirm.html", {
                "booking": booking, "invoice": booking.invoice,
                "deposit": cfg.deposit_for(booking.total_gross),
                "cancellation_text": cfg.cancellation_text,
                "payments_active": pay_svc.payments_enabled()})
        messages.error(request, err or "Buchung nicht möglich.")

    # Review/Eingabe-Seite (GET oder fehlgeschlagener POST)
    quote = svc.external_quote(quarter, start, end, cfg)
    available = svc.quarter_is_free(quarter, start, end) and \
        any(q.id == quarter.id for q, _ in svc.external_available_quarters(start, end))
    return render(request, "booking/external_book.html", {
        "cfg": cfg, "quarter": quarter, "start": start, "end": end,
        "persons": persons, "quote": quote, "available": available,
        "form_data": request.POST if request.method == "POST" else {},
    })


def _ext_nav_qs(start, end, persons) -> str:
    """Query-Suffix für die Kalender-Navigation (erhält Auswahl/Personen)."""
    parts = [f"persons={persons}"]
    if start:
        parts.append(f"start={start:%Y-%m-%d}")
    if end:
        parts.append(f"end={end:%Y-%m-%d}")
    return "&" + "&".join(parts)


# Magic-Link-Endpunkte gegen Token-Erraten bremsen (je IP).
@ratelimit(key="ip", rate="30/m", block=True)
def external_manage(request, token):
    """Magic-Link-Selbstverwaltung für externe Gäste (kein Login): eigene
    Buchungen ansehen und – im Rahmen der Stornobedingungen – stornieren."""
    bookings = svc.guest_bookings_by_token(token)
    if not bookings:
        return render(request, "booking/external_manage.html",
                      {"unknown": True}, status=404)
    guest = bookings[0].guest
    if request.method == "POST" and request.POST.get("action") == "cancel":
        preview, err = svc.cancel_external_booking_by_token(
            token, request.POST.get("booking"))
        if err:
            messages.error(request, err)
        else:
            messages.success(
                request,
                f"Buchung storniert. Erstattung: {preview['refund']} € "
                f"({preview['percent']} %).")
        return redirect("external_manage", token=token)
    cfg = svc.ExternalConfig.get_solo()
    from shop import payments as pay_svc
    today = date.today()
    rows = [{"b": b, "cancellable": b.status == b.CONFIRMED and b.start > today,
             "payable": bool(b.invoice_id and b.invoice.is_payable),
             "preview": svc.external_cancellation_preview(b, cfg)}
            for b in bookings]
    return render(request, "booking/external_manage.html", {
        "guest": guest, "rows": rows, "cfg": cfg, "today": today,
        "payments_active": pay_svc.payments_enabled()})


@ratelimit(key="ip", rate="30/m", block=True)
def external_pay(request, token):
    """Externer Gast startet die Online-Bezahlung einer seiner Buchungen
    (login-frei über den Magic-Link-Token)."""
    bookings = svc.guest_bookings_by_token(token)
    if not bookings:
        return render(request, "booking/external_manage.html",
                      {"unknown": True}, status=404)
    bid = request.GET.get("booking") or request.POST.get("booking")
    booking = next((b for b in bookings if str(b.id) == str(bid)), None)
    from shop import payments as pay_svc
    if not booking or not booking.invoice_id:
        messages.error(request, "Buchung/Rechnung nicht gefunden.")
        return redirect("external_manage", token=token)
    if not pay_svc.payments_enabled():
        messages.error(request, "Online-Bezahlung ist derzeit deaktiviert.")
        return redirect("external_manage", token=token)
    if not booking.invoice.is_payable:
        messages.info(request, "Diese Rechnung ist bereits beglichen.")
        return redirect("external_manage", token=token)
    try:
        pay = pay_svc.start_payment(booking.invoice, request=request)
    except pay_svc.PaymentUnavailable:
        messages.error(request, "Online-Bezahlung ist derzeit nicht möglich.")
        return redirect("external_manage", token=token)
    return redirect(pay.checkout_url)


@login_required
def community(request):
    """Gemeinschafts-Spiegel (ADR 0063): aggregierte, mitglieder-sichtbare
    Transparenz – Auslastung, Los-Ergebnis-Historie und anonyme Karma-Verteilung.
    Bewusst nur Aggregate (Datensparsamkeit), wenige DB-Abfragen."""
    return render(request, "booking/community.html",
                  {"stats": svc.community_stats()})


@login_required
def lottery_fairness(request):
    """Login-geschützte Beweis-/Erklärseite: zeigt den statistischen Fairness-
    Nachweis des Losverfahrens (Monte-Carlo) als Grafen. Konfiguriert/gestartet
    wird im Backend (Admin-Aktion am „Fairness-Nachweis")."""
    from .models import FairnessSimConfig
    cfg = FairnessSimConfig.get_solo()
    result = cfg.last_result
    eq_chart = karma_chart = None
    if result:
        eq_chart = _fairness_eq_chart(result["equal"])
        karma_chart = _fairness_karma_chart(result["karma"])
    return render(request, "booking/fairness.html", {
        "cfg": cfg, "result": result,
        "eq_chart": eq_chart, "karma_chart": karma_chart,
    })


# Inline-SVG-Geometrie (server-seitig berechnet, ohne JS-Abhängigkeit).
# WICHTIG: alle Koordinaten als Strings mit PUNKT-Dezimaltrenner ausgeben –
# Djangos deutsche L10N würde Floats sonst mit Komma rendern (x="44,0"), was in
# SVG ungültig ist und dazu führt, dass Balken/Linien gar nicht gezeichnet werden.
_CHART_W, _CHART_H = 560, 230
_PAD_L, _PAD_B, _PAD_T, _PAD_R = 44, 28, 12, 12


def _n(v) -> str:
    """SVG-sichere Zahl (Punkt als Dezimaltrenner, unabhängig von der Locale)."""
    return f"{float(v):.1f}"


def _yticks(vmax: float, y_of) -> list[dict]:
    """Vier Y-Achsen-Markierungen (0 … vmax) als Prozent für das Gitternetz."""
    ticks = []
    for i in range(5):
        v = vmax * i / 4
        ticks.append({"y": _n(y_of(v)),
                      "label": f"{v * 100:.0f} %".replace(".", ",")})
    return ticks


def _fairness_eq_chart(eq: dict) -> dict:
    """Balken je Nutzer (Gewinnrate) + Erwartungslinie + 95%-Konfidenz-Whisker."""
    users = eq["users"]
    vmax = max(eq["expected_rate"] * 2, eq["max_rate"] * 1.15, 0.05)
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B
    n = len(users)
    gap = 6
    bw = max(4.0, plot_w / n - gap)

    def y_of(v):
        return _PAD_T + plot_h - (v / vmax) * plot_h

    bars = []
    for i, u in enumerate(users):
        x = _PAD_L + i * (bw + gap)
        y = y_of(u["rate"])
        bars.append({
            "x": _n(x), "y": _n(y), "w": _n(bw),
            "h": _n(_PAD_T + plot_h - y),
            "cx": _n(x + bw / 2),
            "ci_top": _n(y_of(u["ci_high"])),
            "ci_bot": _n(y_of(u["ci_low"])),
            "label": u["index"], "rate": round(u["rate"] * 100, 1),
        })
    return {
        "w": _CHART_W, "h": _CHART_H, "bars": bars,
        "exp_y": _n(y_of(eq["expected_rate"])),
        "exp_pct": round(eq["expected_rate"] * 100, 1),
        "axis_y": _n(_PAD_T + plot_h), "axis_x0": _n(_PAD_L),
        "axis_x1": _n(_CHART_W - _PAD_R), "top_y": _n(_PAD_T),
        "yticks": _yticks(vmax, y_of),
    }


def _fairness_karma_chart(rows: list) -> dict:
    """Balken je Ausgleichsfaktor (Gewinnrate der bevorzugten Partei)."""
    vmax = max((r["rate"] for r in rows), default=0.1) * 1.2 or 0.1
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B
    n = len(rows)
    gap = 14
    bw = max(6.0, plot_w / n - gap)

    def y_of(v):
        return _PAD_T + plot_h - (v / vmax) * plot_h

    bars = []
    for i, r in enumerate(rows):
        x = _PAD_L + i * (bw + gap)
        y = y_of(r["rate"])
        bars.append({
            "x": _n(x), "y": _n(y), "w": _n(bw),
            "h": _n(_PAD_T + plot_h - y),
            "cx": _n(x + bw / 2),
            "ci_top": _n(y_of(r["ci_high"])),
            "ci_bot": _n(y_of(r["ci_low"])),
            "label": r["factor"], "rate": round(r["rate"] * 100, 1),
        })
    return {"w": _CHART_W, "h": _CHART_H, "bars": bars,
            "axis_y": _n(_PAD_T + plot_h), "axis_x0": _n(_PAD_L),
            "axis_x1": _n(_CHART_W - _PAD_R), "top_y": _n(_PAD_T),
            "yticks": _yticks(vmax, y_of)}


# Das Widget soll bewusst von der Re:Hof-Website (fremde Origin) per <iframe>
# eingebettet werden. Die globale CSP setzt frame-ancestors 'none' (Clickjacking-
# Schutz für die App); hier lockern wir NUR diese eine Direktive für diese eine
# Antwort. @xframe_options_exempt bleibt als Fallback für ältere Browser.
@csp_replace({"frame-ancestors": ["*"]})
@xframe_options_exempt
def external_embed(request):
    """Einbettbares Verfügbarkeits-Widget für die Re:Hof-Website (read-only).

    Zeigt den grün/grau-Kalender und – sobald ein Zeitraum (von/bis) gewählt ist –
    die freien Unterkünfte mit Preis (keine Gastdaten, keine Navigation/PWA). Nur
    der Klick auf „Buchen“ führt (in neuem Tab) auf die Re:Hof-Buchungsseite
    (`external_book`). `@xframe_options_exempt`, damit die Seite per <iframe>
    eingebunden werden darf."""
    cfg = svc.ExternalConfig.get_solo()
    today = date.today()
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    try:
        persons = int(request.GET.get("persons") or 2)
    except (TypeError, ValueError):
        persons = 2
    offers = (svc.external_available_quarters(start, end)
              if (cfg.active and start and end) else [])
    year, month = _month_from_request(request, today)
    cal = svc.build_external_calendar(year, month, cfg) if cfg.active else None
    response = render(request, "booking/external_embed.html", {
        "cfg": cfg, "today": today, "cal": cal,
        "start": start, "end": end, "persons": persons,
        "offers": offers, "searched": bool(start and end),
        "book_url": request.build_absolute_uri(reverse("external_book")),
        "home_url": request.build_absolute_uri(reverse("external_home")),
        "nav_qs": _ext_nav_qs(start, end, persons),
        **(_cal_nav(cal) if cal else {"months": [], "years": []}),
    })
    # Widget ist bewusst fremd-einbettbar → Resource-Policy lockern (statt der
    # globalen same-origin), passend zu @csp_replace(frame-ancestors) oben.
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response


# --------------------------------------------------------------------------- #
# Hofladen-Terminal vor Ort (ADR 0053): token-authentifiziertes Kiosk-Gerät,
# offline-fähig. KEIN Mitglieder-Login, KEINE Sitzung – nur Roster/Katalog laden
# und offline erfasste Einkäufe auf die Monatsrechnung nachreichen.
# --------------------------------------------------------------------------- #

def terminal_page(request):
    """Die Kiosk-Seite (offline-fähig, große, einfache Oberfläche). Sie holt ihre
    Daten per Token über `terminal_data` und arbeitet danach offline weiter."""
    return render(request, "booking/terminal.html")


def _terminal_token_from(request):
    import json
    try:
        data = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return None, {}
    return data.get("token", ""), data


@csrf_exempt
@require_POST
# Token-Endpunkt gegen Token-Brute-Force bremsen (je IP).
@ratelimit(key="ip", rate="60/m", block=True)
def terminal_data(request):
    """Roster + Katalog + Einstellungen – nur mit gültigem Geräte-Token."""
    token, _ = _terminal_token_from(request)
    if not svc.terminal_token_ok(token):
        return JsonResponse({"ok": False, "error": "token"}, status=403)
    return JsonResponse(svc.terminal_payload())


@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="60/m", block=True)
def terminal_sync(request):
    """Nimmt offline erfasste Einkäufe entgegen (idempotent) und bucht sie auf die
    Monatsrechnung. Nur mit gültigem Token."""
    token, data = _terminal_token_from(request)
    if not svc.terminal_token_ok(token):
        return JsonResponse({"ok": False, "error": "token"}, status=403)
    accepted, rejected = [], []
    for txn in (data.get("transactions") or [])[:200]:
        ref = str(txn.get("ref", ""))
        username = str(txn.get("username", ""))
        pairs = [(it.get("id"), it.get("qty")) for it in (txn.get("items") or [])]
        ok, _err = svc.terminal_record(username, pairs, ref)
        (accepted if ok else rejected).append(ref)
    return JsonResponse({"ok": True, "accepted": accepted, "rejected": rejected})
