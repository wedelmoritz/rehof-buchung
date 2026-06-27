# 0025 – Warteliste und „spontan frei"-Benachrichtigung

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 10 – Buchung ändern, Warteliste & Wechselwunsch](../FACHKONZEPT.md#10-buchung-ändern-warteliste--wechselwunsch)
> sowie [§ 16 – Benachrichtigungen](../FACHKONZEPT.md#16-benachrichtigungen).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Beliebte Zeiträume sind oft belegt. Mitglieder sollen sich für einen belegten
Zeitraum **vormerken** können und erfahren, sobald er frei wird. Außerdem werden
Slots kurzfristig frei (Storno, Verkürzung, Quartier-Wechsel) – diese Chance soll
fair und schnell alle Interessierten erreichen, nicht nur Zufallsbesucher der Seite.

## Entscheidung

Eine **Warteliste** plus aktive Benachrichtigung bei frei werdenden Slots.

- **Vormerken:** `services.add_waitlist_entry` (Paket `booking/services/`), Modell
  `booking/models.py:WaitlistEntry`; eigene offene Einträge erscheinen unter „Meine
  Wartelisten-Einträge“ in *Meine Buchungen*.
- **Wird ein Wartelisten-Zeitraum durch Storno frei:** `notify_waitlist_if_free`
  erzeugt eine `Notification` **und** – über die Outbox (ADR 0027) – eine E-Mail an
  die Wartenden.
- **Kurzfristig frei durch Verkürzen/Quartier-Wechsel:**
  `_broadcast_spontaneously_free` meldet das frei gewordene Quartier **an alle**
  Mitglieder (In-App) + E-Mail an die Warteliste. Die fachlichen Regeln (u. a. die
  7-Tage-Frist beim reinen Verkürzen) stehen in Fachkonzept § 10 (technisch in
  ADR 0026).

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
