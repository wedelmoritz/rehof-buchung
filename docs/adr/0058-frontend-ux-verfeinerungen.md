# 0058 – Frontend-UX-Verfeinerungen (Benutzerbereich + Verwaltungs-Dashboard)

## Status

Accepted (2026-06-28)

> Ergebnis einer systematischen UX-Prüfung des Frontends (Mitglieder-Bereich UND
> Verwaltungs-Dashboard), Desktop und Smartphone. Pendant zur Backend-Prüfung
> (ADR 0057).

## Kontext

Die Prüfung bestätigte einen insgesamt sehr guten Zustand (saubere Struktur, je
genau eine `<h1>`, beschriftete Felder, alt-Texte, keine JS-Fehler, responsiv ohne
horizontales Scrollen, mobile Tab-Leiste + „Mehr"-Sheet). Gefunden wurden vor allem
Klarheits- und Politur-Punkte – plus ein echter Eingabe-Bug im Hofladen.

## Entscheidung

**P1 – Klarheit:**
- **Buchungskalender:** Vergangene Tage des laufenden Monats sahen wie freie (grüne)
  Tage aus, waren aber nicht klickbar (kein Feedback). Sie werden jetzt **gedämpft/
  neutral** dargestellt (`td.past`) mit Titel „Vergangener Tag – nicht mehr buchbar".
- **Benachrichtigungs-Karte** nur noch auf der **Übersicht** statt zusätzlich auf
  Buchen/Wunschliste/Meine Buchungen (und der Gäste-Seite) – sie belegte sonst den
  oberen Premium-Platz jeder Seite; Einzel-Ereignisse zeigt ohnehin der Toast.

**P2:**
- **Nicht-farbliche Verfügbarkeits-Info:** Buchbare Tage tragen `aria-label`/`title`
  („Tag N: x von y Einheiten frei") – Screenreader/Hover statt nur Ampelfarbe.
- **Dashboard-Datei-Upload** statt nacktem, englischem „Choose File": gestylter,
  deutscher Knopf „Datei wählen …" + Dateiname (`{% localize off %}`-frei,
  fokus-sichtbar per `:focus-within`).
- **Dashboard-Sprung-Chips** (klebrig unter dem Kopf, am Handy statisch) zu den
  langen Abschnitten Reinigung/Buchungen/Rechnungen/Kontoabgleich.
- **Redundante Platzhalter gekürzt** (Transfer-Suchfeld; das Label trägt die
  Bedeutung).

**P3:**
- **Hofladen-Mengenfeld-Bug behoben:** Bei dezimaler Schrittweite (z. B. 0,1 kg)
  rendert Django den Wert lokalisiert mit **Komma** – ein `<input type=number>`
  verwirft „0,1" und zeigte das Feld **leer**. Mengen-Inputs jetzt in
  `{% localize off %}` (Punkt statt Komma) → korrekt vorbelegt.
- **Tastatur-Fokus** sichtbar verstärkt: einheitlicher `:focus-visible`-Ring im
  Marken-Akzent (nur bei Tastaturnutzung).
- **„Heute"** im Kalender als Sekundär-/Ghost-Knopf (Akzent bleibt Primäraktionen
  vorbehalten, ADR 0054).
- **Wunschliste auf Touch sortierbar:** zusätzlich zum HTML5-Drag (Maus) ein
  additiver **Pointer-Events**-Pfad am Ziehgriff (nur Touch/Stift); die ▲▼-Knöpfe
  bleiben als garantierter Fallback.

## Konsequenzen

**Positiv**
- Weniger Missverständnisse (vergangene Tage, Verfügbarkeit auch nicht-farblich),
  konsistentere/​deutsche Bedienelemente, schnellere Navigation im langen Dashboard,
  bessere Tastatur-Bedienbarkeit, Touch-Sortierung der Wunschliste.
- Behebt einen echten Eingabe-Bug (leeres Mengenfeld bei Dezimal-Schrittweite).

**Grenzen**
- Touch-Drag ist additiv (Maus nutzt weiter HTML5-Drag); die volle Geste ist nur
  bei geöffnetem Wunsch-Zeitraum sichtbar testbar – die ▲▼-Knöpfe sichern die
  Funktion in jedem Fall.
- Die Sprung-Chips kleben unter einem Kopf mit fester Höhe (Desktop); am Handy
  bewusst statisch.
