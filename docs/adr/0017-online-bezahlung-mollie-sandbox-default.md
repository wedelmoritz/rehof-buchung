# 0017 – Online-Bezahlung (Mollie) als eine Naht, Sandbox als Default

## Status

Accepted (2026-06-26)

## Kontext

Mitglieder (Hofladen-Rechnungen) und externe Gäste (Übernachtungen) sollen online
bezahlen können. Da beide eine `Invoice` haben (siehe ADR 0016), soll es **ein**
Bezahlsystem geben. Gleichzeitig muss die App ohne echten Zahlungsanbieter testbar
und vorführbar sein – und eine Fehlkonfiguration darf **niemals** dazu führen, dass
eine unbezahlte Rechnung als bezahlt gilt.

## Entscheidung

Online-Bezahlung auf **`Invoice`-Ebene** über **Mollie**, gekapselt als schmale Naht:

- **Naht** `shop/payments.py` (`start_payment`/`settle_payment`/`cancel_payment`,
  `payments_enabled`) – die echte Anbindung liegt dahinter in `shop/mollie_api.py`
  (nur mit Key aktiv). Modell `shop/models.py:Payment` (token-geschützte,
  login-freie Bezahl-/Rückkehr-URLs).
- **Sandbox als Default:** `ShopConfig.payments_test_mode=True` zeigt eine eingebaute
  Test-Bezahlseite (kein Konto, keine Gebühren). Ein `test_…`-Key nutzt Mollies
  Testumgebung, ein `live_…`-Key echtes Geld.
- **Fail-safe gegen Fehlkonfiguration:** `payments_enabled` verlangt aktiv **und**
  (Test-Modus **oder** Key). `start_payment` fällt **nicht** still auf Sandbox
  zurück, wenn im Echtbetrieb der Key fehlt, sondern wirft `PaymentUnavailable`
  (`payments.py:25-52`) – verhindert „bezahlt ohne Zahlung“.
- **Online bezahlt ⇒ Rechnung sofort bestätigt/archiviert** (kein Kontoabgleich) +
  Benachrichtigung. Mitglieder über `shop_invoices`, Gäste über `external_pay`
  (Magic-Link).

## Betrachtete Alternativen

- **Getrennte Bezahlwege für Mitglieder und Gäste:** doppelte Integration; mehr
  Fehlerquellen.
- **Stripe/PayPal direkt im View:** Anbieter fest verdrahtet, schlechter testbar;
  Mollie hinter einer Naht bleibt austauschbar.
- **Stiller Sandbox-Fallback bei fehlendem Key:** gefährlich – eine Rechnung könnte
  ohne echte Zahlung als beglichen erscheinen.

## Konsequenzen

**Positiv**
- Ein Bezahlsystem für Mitglieder und Gäste; Anbieter hinter einer Naht
  austauschbar.
- Vollständig test-/vorführbar ohne Konto (Sandbox-Default).
- Fail-safe: Fehlkonfiguration blockiert, statt fälschlich „bezahlt“ zu setzen.

**Negativ**
- Externe Abhängigkeit (Mollie) im Echtbetrieb; Webhook-/Rückkehr-Flows müssen
  abgesichert bleiben.
- Zustand `payments_test_mode` muss für den Echtbetrieb bewusst umgestellt werden.
