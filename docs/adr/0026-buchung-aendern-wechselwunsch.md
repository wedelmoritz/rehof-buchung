# 0026 – Buchung ändern und Wechselwunsch (auch bei Überlappung)

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 10 – Buchung ändern, Warteliste & Wechselwunsch](../FACHKONZEPT.md#10-buchung-ändern-warteliste--wechselwunsch).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Pläne ändern sich: Mitglieder wollen ihre Buchung verlängern/verkürzen, die
Unterkunft wechseln oder die Personenzahl anpassen – ohne stornieren und neu buchen
zu müssen. Außerdem wollen sich Mitglieder untereinander zu Quartiertauschen
verabreden, auch wenn die Zeiträume nicht exakt deckungsgleich sind.

## Entscheidung

**Buchung ändern** in einem Schritt und **Wechselwünsche** als beidseitig
bestätigter Vorgang.

- **Ändern:** `services.adjust_allocation` (Paket `booking/services/`) deckt
  Zeitraum, **Unterkunft-Wechsel** (nur freie – `free_quarters_for`) und
  **Personenzahl** ab; die Regeln für Verlängern/Verkürzen/Wechsel (inkl. der
  7-Tage-Frist beim reinen Verkürzen) stehen in Fachkonzept § 10. Frei werdende
  Nächte lösen „spontan frei an alle“ aus (ADR 0025).
- **Wechselwunsch:** `services.create_swap_request`/`respond_swap_request`, Modell
  `models.SwapRequest`. Bewusst **auch bei bloßer Überlappung** möglich – mit Hinweis;
  die Empfänger:in stimmt zu/lehnt ab.
- **„Wer ist gleichzeitig da“** wird dafür in **exakt gleiche** An-/Abreise und
  **nur überlappend** getrennt (`services.concurrent_split`).

## Betrachtete Alternativen

- **Nur Storno + Neubuchung:** verliert den Slot zwischenzeitlich, schlechtere UX.
- **Wechselwunsch nur bei exakt gleichem Zeitraum:** schließt sinnvolle Tausche bei
  leichter Überlappung aus.
- **Verkürzen jederzeit ohne Frist:** würde sehr kurzfristig Slots freigeben, die
  niemand mehr fair nutzen kann → 7-Tage-Frist.

## Konsequenzen

**Positiv**
- Flexible Selbstverwaltung ohne Storno-Umweg; frei werdende Nächte kommen anderen
  zugute.
- Tausche sind realistisch (auch bei Überlappung) und beidseitig bestätigt.

**Negativ**
- Mehr Regel-Verzweigungen in `adjust_allocation` (Frist, Mindestnächte, Budget,
  Wechsel) – test- und pflegeintensiv.
- Überlappende Tausche brauchen klare Hinweise, damit Erwartungen stimmen.
