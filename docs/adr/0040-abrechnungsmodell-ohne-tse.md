# 0040 – Abrechnungsmodell ohne TSE (KassenSichV / §146a AO)

## Status

Accepted (2026-06-27)

> **Kein Rechtsrat.** Diese Einschätzung stützt sich auf offizielle Quellen (s. u.),
> ersetzt aber keine steuerliche Beratung. Vor dem Produktivbetrieb sollte die
> Genossenschaft die Bewertung durch ihren Steuerberater bestätigen lassen.

## Kontext

Der Hofladen/die Buchung bietet zwei Zahlungswege (beide mit ordnungsgemäßer
Rechnung inkl. MwSt-Aufschlüsselung nach §14 UStG, siehe ADR 0016/0028):

1. **Kauf auf Rechnung** – Einkäufe werden monatlich als Sammelrechnung abgerechnet
   (`shop.Invoice`, Nummer `HL-JJJJ-MM-NNN`), Zahlung per **Überweisung** mit der
   Rechnungsnummer als Referenz (Kontoabgleich, ADR 0029).
2. **Online-Bezahlung** – direkte Zahlung über einen **Online-Zahlungsdienstleister**
   (im System: **Mollie**, ADR 0017), ebenfalls mit Rechnung.

Frage: Unterliegt das System der **Kassensicherungsverordnung (KassenSichV)** und
braucht es eine zertifizierte **technische Sicherheitseinrichtung (TSE)** nach
§146a AO?

## Entscheidung

Das System wird **ohne TSE** betrieben. Beide Zahlungswege sind so gestaltet, dass
**keine Kassenfunktion** im Sinne der KassenSichV entsteht.

### Begründung (rechtliche Analyse)

**Wann greift die TSE-Pflicht?** Die KassenSichV (seit 01.01.2020) verlangt eine
zertifizierte TSE, wenn ein elektronisches Aufzeichnungssystem eine **Kassenfunktion**
hat. Laut AEAO zu §146a Nr. 1.2 liegt eine Kassenfunktion vor, wenn das System „der
Erfassung und Abwicklung von zumindest teilweise baren Zahlungsvorgängen" dient –
einschließlich „vergleichbarer elektronischer, **vor Ort** genutzter Zahlungsformen"
(Geldkarten, virtuelle Konten, Gutscheine). Entscheidend ist das Kriterium
**„vor Ort"** – die physische Anwesenheit der Kundin beim Bezahlvorgang.

**Zahlungsweg 1 (Rechnung/Überweisung):** Kein Zahlungsvorgang vor Ort. Das Mitglied
**erfasst nur seinen Einkauf** in der App; bezahlt wird zeitversetzt per Banküberweisung.
Es werden keine baren/bargeldähnlichen Zahlungen erfasst – funktional eine
**Warenwirtschaft/Bestellerfassung**, kein Kassensystem. „Ein Warenwirtschaftssystem
ohne Kassenmodul unterliegt nicht dem Anwendungsbereich des §146a Abs. 1 Satz 1 AO."

**Zahlungsweg 2 (Online via Mollie):** „Grundsätzlich muss ein elektronisches
Aufzeichnungssystem in einem Webshop nicht mit einer TSE abgesichert werden,
unabhängig von der Zahlungsform, da in einem Webshop **keine Zahlung vor Ort**
stattfinden kann" (ZDH-Handreichung Kassenführung). Auch wenn der Einkauf physisch
im Laden erfolgt, läuft die **Zahlungsabwicklung vollständig online** über den
Dienstleister, auf dem **eigenen Gerät** der Kundin – nicht über ein Laden-Kassensystem.
Das Argument gilt **PSP-unabhängig** (Mollie, PayPal o. a.).

## Betrachtete Alternativen

- **TSE einbauen (Hardware- oder Cloud-TSE):** ~100–300 €/Jahr + Einrichtung,
  Meldepflicht, DSFinV-K-Export – ohne TSE-pflichtige Kassenfunktion unnötig.
- **Vor-Ort-POS-Terminal (z. B. PayPal Zettle, Karten-/Bargeld-Annahme im Laden):**
  **wäre** TSE-pflichtig – bewusst **nicht** Teil des Systems. Die App ist
  Bestellerfassung/Warenwirtschaft, kein POS.

## Konsequenzen

**Positiv**
- Kein Bedarf an TSE-Hardware/Cloud-TSE-Abo; keine Meldepflicht nach §146a Abs. 4 AO;
  keine DSFinV-K-Exportpflicht; keine Belegausgabepflicht nach KassenSichV
  (ordnungsgemäße Rechnungen werden dennoch erstellt).
- Deutlich geringere technische Komplexität.

**Zu beachten / Negativ**
- **GoBD gilt unabhängig:** Geschäftsvorfälle vollständig, richtig, zeitnah,
  unveränderbar aufzeichnen.
- Rechnungen brauchen die Pflichtangaben nach §14 UStG bzw. den §19-Hinweis (siehe
  ADR 0041).
- **Erweiterungs-Trigger:** Wird künftig **Bargeld oder Kartenzahlung vor Ort**
  ergänzt, ist die TSE-Frage neu zu bewerten.
- **Risiko bei Fehleinschätzung:** Verstöße gegen die KassenSichV können nach §379 AO
  mit bis zu **25.000 €** geahndet werden. Das Risiko wird als gering eingeschätzt
  (Webshop/keine Vor-Ort-Zahlung), eine steuerliche Bestätigung wird dennoch empfohlen.

## Quellen

1. BMF, FAQ „Das Kassengesetz für mehr Steuergerechtigkeit" –
   bundesfinanzministerium.de (FAQ Steuergerechtigkeit/Belegpflicht).
2. ZDH-Handreichung „Kassenführung" (Fachbereich Steuern und Finanzen) – enthält die
   Klarstellung zu Webshops und Warenwirtschaftssystemen.
3. BSI – Technische Sicherheitseinrichtung (bsi.bund.de).
4. KassenSichV – Verordnung zu den technischen Anforderungen an elektronische
   Aufzeichnungs-/Sicherungssysteme.
5. §146a AO; AEAO zu §146a; §379 AO.
