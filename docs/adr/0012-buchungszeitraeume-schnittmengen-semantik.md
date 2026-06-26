# 0012 – Buchungszeiträume mit Schnittmengen-Semantik

## Status

Accepted (2026-06-26)

## Kontext

Die Freigabe von Buchungszeiträumen hat zwei Ebenen: eine **globale** Freigabe (über
die `BookingPeriod`) und eine **quartiersspezifische** Einschränkung (die
**Quartier-Saison** `Quarter.season_*`). Es muss eindeutig definiert sein, wie beide
zusammenwirken – insbesondere darf eine spezifische Regel die globale Freigabe nicht
versehentlich **ausweiten**.

## Entscheidung

Es gilt **Schnittmengen-Semantik (UND, nicht ODER)**: Ein Tag/Zeitraum ist nur
buchbar, wenn er **sowohl** global freigegeben **als auch** innerhalb der
Quartier-Saison liegt. Spezifische Fenster können nur **weiter einschränken**, nie
über die globale Freigabe hinaus erweitern.

- Reine Logik in `booking/availability.py` (`is_released`, `range_released`).
- Der Service prüft beide Ebenen zusammen: `services.range_is_released` kombiniert
  globale Fenster (`_active_windows`) mit der Quartier-Saison
  (`Quarter.bookable_on`/`_in_season_range`); siehe `services.py:440-447` und die
  Tagesprüfung in der Kalenderaufbereitung (`services.py:547`).

Die Semantik ist als **Ein-Punkt-Entscheidung** in der reinen Logik gekapselt – ein
Wechsel zu Vereinigungs-Semantik wäre hier lokal änderbar.

## Betrachtete Alternativen

- **Vereinigungs-Semantik (ODER):** ein spezifisches Fenster könnte über die globale
  Freigabe hinaus öffnen – unerwünscht, da schwer zu überblicken und fehleranfällig.
- **Nur eine Ebene (global ODER spezifisch):** verlöre entweder die zentrale
  Steuerung oder die quartiersgenaue Einschränkung.

## Konsequenzen

**Positiv**
- Vorhersehbar: spezifische Regeln können nie „aus Versehen mehr öffnen“.
- Zentrale Steuerung bleibt die Obergrenze; Quartier-Saison verfeinert nur.

**Negativ**
- Zwei Ebenen müssen gemeinsam gedacht werden; eine zu enge Quartier-Saison kann
  trotz globaler Freigabe blockieren (gewollt, aber erklärungsbedürftig).
