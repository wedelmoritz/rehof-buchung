# 0048 – uv als Entwickler-Werkzeug und mypy auf der reinen Logik

## Status

Accepted (2026-06-27)

## Kontext

Das Projekt ist eine Python/Django-App; Abhängigkeiten standen bisher nur in
`requirements.txt`. Aus dem Review kamen zwei Wünsche: **uv** als schnelleres,
reproduzierbares Werkzeug für Abhängigkeiten/venv, und ein **Type-Checker**. Ein
Sprachwechsel (statisch typisierte Sprache) wäre für ein kleines, ehrenamtlich
betriebenes Projekt unverhältnismäßig – uv + Typprüfung holen den Großteil des
Nutzens (schnelleres Setup, frühe Fehler) bei kleinem Aufwand.

## Entscheidung

**uv** wird als Entwickler-Werkzeug eingeführt, **ohne die Build-Kette anzufassen**:

- `pyproject.toml` (PEP 621) ist die **Quelle** für Abhängigkeiten + Werkzeug-
  Konfiguration; `uv.lock` pinnt die Versionen reproduzierbar. Lokal:
  `uv sync --extra dev --extra test`, `uv run …`.
- Das **Docker-Image installiert weiter aus `requirements.txt`** (gleiche
  Top-Level-Pins). Bewusst unverändert, um die produktive Build-/Deploy-Kette
  nicht zu riskieren. Beide Listen sind synchron zu halten (kleiner, akzeptierter
  Wartungspunkt; Alternative siehe unten).

**Type-Checking mit mypy**, **bewusst auf die Django-freie reine Logik beschränkt**
(`booking/lottery|availability|rules|validation|external|beds24|fairness.py`,
ADR 0002): diese Module sind gut typisiert und ohne ORM-Dynamik – dort fängt mypy
**echte** Fehler statt Framework-Fehlalarme. Konfiguration in `pyproject.toml`
(moderate Flags: `check_untyped_defs`, `no_implicit_optional`, `warn_unused_ignores`),
läuft im CI-Job „reine Logik" und ist dort **grün** (Pflicht, kein Soft-Fail).

## Betrachtete Alternativen

- **uv als alleiniges Build-Tool (auch im Image), `requirements.txt` generieren:**
  sauberer (eine Quelle), aber ein voll gepinntes, generiertes `requirements.txt`
  ändert die Image-Build-Inputs spürbar; ohne Test der Build-Kette zu riskant. Kann
  später per `uv export`/`uv pip compile` nachgezogen werden.
- **ty (Astral) statt mypy:** vom Review gewünscht und zu uv passend, aber noch
  **Alpha** – für einen verpflichtenden CI-Gate zu instabil. mypy prüft denselben
  Code; ein späterer Wechsel zu ty ist offen (gleiche reine Module).
- **mypy über die ganze Codebasis (inkl. Django):** verworfen ohne `django-stubs`
  viele Fehlalarme; mit Stubs hoher Pflegeaufwand. Der Mehrwert liegt in der reinen
  Logik – dort ist die Typprüfung streng und ruhig.
- **pyright statt mypy:** gleichwertig, bräuchte aber Node im sonst Python-reinen
  Repo. mypy bleibt im Python-Ökosystem.

## Konsequenzen

**Positiv**
- Schnelles, reproduzierbares Dev-Setup mit uv (`uv.lock`).
- Typfehler in der wertvollsten Schicht (reine Regel-Logik) werden im CI gefangen.
- Geringes Risiko: produktive Build-/Deploy-Kette unverändert.

**Negativ / Grenzen**
- **Zwei Abhängigkeitslisten** (`pyproject.toml` + `requirements.txt`) müssen synchron
  bleiben – dokumentiert; spätere Vereinheitlichung über uv möglich.
- Der Service-/View-Layer ist (noch) nicht typgeprüft – bewusste Scope-Grenze; bei
  Bedarf schrittweise mit `django-stubs` erweiterbar.
