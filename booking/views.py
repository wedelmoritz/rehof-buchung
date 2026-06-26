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
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt

from .forms import ProfileForm, RegistrationForm, TransferForm, WishForm
from .models import Allocation, BookingPeriod, Member, Quarter, Wish
from . import services as svc


# Obergrenze für hochgeladene Dateien (Kontoauszug/Beds24-CSV) – Schutz vor
# versehentlichem Speicher-DoS durch riesige Uploads.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Pastell-Palette zur Unterscheidung der Mitglieder in der Übersicht.
MEMBER_COLORS = [
    "#cfe6c7", "#f6dcc0", "#d9e3f3", "#f3d9e2", "#e7dcf0", "#cfe7e6",
    "#f7eccc", "#e0e8c8", "#f1d7d0", "#d6e6da", "#ecd9c4", "#dde0ee",
]


def _current_member(request) -> Member | None:
    return getattr(request.user, "member", None)


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
    # Jedem im Monat vorkommenden Mitglied eine feste Pastellfarbe geben, damit
    # auf einen Blick sichtbar ist, wer wann da ist (Gemeinschaftsaspekt).
    color_map: dict[int, str] = {}
    legend: list[dict] = []
    for week in cal["weeks"]:
        for d in week:
            for b in d["bookings"]:
                if b.get("external"):
                    continue  # Externe: feste Farbe (in services gesetzt)
                mid = b["member_id"]
                if mid not in color_map:
                    color_map[mid] = MEMBER_COLORS[len(color_map) % len(MEMBER_COLORS)]
                    legend.append({"name": b["who"], "color": color_map[mid],
                                   "mine": b["mine"]})
                b["color"] = color_map[mid]
    # Optionaler Belegungs-Zeitstrahl (pro Unterkunft eine Zeile mit Balken).
    view_mode = "timeline" if request.GET.get("view") == "timeline" else "grid"
    timeline = None
    if view_mode == "timeline":
        timeline = svc.build_occupancy_timeline(member, year, month)
        for row in timeline["rows"]:
            for bar in row["bars"]:
                bar["color"] = (timeline["extern_color"] if bar["external"]
                                else color_map.get(bar["member_id"], "#d8cfc0"))
    sel_day = _parse_date(request.GET.get("day"))
    detail = svc.day_detail(member, sel_day) if sel_day else None
    return render(request, "booking/overview.html", {
        "member": member,
        "cal": cal,
        "timeline": timeline,
        "view_mode": view_mode,
        "today": today,
        "year": today.year,
        "legend": legend,
        "sel_day": sel_day,
        "detail": detail,
        "nav_qs": "&view=timeline" if view_mode == "timeline" else "",
        "show_today": True,
        **_cal_nav(cal),
        "nights_remaining": (
            member.nights_remaining_in_year(today.year) if member else 0
        ),
        "notifications": svc.unread_notifications(member),
        "open_period": BookingPeriod.objects.filter(
            status=BookingPeriod.WISHES_OPEN).first(),
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

    if persons < quarter.min_occupancy:
        persons = quarter.min_occupancy
    if persons > quarter.max_occupancy:
        persons = quarter.max_occupancy

    remaining_now = member.nights_remaining_in_year(start.year)
    # Mitbuchbare Dienstleistungen (z.B. Endreinigung) – Verfügbarkeit am Abreisetag.
    offers = [
        {"p": p, "available": p.available_on(end)}
        for p in Product.objects.filter(active=True, book_with_stay=True)
        .order_by("sort_order", "name")
    ]

    if request.method == "POST" and request.POST.get("action") == "confirm":
        companions = request.POST.get("companions", "").strip()
        alloc, err = svc.book_spontaneous(
            member, quarter, start, end, persons, companions=companions)
        if not alloc:
            messages.error(request, err or "Buchung nicht möglich.")
        else:
            added = []
            for o in offers:
                if request.POST.get(f"service_{o['p'].id}") and o["available"]:
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
            messages.success(request, msg)
            return redirect("my_bookings")

    return render(request, "booking/book_confirm.html", {
        "member": member, "quarter": quarter, "start": start, "end": end,
        "nights": nights, "persons": persons,
        "remaining_now": remaining_now,
        "remaining_after": remaining_now - nights,
        "enough_days": remaining_now >= nights,
        "min_nights": svc.min_nights_for_range(start, end),
        "offers": offers,
    })


@login_required
def book(request):
    """Klick-Buchung: Personen + Barrierefrei oben einstellen, im Ampel-Kalender
    Anreise/Abreise wählen, dann passendes Quartier buchen (oder Warteliste)."""
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

    eff_start = eff_end = None
    suitable, maybe_unsuitable, occ_quarters = [], [], []
    range_min_nights = 0
    too_short = False
    not_enough_days = False
    days_remaining_year = 0
    if member and sel_start:
        eff_start = sel_start
        eff_end = sel_end if sel_end else sel_start + timedelta(days=1)
        nights = (eff_end - eff_start).days
        range_min_nights = svc.min_nights_for_range(eff_start, eff_end)
        too_short = nights < range_min_nights
        days_remaining_year = member.nights_remaining_in_year(eff_start.year)
        not_enough_days = nights > days_remaining_year
        free_quarters, occ_quarters = svc.split_quarters_for_range(eff_start, eff_end)
        # Termin-/Regel-/Budget-Grund ist quartiers-unabhängig → einmal berechnen.
        reason = svc.schedule_blocker(member, eff_start, eff_end)
        for q in free_quarters:
            fits_persons = q.min_occupancy <= persons <= q.max_occupancy
            fits_access = (not need_accessible) or q.accessible
            info = {
                "q": q, "reason": reason,
                "fits_persons": fits_persons, "fits_access": fits_access,
                "bookable": reason is None and fits_persons,
            }
            if fits_persons and fits_access and reason is None:
                suitable.append(info)
            else:
                maybe_unsuitable.append(info)

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
        "days_remaining_year": days_remaining_year,
        "suitable": suitable,
        "maybe_unsuitable": maybe_unsuitable,
        "occ_quarters": occ_quarters,
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
        return redirect("my_bookings")

    upcoming, past = [], []
    incoming_swaps = []
    submitted_wishes = []
    my_waitlist = []
    wish_period = None
    if member:
        for a in member.allocations.select_related("quarter").filter(
                provisional=False).order_by("start"):
            (upcoming if a.end > today else past).append(a)
        for a in upcoming:
            a.waiters = svc.waiters_for_allocation(a)
            a.concurrent = svc.concurrent_split(a)
            a.min_nights = svc.min_nights_for_range(a.start, a.end)
            # Andere Quartiere, die für den AKTUELLEN Zeitraum + Personen frei
            # sind (für den Unterkunfts-Wechsel im „Buchung ändern“-Bereich).
            a.switch_options = svc.free_quarters_for(
                a.start, a.end, a.persons, exclude_id=a.quarter_id)
        incoming_swaps = svc.pending_swaps_for(member)
        my_waitlist = list(
            member.waitlist_entries.filter(fulfilled=False, end__gte=today)
            .select_related("quarter").order_by("start"))
        wish_period = BookingPeriod.objects.filter(status__in=[
            BookingPeriod.WISHES_OPEN, BookingPeriod.LOTTERY_READY]).first()
        if wish_period:
            submitted_wishes = list(
                Wish.objects.filter(member=member, period=wish_period, submitted=True)
                .select_related("quarter").order_by("priority", "id"))

    return render(request, "booking/my_bookings.html", {
        "member": member,
        "today": today,
        "booking_year": today.year,
        "nights_remaining": member.nights_remaining_in_year(today.year) if member else 0,
        "nights_used": member.nights_used_in_year(today.year) if member else 0,
        "annual_budget": member.annual_night_budget if member else 0,
        "upcoming": upcoming,
        "past": past,
        "incoming_swaps": incoming_swaps,
        "submitted_wishes": submitted_wishes,
        "my_waitlist": my_waitlist,
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
    member = _current_member(request)
    today = date.today()
    period = BookingPeriod.objects.filter(status=BookingPeriod.WISHES_OPEN).first()
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
                    form.cleaned_data["start"], form.cleaned_data["end"])
                if werr:
                    messages.error(request, werr)
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
            .select_related("quarter").order_by("priority", "id")
        )
        wishlist_submitted = any(w.submitted for w in wishes) and len(wishes) > 0
        wish_nights = sum(w.nights for w in wishes)

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

    eff_start = eff_end = None
    candidates = []
    if member and period and sel_start:
        eff_start = sel_start
        eff_end = sel_end if sel_end else sel_start + timedelta(days=1)
        counts = svc.quarter_wish_counts(period, eff_start, eff_end)
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
        "wish_form": WishForm(),
        "wishes": wishes,
        "wishlist_submitted": wishlist_submitted,
        "wish_nights": wish_nights,
        "wish_budget": member.wish_night_budget if member else 0,
        "notifications": svc.unread_notifications(member),
    })


# --------------------------------------------------------------------------- #
# Tage übertragen
# --------------------------------------------------------------------------- #

def register(request):
    """Selbstregistrierung. Legt nur ein Login-Konto an; das Buchungs-Profil
    (Member) vergibt anschließend die Verwaltung. Bis dahin: Warte-Seite."""
    if request.user.is_authenticated:
        return redirect("overview")
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
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


@login_required
def help_page(request):
    """Erklärseite: Abläufe, Auslosung im Detail, Tage & Anteile, Hofladen."""
    return render(request, "booking/help.html", {
        "member": _current_member(request),
    })


@login_required
def profile(request):
    """Eigene Profil-/Rechnungsdaten (Name, Anschrift, IBAN) selbst pflegen.
    Nur die eigenen Daten – `member` stammt aus request.user."""
    member = _current_member(request)
    if not member:
        return redirect("overview")
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil gespeichert.")
            return redirect("profile")
    else:
        form = ProfileForm(instance=member)
    return render(request, "booking/profile.html", {"member": member, "form": form})


@login_required
def transfer(request):
    """Tage an ein anderes Mitglied übertragen (innerhalb des Jahres)."""
    member = _current_member(request)
    year = date.today().year
    if not member:
        return redirect("overview")

    pending = None
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
    })


# --------------------------------------------------------------------------- #
# Verwaltungs-Dashboard (nur Staff): anstehende Buchungen, Reinigung, Rechnungen
# --------------------------------------------------------------------------- #

def _staff_required(request):
    """Zugang zum Verwaltungs-Dashboard: Verwaltung-Gruppe oder Admin."""
    from .permissions import is_verwaltung
    return is_verwaltung(request.user)


@login_required
def dashboard(request):
    """Operatives Verwaltungs-Dashboard für das (kleine) Team: was steht an, was
    muss geputzt werden, welche Rechnungen sind offen/überfällig – mit Export
    und Versand per Knopfdruck. Nur für Verwaltungs-/Superuser."""
    if not _staff_required(request):
        messages.error(request, "Dieser Bereich ist der Verwaltung vorbehalten.")
        return redirect("overview")

    from shop import services as shop_svc
    from shop.models import Invoice
    from .models import OpsConfig
    from decimal import Decimal

    today = date.today()
    ny, nm = svc.next_month(today)
    year, month = _month_from_request(request, today, ny, nm)
    m_from, m_to = svc.month_bounds(year, month)
    only_cleaning = (request.GET.get("only_cleaning") == "1"
                     or request.POST.get("only_cleaning") == "1")

    # Aktionen (POST): Listen versenden bzw. überfällige erinnern.
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send_cleaning":
            deps = list(svc.departures_in_range(m_from, m_to))
            text = svc.cleaning_text(deps, only_cleaning=only_cleaning)
            body = (f"Reinigungsliste {svc.month_label(year, month)}\n"
                    f"(Abreisetag = Reinigungstag)\n\n{text}\n")
            recips = svc.email_cleaning(
                f"Re:Hof – Reinigungsliste {month:02d}/{year}", body)
            messages.success(
                request, f"Reinigungsliste an {len(recips)} Empfänger gesendet."
                if recips else "Keine Empfänger hinterlegt (Betriebs-Einstellungen).")
        elif action == "send_upcoming":
            allocs = list(svc.arrivals_in_range(m_from, m_to))
            body = (f"Anstehende Buchungen {svc.month_label(year, month)}\n\n"
                    f"{svc.bookings_text(allocs)}\n")
            recips = svc.email_admins(
                f"Re:Hof – Buchungen {month:02d}/{year}", body)
            messages.success(
                request, f"Übersicht an {len(recips)} Empfänger gesendet."
                if recips else "Keine Empfänger hinterlegt (Betriebs-Einstellungen).")
        elif action == "remind_overdue":
            n = shop_svc.remind_overdue()
            messages.success(request, f"{n} Zahlungserinnerung(en) verschickt.")
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
                    messages.success(
                        request, f"Kontoauszug „{batch.filename}“: "
                        f"{batch.n_imported} neue Eingänge übernommen, "
                        f"{batch.n_matched} Rechnung(en) automatisch als bezahlt "
                        f"verbucht.")
                except Exception as exc:  # noqa: BLE001 – Nutzerfehler freundlich melden
                    messages.error(request, f"Import nicht möglich: {exc}")
        return redirect(f"{reverse('dashboard')}?year={year}&month={month}"
                        + ("&only_cleaning=1" if only_cleaning else ""))

    arrivals = list(svc.arrivals_in_range(m_from, m_to))
    departures = list(svc.departures_in_range(m_from, m_to))
    cleaning = [a for a in departures if getattr(a, "has_cleaning", False)]
    cleaning_view = cleaning if only_cleaning else departures

    open_inv = list(shop_svc.open_invoices().order_by("due_date", "number"))
    overdue = [i for i in open_inv if i.is_overdue]
    open_sum = sum((i.total_gross for i in open_inv), Decimal(0))
    overdue_sum = sum((i.total_gross for i in overdue), Decimal(0))

    # Online (Mollie) bezahlte Rechnungen – fürs Dashboard separat ausweisbar.
    online_qs = (Invoice.objects.exclude(payment_method="")
                 .select_related("member", "guest").prefetch_related("items"))
    online_total_count = online_qs.count()
    online_month = [i for i in online_qs
                    if i.paid_online_at and i.paid_online_at.year == year
                    and i.paid_online_at.month == month]
    online_sum = sum((i.total_gross for i in online_month), Decimal(0))

    # Rechnungssicht: filterbar (offen / überfällig / bezahlt gemeldet / online / alle).
    inv_filter = request.GET.get("inv", "open")
    if inv_filter == "overdue":
        invoices_view = sorted(overdue, key=lambda i: (i.due_date or today, i.number))
    elif inv_filter == "paid":
        invoices_view = list(Invoice.objects.filter(status=Invoice.PAID)
                             .select_related("member", "guest")
                             .prefetch_related("items").order_by("-paid_reported_at"))
    elif inv_filter == "online":
        invoices_view = list(online_qs.order_by("-paid_online_at"))
    elif inv_filter == "all":
        invoices_view = list(Invoice.objects.select_related("member", "guest")
                             .prefetch_related("items")
                             .order_by("-year", "-month", "number"))
    else:
        inv_filter = "open"
        invoices_view = open_inv
    inv_view_sum = sum((i.total_gross for i in invoices_view), Decimal(0))

    from shop.models import BankImport, BankTransaction
    recent_imports = list(BankImport.objects.all()[:5])
    unmatched_count = BankTransaction.objects.filter(
        matched_invoice__isnull=True, amount__gt=0).count()

    months = [{"num": i, "name": svc.MONTHS_DE[i]} for i in range(1, 13)]
    return render(request, "booking/dashboard.html", {
        "today": today, "year": year, "month": month,
        "month_label": svc.month_label(year, month),
        "months": months, "years": list(range(today.year - 1, today.year + 3)),
        "arrivals": arrivals, "departures": departures,
        "cleaning_view": cleaning_view, "only_cleaning": only_cleaning,
        "n_cleaning": len(cleaning),
        "open_invoices": open_inv, "overdue": overdue,
        "open_sum": open_sum, "overdue_sum": overdue_sum,
        "invoices_view": invoices_view, "inv_filter": inv_filter,
        "inv_view_sum": inv_view_sum,
        "online_total_count": online_total_count, "online_sum": online_sum,
        "online_count": len(online_month),
        "recent_imports": recent_imports, "unmatched_count": unmatched_count,
        "beds24_enabled": OpsConfig.get_solo().beds24_import_enabled,
        "stats": svc.dashboard_stats(),
    })


@login_required
def dashboard_export(request, kind: str, fmt: str):
    """Export der Dashboard-Listen als xlsx oder CSV (Buchungen, Reinigung,
    Rechnungen)."""
    if not _staff_required(request):
        return redirect("overview")
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


@login_required
def dashboard_products(request):
    """Hofladen-Katalog im Verwaltungs-Dashboard pflegen (Verwaltung-Rolle):
    Produkte anlegen/ändern/aktiv schalten und Gruppen anlegen – ohne Backend."""
    if not _staff_required(request):
        messages.error(request, "Dieser Bereich ist der Verwaltung vorbehalten.")
        return redirect("overview")
    from decimal import Decimal, InvalidOperation
    from shop.models import Product, ProductGroup

    def _price(raw, fallback="0"):
        return Decimal(str(raw or fallback).replace(",", ".").strip())

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_group":
                name = (request.POST.get("name") or "").strip()
                if name:
                    ProductGroup.objects.get_or_create(
                        name=name, defaults={"emoji": (request.POST.get("emoji") or "").strip()})
                    messages.success(request, f"Gruppe „{name}“ angelegt.")
                else:
                    messages.error(request, "Bitte einen Gruppennamen angeben.")
            elif action == "add_product":
                grp = ProductGroup.objects.get(id=request.POST.get("group"))
                name = (request.POST.get("name") or "").strip()
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
                p.name = (request.POST.get("name") or p.name).strip()
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
            member = svc.beds24_create_member(row.guest_name,
                                              row.raw.get("email", "") if row.raw else "")
            row.chosen_member = member
            row.save(update_fields=["chosen_member"])
            messages.success(request, f"Mitglied „{member.display_name}“ angelegt "
                                      "und der Zeile zugeordnet.")
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
        context.update({
            "batch": batch,
            "rows": list(batch.rows.select_related(
                "suggested_member", "suggested_quarter",
                "chosen_member", "chosen_quarter").all()),
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
    return render(request, "booking/external_embed.html", {
        "cfg": cfg, "today": today, "cal": cal,
        "start": start, "end": end, "persons": persons,
        "offers": offers, "searched": bool(start and end),
        "book_url": request.build_absolute_uri(reverse("external_book")),
        "home_url": request.build_absolute_uri(reverse("external_home")),
        "nav_qs": _ext_nav_qs(start, end, persons),
        **(_cal_nav(cal) if cal else {"months": [], "years": []}),
    })
