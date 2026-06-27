# 0023 – Externe Gäste: öffentlicher Gast-Checkout mit Magic-Link

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 12 – Externe Gäste](../FACHKONZEPT.md#12-externe-gäste) sowie
> [§ 4 – Saison- & Buchungsregeln](../FACHKONZEPT.md#4-saison--buchungsregeln)
> (Mindestaufenthalt). Diese ADR hält die *technische* Entscheidung und ihre
> Abwägungen fest; die Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Freie Quartiere sollen auch an **externe Gäste** (ohne Genossenschafts-Login)
vermietet werden können – mit Verfügbarkeit, Buchung und Bezahlung. Gäste sollen
sich **kein Konto** anlegen müssen, ihre Buchung aber später ansehen und stornieren
können. Mitglieder buchen weiterhin kostenfrei und unverändert.

## Entscheidung

Ein **öffentlicher, login-freier Buchungsweg** mit Magic-Link statt Gast-Accounts.

- **Datenmodell:** `booking/models.py:Guest` (Bucher ohne Login, mit `token` für den
  Magic-Link), `ExternalBooking` (Reservierung; blockiert die Verfügbarkeit;
  verknüpft mit einer `shop.Invoice`), `ExternalConfig` (Singleton: hält die
  Externen-Regelwerte – Anreise-Wochentage, Mindestnächte, Vorlauf, Anzahlung,
  Stornostaffel, Säumniszuschlag, AGB; Regelwerte: Fachkonzept § 12).
- **Reine Regel-Logik** Django-frei in `booking/external.py` (`external_allowed`,
  `cancellation_refund`), isoliert testbar (`tests/test_beds24.py`/externe Tests).
- **Service-Flow** im Paket `booking/services/`: `external_quote` (saisonale Preise pro
  Nacht + Anzahlung/Storno-Text), `external_available_quarters`,
  `create_external_booking`, `cancel_external_booking`, `build_external_calendar`
  sowie die `*_by_token`-Varianten für die Magic-Link-Selbstverwaltung.
- **Öffentliche Views** (zweistufig wie intern): `external_home` (`/extern/`) →
  `external_book` → `external_confirm`; dazu `external_manage`
  (`/extern/verwalten/<token>/`), `external_pay` (Online-Bezahlung über den Link)
  und das einbettbare Widget `external_embed` (`@xframe_options_exempt`).
- **Abrechnung** läuft über dieselbe generalisierte `Invoice` wie der Hofladen
  (siehe ADR 0016); intern erscheinen Gäste neutral als „extern“.
- **Mindestaufenthalt – konfigurierbar, Standard wie intern:** Der Schalter
  `ExternalConfig.min_nights_follow_internal` steuert, ob der Externen-Mindest-
  aufenthalt der internen Regel (inkl. Saison) folgt oder einen eigenen festen Wert
  (`ExternalConfig.min_nights`) nutzt – berechnet über `services.external_min_nights`
  → `min_nights_for_range`. Die fachliche Regel (Default = identisch zu intern,
  optional abweichend) steht in Fachkonzept § 4/§ 12; technisch ist hier die Naht
  zwischen Schalter und reiner Regel-Logik festgehalten.

## Betrachtete Alternativen

- **Gast-Accounts mit Passwort:** Hürde für einmalige Buchungen; mehr Konten-/
  Passwort-Verwaltung.
- **Externen-Mindestaufenthalt fix an die internen Regeln koppeln:** einfacher,
  aber die Genossenschaft könnte für Gäste keinen abweichenden Mindestaufenthalt
  setzen – verworfen zugunsten des Schalters (Default = identisch zu intern).
- **Externen-Mindestaufenthalt komplett unabhängig (kein „wie intern“):** würde
  den Normalfall (gleiche Regeln wie Mitglieder) zur manuellen Pflege machen und
  Saison-Mindestnächte für Gäste leicht übersehen lassen.
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
