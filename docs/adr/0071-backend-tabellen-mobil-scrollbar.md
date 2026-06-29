# 0071 – Backend-Tabellen auf dem Handy horizontal scrollbar

## Status

Accepted (2026-06-29)

> Mobil-Fix zu ADR 0067 (Ein-Spalten-Layout) und 0070 (Mitglied/Anteil-Verwaltung).

## Kontext

Auf dem Smartphone wirkten die Backend-Tabellen „kaputt": breite Listen
(z. B. **Benutzer**, **Nutzer-Konten**, **Mitglieds-Anteile**) und die
**Tabular-Inlines** (Tage-Anteile am Mitglied/Anteil) brachen mitten im Wort um
oder waren **rechts abgeschnitten** – „rechts davon nichts sichtbar".

Zwei Ursachen, per DOM-Messung bestätigt:
- Die Änderungslisten-Tabelle steckt in `.results` (`overflow-x:auto`, also
  technisch scrollbar), aber **ohne Affordanz**: Zellen brachen um, es gab keinen
  sichtbaren Hinweis, dass man seitlich wischen kann.
- Die **Inline-Tabellen** wurden vom **Karten-`overflow:hidden`** der `.module`
  (Look aus ADR 0054/0065) **abgeschnitten** – echtes Klippen, nicht scrollbar
  (Tabelle 618 px im 360-px-Modul).

## Entscheidung

Auf schmalen Schirmen (`max-width: 768px`):
- **Zellen nicht umbrechen** (`white-space:nowrap`) in Änderungslisten und
  Inline-Tabellen → eine Zeile je Datensatz, lesbar statt zerbrochen.
- Den jeweiligen **Container horizontal scrollen** lassen: `#changelist .results`
  bleibt `overflow-x:auto`; die **Inline-Module** werden von `overflow:hidden` auf
  `overflow:auto` gestellt (Karten-Look bleibt, Tabelle wird scrollbar).
- **Sichtbarer dünner Scrollbalken** als Wisch-Affordanz (`::-webkit-scrollbar`),
  plus `-webkit-overflow-scrolling:touch` für sanftes Scrollen auf iOS.

Reiner CSS-Fix in `templates/admin/base_site.html`; keine Skripte/Inline-Handler
(CSP unverändert).

## Konsequenzen

**Positiv** – breite Tabellen sind am Handy vollständig erreichbar (seitlich
wischen), Zellen bleiben lesbar, der Scrollbalken zeigt, dass es weitergeht; der
warme Karten-Look bleibt. Per Screenshot/DOM verifiziert (Listen-Tabelle und
Inline-Tabelle scrollen bis zum Ende; Spalten „Tage-Anteil/Wunsch/Löschen?" wieder
sichtbar). **Hinweis (kein Bug):** die **„GESCHICHTE"** (Versionen/Wiederherstellen,
ADR 0070) steht – wie in Django üblich – **auf der jeweiligen Einzel-Seite**
(Benutzer/Mitglied/Anteil **bearbeiten**, oben), **nicht** in den Listen; in den
Listen gibt es stattdessen „Gelöschtes wiederherstellen". **Grenze** – kein
gestapeltes Karten-Layout der Tabellen (bewusst: robuster, generischer Scroll
statt fragiler Spalten-Umbau je Modell).
