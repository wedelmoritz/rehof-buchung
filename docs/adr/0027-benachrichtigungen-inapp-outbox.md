# 0027 – Benachrichtigungen: In-App plus entkoppelte E-Mail-Outbox

## Status

Accepted (2026-06-26)

## Kontext

Mehrere Ereignisse müssen Mitglieder erreichen (Losergebnis, Wartelisten-Platz frei,
Rechnung erstellt, Konto-Freischaltung). E-Mail-Versand im Request-Zyklus wäre
langsam und fehleranfällig (SMTP-Timeouts blockieren die Antwort), gerade bei
Massenmails. Mitglieder sollen E-Mails abbestellen können, ohne In-App-Hinweise zu
verlieren.

## Entscheidung

Zwei Kanäle, der E-Mail-Versand **entkoppelt** über eine Outbox-Warteschlange.

- **In-App:** `booking/models.py:Notification` – immer zugestellt, in der App
  sichtbar.
- **E-Mail entkoppelt:** `services.email_member` (`booking/services/notify.py`) stellt
  bei Opt-in (`Member.email_opt_in`) eine `OutboxEmail` in die Warteschlange. Das
  Kommando `send_outbox` (vom Scheduler regelmäßig aufgerufen, ADR 0021) versendet
  sie – unabhängig vom Request, gut für Massenmails. `OutboxEmail` trägt
  `attachment*`-Felder, sodass z. B. das Rechnungs-PDF mitgeschickt wird (ADR 0028).
- **Provider-neutral** über `EMAIL_*`/`PUBLIC_BASE_URL`; ohne `EMAIL_HOST` landet
  alles im Log (Konsole) – test-/vorführbar ohne Mailserver (`config/settings.py`).

## Betrachtete Alternativen

- **Nur In-App:** Mitglieder müssten die Seite aktiv prüfen; kein Push außerhalb.
- **Synchroner E-Mail-Versand im View:** blockiert die Antwort, skaliert nicht bei
  Massenmails, schlechter bei SMTP-Fehlern.
- **Task-Queue (Celery + Broker):** mächtiger, aber Overkill für den Umfang; die
  DB-Outbox + Scheduler genügt.

## Konsequenzen

**Positiv**
- Schnelle Requests; robuster, wiederholbarer Versand entkoppelt vom Web-Worker.
- In-App bleibt auch bei E-Mail-Opt-out erhalten; Anhänge (PDF) möglich.

**Negativ**
- Leichte Verzögerung (Versand erst beim nächsten Scheduler-Lauf).
- Idempotenz/Doppelversand-Schutz muss bei den auslösenden Ereignissen beachtet
  werden.
