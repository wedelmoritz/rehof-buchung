# 0018 – Verwaltungs-Dashboard als operatives Team-Cockpit (getrennt vom Backend)

## Status

Accepted (2026-06-26)

## Kontext

Das kleine Verwaltungsteam braucht für den Alltag eine fokussierte Oberfläche: Was
steht an, was muss geputzt werden, welche Rechnungen sind offen? Das Django-Backend
ist dafür zu mächtig und zu nah an den Rohdaten – und nicht jede Person im Team soll
Stammdaten/Buchungen ändern können (siehe ADR 0014). Den Hofladen-Katalog soll die
Verwaltung pflegen können, **ohne** Backend-Zugang.

## Entscheidung

Ein eigenes **Verwaltungs-Dashboard** unter `/verwaltung/`
(`booking/views.py:dashboard`), zugänglich für die Rolle **Verwaltung oder Admin**
(`_staff_required` → `is_verwaltung`, `views.py:712-725`). Bewusst **getrennt** vom
Backend `/admin/`.

- **Kennzahlen & Statistik** (`services.dashboard_stats`): Anzahl Benutzer und
  Mitglieder, Auslastung der Unterkünfte (aktueller + kommender Monat), Ergebnis der
  letzten bestätigten Verlosung (erfüllte vs. nicht erfüllte Wünsche), KPI „online
  bezahlt“.
- **Operative Listen:** Reinigungsliste (Abreisen = Reinigungstage), anstehende
  Buchungen, offene/überfällige/online bezahlte Rechnungen – je mit **Export**
  (xlsx/CSV, `booking/exports.py`) und **Versand per Knopf** (`send_cleaning`,
  `send_upcoming`, `remind_overdue`; Empfänger aus `OpsConfig`,
  `views.py:740-763`).
- **Hofladen-Katalog pflegen** ohne Backend (`dashboard_products`,
  `views.py:893`).
- **Buchungen/Losung nur lesend**; Backend-Deeplinks im Dashboard nur für Admins,
  der Beds24-Import nur für Admins sichtbar (`is_admin`).

## Betrachtete Alternativen

- **Nur das Django-Backend nutzen:** zu mächtig/roh; keine kuratierte Tagesansicht;
  Lese-/Schreibrechte schwer einzugrenzen.
- **Separates Admin-Tool/Service:** zusätzlicher Betriebsaufwand für ein kleines
  Team; das integrierte Dashboard genügt.

## Konsequenzen

**Positiv**
- Aufgabenorientierte, schlanke Oberfläche fürs Tagesgeschäft.
- Verwaltung arbeitet eigenständig (Katalog, Listen, Versand) ohne Backend-Rechte.
- Lesezugriff auf Buchungen/Losung ohne Änderungsrisiko.

**Negativ**
- Dashboard-Logik (Abfragen/Exporte/Texte) liegt zusätzlich im Service-Layer
  (`booking/services/dashboard.py`) und muss mit den Stammdaten konsistent bleiben.
- Manche Aktionen sind rollenabhängig zweifach abzusichern (Verwaltung vs. Admin).
