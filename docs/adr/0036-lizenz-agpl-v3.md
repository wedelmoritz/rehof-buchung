# 0036 – Lizenz: GNU AGPL v3

## Status

Accepted (2026-06-26)

## Kontext

Die App ist eine Genossenschafts-Lösung. Es ist eine bewusste Wert-Entscheidung, ob
und wie sie weitergegeben werden darf – insbesondere, dass eine **gehostete**
Variante den Quellcode offenlegen muss, damit die Lösung dauerhaft offen bleibt und
nicht in einer geschlossenen Abwandlung „verschwindet“.

## Entscheidung

Die App steht unter der **GNU Affero General Public License v3** (`LICENSE`,
im README-Abschnitt „Lizenz“ erläutert).

- Nutzung, Veränderung und Weitergabe sind erlaubt.
- Wer die App – **auch als gehosteten Webdienst** – betreibt, muss den Quellcode der
  eingesetzten Version zugänglich machen (die „Network-Use“-Klausel der AGPL).

## Betrachtete Alternativen

- **Permissiv (MIT/Apache-2.0):** erlaubt geschlossene Forks und gehostete Dienste
  ohne Offenlegung – widerspricht dem Ziel der dauerhaften Offenheit.
- **GPL-3.0 (ohne „Affero“):** greift nicht beim reinen Hosting (SaaS-Lücke).
- **Proprietär/keine Lizenz:** widerspricht dem genossenschaftlichen Gedanken.

## Konsequenzen

**Positiv**
- Die Lösung bleibt offen – auch Betreiber gehosteter Varianten müssen ihren Stand
  teilen.
- Klarer rechtlicher Rahmen für Weitergabe und Mitwirkung.

**Negativ**
- Die AGPL kann Dritte abschrecken, die eine geschlossene Nutzung anstreben.
- Eingebundene Abhängigkeiten müssen lizenzkompatibel bleiben.
