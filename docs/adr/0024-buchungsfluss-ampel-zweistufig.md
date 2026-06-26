# 0024 – Buchungsfluss: Ampel-Kalender + zweistufige Bestätigung

## Status

Accepted (2026-06-26)

## Kontext

Die Spontanbuchung muss für Laien verständlich sein und trotzdem viele Regeln
berücksichtigen (Freigabe, Quartier-Saison, Eignung nach Personen/Barrierefreiheit,
Mindestnächte, verbleibendes Budget). Ein einstufiges Formular würde Fehler erst
beim Absenden zeigen; eine verbindliche Buchung darf nicht versehentlich entstehen.

## Entscheidung

Ein **zweistufiger Fluss** mit vorgeschalteter Verfügbarkeitsanzeige:

1. **`book`** (`booking/views.py`): Ampel-Kalender (frei/belegt/gesperrt), Personen
   und Barrierefreiheit oben einstellen, Anreise/Abreise wählen (auch über
   Monatsgrenzen). Eignung und Mindestaufenthalt werden **vorab** angezeigt; ist
   alles belegt → Warteliste (siehe ADR 0025). Hilfsservices:
   `services.split_quarters_for_range`, `range_is_released`, `min_nights_for_range`.
2. **`book_confirm`**: Bestätigungsschritt – Unterkunft/Zeitraum prüfen, Personen +
   Begleitung, verbleibende Tage sehen, optional Endreinigung mitbuchen. **Erst**
   „Verbindlich buchen“ legt die `Allocation` über `services.book_spontaneous` an
   (der Knopf ist deaktiviert, solange Mindestaufenthalt/Budget verletzt sind).

Derselbe zweistufige Aufbau gilt analog für Wunsch-, Externen- und Transfer-Flows
(Konsistenz). Die eigentliche Anlage ist gegen Races gesperrt (siehe ADR 0013).

## Betrachtete Alternativen

- **Einstufiges Formular:** Regelverstöße erst nach Absenden sichtbar; höhere
  Fehl-/Fehlbuchungsgefahr.
- **Voll-AJAX-Wizard (SPA):** mehr Frontend-Komplexität, gegen das schlanke
  server-gerenderte Prinzip (ADR 0001/0002).

## Konsequenzen

**Positiv**
- Fehler werden vor der verbindlichen Buchung sichtbar; bewusster Bestätigungsschritt.
- Einheitliches Muster über alle Buchungsarten.

**Negativ**
- Ein zusätzlicher Schritt/Roundtrip pro Buchung.
- Verfügbarkeit wird zweimal berechnet (Anzeige + finale Prüfung) – bewusst, da der
  Zustand sich zwischen den Schritten ändern kann.
