# 0077 – Unterkunfts-Tausch: nur exakter Zeitraum, automatische Ausführung, getrennt von der Belegungsanzeige

## Status

Accepted (2026-07-01)

> Verfeinert den Wechselwunsch aus dem Buchungs-Ändern-Bereich (ADR 0024/Fachkonzept § 10).

## Kontext

Der bisherige „Wechselwunsch" war umständlich und unklar:

- Er ließ sich für **überlappende** (nicht deckungsgleiche) Zeiträume anfragen –
  ein Unterkunfts-Tausch ergibt dort aber keinen Sinn und lässt sich nicht sauber
  ausführen.
- Die **Belegungsanzeige** („wer ist zur gleichen Zeit da") und die **Tausch-Aktion**
  waren in einem Aufklapp-Block vermischt, mit Tausch-Buttons an jeder Zeile.
- Vor allem: **Zustimmen führte den Tausch nicht aus.** Es setzte nur einen Status
  und benachrichtigte; die tatsächliche Umbuchung mussten die Beteiligten „mit der
  Verwaltung abstimmen". Das ist fehleranfällig und intransparent.

## Entscheidung

**Tausch nur bei EXAKT gleichem Zeitraum – und bei Zustimmung sofort ausgeführt.**

1. **Belegung vs. Aktion getrennt** (`my_bookings`): drei klar getrennte
   Aufklapp-Bereiche je Buchung –
   - **„Wer ist zur gleichen Zeit da?"** – rein informativ, **nur Mitglieder**
     (externe Gäste sind `ExternalBooking`, tauchen hier nie auf), aufgeteilt in
     *genau gleicher Zeitraum* und *überlappend*, **ohne** Aktions-Buttons;
   - **„Buchung ändern"** – unverändert (Unterkunft/Zeitraum/Personen);
   - **„Unterkunft mit jemandem tauschen"** – zeigt **ausschließlich** Buchungen mit
     **exakt gleichem** Zeitraum (die einzigen, mit denen ein Tausch Sinn ergibt).

2. **Exakter Zeitraum erzwungen** (`services.create_swap_request`): Anfrage nur, wenn
   `start`/`end` beider Buchungen identisch sind und die Unterkünfte verschieden (plus
   Dedup gegen doppelte offene Anfragen).

3. **Automatische, konfliktfreie Ausführung** (`services.respond_swap_request`): Bei
   Zustimmung werden – **unter Sperre und mit erneuter Prüfung** (beide Buchungen
   existieren noch, Zeitraum weiterhin identisch, Personenzahl passt in die jeweils
   andere Unterkunft, ADR 0076) – die **Quartiere der beiden Buchungen getauscht**
   (`quarter`-Feld), der Zeitraum bleibt gleich. Das ist immer konfliktfrei, weil
   beide Buchungen exakt denselben, sich gegenseitig ausschließenden Slot belegen.
   Andere offene Anfragen zu diesen Buchungen werden geschlossen; beide Seiten werden
   benachrichtigt.

4. **Hilfreicher Fallback statt Sackgasse:** Gibt es keinen exakten Tausch-Partner,
   erklärt der Bereich das und verweist – wenn möglich – auf **„Buchung ändern"**:
   sind Unterkünfte für den Zeitraum **frei**, kann man direkt wechseln (kein Tausch
   nötig); sonst prüft `services.swap_shift_hint` (effizient, wenige Abfragen: Belegung/
   Freigaben/Quartiere je einmal geladen, Verschiebungen in Python) einen **leicht
   verschobenen Zeitraum** und nennt die nächstliegende freie Unterkunft – umzusetzen
   ebenfalls über „Buchung ändern".

## Betrachtete Alternativen

- **Überlappende Tausche mit Absprache** (bisher): unklar, nicht ausführbar → verworfen.
- **Tausch nur vormerken, Umbuchung manuell**: intransparent, fehleranfällig → ersetzt
  durch die automatische Ausführung (dank exaktem Zeitraum risikolos).

## Konsequenzen

**Positiv** – klares mentales Modell (Tausch = gleicher Zeitraum, nur die Unterkunft
wechselt), Zustimmung führt den Tausch **sofort** aus, saubere Trennung von Anzeige
und Aktion, professionelle UI (Web + mobil). Effizient: die Tausch-Kandidaten kommen
aus der ohnehin geladenen Belegung (keine Extra-Abfrage), der Verschiebe-Tipp läuft
nur, wenn weder Tausch- noch freie Wechsel-Option besteht.

**Grenzen** – Tausche sind auf **zwei Parteien mit identischem Zeitraum** beschränkt
(bewusst). Ringtausch/annähernde Zeiträume sind nicht abgebildet; dafür ist „Buchung
ändern" der Weg.
