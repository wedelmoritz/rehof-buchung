# 0010 – Tage-Übertragung an andere Mitglieder

## Status

Accepted (2026-06-26)

## Kontext

Das jährliche Tage-Kontingent (50 Nächte, kein Übertrag ins Folgejahr) ist eine
Vorgabe der Genossenschaft (siehe ADR 0009). In der Praxis nutzt aber nicht jedes
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
  unterläuft die Vorgabe „kein Übertrag ins Folgejahr“ aus ADR 0009 nicht.

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
