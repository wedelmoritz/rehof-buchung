# 0046 – Observability: strukturiertes Logging, Sentry und Health-Endpoint

## Status

Accepted (2026-06-27)

## Kontext

Bisher gab es keine systematische Sicht auf den laufenden Betrieb: kein zentrales
Fehler-Tracking, kein definiertes Log-Format, und der Container-Healthcheck pingte
nur `/login/` (prüfte also nicht die Datenbank). Produktionsfehler fielen damit erst
auf, wenn ein Mitglied sich meldete. Für eine ehrenamtlich betriebene App ist die
Frage nicht „maximale Observability", sondern „mit minimalem Aufwand nicht mehr
blind sein".

## Entscheidung

Drei kleine, zueinander passende Bausteine:

1. **Strukturiertes Logging nach stdout** (`settings.LOGGING`): ein Console-Handler
   mit Format `{asctime} {levelname} {name}: {message}`; Docker/Caddy sammeln stdout.
   Level über `LOG_LEVEL` (Default `INFO`, in `DEBUG` `DEBUG`). `django.request` auf
   `WARNING`, damit 4xx/5xx sichtbar werden; eigene Logger `booking`/`shop`.

2. **Fehler-Tracking mit Sentry**, **gated** über `SENTRY_DSN` – **ohne DSN aus**
   (gleiche Konvention wie VAPID/Mollie-Sandbox). Bewusst **`send_default_pii=False`**
   (keine personenbezogenen Daten an Sentry, DSGVO/ADR 0043); `traces_sample_rate`
   per Env (Default 0 = nur Fehler, kein Performance-Sampling). Der Init ist in
   `try/except` gekapselt: fehlt `sentry-sdk`, läuft die App normal weiter.

3. **Health-Endpoint `/healthz/`** (ohne Login, von der Aktivierungs-Sperre
   ausgenommen): führt einen trivialen DB-Query aus und liefert `200 {"status":"ok"}`
   bzw. `503` bei DB-Problemen. Der **Container-Healthcheck** zeigt damit auch eine
   weggebrochene DB als `unhealthy`; ein **externer Uptime-Dienst** (z.B. UptimeRobot)
   kann denselben Endpoint pingen.

## Betrachtete Alternativen

- **Voller Metrics-Stack (Prometheus/Grafana/Loki):** verworfen – für einen
  Ein-Server-Betrieb mit kleinem Team unverhältnismäßig viel Betriebslast. stdout-Logs
  + Sentry + Uptime-Ping decken die realen Bedürfnisse (Fehler sehen, „läuft es noch").
- **Sentry immer an / Key im Code:** verworfen – DSN ist Env-Konfiguration; ohne DSN
  muss die App (Dev/Test/Self-Hoster ohne Sentry) unverändert laufen.
- **PII an Sentry senden (Default):** verworfen – Datensparsamkeit (ADR 0043);
  Stacktraces ohne Nutzerdaten genügen zur Diagnose.
- **Healthcheck weiter nur `/login/`:** verworfen – prüft die DB nicht; ein DB-Ausfall
  bliebe „grün". `/healthz/` mit echtem DB-Query ist aussagekräftiger.
- **DB-Query-Healthcheck mit ORM-Modell:** verworfen zugunsten `SELECT 1` (leicht,
  ohne Migrationsabhängigkeit, auch bei leerer DB aussagekräftig).

## Konsequenzen

**Positiv**
- Produktionsfehler landen (mit DSN) zentral in Sentry statt nur im Log.
- Einheitliche, maschinenlesbare Logs; Log-Level ohne Code-Änderung steuerbar.
- DB-bewusster Healthcheck → kaputter Start/DB-Ausfall sofort sichtbar.
- Alles optional/gated: Dev/Test/Self-Hosting laufen ohne Zusatzkonfiguration.

**Negativ / Grenzen**
- Kein Metrics/Tracing-Dashboard – bewusst (Aufwand). `traces_sample_rate` lässt sich
  später hochdrehen, wenn Performance-Insights gebraucht werden.
- Externes Uptime-Monitoring ist **Betriebs-Setup** (nicht im Repo) – im README als
  Schritt dokumentiert.
- `sentry-sdk` ist eine neue Abhängigkeit (nur aktiv mit DSN).
