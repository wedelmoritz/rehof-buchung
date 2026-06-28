"""Django-Settings – konfiguriert über Umgebungsvariablen (.env).

Sicherheitsrelevante Defaults sind auf Produktion ausgelegt; mit DEBUG=1
werden sie für lokale Entwicklung gelockert.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Korrekter MIME-Typ für das PWA-Manifest (sonst octet-stream). Greift sowohl im
# Dev-Static-Server als auch bei WhiteNoise (initialisiert aus mimetypes).
mimetypes.add_type("application/manifest+json", ".webmanifest", True)


def env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(int(default))).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get("SECRET_KEY", "unsafe-dev-key-change-me")
DEBUG = env_bool("DEBUG", False)

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]
# Loopback immer erlauben: damit der Container-Healthcheck (und der interne
# Zugriff hinter Caddy) auch in Produktion funktioniert, ohne die Domain zu kennen.
for _h in ("127.0.0.1", "localhost"):
    if _h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_h)
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    # Fachlich gegliederte Admin-Site (ADR 0049) statt "django.contrib.admin".
    "booking.admin_apps.RehofAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "booking",
    "shop",
    "axes",  # Brute-Force-Schutz für Anmeldungen
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Sperrt eingeloggte Nutzer ohne Mitglieds-Profil aus (Freischaltung nötig).
    "booking.middleware.ActivationGateMiddleware",
    # django-axes MUSS als letztes stehen (verarbeitet Login-Versuche).
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "booking.context_processors.roles",
                "booking.context_processors.legal",
                "booking.context_processors.push",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Datenbank: Postgres über DATABASE_URL, sonst SQLite (z.B. für Tests) ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL:
    import dj_database_url
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
    # Persistente Verbindungen (conn_max_age) + Health-Check: eine vom Server
    # geschlossene/abgelaufene Verbindung wird vor dem Request einmal geprüft und
    # neu aufgebaut, statt unter Last einen Fehler zu werfen.
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Authentifizierung -----------------------------------------------------
# Klassischer Django-Login mit sauber gehashtem Passwort. Angemeldet wird mit
# E-Mail ODER Benutzername (eigenes Backend). django-axes sperrt nach zu vielen
# Fehlversuchen. NAHTSTELLE für später: Hier ließe sich ein OIDC-Backend (z.B.
# Keycloak via mozilla-django-oidc) ergänzen, ohne die übrige App zu ändern.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",          # muss zuerst stehen
    "booking.auth.EmailOrUsernameModelBackend",     # Login per E-Mail/Benutzername
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "overview"
LOGOUT_REDIRECT_URL = "login"

# --- Brute-Force-Schutz (django-axes) --------------------------------------
AXES_FAILURE_LIMIT = 5            # so viele Fehlversuche …
AXES_COOLOFF_TIME = 1            # … dann 1 Stunde gesperrt
AXES_RESET_ON_SUCCESS = True
# Gesperrt wird die Kombination aus Benutzer UND IP – schützt das Zielkonto,
# ohne dass ein Angreifer fremde Konten flächendeckend aussperren kann.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
# Erfolgreiche An-/Abmeldungen nicht protokollieren (spart DB-Schreiblast); die
# Fehlversuche fürs Lockout werden weiterhin erfasst.
AXES_DISABLE_ACCESS_LOG = True

# --- Sitzungs-/Cookie-Härtung ----------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_REFERRER_POLICY = "same-origin"

# --- E-Mail (provider-neutral über die Umgebung) ---------------------------
# Ohne EMAIL_HOST landet alles im Container-Log (Konsole) – so läuft
# Entwicklung/Tests ohne Zugangsdaten. In Produktion EMAIL_* in der .env setzen.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "Re:Hof <noreply@localhost>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
# Öffentliche Basis-URL für Links in E-Mails (z.B. https://rehof.example.de).
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
    EMAIL_TIMEOUT = 20
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- Web-Push (mobil, PWA) -------------------------------------------------
# VAPID-Schlüsselpaar für Web-Push. Ohne beide Schlüssel ist Push einfach AUS
# (kein Zwang – wie der Mollie-Sandbox-Default). Erzeugen z.B. mit
# `python manage.py vapid_keys`. Der öffentliche Schlüssel geht an den Browser,
# der private bleibt geheim (.env). `VAPID_ADMIN_EMAIL` ist der Kontakt im
# VAPID-Claim (mailto:) gegenüber dem Push-Dienst.
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_ADMIN_EMAIL = os.environ.get("VAPID_ADMIN_EMAIL", "")
PUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

# --- Optionales Redis (Cache + Sessions + Axes-Lockout) --------------------
# Standardmäßig AUS (DB-Sessions, lokaler Cache). Wird REDIS_URL gesetzt UND der
# redis-Dienst gestartet (docker compose --profile cache), entlastet das die DB
# bei vielen gleichzeitigen Zugriffen: Sessions und Brute-Force-Zähler liegen
# dann im gemeinsamen Cache statt in PostgreSQL.
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
    # `cached_db` statt reinem `cache`: lesen aus Redis (entlastet die DB bei jedem
    # Request), ABER persistent in der DB. Fällt Redis aus oder wird neu gestartet,
    # bleiben die Sitzungen erhalten (kein Massen-Logout) – nur kurz wieder DB-Lese.
    # Bestehende DB-Sitzungen werden weiter gelesen → nahtloser Umstieg.
    SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
    SESSION_CACHE_ALIAS = "default"
    # Brute-Force-Zähler im gemeinsamen Cache (statt je Request in der DB).
    AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"

# --- Lokalisierung ---------------------------------------------------------
LANGUAGE_CODE = "de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

# --- Static ----------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # In Produktion gehashte, langfristig cachebare Dateien (Manifest). In
        # DEBUG/Tests die einfache Storage, damit {% static %} ohne vorheriges
        # collectstatic auflösbar bleibt (sonst „Missing staticfiles manifest“).
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
# WhiteNoise: PWA-Manifest mit korrektem MIME-Typ ausliefern.
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sicherheits-Härtung (greift in Produktion, d.h. wenn DEBUG=0) ----------
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)  # Caddy terminiert TLS
    # Secure-Cookies gehören zum TLS-Edge (Caddy). Default an; für eine prod-nahe
    # Testumgebung OHNE TLS (E2E-CI über http) per Env abschaltbar (ADR 0047).
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Hinter Caddy: TLS endet beim Proxy, der per X-Forwarded-Proto signalisiert,
    # dass die ursprüngliche Anfrage HTTPS war. So erkennt Django sie als sicher.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Caddy setzt X-Forwarded-Host; damit baut Django absolute URLs unter der
    # öffentlichen Domain (statt der internen Container-Adresse).
    USE_X_FORWARDED_HOST = True
    X_FRAME_OPTIONS = "DENY"
    # Hinter genau einem Proxy (Caddy): echte Client-IP aus X-Forwarded-For, damit
    # django-axes nicht alle Anfragen unter der Proxy-IP zusammenfasst.
    AXES_IPWARE_PROXY_COUNT = 1


# --- DSGVO: Aufbewahrungs-/Löschfristen (Tage), per Env überschreibbar -------
# Das Kommando `cleanup_data` (vom Scheduler täglich aufgerufen) löscht bzw.
# pseudonymisiert anhand dieser Fristen. Rechnungs-/Zahlungsdaten (10 Jahre,
# §147 AO / §14b UStG) bleiben bewusst unangetastet (siehe ADR 0043).
def env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


RETENTION_OUTBOX_DAYS = env_int("RETENTION_OUTBOX_DAYS", 90)       # versendete Mails (inkl. Anhang)
RETENTION_NOTIFICATION_DAYS = env_int("RETENTION_NOTIFICATION_DAYS", 180)  # In-App-Benachrichtigungen
RETENTION_BANK_RAW_DAYS = env_int("RETENTION_BANK_RAW_DAYS", 90)   # Kontoauszug-Rohzeile leeren
RETENTION_BEDS24_DAYS = env_int("RETENTION_BEDS24_DAYS", 180)      # Beds24-Migrations-Importe
RETENTION_BANKIMPORT_DAYS = env_int("RETENTION_BANKIMPORT_DAYS", 365)  # Import-Lauf-Metadaten
RETENTION_SWAP_WAITLIST_DAYS = env_int("RETENTION_SWAP_WAITLIST_DAYS", 180)  # erledigte Wechsel/Warteliste
RETENTION_WISH_YEARS = env_int("RETENTION_WISH_YEARS", 2)          # Wünsche beendeter Perioden
RETENTION_AXES_DAYS = env_int("RETENTION_AXES_DAYS", 30)           # Brute-Force-Fehlversuche


# --- Observability: Logging + Fehler-Tracking (ADR 0046) -------------------
# Strukturierte Logs nach stdout – Docker/Caddy sammeln sie. Level per Env.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # 5xx/Anfrage-Fehler sichtbar machen (sonst schluckt Django sie still).
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "booking": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "shop": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# Sentry (Fehler-Tracking) ist nur mit gesetztem SENTRY_DSN aktiv – sonst aus,
# wie VAPID/Mollie. **Keine PII** an Sentry (send_default_pii=False; DSGVO/ADR 0043).
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
            send_default_pii=False,
            environment=os.environ.get(
                "SENTRY_ENVIRONMENT", "dev" if DEBUG else "production"),
            release=os.environ.get("SENTRY_RELEASE", "") or None,
        )
    except Exception:  # sentry-sdk nicht installiert → ohne Tracking weiter
        pass
