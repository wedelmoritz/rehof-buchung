# 0093 – Hilfetexte in editierbare Inhalts-Dateien auslagern (sicher gerendert)

## Status

Accepted (2026-07-05) · adressiert Feedback #66 · konkretisiert ADR 0087 (Punkt 8)

## Kontext

Die Betriebsleitung möchte die **Hilfe-Prosa** redaktionell anpassen können, ohne den
Entwickler einzubeziehen (Feedback #66). Die Hilfe-Seite (`help.html`) ist aber ein
großes Template mit reichem Markup (SVG-Flüsse, Formeln, Tabellen, `{% if %}`-Logik) –
darin Text zu ändern ist fehleranfällig (Template-Tags, CSP, Struktur).

Ein vollwertiges CMS mit DB-Redaktion wäre der nächste Schritt, öffnet aber eine
HTML-/XSS-Angriffsfläche und ist für „nice-to-have“ überdimensioniert.

## Entscheidung

**Prosa-Abschnitte in editierbare Inhalts-Dateien auslagern** (`booking/help_content/
*.md`), getrennt vom Template-Markup. Eine Textänderung ist damit ein **risikoarmer
Ein-Datei-Edit** in einfacher Markup-Sprache – ohne Template-Struktur/CSP zu berühren.

**Sicher gerendert** über einen **Django-freien, escape-first Mini-Renderer**
(`booking/helptext.py::render_markup`, im pytest-Suite geprüft): der Textinhalt wird
**zuerst vollständig HTML-escaped**, danach werden nur wenige, kontrollierte
Formatierungen wieder eingesetzt (Absatz, `## Überschrift`, `- Liste`, `**fett**`,
`[Text](ziel)` mit **Ziel-Allowlist** `/…` · `#…` · `https://…` · `mailto:`). Aus dem
Inhalt kann so **kein** HTML/JS entstehen (kein `<script>`, keine Handler) – passend
zur strikten CSP. Operationswerte/URLs kommen als `$platzhalter` und werden per
`string.Template.safe_substitute` gesetzt (kein SSTI); URLs liefert `reverse()`, damit
die Inhalts-Dateien **keine** Template-Tags brauchen.

Der Loader `services.help_sections()` liest `help_content/<key>.md` (erste Zeile
`# Titel`), rendert den Rest und gibt `{key: {title, html}}` zurück; `help.html` bettet
die Abschnitte per `{{ help.<key>.html|safe }}` ein. Ausgelagert sind zunächst die
reinen Prosa-Karten **Warteliste · Gemeinschaft · Hofladen · Tage übertragen**; die
algorithmisch-reichen Abschnitte (Auslosung/Formeln/SVG) bleiben bewusst im Template.

## Konsequenzen

**Positiv** – redaktionelle Änderungen an der Kern-Hilfe sind ein einfacher, sicherer
Text-Edit; die Trennung Inhalt/Markup ist die Vorstufe zu einem späteren CMS; der
Renderer ist Django-frei und deckungsgleich getestet.

**Grenzen** – „ohne Entwickler“ heißt aktuell „ohne Template-Kenntnisse, per Datei im
Repo/Deploy“ – noch keine Laufzeit-Redaktion im Backend. Die rich-strukturierten
Abschnitte bleiben im Template (bewusst nicht in Markup gepresst).
