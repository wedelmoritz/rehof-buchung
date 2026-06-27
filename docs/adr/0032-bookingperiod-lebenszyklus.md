# 0032 – BookingPeriod: eine Periode pro Jahr, statusgesteuerter Lebenszyklus

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 3 – Buchungsperiode & Lebenszyklus](../FACHKONZEPT.md#3-buchungsperiode--lebenszyklus).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Wunsch-Einreichung, Losung, Bestätigung und freie Buchung gehören fachlich zu
**einem** Buchungsjahr und müssen in einer klaren Reihenfolge ablaufen. Frühere
Modelle trennten „Losung“ und „buchbares Fenster“ in getrennte Objekte, was zu
mehreren Perioden pro Jahr und widersprüchlichen Zuständen führte (vgl. den
Migrations-Resilienz-Job, ADR 0022).

## Entscheidung

**Eine `BookingPeriod` pro Buchungsjahr** (`target_year` eindeutig), die ihren
gesamten Lebenszyklus über einen **Status** durchläuft (`booking/models.py:286`).

- **Status-Kette** als Konstanten `LIFECYCLE` (`models.py:304-326`); die
  Reihenfolge der Status `draft → … → ended` (plus `suspended`) ist im Fachkonzept
  § 3 gepflegt.
- **Aus den Terminen abgeleitet:** `compute_status` (`models.py:353`) leitet den
  Status aus `wishlist_open/close`, `draw_at`, `start/end` ab – führt aber bewusst
  **nur bis `lottery_review`**; der Schritt nach `lottery_done` ist **manuell**
  (Bestätigung, ADR 0008).
- **Vorwärts-Schaltung** durch den Cron (`run_due_lotteries`, ADR 0021): nie zurück,
  nie automatisch aus `lottery_review` heraus.
- **Normale Buchung** nur im Status `free_booking`; die Losung ist davon entkoppelt
  (ADR 0006). Quartiersgrenzen laufen über die Quartier-Saison, nicht über eigene
  Perioden (ADR 0012).

## Betrachtete Alternativen

- **Getrennte Objekte für Losung und Buchungsfenster:** mehrere Perioden pro Jahr,
  widersprüchliche Zustände (real aufgetreten → zusammengeführt).
- **Status frei manuell setzen:** fehleranfällig; die Ableitung aus Terminen + ein
  bewusster Bestätigungsschritt ist robuster.

## Konsequenzen

**Positiv**
- Ein klarer, terminbasierter Ablauf je Jahr; eindeutiger Zustand.
- Cron schaltet vorwärts, kritische Übergänge (Veröffentlichung) bleiben manuell.

**Negativ**
- Die Statussemantik (was ist in welchem Status erlaubt) muss überall konsistent
  geprüft werden.
- `target_year`-Eindeutigkeit erfordert Sorgfalt bei Migrationen auf Altdaten.
