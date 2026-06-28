# Backend-2FA (Zwei-Faktor) ein-/ausschalten

Das **Backend `/admin/`** (Admin-Rolle) ist standardmäßig per **Zwei-Faktor (TOTP)**
geschützt (ADR 0061). Gesteuert wird das über **eine** Umgebungsvariable:

```
ADMIN_OTP_REQUIRED   1 = an (Default in Produktion)   ·   0 = aus
```

> Betrifft **nur** das Backend `/admin/` (Superuser/Admin). **Mitglieder**, die
> Web-App und das Verwaltungs-Dashboard (`/verwaltung/`) sind **nicht** betroffen.

---

## 🚑 Ausgesperrt? So kommst du sofort wieder rein

Du hast zwei einfache Wege – wähle einen:

### Variante A – 2FA jetzt AUSschalten (gewünschter Zustand)

```bash
# 1) In der .env setzen (Datei im Projektverzeichnis):
ADMIN_OTP_REQUIRED=0

# 2) Den web-Container mit der neuen Einstellung neu starten:
docker compose up -d

# 3) Im Backend ganz normal mit Benutzername + Passwort anmelden.
```

> **Wichtig:** Dass die `.env`-Variable im Container ankommt, setzt diese Version
> voraus (`docker-compose.yml` reicht `ADMIN_OTP_REQUIRED` durch). Läuft bei dir noch
> eine ältere Version, vorher aktualisieren:
> ```bash
> git pull && docker compose up -d --build
> ```
> (Oder behelfsweise in `docker-compose.yml` beim `web`-Dienst die Zeile
> `ADMIN_OTP_REQUIRED: ${ADMIN_OTP_REQUIRED:-1}` ergänzen und `docker compose up -d`.)

### Variante B – mit 2FA reinkommen (ohne es abzuschalten)

Falls du 2FA lieber gleich nutzen willst, richte ein Gerät ein und melde dich mit
Code an – **kein** Neustart/Redeploy nötig:

```bash
docker compose exec web python manage.py admin_otp_setup --user DEIN_BENUTZERNAME
```

Den angezeigten **QR-Code** mit einer Authenticator-App scannen (z. B. Aegis,
FreeOTP, Google Authenticator). Beim nächsten Backend-Login zusätzlich den
**6-stelligen Code** eingeben.

---

## 2FA einfach AUSschalten

```bash
# .env:
ADMIN_OTP_REQUIRED=0
docker compose up -d
```

Danach reicht im Backend Benutzername + Passwort.

## 2FA einfach (wieder) EINschalten

```bash
# 1) Für JEDES Admin-Konto einmalig ein TOTP-Gerät einrichten (sonst Lockout!):
docker compose exec web python manage.py admin_otp_setup --user DEIN_BENUTZERNAME
#    -> QR-Code in der Authenticator-App scannen.

# 2) In der .env einschalten und neu starten:
ADMIN_OTP_REQUIRED=1
docker compose up -d
```

Ab jetzt verlangt `/admin/` zusätzlich den 6-stelligen Code.

> **Reihenfolge merken:** erst Gerät einrichten (Schritt 1), dann einschalten
> (Schritt 2). Wer zuerst einschaltet, ohne ein Gerät zu haben, sperrt sich aus –
> dann hilft Variante A oder B oben.

---

## Weitere Handgriffe

- **Zweiten Faktor verloren / Handy weg:** Gerät zurücksetzen und neu einrichten:
  ```bash
  docker compose exec web python manage.py admin_otp_setup --user DEIN_BENUTZERNAME --reset
  ```
- **Mehrere Admins:** `admin_otp_setup` je Konto einmal ausführen.
- **Lokale Entwicklung (`DEBUG=1`):** 2FA ist dort standardmäßig **aus** – kein
  Setup nötig.

---

## Wie es funktioniert (kurz)

- `config/settings.py`: `ADMIN_OTP_REQUIRED = env_bool("ADMIN_OTP_REQUIRED", not DEBUG)`
  – Default also **an in Produktion**, **aus in der Entwicklung/Tests**.
- Die Backend-Site (`booking/admin_site.py`, `RehofAdminSite`) erbt von
  `OTPAdminSite` und verlangt in `has_permission` zusätzlich `request.user.
  is_verified()` – **aber nur**, wenn `ADMIN_OTP_REQUIRED` gesetzt ist.
- `docker-compose.yml` reicht `ADMIN_OTP_REQUIRED` an den `web`-Container durch
  (Default `1`; ein **leerer** Wert würde 2FA ausschalten – daher nie leer setzen).

Siehe auch [ADR 0061](adr/0061-sicherheits-haertungspaket.md) und
[DEPLOYMENT.md § 3.5](DEPLOYMENT.md).
