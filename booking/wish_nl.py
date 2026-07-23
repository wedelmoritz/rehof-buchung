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
    # Grober Zeitwunsch OHNE konkretes Startdatum: ein oder mehrere KANDIDAT-Monate
    # (nach Präferenz sortiert – „im Juli"→[7], „Sommerwoche"→[7,8,6]) und/oder eine
    # Dauer („eine Woche"). Der Service-Layer löst daraus je Kandidat das erste
    # passende/freie Datum auf (braucht Verfügbarkeit → nicht in der reinen Logik,
    # ADR 0108-Nachtrag). `day_bias` verschiebt den Suchstart im Monat.
    months: list[int] = field(default_factory=list)   # Kandidat-Monate 1–12, geordnet
    day_bias: str | None = None              # "start" | "mid" | "end" (Anfang/Mitte/Ende)
    nights: int | None = None                # erkannte Dauer in Nächten (falls vorhanden)
    # Vom Service befüllt: bis zu N konkrete Vorschläge {start, end, label} (der erste
    # ist zugleich start/end); die weiteren sind die „Meintest du…?"-Alternativen.
    suggestions: list = field(default_factory=list)
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
    def month(self) -> int | None:
        """Bevorzugter (erster) Kandidat-Monat, für einfache Prüfungen/Abwärtskompat."""
        return self.months[0] if self.months else None

    @property
    def is_empty(self) -> bool:
        """Nichts Verwertbares erkannt (Formular bleibt wie es ist)."""
        return not any((self.start, self.months, self.quarter_key, self.eq_class_key,
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
    # Synonyme: „verlängertes/langes Wochenende" (3), „ein paar/einige Tage" (3).
    if re.search(r"\b(?:verlaengertes|verlangertes|langes)\s+wochenende\b", norm):
        return 3
    if re.search(r"\b(?:ein\s+)?paar\s+tage\b", norm) or "einige tage" in norm:
        return 3
    if "woche" in norm:
        return 7
    if "wochenende" in norm:
        return 2                                  # Fr→So = 2 Nächte
    return None


_MONTH_NAMES = ("", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                "August", "September", "Oktober", "November", "Dezember")


# Jahreszeit → Kandidat-Monate, nach typischer Ferien-/Urlaubs-Präferenz geordnet.
# Bewusst konservativ; die Mehrdeutigkeit klärt der Nutzer über „Meintest du…?"-Chips.
# Beide Schreibweisen (ü→„u" nach _norm ODER vom Nutzer als „ue" getippt), wie überall
# im Parser (vgl. „naechte"/„nachte").
_SEASONS: dict[str, list[int]] = {
    "fruhling": [5, 4, 6], "fruehling": [5, 4, 6],
    "fruhjahr": [5, 4, 6], "fruehjahr": [5, 4, 6], "lenz": [5, 4],
    "sommer": [7, 8, 6], "hochsommer": [8, 7],
    "spatsommer": [8, 9], "spaetsommer": [8, 9],
    "herbst": [10, 9, 11], "winter": [1, 2, 12],
}
# Kompositum-Endungen: nur „…woche/…wochen" implizieren 7 Nächte, die übrigen sind
# reine Zeit-Hinweise (Monat/Jahreszeit) ohne feste Dauer.
_COMPOUND_SUFFIXES = ("wochen", "woche", "ferien", "urlaub", "urlaube", "zeit", "tage")


def _month_candidates(token: str) -> tuple[list[int], int | None]:
    """Ein Zeit-Token → (Kandidat-Monate, Nächte-Hinweis). Erkennt puren Monatsnamen,
    pure Jahreszeit UND Komposita („Juliwoche"/„Sommerwoche"/„Herbsturlaub"): der
    Präfix liefert Monat/Jahreszeit, das Suffix ggf. die Dauer (…woche → 7 Nächte)."""
    mon = _MONTHS.get(token)
    if mon:
        return [mon], None
    if token in _SEASONS:
        return list(_SEASONS[token]), None
    for suf in _COMPOUND_SUFFIXES:
        if token.endswith(suf) and len(token) > len(suf):
            prefix = token[: -len(suf)]
            nights = 7 if suf in ("woche", "wochen") else None
            pm = _MONTHS.get(prefix)
            if pm:
                return [pm], nights
            if prefix in _SEASONS:
                return list(_SEASONS[prefix]), nights
            break
    return [], None


def _extract_time_months(toks: list[str]) -> tuple[list[int], int | None]:
    """Grober Zeitraum ohne Tag → geordnete Kandidat-Monate (+ evtl. Nächte-Hinweis).
    Ein explizit genannter Monatsname hat Vorrang vor einer Jahreszeit; sonst die
    erste erkannte Jahreszeit/Kompositum. Nur ganze Tokens (kein Teilstring)."""
    season_hit: tuple[list[int], int | None] | None = None
    for t in toks:
        mon = _MONTHS.get(t)
        if mon:
            return [mon], None                  # expliziter Monat gewinnt
        if season_hit is None:
            cand, nights = _month_candidates(t)
            if cand:
                season_hit = (cand, nights)
    return season_hit if season_hit else ([], None)


def _extract_month(toks: list[str]) -> int | None:
    """Bevorzugter Kandidat-Monat (Abwärtskompatibilität / einfache Prüfungen)."""
    months, _ = _extract_time_months(toks)
    return months[0] if months else None


def _extract_day_bias(norm: str) -> str | None:
    """„Anfang/Mitte/Ende <Monat>" bzw. „erste/letzte Woche" → Suchstart im Monat."""
    if re.search(r"\banfang\b", norm) or re.search(r"\berste\w*\s+woche\b", norm):
        return "start"
    if re.search(r"\bmitte\b", norm):
        return "mid"
    if re.search(r"\bende\b", norm) or re.search(r"\bletzte\w*\s+woche\b", norm):
        return "end"
    return None


def _extract_relative(norm: str, today: date) -> tuple[date | None, int | None]:
    """Relative Zeitangaben AB HEUTE (nur für Buchungen sinnvoll): „nächste Woche",
    „übernächste Woche", „in 2 Wochen", „in 5 Tagen". Gibt (Startdatum, Nächte) oder
    (None, None). „nächste Woche" = kommender Montag, 7 Nächte."""
    def _next_monday(base: date) -> date:
        days = (7 - base.weekday()) % 7 or 7
        return base + timedelta(days=days)

    if re.search(r"\buber(?:na|nae)chste[nrs]?\s+woche\b", norm):
        return _next_monday(today) + timedelta(days=7), 7
    if re.search(r"\b(?:na|nae)chste[nrs]?\s+woche\b", norm):
        return _next_monday(today), 7
    m = re.search(r"\bin\s+(\d{1,2})\s+wochen\b", norm)
    if m:
        return today + timedelta(days=int(m.group(1)) * 7), None
    m = re.search(r"\bin\s+(\d{1,2})\s+tagen\b", norm)
    if m:
        return today + timedelta(days=int(m.group(1))), None
    return None, None


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

    # --- Zeitraum: konkrete Daten → relative Angaben (nur Buchung) → benannte
    #     (konfigurierte) Zeiträume → grober Monat/Jahreszeit (Kandidaten fürs Service) ---
    dates = _extract_dates(norm, year)
    # Relative Angaben („nächste Woche", „in 2 Wochen") nur ohne konkretes Datum und nur
    # für Buchungen (bei Wünschen fürs Folgejahr sinnlos). Sie „verbrauchen" eine
    # „in N Wochen"-Formulierung, damit sie nicht zusätzlich als Dauer zählt.
    rel_start = rel_nights = None
    norm_dur = norm
    if kind == "booking" and today is not None and len(dates) == 0:
        rel_start, rel_nights = _extract_relative(norm, today)
        if rel_start is not None:
            norm_dur = re.sub(r"\bin\s+\d{1,2}\s+(?:wochen|tagen)\b", " ", norm_dur)
            norm_dur = re.sub(r"\b(?:uber)?(?:na|nae)chste[nrs]?\s+woche\b", " ", norm_dur)
    duration = _extract_duration(norm_dur)
    if duration:
        intent.nights = duration
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
    elif rel_start is not None:
        intent.start = rel_start
        n = rel_nights or duration
        if n:
            intent.end = rel_start + timedelta(days=n)
            intent.nights = n
        intent.matched.append(f"ab {rel_start:%d.%m.} vorgeschlagen")
    else:
        # Benannte, KONFIGURIERTE Zeiträume (Ferien/Saison) – Substring-Treffer.
        for name, s, e in list(holidays) + list(seasons):
            if name and _norm(name) in norm and s and e:
                intent.start, intent.end = s, e
                intent.matched.append(f"{name} ({s:%d.%m.}–{e:%d.%m.})")
                break
        if intent.start is None:
            # Grober Zeitwunsch („eine Woche im Juli", „Sommerwoche", „Anfang August"):
            # Kandidat-Monate (+ evtl. Dauer/Monatsteil) festhalten – das Service-Layer
            # schlägt daraus je Kandidat das erste passende/freie Datum vor.
            months, snights = _extract_time_months(toks)
            if months:
                intent.months = months
                if snights and not intent.nights:
                    intent.nights = snights
                intent.day_bias = _extract_day_bias(norm)
                if len(months) == 1:
                    intent.matched.append(f"im {_MONTH_NAMES[months[0]]}")
                else:
                    intent.matched.append(
                        "Zeitraum: " + " / ".join(_MONTH_NAMES[m] for m in months))
            elif duration:
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
