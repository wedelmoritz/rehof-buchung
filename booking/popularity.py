"""Reine Logik: **Beliebtheit relativ zur Kapazität** (ADR 0103, P0).

Die Wunsch-Anzeige soll nicht die *rohe* Nachfrage zeigen, sondern wie gefragt ein
Zeitraum **im Verhältnis zur vergebbaren Kapazität** ist – gemessen je
**Äquivalenzklasse** (die Losung weicht auf gleichwertige Quartiere derselben Klasse
aus, ADR 0003). Diese Größe ist rein rechnerisch und **Django-frei**, damit sie ohne
DB in ``tests/`` prüfbar bleibt; der Service reicht überlappende Wunschzahl + Kapazität
herein.

**Wortwahl bewusst positiv (ADR 0072):** intern „Nachfrage/Knappheit", im Frontend
niemals „Konflikt/umkämpft":

| Verhältnis Nachfrage : Kapazität | Band-Key | Frontend-Label |
|---|---|---|
| keine Überschneidung (0)          | ``free``    | **frei** |
| Nachfrage < Kapazität             | ``some``    | **etwas gefragt** |
| Nachfrage ≈ Kapazität             | ``popular`` | **beliebt** |
| Nachfrage ≫ Kapazität             | ``very``    | **sehr beliebt** |

Alles ist **Anzeige** – die RSD-Losung bleibt unberührt (Strategiesicherheit): dem
Signal zu folgen ist genau das kooperative Verhalten, das der Mechanismus belohnt.
"""
from __future__ import annotations

# Schwellen (Nachfrage/Kapazität). Bewusst als benannte Konstanten – die genaue
# Kalibrierung ist eine Wert-Entscheidung der BL (ADR 0103); Default: „beliebt" ab
# Gleichstand, „sehr beliebt" ab dem 1,5-Fachen der Kapazität.
POPULAR_RATIO = 1.0        # Nachfrage ≈ Kapazität → „beliebt"
VERY_POPULAR_RATIO = 1.5   # Nachfrage ≫ Kapazität → „sehr beliebt"

# Reihenfolge „harmloser → gefragter" (für „nimm das gefragtere Band" bei Aggregation).
_ORDER = ["free", "some", "popular", "very"]

_BANDS: dict[str, dict] = {
    "free":    {"key": "free",    "label": "frei",          "tone": "free"},
    "some":    {"key": "some",    "label": "etwas gefragt", "tone": "many"},
    "popular": {"key": "popular", "label": "beliebt",       "tone": "few"},
    "very":    {"key": "very",    "label": "sehr beliebt",  "tone": "full"},
}


def popularity_band(overlap: int, capacity: int) -> dict:
    """Beliebtheits-Band aus **überschneidender Nachfrage** ``overlap`` und
    **vergebbarer Kapazität** ``capacity`` (Zahl gleichwertiger, in diesem Fenster
    buchbarer Quartiere der Klasse).

    Gibt ``{"key", "label", "tone"}`` zurück. ``tone`` ist bewusst gleich den
    bestehenden Kalender-Ampel-Klassen (``free``/``many``/``few``/``full``), damit die
    vorhandene Färbung ohne CSS-Zuwachs weiterläuft. Deterministisch & ohne Django."""
    overlap = max(0, int(overlap or 0))
    if overlap == 0:
        return _BANDS["free"]
    cap = int(capacity or 0)
    # Keine buchbare Kapazität, aber Nachfrage → maximal gefragt (Division vermeiden).
    ratio = float("inf") if cap <= 0 else overlap / cap
    if ratio < POPULAR_RATIO:
        return _BANDS["some"]
    if ratio <= VERY_POPULAR_RATIO:
        return _BANDS["popular"]
    return _BANDS["very"]


def band_rank(band: dict | str) -> int:
    """Rang eines Bandes (0 = frei … 3 = sehr beliebt) – für „nimm das gefragtere"."""
    key = band["key"] if isinstance(band, dict) else band
    return _ORDER.index(key) if key in _ORDER else 0


def worse_band(a: dict, b: dict) -> dict:
    """Das **gefragtere** (höher-rangige) der beiden Bänder – zum Aggregieren mehrerer
    Klassen zu EINEM Tages-/Wochensignal (die knappste Klasse bestimmt die Warnung)."""
    return a if band_rank(a) >= band_rank(b) else b


def suitability_score(fits: bool, band: dict, *, own_wish: bool = False) -> tuple:
    """Sortierschlüssel für **Empfehlungen beim Eintragen** (ADR 0103, P0b):
    passende Unterkünfte mit **geringer** Beliebtheit zuerst. Kleiner = besser.

    Reihenfolge: erst Eignung (passt zur Personenzahl), dann geringe Beliebtheit
    (``band_rank``), eigene bereits gewünschte Quartiere nach hinten (nicht doppelt
    empfehlen). Rein für die Anzeige – kein Eingriff ins Losverfahren."""
    return (0 if fits else 1, 1 if own_wish else 0, band_rank(band))
