# 0038 – Zahlungsanbindung: Anzahlung und Storno-Erstattung

## Status

Proposed (2026-06-26) – Teil-Funktionen offen; baut auf ADR 0017 (Mollie) auf

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 13 – Rechnungen, Zahlung & Steuer](../FACHKONZEPT.md#13-rechnungen-zahlung--steuer)
> (Anzahlung/Storno-Erstattung). Diese ADR hält die *technische* Entscheidung und
> ihre Abwägungen fest; die Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Die Online-Bezahlung einer **vollständigen `Invoice`** ist umgesetzt und produktiv
nutzbar (ADR 0017: `shop/payments.py` `start_payment`/`settle_payment`, Sandbox-
Default, Webhook/Rückkehr, idempotent). Für externe Gäste (ADR 0023) sieht die
`ExternalConfig` aber zwei weitergehende Geldflüsse vor, die **noch nicht über den
Zahlungsanbieter automatisiert** sind:

- **Anzahlung** (`deposit_percent`, `ExternalConfig.deposit_for`): wird im Angebot
  (`services.external_quote` → `deposit_gross`) und in der Bestätigungs-E-Mail nur
  **informativ** ausgewiesen („bitte zuerst überweisen"). Es gibt **keine** separate
  Online-Teilzahlung der Anzahlung mit anschließender Restzahlung.
- **Storno-Erstattung** (`booking/external.py:cancellation_refund`,
  `services.external_cancellation_preview`): die Erstattungs-Staffel wird **berechnet
  und angezeigt**; `services.cancel_external_booking` gibt die Aufschlüsselung
  zurück, löst aber **keinen** Provider-Refund aus. `shop/mollie_api.py` kennt nur
  `create_payment`/`payment_status` – **keine** Refund-Funktion. Rückerstattungen
  erfolgen heute **manuell** (Überweisung durch die Verwaltung).

## Entscheidung

Wir halten den offenen Umfang fest und legen die Ausbaurichtung fest (Umsetzung
folgt als eigener Change):

1. **Anzahlung online:** Beim verbindlichen Buchen eine `Payment` über den
   **Anzahlungsbetrag** (`deposit_gross`) statt des Gesamtbetrags starten
   (`start_payment(..., amount=deposit_gross)` ist bereits parametrisierbar). Die
   `Invoice` bleibt offen über den Restbetrag; Status erst „bestätigt", wenn der
   Rest beglichen ist. Modell `shop.Payment` trägt schon einen frei wählbaren
   `amount` – die Naht ist vorhanden.
2. **Storno-Erstattung automatisiert:** `shop/mollie_api.py` um `create_refund`
   erweitern; `shop/payments.py` bekommt ein `refund_payment(payment, amount)` als
   **eine Naht** (Sandbox simuliert, echter Mollie-Refund mit Key). `cancel_*` ruft
   sie mit dem berechneten Erstattungsbetrag auf und protokolliert den Refund an
   `Payment`/`Invoice`.
3. **Idempotenz & Sicherheit** wie bei `settle_payment`: Zeilensperre, kein
   Doppel-Refund, Benachrichtigung an Gast/Mitglied.

Bis dahin bleiben **Anzahlung informativ** und **Erstattung manuell** – bewusst, da
beide echte Geldflüsse sind und eine sorgfältige (auch buchhalterische) Umsetzung
inkl. Tests gegen die Mollie-Testumgebung brauchen.

## Betrachtete Alternativen

- **Sofort vollständig umsetzen:** mehr Risiko (echte Geldflüsse, Refund-Edge-Cases,
  Teilzahlungs-Buchhaltung) – zunächst als ADR festgehalten und separat umzusetzen.
- **Nur Vorkasse/Überweisung, keine Online-Anzahlung/-Erstattung:** einfacher, aber
  schlechtere Gäste-Erfahrung und mehr manuelle Verwaltungsarbeit.
- **Externer Zahlungsdienstleister mit eigener Storno-/Anzahlungslogik:** zusätzliche
  Abhängigkeit; Mollie deckt Refunds/Teilzahlungen über dieselbe Naht bereits ab.

## Konsequenzen

**Positiv**
- Der offene Umfang ist klar benannt und die Ausbaurichtung steht (Nähte vorhanden:
  `Payment.amount`, `start_payment(amount=…)`).
- Kein stiller Halbzustand: Anzahlung/Erstattung sind heute eindeutig als manuell
  dokumentiert (UI weist sie informativ aus).

**Negativ**
- Bis zur Umsetzung **manueller Aufwand** (Erstattung überweisen, Anzahlung/​Rest
  nachhalten) und entsprechendes Fehlerrisiko.
- Echte Geldflüsse erfordern sorgfältige Tests (Mollie-Testumgebung) und ggf.
  buchhalterische Abstimmung, bevor der Status auf „Accepted" gehoben wird.
