# 0057 – Backend-UX-Verfeinerungen (Navigator einklappbar/Akkordeon, Listen, Leer-Hinweise)

## Status

Accepted (2026-06-28)

> Verfeinert ADR 0055 (persistenter Navigator + pjax) nach einer systematischen
> UX-Prüfung des Backends (Desktop **und** Smartphone).

## Kontext

Die UX-Prüfung ergab vor allem ein Problem: Der persistente Navigator (Suche +
Bereiche) **verdrängte den Inhalt** – auf dem Handy stand er **283 px** hoch über
der Liste, der aktive Bereich klappte automatisch auf, und der Offen-Zustand der
Bereiche **akkumulierte** unbegrenzt in `localStorage`. Dazu kleinere Lücken:
die operative Liste „Zuteilungen“ ohne Datums-Orientierung, einige Listen ohne
Such-/Filterfelder, kein freundlicher Leer-Zustand, Klein-Schwächen am Handy.

## Entscheidung

**Navigator kompakt & beherrschbar (P1):**
- **Einklappbar** über eine immer sichtbare Leiste „Suche & Bereiche · <Standort>“.
  **Mobil per Default eingeklappt** (CSS-Media-Query, kein Flackern), Desktop offen;
  die Wahl wird gemerkt (`localStorage rehof.nav.collapsed`). Eingeklappt zeigt die
  Leiste den **aktuellen Standort** (aktiver Eintrag) zur Orientierung.
- **Akkordeon:** Es ist **immer nur EIN Bereich offen** (öffnet sich einer, schließen
  sich die anderen). Der Offen-Zustand akkumuliert nicht mehr; pro Seite wird der
  **aktive** Bereich geöffnet (Höhe bleibt begrenzt). Mobil ~37 px statt 283 px.
- **Badge:** Der Eintrag „Neue Benutzer (Zuordnung)“ trägt die **Anzahl offener
  Konten** (aus `RehofAdminSite.each_context` → `users_without_membership().count()`),
  sodass die Aufgabe von jeder Seite sichtbar ist.

**Listen klarer (P1/P2):**
- „Zuteilungen“ (`AllocationAdmin`): `date_hierarchy="start"`, `ordering=("-start",)`,
  Spalte „Nächte“, Suche um Quartier/Benutzername erweitert, `list_select_related`.
- Such-/Filter-/Datums-Lücken geschlossen (`Wish`, `Notification`, `SwapRequest`:
  `date_hierarchy`/Suche/`list_select_related`).

**Politur (P2/P3):**
- Mobil die „+“-Schnellanlage am Navigator ausgeblendet (Fehlklick-Gefahr),
  kürzerer Such-Platzhalter, kompaktere Kopfzeile.
- **Freundlicher Leer-Hinweis** in Listen („Noch keine Einträge“ bzw. „Keine Treffer
  für die aktuelle Suche/Filter“) – rein additiv per JS, auch nach pjax; ersetzt das
  nackte „0 …“.
- „Neueste Aktionen“ als ruhige helle Karte statt grauem Block.

## Konsequenzen

**Positiv**
- Der Inhalt steht wieder oben; mobil ist der Navigator standardmäßig aus dem Weg,
  per Tipp erreichbar. Orientierung bleibt (Standort-Label, aktiver Bereich).
- Höhe des Navigators ist **begrenzt** (max. ein offener Bereich), kein Akkumulieren.
- Operative Listen sind nach Datum auffindbar/sortiert; weniger Scrollen/Suchen.

**Negativ / Grenzen**
- Auf dem Desktop ist standardmäßig **ein** Bereich offen – minimal höher als ganz
  zu; per Leiste einklappbar.
- Der Leer-Hinweis ist JS-additiv (ohne JS bleibt Djangos „0 …“); bewusst, um die
  Changelist-Templates nicht global zu überschreiben.
- `each_context` führt pro Admin-Seite eine zusätzliche COUNT-Abfrage aus (günstig).
