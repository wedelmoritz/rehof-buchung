# 0081 – Endreinigung als Freigabe-Workflow (Anfrage → Betriebsleitung bestätigt/lehnt ab)

## Status

Accepted (2026-07-02)

> Präzisiert die beim Buchen mitbuchbaren Dienstleistungen (ADR 0075/Fachkonzept § 9/13).

## Kontext

Die **Endreinigung** war als Hofladen-Dienstleistung modelliert (`Product` mit
`book_with_stay`): beim Buchen opt‑in angeklickt, entstand **sofort** ein bestätigter
Einkauf (`purchase_service`) auf der Monatsrechnung. Aus der Praxis (Tester-Feedback
#28/#33):

- Die Endreinigung ist **keine spontan zubuchbare** Leistung, sondern wird mit der
  **Betriebsleitung (BL)** und dem Reinigungsteam **abgestimmt** – sie gehört in den
  **Buchungsprozess**, nicht als frei buchbare DL in den Hofladen.
- Für das Mitglied war **nicht sichtbar**, ob die Endreinigung angefragt/bestätigt
  ist – es fehlte eine Rückmeldung/ein Status.

## Entscheidung

**Bestätigungspflichtige Dienstleistungen als Anfrage-/Freigabe-Workflow.**

1. **Neues Flag `Product.needs_approval`** (Default aus). Ist es gesetzt (für die
   Endreinigung), wird die Leistung beim Buchen **nur angefragt**, nicht sofort
   abgerechnet. Andere DLs (z. B. Sauna) bleiben unverändert Sofort-Kauf.

2. **Neues Modell `shop.ServiceRequest`** (`member`, `product`, `allocation`,
   `service_date`, `status` = requested/confirmed/rejected, `line_item`,
   Zeitstempel/Entscheider). Beim Buchen erzeugt `services.request_service` eine
   Anfrage (idempotent je Buchung+Produkt) und benachrichtigt die BL (E‑Mail an die
   `OpsConfig`-Adressen + Dashboard-Liste).

3. **Freigabe im Verwaltungs-Dashboard** (Abschnitt „Anfragen zur Freigabe“):
   **Bestätigen** (`confirm_service_request`) legt die Rechnungs-Position an
   (`purchase_service`, damit erscheint sie auch in der **Reinigungsliste**) und
   benachrichtigt das Mitglied; **Ablehnen** (`reject_service_request`) informiert das
   Mitglied (optional mit Grund). Beide sind idempotent (nur aus `requested`).

4. **Status für das Mitglied** in „Meine Buchungen“ (#33): je Buchung ein Chip
   „🕓 angefragt · an Betriebsleitung übermittelt“ / „✅ bestätigt“ / „✖ abgelehnt“.

5. **Abrechnung erst bei Bestätigung** – eine abgelehnte/offene Anfrage erzeugt
   **keine** Rechnungsposition.

## Nicht im Hofladen-Katalog (#37)

Beim-Buchen-Leistungen (`book_with_stay`, z. B. Endreinigung) gehören in den
**Buchungsabschnitt**, nicht in den Hofladen. Der Mitglieder-Katalog (`shop_index`)
**blendet sie aus**, und der `add`-Endpoint **lehnt sie server-seitig ab** – so lassen
sie sich nicht als eigenständiger Warenkorb-Kauf hinzufügen. Die Abrechnung einer
**bestätigten** Endreinigung läuft weiterhin über die reguläre Monatsrechnung (das
Rechnungs-/USt-/Kontoabgleich-System ist bewusst der einzige Abrechnungsweg); im
Mitglieder-Katalog taucht sie aber nicht mehr auf.

## Aufteilung Backend ↔ Dashboard

Die **Freigabe** liegt bewusst im **Verwaltungs-Dashboard** (Tagesgeschäft der BL,
kein Backend nötig). Der `ServiceRequestAdmin` im Django-Admin ist nur **Nachschau**
(kein Anlegen, kein Bestätigen dort).

## Konsequenzen

**Positiv** – entspricht dem realen Ablauf; klare Rückmeldung ans Mitglied; keine
ungewollte Abrechnung ohne Freigabe; generisch (`needs_approval`) auch für weitere
abzustimmende Leistungen nutzbar. Effizient: eine zusätzliche Abfrage im Dashboard
und ein Prefetch in „Meine Buchungen“. Migration (`Product.needs_approval` +
`ServiceRequest`); die Demo/Testdaten setzen die Endreinigung auf
`needs_approval=True` und legen einige offene Anfragen an.

**Grenzen** – der Abrechnungs­fall bleibt einfach (eine Anfrage → eine Position bei
Bestätigung). Storniert das Mitglied die Buchung, entfällt die Anfrage mit
(`allocation`-CASCADE); eine bereits bestätigte Position folgt der bestehenden
`LineItem`-Logik. Aufbewahrung/DSGVO-Pruning erledigter Anfragen ist ein späterer
Kandidat (heute an der `Allocation` gekoppelt).
