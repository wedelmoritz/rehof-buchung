"""Service-Layer (wishes): Wunschliste: Eintragen/Umsortieren/Löschen.

Wünsche sind ab dem Eintragen verbindlich und nehmen an der Losung teil (kein
„Einreichen"/Entwurf mehr, wie beim Buchen; ADR 0101).

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
    '_renumber_wishes', 'add_wish', 'adjust_wish', 'move_wish', 'reorder_wishes',
    'delete_wish', 'wishes_editable', 'wish_demand_band',
    'wish_coordination', 'add_wish_for_member', 'WISH_EXPORT_COLUMNS', 'wish_export_rows',
]


def add_wish_for_member(actor, member, period, quarter, start, end,
                        membership_id=None) -> tuple["Wish | None", str | None]:
    """Trägt die Verwaltung stellvertretend einen Wunsch für ein Mitglied nach (ADR 0101,
    für Vergessene – auch in der Entzerrungsphase). Der Wunsch ist ab dem Eintragen
    verbindlich. Auditiert (`Wish.created_by = actor`, analog `book_for_member`).
    **Defense in depth:** das Recht `add_wish_for_member` wird hier zusätzlich geprüft
    (nicht nur in der View)."""
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
    wish.save(update_fields=["created_by"])
    return wish, None


WISH_EXPORT_COLUMNS = [
    "Mitglied", "Benutzername", "Quartier", "Anreise", "Abreise", "Nächte",
    "Priorität", "Aufgenommen am", "Nachgetragen von",
]


def wish_export_rows(period) -> list[list]:
    """Zeilen für den Wunsch-Export der Verwaltung (ADR 0101): je Wunsch eine Zeile
    (alle Wünsche der Periode nehmen an der Losung teil). Nach Mitglied + Priorität
    sortiert. Effizient über `select_related`."""
    qs = Wish.objects.filter(period=period).select_related(
        "member", "member__user", "quarter", "created_by").order_by(
        "member__display_name", "priority")
    rows = []
    for w in qs:
        rows.append([
            w.member.display_name,
            w.member.user.username if w.member.user_id else "",
            w.quarter.name,
            w.start.isoformat(), w.end.isoformat(), (w.end - w.start).days,
            w.priority,
            w.added_at.strftime("%Y-%m-%d %H:%M") if w.added_at else "",
            w.created_by.get_username() if w.created_by_id else "",
        ])
    return rows


def wish_coordination(period, member) -> dict:
    """**Wunsch-Details je Wunsch** für die Entzerrung (ADR 0101, Batch 2): für jeden
    Wunsch des Mitglieds die anderen Mitglieder mit einem **überlappenden** Wunsch fürs
    **selbe Quartier** (für private Absprachen) UND die Zahl dieser Überlappungen (als
    Chancen-Begründung, zusammen mit der eigenen Priorität).

    **Wir setzen auf Begegnung:** Der **Anzeigename** überlappender Mitglieder ist immer
    sichtbar. **Kontaktkanäle je einzeln verbergbar** (`coordination_hide_phone`/
    `coordination_hide_email`, Default beide sichtbar) – so kann man sich außerhalb der
    App abstimmen. **Datenschutz (DSGVO Art. 5/25):** nur überlappende Wünsche, nur
    Name + die nicht verborgenen Kanäle. Nur in der Entzerrungsphase aufzurufen (die
    View steuert Status/Login). Zwei DB-Abfragen.

    Gibt `{wish_id: {"neighbors": [{"name","phone","email","start","end"}],
    "overlap_count": int}}` (nur Wünsche mit mindestens einer Überlappung)."""
    mine = list(Wish.objects.filter(period=period, member=member)
                .select_related("quarter").order_by("priority", "id"))
    if not mine:
        return {}
    others = list(
        Wish.objects.filter(period=period)
        .exclude(member=member)
        .select_related("member", "member__user"))
    out: dict = {}
    for w in mine:
        neigh: list[dict] = []
        seen: set = set()
        for o in others:
            if o.quarter_id != w.quarter_id:
                continue
            if not (o.start < w.end and o.end > w.start):
                continue
            om = o.member
            if om.id in seen:
                continue
            seen.add(om.id)
            neigh.append({
                "name": om.display_name,
                "phone": "" if om.coordination_hide_phone else om.phone,
                "email": "" if om.coordination_hide_email else (
                    om.user.email if om.user_id else ""),
                "start": o.start, "end": o.end,
            })
        if neigh:
            out[w.id] = {"neighbors": neigh, "overlap_count": len(neigh)}
    return out


def wish_demand_band(overlap_count: int) -> dict:
    """Nachfrage-/Beliebtheits-Ampel je Wunsch (ADR 0101 Batch 2-Nachtrag): leitet aus
    der Zahl der Mitglieder mit einem **überlappenden** Wunsch fürs selbe Quartier ein
    verständliches Band ab – bewusst OHNE Prozentzahl (die Los-Gewinn-Chance ist eine
    andere Größe und wird separat qualitativ gezeigt). Positive Wortwahl (ADR 0072).

    Gibt `{"key","label","tone"}` – tone steuert die Farbe (good/open/warn/bad)."""
    if overlap_count <= 0:
        return {"key": "none", "label": "Keine anderen Wünsche", "tone": "good"}
    if overlap_count <= 2:
        return {"key": "few", "label": "Wenige andere Wünsche", "tone": "open"}
    if overlap_count <= 4:
        return {"key": "popular", "label": "Beliebt", "tone": "warn"}
    return {"key": "hot", "label": "Sehr beliebt", "tone": "bad"}


def wishes_editable(period: BookingPeriod, member: Member) -> tuple[bool, str | None]:
    """Darf `member` in `period` seine Wünsche eintragen/anpassen? (ADR 0101)

    Bearbeitbar im **Wunsch-Fenster** (`WISHES_OPEN`) UND in der **Entzerrungsphase**
    (`WISHES_REVIEW`): dort ist die Frist zwar vorbei (Anzeige/Erinnerung), aber
    Anpassen bleibt bewusst möglich – der Zweck der Phase ist das **Entzerren**.
    Wünsche sind ab dem Eintragen verbindlich (kein Einreichen/Zurückziehen mehr),
    jede Änderung zählt sofort. Bewusst KEINE harte Teilnehmer-Sperre: das
    RSD-Losverfahren ist strategiesicher (späte Anpassungen sind kein Vorteil). Eine
    strengere Frist ließe sich später ergänzen. Außerhalb dieser beiden Phasen:
    gesperrt (Defense in depth – die Views wählen die Periode ohnehin nach Status).
    `member` ist bewusst Teil der Signatur (Aufrufer übergeben ihn), damit eine
    spätere, feinere Teilnehmerregel keine Signaturänderung braucht."""
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
    """Fügt einen Wunsch ans Ende der Liste an. Er ist ab dem Eintragen verbindlich
    und nimmt an der Losung teil (kein Einreichen/Entwurf mehr, ADR 0101).

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
    # Wünsche sind ab dem Eintragen verbindlich und nehmen an der Losung teil
    # (kein „Einreichen"/Entwurf mehr, wie beim Buchen).
    wish = Wish.objects.create(
        member=member, period=period, quarter=quarter, start=start, end=end,
        priority=next_prio, added_at=timezone.now(),
        membership=member.membership_for(membership_id),
    )
    return wish, None


@transaction.atomic
def adjust_wish(member, period, wish_id, quarter, start, end) -> tuple["Wish | None", str | None]:
    """Ändert einen bestehenden Wunsch (anderer Zeitraum und/oder andere Unterkunft)
    an Ort und Stelle – ohne die Priorität zu verlieren. Es gelten dieselben Prüfungen
    wie beim Eintragen (Phase bearbeitbar, gültiger Zeitraum, Quartier-Saison,
    Mindestnächte/Deckel, keine exakte Doppelung). ADR 0101 Batch 2-Nachtrag."""
    if not member.can_book:
        return None, ("Dein Konto ist derzeit nicht buchungsberechtigt "
                      "(passives/ausgeschiedenes Mitglied).")
    ok, reason = wishes_editable(period, member)
    if not ok:
        return None, reason
    wish = Wish.objects.filter(id=wish_id, member=member, period=period).first()
    if wish is None:
        return None, "Wunsch nicht gefunden."
    if (end - start).days <= 0:
        return None, "Ungültiger Zeitraum (Abreise muss nach Anreise liegen)."
    if not _in_season_range(quarter, start, end):
        return None, (f"{quarter.name} ist in diesem Zeitraum nicht durchgängig "
                      "buchbar (Quartier-Saison). Bitte den gesamten Zeitraum "
                      "innerhalb der Saison wählen.")
    rule_err = wish_rule_error(start, end)
    if rule_err:
        return None, rule_err
    # Exakte Doppelung mit einem ANDEREN eigenen Wunsch verhindern.
    if Wish.objects.filter(member=member, period=period, quarter=quarter,
                           start=start, end=end).exclude(id=wish.id).exists():
        return None, ("Diesen Wunsch hast du schon eingetragen (gleiche Unterkunft "
                      "und gleicher Zeitraum).")
    wish.quarter = quarter
    wish.start = start
    wish.end = end
    wish.save(update_fields=["quarter", "start", "end"])
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


