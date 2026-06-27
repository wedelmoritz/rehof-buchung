# 0013 – Buchungs-Korrektheit über Zeilensperre (SELECT … FOR UPDATE)

## Status

Accepted (2026-06-26)

## Kontext

Beliebte Slots ziehen gleichzeitige Buchungsversuche an: Mehrere Mitglieder können im
selben Moment dasselbe Quartier zum selben Datum buchen wollen. Ohne Schutz
entstünden **Doppelbuchungen** (zwei Zuteilungen für denselben Slot) – ein
fachlicher Fehler, der nach außen sofort sichtbar wäre.

## Entscheidung

Die Spontanbuchung serialisiert konkurrierende Versuche über eine **Zeilensperre auf
der Quartier-Zeile** innerhalb einer Transaktion. In
`booking/services/booking_ops.py::book_spontaneous`:

- `transaction.atomic` umschließt Prüfung **und** Anlage.
- `Quarter.objects.select_for_update().filter(pk=quarter.pk).first()` sperrt die
  Quartier-Zeile, sodass parallele Versuche auf dasselbe Quartier
  nacheinander laufen; der zweite sieht die bereits angelegte Buchung und wird sauber
  abgewiesen (Rückgabe `(None, Fehlertext)`, kein Crash).

Abgesichert durch Race-Tests gegen echtes PostgreSQL:
`booking/tests_concurrency.py` (`TransactionTestCase`, echte Threads + `Barrier`):
20 gleichzeitige Buchungen desselben Slots → genau **eine** Zuteilung; 10
verschiedene Quartiere → alle 10 gelingen (keine falsche Blockade über Quartiere
hinweg). Auf SQLite ist `SELECT FOR UPDATE` wirkungslos, daher übersprungen –
ausgeführt im CI-PostgreSQL-Job (siehe ADR 0022).

## Betrachtete Alternativen

- **Optimistische Sperre/`unique`-Constraint:** ein Unique-Index über
  (Quartier, Tag) ist bei Zeiträumen/Überlappungen unhandlich; FOR UPDATE bildet die
  Belegungsprüfung natürlicher ab.
- **Anwendungs-Lock (z. B. in Python/Cache):** greift nicht über mehrere
  Gunicorn-Worker/Prozesse hinweg zuverlässig.
- **Keine Sperre, nur Prüfung:** Time-of-check/Time-of-use-Lücke → Doppelbuchung.

## Konsequenzen

**Positiv**
- Garantiert genau eine Buchung pro Slot unter echter Parallelität.
- Sperrt nur pro Quartier-Zeile – verschiedene Quartiere blockieren sich nicht.
- Durch Tests gegen echtes PostgreSQL belegt.

**Negativ**
- Verlässt sich auf PostgreSQL-Semantik (Produktions-DB); auf SQLite nicht prüfbar.
- Die Transaktion muss kurz bleiben, damit die Sperre auf heißen Slots nicht staut.
