"""Plausibilitäts-Prüfungen für Benutzereingaben – reines Python (ohne Django),
damit isoliert mit ``pytest`` testbar (siehe ``tests/test_validation.py``).

Jede ``*_error``-Funktion liefert einen **deutschen Fehlertext** oder ``None``
(= in Ordnung). Die Django-Anbindung (Formulare in ``forms.py``, Service-Layer in
``services.py``) macht daraus eine ``ValidationError`` bzw. eine Fehlermeldung.

Zweck:
  1. **Grundlegende Plausibilität:** Name nur Buchstaben, PLZ genau 5 Ziffern,
     IBAN mit Längen- UND Prüfsummen-Check (ISO 13616 / Mod-97) usw.
  2. **Defense-in-Depth gegen XSS/Injektion:** Steuerzeichen und Markup (`<`/`>`)
     werden in Namen/Orten/Adressen abgewiesen. Django-Templates escapen Ausgaben
     ohnehin; diese Prüfung schützt zusätzlich Exporte (CSV/xlsx), Rechnungs-PDF
     und E-Mails, wo nicht dieselbe HTML-Escaping-Logik greift. Die CSV-/xlsx-
     Formel-Injektion wird zusätzlich in ``exports.py`` entschärft.

Annahme: deutsche Adressen (PLZ = 5 Ziffern). Für internationale Gäste müsste ein
Land-Feld + länderspezifische Regeln ergänzt werden (siehe docs/ADR 0039).
"""
from __future__ import annotations

import re

# Steuerzeichen: in EINZEILIGEN Feldern (Name/PLZ/Ort/…) ist KEINES erlaubt.
_CTRL_ANY = re.compile(r"[\x00-\x1f\x7f]")
# In Freitext bleiben Zeilenumbruch (\n) und Tabulator (\t) erlaubt.
_CTRL_FREETEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _has_ctrl(s: str) -> bool:
    return bool(_CTRL_ANY.search(s))


def strip_controls(value: str | None, *, max_len: int | None = None) -> str:
    """Säubert Freitext: entfernt Steuerzeichen (außer \\n/\\t) und kürzt optional.
    Nicht-abweisend – für Notizen/Begleitung/Nachrichten, wo Django die Ausgabe
    ohnehin escapt."""
    s = _CTRL_FREETEXT.sub("", value or "")
    if max_len is not None:
        s = s[:max_len]
    return s


def name_error(value: str | None, *, field: str = "Name",
               min_len: int = 2, max_len: int = 120) -> str | None:
    """Name: nur Buchstaben (inkl. Umlaute/Akzente), Leerzeichen sowie ``- ' .``
    (für „Anne-Marie", „O'Brien", „Dr."). Keine Ziffern, kein Markup."""
    v = (value or "").strip()
    if not v:
        return f"Bitte {field} angeben."
    if _has_ctrl(v):
        return f"{field} enthält ungültige Zeichen."
    if len(v) < min_len:
        return f"{field} ist zu kurz."
    if len(v) > max_len:
        return f"{field} ist zu lang (höchstens {max_len} Zeichen)."
    if any(ch in v for ch in "<>"):
        return f"{field} enthält ungültige Zeichen."
    if not all(ch.isalpha() or ch in " -'." for ch in v):
        return (f"{field} darf nur Buchstaben, Leerzeichen, Bindestrich und "
                "Apostroph enthalten.")
    if not any(ch.isalpha() for ch in v):
        return f"{field} muss Buchstaben enthalten."
    return None


def plz_error(value: str | None, *, required: bool = True) -> str | None:
    """Deutsche PLZ: genau 5 Ziffern."""
    v = (value or "").strip()
    if not v:
        return "Bitte PLZ angeben." if required else None
    if not re.fullmatch(r"[0-9]{5}", v):
        return "Die PLZ muss aus genau 5 Ziffern bestehen."
    return None


def city_error(value: str | None, *, required: bool = True,
               max_len: int = 120) -> str | None:
    """Ort: Buchstaben + übliche Satzzeichen (Leerzeichen, ``- . ' ( ) /``),
    z. B. „Frankfurt (Oder)", „Halle (Saale)". Keine Ziffern, kein Markup."""
    v = (value or "").strip()
    if not v:
        return "Bitte Ort angeben." if required else None
    if _has_ctrl(v) or any(ch in v for ch in "<>"):
        return "Der Ort enthält ungültige Zeichen."
    if len(v) > max_len:
        return f"Der Ort ist zu lang (höchstens {max_len} Zeichen)."
    if not all(ch.isalpha() or ch in " -.'()/" for ch in v):
        return "Der Ort darf nur Buchstaben und übliche Satzzeichen enthalten."
    if not any(ch.isalpha() for ch in v):
        return "Der Ort muss Buchstaben enthalten."
    return None


def street_error(value: str | None, *, required: bool = True,
                 max_len: int = 160) -> str | None:
    """Straße & Hausnummer: Buchstaben, Ziffern (Hausnr.) und ``- . , / &`` sowie
    Leerzeichen. Kein Markup/Steuerzeichen."""
    v = (value or "").strip()
    if not v:
        return "Bitte Straße & Hausnummer angeben." if required else None
    if _has_ctrl(v) or any(ch in v for ch in "<>"):
        return "Die Straße enthält ungültige Zeichen."
    if len(v) > max_len:
        return f"Die Straße ist zu lang (höchstens {max_len} Zeichen)."
    if not all(ch.isalnum() or ch in " -.,/&" for ch in v):
        return "Die Straße enthält ungültige Zeichen."
    if not any(ch.isalpha() for ch in v):
        return "Die Straße muss einen Straßennamen enthalten."
    return None


def email_error(value: str | None, *, required: bool = True) -> str | None:
    """Einfache E-Mail-Plausibilität (genau ein @, Punkt in der Domain, keine
    Leer-/Steuerzeichen). Die echte Zustellbarkeit zeigt sich erst beim Versand."""
    v = (value or "").strip()
    if not v:
        return "Bitte E-Mail-Adresse angeben." if required else None
    if _has_ctrl(v) or " " in v or v.count("@") != 1 or len(v) > 254:
        return "Bitte eine gültige E-Mail-Adresse angeben."
    local, _, domain = v.partition("@")
    if not local or "." not in domain or domain.startswith(".") \
            or domain.endswith(".") or ".." in domain:
        return "Bitte eine gültige E-Mail-Adresse angeben."
    return None


# IBAN-Längen je Land (gängige Auswahl). Unbekannte Länder: generische 15–34-Prüfung.
IBAN_LENGTHS = {
    "DE": 22, "AT": 20, "CH": 21, "LI": 21, "NL": 18, "BE": 16, "LU": 20,
    "FR": 27, "MC": 27, "IT": 27, "ES": 24, "PT": 25, "DK": 18, "SE": 24,
    "NO": 15, "FI": 18, "PL": 28, "CZ": 24, "SK": 24, "GB": 22, "IE": 22,
}


def iban_error(value: str | None, *, required: bool = False) -> str | None:
    """IBAN-Prüfung: Format, Länge (länderspezifisch, wenn bekannt) **und**
    Prüfsumme (ISO 13616, Mod-97). Leer ist erlaubt, sofern nicht ``required``."""
    raw = (value or "").replace(" ", "").upper()
    if not raw:
        return "Bitte IBAN angeben." if required else None
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]+", raw):
        return "Ungültige IBAN (Format: 2 Buchstaben, 2 Ziffern, dann alphanumerisch)."
    if not (15 <= len(raw) <= 34):
        return "Ungültige IBAN (Länge)."
    expected = IBAN_LENGTHS.get(raw[:2])
    if expected and len(raw) != expected:
        return (f"Ungültige IBAN-Länge für {raw[:2]} "
                f"(erwartet {expected} Zeichen, erhalten {len(raw)}).")
    # Mod-97: hinten/vorne tauschen, Buchstaben → Zahlen (A=10 … Z=35), Rest = 1.
    rearranged = raw[4:] + raw[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    if int(digits) % 97 != 1:
        return "Ungültige IBAN (Prüfsumme stimmt nicht)."
    return None


def normalize_iban(value: str | None) -> str:
    """Vereinheitlicht eine (gültige) IBAN: ohne Leerzeichen, Großbuchstaben."""
    return (value or "").replace(" ", "").upper()
