# 0025 – Warteliste und „spontan frei"-Benachrichtigung

## Status

Accepted (2026-06-26)

## Kontext

Beliebte Zeiträume sind oft belegt. Mitglieder sollen sich für einen belegten
Zeitraum **vormerken** können und erfahren, sobald er frei wird. Außerdem werden
Slots kurzfristig frei (Storno, Verkürzung, Quartier-Wechsel) – diese Chance soll
fair und schnell alle Interessierten erreichen, nicht nur Zufallsbesucher der Seite.

## Entscheidung

Eine **Warteliste** plus aktive Benachrichtigung bei frei werdenden Slots.

- **Vormerken:** `services.add_waitlist_entry` (`booking/services.py:685`), Modell
  `booking/models.py:WaitlistEntry`; eigene offene Einträge erscheinen unter „Meine
  Wartelisten-Einträge“ in *Meine Buchungen*.
- **Wird ein Wartelisten-Zeitraum durch Storno frei:** `notify_waitlist_if_free`
  (`services.py:719`) erzeugt eine `Notification` **und** – über die Outbox (ADR
  0027) – eine E-Mail an die Wartenden.
- **Kurzfristig frei durch Verkürzen/Quartier-Wechsel:**
  `_broadcast_spontaneously_free` (`services.py:1405`) meldet das frei gewordene
  Quartier **an alle** Mitglieder (In-App) + E-Mail an die Warteliste. Beim reinen
  Verkürzen im selben Quartier gilt zusätzlich die 7-Tage-Frist (siehe ADR 0026).

## Betrachtete Alternativen

- **Keine Warteliste (nur „später nochmal schauen“):** unfair, intransparent,
  benachteiligt Gelegenheits-Nutzer.
- **Automatische Zuteilung an den ersten Wartenden:** nimmt die Wahl, kollidiert mit
  Budget/Eignung; die Benachrichtigung + freie Buchung ist einfacher und gerechter.

## Konsequenzen

**Positiv**
- Faire, aktive Chance auf frei werdende Slots statt Zufall.
- Wiederverwendung der Benachrichtigungsschiene (In-App + E-Mail).

**Negativ**
- Benachrichtigungs-Volumen bei vielen Wartenden/Broadcasts; Idempotenz und
  Opt-out (ADR 0027) müssen greifen.
- „Spontan frei an alle“ kann zu einem Ansturm auf denselben Slot führen – abgesichert
  durch die Zeilensperre (ADR 0013).
