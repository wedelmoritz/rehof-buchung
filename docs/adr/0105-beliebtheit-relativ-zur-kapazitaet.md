# 0105 – Beliebtheit relativ zur Kapazität + proaktive Vorschläge (Umsetzung P0)

## Status

Proposed (2026-07-20) · **setzt [ADR 0103](0103-wunsch-situationsbild-beliebtheit-und-vorschlaege.md)
P0 um** · Wortwahl [ADR 0072](0072-positive-wortwahl-frontend.md) · Äquivalenzklassen/
Ausweichen [ADR 0003](0003-losverfahren-weighted-rsd.md). **Umgesetzt (2026-07).**

## Kontext

Der Wunsch-Kalender färbte Tage nach **roher** Nachfrage gegen die **Gesamt**-Quartierszahl.
Das verkennt die Äquivalenzklassen: Eine kleine Klasse kann überzeichnet sein, während die
Gesamtzahl harmlos aussieht. ADR 0103 (P0) verlangt **Beliebtheit relativ zur Kapazität je
Äquivalenzklasse** und **proaktive Vorschläge schon beim Eintragen**.

## Entscheidung

**Reine Logik `booking/popularity.py` (Django-frei):** `popularity_band(overlap, capacity)`
bildet das Verhältnis Nachfrage : Kapazität auf vier **positive** Bänder ab
(frei / etwas gefragt / beliebt / sehr beliebt; ADR 0072). Schwellen als benannte
Konstanten (`POPULAR_RATIO=1.0`, `VERY_POPULAR_RATIO=1.5` – „beliebt" ab Gleichstand,
„sehr beliebt" ab dem 1,5-Fachen; die genaue Kalibrierung ist eine BL-Wert-Entscheidung).
Dazu `worse_band` (mehrere Klassen → ein Signal, die **knappste** Klasse warnt) und
`suitability_score` (Sortierschlüssel Eignung × geringe Beliebtheit). Das `tone`-Feld ist
bewusst gleich den bestehenden Ampel-Klassen (`free/many/few/full`) → **kein CSS-Zuwachs**.

**P0a – Kalender-Signal.** `build_wish_calendar` färbt jeden Tag **je Äquivalenzklasse**
kapazitätsrelativ: überschneidende Wünsche der Klasse gegen die an diesem Tag **buchbaren**
gleichwertigen Quartiere (`Quarter.bookable_on`, saison-bewusst); die knappste Klasse
bestimmt die Tages-Ampel. Positive Legende/Tooltips.

**P0b – Proaktive Vorschläge beim Eintragen.** `class_popularity_for_range(period, start,
end)` liefert das Band **je Quartier** für den gewählten Zeitraum. Die Kandidatenliste wird
nach `suitability_score` sortiert (wenig gefragte zuerst), ein Block **„💡 Empfohlen: hier
hast du die besten Chancen"** hebt die drei passendsten, wenig gefragten, noch nicht selbst
gewünschten Unterkünfte hervor. Ergänzend erscheint der **„weniger beliebter Zeitraum"**-
Tipp (`wish_deconfliction`) **schon bei der Auswahl** je Kandidat.

**Granularität (bewusste Abweichung vom Konzept):** ADR 0103 nennt „Wochen-Granularität".
Umgesetzt ist **Tages**-Granularität (je Tag die überschneidenden Wünsche) – für das
Wählen von An-/Abreise **ehrlicher** (nur real am selben Tag konkurrierende Wünsche zählen)
und feiner als der Wochen-Eimer; das kapazitätsrelative Prinzip bleibt identisch.

## Architektur / Sicherheit / Performanz

- **Strategiesicherheit unberührt:** alles ist **Anzeige**; die RSD-Losung bleibt gleich →
  dem Vorschlag zu folgen ist genau das kooperative Verhalten des Mechanismus (kein Gaming).
- **Datensparsamkeit/Security:** nur **Aggregat-Bänder** (keine Namen); keine externen
  Calls; alle Werte serverseitig, escaped gerendert; CSP-treu (keine Inline-Handler);
  `data-ajax`-Progressive-Enhancement wie bisher.
- **Performanz:** eine Wunsch-Abfrage je Ansicht; Quartiere je Klasse einmal geladen
  (wenige Dutzend Objekte), Rest in Python – gleiche Größenordnung wie zuvor.

## Betrachtete Alternativen

- **Aggregat statt je Klasse:** verworfen – verdeckt die Knappheit einzelner Klassen
  (genau der Fehler des alten Signals).
- **Wochen-Eimer (wie im Konzept):** verworfen zugunsten Tages-Granularität (ehrlicher
  fürs Datum-Wählen; s. o.).
- **Schwellen im Backend konfigurierbar:** zurückgestellt (erst Feld/Justierbedarf mit der
  BL klären) – Konstanten sind klar benannt und leicht später zu heben.

## Konsequenzen

**Positiv** – der Kalender zeigt endlich die ehrliche Chance-Information (klassen- und
kapazitätsrelativ); Vorschläge ziehen das Entzerren **an den Entscheidungspunkt**; positive
Wortwahl; volle Auditierbarkeit, keine neue Abhängigkeit.

**Negativ / Grenzen** – die Bänder-Schwellen sind (noch) Code-Konstanten; die Kapazität
nimmt den Starttag des Fensters als Repräsentant (bei saisonalen Rändern eine kleine
Vereinfachung, nur Anzeige).
