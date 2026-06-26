# 0031 – Fairness-Nachweis per Monte-Carlo-Simulation

## Status

Accepted (2026-06-26)

## Kontext

Das Losverfahren (ADR 0003/0004) ist nur dann vertrauenswürdig, wenn die
Genossenschaft seine Fairness **nachvollziehen** kann – ohne den Code lesen zu
müssen. Es braucht einen verständlichen Beleg, dass gleich gestellte Mitglieder
dieselbe Chance haben und dass das Karma nachweisbar wirkt.

## Entscheidung

Ein **statistischer Fairness-Nachweis** per Monte-Carlo-Simulation, im Frontend
sichtbar.

- **Reine Logik** in `booking/fairness.py` (Django-frei, auf dem puren
  `lottery`-Modul): `simulate_equal_chance` und `simulate_karma_effect` mit eigener
  Statistik (`chi2_sf` = Chi-Quadrat-Anpassungstest, `wilson_interval` =
  Konfidenzintervall) – belegt „equal treatment of equals“ der RSD. Tests in
  `tests/test_fairness.py`.
- **Anzeige:** Seite `lottery_fairness` (`/losung-fairness/`, login-pflichtig, aus
  der Hilfe verlinkt) mit Inline-SVG-Grafen.
- **Konfiguration/Start** im Backend am Singleton `FairnessSimConfig` (Admin-Knopf
  „Simulation jetzt berechnen“, Ergebnis als JSON gespeichert); Service
  `services.run_fairness_simulation`.

## Betrachtete Alternativen

- **Nur formaler Beweis im Text:** für Laien schwer zugänglich; kein interaktiver
  Beleg.
- **Externe Statistik-Bibliothek (scipy/numpy):** zusätzliche schwere Abhängigkeit;
  die wenigen Tests (Chi²-SF, Wilson) sind selbst implementierbar und bleiben
  Django-/dependency-frei.
- **Live-Simulation bei jedem Aufruf:** rechenintensiv; daher konfiguriert/gestartet
  und Ergebnis gespeichert.

## Konsequenzen

**Positiv**
- Nachvollziehbarer, sichtbarer Fairness-Beleg ohne Code-Lektüre.
- Keine schweren Numerik-Abhängigkeiten; reine, testbare Logik.

**Negativ**
- Eigene Statistik-Implementierung muss korrekt bleiben (durch Tests abgesichert).
- Das gespeicherte Ergebnis ist eine Momentaufnahme der gewählten Parameter.
