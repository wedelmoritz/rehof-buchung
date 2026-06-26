# Architecture Decision Records (ADRs)

Dieser Ordner dokumentiert die tragenden Architektur- und Designentscheidungen der
Re:Hof Quartier-Buchung. Jeder ADR folgt dem klassischen **MADR**-Format mit den
Abschnitten *Titel, Status, Kontext, Entscheidung, Betrachtete Alternativen,
Konsequenzen (positiv/negativ)* und ist durch konkrete Stellen im Code belegt.

**Status-Werte:**
- **Accepted** – entschieden und im Code umgesetzt.
- **Proposed** – Entscheidung getroffen/vorgesehen, Umsetzung (noch) offen.

## Index

| Nr. | Titel | Status |
|----:|-------|--------|
| [0001](0001-django-postgresql-stack.md) | Django + PostgreSQL als Stack | Accepted |
| [0002](0002-drei-schichten-architektur.md) | Drei-Schichten-Architektur: reine Logik / Service-Layer / dünne Views | Accepted |
| [0003](0003-losverfahren-weighted-rsd.md) | Losverfahren: gewichtete Zufallsreihenfolge im Runden-Prinzip | Accepted |
| [0004](0004-karma-ausgleichsfaktor.md) | Karma/Ausgleichsfaktor über die Jahre | Accepted |
| [0005](0005-aequivalenzklassen.md) | Äquivalenzklassen als konfigurierbare Wert-Entscheidung | Accepted |
| [0006](0006-losung-unabhaengig-von-buchungszeitraum.md) | Losung bewusst unabhängig von den Buchungszeiträumen | Accepted |
| [0007](0007-nur-eingereichte-wuensche.md) | Nur eingereichte Wünsche nehmen an der Losung teil | Accepted |
| [0008](0008-losung-review-workflow.md) | Losung-Review-Workflow: vorläufig prüfen, bestätigen oder zurücknehmen | Accepted |
| [0009](0009-buchungsregeln-der-genossenschaft.md) | Buchungsregeln der Genossenschaft umgesetzt | Accepted (teilw.) |
| [0010](0010-tage-uebertragung-an-mitglieder.md) | Tage-Übertragung an andere Mitglieder | Accepted |
| [0011](0011-schulferien-informativ-getrennt.md) | Schulferien als rein informatives, vom Regelwerk getrenntes Modell | Accepted |
| [0012](0012-buchungszeitraeume-schnittmengen-semantik.md) | Buchungszeiträume mit Schnittmengen-Semantik | Accepted |
| [0013](0013-buchungskorrektheit-zeilensperre.md) | Buchungs-Korrektheit über Zeilensperre (SELECT … FOR UPDATE) | Accepted |
| [0014](0014-rollentrennung-admin-verwaltung.md) | Rollentrennung Admin (Superuser) vs. Verwaltung (Gruppe) | Accepted |
| [0015](0015-auth-haertung-und-oidc-naht.md) | Auth-Härtung: E-Mail/Benutzername-Login, Brute-Force-Schutz, Aktivierungs-Gate | Accepted (OIDC: Proposed) |
| [0016](0016-hofladen-eigene-app-generalisierte-invoice.md) | Hofladen als eigene App `shop` mit generalisierter Rechnung | Accepted |
| [0017](0017-online-bezahlung-mollie-sandbox-default.md) | Online-Bezahlung (Mollie) als eine Naht, Sandbox als Default | Accepted |
| [0018](0018-verwaltungs-dashboard.md) | Verwaltungs-Dashboard als operatives Team-Cockpit (getrennt vom Backend) | Accepted |
| [0019](0019-backend-django-admin-stammdaten.md) | Backend (Django-Admin) als Stammdaten- und Mitgliederverwaltung | Accepted |
| [0020](0020-betriebsmodell-docker-compose-caddy.md) | Betriebsmodell: Docker-Compose (web + PostgreSQL) hinter separatem Caddy | Accepted |
| [0021](0021-hintergrund-scheduler-container.md) | Hintergrund-Scheduler-Container statt System-Cron | Accepted |
| [0022](0022-zwei-ebenen-teststrategie-ci.md) | Zwei-Ebenen-Teststrategie und CI inkl. Migrations-Resilienz | Accepted |
| [0023](0023-externe-gaeste-magic-link.md) | Externe Gäste: öffentlicher Gast-Checkout mit Magic-Link | Accepted |
| [0024](0024-buchungsfluss-ampel-zweistufig.md) | Buchungsfluss: Ampel-Kalender + zweistufige Bestätigung | Accepted |
| [0025](0025-warteliste-spontan-frei.md) | Warteliste und „spontan frei"-Benachrichtigung | Accepted |
| [0026](0026-buchung-aendern-wechselwunsch.md) | Buchung ändern und Wechselwunsch (auch bei Überlappung) | Accepted |
| [0027](0027-benachrichtigungen-inapp-outbox.md) | Benachrichtigungen: In-App plus entkoppelte E-Mail-Outbox | Accepted |
| [0028](0028-rechnungs-pdf-weasyprint.md) | Rechnungs-PDF mit WeasyPrint (Inhalt von Ausgabe getrennt) | Accepted |
| [0029](0029-kontoabgleich-bankimport.md) | Kontoabgleich: Bank-Import (CSV/CAMT) mit automatischer Verbuchung | Accepted |
| [0030](0030-beds24-migrations-assistent.md) | Beds24-Migrations-Assistent: einmaliger CSV-Import mit manuellem Abgleich | Accepted |
| [0031](0031-fairness-nachweis-monte-carlo.md) | Fairness-Nachweis per Monte-Carlo-Simulation | Accepted |
| [0032](0032-bookingperiod-lebenszyklus.md) | BookingPeriod: eine Periode pro Jahr, statusgesteuerter Lebenszyklus | Accepted |
| [0033](0033-mitglieds-datenmodell-membership-member-share.md) | Mitglieds-Datenmodell: Membership / Member / Share | Accepted |
| [0034](0034-konfiguration-singleton-modelle.md) | Konfiguration über Singleton-Modelle | Accepted |
| [0035](0035-pwa-offline-responsive.md) | PWA: installierbar, offline-fähig, responsive Navigation | Accepted |
| [0036](0036-lizenz-agpl-v3.md) | Lizenz: GNU AGPL v3 | Accepted |
| [0037](0037-backup-haertung-zurueckgestellt.md) | Backup und weiteres Hardening bewusst zurückgestellt | Proposed |

## Offene Punkte (in ADRs markiert)

- **Parallel-Limit/Mehrfach-Deckel in der Losung** – siehe ADR 0009. Die
  Saison-**Mindestnächte** gelten inzwischen auch für Wunschliste/Losung (beim
  Einreichen) und externe Buchungen; offen bleibt nur das Parallel-Limit/der
  Deckel über mehrere Buchungen im Los-Algorithmus selbst.
- **OIDC/Keycloak-Anbindung** – siehe ADR 0015 (Naht vorhanden, nicht umgesetzt).
- **Backup & weiteres Hardening** – siehe ADR 0037 (Blueprint vorhanden, vor dem
  Wirkbetrieb umzusetzen).
