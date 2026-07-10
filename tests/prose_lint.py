"""Prosa-Linter für Hilfe-/Erklärtexte – **Verständlichkeit & Prägnanz**.

Reine Logik (Django-frei), damit die Prüfung in der schnellen `tests/`-Suite läuft
und damit **bei jedem Commit** (lokal + CI). Der Linter misst objektive Näherungen
für Verständlichkeit – er ersetzt **kein** menschliches Lektorat, sondern hält
messbare Leitplanken:

* **Satzlänge** – lange Sätze sind der größte Verständlichkeits-Killer:
  `max_sentence_words` (härteste Grenze) + `avg_sentence_words` je Text.
* **Lesbarkeit** – **Wiener Sachtextformel** (WSTF1, deutsche Kennzahl, grob eine
  Schulstufe): niedriger = leichter. Grenze `wstf_max`.
* **Prägnanz/Jargon** – kleine Sperrliste (interne/englische Fachbegriffe statt
  Klartext), leicht erweiterbar.

Deutsch-spezifisch behandelt: Abkürzungen mit Punkt (z. B., d. h., u. a., …),
Ordinal-/Zahlpunkte und `$platzhalter` (aus dem Hilfe-Mini-Markup, ADR 0093), damit
die Satztrennung nicht fälschlich zerfällt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Abkürzungen, deren Punkt KEIN Satzende ist (Punkt entfernt → ein Token).
_ABBREV = {
    "z. B.": "zB", "z.B.": "zB", "d. h.": "dh", "d.h.": "dh", "u. a.": "ua",
    "u.a.": "ua", "u. Ä.": "uÄ", "o. Ä.": "oÄ", "o.Ä.": "oÄ", "i. d. R.": "idR",
    "s. o.": "so", "s. u.": "su", "u. v. m.": "uvm", "e. V.": "eV",
    "ggf.": "ggf", "inkl.": "inkl", "exkl.": "exkl", "etc.": "etc", "usw.": "usw",
    "bzw.": "bzw", "vs.": "vs", "ca.": "ca", "max.": "max", "min.": "min",
    "Nr.": "Nr", "Art.": "Art", "Abs.": "Abs", "Mio.": "Mio", "Mrd.": "Mrd",
    "evtl.": "evtl", "sog.": "sog", "vgl.": "vgl", "Tel.": "Tel",
}
_VOWELS = "aeiouyäöü"


def _normalize(text: str) -> str:
    """Mini-Markup/Markdown grob strippen und deutsche Punkt-Fallen entschärfen."""
    # Links [Text](url) -> Text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Auszeichnungen/Überschriften/Listen entfernen
    text = re.sub(r"[#*_`>]", " ", text)
    text = re.sub(r"(?m)^\s*[-•]\s+", " ", text)
    # Platzhalter $name -> neutrales Wort
    text = re.sub(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "Wert", text)
    # Abkürzungen schützen
    for k, v in _ABBREV.items():
        text = text.replace(k, v)
    # Zahl+Punkt (Ordinale/Beträge): Punkt schützen -> kein Satzende
    text = re.sub(r"(\d)\.(?=\s|$)", r"\1․", text)   # ONE DOT LEADER als Platzhalter
    return text


def split_sentences(text: str) -> list[str]:
    text = _normalize(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for p in parts:
        p = p.replace("․", ".").strip()
        if re.search(r"[A-Za-zÄÖÜäöüß]", p):
            out.append(p)
    return out


def words(sentence: str) -> list[str]:
    return re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]*", sentence)


def syllables(word: str) -> int:
    """Heuristik: Anzahl Vokalgruppen (Diphthong = eine Silbe), mindestens 1."""
    return max(1, len(re.findall(rf"[{_VOWELS}]+", word.lower())))


@dataclass
class Metrics:
    n_sentences: int
    n_words: int
    avg_sentence_words: float
    max_sentence_words: int
    wstf: float                       # Wiener Sachtextformel (≈ Schulstufe)


def analyze(text: str) -> Metrics:
    sents = split_sentences(text)
    all_words: list[str] = []
    max_len = 0
    for s in sents:
        w = words(s)
        if not w:
            continue
        all_words.extend(w)
        max_len = max(max_len, len(w))
    n = len(all_words) or 1
    ns = len(sents) or 1
    syl = [syllables(w) for w in all_words]
    ms = 100 * sum(1 for s in syl if s >= 3) / n      # % mehrsilbige Wörter
    sl = n / ns                                        # Ø Satzlänge (Wörter)
    iw = 100 * sum(1 for w in all_words if len(w) > 6) / n   # % lange Wörter
    es = 100 * sum(1 for s in syl if s == 1) / n       # % einsilbige Wörter
    wstf = 0.1935 * ms + 0.1672 * sl + 0.1297 * iw - 0.0327 * es - 0.875
    return Metrics(
        n_sentences=len(sents), n_words=len(all_words),
        avg_sentence_words=round(sl, 1), max_sentence_words=max_len,
        wstf=round(wstf, 1),
    )


# Interne/englische Fachbegriffe, die in Nutzer-Texten Klartext weichen sollen.
BANNED_TERMS = {
    "Membership": "Anteil", "Allocation": "Buchung", "LotteryRun": "Losung",
    "Wish": "Wunsch", "Frontend": "App/Oberfläche", "Backend": "Verwaltung",
    "opt-in": "aktivieren", "opt-out": "abschalten",
}


@dataclass
class Limits:
    max_sentence_words: int = 35
    avg_sentence_words: float = 22.0
    wstf_max: float = 13.0


def check(label: str, text: str, limits: Limits = Limits()) -> list[str]:
    """Liste konkreter Verstöße (leer = ok) für einen Text."""
    m = analyze(text)
    issues: list[str] = []
    if m.max_sentence_words > limits.max_sentence_words:
        issues.append(
            f"{label}: längster Satz {m.max_sentence_words} Wörter "
            f"(> {limits.max_sentence_words}) – kürzen/teilen.")
    if m.avg_sentence_words > limits.avg_sentence_words:
        issues.append(
            f"{label}: Ø Satzlänge {m.avg_sentence_words} Wörter "
            f"(> {limits.avg_sentence_words}).")
    if m.wstf > limits.wstf_max:
        issues.append(
            f"{label}: Lesbarkeit WSTF {m.wstf} (> {limits.wstf_max}) – "
            f"einfacher formulieren.")
    for term, better in BANNED_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", text):
            issues.append(f'{label}: Fachbegriff "{term}" -> besser "{better}".')
    return issues
