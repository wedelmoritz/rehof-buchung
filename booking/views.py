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

from .forms import ProfileForm, RegistrationForm, TransferForm, WishForm
from .models import Allocation, BookingPeriod, Member, Quarter, Wish
from . import services as svc


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
                mid = b["member_id"]
                if mid not in color_map:
                    color_map[mid] = MEMBER_COLORS[len(color_map) % len(MEMBER_COLORS)]
                    legend.append({"name": b["who"], "color": color_map[mid],
                                   "mine": b["mine"]})
                b["color"] = color_map[mid]
    sel_day = _parse_date(request.GET.get("day"))
    detail = svc.day_detail(member, sel_day) if sel_day else None
    return render(request, "booking/overview.html", {
        "member": member,
        "cal": cal,
        "today": today,
        "year": today.year,
        "legend": legend,
        "sel_day": sel_day,
        "detail": detail,
        "nav_qs": "",
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
    wish_period = None
    if member:
        for a in member.allocations.select_related("quarter").filter(
                provisional=False).order_by("start"):
            (upcoming if a.end > today else past).append(a)
        for a in upcoming:
            a.waiters = svc.waiters_for_allocation(a)
            a.concurrent = svc.concurrent_allocations(a)
        incoming_swaps = svc.pending_swaps_for(member)
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
            n = svc.submit_wishlist(member, period)
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
    if _current_member(request) or request.user.is_staff:
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
    return bool(request.user.is_authenticated and request.user.is_staff)


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
        qs = (shop_svc.overdue_invoices() if status == "overdue"
              else shop_svc.open_invoices() if status == "open"
              else Invoice.objects.all())
        qs = qs.order_by("due_date", "number")
        return exports.table_response(
            fmt, f"rechnungen-{status}", f"Rechnungen {status}",
            shop_svc.INVOICE_COLUMNS, shop_svc.invoice_export_rows(qs))
    return redirect("dashboard")


@login_required
def period_result(request, period_id: int):
    period = get_object_or_404(BookingPeriod, id=period_id)
    member = _current_member(request)
    run = period.runs.first()
    confirmed = bool(run and run.confirmed)
    is_staff = request.user.is_staff
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
