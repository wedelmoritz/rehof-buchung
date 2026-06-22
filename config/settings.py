"""Django-Settings – konfiguriert über Umgebungsvariablen (.env).

Sicherheitsrelevante Defaults sind auf Produktion ausgelegt; mit DEBUG=1
werden sie für lokale Entwicklung gelockert.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


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
    "django.contrib.admin",
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
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
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
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sicherheits-Härtung (greift in Produktion, d.h. wenn DEBUG=0) ----------
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)  # Caddy terminiert TLS
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
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
