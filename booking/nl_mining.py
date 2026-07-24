"""Reine Logik (Django-frei): robuste Aggregation der NL-Lern-Signale zu Kandidaten
(ADR 0113, Batch NL-L2).

**Poisoning-fest by design:** das Quorum zählt **verschiedene Pseudonyme** (jedes zählt
höchstens **1 Stimme**), dazu **Exklusivität** (ein Token muss überwiegend auf DASSELBE
Quartier zeigen) und **Zeit-Stabilität** (kein Ein-Tages-Ausbruch). Ein einzelner
Vielschreiber (ein Pseudonym) erreicht das Quorum damit nie – unabhängig von der Zahl
seiner Eingaben.

Kein DB-Zugriff → isoliert testbar (`tests/test_nl_mining.py`). Der Service (`nl_learn_ops`)
liest die pseudonymen Signale, reicht sie als schlichte Dicts herein und macht aus den
Kandidaten `NlProposal`-Zeilen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class AliasCandidate:
    """Vorschlag: `token` ist ein Alias für Quartier `quarter_id`."""
    token: str
    quarter_id: int
    distinct_users: int      # verschiedene Pseudonyme (= Stimmen)
    support: int             # Gesamt-Beobachtungen (nur informativ)
    exclusivity: float       # Anteil der Stimmen auf das dominante Quartier (0..1)
    span_days: int           # Zeitspanne der stützenden Signale (Stabilität)


@dataclass(frozen=True)
class RankingCandidate:
    """Vorschlag: für Jahreszeit `season` soll `month` vorne stehen (statt bisher)."""
    season: str
    month: int
    distinct_users: int
    old_order: tuple
    new_order: tuple


def mine_alias_candidates(events, *, quorum: int = 3, min_exclusivity: float = 0.8,
                          min_span_days: int = 3) -> list[AliasCandidate]:
    """`events`: Iterable von Dicts `{pseudo, token, quarter, day}` (day = Ordinalzahl).
    Nur Signale, bei denen der Parser KEIN Quartier erkannte, aber die Person eines
    wählte. Ein `token` wird zum Alias-Kandidaten für sein **dominantes** Quartier, wenn
    (1) ≥ `quorum` **verschiedene Pseudonyme** es stützen (jedes einmal gezählt),
    (2) die Exklusivität ≥ `min_exclusivity` ist (kaum Streuung auf andere Quartiere),
    (3) die Signale über ≥ `min_span_days` Tage verteilt sind (kein Ausbruch)."""
    # token -> quarter -> {users:set, days:[]}
    by_tok: dict = defaultdict(lambda: defaultdict(
        lambda: {"users": set(), "days": []}))
    for e in events:
        tok, q = e["token"], e["quarter"]
        if not tok or q is None:
            continue
        cell = by_tok[tok][q]
        cell["users"].add(e["pseudo"])
        cell["days"].append(int(e["day"]))

    out: list[AliasCandidate] = []
    for token, quarters in by_tok.items():
        all_users: set = set()
        for cell in quarters.values():
            all_users |= cell["users"]
        dom_q, dom = max(quarters.items(), key=lambda kv: len(kv[1]["users"]))
        du = len(dom["users"])
        exclusivity = du / len(all_users) if all_users else 0.0
        span = (max(dom["days"]) - min(dom["days"])) if dom["days"] else 0
        if du >= quorum and exclusivity >= min_exclusivity and span >= min_span_days:
            out.append(AliasCandidate(
                token=token, quarter_id=dom_q, distinct_users=du,
                support=len(dom["days"]), exclusivity=round(exclusivity, 3),
                span_days=span))
    out.sort(key=lambda c: (-c.distinct_users, c.token))
    return out


def mine_ranking_candidates(events, current_orders, *, quorum: int = 3,
                            min_exclusivity: float = 0.6) -> list[RankingCandidate]:
    """`events`: Dicts `{pseudo, season, month}` (Person tippte eine Jahreszeit und wählte
    danach `month`). `current_orders`: `{season: [monat,…]}` (heutige Reihung). Gewinnt
    ein Monat mit ≥ `quorum` **verschiedenen Pseudonymen** und ausreichender Exklusivität,
    steht aber nicht vorne, wird ein Reorder vorgeschlagen (nur Permutation der Liste)."""
    by_season: dict = defaultdict(lambda: defaultdict(set))
    for e in events:
        s, m = e.get("season"), e.get("month")
        if s and m:
            by_season[s][m].add(e["pseudo"])

    out: list[RankingCandidate] = []
    for season, months in by_season.items():
        order = list(current_orders.get(season, []))
        if not order:
            continue
        total_users = len(set().union(*months.values())) if months else 0
        win_m, users = max(months.items(), key=lambda kv: len(kv[1]))
        du = len(users)
        exclusivity = du / total_users if total_users else 0.0
        if (du >= quorum and exclusivity >= min_exclusivity
                and win_m in order and order[0] != win_m):
            new_order = tuple([win_m] + [m for m in order if m != win_m])
            out.append(RankingCandidate(
                season=season, month=win_m, distinct_users=du,
                old_order=tuple(order), new_order=new_order))
    out.sort(key=lambda c: (-c.distinct_users, c.season))
    return out
