"""Einlesen von Kontoauszügen für den Rechnungsabgleich.

Bewusst um eine **normalisierte Transaktion** (`ParsedTxn`) herum gebaut: pro
Format ein Parser, der Datei-Bytes → Liste von `ParsedTxn` macht. So ist ein
weiteres Format (z.B. MT940) später nur ein zusätzlicher Parser.

Unterstützt:
  * `csv`  – die meisten deutschen Bank-CSV-Exporte (Spalten werden über
             Header-Stichwörter erkannt; deutsches Zahlen-/Datumsformat,
             UTF-8 oder ISO-8859-1).
  * `camt` – CAMT.053 (ISO 20022, XML) – standardisiert, alle Banken bieten es.

Nur **Eingänge** (Gutschriften, Betrag > 0) sind für den Abgleich relevant;
Belastungen werden ignoriert.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET


@dataclass
class ParsedTxn:
    booked_on: date | None
    amount: Decimal
    purpose: str
    name: str
    iban: str
    raw: str = ""

    def fingerprint(self) -> str:
        base = (f"{self.booked_on}|{self.amount}|{self.purpose.strip()}|"
                f"{self.iban}|{self.name.strip()}")
        return hashlib.sha1(base.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def _parse_amount(text: str) -> Decimal | None:
    """Deutsches/englisches Zahlenformat → Decimal. '1.234,56' und '1234.56'."""
    s = (text or "").strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-") or s.endswith("-")
    s = s.strip("+-").replace("€", "")
    if "," in s and "." in s:
        # Annahme: '.' Tausender, ',' Dezimal (deutsches Format)
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        val = Decimal(s)
    except InvalidOperation:
        return None
    return -val if neg else val


def _parse_date(text: str) -> date | None:
    s = (text or "").strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #

# Spalten-Erkennung über Stichwörter im (klein geschriebenen) Header.
_COL = {
    "date": ["buchungstag", "buchungsdatum", "valutadatum", "valuta", "datum"],
    "amount": ["betrag", "umsatz"],
    "purpose": ["verwendungszweck", "buchungstext", "vorgang"],
    "name": ["beguenstigter", "zahlungsbeteiligter", "auftraggeber",
             "empfänger", "empfaenger", "name", "zahlungspflichtiger"],
    "iban": ["kontonummer/iban", "iban zahlungsbeteiligter", "iban", "kontonummer"],
}


def _pick(header: list[str], keys: list[str]) -> int | None:
    low = [h.strip().lower() for h in header]
    for key in keys:                       # erst exakte, dann Teiltreffer
        for i, h in enumerate(low):
            if h == key:
                return i
    for key in keys:
        for i, h in enumerate(low):
            if key in h:
                return i
    return None


def parse_csv(data: bytes) -> list[ParsedTxn]:
    text = _decode(data)
    # Trennzeichen erkennen (deutsche Exporte meist ';').
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    # Viele deutsche Bank-Exporte (Sparkasse/DKB/…) stellen dem eigentlichen
    # Header eine Metadaten-Präambel voran („Konto:“, „Zeitraum:“ …). Deshalb NICHT
    # blind rows[0] als Header nehmen, sondern die erste Zeile suchen, in der sowohl
    # Datum- als auch Betrag-Spalte erkannt werden (#53). Nur die ersten Zeilen
    # prüfen – der Header steht immer weit oben.
    header_i, idx = None, {}
    for i, row in enumerate(rows[:25]):
        cand = {k: _pick(row, keys) for k, keys in _COL.items()}
        if cand["amount"] is not None and cand["date"] is not None:
            header_i, idx = i, cand
            break
    if header_i is None:
        raise ValueError(
            "CSV nicht erkannt: Spalten für Datum/Betrag fehlen. Bitte einen "
            "CSV-Export mit Spalten wie „Buchungstag“ und „Betrag“ verwenden.")

    out: list[ParsedTxn] = []
    for row in rows[header_i + 1:]:
        def cell(key):
            i = idx[key]
            return row[i] if i is not None and i < len(row) else ""
        amount = _parse_amount(cell("amount"))
        if amount is None or amount <= 0:      # nur Eingänge
            continue
        out.append(ParsedTxn(
            booked_on=_parse_date(cell("date")),
            amount=amount,
            purpose=cell("purpose").strip(),
            name=cell("name").strip(),
            iban=cell("iban").strip(),
            raw=delim.join(row),
        ))
    return out


# --------------------------------------------------------------------------- #
# CAMT.053 (XML, namensraum-tolerant)
# --------------------------------------------------------------------------- #

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _findall_text(el, name) -> list[str]:
    return [c.text.strip() for c in el.iter()
            if _local(c.tag) == name and c.text and c.text.strip()]


def parse_camt(data: bytes) -> list[ParsedTxn]:
    # Schutz vor „billion laughs"/Entity-Expansion: DOCTYPE/ENTITY ablehnen.
    # CAMT.053-Dateien enthalten so etwas nie (defusedxml ohne Extra-Abhängigkeit).
    head = (data[:4096] if isinstance(data, (bytes, bytearray)) else b"").lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("CAMT-Datei mit DOCTYPE/ENTITY wird abgelehnt.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"CAMT-Datei nicht lesbar: {exc}")
    out: list[ParsedTxn] = []
    entries = [e for e in root.iter() if _local(e.tag) == "Ntry"]
    for e in entries:
        cd = _find(e, "CdtDbtInd")
        if cd is None or (cd.text or "").strip().upper() != "CRDT":
            continue                            # nur Gutschriften
        amt_el = _find(e, "Amt")
        amount = _parse_amount(amt_el.text if amt_el is not None else "")
        if amount is None or amount <= 0:
            continue
        # Buchungsdatum
        bookg = _find(e, "BookgDt")
        booked = None
        if bookg is not None:
            dt = _find(bookg, "Dt") or _find(bookg, "DtTm")
            booked = _parse_date((dt.text or "")[:10]) if dt is not None else None
        # Verwendungszweck = alle Ustrd zusammen
        purpose = " ".join(_findall_text(e, "Ustrd"))
        # Zahler: Dbtr/Nm + DbtrAcct IBAN
        name, iban = "", ""
        dbtr = _find(e, "Dbtr")
        if dbtr is not None:
            nm = _find(dbtr, "Nm")
            name = (nm.text or "").strip() if nm is not None else ""
        acct = _find(e, "DbtrAcct")
        if acct is not None:
            ib = _find(acct, "IBAN")
            iban = (ib.text or "").strip() if ib is not None else ""
        out.append(ParsedTxn(
            booked_on=booked, amount=amount, purpose=purpose,
            name=name, iban=iban,
            raw=ET.tostring(e, encoding="unicode")[:1000]))
    return out


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

PARSERS = {"csv": parse_csv, "camt": parse_camt}


def parse(data: bytes, fmt: str) -> list[ParsedTxn]:
    fmt = (fmt or "csv").lower()
    if fmt not in PARSERS:
        raise ValueError(f"Unbekanntes Format: {fmt}")
    return PARSERS[fmt](data)
