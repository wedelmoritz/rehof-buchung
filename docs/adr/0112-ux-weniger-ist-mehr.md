# 0112 – UI/UX: „Weniger ist mehr" – Überladung je Seite reduzieren (Tier 1)

## Status

Accepted (2026-07-20) · verfeinert [ADR 0059](0059-uebersicht-aufgeraeumt-status-chips.md)
(aufgeräumte Übersicht), [ADR 0098](0098-uebersicht-belegungsplan-held.md) (Belegungsplan
als Held), [ADR 0064](0064-p2-features-entzerrung-solidaritaet.md)/[0103](0103-wunsch-entzerrung-konzept.md)
(Wunsch-/Entzerrungs-Features), [ADR 0085](0085-verwaltung-unterseiten.md) (Verwaltungs-
Unterseiten). **Umgesetzt (2026-07)** – erste Umsetzungsstufe des vollständigen UI/UX-Reviews.

## Kontext

Der vollständige UI/UX-Review über **jede** Seite (Leitfrage „möglichst wenig Funktionalität
pro Seite, auf einen Blick klar") fand die Überladung an wenigen Stellen konzentriert, fast
immer in zwei Mustern: **dieselbe Information mehrfach dargestellt** oder **artfremde
Nebenfunktionen auf die Kernseite gemischt.** Diese ADR hält die **risikoarme erste Stufe**
(Tier 1) fest – reine Darstellungs-Änderungen (Schicht 3), keine Regel-/Service-Logik.

## Entscheidung

**1) Toter Code entfernt.** Der Kontext `notifications` wurde in `book`/`my_bookings`/
`wishlist` geladen, aber in keinem der drei Templates gerendert (nur `overview` nutzt ihn) –
entfernt (3 Abfragen gespart). Die verwaiste Partial `_notifications.html` (nirgends
inkludiert) gelöscht. Analog der auf der Übersicht nicht mehr benötigte `winter`/`weekend`-
Kontext.

**2) Signal-Redundanz auf der Wunschliste reduziert.** Der separate **„Empfohlen"-Block**
war eine Teilmenge der ohnehin nach „beste Chance zuerst" sortierten Kandidatenliste →
entfernt (Kontext `recommended` gestrichen). Die **numerische Nachfrage-Zahl je Kalendertag**
(`{{ d.demand }}×`) entfiel; die **Beliebtheits-Farbe + Legende** tragen die Aussage „wie
gefragt" weiter. (Die feingranulare Signal-Entdopplung **innerhalb** des „Details"-Aufklappers
bleibt Tier 2 – sie ist bereits progressiv verborgen und berührt „auf einen Blick" nicht.)

**3) Passive Richtwerte aus der Übersicht.** Winter-/Wochenend-Chips sind Kennzahlen ohne
Handlung auf der Startseite → dort entfernt; sie stehen weiter im **Handlungskontext** auf
„Buchen" (dort zusätzlich von mehrzeiliger Prosa auf je eine kompakte Zeile gekürzt, die
Ausführung steht in der Hilfe). Damit trägt die Status-Zeile nur noch **aktionable** Chips
(Tage frei / Losung), ADR 0059 konsequent zu Ende geführt.

**4) Sekundäres progressiv verborgen (`<details>`).** „Buchen": NL-Freitextfeld und die
„Nicht verfügbar"-Liste (B6/ADR 0092) eingeklappt (NL öffnet automatisch bei Vorschlag).
„Meine Buchungen": Warteliste und vergangene Buchungen eingeklappt (wie „Zuletzt storniert");
der **Wunschlisten-Spiegel** (eine ganze Fremd-Tabelle) auf einen Verweis-Chip reduziert –
Wünsche sind keine Buchungen. „Verwaltung": xlsx+CSV je Liste hinter ein einheitliches
**„Export ▾"** (4 Seiten), der Rand-Workflow „Bereits entschiedene ändern" (Reinigung) und
der „Empfänger-Export" (Rundnachricht) eingeklappt.

## Architektur / Sicherheit / Performanz

- Reine Template-/Kontext-Änderungen; keine Domänen-/Service-Logik, keine Migrationen.
- **CSP-treu:** ausschließlich `<details>`/Markup-Umbau, keine Inline-Handler; positive
  Wortwahl (ADR 0072) unberührt; mehrzeilige Erklärungen als `{% comment %}` (Konvention).
- Kleiner Nebeneffekt: 3 überflüssige `unread_notifications`-Abfragen + 2 `winter/weekend`-
  Berechnungen je Seitenaufruf gespart.
- Tests an die neue Absicht angepasst: `test_winter_richtwert_auf_buchen_nicht_uebersicht`
  (Übersicht ohne, „Buchen" mit Winter-Richtwert), `test_wishlist_zeigt_…` prüft jetzt die
  sortierte Liste statt des entfernten Empfohlen-Blocks. Volle Suite grün.

## Konsequenzen

**Positiv** – die überladensten Seiten (Buchen, Wunschliste, Meine Buchungen) sind auf einen
Blick klarer; wiederkehrende Doppel-Darstellungen und tote Zuladungen sind weg.

**Negativ / Grenzen** – die tiefergreifenden Umbauten (Wunschliste **3→2 Reiter**, Hilfe-
Losungstiefe auf Unterseite, `verw_konto`→`verw_rechnungen`, Inline-CSS/JS auslagern) sind
**bewusst Tier 2** und hier NICHT enthalten; ebenso die Team-Präferenz-Fragen (Dashboard-KPIs
5→3, `verw_auslastung` als eigener Nav-Punkt), die vor Umsetzung eine Rückfrage brauchen.
