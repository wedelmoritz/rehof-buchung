"""Service (nl_learn): pseudonymisierte Instrumentierung fürs NL-Parser-Lernen
(ADR 0113, Batch NL-L1).

Erfasst – **nur** bei aktivem Opt-in (`OpsConfig.nl_learning_enabled`) **und** gesetztem
`NL_LEARN_SALT` (fail-closed) – welche Kurz-Eingaben der Parser nicht sauber auflöste und
was die Person **danach** wählte (Korrektur-Signal, ADR 0113). Es wird **kein Freitext-Satz
und keine Identität** gespeichert: nur ein **Pseudonym** (HMAC über die Mitglieds-ID),
normalisierte Einzel-Tokens und das Ergebnis-Delta. Alles best-effort und **nie
blockierend** – ein Fehler hier darf nie eine Buchung/Wunsch-Eintragung stören.

Teil des `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .. import wish_nl
from ..models import NlInteraction, OpsConfig

log = logging.getLogger("booking.nl_learn")

__all__ = ["nl_learning_active", "nl_pseudonym", "nl_log_interaction",
           "nl_attach_outcome"]

_MAX_TOKENS = 12                 # je Eingabe höchstens so viele Tokens speichern
_MAX_TOKEN_LEN = 32
_PENDING_KEY = "nl_pending"      # Session-Korrelation Parse → spätere Wahl
_PENDING_MAX_AGE_S = 45 * 60     # 45 min: danach zählt die Wahl nicht mehr zur Eingabe


def nl_learning_active() -> bool:
    """Lernen NUR, wenn das Opt-in gesetzt UND das Salt vorhanden ist (fail-closed).
    Ohne Salt sind keine Pseudonyme bildbar → es wird garantiert nichts gespeichert."""
    if not getattr(settings, "NL_LEARN_SALT", ""):
        return False
    try:
        return bool(OpsConfig.get_solo().nl_learning_enabled)
    except Exception:  # noqa: BLE001 – im Zweifel AUS
        return False


def nl_pseudonym(member_id) -> str:
    """`HMAC-SHA256(member_id, NL_LEARN_SALT)` als Hex – ohne das Geheimnis nicht
    umkehrbar. Zählt „verschiedene Personen", ohne die Identität zu speichern."""
    return hmac.new(settings.NL_LEARN_SALT.encode("utf-8"),
                    str(member_id).encode("utf-8"), hashlib.sha256).hexdigest()


def _clean_tokens(text: str) -> list[str]:
    seen, out = set(), []
    for t in wish_nl.tokens_of(text):
        t = t[:_MAX_TOKEN_LEN]
        if t and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= _MAX_TOKENS:
            break
    return out


def nl_log_interaction(request, member, kind: str, intent, *, raw_text: str) -> None:
    """Beim Parsen aufrufen: legt ein pseudonymes Signal an (normalisierte Tokens der
    Eingabe + was der Parser vorschlug) und merkt sich die Zeile über eine
    Korrelations-ID in der Session, um später das Ergebnis anzuhängen."""
    if not (member and nl_learning_active()):
        return
    try:
        proposed_month = intent.start.month if getattr(intent, "start", None) else None
        with transaction.atomic():
            row = NlInteraction.objects.create(
                pseudonym=nl_pseudonym(member.id),
                kind=kind,
                unresolved=_clean_tokens(raw_text),
                proposed_quarter_id=getattr(intent, "quarter_key", None)
                if isinstance(getattr(intent, "quarter_key", None), int) else None,
                proposed_month=proposed_month,
                suggestion_shown=bool(getattr(intent, "suggestions", None)),
            )
        request.session[_PENDING_KEY] = {
            "id": row.id, "kind": kind,
            "ts": timezone.now().timestamp(),
            "pq": row.proposed_quarter_id, "pm": row.proposed_month,
        }
    except Exception:  # noqa: BLE001 – nie blockierend
        log.debug("nl_log_interaction skipped", exc_info=True)


def nl_attach_outcome(request, member, kind: str, *, quarter_id=None, start=None) -> None:
    """Nach dem tatsächlichen Buchen/Wunsch-Eintragen aufrufen: hängt – wenn es eine
    frische, passende Parse-Korrelation in der Session gibt – das **Ergebnis** an
    (gewähltes Quartier/Startmonat + ob der Vorschlag überstimmt wurde) und räumt die
    Korrelation ab. Best-effort/nie blockierend."""
    if not (member and nl_learning_active()):
        return
    pend = request.session.get(_PENDING_KEY) if hasattr(request, "session") else None
    if not pend or pend.get("kind") != kind:
        return
    try:
        age = timezone.now().timestamp() - float(pend.get("ts") or 0)
        if age < 0 or age > _PENDING_MAX_AGE_S:
            request.session.pop(_PENDING_KEY, None)
            return
        chosen_month = start.month if start else None
        proposed_q, proposed_m = pend.get("pq"), pend.get("pm")
        overridden = None
        if proposed_q is not None or proposed_m is not None:
            overridden = ((proposed_q is not None and proposed_q != quarter_id)
                          or (proposed_m is not None and proposed_m != chosen_month))
        NlInteraction.objects.filter(id=pend["id"], outcome_at__isnull=True).update(
            outcome_at=timezone.now(),
            chosen_quarter_id=quarter_id,
            chosen_month=chosen_month,
            overridden=overridden,
        )
    except Exception:  # noqa: BLE001 – nie blockierend
        log.debug("nl_attach_outcome skipped", exc_info=True)
    finally:
        try:
            request.session.pop(_PENDING_KEY, None)
        except Exception:  # noqa: BLE001
            pass
