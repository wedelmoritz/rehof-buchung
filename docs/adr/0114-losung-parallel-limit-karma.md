# 0114 – Losung: Basis-Parallel-Limit je Mitglied + Karma-Entschärfung

## Status

Accepted (2026-07-28) · härtet das Losverfahren aus
[ADR 0009](0009-saison-regeln-losung.md) (Saison-Regeln in der Losung) und die
Karma-Regel der Spezifikation 3.3. **Umgesetzt (2026-07)** – Ergebnis einer
gezielten Strategiesicherheits-Prüfung („bringen viele Wünsche für denselben
Zeitraum einen Vorteil?").

## Kontext

Frage aus der Genossenschaft: **Steigt die Chance eines Mitglieds, wenn es mehrere
– am besten sehr viele – Wünsche für denselben Zeitraum einträgt?**

Empirische Prüfung per Monte-Carlo (reines `booking.lottery`, 4000 Läufe je Fall):

* **Gewinn*chance* auf einen Zeitraum: NEIN.** Ob ein Mitglied 1 Wunsch, 5 exakte
  Duplikate oder zwei gleichwertige Quartiere derselben Woche listet – die
  Wahrscheinlichkeit, *mindestens eine* Einheit im Zeitraum zu bekommen, ist
  identisch (0,498). Grund: Die gewichtete RSD zieht **ein Los-Ticket je Partei**
  (nicht je Wunsch), und die Ausweich-Logik scannt ohnehin die **ganze
  Äquivalenzklasse**. Das ist die strategiesichere Kern-Eigenschaft, deterministisch
  getestet (`test_strategieproof_*`).
* **Aber zwei echte, verwandte Lücken:**
  1. **Monopolisierung mehrerer Einheiten im selben Zeitraum.** Wer mehrere
     gleichwertige Einheiten *derselben Woche* listet, konnte sie **gleichzeitig
     gewinnen** (Ø 2,0 statt 1,0 Einheiten) – zu Lasten anderer. Der vorhandene
     Schutz `SeasonRule.max_parallel_units` greift **nur**, wenn eine Saison-Regel
     den Zeitraum abdeckt; außerhalb konfigurierter Saisons gab es in der Losung
     **keine** Obergrenze gleichzeitiger Einheiten.
  2. **Karma-Farming.** Ein aussichtsloser Zusatzwunsch auf einen heißen Slot
     brachte **+0,1 Karma** fürs Folgejahr – auch wenn das Mitglied den Slot gar
     nicht wollte und die Woche längst anderweitig gewonnen hatte.

## Entscheidung

**1. Basis-Parallel-Limit PRO MITGLIED (Default 1, konfigurierbar).** In der Losung
gewinnt ein einzelnes Mitglied pro *überlappender Nacht* höchstens
`BookingPolicy.lottery_max_parallel_units` Einheiten (Default **1**, `0` =
unbegrenzt). Reine Logik: neuer Parameter `max_parallel_per_party` in
`lottery.run_lottery` (+ `simulate_win_probabilities`), der die je Partei bereits
zugeteilten Zeiträume nachtweise zählt und einen Wunsch, der den Deckel
überschreiten würde, **terminal überspringt** (`parallel_skip`) – **kein Verlust,
kein Karma**, wie ein Budget-Übersprung. Damit:

* werden mehrere Wünsche fürs selbe Fenster zu **reinen Ausweich-Alternativen** (nur
  einer gewinnt) – die Chance steigt nicht, die Monopolisierung ist ausgeschlossen;
* bleibt die **ehrliche Alternativ-Angabe** über verschiedene Äquivalenzklassen
  erlaubt und sinnvoll (man darf viele akzeptable Optionen listen – man gewinnt nur
  eine).

Bewusst **pro Mitglied/Login** (nicht pro Anteil): ein Tandem-Paar (zwei Konten)
kann je eine Einheit gewinnen. Ergänzt – nicht ersetzt – die per-Anteil wirkende
Saison-Regel `max_parallel_units` (ADR 0009); die strengere Regel gewinnt.

**2. Karma-Entschärfung.** Ein echter Verlust zählt **nur dann fürs Karma**, wenn
das Mitglied im *überlappenden* Zeitraum nicht ohnehin schon eine Zuteilung hat. So
kann ein aussichtsloser Zweitwunsch fürs selbe Fenster keinen Karma-Schritt „farmen";
**ehrliche Verlierer** (ohne Zuteilung im Fenster) behalten ihren Bonus. Das
Log-Feld `karma_counted` macht es nachvollziehbar.

## Konsequenzen

* **Wirkt konsistent** in der echten Losung (`run_period_lottery`), in der
  **Chancen-Prognose** und der **Verifikations-Wiederholung** (`verify_period_lottery`)
  – alle reichen den Policy-Wert durch, damit angezeigte und gezogene Ergebnisse
  übereinstimmen.
* **Rückwärtskompatibel abschaltbar:** `lottery_max_parallel_units = 0` stellt das
  frühere Verhalten wieder her; ein höherer Wert erlaubt gezielt mehr (z. B. große
  Anteile).
* **Wirkt auch über verschiedene Äquivalenzklassen:** Das Limit zählt die je Partei
  im Lauf zugeteilten Zeiträume **klassenübergreifend**. Wer für dieselbe Woche
  Wünsche in *verschiedenen* Kategorien listet (z. B. Klasse A **und** Klasse B),
  gewinnt daher ebenfalls nur **eine** Einheit – der zweite Treffer wird
  `parallel_skip`t (verifiziert: mit freier Kapazität 1 statt 2 Einheiten). Das ist
  **kein Widerspruch** zu „mehr Chance durch mehrere Klassen": Solche Wünsche sind
  echte, gleich-akzeptable **Alternativen** („A *oder* B"), die die Chance auf
  *irgendeinen* Treffer legitim erhöhen (RSD-Eigenschaft „keine Verschwendung": keine
  gewollte Einheit bleibt leer), ohne dass jemand **mehrere** Einheiten monopolisiert
  oder ein zusätzliches Los-Ticket bekäme. Wer sich auf eine Kategorie festlegt, hat
  für genau diese engere Chancen – Ausdruck der eigenen (schmaleren) Präferenz, keine
  Benachteiligung. Empirisch bestätigt (Monte-Carlo) und in `tests/test_lottery.py`
  festgehalten.
* **Strategiesicherheit gewahrt:** Übersprünge sind terminal und karma-neutral (wie
  Budget-/Saison-Übersprünge). `test_strategieproof_*` bleibt grün.
* **Grenze:** Ein aussichtsloser Wunsch für einen *nicht* überlappenden Zeitraum, den
  das Mitglied gar nicht will, bringt weiterhin einen (einmaligen, gedeckelten)
  Karma-Schritt – das ist von einem echten Verlust nicht unterscheidbar und bewusst
  nicht „geschlossen" (sonst würden ehrliche Verlierer bestraft).

## Verworfene Alternative: Obergrenze für die Zahl der Klassen je Fenster

Aufgeworfen wurde: Wer für dieselbe Woche in **allen** Äquivalenzklassen wünscht,
priorisiert sie und bekommt **mit hoher Wahrscheinlichkeit eine** davon – ist das
gewollt? Sollte man die Zahl der Klassen je Fenster begrenzen (z. B. auf 3)?

Per Monte-Carlo geprüft (reale Struktur: **4 Klassen** mit Kapazitäten [3,2,3,2] =
10 Einheiten, umkämpfte Woche mit 16 Parteien):

* **Der Vorteil ist real:** ein „Blanket"-Mitglied (alle 4 Klassen) gewinnt mit
  **0,93** gegenüber **0,58** für unflexible Mitglieder (nur 1 Klasse).
* **Eine Grenze von 3 ist praktisch wirkungslos:** sie senkt den Vorteil nur von
  **0,92 → 0,87** (bei 4 Klassen ist „3“ fast so gut wie „4“); die unflexiblen
  Mitglieder profitieren **nicht** (0,571 → 0,572). Erst eine Grenze von **1** gleicht
  die Chancen an (0,586 ≈ 0,582).
* **Eine wirksame Grenze (1–2) zerstört „keine Verschwendung“:** dann bleiben
  **gewollte Einheiten leer, während Mitglieder leer ausgehen** (im Test steigt der
  Leerstand von 0,00 auf 0,69 Einheiten). Das Losverfahren verlöre seine
  Effizienz-Eigenschaft.
* **Flexibilität ist netto pro-sozial:** Geht M0 von 1 → 4 Klassen, sinkt die
  Feld-Gewinnrate nur **0,581 → 0,570** (−1 Pp, diffus) – weil M0 durch das
  Parallel-Limit **trotzdem nur eine** Einheit nimmt –, während die **Gesamtauslastung
  steigt** (9,30 → 9,48 vergeben). Wären alle gleich flexibel, ist es **perfekt fair**
  (jeder 0,625, 0 Leerstand). Das „Problem“ ist nicht Flexibilität, sondern die
  **Ungleichheit** flexibel/unflexibel – bei jeder effizienten, präferenz-treuen
  Vergabe unvermeidlich.

**Entscheidung: keine Klassen-Grenze.** Der Rest-Vorteil wird bereits abgefedert durch
**Karma** (der unflexible Verlierer sammelt +Faktor über die Jahre, der Gewinner setzt
bei umkämpftem Gewinn auf 1,0 zurück), das **Wunsch-Budget** (nur die halben
Jahres-Tage → auch ein Blanket-Mitglied gewinnt nur wenige Wochen/Jahr) und die
**Belegung** (Klassen unterscheiden sich in der Personenzahl; eine ehrliche kleine
Partei „passt“ real nur in wenige Klassen, ein zu großer Losgewinn fällt beim Buchen
unter die „kleiner-buchen“-Regel). Falls die Delegation es politisch dennoch will,
ließe sich eine **konfigurierbare** Grenze (Default aus) später ergänzen – die
Simulation zeigt aber, dass sie bei 4 Klassen wenig bewirkt.

## Tests

Reine Logik (`tests/test_lottery.py`): Duplikate/gleichwertige Wünsche fürs selbe
Fenster → genau eine Zuteilung; Parallel-Limit abschaltbar/konfigurierbar; nicht
überlappende Wünsche unberührt; Karma-Farming (überlappender Zweitwunsch) bringt kein
Karma; ehrlicher Verlust behält Karma; verschiedene Klassen fürs selbe Fenster →
höhere Trefferchance, aber Ø ≤ 1 Einheit; `test_strategieproof_*` grün. Integration
(`booking/tests_usecases.py`): `lottery_max_parallel_units` wirkt end-to-end über
`run_period_lottery` (Default 1 → eine Zuteilung; 0 → mehrere).
