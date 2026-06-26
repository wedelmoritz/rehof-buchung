# 0001 – Django + PostgreSQL als Stack

## Status

Accepted (2026-06-26)

## Kontext

Die Genossenschaft braucht eine Web-App mit Mitgliederverwaltung, Authentifizierung,
einem Verwaltungs-Backend, Buchungs- und Rechnungslogik. Das Team ist klein; der
Wartungsaufwand muss niedrig bleiben. Perspektivisch soll ein zentrales Login
(OIDC/Keycloak) angebunden werden können, ohne die App umzubauen.

## Entscheidung

Wir setzen auf **Django** (Python) mit **PostgreSQL** als Datenbank.

- Das eingebaute **Django-Admin** liefert die Stammdaten-/Mitgliederverwaltung
  praktisch geschenkt (`booking/admin.py`, `django.contrib.admin` in
  `config/settings.py:INSTALLED_APPS`).
- Auth, CSRF, Sessions, Passwort-Hashing kommen out-of-the-box
  (`config/settings.py:MIDDLEWARE`, `AUTH_PASSWORD_VALIDATORS`).
- Die DB-Wahl ist über `DATABASE_URL` gekapselt: Produktion = PostgreSQL,
  Tests/Entwicklung = SQLite (`config/settings.py:88-99`).
- Eine **OIDC-Naht** ist in den Settings vorbereitet: `AUTHENTICATION_BACKENDS`
  ist erweiterbar, der Kommentar markiert die Stelle für ein Keycloak-Backend
  (`config/settings.py:109-117`).

## Betrachtete Alternativen

- **FastAPI (Python):** schlanker Kern, aber Admin, Auth und Mitgliederverwaltung
  müssten selbst gebaut werden – mehr Code, mehr Wartung.
- **TypeScript/Next.js:** modernes Frontend, jedoch ebenfalls Eigenbau bei
  Admin/Auth und ein zweites Sprach-Ökosystem im kleinen Team.

## Konsequenzen

**Positiv**
- Mitgliederverwaltung, Auth und Backend stehen sofort und robust bereit.
- Klarer, dokumentierter Migrationspfad zu OIDC/Keycloak ohne App-Umbau.
- Ein Sprach-Ökosystem (Python) für Logik, Tests und Betrieb.

**Negativ**
- Server-gerendertes Django ist weniger „SPA-modern“ als ein JS-Frontend.
- PostgreSQL muss betrieben werden (gelöst über Docker-Compose, siehe ADR 0020).
