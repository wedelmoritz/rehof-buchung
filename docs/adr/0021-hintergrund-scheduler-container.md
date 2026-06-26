# 0021 – Hintergrund-Scheduler-Container statt System-Cron

## Status

Accepted (2026-06-26)

## Kontext

Mehrere Aufgaben laufen zeitgesteuert: fällige Losungen ausführen, monatliche
Hofladen-Rechnungen erstellen, die E-Mail-Outbox versenden, Verwaltungs-Mails. Ein
klassischer System-Cron auf dem Host müsste die Container-Umgebung (Python, Env,
DB-URL) nachbauen und wäre vom App-Deployment entkoppelt.

## Entscheidung

Ein eigener **`cron`-Container** aus demselben Image führt die geplanten Kommandos
aus (`docker-compose.yml`, Service `cron`).

- Überschreibt den Entrypoint mit `python manage.py run_scheduler` (kein Webserver).
- Wartet via `depends_on: web (service_healthy)`, bis Migrationen durch sind.
- Intervall über `CRON_INTERVAL_SECONDS` (Default 900 = 15 min).
- `run_scheduler` ruft regelmäßig die fälligen Kommandos auf: `run_due_lotteries`
  (Perioden vorwärtsschalten/auslosen), `generate_monthly_invoices`,
  `send_outbox` (E-Mail-Versand entkoppelt vom Request), `notify_admins_upcoming`.

So gehören Zeitsteuerung und App zum **gleichen Deployment** (gleiches Image,
gleiche Env).

## Betrachtete Alternativen

- **System-Cron auf dem Host:** muss Container-Env nachbauen; getrennt vom Deployment;
  fehleranfälliger bei Updates.
- **Celery/Beat + Broker:** mächtige Task-Queue, aber für wenige periodische Jobs
  überdimensioniert (zusätzlicher Broker/Worker).
- **Lange laufende Aufgaben im Web-Worker:** würde Gunicorn-Worker blockieren (z. B.
  eine große Losung) – bewusst vermieden.

## Konsequenzen

**Positiv**
- Zeitsteuerung im selben Image/Deployment; keine Host-Konfiguration nötig.
- Schwere Aufgaben (Losung, Massenmail) belasten die Web-Worker nicht.
- Einfaches Modell ohne zusätzlichen Broker.

**Negativ**
- Der Scheduler pollt im Intervall statt sekundengenau zu cronen (für diesen
  Anwendungsfall ausreichend).
- Ein weiterer Dauer-Container (geringer Ressourcenbedarf auf dem VPS).
