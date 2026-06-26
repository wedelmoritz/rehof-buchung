# 0023 – Externe Gäste: öffentlicher Gast-Checkout mit Magic-Link

## Status

Accepted (2026-06-26)

## Kontext

Freie Quartiere sollen auch an **externe Gäste** (ohne Genossenschafts-Login)
vermietet werden können – mit Verfügbarkeit, Buchung und Bezahlung. Gäste sollen
sich **kein Konto** anlegen müssen, ihre Buchung aber später ansehen und stornieren
können. Mitglieder buchen weiterhin kostenfrei und unverändert.

## Entscheidung

Ein **öffentlicher, login-freier Buchungsweg** mit Magic-Link statt Gast-Accounts.

- **Datenmodell:** `booking/models.py:Guest` (Bucher ohne Login, mit `token` für den
  Magic-Link), `ExternalBooking` (Reservierung; blockiert die Verfügbarkeit;
  verknüpft mit einer `shop.Invoice`), `ExternalConfig` (Singleton: Regeln Mo–Do,
  Mindestnächte, Vorlauf, Anzahlung, Stornostaffel, Säumniszuschlag, AGB).
- **Reine Regel-Logik** Django-frei in `booking/external.py` (`external_allowed`,
  `cancellation_refund`), isoliert testbar (`tests/test_beds24.py`/externe Tests).
- **Service-Flow** in `booking/services.py`: `external_quote` (saisonale Preise pro
  Nacht + Anzahlung/Storno-Text), `external_available_quarters`,
  `create_external_booking`, `cancel_external_booking`, `build_external_calendar`
  sowie die `*_by_token`-Varianten für die Magic-Link-Selbstverwaltung.
- **Öffentliche Views** (zweistufig wie intern): `external_home` (`/extern/`) →
  `external_book` → `external_confirm`; dazu `external_manage`
  (`/extern/verwalten/<token>/`), `external_pay` (Online-Bezahlung über den Link)
  und das einbettbare Widget `external_embed` (`@xframe_options_exempt`).
- **Abrechnung** läuft über dieselbe generalisierte `Invoice` wie der Hofladen
  (siehe ADR 0016); intern erscheinen Gäste neutral als „extern“.

## Betrachtete Alternativen

- **Gast-Accounts mit Passwort:** Hürde für einmalige Buchungen; mehr Konten-/
  Passwort-Verwaltung.
- **Externe Buchungen nur über die Verwaltung:** kein Self-Service, mehr manuelle
  Arbeit.
- **Separates Rechnungssystem für Gäste:** doppelte Logik (verworfen, siehe 0016).

## Konsequenzen

**Positiv**
- Niedrigschwellige Buchung ohne Konto; Selbstverwaltung per Link.
- Regeln/Preise/Storno im Backend konfigurierbar; Regel-Logik isoliert testbar.
- Eine Rechnungs-/Zahlungsschiene für Mitglieder und Gäste.

**Negativ**
- Der Magic-Link-`token` ist das Zugangsgeheimnis – muss sicher erzeugt/behandelt
  werden (kein Raten, kein Logging).
- Zusätzliche öffentliche Angriffsfläche (`/extern/`), die abgesichert bleiben muss.
