# 0069 – Identitäts-Modell: Benutzer · Mitglied · Mitglieds-Anteil

## Status

Accepted (2026-06-29)

> Hält das geprüfte Modell und zwei bewusste Entscheidungen fest. Verfeinert
> ADR 0056 (Onboarding) und 0068 (Auto-Voll-Anteil). Baut auf 0066 (Regeln je Anteil).

## Kontext

Geprüft wurde, ob sich die drei Ebenen sauber zuordnen lassen und ob die Verwaltung
das **einfach und nachvollziehbar** bedienen kann:

- **Benutzer** (`User`) = ein **Login** (Anmeldedaten).
- **Mitglied** (`Member`) = die **Buchungs-Partei**: Wünsche, Buchungen, Tage-Budget,
  Karma, Rechnungs-/Profildaten.
- **Mitglieds-Anteil** (`Membership`) = ein **Genossenschafts-Anteil** (eine
  Vielleben-eG-Nummer) mit Jahres-Tagebudget (Standard **50 Tage**).

Verbunden: **Benutzer ↔ Mitglied** über `Member.user` (heute **1:1**); **Mitglied ↔
Anteil** über `Share` (n:m, mit festem Tage-Anteil je Zuordnung).

Was bereits geht (bestätigt):
- **Benutzer → Mitglied** zuordnen (Onboarding/Benutzer-Formular, ADR 0056/0068).
- **Mitglied → Anteil**: **voll** (ein Mitglied = 50 Tage) **oder Tandem-Teil** (z. B.
  25 Tage; `Share.night_budget` < Gesamtbudget) – mehrere Mitglieder teilen einen Anteil.
- **Ein Mitglied → mehrere Tandem-Anteile** (mehrere `Share`s; das Budget ist die
  **Summe** der Tage-Anteile).

## Entscheidung

1. **Modell bleibt dreistufig** (Benutzer · Mitglied · Anteil). Es bildet
   Voll-Mitglied, Tandem (Teil-Anteil) und Mehrfach-Tandem korrekt ab.

2. **Mehrere Benutzer pro Mitglied: vorerst NICHT umgesetzt** (Benutzer↔Mitglied
   bleibt **1:1**). Der Wunsch – mehrere Logins teilen **ein** Mitglied (gleiche
   Wünsche/Buchungen, Mails an alle Adressen) – ist als **Roadmap-Punkt** vermerkt
   (Entkopplung Benutzer→Mitglied auf n:1 über ein Verknüpfungs-Modell, Migration der
   bestehenden 1:1-Zuordnungen). Wird später als eigener Schritt umgesetzt.

3. **Kein Tage-Deckel je Mitglied:** die Tage-Anteile mehrerer Tandems **summieren**
   sich weiterhin **unbegrenzt** (bewusst kein 50-Tage-Limit auf die Summe). Die
   Verwaltung steuert die Vergabe über die sichtbaren „vergeben / frei"-Anzeigen.

4. **UX/Verständlichkeit geschärft** (diese Änderung):
   - Mitglieds-Anteil-Liste zeigt **„X/50 vergeben · Y frei (für Tandem-Partner)"**
     (bzw. „voll" / „überbelegt").
   - Anteil-Formular erklärt Voll vs. Tandem mit konkretem Beispiel (25 + 25); die
     Nutzer-Tabelle heißt sinngemäß „Mitglieder & Tage-Anteil – ein Mitglied mit 50 =
     Voll, mehrere mit zusammen 50 = Tandem".
   - Geführtes Onboarding: „Neuen Anteil anlegen (Voll-Mitglied, 50 Tage)" steht
     **oben** (Normalfall), bestehende Anteile zeigen **„noch N frei (Tandem)"**, plus
     ein Hinweis „Voll = neuer Anteil, volle Tage; Tandem = bestehenden Anteil mit
     freiem Rest wählen und nur den Teil eintragen".
   - Das Benutzer-Formular zeigt weiterhin die zugeordneten Anteile (ADR 0068).

## Betrachtete Alternativen

- **Benutzer↔Mitglied sofort entkoppeln (n:1):** verschoben – Kern-/Auth-Umbau mit
  Migration und Datenschutz-Implikationen (mehrere Credentials auf dieselben Daten,
  Mails an mehrere Adressen); bewusst als eigener, sauber geplanter Schritt.
- **50-Tage-Deckel je Mitglied erzwingen:** verworfen – die Verwaltung soll die
  Aufteilung frei steuern; Transparenz über „frei/vergeben" genügt.

## Konsequenzen

**Positiv** – die Zuordnung Benutzer→Mitglied→Anteil (voll/Tandem/Mehrfach-Tandem)
ist bestätigt funktionsfähig und im Backend jetzt deutlich nachvollziehbarer (frei/
vergeben sichtbar, klare Beispiele). **Offen/Roadmap** – „mehrere Benutzer pro
Mitglied" (Mehrfach-Login mit Mails an alle) ist noch nicht möglich und als nächster
Schritt vorgemerkt. **Grenze** – ohne Deckel kann ein Mitglied rechnerisch mehr als
50 Tage aus mehreren Tandems summieren; das liegt bewusst in der Hand der Verwaltung.
