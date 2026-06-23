# Externe Gäste: Buchung & Zahlung — Konzept

> **Status: KONZEPT — NICHT UMGESETZT.** Bauplan zum Ablösen von **beds24**:
> Externe Gäste buchen und zahlen direkt in dieser App; Mitglieder buchen wie
> bisher kostenfrei. Entscheidungen (abgestimmt):
>
> - **Zahlung:** Mollie (Hosted Checkout) als Primärweg; Rechnung/Vorkasse als Fallback.
> - **Einstieg:** Hybrid – buchen/zahlen zentral in der App + einbettbares
>   Verfügbarkeits-Widget/Feed für die bestehende Re:Hof-Website.
> - **Gast-Konto:** Gast-Checkout ohne Pflicht-Registrierung (E-Mail + Magic-Link).

## 1. Zielbild

- **Eine Quelle der Wahrheit** für Belegung bleibt diese App. Mitglieder: bisheriger
  Flow, kein Zahlschritt („100 % Rabatt“). **Externe**: zusätzliche, **bezahlte
  Schicht** mit eigenem öffentlichen Einstieg.
- Vorhandene Nähte: `Member.is_external`, `Allocation.source="external"`; die
  Rechnungs-/Abgleich-Infrastruktur (`shop` Invoice, Fälligkeit, Mahnung,
  `shop/reconcile.py`) und das **„provisional“-Hold-Muster** (aus dem Losungs-
  Review) sind wiederverwendbar.

## 2. Architektur (Hybrid)

```
Re:Hof-Website ──(read-only)── Verfügbarkeits-Widget/Feed (iframe oder iCal/JSON)
                                   │  Link „Jetzt buchen“
                                   ▼
        ┌─────────────────  Diese App (öffentlicher Bereich, ohne Login)  ─────────────────┐
        │  Info + Kalender → Auswahl → Gast-Daten → HOLD (provisorisch) → Mollie-Checkout    │
        │                                   ▲ Webhook (bezahlt) → Buchung fix + Bestätigung   │
        └───────────────────────────────────────────────────────────────────────────────────┘
```

- Der öffentliche Bereich muss von der `ActivationGateMiddleware` **ausgenommen**
  werden (wie heute `sw`/`offline`).
- Das Widget für die Website ist **read-only** (zeigt nur „externten-buchbar“) und
  verlinkt zur App-Buchungsseite. Optionen: iframe-Seite, JSON-Endpoint oder
  iCal-Feed (`.ics`).

## 3. Gast-Modell (ohne Pflicht-Registrierung)

- Externe buchen mit **E-Mail + Kontakt-/Rechnungsdaten**; ihre Buchung
  verwalten/stornieren sie über einen **Magic-Link** (signierter Token per Mail).
- Datenmodell: `Allocation(source="external")` + schlankes **`Guest`** (Name,
  E-Mail, Anschrift) statt `Member`. Optionales Konto später möglich, nicht nötig.

## 4. Verfügbarkeit & Externen-Regeln (Backend-konfigurierbar)

**Entkopplung:** „grundsätzlich für Externe freigegeben“ (Policy) ≠ „tatsächlich
frei“ (Belegung). Externen-buchbar = *Policy erlaubt* **und** *nicht belegt*.

Neues Konfig-Modell **`ExternalPolicy`** (global und/oder je Quartier):

- erlaubte **Wochentage** (z. B. Mo–Do → „Wochenenden nur Mitglieder“),
- **Saison-/Datumsfenster** (wann Externe überhaupt dürfen),
- **Min/Max-Nächte**, **Vorlauf/Cutoff** (frühestens/spätestens buchbar),
- optional „keine Einzelnacht-Lücken zwischen Mitgliederbuchungen reißen“.

Konzeptuell analog zu den vorhandenen `SeasonRule`s; die reine Logik kann in ein
Modul `external.py` (Django-frei, testbar) wie `rules.py`/`availability.py`.

## 5. Preise & Steuer

- Neues **Preis-Modell**: Preis je Quartier/Nacht (optional saisonabhängig) +
  **Endreinigung** (vorhandenes `Product`) + optional **Kaution**. Mitglieder =
  Preis 0 (kein Zahlschritt).
- **USt (DE):** Beherbergung **7 %**, Nebenleistungen (Reinigung) **19 %** —
  getrennt ausweisen; `Invoice.vat_breakdown()` kann das bereits.

## 6. Zahlung mit Mollie (Hosted Checkout)

**Warum Mollie:** Karte, **PayPal (inklusive)**, Apple/Google Pay, SEPA, giropay;
~1,2 % + 0,25 € je EU-Karte; **keine Fixkosten** (nur Transaktionsgebühr); starke
DACH/SEPA-Abdeckung. **PCI = SAQ-A** (Kartendaten nur beim Anbieter, nie auf
unserem Server); **PSD2/SCA** erledigt Mollie. Bibliothek: `mollie-api-python`.

**Ablauf (Best Practice):**

1. Gast wählt Quartier/Zeitraum → wir prüfen Policy **und** Belegung.
2. **HOLD:** `Allocation(provisional=True)` mit **Ablaufzeit** anlegen (blockiert
   den Slot, genau wie beim Losungs-Review). Verhindert Doppelbuchung.
3. **Mollie-Payment** erzeugen (mit **Idempotency-Key**) → Redirect zum Hosted
   Checkout.
4. **Webhook** (Signatur/Status-Abruf, **idempotent** über gespeicherte
   Payment-/Event-ID mit Unique-Constraint, schnelle 2xx): bei `paid` → Buchung
   fix (`provisional=False`), Bestätigungs-Mail + Beleg (PDF wie Rechnung); bei
   `expired/failed/canceled` → Hold freigeben.
5. **Storno/Refund** über die Mollie-API gemäß Stornobedingungen.

**Sicherheit:** Webhook-Signatur prüfen, Idempotenz, keine Kartendaten speichern,
Hold-Ablauf serverseitig (Cron/Scheduler) erzwingen, DB-Constraint gegen
Überschneidungen.

**Fallback Rechnung/Vorkasse** (vorhandene Invoice + `reconcile.py`), für Externe
**strenger**: **Vorkasse/Anzahlung Pflicht** vor Bestätigung (sonst kurzer
Zahlungs-Zeitraum mit **automatischem Freigeben**), **Säumniszuschlag**, klare
**Stornobedingungen**. Bewusst nur Ausnahme/manuell — Vorkasse per Mollie ist für
Externe deutlich risikoärmer.

## 7. Datenmodell-Skizze (neu/erweitert)

- `Guest` — Kontakt-/Rechnungsdaten externer Bucher (kein Login).
- `ExternalPolicy` — Verfügbarkeits-/Regelwerk für Externe (s. o.).
- `QuarterPrice` (oder Felder an `Quarter` + Saison-Overrides) — Preise/Kaution.
- `Payment` — PSP-Vorgang (Mollie-ID, Status, Betrag, Event-IDs, Idempotenz).
- `Allocation` erweitern: `guest` (FK, optional), `hold_expires_at`,
  `payment` (FK). `source="external"` existiert bereits.

## 8. Sicherheit & Compliance

- Hosted Checkout → **PCI SAQ-A**; Webhook-Signatur + Idempotenz; keine Kartendaten;
  Refund via API; Doppelbuchung über Hold + DB-Constraint; **DSGVO**-sparsame
  Gastdaten + Aufbewahrungsfristen; ToS/Datenschutz/Impressum.

## 9. Recht & Betrieb (DE) — vorab klären (keine Rechtsberatung)

- **USt** 7 % Beherbergung / 19 % Nebenleistungen, getrennt ausweisen.
- **Meldeschein:** seit 1.1.2025 nur noch für **ausländische** Gäste Pflicht.
- **Kurtaxe/Beherbergungssteuer:** kommunal — am Standort prüfen, ggf. als Posten.
- **Widerrufsrecht** bei Beherbergung zu festem Termin ausgeschlossen (§312g BGB) →
  trotzdem **AGB/Stornobedingungen** nötig.
- **Impressum, Datenschutz, Preisangaben** (Endpreise inkl. USt, PAngV).
- **EU-Kurzzeitvermietung / KVDG (ab 2026):** evtl. Registrierungsnummer prüfen.

## 10. Phasenplan

- **E1 – Fundament:** Modelle `Guest`, Preise, `ExternalPolicy`; öffentlicher
  **read-only Verfügbarkeitskalender** + iCal/JSON-Feed fürs Website-Widget;
  Gate-Ausnahme für den öffentlichen Bereich.
- **E2 – Bezahlte Buchung:** öffentlicher Flow mit **Hold** + **Mollie-Hosted-
  Checkout** + Webhook-Bestätigung + Bestätigungs-/Storno-Mails + Refund.
- **E3 – Fallback & Verwaltung:** Rechnungs-/Vorkasse-Weg (Anzahlung,
  Säumniszuschlag); externe Buchungen + Zahlungsstatus im Dashboard.
- **E4 – Website-Einbettung & Feinschliff:** Widget/iframe final, AGB/Impressum,
  Reporting/Export.

## 11. Offene Punkte (vor E1 zu klären)

- Preislogik: feste Preise je Quartier oder Saisonstaffel? Kaution ja/nein?
- Stornobedingungen/Refund-Quoten (z. B. 100 %/50 %/0 % je Vorlauf).
- Genauer Externen-Rhythmus (Mo–Do? ganze Wochen? Saisonfenster?).
- Widget-Form: iframe-Seite, JSON oder iCal-Feed (oder mehrere).
- Mollie-Konto/Geschäftskonto der eG + Test-API-Keys.
