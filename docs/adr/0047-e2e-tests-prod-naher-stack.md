# 0047 – End-to-End-Tests gegen einen prod-nahen Docker-Stack

## Status

Accepted (2026-06-27)

## Kontext

Die Teststrategie (ADR 0022) deckt zwei Ebenen ab: reine Logik (pytest, ohne DB)
und Django-Integrationstests gegen echtes PostgreSQL. Beide laufen aber
**in-process** über den Django-Test-Client – die echte Naht aus **gunicorn,
WhiteNoise (gehashte Statics/Manifest), Cookies, Redirects und clientseitigem
JavaScript** (AJAX-Navigation, Offline-Warenkorb, Toasts) wird dabei nicht
ausgeführt. Genau dort entstehen Fehler, die kein `manage.py test` sieht. Es fehlte
ein End-to-End-Test und eine Testumgebung, die der Produktion entspricht.

## Entscheidung

Eine dritte Testebene: **End-to-End-Smoke-Tests mit Playwright** gegen einen
**prod-nahen Docker-Stack**.

- **Prod-naher Stack** (`docker-compose.ci.yml`): dasselbe Image (`build: .`),
  derselbe Entrypoint (warte auf DB → `migrate` → gunicorn), `DEBUG=0`, echtes
  PostgreSQL – also die produktive Kette. Unterschiede nur fürs Testen: **kein
  Caddy/TLS** (direkt über `http://localhost:8000`), Port veröffentlicht, und die
  **Secure-Cookie-Flags aus** (sie gehören zum TLS-Edge, den die CI nicht hat;
  dafür sind `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` per Env abschaltbar).
- **Tests** in `tests_e2e/` (Python + `pytest-playwright`, getrennt von der
  App-Abhängigkeit über `requirements-e2e.txt`). Bewusst **wenige, robuste**
  Smoke-Tests der kritischen Pfade: Health, Anmeldung (richtig/falsch),
  Buchungs-Seite lädt, **Geld-Pfad Hofladen** (Artikel → Kasse → Rechnung).
- **CI** (neuer Job `e2e`): Stack bauen/starten, auf **`/healthz/`** warten
  (ADR 0046), `seed_demo --testdata` für stabile Konten (`test`/`admin`/
  `verwaltung`), Browser installieren, Playwright laufen lassen, am Ende abräumen.
- **Datengrundlage:** das bestehende, deterministische `seed_demo --testdata`
  liefert reproduzierbare Konten und Stammdaten – kein eigener Fixtures-Apparat.

## Betrachtete Alternativen

- **`StaticLiveServerTestCase` (Djangos In-Process-Live-Server):** einfacher, aber
  nicht prod-nah – kein gunicorn, kein Image/Entrypoint, kein WhiteNoise-Manifest.
  Der explizite Wunsch war eine *produktionsidentische* Umgebung.
- **Voller Stack inkl. Caddy/TLS in der CI:** verworfen – echtes TLS/Domain/Cert in
  der CI ist Aufwand ohne Mehrwert für die App-Tests; gegen gunicorn über http zu
  testen deckt die App-Schicht ab. Caddy ist reiner TLS-Edge.
- **E2E in Node/TypeScript:** verworfen zugunsten **Python-Playwright** – bleibt im
  Python-Ökosystem des Teams (pytest), keine zweite Toolchain im Repo.
- **Vollständige User-Journeys statt Smoke:** bewusst nicht – breite, fragile E2E
  sind teuer und flaky. Wenige stabile Pfade + die schnellen Integrationstests sind
  das bessere Verhältnis; weitere Flows können gezielt ergänzt werden.

## Konsequenzen

**Positiv**
- Die reale Browser-/Server-Naht (Cookies, Statics, JS, gunicorn) ist abgedeckt.
- Die Testumgebung entspricht der Produktion (Image/Entrypoint/DB) – Fehler beim
  Container-Start/Migrate/Statics fallen in der CI auf, nicht erst auf dem VPS.
- Synergie mit ADR 0046: `/healthz/` ist das Startsignal für die Tests.

**Negativ / Grenzen**
- Der E2E-Job ist langsamer (Image-Build + Browser-Download) als die übrigen Jobs;
  er läuft parallel und blockiert das schnelle Logik-Signal nicht.
- `pytest-playwright` ist eine zusätzliche (test-only) Abhängigkeit.
- Die Secure-Cookie-Flags sind in der Testumgebung aus – bewusst, da kein TLS;
  die Prod-Defaults bleiben `True`.
