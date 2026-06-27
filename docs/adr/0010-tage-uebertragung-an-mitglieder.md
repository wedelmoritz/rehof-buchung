# 0010 – Tage-Übertragung an andere Mitglieder

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 11 – Tage-Übertragung](../FACHKONZEPT.md#11-tage-übertragung).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Das jährliche Tage-Kontingent (kein Übertrag ins Folgejahr) ist eine fachliche
Vorgabe (Regelwerte: Fachkonzept § 1/§ 11). In der Praxis nutzt aber nicht jedes
Mitglied sein Kontingent aus, während andere mehr bräuchten. Eine Weitergabe unter
Mitgliedern war **nicht** Teil der Buchungsregeln, ist aber ein naheliegender Wunsch.

## Entscheidung

Wir führen die **Übertragung von Nächten an andere Mitglieder** als eigenständiges
Feature ein – bewusst als **Entscheidung des Projekts**, nicht als Umsetzung einer
Vorgabe.

- Modell `booking/models.py:NightTransfer` hält Geber, Empfänger und Anzahl Nächte.
- Ablauf zweistufig im Service/View (`booking/views.py:transfer`): Vorschau mit
  Empfänger-Anzeige und Disclaimer, dass die **Basis des Übertrags privatrechtlich**
  zwischen den Beteiligten zu regeln ist, dann „verbindlich übertragen“.
- Die Übertragung bewegt Nächte **innerhalb desselben Kalenderjahres** – sie
  unterläuft die fachliche Vorgabe „kein Übertrag ins Folgejahr“ nicht
  (Regelwerte: Fachkonzept § 11).

## Betrachtete Alternativen

- **Keine Übertragung:** ungenutzte Kontingente verfallen, obwohl Bedarf bestünde.
- **Automatischer Pool/Marktplatz:** zu komplex und potenziell konfliktträchtig;
  die direkte, einvernehmliche Übertragung ist einfacher und transparenter.

## Konsequenzen

**Positiv**
- Ungenutzte Tage kommen der Gemeinschaft zugute.
- Klare, nachvollziehbare Übertragung mit ausdrücklichem Disclaimer.

**Negativ**
- Die rechtliche/finanzielle Basis liegt außerhalb der App (privatrechtlich) – die
  App dokumentiert nur die Mengen-Übertragung.
- Zusätzliche Buchführung über `NightTransfer` bei der Budget-Berechnung.
