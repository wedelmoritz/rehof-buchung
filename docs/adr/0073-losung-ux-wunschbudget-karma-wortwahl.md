# 0073 – Losung-UX: halbes Wunsch-Budget, Karma auf der Wunschliste, sanftere Wortwahl

## Status

Accepted (2026-06-29)

> Verfeinert ADR 0072 (positive Wortwahl), 0004 (Karma) und die Tage-Regeln.

## Kontext

Drei Wünsche aus dem Praxis-Feedback:

1. **Wunsch-Budget** war ein **separat gepflegter** Wert je Anteil (Standard 25) –
   unnötig fehleranfällig und nicht klar an die Tage gekoppelt.
2. Der **Ausgleichsfaktor (Karma)** stand auf **mehreren** Seiten (Profil **und**
   „Meine Buchungen") – verstreut und außerhalb seines eigentlichen Kontexts.
3. Im Los-Ergebnis fielen **harte** Begriffe („Verlust", „Pech", „leider nicht
   erfüllbar").

## Entscheidung

**1) Wunsch-Budget = genau die Hälfte der Tage, abgerundet.**
`Member.wish_night_budget` wird **immer aus dem Tage-Budget abgeleitet**:
`annual_night_budget // 2` (50→25, 25→12, 35→17, …). Es wird **nicht mehr je Anteil
gespeichert/eingegeben**; die Eingabefelder „Wunsch-Tage" in Onboarding und
Anteils-Inlines entfallen (kurzer Hinweis „= die Hälfte, automatisch"). Das alte
`Share.wish_night_budget`/`Membership.wish_night_budget` bleibt als Feld bestehen,
ist aber **obsolet** (keine Migration nötig; spätere Bereinigung möglich).

**2) Karma genau dort, wo es zählt: auf der Wunschliste.** Der Ausgleichsfaktor
(mit der vollen Erklärung) steht jetzt **nur** auf der **Wunschliste** – dem
member-seitigen Zuhause der Losung – und ist von **„Meine Buchungen"** und vom
**Profil** entfernt. Er wird dort für jedes (nicht-externe) Mitglied angezeigt,
auch außerhalb der Wunsch-Phase; die Hilfe verlinkt entsprechend.

**3) Sanftere Wortwahl** im gesamten Frontend/Benachrichtigungen:
- „Verlust" → **„diesmal nichts/nicht"**; „kein Verlust" → **„zählt nicht negativ"**.
- „Pech aus Vorjahren" → **„Ausgleich aus Vorjahren"**.
- „leider nicht" → **„diesmal nicht"**; „diese Wünsche waren nicht erfüllbar" →
  **„diese Wünsche haben diesmal nicht geklappt"**.
- „mit echtem Verlust" (Karma) → **„mit einem nicht erfüllten Wunsch"**.

Betroffen: `models.py` (abgeleitetes Budget), `admin.py`/`onboarding.html`
(Eingaben raus), `wishlist.html` (Karma-Karte rein), `my_bookings.html`/
`profile.html` (Karma raus), `help.html`, `services/lottery_ops.py` (Benachrichtigungen).

## Konsequenzen

**Positiv** – das Wunsch-Budget ist immer korrekt und selbsterklärend an die Tage
gekoppelt; Karma steht im richtigen Kontext und macht das Profil/​die Buchungen
schlanker; das Los-Ergebnis klingt fair und einladend statt entmutigend.
**Grenzen** – `*.wish_night_budget`-Felder bleiben vorerst als toter Ballast in der
DB (bewusst, um eine Migration zu sparen). Außerhalb der Wunsch-Phase ist das Karma
nur noch auf der Wunschliste sichtbar (für die Übersicht zusätzlich im
Gemeinschafts-Spiegel) – als Kompromiss zwischen Kontext und Auffindbarkeit.
