# 0016 – Hofladen als eigene App `shop` mit generalisierter Rechnung

## Status

Accepted (2026-06-26)

## Kontext

Neben Quartier-Buchungen verkauft die Genossenschaft Waren und Dienstleistungen
(Hofladen, z. B. Endreinigung, Sauna) und rechnet diese ab. Diese Geld-/Abrechnungs-
logik (Preis-Snapshots, Steuer, §14-Rechnung, Mahnwesen) ist fachlich eigenständig
und sollte die Buchungs-App nicht aufblähen. Zudem brauchen **zwei** Empfängerarten
eine Rechnung: **Mitglieder** (Hofladen, mitgebuchte Dienste) und **externe Gäste**
(Übernachtungen, siehe `docs/EXTERNE-GAESTE.md`).

## Entscheidung

Der Hofladen ist eine **eigene Django-App `shop`** (in `INSTALLED_APPS`), mit
eigenem Admin, denselben Webapp-/Login-Mechanismen und einer klaren Geld-Schicht
(`shop/services.py`, getestet in `shop/tests.py`).

- **Lebenszyklus einer Position:** Warenkorb → **Checkout** (`services.checkout`
  legt einen read-only `Purchase` an) → **Rechnung** (`Invoice`, Nummer
  `HL-JJJJ-MM-NNN`, Status offen → bezahlt-gemeldet → bestätigt/archiviert).
  Positionen sind `LineItem` mit **Preis-Snapshot** (Brutto, MwSt-Satz zum
  Kaufzeitpunkt; `shop/models.py`).
- **Generalisierte Rechnung:** `shop/models.py:Invoice` trägt **entweder** `member`
  **oder** `guest` (beide nullable) und liefert einen einheitlichen
  `recipient_label` (`models.py:284-291`). So nutzen Mitglieder und Gäste **dieselbe**
  Rechnungs-, PDF-, Mahn- und Kontoabgleich-Logik.
- **Abrechnung** monatlich (`generate_monthly_invoices`, Cron) **oder** sofort
  (`generate_invoice_now`). Beim Buchen mitgebuchte Dienste laufen über
  `purchase_service` direkt als bestätigter Einkauf.
- **Stammdaten** im Singleton `ShopConfig` (Name, Anschrift, IBAN, Präfix,
  Zahlungsziel) – editierbar nur im Backend (Admin-Rolle).

## Betrachtete Alternativen

- **Hofladen-Logik in der `booking`-App:** vermischt zwei Domänen; schlechtere
  Trennung von Geld- und Buchungslogik.
- **Zwei getrennte Rechnungsmodelle (Mitglied vs. Gast):** doppelte PDF-/Mahn-/
  Abgleich-Logik; mehr Code und Pflege.

## Konsequenzen

**Positiv**
- Saubere Domänentrennung; Geldlogik isoliert testbar (`shop/services.py`).
- Ein Rechnungsweg für Mitglieder **und** Gäste (PDF, Mahnung, Kontoabgleich).
- Preis-Snapshots machen Rechnungen reproduzierbar und §14-konform.

**Negativ**
- Zwei nullable Empfängerfelder an `Invoice` erfordern Invarianten (genau einer von
  beiden) und Sorgfalt bei Abfragen.
- App-übergreifende Kopplung: `shop` importiert `booking.Member`/`Guest`.
