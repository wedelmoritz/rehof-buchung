# 0080 – Wunsch-Frist sichtbar machen + zweistufige Erinnerung vor der Auslosung

## Status

Accepted (2026-07-01)

## Kontext

Die Auslosung vergibt die begehrten Zeiten des Folgejahres; nur **eingereichte**
Wünsche nehmen teil (ADR 0062/0073). Bislang war für Mitglieder aber **nicht klar
sichtbar**, bis wann sie ihre Wünsche einreichen müssen, und es gab **keine aktive
Erinnerung**. Wer den Termin verpasste oder nur einen Entwurf liegen hatte, fiel
still aus der Losung – vermeidbar und unfair gegenüber den Aufmerksamen.

## Entscheidung

**Frist konkret anzeigen und zweistufig automatisiert erinnern.**

1. **Einheitliche Frist** (`BookingPeriod.submission_deadline`): der letzte Tag zum
   Einreichen = `wishlist_close` (dann schließt das Wunsch-Fenster), sonst der Tag
   des Losdatums `draw_at`. Eine Property, damit Anzeige und Erinnerung **dieselbe**
   Frist verwenden.

2. **Sichtbar auf der Übersicht** (`overview`): Der Los-Chip nennt jetzt die Frist
   („Einreichen bis TT.MM.JJJJ"). Hat **dieses** Mitglied noch **nichts eingereicht**,
   erscheint stattdessen ein **Warn-Chip** („⚠️ Noch keine Wünsche eingereicht · bis …").
   Auf der **Wunschliste** steht ein Fristen-Banner (Einreichen bis · Ziehung), das
   klar sagt, ob schon etwas im Lostopf ist.

3. **Zweistufige Erinnerung** (`services.send_wish_reminders`, Kommando
   `send_wish_reminders`, im `run_scheduler` täglich): erinnert **nur** buchungs-
   berechtigte Mitglieder (nicht extern, mit Tage-Anteil, aktives Login), die **noch
   keinen Wunsch eingereicht** haben (gar keinen **oder** nur einen Entwurf) –
   **In-App** (löst zugleich Web-Push aus) **und** E-Mail (Opt-in). Die zweite Stufe
   ist dringlicher formuliert („Letzte Erinnerung").

4. **Konfigurierbar** (`BookingPolicy.wish_reminder_lead1/lead2`, Default **7** und
   **2** Tage vor der Frist; je **0 = Stufe aus**). Gewählt: 7 Tage (genug Vorlauf,
   Wochenende inklusive) + 2 Tage (dringlicher Schluss-Spurt; 1 Tag wäre für viele zu
   knapp zum Reagieren).

5. **Idempotent**: Jede Stufe wird **genau einmal je Periode** versendet
   (`BookingPeriod.wish_reminder1_at/2_at`). Stufe 1 feuert im Fenster
   `[Frist−lead1, Frist−lead2)`, Stufe 2 in `[Frist−lead2, Frist)` – so überlappen
   sie nicht und niemand bekommt am selben Tag zwei Mails. Wer zwischen den Stufen
   einreicht, fällt aus der zweiten Runde heraus.

## Betrachtete Alternativen

- **Nur eine Erinnerung**: reicht erfahrungsgemäß nicht – eine frühe (Planung) und
  eine späte (Schluss-Spurt) erreichen mehr Leute → zweistufig.
- **Fest verdrahtete Fristen**: die Vorlaufzeiten sind eine Betriebsentscheidung →
  konfigurierbar (mit sinnvollen Defaults), abschaltbar je Stufe.
- **Auch Einreichende erinnern**: unnötiges Rauschen → nur wer noch nichts im Lostopf
  hat.

## Konsequenzen

**Positiv** – niemand verpasst die Losung aus Unwissenheit; die Frist ist überall
präsent (Übersicht, Wunschliste, aktive Erinnerung über alle Kanäle). Effizient:
eine Mitglieder-Abfrage + eine Menge der bereits Eingereichten; der Versand läuft
über die bestehende Outbox/Push-Naht. Neue Migration (2 Perioden-Zeitstempel + 2
Policy-Felder).

**Grenzen** – die Erinnerung setzt einen gesetzten Termin voraus (`wishlist_close`
oder `draw_at`); ohne Termin gibt es keine Frist und keine Erinnerung. Der Versand
hängt am täglichen Scheduler-Lauf – ein längerer Ausfall über beide Fenster hinweg
könnte eine Stufe verpassen (die jeweils andere Stufe bzw. die Anzeige greifen
weiterhin).
