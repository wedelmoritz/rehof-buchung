"""
Losverfahren für die Quartier-Buchung der Genossenschaft.

Dieses Modul ist bewusst FREI von Django-Abhängigkeiten: Es arbeitet nur mit
einfachen Datenklassen. Dadurch ist es isoliert testbar, gut zu reviewen und
das Ergebnis ist reproduzierbar.

Verfahren: Gewichtete Zufallsreihenfolge im Runden-Prinzip (Round-Robin),
fachlich eine "weighted random serial dictatorship" mit Ausweich-Logik über
Äquivalenzklassen und einem Ausgleichsfaktor ("Karma") über die Jahre.

Kerneigenschaften (siehe Spezifikation, Abschnitt 3.2):
  * Strategiesicher: Die ehrliche Angabe der wahren Wünsche ist immer
    mindestens so gut wie jeder Trick. Die Wunschliste bestimmt nur, WAS man
    nimmt, wenn man dran ist – nicht, WANN man dran ist.
  * Keine Verschwendung: Es bleibt kein Quartier frei, das jemand gewollt
    hätte, während eine andere Partei leer ausgeht.
  * Nachvollziehbar: Die Ziehung wird Schritt für Schritt protokolliert und
    ist über den Seed reproduzierbar.

Wichtige Korrektheits-Beobachtung: Innerhalb EINES Losdurchlaufs wird Belegung
nur hinzugefügt, nie freigegeben. Die Verfügbarkeit nimmt also monoton ab.
Daraus folgt: Kann ein Wunsch im Moment seiner Betrachtung nicht erfüllt
werden, kann er es auch später in diesem Durchlauf nie. Deshalb dürfen
Verluste und Budget-Übersprünge sofort (eager) entschieden werden – das ist
beweisbar optimal.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta


# --------------------------------------------------------------------------- #
# Verifizierbarkeit: Commit-Reveal des Zufalls-Seeds (provably fair)
# --------------------------------------------------------------------------- #

def seed_commitment(seed: int) -> str:
    """Öffentliche Prüfsumme (SHA-256) eines Los-Seeds.

    Vor der Ziehung wird dieser Hash veröffentlicht ("Commit"), der Seed selbst
    aber geheim gehalten. Nach der Ziehung wird der Seed offengelegt ("Reveal");
    jede:r kann dann `seed_commitment(seed)` neu bilden und mit dem zuvor
    veröffentlichten Wert vergleichen. Stimmen sie überein, stand der Seed schon
    VOR der Ziehung fest – die Verwaltung konnte ihn also nicht nachträglich zu
    Gunsten einzelner wählen. Reine Funktion (Django-frei, isoliert testbar)."""
    return hashlib.sha256(str(int(seed)).encode("ascii")).hexdigest()


def verify_commitment(seed: int, commitment: str) -> bool:
    """True, wenn `commitment` die veröffentlichte Prüfsumme zu `seed` ist."""
    return bool(commitment) and seed_commitment(seed) == commitment.strip().lower()


# --------------------------------------------------------------------------- #
# Eingabe-Datenklassen
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Quarter:
    """Ein Quartier. `eq_class` ist die Äquivalenzklasse (gleichwertige
    Quartiere teilen denselben Wert und dürfen gegeneinander getauscht werden)."""
    id: str
    name: str
    eq_class: str


@dataclass
class Party:
    """Eine buchende Partei (ein Mitglied oder eine Clique).
    `factor` ist der Ausgleichsfaktor (Start 1.0, höher = bessere Chance auf
    einen vorderen Platz). `wish_night_budget` ist die Obergrenze an Nächten,
    die über die Jahres-Wunschliste vergeben werden (beschlossen: 25)."""
    id: str
    name: str
    factor: float = 1.0
    wish_night_budget: int = 25


@dataclass(frozen=True)
class Wish:
    """Ein Buchungswunsch: konkret gewünschtes Quartier + Zeitraum.
    `priority` 1 = höchste Priorität. `end` ist der Abreisetag (exklusiv),
    d.h. die belegten Nächte sind start .. end-1."""
    party_id: str
    priority: int
    quarter_id: str
    start: date
    end: date

    @property
    def nights(self) -> int:
        return (self.end - self.start).days


# --------------------------------------------------------------------------- #
# Ergebnis-Datenklassen
# --------------------------------------------------------------------------- #

@dataclass
class Allocation:
    """Eine zugeteilte Buchung."""
    party_id: str
    quarter_id: str            # tatsächlich zugeteiltes Quartier
    start: date
    end: date
    via_substitution: bool     # True = Ausweichquartier (gleichwertig) statt Wunsch
    contested: bool            # True = um diesen Slot wurde wirklich konkurriert
    original_quarter_id: str   # ursprünglich gewünschtes Quartier

    @property
    def nights(self) -> int:
        return (self.end - self.start).days


@dataclass
class LotteryResult:
    order: list[str]                       # Parteien-IDs in Ziehungsreihenfolge
    allocations: list[Allocation]          # alle Zuteilungen
    losses: list[Wish]                     # echte Verluste (keine Gleichwertige frei)
    new_factors: dict[str, float]          # party_id -> neuer Ausgleichsfaktor
    log: list[dict] = field(default_factory=list)  # strukturiertes Protokoll


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

def _overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Überlappen sich zwei Nacht-Intervalle [start, end)?"""
    return a_start < b_end and b_start < a_end


def _range_free(occ: dict[str, set[date]], qid: str, start: date, end: date) -> bool:
    d = start
    while d < end:
        if d in occ[qid]:
            return False
        d += timedelta(days=1)
    return True


def _occupy(occ: dict[str, set[date]], qid: str, start: date, end: date) -> None:
    d = start
    while d < end:
        occ[qid].add(d)
        d += timedelta(days=1)


def weighted_random_order(
    parties: list[Party], seed: int, tiebreak: str = "id"
) -> list[str]:
    """Erzeugt eine gewichtete Zufallsreihenfolge der Parteien.

    Verfahren nach Efraimidis-Spirakis: Jede Partei erhält den Schlüssel
    key = u ** (1/factor) mit u gleichverteilt in (0,1). Höherer Faktor ->
    Schlüssel näher an 1 -> tendenziell weiter vorne. Über `seed` reproduzierbar.
    """
    rng = random.Random(seed)
    keyed = []
    for p in parties:
        u = rng.random()
        # max(., 1e-9) schützt vor Division durch 0 bei (theoretisch) factor 0
        key = u ** (1.0 / max(p.factor, 1e-9))
        keyed.append((key, p.id))
    # Absteigend nach Schlüssel; Gleichstand deterministisch nach ID
    keyed.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [pid for _, pid in keyed]


# --------------------------------------------------------------------------- #
# Hauptverfahren
# --------------------------------------------------------------------------- #

def run_lottery(
    parties: list[Party],
    quarters: list[Quarter],
    wishes: list[Wish],
    *,
    seed: int,
    factor_step: float = 0.1,
    factor_cap: float = 1.5,
    reset_on_contested_win: bool = True,
    order: list[str] | None = None,
    rule_check: Callable[[str, date, date, list[tuple[date, date]]], str | None]
    | None = None,
) -> LotteryResult:
    """Führt eine Jahres-Losung durch.

    Parameter:
      seed                    Zufalls-Startwert (Reproduzierbarkeit/Audit).
      factor_step             Bonus auf den Faktor pro Jahr mit echtem Verlust.
      factor_cap              Obergrenze des Faktors.
      reset_on_contested_win  Faktor bei Gewinn eines umkämpften Slots auf 1.0.
      order                   Optionale feste Reihenfolge (für Tests/Audit);
                              wenn None, wird gewichtet ausgelost.
      rule_check              Optionaler Callback der Saison-Regeln über mehrere
                              Buchungen (Parallel-Limit/Aufenthaltsdeckel). Aufruf
                              `rule_check(party_id, start, end, bisherige_stays)`;
                              gibt es einen Grund (str) zurück, wird der Wunsch
                              TERMINAL übersprungen (kein echter Verlust, kein
                              Karma – wie ein Budget-Übersprung; das wahrt die
                              Strategiesicherheit). None = erlaubt.

    Karma-Regel (Spezifikation 3.3), Auflösung bei gemischtem Ausgang:
      - Hatte die Partei IRGENDWO einen echten Verlust  -> Faktor + step (gedeckelt)
      - sonst, wenn sie einen UMKÄMPFTEN Slot gewann     -> Faktor zurück auf 1.0
      - sonst                                            -> Faktor unverändert
    "Echter Verlust" = gewünschter Zeitraum, in der ganzen Äquivalenzklasse
    nichts frei. Budget-bedingtes Aussetzen (eigenes Kontingent voll) zählt
    NICHT als Verlust – man hat seinen Anteil ja bekommen.
    """
    party_by_id = {p.id: p for p in parties}
    quarter_by_id = {q.id: q for q in quarters}
    class_of = {q.id: q.eq_class for q in quarters}

    class_members: dict[str, list[str]] = {}
    for q in quarters:
        class_members.setdefault(q.eq_class, []).append(q.id)

    wishes_by_class: dict[str, list[Wish]] = {}
    for w in wishes:
        cls = class_of[w.quarter_id]
        wishes_by_class.setdefault(cls, []).append(w)

    def is_contested(w: Wish, pid: str) -> bool:
        """Gab es echte Konkurrenz um diese Klasse in diesem Zeitraum?"""
        cls = class_of[w.quarter_id]
        for ow in wishes_by_class.get(cls, ()):
            if ow.party_id != pid and _overlap(w.start, w.end, ow.start, ow.end):
                return True
        return False

    # Reihenfolge bestimmen
    if order is None:
        order = weighted_random_order(parties, seed)
    else:
        order = list(order)

    # Wunschlisten je Partei nach Priorität sortieren (stabil über Startdatum)
    wishes_by_party: dict[str, list[Wish]] = {p.id: [] for p in parties}
    for w in wishes:
        wishes_by_party[w.party_id].append(w)
    for pid in wishes_by_party:
        wishes_by_party[pid].sort(key=lambda w: (w.priority, w.start, w.quarter_id))

    occ: dict[str, set[date]] = {q.id: set() for q in quarters}
    pointer: dict[str, int] = {p.id: 0 for p in parties}
    nights_used: dict[str, int] = {p.id: 0 for p in parties}
    had_genuine_loss: dict[str, bool] = {p.id: False for p in parties}
    won_contested: dict[str, bool] = {p.id: False for p in parties}
    # Bereits in DIESEM Lauf zugeteilte Zeiträume je Partei – Grundlage für die
    # Saison-Regeln über mehrere Buchungen (Parallel-Limit/Aufenthaltsdeckel).
    party_stays: dict[str, list[tuple[date, date]]] = {p.id: [] for p in parties}

    allocations: list[Allocation] = []
    losses: list[Wish] = []
    log: list[dict] = []

    log.append({"event": "order", "order": list(order), "seed": seed})

    round_no = 0
    # Es wird so lange in Runden iteriert, bis alle Wunschlisten abgearbeitet
    # sind. Pro Runde bekommt jede Partei HÖCHSTENS EINE erfolgreiche Buchung;
    # Verluste/Budget-Übersprünge werden sofort (terminal) verbucht.
    while any(pointer[pid] < len(wishes_by_party[pid]) for pid in order):
        round_no += 1
        for pid in order:
            wl = wishes_by_party[pid]
            party = party_by_id[pid]
            # Eine "Runde" für diese Partei: durch Verluste/Übersprünge laufen,
            # bis genau eine Buchung gelingt oder die Liste erschöpft ist.
            while pointer[pid] < len(wl):
                w = wl[pointer[pid]]
                n = w.nights

                # (1) Eigenes Budget erschöpft? -> terminal überspringen, KEIN Verlust
                if nights_used[pid] + n > party.wish_night_budget:
                    log.append({
                        "event": "budget_skip", "round": round_no, "party": pid,
                        "wish_quarter": w.quarter_id, "priority": w.priority,
                        "nights": n, "nights_used": nights_used[pid],
                        "budget": party.wish_night_budget,
                    })
                    pointer[pid] += 1
                    continue

                # (1b) Saison-Regeln über mehrere Buchungen (Parallel-Limit/
                # Aufenthaltsdeckel)? Wäre der Deckel mit den schon zugeteilten
                # Zeiträumen überschritten -> terminal überspringen, KEIN Verlust
                # (die Partei hat ihren Saison-Anteil bereits; wahrt die
                # Strategiesicherheit – Über-Wünschen bringt kein Karma).
                if rule_check is not None:
                    blocked = rule_check(pid, w.start, w.end, party_stays[pid])
                    if blocked:
                        log.append({
                            "event": "rule_skip", "round": round_no, "party": pid,
                            "wish_quarter": w.quarter_id, "priority": w.priority,
                            "reason": blocked,
                            "start": w.start.isoformat(), "end": w.end.isoformat(),
                        })
                        pointer[pid] += 1
                        continue

                # (2) Konkretes Wunschquartier frei?
                target: str | None = None
                via_sub = False
                if _range_free(occ, w.quarter_id, w.start, w.end):
                    target = w.quarter_id
                else:
                    # (3) Ausweichen: gleichwertiges Quartier in derselben Klasse
                    cls = class_of[w.quarter_id]
                    for qid in class_members[cls]:
                        if qid == w.quarter_id:
                            continue
                        if _range_free(occ, qid, w.start, w.end):
                            target = qid
                            via_sub = True
                            break

                # (4) Nichts frei in der ganzen Klasse -> echter Verlust (terminal)
                if target is None:
                    losses.append(w)
                    had_genuine_loss[pid] = True
                    log.append({
                        "event": "loss", "round": round_no, "party": pid,
                        "wish_quarter": w.quarter_id, "priority": w.priority,
                        "start": w.start.isoformat(), "end": w.end.isoformat(),
                        "eq_class": class_of[w.quarter_id],
                    })
                    pointer[pid] += 1
                    continue

                # (5) Zuteilen
                _occupy(occ, target, w.start, w.end)
                nights_used[pid] += n
                party_stays[pid].append((w.start, w.end))
                contested = is_contested(w, pid)
                if contested:
                    won_contested[pid] = True
                allocations.append(Allocation(
                    party_id=pid, quarter_id=target, start=w.start, end=w.end,
                    via_substitution=via_sub, contested=contested,
                    original_quarter_id=w.quarter_id,
                ))
                log.append({
                    "event": "assign", "round": round_no, "party": pid,
                    "quarter": target, "wish_quarter": w.quarter_id,
                    "via_substitution": via_sub, "contested": contested,
                    "priority": w.priority, "nights": n,
                    "start": w.start.isoformat(), "end": w.end.isoformat(),
                })
                pointer[pid] += 1
                break  # genau eine Buchung pro Runde und Partei

    # Karma-Aktualisierung
    new_factors: dict[str, float] = {}
    for p in parties:
        if had_genuine_loss[p.id]:
            new_factors[p.id] = round(min(p.factor + factor_step, factor_cap), 6)
        elif reset_on_contested_win and won_contested[p.id]:
            new_factors[p.id] = 1.0
        else:
            new_factors[p.id] = round(p.factor, 6)

    log.append({"event": "factors", "new_factors": dict(new_factors)})

    return LotteryResult(
        order=list(order),
        allocations=allocations,
        losses=losses,
        new_factors=new_factors,
        log=log,
    )


# --------------------------------------------------------------------------- #
# Lesbares Protokoll (für das Audit / die Ergebnisanzeige)
# --------------------------------------------------------------------------- #

def render_log_text(
    result: LotteryResult,
    party_names: dict[str, str] | None = None,
    quarter_names: dict[str, str] | None = None,
) -> str:
    """Erzeugt ein menschenlesbares Ziehungsprotokoll."""
    pn = party_names or {}
    qn = quarter_names or {}

    def P(pid: str) -> str:
        return pn.get(pid, pid)

    def Q(qid: str) -> str:
        return qn.get(qid, qid)

    lines: list[str] = []
    lines.append("=== ZIEHUNGSPROTOKOLL ===")
    lines.append(f"Reihenfolge: {' > '.join(P(p) for p in result.order)}")
    lines.append("")
    for e in result.log:
        ev = e["event"]
        if ev == "assign":
            sub = " (Ausweichquartier)" if e["via_substitution"] else ""
            con = " [umkämpft]" if e["contested"] else ""
            lines.append(
                f"R{e['round']}: {P(e['party'])} -> {Q(e['quarter'])}"
                f" {e['start']}..{e['end']} (Prio {e['priority']}){sub}{con}"
            )
        elif ev == "loss":
            lines.append(
                f"R{e['round']}: {P(e['party'])} VERLOREN "
                f"{Q(e['wish_quarter'])} {e['start']}..{e['end']} "
                f"(Klasse {e['eq_class']} komplett belegt)"
            )
        elif ev == "budget_skip":
            lines.append(
                f"R{e['round']}: {P(e['party'])} übersprungen "
                f"(Budget {e['nights_used']}/{e['budget']} Nächte erreicht)"
            )
        elif ev == "rule_skip":
            lines.append(
                f"R{e['round']}: {P(e['party'])} übersprungen "
                f"(Saison-Regel: {e['reason']})"
            )
    lines.append("")
    lines.append("=== NEUE AUSGLEICHSFAKTOREN ===")
    for pid, f in result.new_factors.items():
        lines.append(f"  {P(pid)}: {f}")
    return "\n".join(lines)
