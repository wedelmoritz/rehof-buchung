"""Reine Logik: **regelbasierter** Parser für natürlichsprachliche Kurz-Eingaben
(ADR 0103, P2 „Weg A"). Django-frei, ohne DB, ohne KI/externe Aufrufe – deshalb
isoliert in ``tests/`` prüfbar und DSGVO-neutral (nichts verlässt den Server).

**Zweck:** „ruhige Woche im Juli, barrierefrei, mit Hund" → **strukturierte
Constraints**, die das normale Formular **vorausfüllen** (parse-and-confirm:
best-effort, **nie blockierend**, das Mitglied prüft/korrigiert). Der Parser
**entscheidet nie** – er strukturiert nur.

**Stammdaten werden injiziert** (wie in ``beds24.py``): der Parser kennt **keine**
hartcodierten Quartiere/Klassen/Ferientermine. Der Service reicht die *tatsächlich
konfigurierten* Objekte herein:
  * ``quarters`` / ``eq_classes``: ``[(key, name), …]`` (aktive Quartiere bzw.
    Äquivalenzklassen) – unscharfer Namensabgleich über ``beds24.name_score``.
  * ``seasons`` / ``holidays``: ``[(name, start, end), …]`` – **materialisiert** aus
    den konfigurierten ``SeasonRule``/``SchoolHoliday`` fürs Zieljahr.

**Security by design:**
  * Eingabe wird mit ``strip_controls`` gesäubert und **hart längenbegrenzt**
    (``MAX_LEN``) – vor jeder Verarbeitung.
  * Nur **einfache, gebundene** Regex (keine verschachtelten Quantoren → kein ReDoS).
  * **Kein** ``eval``/``exec``, **kein** Template-Rendering von Eingaben (SSTI-frei).
  * Ausgabe ist ausschließlich strukturierte Data (IDs/Daten/Flags/kurze Labels) –
    niemals HTML; die Anzeige escapt ohnehin.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from .beds24 import Candidate, name_score
from .validation import strip_controls

# Harte Obergrenze der Eingabe (Schutz vor teuren Schleifen/Missbrauch).
MAX_LEN = 400

# Monatsnamen (+ gängige Kürzel) → Nummer.
_MONTHS: dict[str, int] = {
    "januar": 1, "jan": 1, "februar": 2, "feb": 2, "maerz": 3, "marz": 3, "mar": 3,
    "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "oktober": 10,
    "okt": 10, "november": 11, "nov": 11, "dezember": 12, "dez": 12,
}

# Zahlwörter 1–12 (für Personen/Dauer).
_NUMWORDS: dict[str, int] = {
    "ein": 1, "eine": 1, "einer": 1, "zwei": 2, "drei": 3, "vier": 4, "fuenf": 5,
    "funf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwoelf": 12, "zwolf": 12,
}

# Schlagwörter → Besonderheit (Buchungs-relevant; für Wünsche nur mitgeführt).
_SPECIAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hund": ("hund", "hunde", "haustier"),
    "beistellbett": ("beistellbett", "zustellbett", "kinderbett", "gitterbett"),
    "kinder": ("kind", "kinder", "kindern", "baby"),
}
_ACCESSIBLE_WORDS = ("barrierefrei", "barrierearm", "rollstuhl", "rollstuhlgerecht",
                     "stufenlos", "rollator")
_FLEX_WORDS = ("flexibel", "egal wann", "irgendwann", "zeitlich flexibel", "spontan")

# „ruhig", „mit Sauna" etc. sind bewusst NICHT modelliert (kein Feld) → landen in
# `unresolved`, damit die Anzeige ehrlich sagen kann, was nicht verstanden wurde.


def _norm(s: str) -> str:
    """Kleinbuchstaben, Akzente entfernt, ß→ss (für robusten Wortabgleich)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("ß", "ss")


@dataclass
class WishIntent:
    """Strukturiertes Ergebnis des Parsers – füllt das Formular vor, entscheidet nie.

    Alle Felder optional/leer, wenn nicht erkannt (best-effort). ``matched`` sind die
    menschlich lesbaren Treffer (für die Bestätigungs-Anzeige), ``unresolved`` die
    nicht zugeordneten Wörter/Hinweise (Ehrlichkeit über die Grenzen)."""
    kind: str = "wish"                       # "wish" | "booking"
    start: date | None = None
    end: date | None = None
    quarter_key: object | None = None
    eq_class_key: object | None = None
    persons: int | None = None
    accessible: bool | None = None
    flexible: bool = False
    cleaning: bool | None = None             # mit/ohne Endreinigung (nur booking sinnvoll)
    special: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Nichts Verwertbares erkannt (Formular bleibt wie es ist)."""
        return not any((self.start, self.quarter_key, self.eq_class_key,
                        self.persons, self.accessible, self.flexible,
                        self.cleaning is not None, self.special))


# --------------------------------------------------------------------------- #
# Datums-Erkennung
# --------------------------------------------------------------------------- #
# Ein Datum: Tag[.Monat][.Jahr] – Monat/Jahr optional. Bewusst simpel, keine
# verschachtelten Quantoren.
# Alle Muster laufen auf dem akzent-bereinigten `norm` (ü→u, ä→a, ß→ss) – daher
# durchgängig in bereinigter Schreibweise notiert (z. B. „naechte"/„nachte").
_DATE_RE = re.compile(r"\b(\d{1,2})\.(?:\s?(\d{1,2})\.?)?(?:\s?(\d{4}))?")
_MONTHNAME_RE = re.compile(r"\b(\d{1,2})\.?\s*([a-z]+)")
_DURATION_NUM_RE = re.compile(r"\b(\d{1,2})\s*(nacht|naechte|nachte|tag|tage)\b")
_DURATION_WEEK_RE = re.compile(r"\b(\d{1,2})\s*wochen?\b")


def _make_date(day: int, month: int, year: int) -> date | None:
    try:
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def _extract_dates(norm: str, year: int) -> list[date]:
    """Findet konkrete Daten in Textreihenfolge. Erkennt „12.7.", „12.7.2027",
    „12. Juli" und „12." (Monat aus einem späteren Monatsnamen/Datum abgeleitet)."""
    found: list[tuple[int, date]] = []           # (Position, Datum) – für Reihenfolge
    used_spans: list[tuple[int, int]] = []

    # 1) Tag + Monatsname („12. Juli", „3 oktober")
    for m in _MONTHNAME_RE.finditer(norm):
        mon = _MONTHS.get(m.group(2))
        if mon:
            d = _make_date(int(m.group(1)), mon, year)
            if d:
                found.append((m.start(), d))
                used_spans.append((m.start(), m.end()))

    # 2) Numerische Daten „12.7.", „12.7.2027", „12." (Monat später ergänzt)
    pending_dayonly: list[tuple[int, int]] = []  # (Position, Tag) ohne Monat
    for m in _DATE_RE.finditer(norm):
        if any(s <= m.start() < e for s, e in used_spans):
            continue
        day = int(m.group(1))
        mon = int(m.group(2)) if m.group(2) else None
        yr = int(m.group(3)) if m.group(3) else year
        if mon:
            d = _make_date(day, mon, yr)
            if d:
                found.append((m.start(), d))
        else:
            pending_dayonly.append((m.start(), day))

    # „12.–19.7." : ein tag-nur-Datum bekommt den Monat des nächsten datierten Treffers.
    if pending_dayonly and found:
        for pos, day in pending_dayonly:
            nxt = min((d for p, d in found if p > pos), default=None) \
                or found[0][1]
            d = _make_date(day, nxt.month, nxt.year)
            if d:
                found.append((pos, d))

    found.sort(key=lambda t: t[0])
    # Duplikate (gleiche Position/Datum) verwerfen, Reihenfolge halten.
    out: list[date] = []
    for _, d in found:
        if d not in out:
            out.append(d)
    return out


def _extract_duration(norm: str) -> int | None:
    """Aufenthaltslänge in Nächten aus „10 tage", „2 wochen", „eine woche",
    „übers wochenende". Gibt None, wenn keine Dauer erkennbar."""
    m = _DURATION_WEEK_RE.search(norm)
    if m:
        return int(m.group(1)) * 7
    m = _DURATION_NUM_RE.search(norm)
    if m:
        return int(m.group(1))
    for word, n in _NUMWORDS.items():
        if re.search(rf"\b{word}\s+wochen?\b", norm):
            return n * 7
        if re.search(rf"\b{word}\s+(?:naechte|nachte|nacht|tage|tag)\b", norm):
            return n
    if "woche" in norm:
        return 7
    if "wochenende" in norm:
        return 2                                  # Fr→So = 2 Nächte
    return None


def _extract_persons(norm: str) -> int | None:
    """Personenzahl aus „für 4 personen", „zu viert", „wir sind 3", „4 erwachsene"."""
    m = re.search(r"\b(\d{1,2})\s*(?:person|personen|leute|gaeste|gaste|"
                  r"erwachsene|pers)\b", norm)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:fuer|fur|zu|sind|wir sind)\s+(\d{1,2})\b", norm)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return n
    for word, n in _NUMWORDS.items():
        if re.search(rf"\b{word}\s+(?:person|personen|leute|erwachsene)\b", norm):
            return n
    return None


def _match_named(text_tokens: list[str], candidates: list[Candidate],
                 *, min_score: float = 0.62) -> object | None:
    """Bester Kandidat (Quartier/Klasse) per **Sliding-Window**-Namensabgleich
    (`beds24.name_score`). Nur ein sicherer Treffer (hohe Schwelle) wird gesetzt –
    ein Fehltreffer wäre schlimmer als kein Treffer (das Mitglied bestätigt ohnehin)."""
    best_key, best = None, min_score
    n = len(text_tokens)
    for c in candidates:
        for cname in c.names:
            k = max(1, len(_norm(cname).split()))
            for size in {k, k + 1}:
                for i in range(0, max(0, n - size) + 1):
                    window = " ".join(text_tokens[i:i + size])
                    sc = name_score(cname, window)
                    if sc > best:
                        best, best_key = sc, c.key
    return best_key


def _tokens(norm: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", norm) if t]


def _parse_core(text: str, *, quarters, eq_classes, seasons, holidays,
                year: int, today: date | None, kind: str) -> WishIntent:
    intent = WishIntent(kind=kind)
    text = strip_controls(text or "", max_len=MAX_LEN)
    norm = _norm(text)
    if not norm.strip():
        return intent
    toks = _tokens(norm)

    # --- Zeitraum: erst konkrete Daten, dann benannte (konfigurierte) Zeiträume ---
    dates = _extract_dates(norm, year)
    duration = _extract_duration(norm)
    if len(dates) >= 2:
        intent.start, intent.end = dates[0], dates[1]
        if intent.end <= intent.start:
            intent.end = None
            intent.unresolved.append("Abreise ≤ Anreise – bitte prüfen")
        intent.matched.append(f"Zeitraum {dates[0]:%d.%m.}–{dates[1]:%d.%m.}")
    elif len(dates) == 1:
        intent.start = dates[0]
        if duration:
            intent.end = dates[0] + timedelta(days=duration)
            intent.matched.append(
                f"ab {dates[0]:%d.%m.} für {duration} Nächte")
        else:
            intent.matched.append(f"ab {dates[0]:%d.%m.} (Abreise offen)")
            intent.unresolved.append("Enddatum fehlt")
    else:
        # Benannte, KONFIGURIERTE Zeiträume (Ferien/Saison) – Substring-Treffer.
        for name, s, e in list(holidays) + list(seasons):
            if name and _norm(name) in norm and s and e:
                intent.start, intent.end = s, e
                intent.matched.append(f"{name} ({s:%d.%m.}–{e:%d.%m.})")
                break
        if intent.start is None and duration:
            intent.unresolved.append(
                f"Dauer {duration} Nächte erkannt, aber kein Startdatum")

    # --- Quartier / Äquivalenzklasse (unscharf gegen konfigurierte Namen) ---
    q_cands = [Candidate(key=k, names=[n]) for k, n in (quarters or []) if n]
    c_cands = [Candidate(key=k, names=[n]) for k, n in (eq_classes or []) if n]
    qkey = _match_named(toks, q_cands)
    if qkey is not None:
        intent.quarter_key = qkey
        qname = next((n for k, n in quarters if k == qkey), "")
        intent.matched.append(f"Unterkunft: {qname}")
    else:
        ckey = _match_named(toks, c_cands)
        if ckey is not None:
            intent.eq_class_key = ckey
            cname = next((n for k, n in eq_classes if k == ckey), "")
            intent.matched.append(f"Art: {cname}")

    # --- Merkmale mit echtem Modell-Feld ---
    if any(w in norm for w in _ACCESSIBLE_WORDS):
        intent.accessible = True
        intent.matched.append("barrierefrei")
    persons = _extract_persons(norm)
    if persons:
        intent.persons = persons
        intent.matched.append(f"{persons} Personen")
    if any(w in norm for w in _FLEX_WORDS):
        intent.flexible = True
        intent.matched.append("zeitlich flexibel")

    # --- Besonderheiten (Buchung): mit/ohne Endreinigung, Hund, Beistellbett … ---
    if "endreinigung" in norm or "putz" in norm:
        intent.cleaning = not bool(re.search(r"\bohne\b[^.]*endreinigung|"
                                             r"endreinigung[^.]*\bnicht\b", norm))
        intent.matched.append("Endreinigung " + ("erwünscht" if intent.cleaning
                                                  else "nicht erwünscht"))
    for label, words in _SPECIAL_KEYWORDS.items():
        if any(re.search(rf"\b{w}\b", norm) for w in words):
            neg = bool(re.search(rf"\bohne\b\s+\w*\s*{words[0]}", norm)
                       or re.search(rf"kein(?:en|e)?\s+{words[0]}", norm))
            if not neg:
                intent.special.append(label)
                intent.matched.append(label)

    return intent


def parse_wish_text(text: str, *, quarters=None, eq_classes=None, seasons=None,
                    holidays=None, year: int, today: date | None = None) -> WishIntent:
    """Parst eine Kurz-Eingabe **für einen Wunsch** (Quartier/Art + Zeitraum stehen im
    Vordergrund; Personen/Besonderheiten werden mitgelesen, wirken aber erst beim
    späteren Buchen). Best-effort, nie blockierend."""
    return _parse_core(text, quarters=quarters or [], eq_classes=eq_classes or [],
                       seasons=seasons or [], holidays=holidays or [],
                       year=year, today=today, kind="wish")


def parse_booking_text(text: str, *, quarters=None, eq_classes=None, seasons=None,
                       holidays=None, year: int, today: date | None = None) -> WishIntent:
    """Parst eine Kurz-Eingabe **für eine Buchung** – zusätzlich relevant:
    Personenzahl, Endreinigung, Besonderheiten (Hund/Beistellbett …)."""
    return _parse_core(text, quarters=quarters or [], eq_classes=eq_classes or [],
                       seasons=seasons or [], holidays=holidays or [],
                       year=year, today=today, kind="booking")
