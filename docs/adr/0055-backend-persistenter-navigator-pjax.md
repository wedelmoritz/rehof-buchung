# 0055 – Backend: persistenter Navigator (Suche + Bereiche) + pjax statt Layout-Wechsel

## Status

Accepted (2026-06-28)

> Baut auf der fachlichen Backend-Gliederung (ADR 0049) und dem einheitlichen
> Farbsystem (ADR 0054) auf.

## Kontext

Das Django-Backend war verwirrend, weil sich der **Aufbau vollständig wechselte**,
sobald man einen Punkt wählte: Die Startseite zeigte Suche + fachliche Bereiche als
Karten; ein Klick auf z. B. „Benutzer“ lud eine völlig anders aufgebaute
Änderungsliste (eigene Struktur, voller Seiten-Reload). Suche und Bereiche
verschwanden dabei. Gewünscht: **Suche und Bereiche bleiben immer gleich
aufgebaut/sichtbar, der gewählte Bereich wird DARUNTER aufgebaut – möglichst ohne
Neuladen.**

## Entscheidung

**Ein persistenter Navigator (Suche + fachliche Bereiche) oben auf JEDER
Admin-Seite, plus pjax** für den Inhalt darunter.

**Persistenter Navigator (server-gerendert, immer gleich).**
`templates/admin/_rehof_navigator.html` rendert die Suche + die fünf Bereiche
(ADR 0049, kollabierbare `<details>`) aus `available_apps` (in *jedem* Admin-Kontext
vorhanden). Eingehängt über `{% block pretitle %}` in `base_site.html` – dieser
Block wird **nur** von Djangos `base.html` definiert, also von keiner Listen-/
Formular-Seite überschrieben → der Navigator erscheint **überall** identisch (auch
ohne JavaScript). Djangos eingebaute linke Seitenleiste wird abgeschaltet
(`RehofAdminSite.enable_nav_sidebar = False`), um Doppelung zu vermeiden. Die
Startseite zeigt darunter nur noch Erklärung + „Neue Benutzer“ (ADR-frei), nicht
mehr die Bereiche-Karten (die jetzt im Navigator stehen).

**pjax (ohne Neuladen, mit hartem Fallback).** Ein kleiner, abhängigkeitsfreier
Layer in `base_site.html` fängt Klicks auf interne `/admin/`-GET-Links (Bereiche,
Listen, Filter, Sortierung, Seitenblättern, Brotkrumen, Changelist-Suche) ab,
holt die Zielseite per `fetch`, und tauscht **nur den Inhalt UNTER dem Navigator**
aus (`#content` ohne das lebende `#rehof-nav`), aktualisiert Brotkrumen, Titel,
`body`-Klassen und den aktiven Eintrag, und schreibt die History (`pushState`/
`popstate`). Fehlende **Stylesheets** (z. B. `changelists.css`) werden nachgeladen.

**Bewusste Grenzen (Robustheit vor Vollständigkeit).**
- **Änderungs-/Anlage-Formulare, Löschen, History und alle POSTs laden normal**
  (voller Reload). Deren JS (jQuery/`django.jQuery`, Autocomplete/select2,
  Kalender-Widgets, Inlines) zuverlässig nach pjax zu re-initialisieren ist
  fehleranfällig – der Schaden (kaputte Widgets im Verwaltungs-Backend) wäre groß.
  Da der Navigator serverseitig auf jeder Seite steht, bleibt die Struktur auch
  beim vollen Reload gleich – kein „Layout-Wechsel“.
- pjax schleust **keine `<script>` ein** (nur CSS): Listen sind über Links voll
  bedienbar; reine JS-Extras auf pjax-geladenen Listen (z. B.
  „alle Seiten auswählen“) entfallen bewusst – Auswahl pro Zeile + Aktion-Ausführen
  (Formular-POST → voller Reload) funktioniert weiter.
- Jeder Fehler (Parser, fehlendes `#content`, Login-Redirect bei abgelaufener
  Sitzung) fällt auf **normale Navigation** zurück.

## Betrachtete Alternativen

- **Djangos eingebaute Seitenleiste nur umfärben:** löst die Inkonsistenz der
  Startseite nicht und bleibt eine schmale linke Leiste statt „Bereiche oben,
  Inhalt darunter“.
- **Voll-SPA-Admin (alles inkl. Formulare per pjax):** zu fragil (Widget-/jQuery-
  Re-Init über Django-Versionen), hohes Risiko im Verwaltungs-Backend.
- **Gar kein pjax, nur persistenter Navigator:** erfüllt „gleiche Struktur“, aber
  nicht „möglichst ohne Neuladen“. Daher pjax für den häufigen Fall (Bereiche/Listen
  durchblättern) ergänzt.

## Konsequenzen

**Positiv**
- Suche + Bereiche sind **auf jeder Seite gleich** aufgebaut; der gewählte Bereich
  erscheint darunter – kein verwirrender Layout-Wechsel mehr.
- Häufige Navigation (Bereich wählen, Listen filtern/blättern/suchen, zurück)
  läuft **ohne Neuladen**; Listen werden korrekt gestylt nachgeladen.
- Funktioniert auch **ohne JavaScript** (Navigator server-gerendert; Links laden
  normal).

**Negativ / Grenzen**
- Formulare/POSTs laden voll (bewusst, s. o.).
- Statische Seiten mit eigenem `pretitle` würden den Navigator verdrängen – aktuell
  gibt es keine; käme eine hinzu, muss sie `{{ block.super }}` in `pretitle`
  aufrufen.
- „Alle auswählen über Seiten“ fehlt auf pjax-geladenen Listen (Randfall).
