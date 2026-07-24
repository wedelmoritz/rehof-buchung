"""Service (nl_shadow): **Shadow-Auswertung** eines Lern-Vorschlags (ADR 0113, NL-L4).

Bevor die Verwaltung einen Vorschlag übernimmt, rechnet dieser Dienst den Effekt
**kontrafaktisch** vor – ganz ohne den aktiven Parser zu verändern:

1. **Golden-Wächter:** würde die vorgeschlagene *Reihung* eine kanonische
   Jahreszeit-Eingabe anders auflösen? (`booking.nl_golden`) – jede solche Änderung
   ist ein Warnsignal fürs Review.
2. **Kontrafaktischer Replay:** die aufgezeichneten (pseudonymen) Signale werden mit
   dem heutigen Lexikon **und** mit „Lexikon + Vorschlag" durch die reine Logik
   gespielt. Ergebnis: wie viele bislang **ungelöste** Eingaben würden nun das
   gemeinte Quartier treffen (`newly_resolved`) und ob sich eine bereits gelöste
   Eingabe **ändern** würde (`changed`, sollte 0 sein – ein Alias greift nur, wenn der
   Parser sonst kein Quartier fände).

Reine Vorschau (kein Schreiben), gedeckelt (`_SAMPLE_CAP`), best-effort.
"""
from __future__ import annotations

from datetime import date

from .. import nl_golden, wish_nl
from ..models import NlInteraction, NlProposal
from .nl import nl_stammdaten
from .nl_lexicon import nl_active_lexicon

__all__ = ["nl_shadow_eval"]

_SAMPLE_CAP = 400                            # Replay-Obergrenze (Effizienz)


def _candidate_lexicon(baseline: dict, proposal: NlProposal) -> dict:
    """Basis-Lexikon + Vorschlag (in-memory, nicht persistiert)."""
    aliases = dict(baseline.get("aliases") or {})
    rankings = dict(baseline.get("rankings") or {})
    p = proposal.payload or {}
    if proposal.kind == NlProposal.ALIAS:
        tok, qid = p.get("token"), p.get("quarter_id")
        if isinstance(tok, str) and isinstance(qid, int):
            aliases[tok] = qid
    elif proposal.kind == NlProposal.RANKING:
        season, order = p.get("season"), p.get("new_order")
        if season and isinstance(order, list):
            rankings[season] = list(order)
    return {"aliases": aliases, "rankings": rankings}


def _golden_regressions(candidate: dict) -> list[str]:
    """Golden-Fälle, die mit dem Kandidaten-Lexikon vom kanonischen Ergebnis
    abweichen (Basis ist per Test immer grün)."""
    return nl_golden.run_golden(candidate)


def nl_shadow_eval(proposal: NlProposal) -> dict:
    """Vorschau des Effekts eines Vorschlags. Reine Auswertung, best-effort:
    bei einem Fehler eine leere, ehrliche Struktur (blockiert nie das Review)."""
    result = {
        "golden_ok": True, "golden_regressions": [],
        "replay_sample": 0, "newly_resolved": 0, "changed": 0,
    }
    try:
        baseline = nl_active_lexicon()
        candidate = _candidate_lexicon(baseline, proposal)

        regressions = _golden_regressions(candidate)
        result["golden_regressions"] = regressions
        result["golden_ok"] = not regressions

        year = date.today().year + 1
        stamm = nl_stammdaten(year)
        today = date.today()

        # Nur Signale mit Ergebnis und ungelösten Tokens sind für den Replay relevant.
        rows = list(NlInteraction.objects.filter(
            outcome_at__isnull=False, chosen_quarter_id__isnull=False)
            .exclude(unresolved=[])
            .only("unresolved", "chosen_quarter_id")[:_SAMPLE_CAP])
        result["replay_sample"] = len(rows)

        for r in rows:
            text = " ".join(t for t in (r.unresolved or []) if isinstance(t, str))
            if not text:
                continue
            base_i = wish_nl.parse_wish_text(text, year=year, today=today,
                                             learned=baseline, **stamm)
            cand_i = wish_nl.parse_wish_text(text, year=year, today=today,
                                             learned=candidate, **stamm)
            if base_i.quarter_key is None and cand_i.quarter_key == r.chosen_quarter_id:
                result["newly_resolved"] += 1
            elif (base_i.quarter_key is not None
                  and cand_i.quarter_key != base_i.quarter_key):
                result["changed"] += 1
    except Exception:  # noqa: BLE001 – Vorschau ist optional; Review läuft ohne weiter
        pass
    return result
