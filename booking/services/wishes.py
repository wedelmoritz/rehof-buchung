"""Service-Layer (wishes): Wunschliste: Eintragen/Umsortieren/Löschen, Einreichen/Zurückziehen.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from ..models import (
    BookingPeriod, BookingPolicy, Member, Wish,
)
from .slots import _in_season_range, wish_rule_error

__all__ = [
    '_renumber_wishes', 'add_wish', 'move_wish', 'reorder_wishes',
    'delete_wish', 'submit_wishlist', 'withdraw_wishlist', 'wishes_editable',
    'wish_neighbors', 'add_wish_for_member', 'WISH_EXPORT_COLUMNS', 'wish_export_rows',
]


def add_wish_for_member(actor, member, period, quarter, start, end,
                        membership_id=None) -> tuple["Wish | None", str | None]:
    """Trägt die Verwaltung stellvertretend einen Wunsch für ein Mitglied nach und
    reicht ihn ein (ADR 0101, für Vergessene – auch in der Entzerrungsphase). Auditiert
    (`Wish.created_by = actor`, analog `book_for_member`). **Defense in depth:** das
    Recht `add_wish_for_member` wird hier zusätzlich geprüft (nicht nur in der View)."""
    from django.core.exceptions import PermissionDenied
    from .. import authz
    if not authz.user_can(actor, authz.P_ADD_WISH_FOR_MEMBER):
        raise PermissionDenied("Keine Berechtigung, Wünsche nachzutragen.")
    if member is None or member.is_external:
        return None, "Kein gültiges Mitglied gewählt."
    wish, err = add_wish(member, period, quarter, start, end,
                         membership_id=membership_id)
    if err:
        return None, err
    wish.created_by = actor
    wish.submitted = True
    wish.submitted_at = timezone.now()
    wish.save(update_fields=["created_by", "submitted", "submitted_at"])
    return wish, None


WISH_EXPORT_COLUMNS = [
    "Mitglied", "Benutzername", "Quartier", "Anreise", "Abreise", "Nächte",
    "Priorität", "Eingereicht am", "Nachgetragen von",
]


def wish_export_rows(period, *, submitted_only=True) -> list[list]:
    """Zeilen für den Wunsch-Export der Verwaltung (ADR 0101): je Wunsch eine Zeile.
    Standardmäßig nur eingereichte Wünsche (der Lostopf). Neueste Priorität zuerst je
    Mitglied. Effizient über `select_related`."""
    qs = Wish.objects.filter(period=period).select_related(
        "member", "member__user", "quarter", "created_by").order_by(
        "member__display_name", "priority")
    if submitted_only:
        qs = qs.filter(submitted=True)
    rows = []
    for w in qs:
        rows.append([
            w.member.display_name,
            w.member.user.username if w.member.user_id else "",
            w.quarter.name,
            w.start.isoformat(), w.end.isoformat(), (w.end - w.start).days,
            w.priority,
            w.submitted_at.strftime("%Y-%m-%d %H:%M") if w.submitted_at else "",
            w.created_by.get_username() if w.created_by_id else "",
        ])
    return rows


def wish_neighbors(period, member) -> list[dict]:
    """**Wunsch-Nachbarn** für private Absprachen (ADR 0101): für jeden EINGEREICHTEN
    Wunsch des Mitglieds die anderen Mitglieder mit einem **überlappenden** eingereichten
    Wunsch fürs **selbe Quartier** – mit Anzeigename **+ Telefon**, damit man sich
    außerhalb der App abstimmen kann.

    **Datenschutz (ADR 0101, DSGVO Art. 5/25):** Es erscheinen NUR Mitglieder, die die
    Sichtbarkeit nicht abgeschaltet haben (`coordination_opt_out=False`, Default sichtbar);
    nur die zwei Felder (Name/Telefon), nur überlappende Wünsche. Nur während der
    Entzerrungsphase aufzurufen (die View steuert Status/Login). Zwei DB-Abfragen.

    Gibt `[{"wish": Wish, "neighbors": [{"name","phone","start","end"}]}]`."""
    mine = list(Wish.objects.filter(period=period, member=member, submitted=True)
                .select_related("quarter").order_by("priority", "id"))
    if not mine:
        return []
    others = list(
        Wish.objects.filter(period=period, submitted=True)
        .exclude(member=member)
        .select_related("member", "member__user"))
    out: list[dict] = []
    for w in mine:
        neigh: list[dict] = []
        seen: set = set()
        for o in others:
            if o.quarter_id != w.quarter_id:
                continue
            if not (o.start < w.end and o.end > w.start):
                continue
            om = o.member
            if om.coordination_opt_out or om.id in seen:
                continue
            seen.add(om.id)
            neigh.append({"name": om.display_name, "phone": om.phone,
                          "start": o.start, "end": o.end})
        if neigh:
            out.append({"wish": w, "neighbors": neigh})
    return out


def wishes_editable(period: BookingPeriod, member: Member) -> tuple[bool, str | None]:
    """Darf `member` in `period` seine Wünsche eintragen/anpassen/einreichen? (ADR 0101)

    Bearbeitbar im **Wunsch-Fenster** (`WISHES_OPEN`) UND in der **Entzerrungsphase**
    (`WISHES_REVIEW`): dort ist die Einreiche-Frist zwar vorbei (Anzeige/Erinnerung),
    aber Anpassen bleibt bewusst möglich – der Zweck der Phase ist das **Entzerren**.
    Bewusst KEINE harte Teilnehmer-Sperre: das RSD-Losverfahren ist strategiesicher
    (späte Anpassungen sind kein Vorteil), und ein harter Riegel würde mit dem
    bestehenden Einreichen/Zurückziehen-Ablauf kollidieren (wer zum Anpassen
    zurückzieht, wäre sonst plötzlich „raus“). Eine strengere Frist ließe sich später
    ergänzen. Außerhalb dieser beiden Phasen: gesperrt (Defense in depth – die Views
    wählen die Periode ohnehin nach Status). `member` ist bewusst Teil der Signatur
    (Aufrufer übergeben ihn), damit eine spätere, feinere Teilnehmerregel keine
    Signaturänderung braucht."""
    if period.status in (BookingPeriod.WISHES_OPEN, BookingPeriod.WISHES_REVIEW):
        return True, None
    return False, "Für diese Periode können gerade keine Wünsche bearbeitet werden."

def _renumber_wishes(member: Member, period: BookingPeriod) -> None:
    """Setzt die Prioritäten lückenlos auf 1..N gemäß aktueller Reihenfolge."""
    wishes = list(
        Wish.objects.filter(member=member, period=period).order_by("priority", "id")
    )
    for i, w in enumerate(wishes, start=1):
        if w.priority != i:
            w.priority = i
            w.save(update_fields=["priority"])


def add_wish(member, period, quarter, start, end,
             membership_id=None) -> tuple[Wish | None, str | None]:
    """Fügt einen Wunsch als Entwurf ans Ende der Liste an.

    Prüft vorab, dass das Quartier im GANZEN Wunschzeitraum saisonal buchbar ist
    – sonst könnte ein Losgewinn eine Buchung außerhalb der Quartier-Saison
    erzeugen (z.B. Anreise noch in Saison, Abreise schon außerhalb).

    Der Wunsch wird einem Mitglieds-Anteil zugerechnet (Default: eindeutiger/
    größter Anteil; bei Mehrfach-Tandem die Wahl), damit das Parallel-Limit/der
    Aufenthaltsdeckel in der Losung auf den vollen Anteil wirkt (ADR 0066)."""
    if not member.can_book:
        return None, ("Dein Konto ist derzeit nicht buchungsberechtigt "
                      "(passives/ausgeschiedenes Mitglied).")
    ok, reason = wishes_editable(period, member)
    if not ok:
        return None, reason
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
    # Exakte Doppel-Wünsche verhindern (Feedback #2a): dieselbe Unterkunft im exakt
    # gleichen Zeitraum nicht zweimal. Bewusst nur exakte Duplikate – überlappende
    # Wünsche bleiben zulässig (Losverfahren-Konzept unberührt).
    if Wish.objects.filter(member=member, period=period, quarter=quarter,
                           start=start, end=end).exists():
        return None, ("Diesen Wunsch hast du schon eingetragen (gleiche Unterkunft "
                      "und gleicher Zeitraum).")
    # Optionale Obergrenze je Periode (Feedback #5, ADR 0078): standardmäßig 0 =
    # unbegrenzt (bewusst, damit Rückfall-Wünsche möglich bleiben). Nur wenn die
    # Delegation eine Grenze setzt, wird beim Eintragen server-seitig geprüft.
    cap = BookingPolicy.get_solo().max_wishes_per_period or 0
    if cap and Wish.objects.filter(member=member, period=period).count() >= cap:
        return None, (f"Du kannst höchstens {cap} Wünsche je Periode eintragen. "
                      "Bitte ordne stattdessen deine bestehenden Wünsche nach "
                      "Priorität oder entferne einen.")
    last = (
        Wish.objects.filter(member=member, period=period)
        .order_by("-priority").first()
    )
    next_prio = (last.priority + 1) if last else 1
    wish = Wish.objects.create(
        member=member, period=period, quarter=quarter, start=start, end=end,
        priority=next_prio, submitted=False,
        membership=member.membership_for(membership_id),
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
    if not member.can_book:
        return 0, ("Dein Konto ist derzeit nicht buchungsberechtigt "
                   "(passives/ausgeschiedenes Mitglied).")
    ok, reason = wishes_editable(period, member)
    if not ok:
        return 0, reason
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
