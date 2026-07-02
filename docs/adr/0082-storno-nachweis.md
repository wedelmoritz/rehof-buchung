# 0082 – Stornierte Buchungen sichtbar machen (schlanker Storno-Nachweis)

## Status

Accepted (2026-07-02)

## Kontext

Beim Stornieren wird die `Allocation` **gelöscht** (das gibt Verfügbarkeit und Tage
sofort wieder frei). Aus Mitglieds-Sicht (Tester-Feedback #30) fehlte danach jede
Spur: „Meine Buchungen“ zeigte die stornierte Buchung nicht mehr – man war unsicher,
ob sie wirklich raus ist.

## Entscheidung

**Ein schlanker Storno-Nachweis statt Soft-Delete.**

- Neues Modell `booking.CancellationLog` (Snapshot: `member`, `quarter_name`,
  `start`, `end`, `persons`, `source`, `cancelled_at`). `services.cancel_allocation`
  legt den Eintrag an, **bevor** die `Allocation` gelöscht wird.
- „Meine Buchungen“ zeigt einen **eingeklappten** Abschnitt **„Zuletzt storniert“**
  (letzte 90 Tage) mit Quartier/Zeitraum/Personen/Storno-Zeitpunkt.
- **DSGVO:** Die Aufbewahrung (`run_data_retention`) löscht Storno-Nachweise nach der
  Frist `RETENTION_SWAP_WAITLIST_DAYS` (kurzlebiger Komfort, keine Buchhaltung).

## Betrachtete Alternativen

- **Soft-Delete der `Allocation`** (`cancelled_at`/`status`): invasiv – **alle**
  Belegungs-, Regel- und Kalenderabfragen müssten `cancelled` ausschließen (hohe
  Regressionsgefahr in genau dem sicherheitskritischen Pfad). Verworfen zugunsten des
  separaten, risikoarmen Logs.
- **Gar nichts** (Status quo): unbefriedigend für die Mitglieds-Sicherheit.

## Konsequenzen

**Positiv** – Mitglieder sehen, dass ihre Stornierung wirklich erfolgt ist; die
Belegungs-/Regel-Logik bleibt völlig unberührt (der Nachweis ist reine Anzeige).
Effizient (eine Zeile beim Stornieren, ein gefilterter Load in „Meine Buchungen“).
Migration `0049_cancellationlog`. **Grenzen** – der Nachweis ist bewusst kurzlebig
(90 Tage Anzeige, Retention-Pruning) und nicht als Historie/Buchhaltung gedacht.
