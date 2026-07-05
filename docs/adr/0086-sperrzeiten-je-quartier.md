# 0086 – Sperrzeiten je Quartier (Reinigung/Reparatur)

## Status

Accepted (2026-07-05)

> Tester-Feedback der Betriebsleitung (Sophie/Judith): #61.

## Kontext

Die Betriebsleitung braucht die Möglichkeit, ein Quartier für einen Zeitraum
**aus dem Verkehr zu ziehen** – wegen Renovierung, Reparatur, Wasserschaden oder
einer Grundreinigung. Bisher ließ sich das nur simulieren (Schein-Buchung), was
Tage-Budget/Rechnung/Statistik verfälscht hätte.

## Entscheidung

Ein schlankes Modell **`QuarterBlock`** (Quartier, `start`, `end` exklusiv,
`reason`, `created_at`) markiert einen Sperrzeitraum. Ein Block verhält sich in
der Verfügbarkeits-Logik **wie eine Belegung**, gehört aber **niemandem** (kein
Mitglied, keine Rechnung, kein Tage-Verbrauch).

**Integration in die eine Verfügbarkeits-Naht** (`booking/services/slots.py`):
Ein Helfer `_block_qs(quarter, start, end)` liefert überlappende Blöcke; er ist
**neben `_external_blocking_qs`** in alle Sperr-Quellen eingehängt:
`quarter_is_free`, `find_gaps`, `find_bookable_gaps` und `_compute_occupied`
(der geteilte Belegungs-Cache). Da die eigentliche Buchung immer über
`quarter_is_free` unter Sperre prüft, ist ein Block **hart durchgesetzt**
(Spontanbuchung, Bestätigung, Ändern/Wechsel, Warteliste). Der Belegungs-Cache
wird per Signal (`post_save`/`post_delete` auf `QuarterBlock`) invalidiert.

**Pflege durch die Betriebsleitung ohne Backend:** eine Karte „Sperrzeiten
(Reinigung/Reparatur)" auf der Verwaltungs-Unterseite **Reinigung**
(`verw_reinigung`) legt Blöcke an (Quartier · Von · Bis · Grund) und hebt sie
wieder auf – über den zentralen POST-Dispatcher `views._verw_post`
(`add_block`/`delete_block`). Für Admins zusätzlich ein normaler
`QuarterBlockAdmin` im Backend (Sektion „Quartiere & Buchungssystem").

**Sichtbarkeit im Belegungsplan:** `build_occupancy_timeline` rendert Blöcke als
eigene, **schraffiert-graue** Balken (`.bar.blocked`, „🔧 Grund/gesperrt") – so
sieht das Team im Plan sofort, dass eine Einheit gesperrt ist (kein Gast). Blöcke
zählen in der „frei"-Zahl je Tag mit (belegt).

## Konsequenzen

**Positiv** – ein echter, nicht verfälschender Sperrmechanismus; genau EINE
Verfügbarkeits-Naht bleibt maßgeblich (keine Sonderpfade); BL pflegt es ohne
Backend; im Plan sichtbar. Kleine, additive Migration (`booking/0052`).

**Grenzen** – ein Block ist rein zeit-/quartierbezogen (keine Teil-Sperre einzelner
Betten). Wiederkehrende Sperren (z. B. „jeden Montag") sind bewusst nicht
modelliert – bei Bedarf als Folgeschritt.
