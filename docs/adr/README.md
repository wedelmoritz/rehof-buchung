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

## Offene Punkte (in ADRs markiert)

- **Saison-Regeln in der Losung erzwingen** – siehe ADR 0009 (aktuell nur bei der
  normalen Buchung umgesetzt).
- **OIDC/Keycloak-Anbindung** – siehe ADR 0015 (Naht vorhanden, nicht umgesetzt).
