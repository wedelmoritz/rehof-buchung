# 0022 – Zwei-Ebenen-Teststrategie und CI inkl. Migrations-Resilienz

## Status

Accepted (2026-06-26)

## Kontext

Die Kernregeln (Losung, Verfügbarkeit, Buchungsregeln) müssen schnell und oft prüfbar
sein; gleichzeitig brauchen DB-nahe Logik (Service-Layer, Sperren, Migrationen) und
das Zusammenspiel mit echtem PostgreSQL eine produktionsnahe Absicherung. Zwei
Produktionsfehler entstanden früher gerade dort, wo ein frischer Testlauf nichts sah:
bei der **Vorwärts-Migration einer bereits befüllten Alt-DB**.

## Entscheidung

Eine **zweistufige Teststrategie** (passend zur Schicht-Trennung aus ADR 0002),
abgesichert durch CI mit **drei** Jobs (`.github/workflows/tests.yml`):

1. **Reine Logik (ohne DB):** `pytest tests/` – Losung, Verfügbarkeit, Regeln,
   Fairness, Beds24 in Sekunden (Job „Reine Logik“).
2. **Integration gegen echtes PostgreSQL:** `manage.py test booking shop` inkl.
   `manage.py check` und `makemigrations --check --dry-run`; Integrationstests in
   `booking/tests.py` (Einzelfälle) und `booking/tests_usecases.py` (End-to-End);
   Race-Tests `booking/tests_concurrency.py` laufen hier (siehe ADR 0013).
3. **Migrations-Resilienz:** migriert eine **befüllte Alt-DB** (Booking auf 0015
   zurück, Duplikate + Cascade-Wunsch erzeugen) vorwärts und fängt so DB-spezifische
   Fehler (Unique auf Duplikaten, „pending trigger events“), die ein frischer
   Testlauf NICHT sieht.

Ergänzend: Container-Healthcheck und der Migrations-Resilienz-Job verhindern, dass
eine kaputte Migration erst in Produktion auffällt.

## Betrachtete Alternativen

- **Nur Django-Tests gegen DB:** langsameres Feedback; die schnelle, DB-freie
  Logik-Suite entfiele.
- **Nur frische Test-DB:** verfehlt genau die Migrationsfehler auf gewachsenen Daten
  (real passiert).
- **Nur SQLite in der CI:** würde PostgreSQL-spezifisches Verhalten (z. B.
  `SELECT FOR UPDATE`) nicht abdecken.

## Konsequenzen

**Positiv**
- Sehr schnelles Grün/Rot für die Kernregeln; produktionsnahe Absicherung daneben.
- Migrations- und Nebenläufigkeitsfehler werden vor dem Deploy gefangen.
- Am grünen Häkchen erkennbar, ob ein Pull auf die VPS sicher ist.

**Negativ**
- Zwei Test-Ebenen + drei CI-Jobs erhöhen Pflegeaufwand und Laufzeit gegenüber einem
  einzelnen Lauf.
- Der Migrations-Resilienz-Job muss bei strukturellen Migrationsänderungen gepflegt
  werden.
