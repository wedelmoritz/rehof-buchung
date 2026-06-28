# 0059 – Übersicht aufgeräumt: Belegungs-Zeitstrahl als Standard + Wochen-Agenda + Detail im Kontext

## Status

Accepted (2026-06-28)

## Kontext

Die Mitglieder-**Übersicht** wirkte voll/unaufgeräumt: vier schwere Blöcke
stapelten sich vertikal – Benachrichtigungs-Karte, Los-Banner, Kalender **oder**
Belegungsplan (mit zwei Legenden + Ferienliste), und das **Tag-Detail** als große
Karte weit unten. Dazu wiederholte das Monatsraster eine lange Buchung als Label
auf **jedem** Tag.

Recherche zu Gruppen-/Ressourcen-Kalendern (Teamup, Skedda, Resource Guru, Robin,
Outlook „Räume planen", Google-Ressourcenkalender, Hotel-PMS) zeigt: Für „wer ist
wo, von wann bis wann" ist der **Ressourcen-Zeitstrahl** (Zeilen = Quartiere,
Spalten = Tage, ein Balken pro Buchung) der Standard; das Monatsraster ist
Zweitansicht; Detail gehört **on demand in den Kontext** (Panel/Popover), nicht als
Dauerblock; mobil ist eine **Agenda/Liste** am klarsten.

## Entscheidung

Gewählte Variante **„Hybrid"** (= Variante A + Wochen-Agenda):

- **Belegungs-Zeitstrahl ist die Standard-Ansicht** der Übersicht; das Monatsraster
  bleibt über den Umschalter „Kalender" (`?view=grid`). Default-Flip im `overview`-View.
- **„Diese Woche"-Agenda** (`services.week_agenda`) als kompakte, scanbare Liste über
  dem Plan: je Tag An-/Abreisen (Mitglieder + externe Gäste) und Zahl freier
  Quartiere; nur Tage mit Ereignissen + „heute". Auf dem Handy der eigentliche
  Schnell-Überblick (statt des dort engen Zeitstrahls).
- **Tag-Detail im Kontext:** Klick auf Balken/Tag öffnet ein **Detail-Panel rechts
  neben dem Plan** (Desktop, zweispaltiges `.ov-grid`, sticky) bzw. **darunter** am
  Handy – „Wer ist da · Noch frei · An diesem Tag buchen". Die große Karte unten
  entfällt; der bestehende `?day=`-pjax-Fluss füllt einfach das Panel.
- **Schlanke Chrome:** Los-Banner und „Tage frei" als **Status-Chips** oben;
  Benachrichtigungen als **eingeklapptes `<details>`** (statt Dauer-Karte, JS-frei);
  **eine** kombinierte Legende (Personen + heute + Ferien); Hilfe-/Ferien-Fließtext
  entfernt.

## Konsequenzen

**Positiv**
- Deutlich ruhigere, modernere Seite; eine klare Held-Ansicht statt vier
  gleichwertiger Blöcke. Lange Buchungen erscheinen als **ein** Balken statt
  wiederholter Tages-Labels.
- Detail im Kontext (kein Scroll-Bruch nach unten). Mobil sofort „was ist diese
  Woche los".
- Nutzt vorhandene Services (`build_occupancy_timeline`, `day_detail`); neu nur das
  schlanke `week_agenda`.

**Grenzen / bewusst**
- Das Monatsraster ist jetzt **Zweitansicht** (ein Klick entfernt) – manche mögen es
  als Standard; der Umschalter bleibt.
- Das Detail-Panel ist am Handy ein normaler Block unter dem Plan (kein echtes
  Bottom-Sheet) – bewusst einfach/robust gehalten.
- `week_agenda` rechnet je Tag die freien Quartiere (7 leichte Abfragen pro
  Seitenaufruf) – günstig, aber nicht null.
