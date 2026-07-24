# 0113 – Sicheres, selbst-optimierendes NL-Lexikon (human-gated, Phase 1)

## Status

**Proposed** (2026-07) · baut auf [ADR 0103](0103-wunsch-entzerrung-konzept.md) (NL-Konzept,
Weg-A rein regelbasiert), [ADR 0108](0108-nl-parser-regelbasiert-weg-a.md) (regelbasierter
Parser + Stammdaten-Injektion) auf · berührt [ADR 0043](0043-dsgvo-datensparsamkeit-aufbewahrung-loeschung.md)
(DSGVO), [ADR 0061](0061-sicherheits-haertungspaket.md) (Härtung), [ADR 0111](0111-effizienz-n1-hotpaths.md)
(Vorab-Daten). **Noch nicht umgesetzt** – Grundlage für die Batches NL-L1…L6.

## Kontext

Der NL-Parser (ADR 0108) ist bewusst **regelbasiert, deterministisch, auditierbar und
datenschutz-neutral** (nichts wird gespeichert). Wunsch: er soll aus den **Eingaben der
Nutzer:innen und deren anschließender Wahl** dazulernen (mehr Synonyme/Aliase erkennen,
Kandidaten besser reihen) – **ohne** die genannten Eigenschaften zu verlieren.

Naives „Selbst-Lernen" hat bekannte Risiken: **Rückkopplung/Positions-Bias** (der oben
gezeigte Vorschlag wird öfter geklickt → „lernt", er sei richtig), **Daten-Vergiftung**
(wenige/ein Nutzer verschieben Rankings), **Präzisionsverlust/Drift**, **Verlust von
Determinismus/Auditierbarkeit**, **Injection über gelernte Aliase** und – bei kleiner
Datenmenge – **Rauschen**. Zusätzlich ist jedes Speichern von Freitext-Eingaben je Person
**neue personenbezogene Verarbeitung** (DSGVO).

## Entscheidung

Wir bauen ein **human-gated, selbst-optimierendes Lexikon** mit zwei Paradigmenwechseln, die
jedes obige Risiko gezielt neutralisieren. **Phase 1 (dieser ADR)**: das System **schlägt
vor**, ein Mensch **bestätigt** – **kein Auto-Promote**. (Phase 2 – Auto-Promote nur für die
risikoärmste Klasse – bleibt einem späteren ADR vorbehalten.)

### 1) Lernen aus KORREKTUR, nicht aus Bestätigung
Gelernt wird nur, **wo der Parser danebenlag** – die Person hat den Vorschlag **überstimmt**
oder der Parser hat *nichts* verstanden und sie hat trotzdem etwas Konkretes gewählt.
Positionsdaten werden per **Inverse Propensity Scoring** entzerrt (Counterfactual/Unbiased
Learning-to-Rank). Das entfernt die Selbstverstärkung **strukturell**.

### 2) Der Parser modifiziert sich NIE selbst
Zur Laufzeit liest die reine Logik ein **unveränderliches, versioniertes Lexikon**, das wie
die Stammdaten **injiziert** wird (ADR 0108). Damit bleibt `booking/wish_nl.py` Django-frei,
**deterministisch und testbar**. Der Lerner erzeugt nur *Kandidaten*; „scharf schalten" heißt,
den aktiven Zeiger auf eine neue Version legen, **Rollback** = zurücklegen (Staged Rollout:
Shadow → Review → aktiv → Rollback).

### Was gelernt wird (bewusst eng)
- **(a) Quartier-/Klassen-Aliase** („Türmchen"→Turmzimmer) – mündet nur in einen bestehenden
  Bezug, kann **kein falsches Datum** erzeugen.
- **(b) Jahreszeit-Monats-Ranking** – **permutiert nur** die vorhandene Kandidatenliste,
  erfindet keinen Monat außerhalb der Saison.
- **(c) Synonym-Kandidaten** (barrierefrei/Dauer/Monats-Spitznamen) – **nur Vorschlag**,
  Mensch bestätigt.
- **NIE automatisch:** neue Datums-Semantik, feldübergreifende Logik – bleibt getesteter,
  hand-geschriebener Code.

### Pseudonymität statt Voll-Anonymität (Quorum-Kern)
Um zu verhindern, dass **ein** Vielschreiber den Parser kippt, zählt das Quorum
**verschiedene Personen** – dafür braucht es **Pseudonymisierung**, nicht Voll-Anonymität
(die einen Pro-Nutzer-Deckel unmöglich machte). Pseudonym = `HMAC(member_id, NL_LEARN_SALT)`
(unumkehrbar ohne Secret). Das Quorum zählt **verschiedene Pseudonyme**, **jedes höchstens
1 Stimme** → 500 Anfragen einer Person = **1 Stimme**. Weil buchungsfähige Konten von der
**Verwaltung** freigeschaltet werden, ist der Stimm-Pool **vorab geprüfte Mitglieder** (kein
Sybil).

## Architektur / Sicherheit / Performanz

**Proposer/Server-Trennung.** Runtime-Parser (aktiver Snapshot, injiziert) ↔ nächtlicher
**Lerner** (offline: Korrektur-Signal + IPS-Debias → robuste Aggregation → Kandidat → Shadow-
Eval) → **Review-Queue** (Mensch, 1-Klick) → aktiver Snapshot++ (versioniert, hash, Provenienz)
→ Rollback jederzeit.

**Risiko → Mechanismus (jede Zeile ist ein Batch-Baustein):**

| Risiko | Neutralisierung |
|---|---|
| Rückkopplung/Positions-Bias | nur Korrektur-Signal; IPS-Gewichtung |
| Daten-Vergiftung | Quorum **verschiedener Pseudonyme**, Deckel 1 Stimme/Pseudonym, Mindest-Support, Zeit-Stabilität über N Fenster, Exklusivität, getrimmt/Median |
| Präzisionsverlust/Drift | Golden-Regression-Set + Counterfactual-Replay (kein Promote bei Regression); nur bounded Änderungsklassen |
| Determinismus/Audit | Gelerntes = injizierte Daten, kein Code; Snapshot content-hash + Changelog + Provenienz |
| Injection über Aliase | Härtung **beim Übernehmen** (`strip_controls` + Allowlist + Längen/Zeichen), nur Token-Vergleich, Ambiguitäts-Sperre |
| Kleine Datenmenge | konservative Schwellen; Auto nur risikoärmste Klasse (erst Phase 2); Sub-Quorum → Mensch-Queue |
| Betrieb/Verantwortung | fast-automatische Pipeline + schlanke Admin-Review-Seite (Evidenz, 1-Klick, Rollback) |
| DSGVO | **Feature-Logging statt Rohtext-an-Person**: pseudonymisiert, normalisierte Tokens + Ergebnis-Delta, **aggregiert-und-verworfen**, kurze Retention, getrennt von Buchungs-/Identitätsdaten, Löschung Art. 17; **Opt-in-Flag** (Default aus) |

**Sicherheit by Design.** Alles hinter `OpsConfig.nl_learning_enabled` (Default **aus** – bis
zur Aktivierung wird nichts gesammelt); `NL_LEARN_SALT` per Env (rotierbar/scoped); reine
Logik bleibt gehärtet (kein eval/SSTI/ReDoS, Längenlimit); RBAC: Review nur Admin/Superuser.

**Performanz.** Logging = ein `on_commit`-Insert (Hot-Path unberührt); Lerner nachts/off-peak,
SQL-seitige Aggregation; Shadow-Replay über ein begrenztes Fenster mit Vorab-Daten (ADR 0111);
Lexikon wie Stammdaten einmal pro Parse geladen (cachebar).

## Betrachtete Alternativen

- **Approach A (nur Analytics + manuelle Regeln):** billiger, aber kein geschlossener Loop –
  verworfen zugunsten des vorschlags-getriebenen, aber weiterhin human-gated Wegs.
- **Approach C/D (ML-Modell / Online-Bandit):** hoher Aufwand, nicht-deterministisch, DSGVO auf
  Trainingsdaten, Betriebslast (RAM/CPU) – bei kleiner Datenmenge unverhältnismäßig; verworfen
  (vgl. ADR 0103, Weg B/C).
- **Auto-Promote in Phase 1:** verworfen – erst nach bewährter Pipeline (Phase 2) und nur für
  die risikoärmste Klasse (Aliase mit starkem Quorum + bestandener Shadow-Eval).

## Konsequenzen

**Positiv** – der Parser wird über die Zeit datengetrieben besser (v. a. Aliase), **ohne**
Determinismus/Auditierbarkeit/DSGVO preiszugeben; ein einzelner Vielschreiber kann ihn nicht
bewegen; jederzeit rückrollbar.

**Negativ / Grenzen** – Aufwand ~26–42 Dev-Tage (Phase 1); bei kleiner Datenmenge feuern
Vorschläge **selten** (bewusst – Quorum), der Nutzen ist real, aber inkrementell. Pseudonyme
sind DSGVO-technisch weiter personenbezogen (Art. 4(5)) – durch Aggregation/Trennung/kurze
Fristen aber verhältnismäßig. Umsetzung in Batches **NL-L1…L6**; nichts wird aktiv, bis das
Opt-in-Flag gesetzt ist.
