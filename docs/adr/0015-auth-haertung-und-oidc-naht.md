# 0015 – Auth-Härtung: E-Mail/Benutzername-Login, Brute-Force-Schutz, Aktivierungs-Gate

## Status

Accepted (2026-06-26) – OIDC/Keycloak-Anbindung: Proposed (Naht vorhanden, nicht umgesetzt)

## Kontext

Mitglieder registrieren sich selbst; bis zur Freischaltung dürfen sie nichts buchen.
Anmeldungen müssen gegen Brute-Force geschützt sein, ohne dass Angreifer fremde
Konten flächendeckend aussperren können. Login soll niederschwellig sein (E-Mail
**oder** Benutzername). Perspektivisch soll ein zentrales Login (OIDC/Keycloak)
andockbar sein, ohne die App umzubauen.

## Entscheidung

Mehrere abgestimmte Bausteine in `config/settings.py` und `booking/`:

- **Login per E-Mail ODER Benutzername:** eigenes Backend
  `booking/auth.py:EmailOrUsernameModelBackend` (in `AUTHENTICATION_BACKENDS`).
- **Brute-Force-Schutz (django-axes):** Sperre nach 5 Fehlversuchen für 1 h,
  gesperrt wird die Kombination **Benutzer + IP** (`AXES_LOCKOUT_PARAMETERS`),
  `AXES_RESET_ON_SUCCESS=True`; hinter Caddy echte Client-IP über
  `AXES_IPWARE_PROXY_COUNT=1` (`settings.py:122-131`, `222`).
- **Aktivierungs-Gate:** `booking/middleware.py:ActivationGateMiddleware` sperrt
  eingeloggte Nutzer ohne `Member`-Profil aus und leitet auf `pending` um
  (Verwaltungs-/Admin-Konten ausgenommen).
- **Cookie-/Session-Härtung:** HttpOnly, SameSite=Lax, in Produktion Secure +
  HSTS + `SECURE_PROXY_SSL_HEADER` (`settings.py:133-138`, `204-222`).
- **OIDC-Naht:** `AUTHENTICATION_BACKENDS` ist die Einhängestelle; der Kommentar
  markiert, wo ein Keycloak-Backend (z. B. `mozilla-django-oidc`) ergänzt würde
  (`settings.py:109-117`). **Noch nicht umgesetzt.**

## Betrachtete Alternativen

- **Nur Standard-Django-Login ohne axes:** kein Brute-Force-Schutz.
- **Lockout nur per IP oder nur per Benutzer:** entweder Mitbenutzer hinter
  gemeinsamer IP treffen oder gezieltes Aussperren fremder Konten ermöglichen.
- **Sofort externes IdP (Keycloak):** zum jetzigen Stand unnötiger Betriebsaufwand;
  die Naht genügt, bis der Bedarf real ist.

## Konsequenzen

**Positiv**
- Robuster, gut konfigurierter Login-Schutz mit klaren Defaults.
- Selbstregistrierung ohne Risiko: ohne Freischaltung kein Zugriff.
- Migrationspfad zu OIDC steht bereit, ohne die App heute zu belasten.

**Negativ**
- Mehrere Sicherheitsbausteine (axes, Middleware, Backend) müssen zusammen korrekt
  konfiguriert bleiben.
- Die OIDC-Anbindung ist noch offen (Status Proposed für diesen Teil).
