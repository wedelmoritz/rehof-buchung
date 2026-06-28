# 0063 – Gemeinschafts-Spiegel & Karma-Transparenz

## Status

Accepted (2026-06-28)

## Kontext

Das Losverfahren ist fair und (seit ADR 0062) verifizierbar, aber die wirkenden
Größen waren bislang **unsichtbar**: Mitglieder sahen weder die Gesamt-Auslastung,
noch die Ergebnis-Quote der Auslosungen, noch das eigene/aggregierte **Karma**
(`Member.factor`). Transparenz über diese Aggregate stärkt Vertrauen und
Gemeinschaftsgefühl – ohne individuelle Buchungsmuster bloßzustellen.

## Entscheidung

Zwei schlanke, **rein lesende** Transparenz-Bausteine:

1. **Gemeinschafts-Spiegel** (`/gemeinschaft/`, login-pflichtig, View `community`):
   aggregierte Kennzahlen über `services.community_stats` – **Auslastung** (aktueller
   + kommender Monat), **Ergebnis-Historie** der letzten Verlosungen (Anteil erfüllter
   Wünsche je Jahrgang) und die **anonyme Karma-Verteilung** (`karma_distribution`,
   Buckets 1,0–1,5). Darstellung über **CSS-Balken** (Inline-Breiten) – kein JS, kein
   SVG-Geometrie-Aufwand, CSP-konform.

2. **Karma-Transparenz im Profil**: eine Karte zeigt den **eigenen** Ausgleichsfaktor
   (`member.factor`, bereits im Kontext) samt Erklärung (1,0 Normalstand, +0,1 nach
   Verlust, Deckel 1,5, Reset nach umkämpftem Gewinn) und verlinkt Fairness-Nachweis +
   Gemeinschafts-Spiegel.

**Navigation:** ein neuer Sekundär-Eintrag „Gemeinschaft" (Seitenleiste + mobiles
Sheet, eigenes Sprite-Icon) – die Haupt-Tabs bleiben unangetastet (nicht überfrachten).

## Datenschutz & Effizienz

- **Nur Aggregate / k-anonym:** keine Namen, keine Einzel-Buchungen. Der eigene Faktor
  ist nur für das Mitglied selbst sichtbar (Profil).
- **Wenige DB-Abfragen:** `community_stats` ≈ eine Handvoll Aggregat-Queries
  (2× Monats-Auslastung, letzte Losungen, Karma in EINER Query, Count). Dedizierte
  Seite, nicht der heiße Übersichts-Pfad.

## Betrachtete Alternativen

- **Karma-Verlaufshistorie je Mitglied:** das Modell speichert nur den aktuellen
  Faktor (kein Änderungs-Log). Bewusst NICHT nachgerüstet (Datensparsamkeit/Aufwand);
  der aktuelle Stand + Erklärung genügt für Transparenz.
- **Öffentliche Rangliste/Bestenliste:** verworfen – in einer kleinen Genossenschaft
  fördert das Wettbewerb/Neid und legt Verhalten offen (Anti-Pattern, s. Recherche).
- **SVG-Charts wie beim Fairness-Nachweis:** für simple Balken überdimensioniert;
  CSS-Balken sind schlanker und genauso CSP-konform.

## Konsequenzen

**Positiv** – sichtbare Fairness/Auslastung stärkt Vertrauen; baut auf vorhandenen
Aggregaten auf; schlank und ohne neue Abhängigkeit.

**Negativ / Grenzen** – kein Zeitverlauf des eigenen Karmas (nur Momentaufnahme);
die Auslastungs-Kennzahl ist eine grobe Monats-Quote (gewollt einfach).
