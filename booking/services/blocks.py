"""Service-Layer (blocks): Sperrzeit-Konflikte, dringende Sperrung, Umbuchung,
Ausgleichs-Tage (ADR 0097).

Eine Sperrzeit ist wie eine Belegung: sie darf eine bestehende Buchung nicht
still überlagern. Regulär (≥ `block_min_notice_days` Vorlauf) muss die BL das mit
den Mitgliedern klären; im dringenden Fall (z. B. Wasserrohrbruch) gibt es einen
Umbuchungs-/Ausgleichs-Workflow.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from ..models import (
    Allocation, BookingPolicy, CompensationGrant, ExternalBooking, Notification,
    Quarter, QuarterBlock, RelocationRequest,
)
from .notify import absolute_url, email_member
from .slots import quarter_is_free, range_is_released

__all__ = [
    "block_min_notice_days", "max_compensation_days", "block_conflicts",
    "block_within_notice", "suggest_block_window", "relocation_options",
    "create_quarter_block", "propose_relocation", "respond_relocation",
    "cancel_with_apology", "pending_relocation_requests",
    "count_relocations_needed",
]

_BLOCK_MSG = (
    "Das geht nicht: Der Zeitraum überschneidet sich mit bestehenden Buchungen. "
    "Falls die Sperrzeit unbedingt nötig ist, geh bitte zuerst auf die unten "
    "genannten eingebuchten Mitglieder zu und kläre das mit ihnen – das ist nur "
    "bis spätestens {days} Tage vorher möglich, damit sie sich darauf einlassen "
    "können.")


def block_min_notice_days() -> int:
    return BookingPolicy.get_solo().block_min_notice_days or 0


def max_compensation_days() -> int:
    return BookingPolicy.get_solo().max_compensation_days or 0


def block_conflicts(quarter, start: date, end: date, exclude_block_id=None):
    """Bestehende Belegungen, die eine Sperrzeit [start, end) im Quartier überlagern:
    Mitglieder-Buchungen (`allocations`) und bestätigte externe Buchungen. Gibt
    ``(member_allocations, external_bookings)`` zurück."""
    allocs = list(Allocation.objects.filter(
        quarter=quarter, start__lt=end, end__gt=start, provisional=False)
        .select_related("member", "member__user").order_by("start"))
    ext = list(ExternalBooking.objects.filter(
        quarter=quarter, status=ExternalBooking.CONFIRMED,
        start__lt=end, end__gt=start).order_by("start"))
    return allocs, ext


def block_within_notice(start: date, today: date | None = None) -> bool:
    """True, wenn die Sperrung **innerhalb** des Absprache-Vorlaufs beginnt
    (dringender Fall) – dann ist die reguläre Vorab-Absprache nicht mehr möglich."""
    today = today or date.today()
    return (start - today).days < block_min_notice_days()


def suggest_block_window(quarter, start: date, end: date, horizon_days: int = 180):
    """Sucht ab `start` vorwärts das **nächste freie** Fenster gleicher Länge im
    Quartier (frei + freigeschaltet), das keine Buchung überlagert. Gibt
    ``(neu_start, neu_end)`` zurück oder ``None``, wenn im Horizont nichts frei ist."""
    length = (end - start).days
    if length <= 0:
        return None
    cur = start + timedelta(days=1)
    limit = start + timedelta(days=horizon_days)
    while cur <= limit:
        c_end = cur + timedelta(days=length)
        allocs, ext = block_conflicts(quarter, cur, c_end)
        if not allocs and not ext:
            return cur, c_end
        cur += timedelta(days=1)
    return None


def relocation_options(alloc) -> dict:
    """Freie Ersatz-Unterkünfte für den Zeitraum der Buchung (ohne die gesperrte).
    Getrennt in **passend** (Personenzahl im Rahmen) und **zu klein** (`undersized`),
    damit die BL bewusst wählen kann."""
    fitting, undersized = [], []
    for q in Quarter.objects.filter(active=True).order_by("sort_order", "name"):
        if q.id == alloc.quarter_id:
            continue
        if not (range_is_released(q, alloc.start, alloc.end)
                and quarter_is_free(q, alloc.start, alloc.end)):
            continue
        if q.min_occupancy <= alloc.persons <= q.max_occupancy:
            fitting.append(q)
        else:
            undersized.append(q)
    return {"fitting": fitting, "undersized": undersized}


@transaction.atomic
def create_quarter_block(quarter, start: date, end: date, reason: str, *,
                         force: bool = False, actor=None) -> dict:
    """Legt eine Sperrzeit an – aber **nicht**, wenn sie eine Buchung überlagert und
    nicht `force` gesetzt ist. Rückgabe:
    ``{"block": <QuarterBlock|None>, "allocs": [...], "ext": [...],
       "suggestion": (s,e)|None, "within_notice": bool}``.
    Bei Konflikt ohne `force` ist ``block`` None; mit `force` wird trotzdem angelegt
    (dringender Fall) und die Konflikte werden zur Umbuchung zurückgegeben."""
    allocs, ext = block_conflicts(quarter, start, end)
    conflict = bool(allocs or ext)
    info = {
        "block": None, "allocs": allocs, "ext": ext,
        "suggestion": suggest_block_window(quarter, start, end) if conflict else None,
        "within_notice": block_within_notice(start),
    }
    if conflict and not force:
        return info
    from ..validation import strip_controls
    block = QuarterBlock.objects.create(
        quarter=quarter, start=start, end=end,
        reason=strip_controls(reason or "", max_len=200))
    info["block"] = block
    return info


def propose_relocation(alloc, to_quarter, reason: str, *, actor=None,
                       block=None) -> RelocationRequest:
    """Schlägt dem Mitglied eine Ersatz-Unterkunft für seine (bald gesperrte) Buchung
    vor. Legt eine `RelocationRequest` an und benachrichtigt das Mitglied (In-App +
    Mail). `undersized` wird automatisch aus der Personenzahl bestimmt."""
    from ..validation import strip_controls
    undersized = not (to_quarter.min_occupancy <= alloc.persons
                      <= to_quarter.max_occupancy)
    reason = strip_controls(reason or "", max_len=300)
    req = RelocationRequest.objects.create(
        member=alloc.member, allocation=alloc, from_quarter=alloc.quarter,
        to_quarter=to_quarter, undersized=undersized, reason=reason)
    note = (f" Hinweis: {to_quarter.name} ist kleiner als eure Gruppe "
            f"({alloc.persons} Pers.)." if undersized else "")
    msg = (f"Die Verwaltung muss {alloc.quarter.name} für deinen Zeitraum "
           f"({alloc.start:%d.%m.}–{alloc.end:%d.%m.%Y}) sperren"
           f"{f' ({reason})' if reason else ''} und schlägt dir {to_quarter.name} "
           f"als Ersatz vor.{note} Bitte in „Meine Buchungen“ annehmen oder ablehnen.")
    Notification.objects.create(member=alloc.member, message=msg[:255],
                                detail=msg, url="/meine-buchungen/")
    email_member(alloc.member, "Re:Hof: Umbuchungs-Vorschlag der Verwaltung", msg)
    return req


@transaction.atomic
def respond_relocation(member, request_id, accept: bool) -> tuple[bool, str | None]:
    """Mitglied nimmt einen Umbuchungs-Vorschlag an (Buchung zieht **sofort** um –
    unter Sperre neu geprüft) oder lehnt ihn ab. Benachrichtigt die Verwaltung."""
    from .dashboard import notify_booking_activity
    try:
        req = RelocationRequest.objects.select_for_update().select_related(
            "allocation", "to_quarter", "from_quarter").get(
            id=request_id, member=member, status=RelocationRequest.PROPOSED)
    except RelocationRequest.DoesNotExist:
        return False, "Umbuchungs-Anfrage nicht gefunden."

    if not accept:
        req.status = RelocationRequest.REJECTED
        req.responded_at = timezone.now()
        req.save(update_fields=["status", "responded_at"])
        _notify_staff(f"{member.display_name} hat die vorgeschlagene Umbuchung nach "
                      f"{req.to_quarter.name} abgelehnt ({req.from_quarter.name}, "
                      f"{req.allocation.start:%d.%m.}–{req.allocation.end:%d.%m.%Y}).")
        return True, None

    try:
        a = Allocation.objects.select_for_update().get(id=req.allocation_id)
    except Allocation.DoesNotExist:
        req.status = RelocationRequest.CANCELLED
        req.responded_at = timezone.now()
        req.save(update_fields=["status", "responded_at"])
        return False, "Die Buchung besteht nicht mehr."
    # Zielquartier noch frei? (Zustand kann sich seit dem Vorschlag geändert haben.)
    if not quarter_is_free(req.to_quarter, a.start, a.end):
        return False, (f"{req.to_quarter.name} ist inzwischen belegt – bitte die "
                       "Verwaltung ansprechen.")
    a.quarter = req.to_quarter
    a.save(update_fields=["quarter"])
    req.status = RelocationRequest.ACCEPTED
    req.responded_at = timezone.now()
    req.save(update_fields=["status", "responded_at"])
    _notify_staff(f"{member.display_name} hat die Umbuchung nach {req.to_quarter.name} "
                  f"angenommen ({req.allocation.start:%d.%m.}–{req.allocation.end:%d.%m.%Y}).")
    return True, None


@transaction.atomic
def cancel_with_apology(alloc, reason: str, compensation_days: int, *,
                        actor=None) -> dict:
    """Storniert eine Buchung wegen einer dringenden Sperrung, wenn keine (akzeptierte)
    Ersatz-Unterkunft möglich ist: die gebuchten Tage kommen **normal zurück** (kein
    Verfall – die BL verursacht es), optional werden bis zu `max_compensation_days`
    Ausgleichs-Tage gutgeschrieben, und das Mitglied bekommt eine Entschuldigung mit
    Grund. Gibt ``{"compensation": n}`` zurück."""
    from ..models import CancellationLog
    from ..validation import strip_controls
    reason = strip_controls(reason or "", max_len=300)
    days = max(0, min(int(compensation_days or 0), max_compensation_days()))
    member = alloc.member
    quarter, start, end = alloc.quarter, alloc.start, alloc.end
    CancellationLog.objects.create(
        member=member, quarter_name=quarter.name, start=start, end=end,
        persons=alloc.persons, source=alloc.source)
    # Offene Umbuchungs-Anfragen zu dieser Buchung schließen.
    RelocationRequest.objects.filter(
        allocation=alloc, status=RelocationRequest.PROPOSED).update(
        status=RelocationRequest.CANCELLED, responded_at=timezone.now())
    alloc.delete()
    if days:
        CompensationGrant.objects.create(
            member=member, year=start.year, days=days, reason=reason,
            created_by=actor if getattr(actor, "pk", None) else None)
    extra = (f" Als Ausgleich schreiben wir dir {days} zusätzliche "
             f"{'Tage' if days != 1 else 'Tag'} gut." if days else "")
    msg = (f"Es tut uns leid: Wir mussten {quarter.name} für deinen Zeitraum "
           f"({start:%d.%m.}–{end:%d.%m.%Y}) dringend sperren"
           f"{f' ({reason})' if reason else ''} und konnten dir keine passende "
           f"Ersatz-Unterkunft anbieten. Deine Buchung wurde storniert und die Tage "
           f"deinem Kontingent gutgeschrieben.{extra}")
    Notification.objects.create(member=member, message=msg[:255], detail=msg,
                                url="/meine-buchungen/")
    email_member(member, "Re:Hof: Entschuldigung – deine Buchung musste storniert werden",
                 msg)
    return {"compensation": days}


def pending_relocation_requests(member):
    """Offene Umbuchungs-Vorschläge für ein Mitglied (für „Meine Buchungen“)."""
    return list(member.relocation_requests.filter(
        status=RelocationRequest.PROPOSED)
        .select_related("from_quarter", "to_quarter", "allocation"))


def count_relocations_needed(today: date | None = None) -> int:
    """Anzahl der Buchungen, die aktuell mit einer (künftigen) Sperrzeit kollidieren –
    also noch umgebucht oder storniert-entschuldigt werden müssen (Badge fürs
    Dashboard). Angenommene Umbuchungen zählen nicht mehr (die Buchung ist dann aus
    dem gesperrten Quartier heraus)."""
    today = today or date.today()
    n = 0
    for b in QuarterBlock.objects.filter(end__gte=today).only(
            "quarter_id", "start", "end"):
        n += Allocation.objects.filter(
            quarter_id=b.quarter_id, start__lt=b.end, end__gt=b.start,
            provisional=False).count()
    return n


def _notify_staff(text: str) -> None:
    """Kurze Info an die Verwaltungs-Adressen (Umbuchung angenommen/abgelehnt)."""
    from .notify import email_admins
    email_admins("Re:Hof: Antwort auf Umbuchungs-Vorschlag", text)
