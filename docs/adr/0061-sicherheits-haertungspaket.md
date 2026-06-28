# 0061 – Sicherheits-Härtungspaket (Defense in Depth)

## Status

Accepted (2026-06-28)

> **Leitlinie:** IT-Sicherheit – sicherer Datenzugriff, **Vertraulichkeit** und
> **Integrität** – geht vor Effizienz. Die Maßnahmen sind nach Wirkung priorisiert
> (P1 > P2 > P3) und schichtweise umgesetzt (Transport/Header · App-Konfiguration ·
> Authentifizierung · Autorisierung · Daten-at-Rest · Lieferkette · Monitoring).

## Kontext

Die App verarbeitet personenbezogene Daten (Mitglieder, Gäste, IBAN, Rechnungen)
und läuft als selbst gehosteter Docker-Stack hinter Caddy. Vor dem breiteren
Einsatz wurde der gesamte Bestand gegen Stand der Technik / OWASP-Best-Practices
geprüft. Schon vorhanden waren u. a.: django-axes (Brute-Force), gehärtete Cookies
(HttpOnly/SameSite/Secure), `X_FRAME_OPTIONS=DENY`, CSV-Formel-Injektionsschutz,
XXE-Schutz im CAMT-Parser, token-/HMAC-geschützte Terminal-Endpunkte, serverseitige
Mollie-Webhook-Verifikation, DSGVO-Aufräumen. Dieses Paket schließt die in der
Analyse gefundenen Lücken.

## Entscheidung

Umsetzung in Batches; gemeinsame Klammer dieser ADR.

### P1 – Fundament

1. **Django 5.1 → 5.2 LTS.** 5.1 verliert Mitte 2026 den Sicherheits-Support; 5.2
   ist LTS (Support bis 2028). Hebt `requirements.txt`/`pyproject.toml`/`uv.lock`.
2. **Fail-closed `SECRET_KEY`-Wächter.** In Produktion (`DEBUG=0`) bricht der Start
   hart ab (`ImproperlyConfigured`), wenn der Schlüssel fehlt, der Default ist oder
   < 50 Zeichen hat. Ein bekannter/schwacher Schlüssel erlaubt Session-/Signatur-
   Fälschung – lieber nicht starten als unsicher laufen.
3. **Zwei-Faktor (TOTP) fürs Backend/Admin.** `django-otp` + `django_otp.plugins.
   otp_totp/otp_static`, `OTPMiddleware`. Die `RehofAdminSite` erbt von
   `OTPAdminSite` (Token-Abfrage in der Anmeldemaske) und erzwingt in
   `has_permission` zusätzlich `request.user.is_verified()` – **aber nur**, wenn
   `ADMIN_OTP_REQUIRED` gesetzt ist (Default: `not DEBUG`, also Produktion an,
   Tests/Entwicklung aus). So bleiben die vielen `force_login`-Backend-Tests grün.
   Einrichtung out-of-band über `manage.py admin_otp_setup --user <name>` (legt ein
   bestätigtes Gerät an, gibt `otpauth://`-URI + ASCII-QR aus). Per Env temporär
   abschaltbar, falls die Geräteeinrichtung noch aussteht.

   > **Begründung der Test-Gating-Wahl:** `force_login` umgeht den OTP-Login. Würde
   > 2FA hart erzwungen, müsste jeder Backend-Test ein verifiziertes Gerät mitführen.
   > Das Env-Gate (`ADMIN_OTP_REQUIRED`, Default `not DEBUG`) trennt die Erzwingung
   > sauber von der Testbarkeit, ohne in Produktion ein Schlupfloch zu lassen.

## Betrachtete Alternativen

- **2FA über ein Drittpaket mit eigener Login-Maske (z. B. two-factor):** verworfen –
  `django-otp` ist schlank, gut gepflegt und integriert sich direkt in die bestehende
  custom `AdminSite`, ohne den Mitglieder-Login (E-Mail/Benutzername + axes) zu berühren.
- **2FA auch für den Mitglieder-Login:** bewusst (vorerst) nicht – höchster Hebel ist
  das Backend (Vollzugriff auf alle Daten). Mitglieder-2FA bleibt möglicher Folgeschritt.
- **`SECRET_KEY`-Prüfung nur als Warnung loggen:** verworfen – ein schwacher Schlüssel
  ist ein kritischer Vertraulichkeits-/Integritätsbruch; fail-closed ist angemessen.

## Konsequenzen

**Positiv**
- Backend-Übernahme erfordert zusätzlich den zweiten Faktor (Phishing-/Passwort-Leak-
  Schutz für das mächtigste Konto).
- Produktion kann nicht mehr versehentlich mit unsicherem `SECRET_KEY` starten.
- Aktueller, sicherheitsunterstützter Django-LTS-Stand.

**Negativ / Grenzen**
- Vor dem ersten Backend-Login in Produktion muss `admin_otp_setup` gelaufen sein
  (sonst sperrt sich der einzige Admin aus). Notnagel: `ADMIN_OTP_REQUIRED=0` setzen,
  Gerät einrichten, wieder anschalten. Im Deployment-Runbook dokumentiert.
- Geht der zweite Faktor verloren, muss ein Shell-Zugang das Gerät zurücksetzen
  (`admin_otp_setup --reset`) – akzeptabel für den kleinen Betreiberkreis.
