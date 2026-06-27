# 0008 – Losung-Review-Workflow: vorläufig prüfen, bestätigen oder zurücknehmen

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 7 – Losungs-Workflow (Review)](../FACHKONZEPT.md#7-losungs-workflow-review).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Eine Losung greift tief ein (Zuteilungen, Karma-Fortschreibung, Benachrichtigungen).
Ein direktes „Live-Schalten“ wäre riskant: ein fehlerhafter Lauf (falscher Seed,
falsche Datenbasis) ließe sich nicht mehr einfangen, sobald Mitglieder bereits
informiert sind.

## Entscheidung

Ein Losdurchlauf wird zunächst **vorläufig** erzeugt und erst nach Prüfung
veröffentlicht. Umgesetzt im Paket `booking/services/` (Submodul `lottery_ops`):

- `run_period_lottery` legt Zuteilungen als `Allocation.provisional=True` an: sie
  **blockieren die Verfügbarkeit**, sind für Mitglieder aber **unsichtbar**
  (`period_result`/`my_bookings`/Übersicht filtern `provisional=False`). Status der
  Periode → `lottery_review`. Benachrichtigungen werden nur **vorbereitet**
  (`LotteryRun.notices`), nicht zugestellt. Der Vor-Zustand des Karmas wird als
  `LotteryRun.karma_snapshot` gesichert.
- `confirm_lottery` veröffentlicht: setzt `provisional=False`, stellt In-App- und
  E-Mail-Benachrichtigungen zu, Status → `lottery_done`. **Danach kein Undo.**
- `rollback_lottery` (nur unbestätigt) löscht die vorläufigen Zuteilungen, stellt
  das Karma aus `karma_snapshot` wieder her, Status → `lottery_ready`.
- Ein erneuter `run_period_lottery` rollt einen vorhandenen unbestätigten Lauf erst
  zurück (`_restore_factors`), damit sich Karma nicht aufsummiert.

Bedient wird das über `LotteryRunAdmin` (Aktionen Bestätigen/Zurücknehmen mit
Rückfrage); der Cron schaltet NIE automatisch aus `lottery_review` heraus.

## Betrachtete Alternativen

- **Direkt veröffentlichen:** kein Vier-Augen-Prinzip, kein gefahrloses Probelosen.
- **Voll transaktionales Undo nach Veröffentlichung:** sobald Mails raus sind, ist
  ein „Zurück“ in der Außenwirkung ohnehin nicht mehr sauber möglich.

## Konsequenzen

**Positiv**
- Gefahrloses Probelosen und Prüfen vor der Außenwirkung.
- Sauberes Zurückrollen inkl. Karma-Wiederherstellung, solange unbestätigt.

**Negativ**
- Zusätzlicher Zustand (`provisional`, `karma_snapshot`, `notices`) und ein
  bewusster Bestätigungsschritt.
- Nach Bestätigung endgültig – Fehler müssen vorher auffallen.
