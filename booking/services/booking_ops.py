"""Service-Layer (booking_ops): Buchungen: Spontanbuchung, Warteliste, Storno/Ändern, Wechselwunsch, Tage-Übertragung.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from datetime import date, timedelta
from django.db import transaction
from django.utils import timezone
from .. import validation as V
from ..models import (
    Allocation, BookingPolicy, Member, NightTransfer, Notification, Quarter,
    SwapRequest, WaitlistEntry,
)
from .notify import absolute_url, email_member
from .slots import (
    check_booking_rules, has_fitting_free_quarter, is_gap_fill, lead_time_blocker,
    min_nights_for_range, quarter_is_free, range_is_released, undersized_allowed,
)

__all__ = [
    'book_spontaneous', 'add_waitlist_entry', 'waiters_for_allocation',
    'notify_waitlist_if_free', 'concurrent_allocations', 'free_quarters_for',
    'concurrent_split', 'create_swap_request', 'respond_swap_request',
    'pending_swaps_for', 'transfer_nights', 'thank_for_transfer',
    'cancel_allocation', '_broadcast_spontaneously_free', 'adjust_allocation',
    'short_notice_days', 'is_short_notice', 'notify_member_of_staff_booking',
]


def notify_member_of_staff_booking(alloc: Allocation, action: str) -> None:
    """Benachrichtigt das Mitglied, wenn die **Verwaltung** eine Buchung in seinem
    Namen im Backend **angelegt/geändert/storniert** hat (ADR 0094). In-App-
    `Notification` + E-Mail (Opt-in). `action` ∈ {new, change, cancel}. Idempotenz
    ist Sache des Aufrufers (Admin-Hook nur bei echter Änderung)."""
    member = getattr(alloc, "member", None)
    if member is None:
        return
    verb = {"new": "für dich angelegt", "change": "für dich geändert",
            "cancel": "für dich storniert"}.get(action, "für dich geändert")
    zeitraum = f"{alloc.start:%d.%m.%Y}–{alloc.end:%d.%m.%Y}"
    msg = f"Die Verwaltung hat eine Buchung {verb}: {alloc.quarter.name}, {zeitraum}."
    url = "" if action == "cancel" else "/meine-buchungen/"
    Notification.objects.create(member=member, message=msg[:255], url=url)
    email_member(
        member, "Re:Hof: Buchung durch die Verwaltung",
        f"Hallo {member.display_name},\n\n{msg}\n\n"
        + ("" if action == "cancel" else
           "Du findest sie unter „Meine Buchungen“ in der App.\n\n")
        + "Bei Fragen wende dich bitte an die Betriebsleitung.\n\nViele Grüße\nRe:Hof")

@transaction.atomic
def book_spontaneous(
    member: Member, quarter: Quarter, start: date, end: date,
    persons: int = 1, source: str = "spontaneous", companions: str = "",
    membership_id=None, special_requests: str = "",
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
    # Passive/ausgeschiedene Mitglieder dürfen nicht neu buchen (ADR 0087).
    if not member.can_book:
        return None, ("Dein Konto ist derzeit nicht buchungsberechtigt "
                      "(passives/ausgeschiedenes Mitglied).")
    nights = (end - start).days
    if nights <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    persons = int(persons or 0)
    if persons < 1:
        return None, "Bitte mindestens 1 Person angeben."
    # Personenzahl außerhalb des ausgelegten Rahmens (zu viele ODER zu wenige) ist
    # nur erlaubt, wenn die Richtlinie es zulässt UND **alles Passende belegt** ist
    # (harte Kopplung, ADR 0076); im UI deutlich gekennzeichnet.
    outside = not (quarter.min_occupancy <= persons <= quarter.max_occupancy)
    if outside:
        if not undersized_allowed():
            return None, (f"{quarter.name} ist für {quarter.min_occupancy}–"
                          f"{quarter.max_occupancy} Personen ausgelegt "
                          f"(angegeben: {persons}).")
        # Barrierefrei-Bedarf berücksichtigen (#17/ADR 0078): wird eine barrierefreie
        # Unterkunft gebucht, zählen nur andere BARRIEREFREIE freie Unterkünfte als
        # „passend" – sonst würde man auf eine nicht barrierefreie Unterkunft verwiesen.
        if has_fitting_free_quarter(start, end, persons,
                                    need_accessible=quarter.accessible):
            return None, ("Für diese Personenzahl ist noch eine passende Unterkunft "
                          "frei – bitte diese buchen.")
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
    # Mitglieds-Anteil bestimmen (Default: eindeutiger/größter Anteil; bei
    # Mehrfach-Tandem die getroffene Wahl) – die Buchungsregeln zählen über den
    # vollen Anteil inkl. Tandem-Partner (ADR 0066).
    membership = member.membership_for(membership_id)
    # Lückenfüllung (ADR 0075): füllt die Buchung eine freie Lücke exakt aus,
    # entfallen Mindestnächte UND Spontan-Vorausfrist.
    policy = BookingPolicy.get_solo()
    gap_fill = policy.allow_gap_fill and is_gap_fill(quarter, start, end)
    # Spontan-Vorausfrist (außer bei Lückenfüllung).
    if not gap_fill:
        lead_error = lead_time_blocker(start)
        if lead_error:
            return None, lead_error
    # Saison-Regeln: Mindestnächte (bei Lückenfüllung übersprungen),
    # Parallel-Limit, Aufenthaltsdeckel.
    rule_error = check_booking_rules(member, start, end, membership,
                                     skip_min_nights=gap_fill)
    if rule_error:
        return None, rule_error
    alloc = Allocation.objects.create(
        member=member, quarter=quarter, start=start, end=end,
        persons=persons, source=source, membership=membership,
        companions=V.strip_controls(companions, max_len=255),
        special_requests=V.strip_controls(special_requests, max_len=255),
    )
    # Sofort-Meldung an die Verwaltung bei kurzfristiger Buchung (ADR 0089/B3).
    from .dashboard import notify_booking_activity
    notify_booking_activity(alloc, action="new")
    return alloc, None


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
    allow_under = undersized_allowed()
    fitting, oversized = [], []
    for q in Quarter.objects.order_by("name"):
        if exclude_id and q.id == exclude_id:
            continue
        if not (range_is_released(q, start, end) and quarter_is_free(q, start, end)):
            continue
        if q.min_occupancy <= persons <= q.max_occupancy:
            fitting.append(q)
        elif allow_under:
            oversized.append(q)
    # „Außerhalb des Rahmens" nur anbieten, wenn nichts Passendes frei ist (harte
    # Kopplung „alles andere belegt", ADR 0076).
    return fitting if fitting else oversized


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


def _persons_fit(persons: int, quarter: Quarter) -> bool:
    """Passt die Personenzahl in die (getauschte) Unterkunft – im ausgelegten
    Rahmen ODER wenn die Richtlinie Abweichungen zulässt (ADR 0076)?"""
    return (quarter.min_occupancy <= persons <= quarter.max_occupancy
            or undersized_allowed())


@transaction.atomic
def create_swap_request(from_member, from_allocation, to_allocation, message=""):
    """Legt einen Unterkunfts-Tausch-Wunsch an (ADR 0077). Nur bei **exakt gleichem
    Zeitraum** sinnvoll – nur dann lässt sich bei Zustimmung sauber (konfliktfrei)
    tauschen. Benachrichtigt das Gegenüber."""
    if to_allocation.member_id == from_member.id:
        return None, "Das ist deine eigene Buchung."
    # Opt-out je Mitglied (#8/ADR 0078): wer keine Tausch-Anfragen möchte, kann
    # nicht als Partner angefragt werden. Server-seitig erzwungen (nicht nur im UI).
    if not to_allocation.member.accept_swap_requests:
        return None, "Dieses Mitglied nimmt derzeit keine Tausch-Anfragen an."
    if (from_allocation.start != to_allocation.start
            or from_allocation.end != to_allocation.end):
        return None, ("Ein Unterkunfts-Tausch ist nur bei genau gleichem Zeitraum "
                      "möglich.")
    if from_allocation.quarter_id == to_allocation.quarter_id:
        return None, "Ihr seid bereits in derselben Unterkunft."
    if SwapRequest.objects.filter(
            from_allocation=from_allocation, to_allocation=to_allocation,
            status=SwapRequest.PENDING).exists():
        return None, "Dafür läuft bereits eine Tausch-Anfrage."
    sr = SwapRequest.objects.create(
        from_member=from_member, to_member=to_allocation.member,
        from_allocation=from_allocation, to_allocation=to_allocation,
        message=V.strip_controls(message, max_len=500),
    )
    Notification.objects.create(
        member=to_allocation.member,
        message=(f"{from_member.display_name} möchte die Unterkunft tauschen "
                 f"({from_allocation.quarter.name} ↔ {to_allocation.quarter.name}, "
                 f"{from_allocation.start}–{from_allocation.end}). Bei Zustimmung "
                 f"wird sofort getauscht."),
        url="/meine-buchungen/",
    )
    return sr, None


@transaction.atomic
def respond_swap_request(member, swap_id, accept: bool) -> tuple[bool, str | None]:
    """Nimmt einen Tausch-Wunsch an oder lehnt ihn ab. **Bei Zustimmung wird der
    Tausch sofort ausgeführt** (die beiden Buchungen wechseln die Unterkunft; der
    Zeitraum bleibt identisch, ADR 0077) – vorher unter Sperre neu geprüft, ob er
    noch gültig ist. Benachrichtigt beide Seiten."""
    try:
        sr = SwapRequest.objects.select_for_update().select_related(
            "from_allocation", "to_allocation", "from_member").get(
            id=swap_id, to_member=member, status=SwapRequest.PENDING)
    except SwapRequest.DoesNotExist:
        return False, "Tausch-Anfrage nicht gefunden."

    if not accept:
        sr.status = SwapRequest.DECLINED
        sr.responded_at = timezone.now()
        sr.save(update_fields=["status", "responded_at"])
        Notification.objects.create(
            member=sr.from_member,
            message=(f"{member.display_name} hat deinen Unterkunfts-Tausch "
                     f"abgelehnt ({sr.from_allocation.quarter.name} ↔ "
                     f"{sr.to_allocation.quarter.name})."),
            url="/meine-buchungen/")
        return True, None

    # Zustimmung → tatsächlich tauschen. Beide Buchungen frisch unter Sperre laden
    # (Zustand kann sich seit der Anfrage geändert haben).
    try:
        a = Allocation.objects.select_for_update().select_related("quarter").get(
            id=sr.from_allocation_id)
        b = Allocation.objects.select_for_update().select_related("quarter").get(
            id=sr.to_allocation_id)
    except Allocation.DoesNotExist:
        sr.status = SwapRequest.DECLINED
        sr.responded_at = timezone.now()
        sr.save(update_fields=["status", "responded_at"])
        return False, "Der Tausch ist nicht mehr möglich (eine Buchung wurde storniert)."

    if (a.member_id != sr.from_member_id or b.member_id != member.id
            or a.start != b.start or a.end != b.end
            or a.quarter_id == b.quarter_id):
        return False, ("Der Tausch ist nicht mehr möglich – Buchung oder Zeitraum "
                       "hat sich geändert.")
    if not _persons_fit(a.persons, b.quarter) or not _persons_fit(b.persons, a.quarter):
        return False, "Die Personenzahl passt nicht zur getauschten Unterkunft."

    old_a_quarter, old_b_quarter = a.quarter, b.quarter
    a.quarter_id, b.quarter_id = b.quarter_id, a.quarter_id
    a.save(update_fields=["quarter"])
    b.save(update_fields=["quarter"])

    sr.status = SwapRequest.ACCEPTED
    sr.responded_at = timezone.now()
    sr.save(update_fields=["status", "responded_at"])

    # Andere offene Tausch-Anfragen, die eine der beiden Buchungen betreffen, sind
    # jetzt hinfällig (die Unterkünfte haben gewechselt) → schließen.
    from django.db.models import Q
    SwapRequest.objects.filter(status=SwapRequest.PENDING).filter(
        Q(from_allocation_id__in=(a.id, b.id))
        | Q(to_allocation_id__in=(a.id, b.id))
    ).exclude(id=sr.id).update(status=SwapRequest.DECLINED,
                               responded_at=timezone.now())

    Notification.objects.create(
        member=sr.from_member,
        message=(f"{member.display_name} hat zugestimmt – ihr habt getauscht: "
                 f"du bist jetzt in {old_b_quarter.name} (statt {old_a_quarter.name})."),
        url="/meine-buchungen/")
    return True, None


def pending_swaps_for(member):
    """Offene, an `member` gerichtete Wechselwünsche."""
    return list(
        SwapRequest.objects.filter(to_member=member, status=SwapRequest.PENDING)
        .select_related("from_member", "from_allocation__quarter",
                        "to_allocation__quarter")
    )


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
        year=year, note=V.strip_controls(note, max_len=200),
    )
    return t, None


def thank_for_transfer(member: Member, transfer_id) -> tuple[bool, str | None]:
    """Die empfangende Person bedankt sich für eine Tage-Übertragung (P2.7).

    Rein als private Wertschätzung: eine In-App-Benachrichtigung (+ E-Mail, je
    Opt-in) an die schenkende Person. Idempotent (genau einmal je Übertragung) und
    nur durch die tatsächliche Empfängerin auslösbar – keine öffentliche Rangliste."""
    from django.utils import timezone
    try:
        t = NightTransfer.objects.select_related("from_member").get(
            id=transfer_id, to_member=member)
    except NightTransfer.DoesNotExist:
        return False, "Übertragung nicht gefunden."
    if t.thanked_at:
        return False, "Du hast dich für diese Übertragung schon bedankt."
    t.thanked_at = timezone.now()
    t.save(update_fields=["thanked_at"])
    msg = f"{member.display_name} bedankt sich für deine {t.nights} übertragenen Tage."
    Notification.objects.create(member=t.from_member, message=msg, url="/tage-uebertragen/")
    email_member(t.from_member, "Ein Dankeschön",
                 f"Hallo {t.from_member.display_name},\n\n{msg}\n\nViele Grüße\nRe:Hof")
    return True, None


@transaction.atomic
def short_notice_days() -> int:
    """Kurzfrist-Grenze (Tage vor Anreise) aus den Buchungsregeln (ADR 0088)."""
    return BookingPolicy.get_solo().short_notice_days


def is_short_notice(start: date, today: date | None = None) -> bool:
    """Anreise höchstens `short_notice_days` entfernt → Kurzfrist (Verwirkung)."""
    today = today or date.today()
    return start <= today + timedelta(days=short_notice_days())


@transaction.atomic
def cancel_allocation(member: Member, allocation_id) -> tuple[bool, str | None]:
    """Storniert eine Buchung des Mitglieds. Vergangene Buchungen bleiben. Wird
    dadurch ein Wartelisten-Zeitraum frei, werden die Wartenden benachrichtigt.

    **Kurzfrist-Storno** (Anreise ≤ `short_notice_days`, ADR 0088): die Tage
    **verfallen** (Verwirkungs-Eintrag; zurück nur, soweit andere den Zeitraum neu
    buchen) und ALLE Mitglieder werden in der App informiert (ohne Mail)."""
    try:
        a = member.allocations.get(id=allocation_id)
    except Allocation.DoesNotExist:
        return False, "Buchung nicht gefunden."
    if a.end <= date.today():
        return False, "Vergangene Buchungen können nicht storniert werden."
    quarter, start, end = a.quarter, a.start, a.end
    short = is_short_notice(start)
    # Sofort-Meldung an die Verwaltung bei kurzfristigem Storno (vor dem Löschen).
    from .dashboard import notify_booking_activity
    notify_booking_activity(a, action="cancel")
    # Schlanken Storno-Nachweis anlegen, BEVOR die Buchung gelöscht wird (#30) –
    # damit das Mitglied in „Meine Buchungen“ sieht, dass sie wirklich raus ist.
    from ..models import CancellationLog, ForfeitedNights
    CancellationLog.objects.create(
        member=member, quarter_name=quarter.name, start=start, end=end,
        persons=a.persons, source=a.source)
    a.delete()
    if short:
        # Tage verwirken (Rückgabe nur, soweit andere den Zeitraum neu buchen) …
        ForfeitedNights.objects.create(
            member=member, year=start.year, quarter=quarter, start=start, end=end,
            nights=(end - start).days, reason="cancel")
        # … und ALLE Mitglieder in der App informieren (keine Mail; ADR 0088).
        _broadcast_spontaneously_free(quarter, start, end, exclude_member=member)
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

    # Personenzahl muss zur (ggf. neuen) Unterkunft passen – außerhalb des Rahmens
    # (mehr ODER weniger) nur, wenn die Richtlinie es zulässt (ADR 0076).
    outside = not (new_q.min_occupancy <= persons <= new_q.max_occupancy)
    if persons < 1 or (outside and not undersized_allowed()):
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

    # Mindestaufenthalt der NEUEN Dauer – entfällt bei exakter Lückenfüllung
    # (ADR 0075). Die Spontan-Vorausfrist gilt nur für neue Buchungen, nicht beim
    # Anpassen einer bestehenden (Verkürzen hat seine eigene 7-Tage-Frist unten).
    gap_fill = BookingPolicy.get_solo().allow_gap_fill \
        and is_gap_fill(new_q, new_start, new_end)
    min_n = min_nights_for_range(new_start, new_end)
    if new_nights < min_n and not gap_fill:
        return False, f"Mindestaufenthalt {min_n} Nächte (neu wären es {new_nights})."

    # Frei werdende Bereiche bestimmen. Die frühere „≥7-Tage"-Sperre beim Verkürzen
    # entfällt (ADR 0088): Kurzfrist-Verkürzen ist erlaubt, die frei werdenden Nächte
    # VERWIRKEN dann aber (wie beim Kurzfrist-Storno) – Umzug (Quartier-Wechsel)
    # verwirkt nichts (es wird nur umgezogen, nicht gekürzt).
    if quarter_changed:
        freed = [(old_q, a.start, a.end)]             # altes Quartier ganz frei
    else:
        freed = []
        if new_start > a.start:
            freed.append((old_q, a.start, new_start))
        if new_end < a.end:
            freed.append((old_q, new_end, a.end))

    a.quarter, a.start, a.end, a.persons = new_q, new_start, new_end, persons
    a.save(update_fields=["quarter", "start", "end", "persons"])

    # Frei gewordene Zeiträume melden (In-App an alle + Warteliste per Mail).
    for q, s, e in freed:
        _broadcast_spontaneously_free(q, s, e, exclude_member=member)
        notify_waitlist_if_free(q, s, e)
    # Kurzfrist-Verkürzen (nur gleiches Quartier): die frei werdenden Nächte verwirken
    # – zurück nur, soweit andere den Zeitraum neu buchen (ADR 0088).
    if not quarter_changed:
        from ..models import ForfeitedNights
        for q, s, e in freed:
            if is_short_notice(s, today):
                ForfeitedNights.objects.create(
                    member=member, year=s.year, quarter=q, start=s, end=e,
                    nights=(e - s).days, reason="shorten")
    return True, None
