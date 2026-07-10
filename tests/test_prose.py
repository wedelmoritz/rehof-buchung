"""Prosa-Qualität der Hilfe-/Erklärtexte: **Verständlichkeit & Prägnanz**.

Läuft in der schnellen `tests/`-Suite (ohne DB) → **bei jedem Commit** (lokal + CI).
Prüft die redaktionell gepflegten Hilfe-Texte (`booking/help_content/*.md`, ADR 0093)
gegen messbare Leitplanken (Satzlänge, Wiener Sachtextformel, Jargon-Sperrliste;
Details in `tests/prose_lint.py`). Neue/geänderte Hilfetexte müssen die Grenzen
einhalten – das hält sie kurz, prägnant und verständlich.

Die Grenzen sind bewusst konservativ und an den Bestand kalibriert; zum Verschärfen
einfach die `LIMITS` senken (und Texte anpassen).
"""
from __future__ import annotations

import glob
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))       # tests/ auf den Pfad (Support-Modul)
from prose_lint import Limits, analyze, check        # noqa: E402

# Kalibriert am Bestand: kurze Sätze, gute Lesbarkeit.
LIMITS = Limits(max_sentence_words=32, avg_sentence_words=22.0, wstf_max=12.0)

_HELP_GLOB = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "booking", "help_content", "*.md")
_HELP_FILES = sorted(glob.glob(_HELP_GLOB))


def test_help_content_dateien_vorhanden():
    assert _HELP_FILES, "Keine Hilfe-Texte gefunden – Pfad/Glob prüfen."


@pytest.mark.parametrize("path", _HELP_FILES, ids=[os.path.basename(p) for p in _HELP_FILES])
def test_hilfetext_verstaendlich_und_praegnant(path):
    text = open(path, encoding="utf-8").read()
    issues = check(os.path.basename(path), text, LIMITS)
    assert not issues, "Prosa-Leitplanken verletzt:\n  " + "\n  ".join(issues)


def test_linter_kernfunktionen_deterministisch():
    # Abkürzungen zerlegen den Satz NICHT fälschlich.
    assert analyze("Das gilt z. B. für dich und mich.").n_sentences == 1
    # Zwei echte Sätze werden getrennt; langer Satz wird als lang erkannt.
    m = analyze("Kurz. " + "wort " * 40 + "ende.")
    assert m.n_sentences == 2
    assert m.max_sentence_words >= 40
    # Jargon-Sperrliste greift.
    assert any("Membership" in i for i in check("x", "Die Membership ist wichtig."))
