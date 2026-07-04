"""Schutz vor geleakten Template-Kommentaren.

Djangos Template-Lexer erkennt `{# … #}` über `tag_re` **ohne** `re.DOTALL` – ein
über mehrere Zeilen gehender `{# … #}`-Kommentar wird daher NICHT als Kommentar-
Token erkannt und erscheint als **sichtbarer Text** im gerenderten HTML.

Mehrzeilige Erklärungen müssen deshalb als `{% comment %}…{% endcomment %}`
geschrieben werden (oder als mehrere einzeilige `{# … #}`). Dieser Test wacht
darüber – er scannt ALLE Templates und schlägt fehl, sobald ein `{# … #}`-Span
einen Zeilenumbruch enthält.
"""
from __future__ import annotations

import re
from pathlib import Path

# Repo-Wurzel = zwei Ebenen über dieser Datei (tests/ liegt im Projektroot).
ROOT = Path(__file__).resolve().parent.parent

# `{# … #}` nicht-gierig, über Zeilen hinweg (DOTALL) – genau das, was Django NICHT
# als Kommentar erkennt, wenn ein Umbruch drinsteht.
_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)


def _template_files() -> list[Path]:
    return [
        p
        for p in ROOT.glob("**/templates/**/*.html")
        if ".venv" not in p.parts and "site-packages" not in p.parts
    ]


def _leaked_comments(text: str) -> list[tuple[int, str]]:
    """(Zeilennummer, Ausschnitt) je mehrzeiligem {# … #}-Kommentar."""
    out = []
    for m in _COMMENT.finditer(text):
        if "\n" in m.group(0):
            line = text[: m.start()].count("\n") + 1
            snippet = m.group(0)[:60].replace("\n", "⏎")
            out.append((line, snippet))
    return out


def test_es_gibt_templates_zum_pruefen():
    # Sanity: der Glob findet überhaupt Templates (sonst wäre der Test wertlos).
    assert _template_files(), "Keine Templates gefunden – Pfad-Glob prüfen."


def test_keine_mehrzeiligen_raute_kommentare():
    """`{# … #}` darf NIE über mehrere Zeilen gehen (leakt sonst als Text)."""
    problems: list[str] = []
    for path in _template_files():
        text = path.read_text(encoding="utf-8")
        for line, snippet in _leaked_comments(text):
            rel = path.relative_to(ROOT)
            problems.append(f"{rel}:{line}  {snippet}…")
    assert not problems, (
        "Mehrzeilige {# … #}-Kommentare erscheinen als sichtbarer Text – bitte "
        "in {% comment %}…{% endcomment %} umschreiben:\n  " + "\n  ".join(problems)
    )
