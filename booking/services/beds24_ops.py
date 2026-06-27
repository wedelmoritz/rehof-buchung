"""Service-Layer (beds24_ops): Beds24-Migration: CSV-Staging, Mitglied anlegen, Übernahme als Buchungen.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from django.db import transaction
from ..models import (
    Allocation, Member, Quarter,
)

__all__ = [
    '_beds24_member_candidates', '_beds24_quarter_candidates',
    'beds24_stage', 'beds24_create_member', 'beds24_apply',
]

def _beds24_member_candidates():
    """Mitglieder als Match-Kandidaten mit allen Namensvarianten."""
    import re
    from .. import beds24
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
    from .. import beds24
    return [beds24.Candidate(key=q.id, names=[q.name]) for q in Quarter.objects.all()]


def beds24_stage(data: str, filename: str):
    """Parst den Beds24-CSV-Export, legt einen Import-Lauf mit Zeilen an und
    hängt automatische Vorschläge (Mitglied/Quartier) an. Liefert den Import."""
    from .. import beds24
    from ..models import Beds24Import, Beds24ImportRow
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
    from ..models import Membership, Share
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
    from ..models import Beds24ImportRow
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
