# 0042 – Rechtstexte: Impressum, Datenschutz und AGB konfigurierbar

## Status

Accepted (2026-06-27)

> **Kein Rechtsrat.** Die konkreten Texte (v. a. Datenschutz/AGB) muss die
> Genossenschaft inhaltlich verantworten, ggf. mit anwaltlicher Prüfung.

## Kontext

Die App hat einen **öffentlichen** Bereich (externe Gäste-Buchung unter `/extern/`,
ADR 0023) und ist damit ein geschäftsmäßiges Online-Angebot. Daraus folgen rechtliche
Pflichten:

- **Impressum:** für geschäftsmäßige Online-Dienste **gesetzlich verpflichtend**
  (§5 DDG, vormals §5 TMG) und von **jeder** Seite leicht erreichbar.
- **Datenschutzerklärung:** nach **DSGVO Art. 13** ebenfalls **verpflichtend**
  (Verarbeitung personenbezogener Daten: Mitglieder, Gäste, Zahlungen).
- **AGB:** **nicht** zwingend vorgeschrieben, aber bei Beherbergung/Storno dringend
  empfohlen (Vertrags-/Stornobedingungen; die Storno-Staffel steht bereits in
  `ExternalConfig.terms`).

Die Texte/Stammdaten dürfen nicht im Code stehen – die Genossenschaft muss sie selbst
pflegen können.

## Entscheidung

**Konfigurierbare Rechtstexte** + öffentliche Seiten, im Seiten-Fuß verlinkt.

- **Stammdaten/Texte** liegen im Singleton `shop.ShopConfig` (dort, wo bereits
  Name/Anschrift/Steuernummer/Kontakt stehen, ADR 0034): neue Felder `vat_id`,
  `register_court`, `register_number`, `imprint_extra`, `privacy_policy`, `terms_agb`.
- **Impressum** wird aus den strukturierten Feldern **erzeugt** (`coop_name`,
  `coop_address`, `board` = vertretungsberechtigter Vorstand, `tax_number`/`vat_id`,
  Registergericht/-nummer, Kontakt) – keine Doppelpflege; optionaler `imprint_extra`.
- **Öffentliche Views** (ohne Login): `imprint` (`/impressum/`), `privacy`
  (`/datenschutz/`), `terms` (`/agb/`). Erreichbar auch für eingeloggte, noch nicht
  freigeschaltete Konten (Allowlist in `ActivationGateMiddleware`).
- **Fuß auf jeder Seite** (`base.html` + Context-Processor `legal`): Impressum
  **immer**; Datenschutz/AGB nur, wenn gepflegt; Kontakt-Mail. Da die externen Seiten
  `base.html` erweitern, erscheint der Fuß auch im öffentlichen Bereich.
- Die Texte werden **escaped** ausgegeben (Plain-Text mit Zeilenumbrüchen, ADR 0039);
  kein eingebettetes HTML/JS.

## Betrachtete Alternativen

- **Statische Templates mit festem Text:** die Genossenschaft könnte nichts ändern;
  jede Anpassung wäre ein Release.
- **Eigenes `LegalPage`-Modell (slug/body):** flexibler für beliebig viele Seiten,
  aber für drei feste Seiten Overhead; das Impressum bräuchte trotzdem die Stammdaten.
- **Rich-Text/Markdown mit HTML-Ausgabe:** komfortabler, aber XSS-Fläche; bewusst auf
  escaptes Plain-Text beschränkt (kann später mit Sanitizer erweitert werden).

## Konsequenzen

**Positiv**
- Pflichtangaben (Impressum/Datenschutz) vorhanden und von jeder Seite erreichbar.
- Texte/Stammdaten ohne Release pflegbar; Impressum ohne Doppelpflege erzeugt.

**Negativ / Zu beachten**
- Die **inhaltliche Richtigkeit/Vollständigkeit** (v. a. Datenschutz/AGB) liegt bei
  der Genossenschaft – das System liefert nur die Hülle.
- Nur Plain-Text (keine Formatierung/Verlinkung im Fließtext) – bewusst, gegen XSS.
- Ein leeres Impressum zeigt einen Hinweis; vor Go-Live müssen die Felder gepflegt
  sein.
