# Architecture Decision Records (ADRs)

Dieser Ordner dokumentiert die tragenden Architektur- und Designentscheidungen der
Re:Hof Quartier-Buchung. Jeder ADR folgt dem klassischen **MADR**-Format mit den
Abschnitten *Titel, Status, Kontext, Entscheidung, Betrachtete Alternativen,
Konsequenzen (positiv/negativ)* und ist durch konkrete Stellen im Code belegt.

**Trennung Technik ↔ Fachlichkeit:** Die ADRs halten **technische** Entscheidungen
(Frameworks, Muster, Code-Struktur) und ihre Abwägungen fest – **nicht** die
fachlichen Regeln. Die fachlichen Regeln (Tagebudget, Karma-Schritt, Saison-/
Buchungsregeln, Perioden-Lebenszyklus, USt-Sätze, Aufbewahrungsfristen …) stehen
gebündelt und als **einzige Quelle** im [**Fachkonzept**](../FACHKONZEPT.md). Wo
eine technische Entscheidung eine fachliche Regel umsetzt, verweist die ADR über
einen Kasten **„Fachlicher Bezug"** auf den passenden Fachkonzept-Abschnitt, statt
die Regelwerte zu wiederholen.

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
| [0009](0009-buchungsregeln-der-genossenschaft.md) | Buchungsregeln der Genossenschaft umgesetzt | Accepted |
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
| [0038](0038-zahlungsanbindung-anzahlung-storno-erstattung.md) | Zahlungsanbindung: Anzahlung und Storno-Erstattung | Proposed |
| [0039](0039-eingabe-validierung-und-xss-haertung.md) | Eingabe-Validierung der Benutzereingaben und XSS-/Injektions-Härtung | Accepted |
| [0040](0040-abrechnungsmodell-ohne-tse.md) | Abrechnungsmodell ohne TSE (KassenSichV / §146a AO) | Accepted |
| [0041](0041-umsatzsteuer-kleinunternehmer-vs-regelbesteuerung.md) | Umsatzsteuer: Kleinunternehmer (§19) vs. Regelbesteuerung | Accepted |
| [0042](0042-rechtstexte-impressum-datenschutz-agb.md) | Rechtstexte: Impressum, Datenschutz und AGB konfigurierbar | Accepted |
| [0043](0043-dsgvo-datensparsamkeit-aufbewahrung-loeschung.md) | DSGVO: Datensparsamkeit, Aufbewahrung, automatische Löschung & Anonymisierung | Accepted |
| [0044](0044-web-push-und-gezieltes-offline.md) | Web-Push (mobil) und gezieltes Offline-Verhalten | Accepted |
| [0045](0045-domaeneninvarianten-im-modell-clean.md) | Domänen-Invarianten am Modell (`clean`) erzwingen, auch im Admin | Accepted |
| [0046](0046-observability-logging-sentry-healthcheck.md) | Observability: strukturiertes Logging, Sentry und Health-Endpoint | Accepted |
| [0047](0047-e2e-tests-prod-naher-stack.md) | End-to-End-Tests gegen einen prod-nahen Docker-Stack | Accepted |
| [0048](0048-uv-und-typcheck-reine-logik.md) | uv als Entwickler-Werkzeug und mypy auf der reinen Logik | Accepted |
| [0049](0049-backend-fachliche-gliederung.md) | Backend: fachliche Gliederung statt App-Gruppierung | Accepted |
| [0050](0050-services-paket-aufteilung.md) | Service-Layer als Paket: `services.py` in fachliche Submodule aufteilen | Accepted |
| [0051](0051-belastungs-und-nebenlaeufigkeitstests.md) | Belastungs- und Nebenläufigkeitstests (k6 + Zeilensperren-Test) | Accepted |
| [0052](0052-konto-einladung-passwort-selbst-setzen.md) | Konto-Einladung: Passwort selbst setzen statt Admin-Vergabe | Accepted |
| [0053](0053-hofladen-terminal-offline-kiosk.md) | Hofladen-Terminal vor Ort: offline-fähiger, token-authentifizierter Kiosk | Accepted |
| [0054](0054-einheitliches-farbsystem.md) | Einheitliches Farbsystem (warmes Papier-Neutral + Terrakotta-Akzent) | Accepted |
| [0055](0055-backend-persistenter-navigator-pjax.md) | Backend: persistenter Navigator (Suche + Bereiche) + pjax statt Layout-Wechsel | Accepted |
| [0056](0056-gefuehrtes-onboarding-neuer-benutzer.md) | Geführtes Onboarding neuer Benutzer im Backend (Mitglied / Hofladen / deaktivieren) | Accepted |
| [0057](0057-backend-ux-verfeinerungen.md) | Backend-UX-Verfeinerungen (Navigator einklappbar/Akkordeon, Listen, Leer-Hinweise) | Accepted |

## Offene Punkte (in ADRs markiert)

- **OIDC/Keycloak-Anbindung** – siehe ADR 0015 (Naht vorhanden, nicht umgesetzt).
- **Backup & weiteres Hardening** – siehe ADR 0037 (Blueprint vorhanden, vor dem
  Wirkbetrieb umzusetzen).
- **Zahlungsanbindung: Anzahlung & Storno-Erstattung** – siehe ADR 0038 (Voll-
  Bezahlung umgesetzt; Anzahlung informativ, Erstattung manuell).
- **Umsatzsteuer-Status festlegen** – siehe ADR 0041. Beide Modi (Regelbesteuerung
  und §19-Kleinunternehmer) sind umgesetzt und im Backend umschaltbar; der konkrete
  USt-Status der Genossenschaft ist vor Go-Live mit dem Steuerberater zu bestätigen.
- **Rechtstexte inhaltlich pflegen** – siehe ADR 0042. Impressum/Datenschutz/AGB sind
  konfigurierbar (Backend); die Texte muss die Genossenschaft vor Go-Live einpflegen.
- **DSGVO: IBAN-Verschlüsselung & Token-Rotation** – siehe ADR 0043. Die automatische
  Aufbewahrung/Löschung und die Anonymisierung sind umgesetzt; IBAN-Feldverschlüsselung
  (ADR 0037) und Magic-Link-Token-Rotation bleiben offen, Fristen vor Go-Live mit der
  Datenschutz-Verantwortlichen bestätigen.

Die Saison-Regeln (Mindestnächte **und** Parallel-Limit/Aufenthaltsdeckel) gelten
inzwischen vollständig auch in der Losung – siehe ADR 0009 (kein offener Punkt mehr).
