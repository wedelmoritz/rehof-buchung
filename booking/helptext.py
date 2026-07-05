"""Reine Logik: ein winziger, **sicherer** Markup-Renderer für ausgelagerte
Hilfetexte (ADR 0093).

Django-frei (im pytest-Suite `tests/` prüfbar). **Sicherheit zuerst:** der Eingabe-
text wird ZUERST vollständig HTML-escaped, danach werden nur wenige, von uns
kontrollierte Formatierungen wieder eingesetzt (Absätze, Zwischenüberschriften,
Aufzählungen, Fett, Links). So kann aus dem Textinhalt **kein** HTML/JS entstehen
(kein `<script>`, keine Event-Handler) – passend zur strikten CSP.

Operationswerte (Preise/Fristen) werden über `string.Template.safe_substitute`
eingesetzt (keine Template-Engine → kein SSTI); der Wert wird ebenfalls escaped.

Unterstützte Syntax (bewusst minimal):
- Leerzeile trennt Blöcke.
- Block, dessen Zeilen alle mit ``- `` beginnen → Aufzählung (`<ul><li>`).
- Block, der mit ``## `` beginnt → Zwischenüberschrift (`<h3>`).
- Sonst → Absatz (`<p>`); einfache Zeilenumbrüche werden zu `<br>`.
- Inline: ``**fett**`` → `<strong>`, ``[Text](ziel)`` → `<a href>` – nur mit
  erlaubtem Ziel (``/…`` intern, ``https://…`` oder ``mailto:…``).
"""
from __future__ import annotations

import re
from string import Template

__all__ = ["render_markup"]

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def _escape(text: str) -> str:
    """HTML-Sonderzeichen neutralisieren (wie Djangos escape, aber Django-frei)."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&#x27;"))


def _safe_href(target: str) -> str | None:
    """Nur erlaubte Ziele: interne Pfade/Anker, https-URLs, mailto. Sonst None."""
    t = target.strip()
    if (t.startswith("/") or t.startswith("#") or t.startswith("https://")
            or t.startswith("mailto:")):
        # Keine Anführungszeichen/Whitespace im href (bereits escaped, aber sicher).
        if '"' not in t and " " not in t and "\n" not in t:
            return t
    return None


def _inline(escaped: str) -> str:
    """Inline-Formatierung auf bereits **escaptem** Text: Links, dann Fett."""
    def link(m):
        text, target = m.group(1), m.group(2)
        # target wurde mit-escaped (z.B. & → &amp;) – für die Prüfung zurücknehmen.
        raw = (target.replace("&amp;", "&").replace("&#x27;", "'")
                     .replace("&quot;", '"'))
        href = _safe_href(raw)
        if href is None:
            return text                       # ungültiges Ziel → nur der Text
        return f'<a href="{_escape(href)}">{text}</a>'
    out = _LINK_RE.sub(link, escaped)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    return out


def render_markup(text: str, context: dict | None = None) -> str:
    """Rendert den ausgelagerten Hilfetext zu **sicherem** HTML (siehe Modul-Doku).
    `context` füllt `$variable`-Platzhalter (safe_substitute, kein SSTI)."""
    raw = text or ""
    if context:
        # Werte als str; die Ersetzung passiert VOR dem Escapen, sodass auch die
        # eingesetzten Werte escaped werden.
        raw = Template(raw).safe_substitute(
            {k: str(v) for k, v in context.items()})
    blocks = re.split(r"\n[ \t]*\n", raw.strip())
    html_parts: list[str] = []
    for block in blocks:
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = [ln for ln in block.split("\n")]
        if all(ln.strip().startswith("- ") for ln in lines if ln.strip()):
            items = "".join(
                f"<li>{_inline(_escape(ln.strip()[2:].strip()))}</li>"
                for ln in lines if ln.strip())
            html_parts.append(f"<ul>{items}</ul>")
        elif block.strip().startswith("## "):
            html_parts.append(f"<h3>{_inline(_escape(block.strip()[3:].strip()))}</h3>")
        else:
            body = "<br>".join(_inline(_escape(ln)) for ln in lines)
            html_parts.append(f"<p>{body}</p>")
    return "".join(html_parts)
