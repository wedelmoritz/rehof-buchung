# 0026 – Buchung ändern und Wechselwunsch (auch bei Überlappung)

## Status

Accepted (2026-06-26)

## Kontext

Pläne ändern sich: Mitglieder wollen ihre Buchung verlängern/verkürzen, die
Unterkunft wechseln oder die Personenzahl anpassen – ohne stornieren und neu buchen
zu müssen. Außerdem wollen sich Mitglieder untereinander zu Quartiertauschen
verabreden, auch wenn die Zeiträume nicht exakt deckungsgleich sind.

## Entscheidung

**Buchung ändern** in einem Schritt und **Wechselwünsche** als beidseitig
bestätigter Vorgang.

- **Ändern:** `services.adjust_allocation` (`booking/services.py:1421`) deckt
  Zeitraum, **Unterkunft-Wechsel** (nur freie – `free_quarters_for`) und
  **Personenzahl** ab:
  - **Verlängern** spontan, solange die Zusatznächte frei/freigeschaltet/im Budget
    sind.
  - **Verkürzen** nur, wenn der Mindestaufenthalt gewahrt bleibt **und** die frei
    werdenden Nächte ≥ 7 Tage entfernt sind → dann „spontan frei an alle“ (ADR 0025).
  - **Unterkunft-Wechsel** geht spontan und meldet das alte Quartier als „spontan
    frei“ (die 7-Tage-Frist gilt nur fürs reine Verkürzen im selben Quartier).
- **Wechselwunsch:** `services.create_swap_request`/`respond_swap_request`
  (`services.py:1085`/`1104`), Modell `models.SwapRequest`. Bewusst **auch bei
  bloßer Überlappung** möglich – mit Hinweis; die Empfänger:in stimmt zu/lehnt ab.
- **„Wer ist gleichzeitig da“** wird dafür in **exakt gleiche** An-/Abreise und
  **nur überlappend** getrennt (`services.concurrent_split`, `services.py:1071`).

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
