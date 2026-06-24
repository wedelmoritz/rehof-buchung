"""Reine Logik für den Beds24-Migrations-Assistenten (ohne Django/DB).

Beds24 bietet einen CSV-Export der Buchungen (EXPORT-Knopf bzw. Report). Die
Gäste tragen ihre Namen dort selbst ein – es gibt also Schreibweisen-Abweichungen
und keinen stabilen Identifier. Dieses Modul

  * liest die CSV flexibel (Trennzeichen + Spalten per Stichwörtern erkannt),
  * normalisiert Namen und berechnet einen unscharfen Ähnlichkeits-Score, um pro
    Buchung das wahrscheinlichste Mitglied (und Quartier) vorzuschlagen.

Der eigentliche Abgleich bleibt manuell (Service/Views); hier liegt nur die
datenbankfreie, isoliert testbare Rechen-/Parse-Logik.
"""
from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

# Spalten-Erkennung: Stichwörter (klein) je Zielfeld. Erst-Treffer gewinnt.
_HEADER_KEYS = {
    "first": ("first", "firstname", "vorname", "given"),
    "last": ("last", "lastname", "surname", "nachname", "family"),
    "name": ("guest", "name", "gast", "guestname"),
    "arrival": ("arrival", "checkin", "check-in", "check in", "anreise", "from", "von", "start"),
    "departure": ("departure", "checkout", "check-out", "check out", "abreise", "to", "bis", "end"),
    "unit": ("unit", "room", "zimmer", "quartier", "apartment", "property", "unterkunft"),
    "persons": ("numadult", "adult", "guests", "person", "pax", "personen", "anzahl"),
    "status": ("status", "state"),
    "price": ("price", "amount", "preis", "betrag", "total"),
    "email": ("email", "e-mail", "mail"),
    "ref": ("bookid", "booking id", "bookingid", "ref", "referenz", "nummer", "id"),
}

_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d",
                 "%d-%m-%Y", "%d.%m.%y")


@dataclass
class Beds24Row:
    """Eine geparste Buchungszeile aus der Beds24-CSV."""
    guest_name: str
    arrival: date | None
    departure: date | None
    unit: str = ""
    persons: int = 1
    status: str = ""
    email: str = ""
    ref: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def nights(self) -> int:
        if self.arrival and self.departure:
            return max(0, (self.departure - self.arrival).days)
        return 0

    @property
    def valid(self) -> bool:
        return bool(self.guest_name and self.arrival and self.departure
                    and self.departure > self.arrival)


def _norm(s: str) -> str:
    """Kleinbuchstaben, Akzente weg, nur Buchstaben/Ziffern + Einzel-Leerzeichen."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("ß", "ss")
    out = [c if c.isalnum() else " " for c in s]
    return " ".join("".join(out).split())


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).split() if t]


def name_score(a: str, b: str) -> float:
    """Ähnlichkeit zweier Namen in [0,1] – reihenfolge-unabhängig (Tokens werden
    sortiert), robust gegen „Nachname, Vorname" und Tippfehler."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    na, nb = " ".join(sorted(ta)), " ".join(sorted(tb))
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Bonus für gemeinsame ganze Tokens (Vor-/Nachname exakt getroffen).
    sa, sb = set(ta), set(tb)
    overlap = len(sa & sb) / max(len(sa), len(sb))
    return round(0.6 * ratio + 0.4 * overlap, 4)


@dataclass
class Candidate:
    key: object
    names: list[str]


def rank_candidates(query: str, candidates: list[Candidate], *, limit: int = 5,
                    min_score: float = 0.34) -> list[tuple[object, float]]:
    """Liefert die besten (key, score) für einen Namen, absteigend sortiert.
    Je Kandidat zählt der beste Score über alle seine Namensvarianten."""
    scored = []
    for c in candidates:
        best = max((name_score(query, n) for n in c.names if n), default=0.0)
        if best >= min_score:
            scored.append((c.key, best))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:limit]


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    # ISO mit Uhrzeit (2026-06-01 14:00 / 2026-06-01T14:00) → Datumsteil.
    head = value.replace("T", " ").split(" ")[0]
    from datetime import datetime
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _map_headers(header: list[str]) -> dict[str, int]:
    """Ordnet Zielfeldern den Spaltenindex zu (erste passende Spalte gewinnt)."""
    mapping: dict[str, int] = {}
    lowered = [(_norm(h), i) for i, h in enumerate(header)]
    for field_name, keys in _HEADER_KEYS.items():
        for hnorm, idx in lowered:
            if any(k in hnorm for k in keys):
                mapping.setdefault(field_name, idx)
                break
    return mapping


def parse_csv(data: str) -> list[Beds24Row]:
    """Parst den Beds24-CSV-Export zu Buchungszeilen. Trennzeichen wird erkannt
    (Komma/Semikolon/Tab); Spalten über Stichwörter zugeordnet."""
    if not data.strip():
        return []
    sample = data[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(data), delimiter=delim)
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    m = _map_headers(header)

    def cell(row, key):
        idx = m.get(key)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    out: list[Beds24Row] = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        name = cell(row, "name")
        first, last = cell(row, "first"), cell(row, "last")
        if first or last:   # getrennte Spalten haben Vorrang vor „name"
            name = " ".join(p for p in (first, last) if p)
        persons_raw = "".join(ch for ch in cell(row, "persons") if ch.isdigit())
        out.append(Beds24Row(
            guest_name=name,
            arrival=_parse_date(cell(row, "arrival")),
            departure=_parse_date(cell(row, "departure")),
            unit=cell(row, "unit"),
            persons=int(persons_raw) if persons_raw else 1,
            status=cell(row, "status"),
            email=cell(row, "email"),
            ref=cell(row, "ref"),
            raw={header[i] if i < len(header) else f"col{i}": v
                 for i, v in enumerate(row)},
        ))
    return out
