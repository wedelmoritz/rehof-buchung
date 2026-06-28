"""Service-Layer (lottery_ops): Losverfahren: Durchführung, Bestätigung/Rücknahme, Benachrichtigungs-Vorbereitung, Fairness-Simulation.

Teil des aufgeteilten `booking.services`-Pakets (siehe __init__).
"""
from __future__ import annotations

from collections import defaultdict
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from .. import lottery as L
from .. import rules as R
from ..models import (
    Allocation, BookingPeriod, BookingPolicy, LotteryRun, Member,
    Notification, Quarter, Wish,
)
from .notify import absolute_url, email_member
from .slots import _in_season_range, _materialized_seasons

__all__ = [
    'run_period_lottery', '_restore_factors', 'confirm_lottery',
    'rollback_lottery', '_build_lottery_notices', 'run_fairness_simulation',
    'ensure_seed_commit', 'verify_period_lottery',
]


def ensure_seed_commit(period: BookingPeriod) -> BookingPeriod:
    """Legt – falls noch nicht geschehen – den geheimen Los-Seed fest und
    veröffentlicht seine Prüfsumme (Commit-Reveal, ADR 0062). Idempotent.

    Wird aufgerufen, sobald die Wünsche öffnen (vor der Ziehung). So steht der
    Seed fest, bevor die Einträge final sind – die Verwaltung kann ihn später
    nicht zu Gunsten einzelner wählen. Der Seed wird kryptografisch sicher
    erzeugt; veröffentlicht wird nur die Prüfsumme, der Seed selbst erst nach der
    bestätigten Ziehung (über `period.seed`)."""
    import secrets
    if period.seed_commit:
        return period
    if period.seed is None:
        period.seed = secrets.randbits(63)   # CSPRNG, passt in BigInteger
    period.seed_commit = L.seed_commitment(period.seed)
    period.seed_committed_at = timezone.now()
    period.save(update_fields=["seed", "seed_commit", "seed_committed_at"])
    return period

@transaction.atomic
def run_period_lottery(
    period: BookingPeriod,
    *,
    seed: int,
    factor_step: float = 0.1,
    factor_cap: float = 1.5,
    reset_on_contested_win: bool = True,
) -> LotteryRun:
    """Führt die Losung für eine Periode aus, schreibt (vorläufige) Zuteilungen,
    aktualisiert die Ausgleichsfaktoren und legt einen unbestätigten Losdurchlauf
    an. Veröffentlicht wird erst über `confirm_lottery`."""
    # Bestehenden Lauf behandeln, BEVOR die Faktoren gelesen werden: ein
    # bestätigter Lauf ist tabu; ein unbestätigter wird zurückgerollt (Faktoren
    # wiederhergestellt), damit ein erneuter Lauf das Karma nicht aufsummiert.
    existing = period.runs.first()
    if existing and existing.confirmed:
        raise ValueError(
            "Die Losung dieser Periode ist bereits bestätigt und kann nicht "
            "erneut ausgeführt werden – erst zurücknehmen ist nicht möglich.")
    if existing:
        _restore_factors(existing)
        existing.delete()
    Allocation.objects.filter(period=period, source="lottery").delete()

    # Verifizierbarkeit: Der Seed steht über die veröffentlichte Prüfsumme fest
    # (Commit-Reveal, ADR 0062). Ist noch keine Prüfsumme veröffentlicht, wird sie
    # JETZT festgelegt (Fallback – normal passiert das schon beim Öffnen der
    # Wünsche). Ein evtl. übergebener Seed greift nur, solange noch keiner steht;
    # danach ist der committete Seed maßgeblich (sonst passte die Prüfsumme nicht).
    if period.seed is None:
        period.seed = seed
    ensure_seed_commit(period)
    seed = period.seed

    members = list(Member.objects.filter(is_external=False))
    quarters = list(Quarter.objects.filter(active=True))
    # Nur eingereichte Wünsche ("im Lostopf") nehmen an der Losung teil – und nur,
    # wenn das Quartier im GANZEN Wunschzeitraum saisonal buchbar ist (sonst würde
    # die Losung eine Buchung außerhalb der Quartier-Saison erzeugen).
    wishes_qs = [
        w for w in Wish.objects.filter(period=period, submitted=True)
        .select_related("member", "quarter")
        if _in_season_range(w.quarter, w.start, w.end)
    ]

    parties = [
        L.Party(
            id=str(m.id), name=m.display_name,
            factor=m.factor, wish_night_budget=m.wish_night_budget,
        )
        for m in members
    ]
    q_payload = [
        L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
        for q in quarters
    ]
    # rule_group = Mitglieds-Anteil: so wirkt das Parallel-Limit/der Aufenthalts-
    # deckel in der Losung auf den vollen Anteil inkl. Tandem-Partner (ADR 0066).
    # Ohne zugeordneten Anteil fällt die Gruppe auf die Partei zurück.
    w_payload = [
        L.Wish(
            party_id=str(w.member_id), priority=w.priority,
            quarter_id=str(w.quarter_id), start=w.start, end=w.end,
            rule_group=str(w.membership_id) if w.membership_id else str(w.member_id),
        )
        for w in wishes_qs
    ]
    # Rückzuordnung Wunsch -> Anteil, um die Los-Zuteilung dem Anteil zuzuschreiben
    # (Schlüssel: Partei + ursprünglich gewünschtes Quartier + Zeitraum).
    wish_membership = {
        (str(w.member_id), str(w.quarter_id), w.start, w.end): w.membership_id
        for w in wishes_qs
    }

    # Saison-Regeln über mehrere Buchungen (Parallel-Limit/Aufenthaltsdeckel) auch
    # in der Losung erzwingen. Die Saison-Regeln werden EINMAL für die gesamte
    # Wunsch-Spanne materialisiert (keine N+1-Queries); der Callback prüft pro
    # Wunsch die schon im Lauf zugeteilten Zeiträume der Partei. Mindestnächte sind
    # bereits beim Einreichen geprüft (validate_booking prüft sie hier nur erneut –
    # für eingereichte Wünsche unschädlich). Verletzt ein Wunsch den Deckel, wird er
    # in der Losung übersprungen (kein echter Verlust/Karma – wahrt die
    # Strategiesicherheit).
    policy = BookingPolicy.get_solo()
    if wishes_qs:
        span_start = min(w.start for w in wishes_qs)
        span_end = max(w.end for w in wishes_qs)
        _seasons = _materialized_seasons(span_start, span_end)
    else:
        _seasons = []

    def _rule_check(_pid, start, end, existing):
        stays = [R.Stay(start=s, end=e) for (s, e) in existing]
        return R.validate_booking(_seasons, policy.default_min_nights,
                                  start, end, stays)

    result = L.run_lottery(
        parties, q_payload, w_payload,
        seed=seed, factor_step=factor_step, factor_cap=factor_cap,
        reset_on_contested_win=reset_on_contested_win,
        rule_check=_rule_check,
    )

    # Faktor-Stände VOR dem Lauf festhalten (für ein sauberes Rückgängigmachen).
    old_factors = {str(m.id): m.factor for m in members}

    # Vorläufige Zuteilungen (provisional=True): blockieren die Verfügbarkeit,
    # bleiben aber für Mitglieder unsichtbar, bis bestätigt wird.
    for a in result.allocations:
        Allocation.objects.create(
            member_id=int(a.party_id),
            quarter_id=int(a.quarter_id),
            start=a.start, end=a.end,
            source="lottery", period=period,
            membership_id=wish_membership.get(
                (a.party_id, a.original_quarter_id, a.start, a.end)),
            via_substitution=a.via_substitution, contested=a.contested,
            provisional=True,
        )

    # Faktoren aktualisieren
    for m in members:
        new_f = result.new_factors.get(str(m.id))
        if new_f is not None and new_f != m.factor:
            m.factor = new_f
            m.save(update_fields=["factor"])

    # Status zunächst nur „zur Prüfung“ – Veröffentlichung erst per Bestätigung.
    period.status = BookingPeriod.LOTTERY_REVIEW
    period.seed = seed
    period.save(update_fields=["status", "seed"])

    party_names = {str(m.id): m.display_name for m in members}
    quarter_names = {str(q.id): q.name for q in quarters}

    # Benachrichtigungen NUR vorbereiten (nicht zustellen) – das übernimmt erst
    # confirm_lottery. So bekommen Mitglieder vor der Bestätigung nichts zu sehen.
    notices = _build_lottery_notices(
        period, members, result, old_factors, quarter_names)

    log_text = L.render_log_text(result, party_names, quarter_names)
    summary = (
        f"{len(result.allocations)} Zuteilungen, "
        f"{len(result.losses)} Verluste, Seed {seed}"
    )
    return LotteryRun.objects.create(
        period=period, seed=seed, log_text=log_text, summary=summary,
        karma_snapshot=old_factors, notices=notices, confirmed=False,
        n_allocations=len(result.allocations), n_losses=len(result.losses),
    )


def _restore_factors(run) -> None:
    """Setzt die Ausgleichsfaktoren auf den vor dem Lauf gemerkten Stand zurück."""
    for mid, factor in (run.karma_snapshot or {}).items():
        Member.objects.filter(id=int(mid)).update(factor=factor)


def confirm_lottery(run) -> None:
    """Bestätigt einen Losdurchlauf: macht die Zuteilungen sichtbar und stellt
    die vorbereiteten Benachrichtigungen (In-App + E-Mail) zu. Danach ist der
    Lauf nicht mehr rücknehmbar. Idempotent."""
    if run.confirmed:
        return
    period = run.period
    Allocation.objects.filter(
        period=period, source="lottery").update(provisional=False)

    url = reverse("period_result", args=[period.id])
    Notification.objects.filter(url=url).delete()  # Idempotenz
    year = period.target_year
    for n in (run.notices or []):
        member = Member.objects.filter(id=n["member_id"]).first()
        if not member:
            continue
        Notification.objects.create(
            member=member, message=n["message"], detail=n["detail"], url=url)
        body = (f"Hallo {member.display_name},\n\n{n['message']}\n\n{n['detail']}"
                f"\n\nDetails: {absolute_url(url)}\n\nViele Grüße\nRe:Hof")
        email_member(member, f"Auslosung {year}: dein Ergebnis", body)

    run.confirmed = True
    run.confirmed_at = timezone.now()
    run.save(update_fields=["confirmed", "confirmed_at"])
    period.status = BookingPeriod.LOTTERY_DONE
    period.save(update_fields=["status"])


def rollback_lottery(run) -> tuple[bool, str | None]:
    """Macht einen UNbestätigten Losdurchlauf rückgängig: löscht die vorläufigen
    Zuteilungen, stellt das Karma wieder her, setzt die Periode zurück auf
    „zur Auslosung freigegeben“ und entfernt den Lauf. Bestätigte Läufe sind
    gesperrt."""
    if run.confirmed:
        return False, "Diese Losung ist bereits bestätigt und kann nicht mehr zurückgenommen werden."
    period = run.period
    Allocation.objects.filter(
        period=period, source="lottery", provisional=True).delete()
    _restore_factors(run)
    period.status = BookingPeriod.LOTTERY_READY
    period.save(update_fields=["status"])
    run.delete()
    return True, None


def _build_lottery_notices(period, members, result, old_factors, quarter_names):
    """Baut je Teilnehmer (mit eingereichten Wünschen) den Benachrichtigungstext
    mit Gewinnen, Verlusten und Karma-Änderung – als serialisierbare Liste, die
    am Losdurchlauf gespeichert und erst bei der Bestätigung zugestellt wird."""
    wins_by: dict[str, list] = defaultdict(list)
    losses_by: dict[str, list] = defaultdict(list)
    for a in result.allocations:
        wins_by[a.party_id].append(a)
    for w in result.losses:
        losses_by[w.party_id].append(w)
    # Übersprungene Wünsche je Partei (Budget erreicht / Saison-Regel) – zählen
    # NICHT als Verlust, sollen aber erklärt werden (P2.6, ADR 0064).
    budget_skips_by: dict[str, int] = defaultdict(int)
    rule_skips_by: dict[str, int] = defaultdict(int)
    for e in (result.log or []):
        if e.get("event") == "budget_skip":
            budget_skips_by[e["party"]] += 1
        elif e.get("event") == "rule_skip":
            rule_skips_by[e["party"]] += 1

    participant_ids = {
        str(mid) for mid in Wish.objects.filter(period=period, submitted=True)
        .values_list("member_id", flat=True).distinct()
    }
    year = period.target_year
    notices: list[dict] = []

    for m in members:
        pid = str(m.id)
        if pid not in participant_ids:
            continue
        wins = wins_by.get(pid, [])
        losses = losses_by.get(pid, [])
        old_f = old_factors.get(pid, m.factor)
        new_f = result.new_factors.get(pid, old_f)

        msg = (f"Auslosung {year}: {len(wins)} Wunsch/Wünsche bekommen, "
               f"{len(losses)} leider nicht.")
        lines: list[str] = []
        if wins:
            lines.append("Du hast bekommen:")
            for a in wins:
                qn = quarter_names.get(a.quarter_id, a.quarter_id)
                why = []
                if a.via_substitution:
                    orig = quarter_names.get(a.original_quarter_id, a.original_quarter_id)
                    why.append(f"gleichwertiges Ausweichquartier – dein Wunsch „{orig}“ "
                               f"war im Zeitraum schon belegt")
                if a.contested:
                    why.append("um diesen Zeitraum gab es Konkurrenz – das Los hat für "
                               "dich entschieden")
                suffix = f" ({'; '.join(why)})" if why else ""
                lines.append(f"  ✓ {qn} {a.start:%d.%m.%Y}–{a.end:%d.%m.%Y}{suffix}")
        if losses:
            lines.append("Es tut uns leid – diese Wünsche waren nicht erfüllbar:")
            for w in losses:
                qn = quarter_names.get(w.quarter_id, w.quarter_id)
                lines.append(f"  ✗ {qn} {w.start:%d.%m.%Y}–{w.end:%d.%m.%Y} – im gewünschten "
                             f"Zeitraum war die ganze gleichwertige Quartiersgruppe belegt")
        skipped = budget_skips_by.get(pid, 0) + rule_skips_by.get(pid, 0)
        if skipped:
            reasons = []
            if budget_skips_by.get(pid):
                reasons.append("Wunsch-Tagebudget erreicht")
            if rule_skips_by.get(pid):
                reasons.append("Saison-Regel (z. B. Höchstaufenthalt)")
            lines.append(f"Hinweis: {skipped} weitere Wunsch/Wünsche wurden übersprungen "
                         f"({', '.join(reasons)}) – das zählt NICHT als Verlust und bringt "
                         f"daher kein Karma.")
        if new_f > old_f:
            lines.append(
                f"Als Ausgleich steigt dein Ausgleichsfaktor um "
                f"+{round(new_f - old_f, 1)} auf {round(new_f, 1)} – damit hast du "
                f"bei der nächsten Auslosung bessere Chancen auf einen vorderen Platz.")
        elif new_f < old_f:
            lines.append(
                f"Dein Ausgleichsfaktor wurde nach dem Gewinn eines umkämpften "
                f"Wunsches auf {round(new_f, 1)} zurückgesetzt.")
        notices.append({
            "member_id": m.id, "message": msg, "detail": "\n".join(lines),
        })
    return notices


def verify_period_lottery(period: BookingPeriod) -> dict:
    """Prüft die Verifizierbarkeit einer (gelaufenen) Losung (ADR 0062):

      1. Stimmt die veröffentlichte Prüfsumme zum offengelegten Seed? (Commit-Reveal)
      2. Reproduziert ein erneuter Lauf mit demselben Seed und denselben Eingaben
         GENAU die gespeicherten Zuteilungen?

    Read-only. Faktoren werden aus dem Karma-Schnappschuss VOR dem Lauf genommen,
    die Wünsche aus dem (nach Wunschschluss unveränderlichen) Lostopf. Liefert ein
    Report-Dict; nutzbar im Kommando `verify_lottery` und der Verwaltungs-Vorschau."""
    run = period.runs.first()
    if run is None or period.seed is None:
        return {"ok": False, "reason": "Keine gelaufene Losung/kein Seed."}

    commit_ok = (not period.seed_commit) or L.verify_commitment(
        period.seed, period.seed_commit)
    # Rechtzeitig = die Prüfsumme stand spätestens beim Wunschschluss fest (also vor
    # der Ziehung). Ein erst zur Ziehung erzeugter Commit ist schwächer (ADR 0062, S2).
    commit_timely = bool(
        period.seed_committed_at and (
            period.wishlist_close is None
            or period.seed_committed_at.date() <= period.wishlist_close))

    members = list(Member.objects.filter(is_external=False))
    quarters = list(Quarter.objects.filter(active=True))
    wishes_qs = [
        w for w in Wish.objects.filter(period=period, submitted=True)
        .select_related("member", "quarter")
        if _in_season_range(w.quarter, w.start, w.end)
    ]
    snap = run.karma_snapshot or {}
    parties = [
        L.Party(id=str(m.id), name=m.display_name,
                factor=float(snap.get(str(m.id), m.factor)),
                wish_night_budget=m.wish_night_budget)
        for m in members
    ]
    q_payload = [L.Quarter(id=str(q.id), name=q.name, eq_class=str(q.eq_class_id))
                 for q in quarters]
    w_payload = [L.Wish(party_id=str(w.member_id), priority=w.priority,
                        quarter_id=str(w.quarter_id), start=w.start, end=w.end,
                        rule_group=str(w.membership_id) if w.membership_id
                        else str(w.member_id))
                 for w in wishes_qs]

    policy = BookingPolicy.get_solo()
    if wishes_qs:
        _seasons = _materialized_seasons(min(w.start for w in wishes_qs),
                                         max(w.end for w in wishes_qs))
    else:
        _seasons = []

    def _rule_check(_pid, start, end, existing):
        stays = [R.Stay(start=s, end=e) for (s, e) in existing]
        return R.validate_booking(_seasons, policy.default_min_nights,
                                  start, end, stays)

    result = L.run_lottery(parties, q_payload, w_payload, seed=period.seed,
                           rule_check=_rule_check)
    replay = {(int(a.party_id), int(a.quarter_id), a.start, a.end)
              for a in result.allocations}
    stored = {(a.member_id, a.quarter_id, a.start, a.end)
              for a in Allocation.objects.filter(period=period, source="lottery")}
    replay_ok = (replay == stored)
    return {
        "ok": bool(commit_ok and replay_ok),
        "commit_ok": commit_ok,
        "commit_timely": commit_timely,
        "replay_ok": replay_ok,
        "seed": period.seed,
        "seed_commit": period.seed_commit,
        "n_stored": len(stored),
        "n_replay": len(replay),
    }


def run_fairness_simulation(cfg=None) -> dict:
    """Führt die Monte-Carlo-Fairness-Simulation aus und speichert das Ergebnis
    am Singleton. Liefert das Ergebnis-Dict (equal-chance + Karma-Effekt)."""
    from ..models import FairnessSimConfig
    from .. import fairness as F
    cfg = cfg or FairnessSimConfig.get_solo()
    result = {
        "equal": F.simulate_equal_chance(cfg.n_users, cfg.n_items, cfg.n_runs),
        "karma": F.simulate_karma_effect(cfg.n_users, cfg.n_items, cfg.n_runs),
    }
    cfg.last_result = result
    cfg.last_run_at = timezone.now()
    cfg.save(update_fields=["last_result", "last_run_at"])
    return result
