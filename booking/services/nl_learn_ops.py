"""Service (nl_learn_ops): der **Lerner** (ADR 0113, Batch NL-L2).

Liest die pseudonymen Lern-Signale (`NlInteraction`), filtert bekannte Tokens weg,
reicht schlichte Dicts an die reine, poisoning-feste Aggregation (`booking.nl_mining`)
und macht aus den Kandidaten **`NlProposal`**-Zeilen zur menschlichen Bestätigung
(NL-L5). Idempotent über `dedup_key`; respektiert getroffene Entscheidungen.

Läuft nur bei aktivem Opt-in, nachts/off-peak über `learn_nl_proposals` (Scheduler).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .. import nl_mining, wish_nl
from ..models import EquivalenceClass, NlInteraction, NlProposal, Quarter
from .nl_learn import nl_learning_active

log = logging.getLogger("booking.nl_learn")

__all__ = ["mine_nl_proposals", "nl_known_tokens", "open_proposals"]

# Konservative Schwellen (bewusst hoch → bei kleiner Datenmenge lieber selten als falsch;
# ADR 0113). Später konfigurierbar; für Phase 1 fixe, getestete Werte.
QUORUM = 3
MIN_EXCLUSIVITY = 0.8
MIN_SPAN_DAYS = 3
RANK_QUORUM = 3
RANK_EXCLUSIVITY = 0.6


def nl_known_tokens() -> set[str]:
    """Tokens, die der Parser ohnehin kennt (Monate, Jahreszeiten, Quartier-/Klassen-
    Namen) – für Alias-Kandidaten uninteressant und werden herausgefiltert."""
    known: set[str] = set(wish_nl._MONTHS) | set(wish_nl._SEASONS)
    for name in Quarter.objects.filter(active=True).values_list("name", flat=True):
        known |= set(wish_nl.tokens_of(name))
    for name in EquivalenceClass.objects.values_list("name", flat=True):
        known |= set(wish_nl.tokens_of(name))
    return known


def _alias_events(rows, known: set[str]):
    for r in rows:
        if r.proposed_quarter_id is not None or r.chosen_quarter_id is None:
            continue                         # nur wo der Parser KEIN Quartier fand
        day = r.created_at.toordinal()
        for tok in (r.unresolved or []):
            if tok and tok not in known:
                yield {"pseudo": r.pseudonym, "token": tok,
                       "quarter": r.chosen_quarter_id, "day": day}


def _ranking_events(rows):
    for r in rows:
        if r.chosen_month is None:
            continue
        for tok in (r.unresolved or []):
            if tok in wish_nl._SEASONS:
                yield {"pseudo": r.pseudonym, "season": tok, "month": r.chosen_month}


def _upsert(kind: str, dedup_key: str, payload: dict, evidence: dict) -> bool:
    """Legt einen offenen Vorschlag an ODER frischt die Belege eines noch offenen auf.
    Bereits entschiedene (accepted/rejected) bleiben unangetastet (kein Re-Vorschlag).
    Gibt True zurück, wenn neu angelegt."""
    obj, created = NlProposal.objects.get_or_create(
        dedup_key=dedup_key,
        defaults={"kind": kind, "payload": payload, "evidence": evidence})
    if not created and obj.status == NlProposal.OPEN:
        obj.payload, obj.evidence = payload, evidence
        obj.save(update_fields=["payload", "evidence"])
    return created


@transaction.atomic
def mine_nl_proposals() -> dict:
    """Ein Lern-Lauf: aus den Signalen robuste Kandidaten bilden und als Vorschläge
    ablegen. Gibt `{alias, ranking}` = Anzahl NEU angelegter Vorschläge. No-op ohne
    Opt-in."""
    if not nl_learning_active():
        return {"alias": 0, "ranking": 0}
    rows = list(NlInteraction.objects.filter(outcome_at__isnull=False)
                .only("pseudonym", "unresolved", "proposed_quarter_id",
                      "chosen_quarter_id", "chosen_month", "created_at"))
    known = nl_known_tokens()

    n_alias = 0
    for c in nl_mining.mine_alias_candidates(
            _alias_events(rows, known), quorum=QUORUM,
            min_exclusivity=MIN_EXCLUSIVITY, min_span_days=MIN_SPAN_DAYS):
        if _upsert("alias", f"alias:{c.token}:{c.quarter_id}",
                   {"token": c.token, "quarter_id": c.quarter_id},
                   {"distinct_users": c.distinct_users, "support": c.support,
                    "exclusivity": c.exclusivity, "span_days": c.span_days}):
            n_alias += 1

    orders = {s: list(v) for s, v in wish_nl._SEASONS.items()}
    n_rank = 0
    for c in nl_mining.mine_ranking_candidates(
            _ranking_events(rows), orders, quorum=RANK_QUORUM,
            min_exclusivity=RANK_EXCLUSIVITY):
        if _upsert("ranking", f"ranking:{c.season}:{c.month}",
                   {"season": c.season, "month": c.month,
                    "new_order": list(c.new_order)},
                   {"distinct_users": c.distinct_users,
                    "old_order": list(c.old_order)}):
            n_rank += 1
    return {"alias": n_alias, "ranking": n_rank}


def open_proposals():
    """Offene Vorschläge (neueste zuerst) – für die Review-Seite (NL-L5)."""
    return NlProposal.objects.filter(status=NlProposal.OPEN).order_by("-created_at")
