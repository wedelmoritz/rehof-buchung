# 0102 – Losergebnis-Rückblick im Gemeinschaftsspiegel

## Status

Proposed (2026-07-10) · nutzt [ADR 0003](0003-losverfahren-weighted-rsd.md) (Losverfahren),
[ADR 0004](0004-karma-ausgleichsfaktor.md) (Karma), [ADR 0008](0008-losung-review-workflow.md)
(Review-Workflow), [ADR 0062](0062-verifizierbare-auslosung-commit-reveal.md) (Commit-Reveal),
[ADR 0063](0063-gemeinschafts-spiegel-karma-transparenz.md) (Anonymität), [ADR 0095](0095-auslastungsgraph-html-balken.md)
(HTML/CSS-Diagramme) · Gegenstück zu [ADR 0101](0101-entzerrungsphase-vor-losung.md).
**Noch nicht umgesetzt.**

> **Fachlicher Bezug:** Losverfahren/Karma stehen im [Fachkonzept](../FACHKONZEPT.md);
> dieser ADR fügt eine **rückblickende, anonyme Auswertung** hinzu, keine neue Regel.

## Kontext

Nach der Ziehung liegt am `LotteryRun` bereits viel vor: `notices` (je Wunsch *warum*
bekommen/nicht), strukturierter `log`, `karma_snapshot` (Karma **vor** dem Lauf),
`n_allocations`/`n_losses`. Der Gemeinschaftsspiegel ([ADR 0063](0063-gemeinschafts-spiegel-karma-transparenz.md))
zeigt Auslastung/Karma, aber **keinen** Rückblick auf die **einzelne Losung**. Ziel:
anonyme, verständliche Transparenz – was war begehrt, wie ging es aus, wie wirkte das
Karma, was war konfliktfrei.

## Entscheidung

**Beim `confirm_lottery` einmalig** eine Rückblick-Zusammenfassung berechnen und als
**JSON am `LotteryRun`** ablegen (Precompute → Community-Reads = ein Row-Fetch, O(1)).
Anonyme Aggregate, **erst nach Bestätigung** (`confirmed=True`).

**Kennzahlen:**
- **Beliebteste Zeiträume/Quartiere** (meist-gewünscht/umkämpft) + Ausgang („1 von N
  Wünschen erfüllt", anonym).
- **Erfüllungsquote** gesamt · je **Äquivalenzklasse** · je **Zeit-Band** (Feiertage vs.
  normal).
- **Karma-Bewegung:** `karma_snapshot` (vorher) vs. nachher → Verteilungs-Verschiebung
  (Verlierer +Karma, Resets bei heißen Slots); nutzt `karma_distribution`.
- **„Leicht erfüllbar":** konfliktfreie Wünsche (ohne Ziehung erfüllt) vs. umkämpfte.
- **Volumen & Verteilung:** Wünsche **gesamt** (Lostopf) + **Median je Mitglied**;
  erfüllte Wünsche **absolut** + **Median je Mitglied** (Verteilungs-Fairness).
- **Verweise:** Fairness-Nachweis + Seed-Offenlegung ([ADR 0062](0062-verifizierbare-auslosung-commit-reveal.md)).

## Architektur / Sicherheit / Performanz

- **Reine Logik** (Django-frei): `lottery.summarize_run(result, karma_before, karma_after)`
  → strukturierter Dict, testbar.
- **Service** `lottery_retrospective(run)` baut aus `notices`/`log`/Snapshots; **einmal
  bei Bestätigung** (`transaction.on_commit`), Ergebnis in `LotteryRun.retrospective`
  (JSON). Community-View rendert nur.
- **Privacy/Security:** nur `confirmed=True`; **anonyme Aggregate** ([ADR 0063](0063-gemeinschafts-spiegel-karma-transparenz.md));
  keine Identität über das eigene Ergebnis hinaus; Seed-Offenlegung ohnehin erst
  nach der Ziehung ([ADR 0062](0062-verifizierbare-auslosung-commit-reveal.md)).
- **UI/UX:** neuer Abschnitt „Rückblick Losung <Jahr>" im Gemeinschaftsspiegel –
  Balken (Erfüllungsquote), Heat (beliebteste Zeiten), Karma-Shift, „leicht vs.
  umkämpft", Volumen/Median – **HTML/CSS** ([ADR 0095](0095-auslastungsgraph-html-balken.md)),
  kein JS, Theme-Tokens; login-pflichtig wie der Gemeinschaftsspiegel.

## Datenmodell (Umsetzungs-Skizze)

- `LotteryRun.retrospective` (JSONField, default `{}`) – bei Bestätigung befüllt.
- Keine weiteren Modelle nötig (baut auf vorhandenen `LotteryRun`-Feldern auf).

## Betrachtete Alternativen

- **Live berechnen bei jedem Community-Aufruf**: verworfen (unnötige Last; Ergebnis ist
  nach Bestätigung unveränderlich → Precompute).
- **Nicht-anonyme Detail-Auswertung**: verworfen (Persönlichkeitsschutz; die anonyme
  Aggregat-Sicht genügt dem Transparenz-Zweck).

## Konsequenzen

**Positiv** – verständliche, faire Transparenz nach der Losung; nutzt vorhandene
`LotteryRun`-Daten (geringer Aufwand); O(1)-Reads durch Precompute; stärkt Vertrauen
(zusammen mit Fairness-Nachweis/Commit-Reveal).

**Negativ / Grenzen** – der Rückblick ist so gut wie die gespeicherten `notices`/`log`
(bei Altläufen ohne diese Daten bleibt er leer – dokumentierte Grenze); anonyme Aggregate
können bei sehr kleinen Gruppen theoretisch Rückschlüsse zulassen → Kennzahlen bewusst
grob halten (keine Kleinstgruppen ausweisen).
