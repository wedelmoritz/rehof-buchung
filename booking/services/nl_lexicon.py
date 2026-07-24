"""Service (nl_lexicon): das aktive, bestätigte Lexikon + Übernehmen/Ablehnen/Rollback
(ADR 0113, Batch NL-L3).

Das Lexikon ist **injizierte Daten** (kein Code): der Parser bleibt deterministisch/
testbar (`wish_nl`, `learned=`-Parameter). Übernehmen härtet den Wert **beim Schreiben**
(Allowlist, Längenlimit, Ambiguitäts-Sperre) – Gelerntes wird nie als Code, nur als
Vergleichs-Token genutzt.
"""
from __future__ import annotations

import re

from django.utils import timezone

from .. import wish_nl
from ..models import NlLexiconEntry, NlProposal, Quarter
from .nl_learn_ops import nl_known_tokens

__all__ = ["nl_active_lexicon", "apply_proposal", "reject_proposal", "retire_entry",
           "active_lexicon_entries"]

# Alias-Token: nur Kleinbuchstaben/Ziffern (der Parser normalisiert ohnehin so), 2–32.
_ALIAS_RE = re.compile(r"^[a-z0-9]{2,32}$")


def nl_active_lexicon() -> dict:
    """Das aktive Lexikon als injizierbares Dict für den Parser (ADR 0113):
    `{"aliases": {token: quarter_id}, "rankings": {season: [monat,…]}}`. Effizient
    (eine Abfrage); leer, wenn nichts aktiv ist."""
    aliases: dict = {}
    rankings: dict = {}
    for e in NlLexiconEntry.objects.filter(active=True).only("kind", "payload"):
        if e.kind == NlLexiconEntry.ALIAS:
            tok, qid = e.payload.get("token"), e.payload.get("quarter_id")
            if tok and isinstance(qid, int):
                aliases[tok] = qid
        elif e.kind == NlLexiconEntry.RANKING:
            season, order = e.payload.get("season"), e.payload.get("order")
            if season and isinstance(order, list):
                rankings[season] = order
    return {"aliases": aliases, "rankings": rankings}


def active_lexicon_entries():
    """Aktive Einträge (für die Verwaltungs-/Rollback-Ansicht, NL-L5)."""
    return NlLexiconEntry.objects.filter(active=True).order_by("-created_at")


def _validate_alias(token, quarter_id) -> str | None:
    if not (isinstance(token, str) and _ALIAS_RE.match(token)):
        return "Ungültiges Alias-Token."
    # Ambiguitäts-Sperre: kein bereits verstandenes Wort zum Alias machen.
    if token in nl_known_tokens():
        return "Dieses Wort versteht der Parser bereits – kein Alias nötig."
    q = Quarter.objects.filter(id=quarter_id, active=True).first()
    if not q:
        return "Zielquartier existiert nicht (mehr)."
    # Kein Konflikt mit einem bereits aktiven Alias auf ein ANDERES Quartier.
    other = (NlLexiconEntry.objects
             .filter(active=True, kind=NlLexiconEntry.ALIAS, payload__token=token)
             .exclude(payload__quarter_id=quarter_id).first())
    if other:
        return "Für dieses Wort gibt es bereits einen anderen aktiven Alias."
    return None


def _validate_ranking(season, order) -> str | None:
    if season not in wish_nl._SEASONS:
        return "Unbekannte Jahreszeit."
    if (not isinstance(order, list)
            or sorted(order) != sorted(wish_nl._SEASONS[season])):
        return "Reihung muss eine Permutation der Jahreszeit-Monate sein."
    return None


def apply_proposal(proposal: NlProposal, user):
    """Übernimmt einen Vorschlag als aktiven Lexikon-Eintrag (gehärtet + Ambiguitäts-
    Sperre). Idempotent pro `dedup_key` (bestehende aktive Einträge desselben Schlüssels
    werden ersetzt). Markiert den Vorschlag als angenommen. Gibt (entry, None) bzw.
    (None, Fehlertext)."""
    if proposal.status != NlProposal.OPEN:
        return None, "Dieser Vorschlag ist bereits entschieden."
    p = proposal.payload or {}
    if proposal.kind == NlProposal.ALIAS:
        err = _validate_alias(p.get("token"), p.get("quarter_id"))
        payload = {"token": p.get("token"), "quarter_id": p.get("quarter_id")}
    elif proposal.kind == NlProposal.RANKING:
        err = _validate_ranking(p.get("season"), p.get("new_order"))
        payload = {"season": p.get("season"), "order": p.get("new_order")}
    else:
        err = "Unbekannte Vorschlagsklasse."
        payload = {}
    if err:
        return None, err

    # Denselben Schlüssel aktiv nur einmal führen (neuer Stand ersetzt alten).
    NlLexiconEntry.objects.filter(
        active=True, dedup_key=proposal.dedup_key).update(active=False)
    entry = NlLexiconEntry.objects.create(
        kind=proposal.kind, dedup_key=proposal.dedup_key, payload=payload,
        active=True, source_proposal=proposal, approved_by=user,
        evidence=proposal.evidence or {})
    proposal.status = NlProposal.ACCEPTED
    proposal.decided_at = timezone.now()
    proposal.decided_by = user
    proposal.save(update_fields=["status", "decided_at", "decided_by"])
    return entry, None


def reject_proposal(proposal: NlProposal, user) -> bool:
    """Lehnt einen Vorschlag ab (wird nicht erneut vorgeschlagen). Idempotent."""
    if proposal.status != NlProposal.OPEN:
        return False
    proposal.status = NlProposal.REJECTED
    proposal.decided_at = timezone.now()
    proposal.decided_by = user
    proposal.save(update_fields=["status", "decided_at", "decided_by"])
    return True


def retire_entry(entry: NlLexiconEntry) -> bool:
    """Rollback: einen aktiven Eintrag deaktivieren (der Parser nutzt ihn sofort
    nicht mehr)."""
    if not entry.active:
        return False
    entry.active = False
    entry.save(update_fields=["active"])
    return True
