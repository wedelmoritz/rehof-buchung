# 0076 – Wochenend-Richtwert, kleinere Unterkünfte, dynamische Hilfe-Werte, Regel-Transparenz für Wünsche/Losung

## Status

Accepted (2026-06-30)

> Ergänzt ADR 0075 (Buchungsrichtlinien) und 0073/0074 (Losung-UX/Hilfe).

## Kontext

Vier Anschluss-Wünsche aus dem Praxis-Feedback:

a) Analog zum Winter-Richtwert soll ein **Wochenend-Wert** angezeigt werden und
   **warnen, wenn er sich dem Höchstwert nähert**.
b) Unterkünfte sollen sich **auch für mehr Personen** buchen lassen, als sie
   ausgelegt sind (falls nichts Passendes mehr frei ist) – **konfigurierbar** und
   **deutlich angezeigt**.
c) Auf der Hilfeseite stand „Die genauen Werte stellt die Verwaltung im Backend
   ein" – stattdessen sollen die **echten konfigurierten Werte** dort erscheinen.
d) Es soll **genau erklärt** werden, wie die Buchungsregeln für **Wünsche/Losung**
   greifen bzw. nur als Hinweis erscheinen – inkl. des Hinweises, dass man **mehr
   Wochenenden wünschen darf, als erfüllt werden** (legitim, da man mehr wünscht,
   als die Losung vergibt).

Wichtige fachliche Klärung (Auftraggeber): **Winter ist ein MINDEST-Wert pro
Anteil** (20 Tage gelten auf den vollen Anteil; bei Tandems anteilig weniger; kein
Maximum), **Wochenenden sind ein HÖCHST-Wert** (Annäherung warnt).

## Entscheidung

**a) Wochenend-Richtwert (Höchstwert).** Neues Feld
`BookingPolicy.max_weekends_per_year` (Default 9). Reine Logik
`availability.weekend_keys` zählt **Fr-/Sa-Nächte** je Wochenende einmal; Service
`services.weekend_usage(member)` liefert `booked/target` plus `near`
(≥ Ziel − 1) und `over` (≥ Ziel). Anzeige auf **Übersicht** (Chip, warnt bei
`near`) und **Buchen** (Zeile). Der Winter-Wert wird konsistent als **Mindestwert
pro vollem Anteil** dargestellt und in `services.winter_usage` mit dem Tage-Budget
skaliert (`guideline · budget / 50`, Default 20) – Framing „mindestens", kein
Maximum.

**b) Personenzahl außerhalb des Rahmens (konfigurierbar, angezeigt).** Feld
`BookingPolicy.allow_undersized_units` (Default **an**). Ist es aktiv, darf eine
Unterkunft für eine Personenzahl **außerhalb** ihres ausgelegten Rahmens gebucht
werden – **mehr ODER weniger** (z. B. wenn nichts Passendes mehr frei ist).
Durchgesetzt in `book_spontaneous`, `adjust_allocation`, `free_quarters_for` und
`Allocation.clean` (Backend). Im UI **deutlich markiert**: Badge „kleiner als eure
Gruppe · Platz für N" (zu viele) bzw. „größer als nötig · für M–N Pers." (zu wenige)
in der Buchen-Liste, passender Warnhinweis im Bestätigungsschritt. **Harte Kopplung
„alles andere belegt" (Anschluss-Wunsch):** Eine Unterkunft außerhalb des Rahmens ist
**nur dann** buchbar, wenn **keine passende** (für die Personenzahl ausgelegte) freie
Unterkunft mehr existiert (`services.has_fitting_free_quarter`); solange eine passende
frei ist, wird die Buchung **gesperrt** und darauf verwiesen. (`Allocation.clean` im
Backend prüft nur den Schalter – Admins können bewusst zuordnen.) **Gruppen-Schwelle**
`group_min_persons` von 3 auf **6** angehoben (Anschluss-Wunsch).

**c) Hilfe-Werte aus der Konfiguration.** Service
`services.booking_policy_summary()` bündelt die Backend-Werte (Mindestnächte,
Vorlauf, Gruppe-ab, Winter/Wochenende, plus die aus aktiven Saison-Regeln/
Schulferien abgeleiteten Eckwerte: strengste Saison-Mindestnächte, Parallel-Limit,
Aufenthaltsdeckel). Die Hilfeseite rendert diese Werte (`{{ p.* }}`), der Satz
„Die genauen Werte stellt die Verwaltung im Backend ein" entfällt.

**d) Regel-Transparenz für Wünsche/Losung.** Neuer Hilfe-Abschnitt
„Welche Buchungsregeln gelten für Wünsche & Auslosung?" (Anker `#regeln-losung`):
- **beim Eintragen/Einreichen**: Mindestnächte + Einzel-Aufenthaltsdeckel,
- **erst in der Losung**: Parallel-Limit + Deckel über mehrere Buchungen
  (überschreitende Wünsche werden **übersprungen** – kein Verlust/kein Karma),
- **nur Spontanbuchung** (nicht Wünsche/Losung): Vorlauf, Lückenfüllung,
  Winter-/Wochenend-Richtwerte, „kleiner buchen",
- **mehr wünschen als erfüllt wird ist legitim** (auch mehr Wochenenden).
Auf der **Wunschliste** steht dazu ein kurzer Hinweis und – sobald Wünsche
eingetragen sind – die Zahl der **gewünschten Wochenenden**
(`services.wish_weekend_usage`) mit der Klarstellung, dass Über-Wünschen erlaubt ist.

**+ Gemeinschafts-Spiegel.** Der Quartals-Auslastungsgraph wurde **lesbarer**
gemacht (größere `viewBox 0 0 360 160`, deutliche Q1–Q4-Beschriftung, Randwerte
links/rechts ausgerichtet statt über der Achse) und der aufklappbare Detail-Block
zeigt nun **alle Monate des Kalenderjahres** (`services._year_months_occupancy`)
statt nur aktueller + kommender Monat.

## Konsequenzen

**Positiv** – Winter (Mindest, pro Anteil) und Wochenende (Höchst) sind klar
unterscheidbar und steuern sanft; in Engpässen lässt sich eine kleinere Unterkunft
buchen, ohne dass die Größenregel ganz fällt; die Hilfe zeigt die echten Werte und
erklärt präzise, wo Regeln greifen vs. nur Hinweis sind. Wenige zusätzliche
DB-Abfragen (Singleton + kleine Tabellen; Wochenend-/Winter-Zählung je eine Query).

**Grenzen / bewusst** – `allow_undersized_units` ist **standardmäßig an** (vom
Auftraggeber gewünscht); der strikte Modus bleibt per Schalter erhalten und ist in
den Tests explizit abgedeckt. Die „nur falls nichts frei"-Bedingung ist über die
Anzeige-Reihung gelöst, nicht hart erzwungen (eine harte Sperre wäre verwirrender).
Der Wochenend-Höchstwert ist Orientierung, **keine** Buchungssperre.
