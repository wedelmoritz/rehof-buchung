# 0072 – Positive Wortwahl im Frontend („beliebt" statt „umkämpft/Konflikt")

## Status

Accepted (2026-06-29)

> Betrifft die Nutzerinnen-Oberfläche (App, Hilfeseiten, Benachrichtigungen).
> Verfeinert die Texte aus ADR 0064 (Entzerrungs-Hinweis) und 0004 (Karma).

## Kontext

Die Wunsch-/Losungs-Oberfläche beschrieb stark nachgefragte Zeiträume mit
**negativ besetzten** Begriffen: „umkämpft", „Konflikt(e)", „Konkurrenz". Das wirkt
auf Mitglieder eher abschreckend/wettbewerblich, obwohl die Sache schlicht ist:
manche Zeiten/Unterkünfte sind **beliebter** als andere.

## Entscheidung

**Im gesamten Frontend (inkl. Hilfeseiten und Benachrichtigungen) positive,
prägnante Begriffe** verwenden:

- „umkämpft" → **„(sehr) beliebt"**, „nicht umkämpft" → **„wenig gefragt"**.
- „Konflikte mit Wünschen anderer" → **„weitere Wünsche"** bzw. positiv gerahmt:
  „dort **noch keine/erst N weitere** Wünsche", „**weniger beliebte Alternativen –
  dort hast du bessere Chancen**".
- Los-Benachrichtigung: „um diesen Zeitraum gab es Konkurrenz" →
  **„dieser Zeitraum war sehr beliebt"**; Karma-Reset „nach Gewinn eines umkämpften
  Wunsches" → **„… eines sehr beliebten Wunsches"**.
- Ergebnis-Kennzeichnung „umkämpft" → **„beliebt"**; Kalender-Legende „umkämpft" →
  **„sehr beliebt"**.

Betroffen: `wishlist.html`, `help.html`, `result.html`, `profile.html` sowie die
Los-Benachrichtigungs-Texte in `services/lottery_ops.py`. **Interne Bezeichner**
(`contested`, `is_contested`, `won_contested`) bleiben unverändert (kein
Verhaltens-/API-Wechsel, nur Anzeige-Wortlaut).

**Bewusst NICHT pauschal geändert** (ehrliche, nicht beschönigende Sprache):
Begriffe wie „Verlust", „Pech", „leider nicht erfüllbar" im Los-Ergebnis bleiben
zunächst – sie benennen einen realen Ausgang. Eine weitere Aufweichung wäre bei
Bedarf separat zu entscheiden.

## Konsequenzen

**Positiv** – die Oberfläche klingt einladend statt wettbewerblich; die Aussage
(„viele wollen das – hier hast du bessere Chancen") bleibt klar und ehrlich.
**Grenzen** – Design-/Algorithmus-Dokumente (Losverfahren-Spezifikation, Fachkonzept,
ältere ADRs) verwenden „umkämpft/contested" weiter als **technischen** Fachbegriff;
das ist Absicht und kein Widerspruch zur Frontend-Wortwahl.
