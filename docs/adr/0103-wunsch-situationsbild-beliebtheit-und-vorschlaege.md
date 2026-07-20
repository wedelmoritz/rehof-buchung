# 0103 – Wunsch-Situationsbild: Beliebtheit statt Rangliste, proaktive Vorschläge (Konzept)

## Status

**Proposed (2026-07)** · erweitert/ersetzt Teile von
[ADR 0101](0101-entzerrungsphase-vor-losung.md) (Entzerrungsphase, Heatmap, Vorschläge) ·
Wortwahl nach [ADR 0072](0072-positive-wortwahl-frontend.md) · Losregeln
[ADR 0003](0003-losverfahren-weighted-rsd.md)/[ADR 0009](0009-buchungsregeln-der-genossenschaft.md).
**Reines Konzept – noch nicht umgesetzt.**

## Kontext & Problem

Die Wunschliste zeigt aktuell (ADR 0101-Nachtrag) eine **Nachfrage-Heatmap** (Quartier ×
**Monat**, rohe Wunsch-Zahl) und **Ranglisten** der „beliebtesten Unterkünfte/Zeiträume".
Rückmeldung aus der Genossenschaft: Das gibt kein wirklich brauchbares Bild der
Wunschlage. Für eine Gemeinschaft, die knappe Ferienwohnungen für eine Periode verplant,
zählen **nicht** „was ist am beliebtesten" (eine Ranglisten-Frage, die den Blick auf die
umkämpften Dinge lenkt → Herding), sondern drei Handlungs-Fragen:

1. **Wo/wann ist noch etwas frei?** – damit ich einen Wunsch setze, der aufgeht.
2. **Wo kollidiert mein geplanter Wunsch, und was ist die nächste, weniger beliebte
   Alternative?** – proaktiv, **schon beim Eintragen** (heute erst danach).
3. **Ballen wir uns oder verteilen wir uns?** – ein geteiltes Lagebild, das zum
   Ausweichen anstupst.

**Recherche-Beleg (Best Practices):** Für Gruppen, die sich um knappe Zeit-/Raum-
Ressourcen abstimmen, liest sich eine **Dichte-Heatmap „wo ist frei/gefragt"** schneller
als jede Tabelle – und je größer die Gruppe, desto überlegener gegenüber Ranglisten
(When2meet-Prinzip). Fairness-kritische Systeme leben zudem von **Erklärbarkeit und
Nachvollziehbarkeit**; Nutzer misstrauen „KI, die Effizienz über Fairness stellt".

## Wortwahl (verbindlich, ADR 0072)

Die zugrunde liegende Größe ist **Nachfrage relativ zur vergebbaren Kapazität**
(fachlich „Konkurrenz/Knappheit"). Im **gesamten Frontend** wird sie **positiv** benannt –
niemals „Konflikt/umkämpft":

| Fachliche Größe (intern) | Frontend-Begriff | Bedeutung für Mitglieder |
|---|---|---|
| überzeichnet (Nachfrage ≫ Kapazität) | **sehr beliebt** | viele überschneidende Wünsche – bekommt nicht jede:r |
| Nachfrage ≈ Kapazität | **beliebt** | gefragt, aber machbar |
| Nachfrage < Kapazität | **etwas gefragt** | gute Chancen |
| keine Überschneidung | **frei** | so gut wie sicher |

„Sehr beliebt" trägt die Information „hier bestehen viele überschneidende Wünsche" – ohne
negative Färbung. Interne Namen (`contention`, `demand`) bleiben im Code; sichtbar wird
nur die positive Skala.

## Entscheidung (Konzept)

### Kernidee: Beliebtheit **relativ zur Kapazität**, auf **Wochen**-Ebene, am **Entscheidungspunkt**

Heute zählt die Heatmap **rohe** Wünsche je **Monat**. Das ist zu grob und irreführend:
ein Quartier 10× über 10 verschiedene Wochen gewünscht ist **frei**, 3× in **derselben**
Woche ist **sehr beliebt**. Die neue Größe:

> **Beliebtheit(Quartier, Zeitfenster)** = Zahl der **überschneidenden** Wünsche fürs
> selbe bzw. **gleichwertige** Quartier (Äquivalenzklasse), gemessen relativ zur
> vergebbaren Kapazität der Klasse in diesem Fenster.

Weil die Losung Ausweich-Quartiere derselben Äquivalenzklasse nutzt (ADR 0003), zählt
nicht ein einzelnes Quartier, sondern die **Klasse × Woche**: 3 gleichwertige Häuser mit
4 Wünschen in einer Woche = „beliebt" (machbar), 3 Häuser mit 12 Wünschen = „sehr
beliebt". Das ist die ehrliche Chance-Information.

### P0a – Beliebtheits-Signal im Eintrag-Kalender (statt roher Nachfrage)

Reine Logik `popularity_band(klasse, woche) → {key, label, tone}` mit obiger Skala.
Der **Eintrag-Kalender** färbt Tage/Wochen danach (die vorhandene Tages-Ampel wird von
„rohe Zahl" auf „Beliebtheit relativ zur Kapazität" umgestellt). So sieht man **beim
Auswählen** sofort, wie beliebt ein Zeitraum ist. Wochen-Granularität.

### P0b – Proaktive Vorschläge **beim** Eintragen

Sobald Zeitraum + Personenzahl gewählt sind, werden die Kandidaten **sofort** gerankt nach
**(Eignung × geringe Beliebtheit)** und ein kleiner Block **„💡 Empfohlen: hier hast du
die besten Chancen"** zeigt die passenden, am wenigsten gefragten Unterkünfte **zuerst** –
*bevor* verbindlich gesetzt wird. Ergänzend „gleiche Unterkunft, weniger beliebter
Zeitraum" schon bei der Auswahl (`wish_alternatives` **vorgezogen**, heute erst nach dem
Eintragen). Reuse des bestehenden `candidates`-Server-Renderings (data-ajax), **keine**
neue Client-Komplexität.

### P1a – „Wo ist noch frei?" statt Beliebtheits-Rangliste

Die Rangliste „beliebteste Unterkünfte/Zeiträume" wird **umgedreht**: eine positive,
umsetzbare Liste/Heatmap der **wenig gefragten** (Quartier × Woche)-Slots – „hier bekommst
du fast sicher etwas". Reine Logik `freest_slots(period, top) → [{quartier, woche, band}]`.
Das ist genau die Information, die die Gemeinschaft zum Verteilen braucht.

### P1b – Wochen-Beliebtheits-Heatmap **im** Eintrag-Kalender

Das Lagebild an den Entscheidungspunkt binden (When2meet: dort „malen", wo man hin will,
und die Beliebtheit in place sehen) statt auf einem separaten Reiter. Der Nachfrage-Reiter
bleibt für den Gesamtüberblick, verliert aber die Ranglisten zugunsten „wo ist frei".

### P2 – Entzerrungs-Barometer (Gemeinschaft)

Ein einziger, anonymer Community-Indikator, z. B. **„Anteil der Wünsche in sehr beliebten
Slots"** (0–100 %) mit kurzer Einordnung („je niedriger, desto besser verteilt"). Er sinkt,
während alle entzerren – leichtes, opt-in-transparentes Nudging ohne Namen.

## P2 – KI / natürlichsprachliche Eingabe: Aufwand & Server-Ressourcen

**Frage:** „Ich beschreibe frei, was ich will (‚ruhige Woche im Sommer mit den Kindern,
flexibel beim Haus'), das System schlägt sinnvolle Wünsche vor." Nur der **Parse-Schritt**
(Freitext → strukturierte Constraints) wäre KI; **entscheiden** tut weiterhin der
deterministische Optimierer (P0b). Drei Umsetzungswege, ehrlich nach Aufwand/Ressourcen:

### Weg A – Regelbasiert (Schlagwörter + Datums-Parser) — **empfohlen, falls überhaupt NL**
Deutsche Kurz-Eingaben mit Wörterbuch + Datums-Bibliothek parsen: Jahreszeiten/Feiertage
(„Sommer", „Pfingsten"), Personen/Kinder, „ruhig/barrierefrei", „flexibel". Keine KI.
- **Aufwand:** niedrig–mittel (ein Parser-Modul in der reinen Logik + Tests).
- **Server-Ressourcen:** **vernachlässigbar** – ein paar MB (Datums-Lib), Parse in
  **Millisekunden** auf der CPU. Keine neue Infrastruktur.
- **Reichweite:** deckt ~80 % realistischer Kurz-Eingaben ab; alles andere fällt sauber
  auf die normale Formular-Auswahl zurück.

### Weg B – Kleines **lokales** Sprachmodell (on-prem), nur zum Parsen
Ein 1–3-B-Parameter-Instruct-Modell (z. B. Llama 3.2 1B/3B, Qwen2.5 1.5B, Phi-3-mini)
via llama.cpp/Ollama auf dem VPS, Temperatur 0, Ausgabe als **striktes JSON**
(Constraints), das dem Mitglied **zur Bestätigung** gezeigt wird.
- **Aufwand:** **mittel–hoch** – eigener Dienst/Container, Prompt + JSON-Schema-Validierung
  + Guardrails/Fallback, Modell-Datei (~1–3 GB) ausrollen/pflegen, Monitoring, Tests.
- **Server-Ressourcen (der eigentliche Kostenpunkt):**
  - **RAM resident:** je nach Größe/Quantisierung (Q4) ~**1–4 GB** – dauerhaft belegt,
    zusätzlich zu web+PostgreSQL. Auf dem heutigen Ein-VPS-Setup (Docker: web + DB hinter
    Caddy) konkurriert das um Arbeitsspeicher → in der Regel **VPS vergrößern** oder ein
    **separates on-prem-Kästchen**.
  - **CPU-Latenz (kein GPU):** ~5–30 Token/s → eine kurze Extraktion (~50–100 Token)
    dauert **~2–10 Sekunden**. Für die **kleine Nutzungsmenge** (Dutzende Mitglieder,
    Wünsche über einige Wochen verteilt) ist der **Durchsatz** unkritisch – der
    **resident RAM** ist die reale Belastung, nicht die Rechenzeit.
  - **Determinismus:** auch bei Temp 0 nicht versions-stabil → Ergebnis immer **anzeigen +
    bestätigen** lassen, nie automatisch buchen.

### Weg C – Externe LLM-API — **abgelehnt**
PII-Abfluss (Wunsch-/Präferenzdaten), AV-Vertrag, Widerspruch zur Datensparsamkeit,
externe Abhängigkeit/Kosten/Latenz, Nicht-Determinismus. Verstößt gegen Security by Design.

**Empfehlung NL:** **niedrige Priorität.** Falls gewünscht, mit **Weg A** starten (billig,
sofort, kein neuer Betrieb). **Weg B** nur, wenn die Genossenschaft wirklich freie
Fließtext-Eingabe will **und** ~1–4 GB RAM + wenige Sekunden Latenz akzeptiert (idealerweise
größerer VPS / separates Gerät). In **keinem** Fall entscheidet die KI die Zuteilung – sie
schlägt nur strukturierte Constraints vor, der auditierbare Optimierer bleibt der Kern.

## Architektur (state of the art, ADR-konform)

- **Reine Logik (Django-frei, unit-getestet):** `popularity_band`, `freest_slots`,
  Vorschlags-Ranking (und ggf. der Regel-Parser) – deterministisch/erklärbar; passt in die
  bestehende `lottery`/`availability`/`rules`-Schicht. **Strategiesicherheit unberührt:**
  alles ist **Anzeige**; die RSD-Losung bleibt gleich → dem Vorschlag zu folgen ist genau
  das kooperative Verhalten, das der Mechanismus ohnehin belohnt (kein Gaming).
- **Service-Layer:** eine Wunsch-Abfrage, Aggregate O(#Wünsche), gecacht wie die Heatmap
  (Redis-aware, Invalidierung bei Wunsch-Änderung, ADR 0060).
- **Views/Templates:** server-gerendert, data-ajax-Progressive-Enhancement, CSP-treu –
  bestehendes Muster, kein neues Framework, kein Client-JS-Zuwachs.

## Security by Design

- **Datensparsamkeit:** alles nur **Aggregat-Beliebtheit** (keine Namen). „Wer will
  dasselbe" bleibt hinter dem bestehenden per-Kanal-Opt-in (ADR 0101 Batch 2).
- **Kein neuer PII-Abfluss, keine externen Calls** (NL nur lokal/regelbasiert).
- **Symmetrie:** alle sehen dieselben Aggregate → keine Informations-Asymmetrie, kein
  Vorteil durch Insider-Wissen.
- **Auditierbarkeit/Vertrauen:** deterministische, erklärbare Vorschläge – die Grundlage,
  auf der die Genossenschaft dem Verfahren vertraut (im Einklang mit commit-reveal/
  Strategiesicherheit, ADR 0062).

## Priorisierung (Wert vs. Aufwand)

| Prio | Änderung | Wert | Aufwand |
|---|---|---|---|
| **P0** | Beliebtheit relativ zur Kapazität (Kalender-Signal, Wochen) | Hoch | Mittel |
| **P0** | Proaktive Vorschläge beim Eintragen | Hoch | Mittel (Reuse) |
| **P1** | „Wo ist noch frei?" statt Beliebtheits-Rangliste | Hoch | Niedrig–Mittel |
| **P1** | Wochen-Beliebtheits-Heatmap im Eintrag-Kalender | Mittel–Hoch | Mittel |
| **P2** | Entzerrungs-Barometer (Community-Nudge) | Mittel | Niedrig–Mittel |
| **P2** | NL Weg A (regelbasiert) | Niedrig–Mittel | Niedrig |
| **P2** | NL Weg B (lokales kleines LLM) | Niedrig | Hoch (+RAM) |

**Empfehlung:** Mit **P0** starten (Signal von „beliebt (rohe Zahl)" auf „Beliebtheit
relativ zur Kapazität" + Vorschläge nach vorn ziehen). Dann **P1** (Heatmap/Listen
aktionsrelevant: „wo ist frei"). **KI/LLM bewusst zurückstellen** – der Nutzen kommt
deterministisch und schützt Fairness-Vertrauen + Datensparsamkeit.

## Konsequenzen

**Positiv:** Die Wunschliste beantwortet endlich die Handlungs-Fragen (wo ist frei, wohin
ausweichen) statt „was ist beliebt"; Entzerren wird proaktiv statt nachträglich; positive
Wortwahl bleibt; volle Auditierbarkeit, keine neue PII-/Cloud-Abhängigkeit.

**Negativ / offen:** P0 erfordert die genaue Kapazitäts-Definition je Äquivalenzklasse ×
Woche (Abstimmung der Bänder-Schwellen mit der BL). Die Umstellung der Tages-Ampel berührt
mehrere Templates. NL bleibt bewusst optional/zurückgestellt.
