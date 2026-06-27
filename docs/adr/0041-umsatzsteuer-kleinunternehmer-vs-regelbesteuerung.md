# 0041 – Umsatzsteuer: Kleinunternehmer (§19) vs. Regelbesteuerung

## Status

Proposed (2026-06-27) – erfordert Klärung durch die Genossenschaft und ihren
Steuerberater, bevor das System produktiv geht.

> **Kein Rechtsrat.** Analyse auf Basis offizieller Quellen (s. u.); ersetzt keine
> steuerliche Beratung.

## Kontext

Das System erzeugt Rechnungen für zwei Leistungsarten:
1. **Hofladen** – Verkauf von Waren (Lebensmittel/Hofprodukte) an **Mitglieder**.
2. **Unterkunftsbuchungen** – kurzfristige Vermietung von Quartieren, auch an
   **externe Gäste** (ADR 0023).

Frage: Ob und in welcher Höhe **Umsatzsteuer** auf den Rechnungen auszuweisen und
abzuführen ist.

**Stand im Code (Regelbesteuerung):** Heute rechnet das System **immer mit MwSt**:
je Artikel/Dienstleistung ein `vat_rate` (`shop.Product.vat_rate`, Default 7 %,
Auswahl 7/19), je Rechnungsposition `LineItem.vat_rate`, die `Invoice` weist die
**Steuer-Aufschlüsselung je Satz** aus (Netto/Steuer/Brutto, §14 UStG; PDF
`shop/pdf.py` / `invoice_pdf.html`). Externe Übernachtung vs. Zusatzleistung sind
über `ExternalConfig.stay_vat` (7 %) und `cleaning_vat` (19 %) getrennt. Ein
**Kleinunternehmer-Modus (§19)** ist **noch nicht** umgesetzt.

## Analyse

1. **eG ist umsatzsteuerlich ein Unternehmen** (§1 Abs. 1 UStG). Verkäufe an
   Mitglieder sind **keine** steuerfreien Innenumsätze – Genossenschaft und Mitglied
   sind getrennte Rechtssubjekte. „Mitglieder-only" begründet **keine** Befreiung.
2. **Kleinunternehmerregelung (§19 UStG, ab 01.01.2025):** Vorjahresumsatz ≤
   **25.000 €** netto **und** laufendes Jahr ≤ **100.000 €** → Umsätze steuerbefreit.
   Überschreiten der 100.000-€-Grenze beendet die Befreiung sofort ab dem Umsatz
   („Fallbeileffekt"). Dann **kein** MwSt-Ausweis, Pflichthinweis „Gemäß §19 UStG von
   der Umsatzsteuer befreit", **kein** Vorsteuerabzug. **Achtung §14c UStG:** Wird
   irrtümlich MwSt ausgewiesen, schuldet die eG sie trotzdem.
3. **Steuersätze bei Regelbesteuerung:** Lebensmittel **7 %** (§12 Abs. 2 Nr. 1 +
   Anlage 2), Non-Food/Dienstleistungen **19 %**; kurzfristige Beherbergung **7 %**
   (§12 Abs. 2 Nr. 11), Zusatzleistungen (Reinigung, Frühstück, Sauna …) **19 %**
   (separat auf der Rechnung); langfristige Vermietung > 6 Monate **steuerfrei**
   (§4 Nr. 12a) – hier nicht einschlägig.

**Maßgebliche Frage an die Genossenschaft:** Wie hoch ist der Gesamtumsatz (Hofladen
+ Unterkünfte + Sonstiges)? Unter 25.000 €/Jahr → §19, **kein** MwSt-Ausweis.

## Entscheidung

Das System muss **beide Szenarien** abbilden, gesteuert über eine **globale
Einstellung** „Kleinunternehmer ja/nein" (umschaltbar bei Überschreiten der Grenze,
ohne Umbau):

- **Szenario A – Kleinunternehmerin (§19):** Rechnungen **ohne** MwSt-Ausweis,
  Pflichthinweis „Gemäß §19 UStG von der Umsatzsteuer befreit", kein Steuersatz-Feld
  auf der Rechnung. **→ noch umzusetzen** (Schalter + zweiter Rechnungsmodus).
- **Szenario B – Regelbesteuerung:** Rechnungen mit korrektem MwSt-Ausweis je Satz;
  Beherbergung (7 %) und Zusatzleistungen (19 %) getrennt; Aufschlüsselung Netto je
  Satz, Steuerbetrag, Brutto. **→ bereits umgesetzt** (s. „Stand im Code").

## Betrachtete Alternativen

- **Nur Regelbesteuerung fest verdrahten:** unflexibel; wäre bei Kleinunternehmer-
  Status falsch (unzulässiger Ausweis → §14c-Haftung).
- **MwSt nie ausweisen:** falsch, sobald die eG regelbesteuert ist.
- **Schalter konfigurierbar (gewählt):** deckt beide Status ab; ein
  `ShopConfig`-Flag (`small_business`/„Kleinunternehmer") + Rechnungsmodus genügt.

## Konsequenzen

**Positiv**
- Das `vat_rate`-Feld im Produktmodell bleibt; es wird nur in Szenario B auf der
  Rechnung gezeigt. Datenmodell muss nicht umgebaut werden.

**Negativ / Zu beachten**
- Die Rechnungsvorlage braucht **zwei Modi** (mit/ohne MwSt) inkl. §19-Hinweis – in
  Szenario A noch zu bauen.
- **Kritisch vor Go-Live:** Die eG muss ihren USt-Status klären. Falscher Ausweis
  (MwSt trotz §19 → §14c; oder fehlend trotz Regelbesteuerung) hat direkte
  steuerliche Folgen.
- **Empfehlung:** Klärung mit dem Steuerberater der Genossenschaft vor Produktivbetrieb.

## Quellen

- IHK Region Stuttgart – Kleinunternehmerregelung §19 UStG; BMF-Einführungsschreiben
  zur Neuregelung ab 2025.
- BMF Amtliche Umsatzsteuer-Handausgabe 2024, Abschn. 12.16; Haufe –
  Beherbergungsleistungen.
- Gabler Wirtschaftslexikon „Innenumsätze"; Genoverband-Merkblatt zur Steuerpflicht
  von Genossenschaften.
- §1, §4 Nr. 12a, §12 Abs. 2 Nr. 1/Nr. 11, §14, §14c, §19 UStG.
